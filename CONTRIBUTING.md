# Contributing to RelyLoop

Thanks for your interest in contributing! RelyLoop is an open-source project under Apache License 2.0, and we welcome contributions from the community.

This document explains how to set up a development environment, propose changes, and sign your commits under the Developer Certificate of Origin (DCO).

> **Status (alpha):** RelyLoop is pre-MVP1. We are not yet accepting external code contributions while the foundation is being built. Issues, design feedback, and discussions are welcome. Code-contribution guidelines below are forward-looking and will become active once MVP1 ships.

## Code of Conduct

This project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). All contributors are expected to follow it. Report any violations to the maintainers privately at the email listed in `CODE_OF_CONDUCT.md`.

## Developer Certificate of Origin (DCO)

RelyLoop uses the Developer Certificate of Origin instead of a CLA. By signing off on your commits, you certify that:

1. The contribution was created in whole or in part by you, and you have the right to submit it under the open-source license indicated in the file
2. You did not lift the contribution from a source whose license is incompatible with our license
3. You understand and agree that the contribution is public and that a record of it (including all personal information you submit with it) is maintained indefinitely

Read the full text at [developercertificate.org](https://developercertificate.org/).

To sign off a commit, add `Signed-off-by: Your Name <your.email@example.com>` to your commit message. The easiest way is to use `git commit -s`:

```bash
git commit -s -m "feat(adapter): add OpenSearch sigv4 auth"
```

CI rejects PRs whose commits are not signed off.

## Commit message format

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Format:

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

Common types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `perf`. Scope examples: `adapter`, `optuna`, `ui`, `api`, `worker`, `docs`.

Examples:

```
feat(adapter): add Lucidworks Fusion adapter
fix(worker): handle Optuna ask deadlock under high parallelism
docs(spec): clarify multi-tenancy isolation boundaries
chore(deps): bump structlog to 24.4
```

## Setting up a development environment

Prerequisites:

- Docker 24+ with Docker Compose
- Git
- ~16 GB free disk space
- A laptop with 16 GB RAM (32 GB recommended)

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop
docker compose up
```

The full local-development guide ships with MVP1. See `docs/08_guides/install.md` (forthcoming).

## Branching strategy

Trunk-based development:

- `main` is always releasable
- Feature branches are short-lived (target: <1 week)
- Branch names: `<type>/<short-description>` (e.g., `feat/fusion-adapter`, `fix/worker-deadlock`)
- Squash-merge PRs to keep `main` history linear and readable
- No force-pushes to `main`

## Pull requests

1. Fork the repo and create a feature branch from `main`
2. Make your changes with sign-off (`git commit -s`)
3. Run tests locally (`make test` once that target is in place)
4. Push to your fork and open a PR against `main`
5. CI runs lint, type-check, unit tests, contract tests, security scans
6. At least one maintainer review approval is required
7. Squash-merge by a maintainer once approved and CI is green

## Reporting issues

- **Bugs**: use the bug-report template in `.github/ISSUE_TEMPLATE/`. Include reproduction steps, environment details, and logs.
- **Feature requests**: use the feature-request template. Explain the use case and why existing functionality doesn't cover it.
- **Security vulnerabilities**: do **not** open a public issue. Follow the process in `SECURITY.md`.

## Adding a new adapter

RelyLoop's engine, LLM provider, and Git provider adapters are designed for community extension. Each adapter:

- Implements the relevant Protocol in `backend/adapters/`, `backend/llm/`, or `backend/git/`
- Passes the conformance test suite in `tests/contracts/`
- Includes unit tests with `pytest-recording` cassettes
- Documents auth flow, version support, and any quirks in `docs/06_vendor_docs/adapters/<name>.md`

See the spec (`docs/00_overview/product/relevance-copilot-spec.md` §8 for engine adapters, §15 for LLM providers, §16 for Git providers) for the full contracts.

## Maintainers

See `MAINTAINERS.md` for the current maintainer list and their areas of focus.

## Questions

For questions about the project direction, roadmap, or design choices, open a GitHub Discussion (once enabled). For specific implementation questions, open an issue.

Thank you for contributing.
