# Security and privacy

[Documentation home](index.md) · [Security reporting](../SECURITY.md)

## Keep this project private

The repository is intentionally private. GitHub Pages is disabled. A private repository does not automatically make a Pages deployment private; do not enable it or change visibility without a separate approval and access-control review.

No pairing token, personal profile database, conversation transcript, live deployment address, credential file, or private configuration belongs in commits or release assets. Sample configuration uses placeholders.

## Pairing is privileged

The bridge token can read profile context and authorize requests that use Hermes tools. Treat it as a password. The current single-profile token is not a fine-grained role-based permission system or multi-tenant security boundary.

Default server binding is loopback. Prefer SSH or trusted HTTPS. Direct LAN HTTP requires explicit opt-ins on both client and server and exposes tokens/content in plaintext; never port-forward it to the public Internet. TLS verification stays enabled. Exact Host/Origin checks and authenticated reads/writes remain mandatory.

## Client boundaries

Only bundled UI is loaded. Electron context isolation, sandboxing, disabled renderer Node integration, and a narrow preload API separate display code from credentials and network access. Bridge responses are rendered as text. Navigation, new windows, and permission requests are denied. No permissive CORS, telemetry, or remote renderer code is introduced.

Tokens entered during setup necessarily occupy the input temporarily; the field can be shown/copied at the user's request and is cleared/re-hidden on close. Restored saved tokens are not returned by the public configuration API. Remembered credentials use macOS Keychain via safeStorage; there is no plaintext fallback. Session-only storage is the default.

The recent-state cache is connection-scoped and memory-only. Source filtering is shared with badge/alert logic. Seen-ID persistence does not store notification bodies.

## Context and actions

Hermes history is opened read-only. Explicit reflection sends bounded context to the configured model provider and may incur that provider's normal cost. Startup fallback extraction stays local; configured automatic coaching invokes the selected provider on its saved cadence and can incur normal model cost. Coaching settings default to 120 minutes and permit 15–1440 minutes. Context selection remains read-only, bounded and provenance-validated, with failures visible rather than fabricated suggestions. No analysis runs with tools, and suggestions never execute without a click.

Notification optimization and health probes run with tools disabled and may incur configured model-provider costs. Optimized drafts need a reviewed save before scheduling. Due to-do reminders use bridge-local state and no model calls. Daily health findings do not execute fixes; repair clicks authorize normal Hermes requests, and unavailable credentials require explicit recovery rather than approval bypass. External notification links open only validated HTTPS destinations after a user click, never local files or script URLs.

Requests use normal Hermes approvals. Noninteractive runs can fail when approval/device interaction is needed. The bridge does not use shell-interpolated prompts or automatic approval bypass flags. Errors are reported instead of fabricating outcomes.

## Recovery and rotation

Stop the bridge before rotating its token. Remove only the bridge token file, restart the bridge, then re-pair clients securely. Browser cookies are invalidated on bridge restart; bearer token persistence is separate. Never delete Hermes history to clear Woof notifications.

Back up the companion DB and relevant client preferences securely before destructive resets. Dismissal/read acknowledgement are presentation operations, not job cancellation.

## Release caveats

The Mac build is ad-hoc signed, not notarized. Signing verification detects installer corruption but is not a substitute for Developer ID identity/notarization. Do not disable system-wide protections to install it.

Code/original mascot use the MIT license. The bark is user-provided; verify its redistribution rights before public release. The howl is an original synthesized effect. Do not assume an uploaded clip is automatically MIT-licensed.
