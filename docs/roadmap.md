# Roadmap and release history

[Documentation home](index.md)

## Current baseline: 0.4.2

- macOS Apple-silicon desktop client and independently deployed authenticated bridge.
- Approved white/grey direwolf, closer-set round eyes, smaller highlights, neutral resting mouth, circular bark/howl mouth, tail wag, and unread badge.
- Four panels: Notifications, To-do, Proactive, Ideas for you.
- New final-assistant reply ingestion with no initial backfill and durable cursor/deduplication.
- Desktop first-launch cutoff; optional watchdog/heartbeat-style/executed-cron visibility.
- Wolf bark uses the actual uploaded audio decoded to WAV; Little howl and None are selectable.
- Immediate rendering of already-received state on first panel open, shared concurrent fetches, normal follow-up polling.
- Hidden renderer release and once-per-minute idle badge checks.
- Background-only opacity, readable text, dismissal/acknowledgement, panel reorder, and counters.

## Release milestones

- **0.2.x:** configurable remote client/bridge, token controls, smaller mascot, idle optimization, presentation controls.
- **0.3.0:** Woof rename and initial direwolf/native-transparency work.
- **0.3.1:** white/grey/no-tag artwork, three-panel UI, full scrolling, new assistant-message stream and contextual reflection.
- **0.3.2:** first-launch inbox cutoff, 85% default opacity, source opt-ins, counters.
- **0.3.3:** approved B artwork, wag/open-mouth alerts, selectable sounds, removed frosted control.
- **0.3.4:** closer eyes, smaller highlights, circular reaction mouth.
- **0.3.5:** Wolf bark label/MP3 playback wiring and smaller neutral resting mouth; this still referenced the wrong synthesized sample.
- **0.3.6:** actual uploaded bark decoded to WAV, first-open cached rendering, concurrent-fetch sharing, smaller English-only native package. The previous audio-source mistake is corrected, not hidden in the changelog.

- **0.3.7:** closable error/status banners, polling-error dismissal deduplication, cool-blue notification palette, safe GET-only network retry, explicit reflection progress, and live model-backed reflection verification.

- **0.3.8:** Woof-created schedule results bypass unrelated cron source opt-outs; authenticated, ownership-checked custom notification manager supports verified edits, pause/resume and deletion without erasing previous results. Both client and bridge are updated.

- **0.4.0:** agent-optimized notification drafts with review, actionable-only monitoring, lightweight to-dos with due dates/reminders, and daily agent-health issues with user-authorized repair actions. Existing owned cron output is shown without its injected prompt/metadata wrapper.

- **0.4.1:** a dedicated server-backed To-do panel with inline completion/reopening; contextual Proactive coaching and creative Ideas for you run automatically on a configurable 15-minute-to-daily cadence (two hours by default). Daily agent health remains independent.

- **0.4.2:** Woof Settings title; compact To-do cards with server-backed Completed checkboxes; concise Agent health header; coach status moved into Settings; expired full-state cache released at its existing freshness deadline; unused generated npm metadata removed from the app.

Published private downloads are listed in the repository Releases section; not every historical milestone is a release asset.

## Next priorities — proposed, not implemented

1. Developer ID signing and Apple notarization.
2. Verify bark redistribution rights or replace it with a clearly licensed/original recording before public launch.
3. Reproducible native build automation, improved packaged native CI, and interactive Keychain validation.
4. Stronger bridge service-management/onboarding instructions without changing Hermes core automatically.
5. Evaluate lower-latency background delivery against CPU/network/privacy cost; current idle detection is polling, not push.
6. Review token scoping/rotation ergonomics for wider deployments. Current design is single-profile, not multi-tenant.
7. Decide public repository/domain/landing page only after approval. No domain ownership or availability is asserted.

## Known limits

Apple-silicon Mac client is verified; Intel/Windows/Linux desktop builds are not shipped. The backend's Windows timeout paths have unit coverage, not native certification. GUI language is English; runtime trims keep English resource variants and full ICU international date/time data.

Electron remains the dominant installer and RAM baseline. Smaller packaging is not a claim of a tiny native app. Local latency/memory measurements are not universal guarantees.

Suggestions rely on bounded history and can miss context. Explicit reflection uses the configured model provider; failures remain real errors/fallbacks rather than fabricated results. Scheduler/gateway health, provider authorization, and interactive approvals remain outside Woof's control.
