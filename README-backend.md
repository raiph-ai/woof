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

- `notifications`: `{id,title,body,created_at,read,job_id?,custom?:true,session_id?,message_id?,source?,message_timestamp?}`
- `custom_notifications`: the same managed entries returned by `GET /api/custom` (see below)
- `proactive` and `ideas`: `{id,title,body,prompt,source?}`
- `todos`: the same non-deleted todo list returned by `GET /api/todos`
- `jobs`: `{id,name,schedule,enabled,last_status?}`
- `requests`: `{id,title,status,body}`
- `status`: `{profile,hermes_available,analysis_busy,coaching:{interval_minutes,timezone,last_checked_at,next_check_at,busy,last_error},health:{checked_at,busy,issues_count},scheduler:{heartbeat_at,heartbeat_age_seconds,heartbeat_fresh}}`

Scheduler diagnostics cheaply read the selected profile's `cron/ticker_heartbeat`, with no CLI call on every poll. Freshness means a marker no older than 180 seconds, not proof of a live PID or successful execution. Missing or invalid markers report null times and false freshness.

The newest 300 notifications and 100 requests are returned. Older records remain durable in the companion DB. Timestamps are UTC ISO strings. `hermes_available` means the configured executable exists and is executable, not a guarantee that provider credentials or scheduler are healthy.

| POST | Body | Success |
|---|---|---|
| `/api/schedule` | `{title,prompt,schedule,mode:"cron"\|"heartbeat"}` | HTTP 200 `{id,job,mode}` |
| `/api/custom-edit` | `{id,title,prompt,schedule,mode:"cron"\|"heartbeat"}` | HTTP 200 `{notification:managedEntry}` |
| `/api/custom-delete` | `{id}` | HTTP 200 `{id,deleted:true}` |
| `/api/request` | `{prompt,title?,source_session?}` | HTTP 202 `{id,status:"queued"}` |
| `/api/refresh` | `{}` | HTTP 202 `{id,status:"queued"}` or `{status:"running"}` |
| `/api/notification` | `{id,read:true}` | HTTP 200 `{id,read:true}` |
| `/api/job` | `{id,action:"pause"\|"resume"\|"run"}` | HTTP 202 `{id,status:"queued"}` (request ID) |

Async requests transition `queued` → `running` → `completed` or `error`. Poll `/api/state`; ordinary action results/errors also become durable notifications. Coaching and health outcomes are quiet request/status records, not notification spam. Invalid input is HTTP 400, unknown jobs/notifications HTTP 404, CLI/integration errors HTTP 502. Busy submission is HTTP 400. API errors have `{error: "..."}` bodies.

## Woof-owned custom notifications

Authenticated `GET /api/custom` returns `{notifications:[{id,title,prompt,schedule,mode,enabled,last_status,last_run_at,next_run_at,exists}]}`. `mode` is `cron` or `heartbeat`; status/timestamps may be null. Only non-deleted Woof-owned jobs appear. Ownership lives in the companion-only `managed_jobs` ledger, recorded after verified creation. Legacy migration accepts only an exact `created-JOBID` notification whose `job_id` is `JOBID` and whose body begins `Created Hermes schedule: `. Names, prompts and ordinary cron output never establish ownership. The legacy Email checkup creation confirmation can therefore be adopted on bridge activation without altering Hermes profile data.

The list reads current job metadata and retains a last-known snapshot for missing/completed jobs. Missing jobs remain listed with `exists:false`, `enabled:false` and `next_run_at:null`; unknown legacy prompts are empty strings, not invented. `POST /api/custom-edit` rejects missing, deleted and unrelated jobs. It uses supported `cron edit ID --name TITLE --prompt PROMPT --schedule SCHEDULE --deliver local`, then verifies the exact name/prompt, equivalent schedule, local delivery and unchanged enabled state. Interval verification compares canonical minutes so `every 2h` can read back as `every 120m`. Heartbeat creation/editing share the same positive m/h/d interval validation. The `[heartbeat-style]` title and explanatory prompt prefix are applied once; switching to cron removes these wrappers.

`POST /api/custom-delete` accepts owned IDs only, uses `cron remove ID` if the job exists, verifies its absence, and tombstones the ledger row. Already missing/completed owned jobs can be tombstoned without a CLI call; repeated tombstoned deletes are safe. Notification history and ownership are never deleted. Historical/new result notifications carry `custom:true` only when their exact `job_id` is in this ledger, including tombstones. Unrelated cron notifications omit `custom` entirely. This lets clients show custom results without turning on their global cron source. Polling also checks owned output directories for jobs no longer in the cron store, preserving completed one-shot results. Generic `/api/job` pause/resume/run remains unchanged and profile-wide.

## Real Hermes integration

All calls explicitly use the configured executable, profile and home. No shell interpolation, `shell=True`, `--yolo`, core edits, or configuration edits are used. Prompts for immediate requests are passed on stdin via `--query-file -`, not exposed in process arguments. Requests use `chat -Q --oneshot --max-turns 8 --run-budget 120 --source nudge-request --format stream-json`. Hermes tool approvals remain in force. Requests are new sessions; `source_session` is provenance in the prompt, not an automatic continuation of a possibly stale conversation.

Scheduling uses supported `cron create SCHEDULE PROMPT --deliver local --name TITLE`, followed by a read-back of the exact job. User submissions create enabled jobs. `heartbeat` is explicitly a **heartbeat-style interval check implemented as Hermes cron**, not a native heartbeat feature; interval shorthand such as `30m` becomes `every 30m`. Cron mode preserves the installed Hermes semantics (`30m` or `every 2h` repeating, `in 30m` once, an ISO timestamp, or a cron expression). No recurring Hermes jobs are created on backend startup; the bridge loop performs the separately documented read-only daily health probe. Existing profile jobs are displayed; pause/resume/run accept only exact IDs found in that profile store. Pause/resume effects are read back. Manual run may execute immediately or be queued by Hermes for its next scheduler tick; the CLI outcome is preserved.

Scheduled jobs require an existing Hermes scheduler/gateway serving the selected profile. Nudge observes but does not start or reconfigure that scheduler. Local delivery means results are observed from the profile's cron output/status, not sent to messaging platforms.

Request subprocesses have an outer 150-second timeout; optimization/health analysis 90 seconds; contextual coaching 150 seconds with a per-run low-reasoning override and concise JSON output, leaving the selected provider/model unchanged; cron create/pause/resume 45 seconds and manual run 180 seconds. POSIX timeouts kill the process group; Windows attempts native `taskkill /T /F` process-tree termination, then kills the child directly as a fallback. Pipe draining is bounded. Errors persist without retrying actions that might partly have succeeded. Three concurrent async tasks are allowed. Interrupted queued/running requests are marked error after restart rather than replayed.

## Proactive coaching and Ideas for You

Authenticated `GET /api/coaching-settings` returns exactly `{interval_minutes,timezone,last_checked_at,next_check_at,busy,last_error}`. Defaults are **120 minutes** and `UTC`. `POST /api/coaching-settings` accepts `{interval_minutes:integer,timezone?:IANA}`; range is 15–1440 minutes inclusive, booleans/floats/strings are rejected. An omitted timezone retains its saved value. Saving returns durable readback and makes **no model call**. Times are UTC ISO strings; `last_checked_at` means the last attempted/quiet check, not proof of model success. `last_error` is null or a safe failure summary; `busy` matches `status.analysis_busy`.

The ten-second bridge loop runs the same coach as manual `POST /api/refresh`. Automatic coaching waits the configured interval from first activation or the last attempt; the first-activation anchor, last attempt, settings and errors persist across restart. Changing interval recalculates next due from that existing anchor/attempt, not from the save time: shortening may make a check due at the next loop tick, lengthening postpones it. Downtime catches up with one check, never a replay burst. Failed provider/validation/queue attempts also advance the cadence, preventing retry storms. Manual refresh bypasses due time and returns HTTP 202 `{id,status:"queued"}` or `{status:"running"}` under the shared busy guard. This does not create Hermes cron jobs, execute repairs or mutate user jobs.

**Cost and privacy:** each non-quiet due/manual coaching run sends bounded private context to the connected profile's selected provider/model and can incur model costs. Choosing 15 minutes permits more frequent paid calls than the 120-minute default. Unchanged context can still be reflected on at its cadence; this is not a free local-only feature. A quiet check with no eligible conversation, notification or pending todo skips the provider, saves empty panels, and records an honest quiet result. State/settings reads and settings saves never trigger a paid coaching call. Daily health connectivity probing is separate and retains its independent 24-hour cadence.

Context covers the last 36 hours with real timestamps and a previous-evening marker in the configured timezone. Up to eight anchors are reserved from the previous local evening (18:00 through 06:00) plus up to sixteen newest anchors, deduplicated. SQLite history reads use `mode=ro` plus `PRAGMA query_only`. Active human messages and one visible final assistant outcome per anchor are included, excluding companion/nudge/analysis/cron/subagent/tool sources, hidden sessions, injected display rows and compressed summaries when present. Outcome search is bounded to eight rows and excludes future timestamps. Excerpts are at most 1,200 characters, sharing at most 12,000 text characters across the two selections. The unchanged `recent_history()` defaults remain compatible with existing callers; time bounds are optional.

Recent context also includes up to twelve meaningful ordinary user-visible companion notifications/request outcomes (`job_id:null`), owned schedule results and todo reminders, plus up to sixteen pending, non-deleted todos. Unrelated cron output, creation confirmations, watchdog/heartbeat and polling/health-check noise, and exact silent tokens are filtered **before** notification limiting. Notification bodies are excerpts of at most 1,000 characters and task details at most 800. Each of those categories has a 4,500-character serialized cap so conversations retain room. All supplied context, including IDs/metadata, shares a hard 24,000-character serialized budget. The prompt explicitly says this is bounded partial coverage, never “all recent conversations reviewed.”

**Proactive** identifies evidence-based things needing attention, patterns, plausible open loops, unresolved decisions and useful coaching next steps. **Ideas for You** explores divergent personal/project potential: marketing angles, bug-test strategies, product opportunities, customer research, or useful health routines/questions where relevant—not only email triage or paraphrased repeated asks. Reflection considers completed outcomes, distinguishes facts from possibilities, and must not invent obligations, deadlines or medical diagnoses. All history and external content is untrusted DATA, never instructions. Empty panels are valid when nothing useful is supported.

Analysis uses the existing real `chat(analysis=True)` adapter: `-t none --ignore-rules --max-turns 1 --run-budget 60 --source nudge-analysis`, a 90-second outer timeout, and rejection of any tool-use event. The explicit unknown `none` toolset resolves to zero schemas on the supported Hermes chat path; an empty toolset flag would fall back to configured tools. Hermes may emit an `Unknown toolsets: none` warning. This behavior is version-sensitive and should be retested when upgrading Hermes.

Structured output is `{proactive:[],ideas:[]}`, at most five cards per panel. Every card retains the existing `{id,title,body,prompt,source}` UI contract and must cite precise supplied provenance: conversation `{kind:"conversation",session_id,message_id}` (user anchor or supplied assistant outcome), notification `{kind:"notification",id}`, or todo `{kind:"todo",id}`. Multiple references are allowed (maximum six); every one must validate against the exact context. Legacy `source_session,message_id` conversation-pair output is still accepted. Fabricated IDs, cross-source ID swaps, malformed JSON and provider errors fail closed: **last successful cards are preserved**, `status.coaching.last_error` is visible and the request ends in error. No deterministic fallback silently replaces reflection.

Automatic and manual coaching update cards/request outcomes without notification spam. State reads and restarts preserve saved reflection until the next actual coach check. Cards never execute anything automatically; only explicit user `/api/request` dispatch invokes normal Hermes actions/approvals. Independently persisted daily health findings merge into `proactive` without replacing coaching cards.

## New assistant message notifications

Notifications observe all new user-visible final assistant messages in the connected profile, including Slack, CLI and API conversations. On first activation the bridge durably records `max(messages.id)` without importing old conversation messages. If `state.db` does not exist yet, activation occurs on its first successful read. Subsequent polls read ascending insertion IDs in batches of at most 200 rows. Each batch's notifications, seen IDs and cursor commit atomically to the companion database. A backlog is continued from the last consumed row on subsequent polls and restarts, never capped to its latest rows or silently skipped. Polling happens on state reads and every ten seconds; the API still returns only its newest 300 stored notifications.

Stable identity is `(session_id, message_uid)` when Hermes provides a UID, otherwise `(session_id, messages.id)`. Seen identities are durable across restarts; timestamps are not cursors, so late inserts with older timestamps are not lost. Hermes' actual schema uses AUTOINCREMENT integer IDs. Reasoning fields, tool calls/results, analysis/thinking/hidden/internal presentation rows, inactive rows, compressed summaries, known internal gateway/delegation wrappers, subagent/tool sessions and Woof's own `nudge-analysis` are excluded. Legacy non-tool assistant content without a finish reason is treated as final. Cron sessions remain covered by existing cron notifications rather than being imported twice.

Assistant content is preserved as the notification body (text blocks only, maximum existing 32,000 characters), without Slack envelope/provenance or reasoning appended. Provenance is returned separately as `session_id`, stable `message_id`, `source`, and raw `message_timestamp`; valid message timestamps become UTC ISO `created_at`. Actual companion request completions remain visible. When the stream message can be identified by the request's returned session ID and matching response, it is reconciled into the existing `request-ID` completion rather than double-imported; distinct messages and unmapped companion request sessions remain visible. If Hermes provides no distinguishing session identity, the bridge does not guess from body alone across sessions.

## Persistence and cron deduplication

Companion state is `<resolved-profile-home>/nudge/companion.sqlite3`. It stores notifications, requests, suggestions, history fingerprint, assistant high-water cursor, seen cron/message identities, notification provenance and returned request session mappings. Existing databases migrate automatically by adding companion-only tables; no token regeneration is required. Hermes session DB and cron stores are read-only from this backend; cron changes occur through the supported CLI.

Cron polling happens on state reads and every 10 seconds while the backend runs. Markdown output identities are `(job ID, filename)`, not body hashes: identical unrelated-job outputs from separate runs still produce separate notifications; owned successful results use the additional conservative suppression below. Errors/delivery failures are keyed by job/run/status. Deduplication survives restart. Initial import is intentionally capped to the latest 20 output files per job; old outputs are not bulk-imported. The backend does not fabricate scheduler output or sample suggestions.

## Action-based alerts, todos and health

All routes below use the same authentication, Host/Origin policy and JSON/body bounds as the existing API.

| Route | Input | Result |
|---|---|---|
| `POST /api/optimize` | `{title,prompt,schedule,mode,id?}` | HTTP 200 `{title,prompt,schedule,mode,alert_when,summary,method:"agent"}` |
| `GET /api/todos` | — | HTTP 200 `{todos:[todo]}` |
| `POST /api/todo-save` | `{id?,title,details?,due_date,reminder_at?,timezone?}` | HTTP 200 `{todo}` |
| `POST /api/todo-action` | `{id,action:"complete"\|"reopen"\|"delete"}` | HTTP 200 `{todo}` or `{id,deleted:true}` |
| `POST /api/health-check` | `{}` | HTTP 202 `{id,status:"queued"}` or `{status:"running"}` |
| `POST /api/health-action` | `{id}` | HTTP 202 `{id,status:"queued"}` for an unresolved request-kind health issue |

Optimization is one bounded synchronous real `chat(analysis=True)` call, using the same zero-tool analysis contract and 90-second outer timeout. It does not create/edit jobs or mutate the companion ledger. Schedule and mode must match the input exactly. Provider failure, malformed output or altered schedule fails rather than returning a fabricated rewrite. Output limits are 180 characters for title, 14,000 for the agent prompt (plus a short mandatory safety contract), and 1,000 each for alert criteria and summary. Supplying `id` permits at most three bounded result samples only from an existing active managed-owned job. No arbitrary session/history/profile data is sampled.

Alert instructions prioritize concrete new/actionable findings, including email sender, subject, useful links, significance and next step. Unchanged previously reported findings should return the native Hermes token `[SILENT]`, not repetitive summaries. Permission, credential, tool and provider failures must be reported as real problems. The optimizer cannot create permissions, assume account access, enable integrations, send/delete mail or purchase. Runtime checks use existing connections with normal tool approval.

After reviewing the optimized editor output, the client sends `optimized:true` on `/api/schedule` or `/api/custom-edit`. This optional field must be boolean. Only true adds supported `--continuity`; readback must confirm `context_from` includes `self`, and editing must preserve other existing references. Ordinary legacy payload behavior is unchanged. No migration or poll enables continuity or edits existing jobs. Continuity lets the scheduled model compare its own preceding result, including paraphrased-but-unchanged findings; the bridge itself performs only conservative exact normalized-content deduplication, not semantic inference.

Owned cron outputs import only the last recognized response section (`Response`, `Agent Response`, `Assistant Response`, or legacy `Result`/`Output` heading). Reads are bounded at 256 KiB before extracting the 32,000-character notification body. State reads also clean previously stored owned cron-output bodies, recovering a formerly truncated response from its original output file when available. Only output identities establish eligibility; unrelated jobs and status/error notifications are not rewritten. New owned successful exact `[SILENT]` or `WOOF_NO_CHANGE` responses are quietly checkpointed. Repeated normalized successful responses are suppressed; changed findings and known failure/error outputs remain visible. Seen keys and last-success fingerprints survive restarts.

A todo is `{id,title,details,due_date,reminder_at,timezone,status,reminded_at}`. Status is `pending` or `completed`. Title is at most 180 characters; details at most 4,000. `due_date` requires a real `YYYY-MM-DD` calendar date; it is independent of the reminder. Timezone defaults to `UTC` and must be an IANA zone available on the host. `reminder_at` is null or a timezone-aware ISO datetime, stored canonically in UTC. New/changed non-null reminders must be future times. Editing other fields preserves an emitted reminder; changing its future time rearms it. Complete/delete cancel pending delivery; reopen retains reminder emission history. Delete tombstones the todo and preserves notifications.

Reminders use a stable ID per todo/time and atomically persist the ordinary `custom:true` notification together with `reminded_at`. They fire once across restart and catch up after downtime, without any Hermes model/job or executable/history requirement. The existing client notification pipeline determines the user's selected woof/howl/none sound; the backend never chooses or overrides sound.

`/api/state.status.health` is `{checked_at,busy,issues_count}`. The bridge loop queues one read-only health check per 24 hours, using a durable start checkpoint and in-process busy guard; explicit manual checks can run sooner. A healthy check creates no notification/card. Checks inspect executable availability, scheduler heartbeat freshness when schedules are enabled, failed owned jobs, and persisted failed companion actions (explicitly qualified as potentially historical). When the CLI exists, one tools-disabled bounded provider probe tests the selected profile's model/auth connectivity. Failures produce observed-fact cards, never token/log dumps or invented repairs.

Health issues persist separately from conversation suggestions, merging into `proactive` without replacing either suggestion panel. Cards are `{id,title,body,prompt,source:"agent-health",action:{label,kind:"request"|"settings"}}`. Request-kind solutions diagnose the observed issue, scope repair to this profile, preserve user jobs/permissions, require ordinary Hermes approvals and verify the result; they do not assume an OS/service manager. Only an explicit valid `/api/health-action` click queues the stored prompt through the ordinary request path. Settings-kind cards give manual bridge/provider remediation when the CLI/model is unavailable, and cannot queue a pretend model repair. A later successful health check resolves absent issues. Daily checks never repair anything automatically.

## Bridge polling overhead

State reads use companion-only `created_at` indexes for the newest 300 notifications and 100 requests, and join provenance in the notification query instead of issuing up to 300 additional lookups. Index creation is an idempotent startup migration; it retains every record and does not touch Hermes' database. It costs extra companion disk space and index maintenance on writes.

Assistant polling streams its existing insertion-ID batch rather than holding all 200 message bodies/reasoning rows in memory. Excluded roles/sessions are rejected before content parsing. The final consumed ID still commits atomically with imported notifications, including skipped rows; rollback and restart resume the same durable cursor. Custom metadata parses the saved snapshot once rather than twice.

No response/history/file cache or new timer is added: every state read still observes current SQLite/job files. The ten-second background poll, reminders, 120-minute default coaching interval, daily health interval, tools-disabled analyses, and provider/model configuration are unchanged. API JSON serialization/body size and full cron-directory enumeration remain costs. Existing cron behavior still examines only the latest 20 filenames per job on each poll; more than 20 new outputs between polls can leave older unseen files unimported. This optimization does not introduce a new history/task cap or alter that existing cron policy. Assistant backlogs remain lossless 200-row checkpoint batches, and todos/owned-task lists remain uncapped.

A local isolated benchmark (Python stdlib, no provider/job calls) used 5,000 history rows, 12,000 notifications with provenance, 12,000 completed requests, and 4,800 cron result files. Twelve authenticated HTTP state samples after warm-up measured median **210.19 ms before / 55.54 ms after** (ranges 208.02–241.29 / 55.00–58.18 ms). Companion SQL statements per state dropped **396 → 96**. Traced peak Python allocation for a 200-row excluded-message batch dropped **3,365,054 → 38,449 bytes**; batch time was 6.99 → 6.38 ms. Steady-state traced peak remained 1,358,681 bytes, with unchanged 722,874-byte JSON responses. These are fixture measurements, not process RSS or a production latency guarantee; first-start index creation and cold disk behavior are not included. The still-running, unmodified deployment measured 12.12 ms median across eight authenticated reads; updated deployment timing requires the separately managed bridge restart.

## Verification performed

Tests use temporary profile homes and explicit executable fixtures; provider/job actions are mocked, and a temporary executable exercises the real subprocess analysis adapter without a model request or real job. Coverage includes the original functional cases plus profile/environment isolation, executable discovery, authenticated bridge identity, exact remote Host/Origin policy, insecure bind refusal, TLS validation, direct TLS authentication and Secure cookies, reverse-proxy cookies, duplicate headers, timeout platform branches, scheduler markers and fail-closed tool-use rejection. The direct TLS test generates a temporary self-signed certificate using `openssl`; it is skipped if that optional test utility is absent. Production TLS needs only Python's standard library.

Watcher tests insert messages only into isolated temporary fixture databases: no old backfill, new final assistant import, preserved Slack content/provenance, exclusions, 32,000-character truncation, stable UID dedupe and restart, several bounded backlog batches, older timestamps and companion request reconciliation. Reflection tests verify concrete assistance/project/open-loop prompt instructions, outcome context, exact provenance validation and model-card preservation after new history. The connected profile's live `state.db` was inspected read-only for schema and aggregate metadata only, without printing transcripts or inserting synthetic messages.

Tests also cover companion-only custom ownership migration from exact creation records, verified create/edit with canonical intervals, mode prefix handling, authenticated only-owned management, failed readbacks, unrelated-job rejection, delete idempotence/tombstones, historical custom classification, and missing/completed job outputs.

To activate a deployment update, restart **only this bridge**, retaining its existing launch arguments, profile, token and companion database. For a selected profile the equivalent foreground command is `python3 -B backend.py --profile your-profile --hermes-home /path/to/hermes-home`; retain any existing `--hermes`, network or port overrides. Do not run a second listener on an occupied port. The first updated activation establishes the no-backfill checkpoint; later restarts resume it. No frontend rebuild or Hermes gateway/core restart is needed for these backend changes.

For a live deployment smoke check, start the bridge with explicit profile/home, fetch authenticated `/api/info`, verify identity and profile, then stop it. This does not require a model request, a new schedule or scheduler configuration changes.
