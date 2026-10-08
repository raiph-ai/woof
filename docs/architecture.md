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

## Suggestions

Automatic deterministic extraction is explicitly a suggested/unverified fallback and spends no model credits. Explicit history reflection uses the selected profile's provider and bounded history: up to 24 user anchors, associated assistant outcomes, and a shared 12,000-character budget. It is tools-disabled and validates supplied source identities.

Proactive focuses on possible open loops; Ideas proposes concrete assistance. Model-backed cards survive unrelated polling and newer history until another explicit refresh replaces them. Clicking a suggestion sends a new request; provenance is context, not an automatic continuation of an old session.

## Persistence boundaries

- Hermes history: read-only source.
- Companion DB/token: bridge-side durable state and authentication.
- Client settings/seen IDs: desktop-side state; no history deletion.
- Recent-state cache: main-process memory only.
- Scheduler: existing Hermes responsibility.

For exact routes, timeouts, transport checks, and storage behavior, use the [API reference](../README-backend.md).
