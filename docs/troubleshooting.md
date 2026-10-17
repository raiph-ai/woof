# Troubleshooting

[Documentation home](index.md)

## Cannot connect

- Use the bridge URL, not an arbitrary Hermes UI address.
- Check that the bridge process is running and the displayed host/port matches the client.
- For remote connections, a loopback listener is reachable only through a tunnel or local proxy. Use the actual host interface address for an approved LAN deployment.
- Check firewall rules and tunnel health. Do not solve this by opening an unauthenticated public listener.
- Remote HTTP needs the explicit trusted-network opt-in on both ends. HTTPS requires a trusted certificate.
- A 401 means authentication failed; re-enter the token securely. Do not paste it into an issue.
- A 403 can indicate mismatched Host/Origin or a prohibited cross-site request. Check exact public URL/proxy configuration.

## Bridge unavailable after restart

A foreground `backend.py` process stops when its terminal/session ends and does not restart at login. On a macOS Hermes host, install the supported service from a normal host terminal:

```sh
python3 bridge_service.py install --profile your-profile
python3 bridge_service.py status --profile your-profile
```

Stop a manually running bridge before installation; the installer refuses to claim a listener it does not manage. The service keeps the existing token and companion data. See [service management](bridge-service.md) for logs, dry-run, removal, and limitations. The desktop **Launch Woof at login** checkbox starts only the app, not a remote bridge or SSH tunnel. A Mac user LaunchAgent starts at login, not before login.

## Saved connection asks for credentials again

Session-only mode deliberately forgets the token on quit. Remembered tokens require Keychain access. macOS may prompt after an ad-hoc rebuild changes the app's signing identity. Reauthorize on the desktop or reconnect manually; there is no plaintext fallback.

## Sound is wrong or missing

Select Wolf bark and use Preview. This build uses the uploaded recording decoded to `web/sounds/wolf-bark.wav`; Little howl is a separate synthesized clip, and None is silent. Notifications and Preview share the same local playback function.

Check system output device/volume and ensure the newly installed app is actually running. Quit the previous version before replacing it; an already-running old process will keep old code/assets. Do not confuse a standalone preview attachment with the application's wired playback source.

If an uploaded sound was reported as an empty voice message, it may still be valid non-speech audio. Locate the original media and verify source provenance before substituting anything. A replacement must be verified against that source, not an assistant-created default.

## Heard a sound, but cards appear slowly

Current builds render already-fetched notifications from a connection-scoped recent-state cache on first panel open. Cold renderer recreation still takes a small amount of local time. Fresh network calls can be slower if no usable cached state exists. The visible panel then polls normally.

Background badge checks happen once per minute; this is not push streaming. Avoid repeatedly requesting paid history analysis as a refresh workaround.

## Notification absent or historical inbox empty

- Both bridge activation and desktop cutoff deliberately suppress old history.
- Confirm the connected profile. A message in another profile is outside scope.
- Only user-facing final assistant content is imported; internal/tool/analysis rows are intentionally excluded.
- Check source switches for watchdog, heartbeat-style, and executed cron events.
- Check local dismissal state and Restore dismissed cards.
- Large backlogs advance through bounded batches; the UI shows only the newest API window, with a smaller initial card list.

## Reminder never runs

Woof does not start Hermes scheduling. Check the scheduler/gateway serving the selected profile, job enabled state, supported schedule syntax, and provider credentials. Scheduler heartbeat freshness is a diagnostic, not proof of successful execution. Dismissing a card does not pause a job.

## Custom notification saved but no result appeared

Open Settings → Manage custom notifications to confirm the saved task, active/paused status, last result status and next run. Builds before 0.3.8 treated these results like generic cron output, hidden by default. Update both client and bridge to 0.3.8: Woof-created results are eligible without enabling unrelated cron traffic. The existing first-launch cutoff and desktop dismissal still apply; a new client does not backfill older results. Creation does not run a repeating task immediately, and an active existing Hermes scheduler remains required.

## Proactive coaching and To-do panel

The To-do panel saves Complete/Reopen on the bridge, rather than merely hiding a card. Its pending count excludes completed items. If an item does not update, check the connection and returned error; refreshing should show the server state.

For coaching, check Settings → Proactive cadence and the last/next run/error status. Automatic model calls require the bridge and provider to be available; moving the slider is not an immediate reflection request. A failed run retains the last successful cards. The coach reviews bounded recent context, not the entire profile history, and ideas are possibilities rather than verified obligations. Daily agent-health checks are separate and are not slowed down/sped up by the coaching slider.

## Optimization, to-do reminders and health checks

Optimization needs working model-provider authorization. Retry after recovering the provider; do not interpret an error as an optimized result. Review the alert criteria to avoid repeated routine reports. A to-do reminder needs an active bridge and connected desktop; None disables audio, and idle desktop polling can delay the sound. Completing/deleting a to-do cancels pending reminders.

Daily health checks identify only what the bridge can observe about the selected agent. A failure card offers a user-approved repair request or Settings/manual recovery when the agent is unavailable. A clicked request is not proof the repair succeeded; check its returned result and subsequent health status.

## Closable connection errors

Error and information banners have an × button; Escape closes the main error when no dialog is open. Dismissed identical connection errors do not reappear on every poll. A successful state read clears a connection-failure banner. A new explicit action may surface a new error. Ordinary GET reads retry once after a brief transient transport failure; POST actions never auto-replay because they may already have been accepted. History-reflection submission has a bounded 10-second acknowledgement timeout and visible progress; real offline bridges still require connection recovery.

## Suggestions are stale or an action failed

Use explicit Reflect on my history for a new bounded model analysis. Saved model cards are intentionally not overwritten by routine fallback extraction. A suggestion is not proof of unfinished work. Check the resulting error notification for provider/auth/approval failures; do not blindly retry an action that may partly have succeeded.

## UI problems

The main area scrolls beneath the header. Opacity affects backgrounds only. Text should remain opaque. Restore dismissed cards does not reset schedules. Panel reorder/disclosure state is desktop-local. None mutes audio but leaves visual reactions; reduced-motion preference can suppress wagging.

## Useful bug report

Include app version, Mac model/OS, whether Hermes is local/remote, transport type, connected profile name if safe, reproduction, expected/actual behavior, and sanitized errors. Exclude pairing tokens, credentials, private prompts/transcripts, and deployment identifiers that are not needed.
