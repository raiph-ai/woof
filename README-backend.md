# Woof bridge reference

Python 3.9+ standard library only. Run the bridge on the machine hosting Hermes; the desktop client can run elsewhere. It does not start Hermes or change its configuration.

```sh
python3 backend.py --profile work
python3 -B -m unittest test_backend -v
```

Default address: `http://127.0.0.1:47831`. `--port PORT` changes the listener port; `--host HOST` defaults to `127.0.0.1`. The native client configures its server address separately and need not spawn this bridge.

## Profile and executable selection

`--profile NAME` defaults to `HERMES_PROFILE`, otherwise `default`. Every CLI call explicitly selects this profile, ignoring Hermes' sticky active profile. `--hermes-home PATH` accepts a Hermes root or a `ROOT/profiles/NAME` home; it defaults to `HERMES_HOME`, otherwise `~/.hermes`. A profile-shaped path is reduced to its root, then selection is applied: `default` uses the root; named profiles use `ROOT/profiles/NAME`. This mirrors Hermes CLI resolution so filesystem reads and CLI writes use the same home. Initialize named profiles in Hermes first.

`--hermes EXECUTABLE` optionally supplies a path or command. Otherwise discovery uses `shutil.which('hermes')`, then known `~/.hermes/hermes-agent/{.hermes,.venv,venv}/{bin/hermes,Scripts/hermes.exe}` installation paths. Missing executables are reported in state; requests fail rather than fabricating results. Every call sets both `HERMES_PROFILE` and the resolved `HERMES_HOME`; inherited session IDs and automatic approval overrides are removed.

```sh
python3 backend.py --profile work --hermes-home "$HOME/hermes-data" --hermes hermes
```

## Remote deployment

Prefer an SSH tunnel or HTTPS. The token permits Hermes tool execution: protect it like a password and restrict access with firewall rules. This stdlib bridge is not a hardened public Internet application server.

For an SSH tunnel, leave the server on loopback and run `ssh -N -L 47831:127.0.0.1:47831 user@server.example` on the desktop. Configure the client with `http://127.0.0.1:47831`; the tunnel encrypts network traffic without exposing the bridge listener.

For a same-server HTTPS reverse proxy:

```sh
python3 backend.py --profile work --public-url https://nudge.example
```

Forward to loopback port 47831 and preserve the public Host and browser Origin. `--public-url` must be an exact HTTP(S) origin without credentials, query, fragment or path (a trailing `/` is accepted). The bridge does not dynamically trust forwarded headers. Keep the proxy-to-bridge connection on loopback or otherwise encrypted.

For direct TLS:

```sh
python3 backend.py --profile work --host 0.0.0.0 \
  --public-url https://nudge.example:47831 --tls-cert cert.pem --tls-key key.pem
```

Both certificate/key files are required and validated before serving. TLS 1.2+ is required; use a certificate trusted by the client, never disable client verification. `--host ::` supports IPv6.

Non-loopback binds are refused without TLS or explicit `--allow-insecure-http`, even if a public HTTPS URL is supplied. The HTTP exception is only for trusted isolated networks: tokens and private context travel in plaintext. All-interface binds (`0.0.0.0`/`::`) also require `--public-url` for exact Host checks; wildcard request Hosts are never accepted.

```sh
python3 backend.py --profile work --host 0.0.0.0 \
  --public-url http://nudge.example:47831 --allow-insecure-http
```

## Authentication and static assets

First startup creates a random bearer token at:

`<resolved-profile-home>/nudge/token`

The directory is mode 0700; token and companion database are mode 0600 on POSIX. On Windows, protect the profile using account-specific filesystem ACLs; chmod does not provide POSIX-equivalent isolation. Token values are never printed. Transfer remote tokens securely, not through logs, screenshots or source files. Native clients use `Authorization: Bearer <token>` from the main process. The optional browser bootstrap `/?token=TOKEN` returns HTTP 303 to `/` and a signed, one-day `HttpOnly; SameSite=Strict` cookie. Direct TLS or a configured public HTTPS URL adds `Secure`; loopback HTTP does not. Restart invalidates cookies, not the saved bearer token. Avoid token URLs in browser history and proxy logs; native bearer authentication is preferred.

All API reads and writes require authentication. Failures return HTTP 401 JSON, never login redirects. The token URL works only at `/`. Host must exactly match the public URL's netloc or canonical bind `HOST:PORT` (bracketed IPv6); all-interface bind addresses are not trusted request authorities. Supplied Origin must exactly match the public origin or canonical bind origin. Explicit default ports must match exactly. Absent Origin is allowed for native Node fetch; duplicate Host/Origin, `null`, cross-origin and cross-site requests are rejected. No CORS headers are emitted. POST requires `application/json`, a JSON object, and at most 64 KiB. OPTIONS is rejected.

Authenticated static files use an explicit allowlist of the bundled index, scripts, styles, token/settings/panel assets, and mascot SVG. Symlinks and traversal paths are rejected. Responses carry CSP, nosniff, no-referrer and no-store headers. Inline scripts, remote resources, embedding and plugins are forbidden by CSP. No request URLs, prompts, transcripts, or tokens are logged.

The native Electron shell loads a bundled renderer and uses authenticated main-process APIs over IPC, not permissive CORS. Tokens must never reach renderer JavaScript or app URLs. The optional authenticated static browser path remains available; native authentication does not depend on expiring browser cookies.

## API

`GET /api/info` requires authentication and returns `{kind:"hermes-nudge",protocol_version:1,profile:string,origin:string,tls:boolean}`. `tls` identifies listener encryption; an HTTPS proxy can expose an HTTPS origin while listener TLS is false.

`GET /api/state` retains the agreed shape:

- `notifications`: `{id,title,body,created_at,read,job_id?,session_id?,message_id?,source?,message_timestamp?}`
- `proactive` and `ideas`: `{id,title,body,prompt,source?}`
- `jobs`: `{id,name,schedule,enabled,last_status?}`
- `requests`: `{id,title,status,body}`
- `status`: `{profile:string,hermes_available:boolean,analysis_busy:boolean,scheduler:{heartbeat_at:number|null,heartbeat_age_seconds:number|null,heartbeat_fresh:boolean}}`

Scheduler diagnostics cheaply read the selected profile's `cron/ticker_heartbeat`, with no CLI call on every poll. Freshness means a marker no older than 180 seconds, not proof of a live PID or successful execution. Missing or invalid markers report null times and false freshness.

The newest 300 notifications and 100 requests are returned. Older records remain durable in the companion DB. Timestamps are UTC ISO strings. `hermes_available` means the configured executable exists and is executable, not a guarantee that provider credentials or scheduler are healthy.

| POST | Body | Success |
|---|---|---|
| `/api/schedule` | `{title,prompt,schedule,mode:"cron"\|"heartbeat"}` | HTTP 200 `{id,job,mode}` |
| `/api/request` | `{prompt,title?,source_session?}` | HTTP 202 `{id,status:"queued"}` |
| `/api/refresh` | `{}` | HTTP 202 `{id,status:"queued"}` or `{status:"running"}` |
| `/api/notification` | `{id,read:true}` | HTTP 200 `{id,read:true}` |
| `/api/job` | `{id,action:"pause"\|"resume"\|"run"}` | HTTP 202 `{id,status:"queued"}` (request ID) |

Async requests transition `queued` → `running` → `completed` or `error`. Poll `/api/state`; a result/error also becomes a durable notification. Invalid input is HTTP 400, unknown jobs/notifications HTTP 404, CLI/integration errors HTTP 502. Busy submission is HTTP 400. API errors have `{error: "..."}` bodies.

## Real Hermes integration

All calls explicitly use the configured executable, profile and home. No shell interpolation, `shell=True`, `--yolo`, core edits, or configuration edits are used. Prompts for immediate requests are passed on stdin via `--query-file -`, not exposed in process arguments. Requests use `chat -Q --oneshot --max-turns 8 --run-budget 120 --source nudge-request --format stream-json`. Hermes tool approvals remain in force. Requests are new sessions; `source_session` is provenance in the prompt, not an automatic continuation of a possibly stale conversation.

Scheduling uses supported `cron create SCHEDULE PROMPT --deliver local --name TITLE`, followed by a read-back of the exact job. User submissions create enabled jobs. `heartbeat` is explicitly a **heartbeat-style interval check implemented as Hermes cron**, not a native heartbeat feature; interval shorthand such as `30m` becomes `every 30m`. Cron mode preserves Hermes semantics (`30m` once, `every 2h` repeating, or a cron expression). No analysis or recurring jobs are created on backend startup. Existing profile jobs are displayed; pause/resume/run accept only exact IDs found in that profile store. Pause/resume effects are read back. Manual run may execute immediately or be queued by Hermes for its next scheduler tick; the CLI outcome is preserved.

Scheduled jobs require an existing Hermes scheduler/gateway serving the selected profile. Nudge observes but does not start or reconfigure that scheduler. Local delivery means results are observed from the profile's cron output/status, not sent to messaging platforms.

Request subprocesses have an outer 150-second timeout; explicit analysis 90 seconds; cron create/pause/resume 45 seconds and manual run 180 seconds. POSIX timeouts kill the process group; Windows attempts native `taskkill /T /F` process-tree termination, then kills the child directly as a fallback. Pipe draining is bounded. Errors persist without retrying actions that might partly have succeeded. Three concurrent async tasks are allowed. Interrupted queued/running requests are marked error after restart rather than replayed.

## Conversation suggestions

Startup and state reads seed both panels with **Suggested, not verified** deterministic history extraction only when model-backed reflection is not already saved. This fallback is explicitly not an inferred pending task or model reflection. History is checked at most once per minute and fingerprinted. Manual model cards survive newer unrelated history, ordinary polls and restarts; only another explicit refresh replaces them. Automatic seeding spends no model credits. Suggestion prompts do not assume a task is unfinished; cards execute only after explicit `/api/request` dispatch.

`/api/refresh` requests bounded, read-only model analysis with `-t none --ignore-rules --max-turns 1 --run-budget 60 --source nudge-analysis`. Inspection of this installed Hermes chat path confirms an explicitly unknown toolset resolves to zero tool schemas, while an empty toolset flag would fall back to configured tools. Hermes emits an `Unknown toolsets: none` warning; stderr is not shown in the app. This is version-sensitive; retest when upgrading Hermes. The backend also rejects any analysis stream containing tool-use events. Structured suggestions must cite an exact session/message pair found in the supplied history. Invalid JSON/provenance or model errors fall back to deterministic extraction, with a durable error notification.

The profile's `state.db` is opened SQLite `mode=ro` plus `PRAGMA query_only`. Active human USER messages are selected newest first, excluding companion/nudge/analysis/cron/subagent/tool sources, hidden sessions, injected display rows and compressed summaries when those columns exist. At most 24 user anchors are included, with up to one final assistant outcome per anchor before its next human turn (search bounded to eight assistant rows). Excerpts are at most 1,200 characters each and all user/assistant text shares a 12,000-character budget. Every anchor and outcome retains session/message IDs and timestamps. Multimodal content contributes text blocks only. No transcript content is printed to logs. Manual refresh sends this bounded context to the profile's configured model provider; deterministic startup extraction stays local.

Reflection considers the projects described in past conversations and their reported outcomes. **Proactive** identifies plausible open loops, unresolved decisions and follow-ups, qualifying uncertainty. **Ideas for you** proposes concrete assistance the assistant can carry out (draft, build, research, compare, debug, prepare a deliverable), not just paraphrased history or generic inspiration. All model suggestions must cite a supplied anchor's exact session/message pair. Refresh is real tools-disabled model reflection, not a deterministic refresh disguised as analysis. No automatic paid analysis loop, tool execution, or unrequested recurring schedule is introduced.

## New assistant message notifications

Notifications observe all new user-visible final assistant messages in the connected profile, including Slack, CLI and API conversations. On first activation the bridge durably records `max(messages.id)` without importing old conversation messages. If `state.db` does not exist yet, activation occurs on its first successful read. Subsequent polls read ascending insertion IDs in batches of at most 200 rows. Each batch's notifications, seen IDs and cursor commit atomically to the companion database. A backlog is continued from the last consumed row on subsequent polls and restarts, never capped to its latest rows or silently skipped. Polling happens on state reads and every ten seconds; the API still returns only its newest 300 stored notifications.

Stable identity is `(session_id, message_uid)` when Hermes provides a UID, otherwise `(session_id, messages.id)`. Seen identities are durable across restarts; timestamps are not cursors, so late inserts with older timestamps are not lost. Hermes' actual schema uses AUTOINCREMENT integer IDs. Reasoning fields, tool calls/results, analysis/thinking/hidden/internal presentation rows, inactive rows, compressed summaries, known internal gateway/delegation wrappers, subagent/tool sessions and Woof's own `nudge-analysis` are excluded. Legacy non-tool assistant content without a finish reason is treated as final. Cron sessions remain covered by existing cron notifications rather than being imported twice.

Assistant content is preserved as the notification body (text blocks only, maximum existing 32,000 characters), without Slack envelope/provenance or reasoning appended. Provenance is returned separately as `session_id`, stable `message_id`, `source`, and raw `message_timestamp`; valid message timestamps become UTC ISO `created_at`. Actual companion request completions remain visible. When the stream message can be identified by the request's returned session ID and matching response, it is reconciled into the existing `request-ID` completion rather than double-imported; distinct messages and unmapped companion request sessions remain visible. If Hermes provides no distinguishing session identity, the bridge does not guess from body alone across sessions.

## Persistence and cron deduplication

Companion state is `<resolved-profile-home>/nudge/companion.sqlite3`. It stores notifications, requests, suggestions, history fingerprint, assistant high-water cursor, seen cron/message identities, notification provenance and returned request session mappings. Existing databases migrate automatically by adding companion-only tables; no token regeneration is required. Hermes session DB and cron stores are read-only from this backend; cron changes occur through the supported CLI.

Cron polling happens on state reads and every 10 seconds while the backend runs. Markdown output identities are `(job ID, filename)`, not body hashes: identical outputs from separate runs still produce separate notifications. Errors/delivery failures are keyed by job/run/status. Deduplication survives restart. Initial import is intentionally capped to the latest 20 output files per job; old outputs are not bulk-imported. The backend does not fabricate scheduler output or sample suggestions.

## Verification performed

Tests use temporary profile homes and explicit executable fixtures; all Hermes actions are mocked, with no real jobs or model requests. Coverage includes the original functional cases plus profile/environment isolation, executable discovery, authenticated bridge identity, exact remote Host/Origin policy, insecure bind refusal, TLS validation, direct TLS authentication and Secure cookies, reverse-proxy cookies, duplicate headers, timeout platform branches, scheduler markers and fail-closed tool-use rejection. The direct TLS test generates a temporary self-signed certificate using `openssl`; it is skipped if that optional test utility is absent. Production TLS needs only Python's standard library.

Watcher tests insert messages only into isolated temporary fixture databases: no old backfill, new final assistant import, preserved Slack content/provenance, exclusions, 32,000-character truncation, stable UID dedupe and restart, several bounded backlog batches, older timestamps and companion request reconciliation. Reflection tests verify concrete assistance/project/open-loop prompt instructions, outcome context, exact provenance validation and model-card preservation after new history. The connected profile's live `state.db` was inspected read-only for schema and aggregate metadata only, without printing transcripts or inserting synthetic messages.

To activate a deployment update, restart **only this bridge**, retaining its existing launch arguments, profile, token and companion database. For a selected profile the equivalent foreground command is `python3 -B backend.py --profile your-profile --hermes-home /path/to/hermes-home`; retain any existing `--hermes`, network or port overrides. Do not run a second listener on an occupied port. The first updated activation establishes the no-backfill checkpoint; later restarts resume it. No frontend rebuild or Hermes gateway/core restart is needed for these backend changes.

For a live deployment smoke check, start the bridge with explicit profile/home, fetch authenticated `/api/info`, verify identity and profile, then stop it. This does not require a model request, a new schedule or scheduler configuration changes.
