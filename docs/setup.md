# Install and connect

[Documentation home](index.md)

## Two machines, two roles

- **Desktop:** Woof runs on a Mac with Apple silicon. The packaged client does not require Python, Node, or Hermes.
- **Hermes host:** the Python bridge runs beside an already-configured Hermes installation. Python 3.9+ is required; the backend uses only the standard library.

They can be the same machine, but do not assume they are. Install the desktop app on the machine where you want the mascot.

## 1. Install the client

1. Download the current installer from the private release.
2. Verify it against the release's `SHA256SUMS.txt`, for example `shasum -a 256 Woof-0.4.3-arm64.dmg`.
3. Quit an older Woof/Hermes Nudge client before replacing it.
4. Open the DMG and drag Woof into Applications.
5. Launch Woof. Because this build is ad-hoc signed rather than notarized, macOS may require **System Settings → Privacy & Security → Open Anyway** after the first launch attempt. Do not disable Gatekeeper globally.

The legacy Hermes Nudge bundle ID and data directory are retained for upgrade compatibility. Pairing, presentation preferences, and notification cutoff are not intentionally reset during an ordinary upgrade.

## 2. Start the bridge on the Hermes host

Get the source on the host, then run:

```sh
python3 -B backend.py --profile your-profile
```

Omit `--profile` for the default profile. Initialize named profiles in Hermes first. Optional `--hermes-home` and `--hermes` arguments select the data root and executable explicitly. See the [bridge reference](../README-backend.md).

By default the bridge listens at `http://127.0.0.1:47831`. It prints the pairing token's **file path**, not the token. The token is stored at `<resolved-profile-home>/nudge/token`. Retrieve it securely on the host; never put it in source, logs, screenshots, issues, or documentation.

The bridge is a separate foreground process unless you arrange your own service supervision. Its startup does not start Hermes or the Hermes scheduler.

## 3. Choose transport

### Recommended remote path: SSH tunnel

Keep the bridge on loopback. Run this on the desktop and leave it running:

```sh
ssh -N -L 47831:127.0.0.1:47831 user@your-hermes-host
```

In Woof, use `http://127.0.0.1:47831`. The HTTP connection stays on local loopback; SSH protects the traffic crossing the network.

### HTTPS

Use direct TLS or a properly configured HTTPS reverse proxy. Certificates must be trusted by the desktop. `--public-url` is an exact origin; keep the correct Host and Origin when proxying. Certificate verification is never disabled.

### Trusted-network HTTP exception

This is not encrypted. Use it only on an intentionally trusted, isolated network, with firewall restrictions and no public port forwarding. Bind to the intended interface rather than exposing every interface unnecessarily:

```sh
python3 -B backend.py --profile your-profile   --host YOUR_LAN_ADDRESS   --public-url http://YOUR_LAN_ADDRESS:47831   --allow-insecure-http
```

Replace `YOUR_LAN_ADDRESS` with the host's actual current address. The desktop must also enable its trusted-network HTTP checkbox. Never copy someone else's deployment address from an example.

## 4. Pair the desktop

Open Settings, enter the **bridge** URL and pairing token, then Test and Connect. The token field supports Show/Hide, Copy/Paste, and standard Mac shortcuts. Token text is cleared and hidden when Settings closes.

Credentials are session-only by default. **Remember this connection** uses macOS Keychain through Electron safeStorage; there is no plaintext persistence fallback. Keychain may require interactive approval. Changing servers requires the token to be entered again.

## 5. Check functionality

- Confirm the displayed connected profile is the one intended.
- Generate a new user-facing Hermes reply after activation and allow the next poll to import it.
- Check the badge, click the wolf, and open the notification card.
- Choose **Wolf bark**, **Little howl**, or **None**, and use Preview sound.
- Use Reflect on my history only when you want a model-backed analysis; it can incur the configured provider's normal cost.

The first activation deliberately does not bulk-import old assistant messages. The desktop also keeps its own persistent first-launch cutoff. These are separate mechanisms.
