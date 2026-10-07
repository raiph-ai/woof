# Use Woof

[Documentation home](index.md)

## Mascot

Drag the wolf to reposition it. Click to show or hide panels. Right-click for panels, Settings, or Quit. Position is clamped to the display work area and saved.

The unread badge stays on the wolf. A newly arriving eligible notification triggers a brief tail wag and round open mouth. Seen IDs prevent repeated polling/restart from replaying the same alert. A batch produces one reaction rather than one sound per card. Reduced-motion settings suppress the wag.

At rest, the mouth is small and nearly neutral. The approved round-eye artwork uses closer-set eyes, small highlights, white/grey fur, and no blush, collar, or dog tag.

## Three panels

### Notifications

New user-visible final Hermes replies from the connected profile, companion task outcomes, and applicable scheduled-job results. Expand a card to read it; mark it read or dismiss it. The initial visible list is bounded and offers Show older notifications.

There is no old-conversation backfill on bridge activation. Existing saved companion records are additionally filtered by the desktop's persistent first-launch cutoff. Upgrading an already-initialized client keeps that cutoff.

### Proactive

Potential open loops, unresolved decisions, and follow-ups from conversation context. Suggestions are not verified obligations. Automatic fallback extraction is local and free of model calls; explicit reflection is different.

### Ideas for you

Concrete help Hermes can offer on projects described in prior conversations: drafts, research, comparisons, builds, debugging, and deliverables. Reflect on my history performs bounded tools-disabled model analysis. It does not silently execute the suggestions.

Both suggestion panels show counts of visible, non-dismissed cards. Expand the request preview before choosing Ask Hermes to help. That click authorizes a new Hermes request with ordinary tool approval rules.

## Notification source settings

Watchdog, heartbeat-style, and executed-cron results have independent switches, off by default. These are not interchangeable categories. Ordinary assistant replies and schedule-creation confirmations remain normal notifications. Casual discussion of monitoring does not turn a reply into a watchdog event.

Hidden sources do not inflate the badge or play alerts. Enabling a source reveals qualifying old cards quietly rather than sounding for all of them; subsequent newly arriving events can alert normally.

## Sound

- **Wolf bark:** the uploaded recording, decoded from MP3 to a compact 24 kHz mono WAV. Notifications and Preview use this same file, not the old synthesized default.
- **Little howl:** a short original synthesized effect.
- **None:** silent audio; the visual notification reaction remains.

Preview tests the selected sound without creating a notification. Muting stops an active preview. Selection persists independently of pairing. The sound is bundled locally and is not fetched from a website.

## Presentation

Default background opacity is 85%; only the background changes opacity. Text remains fully opaque. Zero reveals the underlying window; 100% is solid. There is no frosted-blur checkbox.

Each card can be dismissed. Acknowledge all acts on the current panel snapshot; notification acknowledgement marks those notifications read on the bridge. Dismissal is not task/job cancellation. Restore dismissed cards reverses desktop-local hiding.

Drag panel handles to reorder them, or use Option+Up/Down. Panel order and disclosure state persist. The main content area scrolls independently beneath the header.

## Reminders and tasks

New notification opens the scheduling form. Its cron mode accepts Hermes schedule syntax; heartbeat-style mode creates a recurring Hermes cron check, not a separate heartbeat-file engine. Scheduler execution still depends on the existing Hermes scheduler.

Scheduled check-ins and Sent to Hermes are not visible panels, although underlying scheduling/request APIs remain. Jobs continue running when cards are dismissed or Woof is hidden. API pause/resume/run capabilities remain in the bridge; the current UI does not expose the former dedicated job panel.

## Idle behavior

Visible panels poll every five seconds after each completed load. Hidden UI polling stops, and the hidden panel renderer is released after a 30-second grace period. Main-process badge checks continue once per minute. That means idle background arrival detection is not an instant push service.

Clicking after an alert displays the already-fetched state first, rather than repeating a slow server request before showing cards. Later normal polling refreshes it. This cache is memory-only, connection-scoped, and freshness-bounded.
