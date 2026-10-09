# Developer guide

[Documentation home](index.md)

## Source map

- `main.cjs`: window lifecycle, pairing, authenticated fetch, source filtering, stable alert IDs, recent-state cache.
- `preload.cjs`: narrow renderer IPC.
- `client-core.cjs`: URL/token validation, compatible handshake, fetch/route limits.
- `shell-utils.cjs`: display bounds and panel placement.
- `backend.py`: stdlib bridge, profile discovery, read-only history, durable outcomes, reflection, scheduler integration.
- `web/app.js`: four panels and user actions; `settings.js`/`panels.js`: configuration and presentation.
- `web/notification-rules.js`: shared cutoff/source classification, with explicit Woof-created results bypassing unrelated cron source opt-outs.
- `web/custom-notifications.js`: Settings custom-schedule manager and verified edit/pause/resume/delete flows.
- `web/mascot.svg`/`mascot.js`: approved artwork, animation, badge, and audio playback.
- `scripts/build_mascot.py`: synchronize inline animated markup with the SVG.
- `scripts/trim_client.py`: strip generated non-English runtime locales, retaining English variants, ICU, graphics/audio libraries.
- `scripts/build_dmg.py`/`build_source.py`: installer and explicit allowlisted source archive.

## Prerequisites

Use Node 24, npm, Python 3.9+, and Playwright Chromium for source tests. Native packaging targets macOS arm64 and uses macOS `codesign`, `iconutil`, `sips`, and `hdiutil`. Python bridge runtime needs no pip dependencies. Hermes is required only for a real integration, not fixture-based tests.

```sh
npm ci
npx playwright install chromium
npm test
python3 -B -m unittest test_backend -v
node test-ui.cjs
npm start
```

The repository's Actions workflow runs portable unit/backend/browser-contract tests. Native Mac verification is separate; a green Linux job is not proof of native audio, Keychain, glass, dragging, or installer behavior.

## Native verification

```sh
node test-notification-prefs.cjs
node test-mascot-alerts.cjs
node test-fast-open.cjs
node test-reflection-errors.cjs
node test-custom-notifications.cjs
node test-workflows.cjs
node test-coaching-todos.cjs
node test-layout.cjs
node test-glass.cjs
node test-panels.cjs
node verify-token-controls.cjs
NUDGE_SESSION_ONLY=1 node verify-desktop.cjs
node verify-memory.cjs
```

Tests isolate client/profile directories. `NUDGE_TEST_APP` can select the packaged executable. Keychain-saving tests may need desktop authorization; do not call a hung headless attempt a pass. Real provider/job tests require explicit opt-ins and must not be enabled casually in CI.

## Build

```sh
python3 scripts/build_mascot.py
node create-icon.cjs
# Regenerate assets/Nudge.iconset from the verified raster if artwork changes,
# then run iconutil -c icns assets/Nudge.iconset -o assets/Nudge.icns.
npm run package
codesign --force --deep --sign - dist/Woof-darwin-arm64/Woof.app
python3 scripts/build_dmg.py
python3 scripts/build_source.py
```

The package command trims the generated English-only client. Build/test/source files and redundant assets are excluded from the native bundle; runtime JS/UI, sounds, license, and framework libraries remain. The source archive includes the full developer materials separately.

`create-icon.cjs` generates the PNG, not the entire Apple iconset automatically. Do not ship an old ICNS after changing only the SVG/PNG.

## Release gate

1. Bump package version and lockfile; update version references.
2. Run portable tests and relevant native regressions, including optimization review/error behavior, durable to-do reminders, and health-check action approval. Exercise model-backed optimization and read-only health checks against the real selected profile before claiming they work.
3. Package, trim, and sign after the final source change.
4. Test the signed executable, including actual playing/ended events, matching source audio, badge/animation, cutoff/dedupe, and cold reopen against slow HTTP.
5. Create/mount the DMG, verify strict signature and expected bundled files/version.
6. Run source privacy scan; exclude history, pairing/config files, binaries/vendor/cache folders from Git.
7. Produce checksums and a ZIP containing exactly the DMG; verify enclosed SHA256 matches the original.
8. Upload assets to the private release and read back repository visibility, release tag/assets, and main commit.

Signing is currently ad-hoc, not notarization. Do not remove graphics/audio libraries speculatively to shrink the app. Prefer measured cuts in redundant build material and unused locale resources over unsafe runtime stripping.

## Before public launch

Review audio licensing, private-data scans, release reproducibility, signed/notarized distribution, screenshots, onboarding, and security guidance. GitHub Pages is not a private documentation default. Public publication requires an explicit visibility decision.
