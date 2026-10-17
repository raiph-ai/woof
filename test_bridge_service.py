"""Isolated service tests: no launchctl registration or real profile writes."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import bridge_service as service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='woof-service-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'home with spaces'
        self.home = self.root / '.hermes/profiles/work-profile'
        self.home.mkdir(parents=True)
        hermes = self.root / 'hermes executable'
        hermes.write_text('#!/bin/sh\nexit 0\n')
        hermes.chmod(0o700)
        backend = self.root / 'backend fixture.py'
        backend.write_text('print("fixture")\n')
        self.config = service.Config(self.home, 'work-profile', Path(sys.executable),
                                     backend, hermes, 47832, self.root)
        self.commands = []
        self.is_loaded = False

    def fake_run(self, command, check=True):
        self.commands.append(command)
        action = command[1]
        if action == 'bootstrap':
            self.is_loaded = True
        elif action == 'bootout':
            self.is_loaded = False
        code = int(action == 'print' and not self.is_loaded)
        return subprocess.CompletedProcess(command, code, '', '')

    def write_service(self):
        self.config.path.parent.mkdir(parents=True, exist_ok=True)
        self.config.path.write_bytes(plistlib.dumps(service.document(self.config)))

    def test_validation_real_python_and_fixture_paths(self):
        service.validate(self.config)
        for field in ('python', 'hermes', 'backend', 'home'):
            with self.subTest(field=field), self.assertRaises(service.ServiceError):
                service.validate(replace(self.config, **{field: self.root / 'absent'}))

    def test_dry_run_spaces_profile_no_writes_or_commands(self):
        with patch.object(service, 'run', side_effect=self.fake_run):
            data = plistlib.loads(service.install(self.config, dry_run=True).encode())
        self.assertEqual(data['ProgramArguments'], self.config.args)
        self.assertEqual(data['EnvironmentVariables']['HERMES_HOME'], str(self.home))
        self.assertTrue(data['KeepAlive'])
        self.assertTrue(data['RunAtLoad'])
        self.assertNotIn('token', json.dumps(data).lower())
        self.assertFalse(self.config.path.exists())
        self.assertFalse((self.home / 'nudge').exists())
        self.assertFalse(any('/bin/launchctl' in c for c in self.commands))
        self.assertNotEqual(self.config.label, replace(self.config, profile='other').label)
        self.assertNotEqual(self.config.label, replace(self.config, home=self.root).label)

    def test_install_idempotence_uninstall_preserves_data(self):
        data = self.home / 'nudge'
        data.mkdir()
        token = data / 'token'
        db = data / 'companion.sqlite3'
        token.write_text('secret' * 8)
        db.write_bytes(b'existing-db')
        with patch.object(service, 'run', side_effect=self.fake_run), \
                patch.object(service, 'check_port'), patch.object(service, 'ready', return_value={}) as ready:
            service.install(self.config)
            service.install(self.config)
            self.assertEqual(ready.call_count, 2)
            self.assertEqual(sum(c[1] == 'bootstrap' for c in self.commands), 1)
            self.assertEqual(service.installed(self.config), service.document(self.config))
            service.uninstall(self.config)
            self.assertFalse(self.config.path.exists())
            self.assertFalse(self.is_loaded)
        self.assertEqual(token.read_text(), 'secret' * 8)
        self.assertEqual(db.read_bytes(), b'existing-db')

    def test_lan_cli_dry_run_and_saved_settings(self):
        with patch.object(service.sys, 'platform', 'darwin'), \
                patch.object(service.Path, 'home', return_value=self.root), \
                patch.object(service, 'run', side_effect=self.fake_run), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            result = service.main(['install', '--dry-run', '--profile', self.config.profile,
                                   '--hermes-home', str(self.home), '--hermes', str(self.config.hermes),
                                   '--backend', str(self.config.backend), '--port', '47832',
                                   '--host', '10.0.0.2', '--public-url', 'http://10.0.0.2:47832',
                                   '--allow-insecure-http'])
        self.assertEqual(result, 0)
        data = plistlib.loads(output.getvalue().encode())
        saved = service.saved_config(replace(self.config, home=self.home.resolve()), data)
        self.assertEqual(saved.host, '10.0.0.2')
        self.assertEqual(saved.public_url, 'http://10.0.0.2:47832')
        self.assertTrue(saved.allow_insecure_http)
        self.assertEqual(saved.args, data['ProgramArguments'])
        self.assertFalse(self.config.path.exists())
        self.assertFalse((self.home / 'nudge').exists())
        self.assertFalse(any(c[0] == '/bin/launchctl' for c in self.commands))

    def test_explicit_path_without_inherited_environment(self):
        config = replace(self.config, python=self.root / 'python bin/python3',
                         hermes=self.root / 'hermes bin/hermes')
        with patch.dict(os.environ, {'PATH': '/untrusted/bin', 'SECRET': 'do-not-copy'}):
            environment = service.document(config)['EnvironmentVariables']
        self.assertEqual(environment['PATH'].split(':'), [
            str(self.root / '.local/bin'), str(config.python.parent), str(config.hermes.parent),
            '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'])
        self.assertEqual(set(environment), {'HOME', 'HERMES_HOME', 'HERMES_PROFILE', 'PATH'})

    def test_network_validation_rejects_unsafe_inputs(self):
        trusted = replace(self.config, host='10.0.0.2', public_url='http://10.0.0.2:47832',
                          allow_insecure_http=True)
        service.validate_network(trusted)
        invalid = [replace(trusted, allow_insecure_http=False), replace(trusted, public_url=None)]
        invalid.extend(replace(trusted, host=host) for host in (
            'localhost', 'bridge.example', '0.0.0.0', '::', '::1', '*', '224.0.0.1', '255.255.255.255'))
        invalid.extend(replace(trusted, public_url=url) for url in (
            'https://10.0.0.2:47832', 'http://10.0.0.3:47832', 'http://10.0.0.2:47833',
            'http://10.0.0.2', 'http://user:pass@10.0.0.2:47832', 'http://10.0.0.2:47832/',
            'http://10.0.0.2:47832/api/info', 'http://10.0.0.2:47832?x=1',
            'http://10.0.0.2:47832#x', 'http://10.0.0.2:47832?', 'http://10.0.0.2:47832#'))
        for config in invalid:
            with self.subTest(host=config.host, url=config.public_url, opt_in=config.allow_insecure_http), \
                    patch.object(service.urllib.request, 'build_opener') as opener, \
                    self.assertRaises(service.ServiceError):
                service.ready(config)
            opener.assert_not_called()
        data = service.document(trusted)
        data['ProgramArguments'].remove('--allow-insecure-http')
        with self.assertRaises(service.ServiceError):
            service.saved_config(self.config, data)

    def test_readiness_and_port_use_configured_host(self):
        config = replace(self.config, host='127.0.0.2', public_url='http://127.0.0.2:47832',
                         allow_insecure_http=True)
        data = self.home / 'nudge'
        data.mkdir()
        (data / 'token').write_text('fixture-token-' * 4)
        payload = {'kind': 'hermes-nudge', 'protocol_version': 1, 'profile': config.profile}
        with patch.object(service.socket, 'socket') as socket_factory, \
                patch.object(service.urllib.request, 'build_opener') as factory:
            response = factory.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps(payload).encode()
            self.assertEqual(service.ready(config), payload)
            request = factory.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.2:47832/api/info')
            socket_factory.return_value.__enter__.return_value.bind.assert_called_with(('127.0.0.2', 0))
            service.check_port(config)
            socket_factory.return_value.__enter__.return_value.bind.assert_called_with(('127.0.0.2', 47832))

    def test_nonlocal_readiness_refused_before_token_or_request(self):
        config = replace(self.config, host='10.0.0.2', public_url='http://10.0.0.2:47832',
                         allow_insecure_http=True)
        with patch.object(service.socket, 'socket') as factory, \
                patch.object(service.Path, 'read_text') as read, \
                patch.object(service.urllib.request, 'build_opener') as opener:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError('not local')
            with self.assertRaisesRegex(service.ServiceError, 'assigned to this machine'):
                service.ready(config)
            read.assert_not_called()
            opener.assert_not_called()

    def test_foreign_files_and_symlinks_refused(self):
        self.config.path.parent.mkdir(parents=True)
        for payload in (b'foreign text', plistlib.dumps({'Label': self.config.label}), plistlib.dumps([])):
            self.config.path.write_bytes(payload)
            with self.assertRaises(service.ServiceError):
                service.uninstall(self.config)
            with patch.object(service, 'validate'), self.assertRaises(service.ServiceError):
                service.install(self.config)
            self.assertEqual(self.config.path.read_bytes(), payload)
        self.config.path.unlink()
        target = self.root / 'foreign'
        target.write_text('untouched')
        self.config.path.symlink_to(target)
        with self.assertRaises(service.ServiceError):
            service.uninstall(self.config)
        self.assertEqual(target.read_text(), 'untouched')

    def test_changed_settings_require_uninstall(self):
        self.write_service()
        with patch.object(service, 'validate'), self.assertRaisesRegex(service.ServiceError, 'different settings'):
            service.install(replace(self.config, port=47833))
        saved = service.saved_config(replace(self.config, port=9999), service.installed(self.config))
        self.assertEqual(saved.port, 47832)

    def test_port_conflict_before_write(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            config = replace(self.config, port=listener.getsockname()[1])
            with patch.object(service, 'validate'), self.assertRaisesRegex(service.ServiceError, 'already in use'):
                service.install(config)
            self.assertFalse(config.path.exists())

    def test_readiness_failure_keeps_owned_file_for_diagnosis(self):
        with patch.object(service, 'run', side_effect=self.fake_run), patch.object(service, 'check_port'), \
                patch.object(service, 'ready', side_effect=service.ServiceError('authentication failed')):
            with self.assertRaisesRegex(service.ServiceError, 'remains installed'):
                service.install(self.config, timeout=0)
        self.assertTrue(self.config.path.exists())

    def test_bootstrap_error_actionable_and_file_retained(self):
        def fail(command, check=True):
            if command[1] == 'bootstrap':
                raise service.ServiceError('bootstrap denied: logged-in user session required')
            return self.fake_run(command, check)
        with patch.object(service, 'run', side_effect=fail), patch.object(service, 'check_port'):
            with self.assertRaisesRegex(service.ServiceError, 'bootstrap denied'):
                service.install(self.config)
        self.assertTrue(self.config.path.exists())

    def test_command_failure_contains_actionable_detail(self):
        with patch.object(service.subprocess, 'run', return_value=subprocess.CompletedProcess([], 5, '', 'denied')):
            with self.assertRaisesRegex(service.ServiceError, 'denied.*logged-in'):
                service.run(['/bin/launchctl', 'bootstrap'])

    def test_uninstall_failed_unload_retains_file(self):
        self.write_service()
        with patch.object(service, 'loaded', return_value=True), patch.object(service, 'run'):
            with self.assertRaisesRegex(service.ServiceError, 'still registered'):
                service.uninstall(self.config)
        self.assertTrue(self.config.path.exists())

    def test_profile_resolution_and_invalid_names(self):
        parser = service.argparse.Namespace(hermes_home=str(self.home), profile='work-profile', port=47832,
                                          python=sys.executable, backend=str(self.config.backend),
                                          hermes=str(self.config.hermes))
        self.assertEqual(service.configuration(parser).home, self.home.resolve())
        parser.profile = '../default'
        with self.assertRaises(ValueError):
            service.configuration(parser)

    def test_authenticated_real_http_readiness(self):
        data = self.home / 'nudge'
        data.mkdir()
        token = 'private-test-token-' * 3
        (data / 'token').write_text(token)
        received = []
        payload = {'kind': 'hermes-nudge', 'protocol_version': 1, 'profile': self.config.profile}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path, self.headers.get('Authorization')))
                self.send_response(200 if self.headers.get('Authorization') == 'Bearer ' + token else 401)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
            def log_message(self, format, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = replace(self.config, port=server.server_port)
        self.assertEqual(service.ready(config), payload)
        self.assertEqual(received[-1], ('/api/info', 'Bearer ' + token))
        payload['profile'] = 'foreign'
        with self.assertRaisesRegex(service.ServiceError, 'different bridge'):
            service.ready(config)
        payload['profile'] = config.profile
        (data / 'token').write_text('wrong-token-' * 4)
        with self.assertRaisesRegex(service.ServiceError, 'Authenticated /api/info failed'):
            service.ready(config)

    def test_status_unmanaged_and_managed(self):
        with patch.object(service.sys, 'platform', 'darwin'), \
                patch.object(service, 'configuration', return_value=self.config), \
                patch.object(service, 'ready', return_value={}), \
                patch.object(service, 'run', side_effect=self.fake_run), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(service.main(['status']), 0)
            self.assertIn('unmanaged', output.getvalue())
            self.assertFalse(self.commands)
            self.write_service()
            self.is_loaded = True
            output.truncate(0)
            output.seek(0)
            self.assertEqual(service.main(['status']), 0)
            self.assertIn('Loaded and authenticated', output.getvalue())
            self.assertFalse(any(c[1] == 'bootstrap' for c in self.commands))

    def test_status_and_start_reconstruct_saved_network(self):
        trusted = replace(self.config, host='10.0.0.2', public_url='http://10.0.0.2:47832',
                          allow_insecure_http=True)
        self.config.path.parent.mkdir(parents=True)
        self.config.path.write_bytes(plistlib.dumps(service.document(trusted)))
        with patch.object(service.sys, 'platform', 'darwin'), \
                patch.object(service, 'configuration', return_value=self.config), \
                patch.object(service, 'loaded', return_value=True), \
                patch.object(service, 'ready', return_value={}) as ready, \
                patch.object(service, 'start') as start, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(service.main(['status']), 0)
            ready.assert_called_once_with(trusted)
            self.assertEqual(service.main(['start']), 0)
            start.assert_called_once_with(trusted, 10)

    def test_cli_platform_guard(self):
        with patch.object(service.sys, 'platform', 'linux'), patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(service.main(['install']), 1)
            self.assertIn('macOS-only', err.getvalue())


if __name__ == '__main__':
    unittest.main()
