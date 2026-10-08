# Woof documentation

**Woof — your AI lookout.** A small white-and-grey desktop direwolf that keeps you aware of Hermes replies, task results, and useful next steps.

Current build: **0.3.7**, macOS Apple silicon. This repository is private. GitHub Pages is not enabled; the documentation is available only to people who can access this repository.

## Start here
- [Install and connect](setup.md): desktop installation, bridge deployment, pairing, and secure transport.
- [Use Woof](usage.md): panels, notification sources, sounds, reminders, and preferences.
- [How it works](architecture.md): client/server flow, message import, cache, and persistence.
- [Troubleshooting](troubleshooting.md): connection, audio, delayed panels, Keychain, and scheduler problems.
- [Developer guide](development.md): source map, tests, packaging, and release checklist.
- [Security and privacy](security.md): access boundaries, data handling, and deployment risks.
- [Roadmap and release history](roadmap.md): current scope, known gaps, and priorities.
- [Detailed bridge API and deployment reference](../README-backend.md).

## Private downloads

The [v0.3.7 release](https://github.com/raiph-ai/woof/releases/tag/v0.3.7) holds the Apple-silicon DMG, ZIP-wrapped installer, source archive, and checksums. Repository access is required. The build is ad-hoc signed, not Apple-notarized.

## What Woof is not

Woof is not a Hermes fork, a cloud-hosted agent, or an autonomous suggestion executor. It is a desktop companion connected to a small authenticated bridge beside an existing Hermes installation. It does not install, start, or reconfigure Hermes or its scheduler.
