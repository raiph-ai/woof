# Bridge autostart (macOS)

`bridge_service.py` installs a **user LaunchAgent**, not a system daemon. It starts the bridge at login, starts it immediately when installed, and restarts it after exit/crash (launchd throttles retries to 10 seconds). This requires a logged-in macOS GUI session. It does not start before login. Linux and Windows service installation are not implemented; the CLI fails explicitly rather than pretending to install. The bridge itself remains cross-platform.

Python 3.9+ and the standard library are sufficient. Keep this checkout and Python/Hermes executables at their installed paths; moving or deleting them breaks autostart. Use a persistent Python installation, not a temporary environment. No administrator privileges are required.

## Install

From the checkout, select your existing profile and **explicit Hermes executable**:

```sh
python3 bridge_service.py install --profile work \
  --hermes-home "$HOME/.hermes" \
  --hermes "/absolute/path/to/hermes"
```

`--hermes-home` accepts either the Hermes root or `ROOT/profiles/NAME`, matching `backend.py`. The selected profile must already exist. `--profile` defaults to `HERMES_PROFILE` or `default`; `--hermes-home` defaults to `HERMES_HOME` or `~/.hermes`. If `--hermes` is omitted, resolution matches the backend: PATH first, then the Hermes source environment under `~/.hermes/hermes-agent`. Prefer explicit paths for reproducible installs. No Hermes core files or other profiles are modified.

The installer freezes absolute Python, backend, selected profile-home, user-home and Hermes paths. By default Python is the interpreter executing this command. Override it with `--python "/absolute/path/to/python3"`; `--backend` is available for an alternate checkout. Executable symlinks are retained deliberately so virtualenv selection is preserved. Arguments are a plist array, not a shell command; spaces in paths are supported.

The service defaults to **`127.0.0.1`**, port `47831`; network access is not enabled by default. Each profile/root gets a distinct service ID, but simultaneous profiles still need distinct `--port` values. Stop any existing foreground bridge before installing: an occupied bind address/port fails preflight rather than attaching to an unrelated process. Installation validates profile directory, backend syntax, Python 3.9+ and executable Hermes path; it does not run Hermes or make a model call. This is executable-path validation, not a check of provider credentials or Hermes model availability.

### Explicit trusted-network HTTP

If Woof connects to the Mac over your trusted LAN, supply the Mac's assigned IPv4 address, its exact HTTP origin and the plaintext opt-in. For example (replace the illustrative address with your Mac's actual LAN address):

```sh
python3 bridge_service.py install --profile work \
  --hermes-home "$HOME/.hermes" --hermes "/absolute/path/to/hermes" \
  --host 10.0.0.2 --port 47831 \
  --public-url http://10.0.0.2:47831 --allow-insecure-http
```

**HTTP exposes the bearer token and bridge traffic to network observers. Use only on a trusted network; do not expose it to the internet or forward the port.** Authentication remains required. Both `--public-url` and `--allow-insecure-http` are mandatory for non-loopback binds. The URL must be exactly `http://HOST:PORT` matching the literal bind address and explicit port: no credentials, trailing slash, path, query or fragment. Hostnames, wildcard/all-interface binds and IPv6 are outside this installer's scope. The backend's TLS/reverse-proxy options remain available for separately managed deployments, not through this helper.

Configure Woof's server URL to that same origin. The address must be assigned to this Mac: port preflight binds the configured address, and readiness proves it is local before reading/sending the token. Readiness never targets a different public URL. A changed/DHCP-expired address requires uninstall/reinstall with the new settings; prefer a stable LAN assignment. Add `--dry-run` to preview without installing.

The LaunchAgent uses an explicit, deduplicated `PATH`: the user's `~/.local/bin`, selected Python directory, selected Hermes executable directory, `/opt/homebrew/bin`, `/usr/local/bin`, then `/usr/bin:/bin:/usr/sbin:/sbin`. This allows Hermes subprocesses to find Homebrew, Node and local tools without inheriting the caller's shell environment or secrets. Shell startup files are not sourced.

Success requires launchd registration **and authenticated `/api/info`** reporting the expected bridge kind, protocol and profile. The existing `PROFILE_HOME/nudge/token` is read only in memory for that check; it is never placed in the plist, arguments or output. A newly started backend may create its normal token/database. This helper never rotates/deletes tokens or databases. It does not copy the caller's environment/secrets into the plist.

### Preview without registering or changing anything

```sh
python3 bridge_service.py install --profile work \
  --hermes-home "$HOME/.hermes" --hermes "/absolute/path/to/hermes" \
  --dry-run > "$TMPDIR/woof-service-preview.plist"
```

Dry-run validates inputs and prints the plist; it does not create service directories, token/database files, check readiness or invoke launchctl. Existing foreign service files are still refused. The redirected preview is not itself an installation.

## Status, retry and uninstall

Use the same `--profile` and `--hermes-home` selector as installation. Status/start read executable, port, host, public URL and plaintext opt-in settings from the installed plist, so you need not repeat `--port`, `--host`, `--public-url`, `--allow-insecure-http`, `--python`, `--backend` or `--hermes`.

```sh
python3 bridge_service.py status --profile work --hermes-home "$HOME/.hermes"
python3 bridge_service.py start --profile work --hermes-home "$HOME/.hermes"
python3 bridge_service.py uninstall --profile work --hermes-home "$HOME/.hermes" --dry-run
python3 bridge_service.py uninstall --profile work --hermes-home "$HOME/.hermes"
```

`status` exits nonzero if unloaded or not authenticated/ready. When no owned service is installed but a manually started bridge authenticates successfully, it exits zero and explicitly reports **unmanaged**, not autostart-enabled; supply the foreground bridge's nondefault `--port` and any trusted-network arguments above. Status never adopts an existing listener. `start` registers an installed but unloaded agent and waits for readiness; an already loaded agent is checked rather than forcibly restarted. If launchd is retrying after a crash, fix the prerequisite and allow its restart interval to elapse. Readiness timeout defaults to 10 seconds; use `--timeout 30` on install/start if needed (maximum 300).

Uninstall unloads only this profile's owned agent, checks it is unloaded, then removes its plist. Tokens, databases and logs are retained. A bootout failure keeps the plist for diagnosis. If the executable paths/settings change, uninstall first and reinstall. Identical installs are idempotent; different settings are not silently overwritten. Foreign/malformed plists and symlink service files are refused.

## Files and troubleshooting

- Agent: `~/Library/LaunchAgents/ai.woof.bridge.PROFILE.HOMEHASH.plist` (mode 0600). The hash distinguishes different Hermes roots. Use the printed exact path/label rather than guessing the hash.
- Log: `PROFILE_HOME/nudge/service.log` (stdout and stderr). No automatic log rotation; check its size periodically.
- Service directories are created only on real installation. The helper never rewrites existing profile token/database data.

Common failures:

- **Port already in use:** stop the manually running bridge or select an unused `--port`. Do not kill an unknown process blindly. The desktop client must use that same port.
- **Bootstrap/launchctl denied:** run from your logged-in macOS account, not sudo, SSH without a GUI session, a sandbox or a restricted automation gateway. This helper does not bypass service-control restrictions. Dry-run remains available in restricted environments.
- **Installed but not loaded:** run `start` in the GUI user session. Inspect `launchctl print gui/$(id -u)/LABEL` using the printed label.
- **Readiness/authentication failed:** inspect `service.log`, confirm Python/backend/Hermes paths remain valid and the selected token is readable, and rule out another profile on the port. Do not delete/regenerate a working token to fix a service problem. Readiness disables proxies and redirects to avoid leaking the token.
- **Timeout after installation:** the owned plist remains installed for diagnosis; the CLI reports failure, not success. Fix the error then retry `start`, or `uninstall` to disable retries.
- **Foreign file:** inspect it manually. Do not replace another application's plist. No `--force` option exists.

## Tests

```sh
python3 -m unittest -v test_bridge_service.py
```

Tests use temporary fixture profiles under `TMPDIR`, mock launchctl commands, and exercise authenticated readiness with a local fixture HTTP server. They do not register a LaunchAgent or access a real profile's token/database. Actual registration/login/restart behavior still needs a manual GUI-session smoke test on macOS.
