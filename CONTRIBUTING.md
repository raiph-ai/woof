# Contributing

Keep changes small; prefer standard-library server code and native browser controls. Preserve profile isolation, explicit approvals, authentication, and TLS checks. Never include real user transcripts, tokens, or local machine paths.

Run `npm test`, `python3 -B -m unittest test_backend -v`, and `node test-ui.cjs` (install Playwright Chromium first). On macOS also run `node verify-desktop.cjs`. Describe which checks actually ran. Do not claim native Windows/Linux desktop support without exercising it.

Before release, package the macOS app, ad-hoc sign for local tests or Developer ID sign/notarize for distribution, create and mount-test the DMG, verify SHA256 checksums, and test the packaged executable with an isolated client directory. No automatic publishing or credentials embedded in releases.
