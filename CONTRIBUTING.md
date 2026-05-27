# Contributing to RelyLoop

Thanks for your interest in contributing! RelyLoop is an open-source project under Apache License 2.0, and we welcome contributions from the community.

This document explains how to set up a development environment, propose changes, and sign your commits under the Developer Certificate of Origin (DCO).

> **Status (alpha):** RelyLoop shipped MVP1 (`v0.1.0`) as alpha. APIs, schemas, and adapter contracts are still evolving — expect breaking changes between minor releases until v1.0 GA. Issues, design feedback, and pull requests are all welcome.

## Code of Conduct

A short kindness ask, not a long list of rules. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Concerns go to the contact in [MAINTAINERS.md](MAINTAINERS.md).

## Governance

Decision-making, who has merge rights, and the path to becoming a maintainer are in [GOVERNANCE.md](GOVERNANCE.md). RelyLoop is currently single-vendor-stewarded (all maintainers are soundminds.ai employees); the transition plan toward multi-organization maintainership is in that document.

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

The [DCO GitHub App](https://github.com/apps/dco) blocks merging until every commit on the PR is signed off. If you forget, the bot links you a one-click fix.

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

- Docker 24+ with Docker Compose v2
- Python 3.12+ (managed by `uv`; install [`uv`](https://docs.astral.sh/uv/) via Homebrew or the official installer)
- Node 18.17+ (Node 20 LTS recommended)
- pnpm 9+ (`corepack enable`)
- Git
- ~16 GB free disk space
- A laptop with 16 GB RAM (32 GB recommended)

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop
uv sync                                  # install Python deps + create .venv
pnpm --dir ui install                     # install frontend deps
make pre-commit-install                   # install pre-commit + commit-msg hooks
make up                                   # boot the Docker stack
```

The full local-development guide is [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md).

## Pre-commit hooks

RelyLoop enforces formatting, linting, type-checking, secret scanning, and Conventional Commits via [pre-commit](https://pre-commit.com). After cloning:

```bash
make pre-commit-install
```

This installs both `pre-commit` (file-quality checks: ruff, mypy, prettier, eslint, gitleaks, large-file guards) and `commit-msg` (Conventional Commits format) hooks.

To run all hooks against the entire repo (useful before pushing):

```bash
make pre-commit
```

**Never bypass hooks with `--no-verify` or `-n`.** If a hook fails, fix the underlying issue. Bypassing the Conventional Commits hook breaks the auto-changelog generation that lands at GA v1; bypassing gitleaks risks committing credentials.

### Verifying the gitleaks hook

To confirm secret scanning is wired correctly on your machine:

```bash
echo "AKIAIOSFODNN7EXAMPLE" > /tmp/fake-key.txt   # well-known AWS test key
git add /tmp/fake-key.txt 2>/dev/null || cp /tmp/fake-key.txt fake-key.txt && git add fake-key.txt
git commit -m "test(security): verify gitleaks rejects fake AKIA key"
# Expect: gitleaks blocks the commit with a "rule: aws-access-token" finding.
git restore --staged fake-key.txt && rm -f fake-key.txt   # clean up
```

The commit should be rejected by the `Detect hardcoded secrets` hook. If it isn't, run `make pre-commit-install` again or check `.git/hooks/pre-commit` exists.

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
3. Run tests locally (`make test`)
4. Push to your fork and open a PR against `main`. The PR template will prompt you for the right information.
5. CI runs lint, type-check, unit tests, contract tests, secret scanning, and frontend build
6. At least one maintainer review approval is required
7. Squash-merge by a maintainer once approved and CI is green

## Reporting issues

- **Bugs**: use the bug-report template in [`.github/ISSUE_TEMPLATE/bug_report.yml`](.github/ISSUE_TEMPLATE/bug_report.yml). Include reproduction steps, environment details, and logs.
- **Feature requests**: use the feature-request template at [`.github/ISSUE_TEMPLATE/feature_request.yml`](.github/ISSUE_TEMPLATE/feature_request.yml). Explain the use case and why existing functionality doesn't cover it.
- **Security vulnerabilities**: do **not** open a public issue. Follow the process in [SECURITY.md](SECURITY.md).

## Adding a new adapter

RelyLoop's engine, LLM provider, and Git provider adapters are designed for community extension. Each adapter:

- Implements the relevant Protocol in [`backend/app/adapters/`](backend/app/adapters/), [`backend/app/llm/`](backend/app/llm/), or [`backend/app/git/`](backend/app/git/)
- Passes the contract test suite in [`backend/tests/contract/`](backend/tests/contract/)
- Includes unit tests under [`backend/tests/unit/`](backend/tests/unit/) (use `pytest-recording` cassettes when exercising real HTTP)
- Documents auth flow, version support, and any quirks under [`docs/06_vendor_docs/`](docs/06_vendor_docs/)

See the spec ([`docs/00_overview/product/relevance-copilot-spec.md`](docs/00_overview/product/relevance-copilot-spec.md) §8 for engine adapters, §15 for LLM providers, §16 for Git providers) and the architecture-level adapters doc ([`docs/01_architecture/adapters.md`](docs/01_architecture/adapters.md)) for the full contracts.

## Maintainers and governance

- Current maintainer roster: [MAINTAINERS.md](MAINTAINERS.md)
- How decisions are made and how to become a maintainer: [GOVERNANCE.md](GOVERNANCE.md)

## Questions

For questions about the project direction, roadmap, or design choices, open a GitHub Discussion (once enabled). For specific implementation questions, open an issue.

Thank you for contributing.
