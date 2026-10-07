# Security

Never submit pairing tokens, authentication files, or conversation transcripts in issues. Report vulnerabilities privately to rp@redcirclestudio.com.

Pairing tokens authorize agent execution. Use SSH tunnels or HTTPS and network restrictions. Do not expose the bridge directly to the Internet. Default is loopback-only. Remote plaintext HTTP requires deliberate opt-in on both ends. TLS validation is mandatory.

The desktop renders bundled UI, not server-provided code. Credentials use OS encryption; no plaintext fallback. The server authenticates all reads/writes, rejects unexpected Host/Origin headers, bounds request sizes, uses exact endpoint allowlists, and does not bypass Hermes approvals.

This is an early community build, not a multi-tenant service. Tokens are single-profile credentials without fine-grained roles. Rotate by stopping the bridge, removing its token file, restarting, and reconnecting clients. Existing browser cookies also expire on server restart.
