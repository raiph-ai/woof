#!/usr/bin/env python3
"""Manage the per-profile macOS user LaunchAgent for the Woof bridge (stdlib only)."""
import argparse
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional
import urllib.error
import urllib.request

import backend

OWNER = 'woof.bridge-service.v1'


class ServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    home: Path
    profile: str
    python: Path
    backend: Path
    hermes: Path
    port: int
    user_home: Path
    host: str = '127.0.0.1'
    public_url: Optional[str] = None
    allow_insecure_http: bool = False

    @property
    def label(self):
        digest = hashlib.sha256(str(self.home).encode()).hexdigest()[:12]
        return f'ai.woof.bridge.{self.profile}.{digest}'

    @property
    def path(self):
        return self.user_home / 'Library/LaunchAgents' / (self.label + '.plist')

    @property
    def logs(self):
        return self.home / 'nudge' / 'service.log'

    @property
    def args(self):
        args = [str(self.python), str(self.backend), '--hermes-home', str(self.home),
                '--profile', self.profile, '--hermes', str(self.hermes),
                '--host', self.host, '--port', str(self.port)]
        if self.public_url is not None:
            args.extend(['--public-url', self.public_url])
        if self.allow_insecure_http:
            args.append('--allow-insecure-http')
        return args

    @property
    def origin(self):
        return f'http://{self.host}:{self.port}'

    @property
    def target(self):
        return f'gui/{os.getuid()}/{self.label}'


def executable(value):
    # Do not resolve executable symlinks: a venv's Python path selects its environment.
    return Path(shutil.which(str(value)) or value).expanduser().absolute()


def configuration(args):
    home = backend.profile_home(args.hermes_home, args.profile).resolve()
    if not 1 <= args.port <= 65535:
        raise ServiceError('--port must be between 1 and 65535')
    config = Config(home, args.profile, executable(args.python),
                  Path(args.backend).expanduser().resolve(),
                  backend.discover_hermes(args.hermes), args.port, Path.home(),
                  getattr(args, 'host', '127.0.0.1'), getattr(args, 'public_url', None),
                  getattr(args, 'allow_insecure_http', False))
    validate_network(config)
    return config


def validate_network(config):
    try:
        address = ipaddress.IPv4Address(config.host)
        if address.is_unspecified or address.is_multicast or address == ipaddress.IPv4Address('255.255.255.255'):
            raise ValueError('host must be a specific unicast IPv4 literal, not a wildcard')
        if not 1 <= config.port <= 65535:
            raise ValueError('--port must be between 1 and 65535')
        backend.listener_options(config.host, config.public_url, None, None, config.allow_insecure_http)
        if not address.is_loopback and config.public_url is None:
            raise ValueError('Non-loopback HTTP requires --public-url and --allow-insecure-http')
        if config.public_url is not None and config.public_url != config.origin:
            raise ValueError('--public-url must be the exact http://HOST:PORT origin matching --host and --port')
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


def run(command, check=True):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f'Cannot execute {command[0]}: {exc}') from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ServiceError(f'{command[0]} {command[1]} failed ({result.returncode}): {detail}. '
                           'Run in your logged-in macOS user session; inspect launchctl print and the service log.')
    return result


def validate(config):
    validate_network(config)
    if not config.home.is_dir():
        raise ServiceError(f'Profile home does not exist: {config.home}; create/select the Hermes profile first')
    if not config.backend.is_file():
        raise ServiceError(f'Backend does not exist: {config.backend}')
    for name, path in [('Python', config.python), ('Hermes', config.hermes)]:
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ServiceError(f'{name} is not executable: {path}; pass an explicit path')
    run([str(config.python), '-c',
         'import sys; import zoneinfo; assert sys.version_info >= (3,9), "Python 3.9+ required"'])
    # Compile without importing/starting the backend or touching its token/database.
    run([str(config.python), '-c',
         'import pathlib,sys; p=pathlib.Path(sys.argv[1]); compile(p.read_bytes(),str(p),"exec")',
         str(config.backend)])


def document(config):
    return {'Label': config.label, 'WoofServiceOwner': OWNER,
            'WoofProfileHome': str(config.home), 'ProgramArguments': config.args,
            'WorkingDirectory': str(config.backend.parent), 'RunAtLoad': True,
            'KeepAlive': True, 'ThrottleInterval': 10, 'Umask': 0o077,
            'EnvironmentVariables': {'HOME': str(config.user_home),
                                     'HERMES_HOME': str(config.home),
                                     'HERMES_PROFILE': config.profile,
                                     'PATH': ':'.join(dict.fromkeys([
                                         str(config.user_home / '.local/bin'), str(config.python.parent),
                                         str(config.hermes.parent), '/opt/homebrew/bin', '/usr/local/bin',
                                         '/usr/bin', '/bin', '/usr/sbin', '/sbin']))},
            'StandardOutPath': str(config.logs), 'StandardErrorPath': str(config.logs)}


def installed(config):
    path = config.path
    if path.is_symlink():
        raise ServiceError(f'Refusing symlink service file: {path}')
    if not path.exists():
        return None
    try:
        data = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise ServiceError(f'Refusing unreadable/foreign service file: {path}') from exc
    if (not isinstance(data, dict) or data.get('WoofServiceOwner') != OWNER or data.get('Label') != config.label
            or data.get('WoofProfileHome') != str(config.home)):
        raise ServiceError(f'Refusing foreign service file: {path}')
    return data


def saved_config(config, data):
    try:
        args = data['ProgramArguments']
        saved = Config(config.home, config.profile, Path(args[0]), Path(args[1]),
                      Path(args[args.index('--hermes') + 1]),
                      int(args[args.index('--port') + 1]), config.user_home,
                      args[args.index('--host') + 1],
                      args[args.index('--public-url') + 1] if '--public-url' in args else None,
                      '--allow-insecure-http' in args)
        validate_network(saved)
        return saved
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise ServiceError(f'Malformed owned service file: {config.path}') from exc


def ready(config):
    validate_network(config)
    # Prove the literal is assigned here before reading/sending credentials.
    # No DNS resolution, proxies, redirects or remote readiness targets.
    try:
        with socket.socket() as sock:
            sock.bind((config.host, 0))
    except OSError as exc:
        raise ServiceError('Readiness host must be an IP assigned to this machine') from exc
    token_path = config.home / 'nudge/token'
    try:
        token = token_path.read_text().strip()
    except FileNotFoundError:
        raise ServiceError(f'Bridge token not yet created: {token_path}') from None
    except OSError as exc:
        raise ServiceError(f'Cannot read bridge token: {token_path}') from exc
    if len(token) < 32 or '\n' in token or '\r' in token:
        raise ServiceError(f'Invalid token file: {token_path}; service does not modify it')
    request = urllib.request.Request(config.origin + '/api/info',
                                     headers={'Authorization': 'Bearer ' + token})
    # Disable proxies and redirects: never forward the local token elsewhere.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=1) as response:
            data = json.loads(response.read(65536))
            if response.status != 200:
                raise ServiceError('Bridge readiness did not return HTTP 200')
    except (OSError, ValueError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        raise ServiceError(f'Authenticated /api/info failed on port {config.port}; '
                           'check service.log, token permissions, and port conflicts') from exc
    if (not isinstance(data, dict) or data.get('kind') != 'hermes-nudge'
            or data.get('protocol_version') != 1 or data.get('profile') != config.profile):
        raise ServiceError('Port answers with a different bridge/profile/protocol; check port conflicts')
    return data


def wait_ready(config, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return ready(config)
        except ServiceError as exc:
            if time.monotonic() >= deadline:
                raise ServiceError(f'{exc}. Service remains installed; inspect {config.logs}, '
                                   'then use start to retry or uninstall to remove autostart.') from exc
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def check_port(config):
    validate_network(config)
    try:
        with socket.socket() as sock:
            sock.bind((config.host, config.port))
    except OSError as exc:
        raise ServiceError(f'Port {config.port} is already in use or host {config.host} is not local; stop the foreground bridge '
                           'or choose another --port before installing/starting') from exc


def loaded(config):
    return run(['/bin/launchctl', 'print', config.target], check=False).returncode == 0


def start(config, timeout):
    validate(config)
    if loaded(config):
        # An existing healthy agent need not be restarted.
        return wait_ready(config, timeout)
    check_port(config)
    run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(config.path)])
    if not loaded(config):
        raise ServiceError('LaunchAgent was not registered; inspect launchctl print and service.log')
    return wait_ready(config, timeout)


def install(config, dry_run=False, timeout=10):
    validate(config)
    prior = installed(config)
    data = document(config)
    if prior is not None and prior != data:
        raise ServiceError('Existing owned service has different settings; uninstall it before reinstalling')
    if dry_run:
        return plistlib.dumps(data).decode()
    if prior is None:
        check_port(config)
        config.path.parent.mkdir(parents=True, exist_ok=True)
        config.logs.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive create: never clobber a foreign file appearing after preflight.
        fd = os.open(config.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(plistlib.dumps(data))
        if installed(config) != data:
            raise ServiceError('Service file verification failed')
    start(config, timeout)
    return f'Installed and authenticated: {config.label}\n{config.path}'


def uninstall(config, dry_run=False):
    data = installed(config)
    if data is None:
        return 'Not installed; token and database unchanged'
    if dry_run:
        return f'Would unload and remove {config.path}; token and database unchanged'
    if loaded(config):
        run(['/bin/launchctl', 'bootout', config.target])
        if loaded(config):
            raise ServiceError('Agent is still registered; service file retained')
    # Recheck ownership immediately before removal.
    installed(config)
    config.path.unlink()
    if config.path.exists():
        raise ServiceError('Service file removal verification failed')
    return 'Uninstalled; token, database, and logs preserved'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'status', 'start', 'uninstall'])
    parser.add_argument('--profile', default=os.environ.get('HERMES_PROFILE', 'default'))
    parser.add_argument('--hermes-home')
    parser.add_argument('--hermes')
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--backend', default=str(Path(__file__).with_name('backend.py')))
    parser.add_argument('--port', type=int, default=47831)
    parser.add_argument('--host', default='127.0.0.1', help='specific local IPv4 literal (no wildcard)')
    parser.add_argument('--public-url', help='exact http://HOST:PORT origin matching the bind')
    parser.add_argument('--allow-insecure-http', action='store_true', help='explicit trusted-network plaintext HTTP opt-in')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--dry-run', action='store_true', help='install: print plist only; uninstall: preview only')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'darwin':
            raise ServiceError('Service management is macOS-only; run backend.py in your Linux user service manager')
        if not 0 <= args.timeout <= 300:
            raise ServiceError('--timeout must be between 0 and 300 seconds')
        config = configuration(args)
        if args.dry_run and args.action not in ('install', 'uninstall'):
            raise ServiceError('--dry-run is only supported for install/uninstall')
        if args.action == 'install':
            print(install(config, args.dry_run, args.timeout))
        elif args.action == 'uninstall':
            print(uninstall(config, args.dry_run))
        else:
            data = installed(config)
            if data is None:
                if args.action == 'status':
                    ready(config)
                    print(f'Authenticated but unmanaged: profile={config.profile}; port={config.port}; '
                          'autostart is not installed. Stop the foreground bridge before install.')
                    return 0
                raise ServiceError(f'Not installed: {config.path}; run install first')
            config = saved_config(config, data)
            if args.action == 'start':
                start(config, args.timeout)
            else:
                if not loaded(config):
                    raise ServiceError(f'Installed but not loaded; run start. Log: {config.logs}')
                ready(config)
            print(f'Loaded and authenticated: {config.label}; profile={config.profile}; port={config.port}')
        return 0
    except (ServiceError, ValueError, OSError) as exc:
        print(f'bridge-service: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
