# How Woof works

[Documentation home](index.md)

## Components

```text
Hermes host                              Desktop Mac
Hermes session DB --read-only--> Python bridge <--authenticated--> Electron main
Hermes CLI <---explicit requests---|                                  |
Hermes scheduler/output ----------|                           narrow local IPC
                                                                      |
                                                           mascot + bundled panel UI
```

Woof complements Hermes without patching its core. The client never needs filesystem access to the remote Hermes installation. The bridge owns integration and durable results; the client owns appearance, local presentation, pairing, and audio.

## Client

`main.cjs` manages windows, pairing, authenticated fetches, notification preferences, stable seen-ID storage, and the recent-state cache. `preload.cjs` exposes a narrow IPC contract to sandboxed, context-isolated renderers. Remote payloads are text/data, not executable UI. APIs use a fixed route allowlist.

The mascot is a small always-on-top transparent window. The panel window is created lazily and released after being hidden. A cache of the latest successful raw state is scoped to the connection object and usable for the first open within 70 seconds. It is re-filtered by current source preferences, invalidated after mutations, and never served while disconnected. Late fetches from a previous connection are rejected. Concurrent state fetches share one in-flight promise; subsequent visible polls still fetch fresh data.

The controlled slow-server reproduction measured roughly 2.7 seconds before the cache fix and 0.27 seconds in the corrected packaged build. This is a local test result, not a performance guarantee on every Mac/network.

The client stores first-launch cutoff/source/sound preferences, bounded seen IDs, window position, and presentation choices locally. Seen keys include the server URL and notification ID, with a 2,000-entry cap. Saved credentials are encrypted with OS storage only when opted in; otherwise they stay in process memory.

## Bridge

`backend.py` is a Python standard-library authenticated HTTP service. It resolves the selected Hermes profile and executable, observes read-only history, invokes supported CLI actions, imports results, and persists its own state in `nudge/companion.sqlite3`.

It does not write into Hermes session history. Scheduling changes happen through the Hermes CLI, not direct cron-store edits. It does not start the scheduler, disable approvals, or replay interrupted actions after restart.

## Message ingestion

1. First successful activation records a durable high-water mark in the Hermes message table without importing old assistant messages.
2. Later polls read ascending IDs in bounded batches of 200 rows.
3. Tool/analysis/internal/inactive/hidden/delegation content is excluded; final user-visible assistant text becomes notifications.
4. Stable session/message identities deduplicate across restart. Cursor and imported results commit atomically.
5. Backlogs continue from the consumed cursor rather than skipping to the newest rows.
6. Message provenance is returned separately; bodies are capped at 32,000 characters. Companion request/cron results are reconciled when identity permits.

The API returns the newest 300 saved notifications and 100 requests; older data remains in the companion DB. A separate desktop cutoff/source filter determines visibility and alerts. Woof-created schedules are recorded in a durable managed-job ledger, with legacy ownership migrated only from matching creation confirmations. Their results carry custom:true and bypass generic cron/health source opt-outs, but not the desktop date cutoff. Deleted schedules retain tombstone ownership for previous results. New authenticated custom-list/edit/delete routes are ownership-checked; edits/removals use supported Hermes CLI commands and verify readback. Unrelated profile jobs are never adopted by name.

## Bridge performance safeguards

Companion-only timestamp indexes serve latest notifications and requests. Notification provenance is fetched with one join instead of one query per card. Assistant batches remain 200 rows with atomic cursor checkpoints, but are streamed rather than fully materialized; excluded roles/sessions are rejected before parsing their bodies. Managed snapshots are parsed once. No additional cache, dependency, task-list cap or wire-payload reduction is introduced. Hermes history remains read-only.

## Small client performance safeguards

Full-state cached results expire at the existing 70-second freshness deadline and are released instead of being retained indefinitely during an outage. Fresh reopens still use the existing cache; concurrent GETs coalesce; mutations/reconnections/forgetting clear cached data. Renderer release and ownership isolation are preserved. The package trim removes unused generated npm installation metadata while keeping audio, ICU, ffmpeg and licenses. No new dependency or framework is introduced.

## Suggestions

Automatic contextual coaching and manual reflection use the selected profile’s provider with tools disabled. A bounded recent window covers the previous evening; conversation anchors/outcomes, relevant notifications and open to-dos supply validated source references. Proactive prioritizes possible attention/coaching needs; Ideas explores grounded personal/project possibilities. The saved cadence defaults to 120 minutes (15–1440 minutes supported), with durable attempt/check checkpoints and a separate daily health schedule. Coaching uses a per-run low-reasoning override and concise output without changing the configured model/provider or normal requests. It uses a 120-second agent run budget with a 150-second subprocess ceiling; shorter existing optimization/health bounds stay unchanged. Failed model runs retain prior successful suggestions and expose an error rather than passing generic extraction off as coaching.

Proactive focuses on possible attention needs and useful next steps; Ideas proposes broader contextual possibilities. Model-backed cards survive unrelated polling until a successful automatic or manual coaching run replaces them. Clicking a suggestion sends a new request; provenance is context, not an automatic continuation of an old session.

## Actionable workflows

Notification optimization is a tools-disabled model call returning a validated reviewable draft; no schedule is created until an explicit save. The bridge retains ownership boundaries for existing-job samples and mutations. Cron output ingestion extracts the actual response and handles owned quiet/no-change signals without displaying injected scheduling prompts.

A separate SQLite to-do store owns dates, completion state and reminder checkpoints. Due reminders are ordinary stable-ID notifications, emitted atomically once; they use existing client preferences and audio, not a new sound subsystem or model-powered cron job.

Daily read-only agent-health findings are persisted separately and merged into Proactive without replacing conversation suggestions. A durable check timestamp controls daily cadence. Remediation is a validated issue-linked request triggered only by the user; this is not an autonomous self-repair daemon.

## Persistence boundaries

- Hermes history: read-only source.
- Companion DB/token: bridge-side durable state and authentication.
- Client settings/seen IDs: desktop-side state; no history deletion.
- Recent-state cache: main-process memory only.
- Scheduler: existing Hermes responsibility.

For exact routes, timeouts, transport checks, and storage behavior, use the [API reference](../README-backend.md).
