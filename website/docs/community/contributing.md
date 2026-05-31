# Contributing

!!! abstract "Summary"
    RelyLoop welcomes contributions under Apache 2.0. The authoritative guide
    is [`CONTRIBUTING.md`](https://github.com/SoundMindsAI/relyloop/blob/main/CONTRIBUTING.md)
    in the repo; this page is the orientation for first-time contributors.

!!! tip "Contributing with an AI agent?"
    RelyLoop is built agent-first and spec-driven. If you use Claude Code (or
    another agent), see **[Contributing with AI agents](contributing-with-agents.md)**
    for onboarding prompts, the skills, the spec → plan → implement pipeline,
    and how cross-model review works.

## First-time path

1. **Set up the dev environment.** You'll need Docker 24+ (Compose v2),
   Python 3.12+ (managed by [`uv`](https://docs.astral.sh/uv/)), Node 20 LTS +
   pnpm 9, and ~16 GB RAM.
   ```bash
   git clone https://github.com/SoundMindsAI/relyloop.git
   cd relyloop
   uv sync                          # Python deps + .venv
   pnpm --dir ui install            # frontend deps
   make pre-commit-install          # format / lint / commit hooks
   make up                          # boot the stack
   ```
2. **Pick something small first.** A docs fix, a test, or a clearly-scoped bug
   is the best way to learn the review loop.
3. **Branch and commit.** Short-lived feature branches off `main`, named
   `<type>/<short-description>`. RelyLoop uses
   [Conventional Commits](https://www.conventionalcommits.org/).
4. **Sign your commits (DCO).** RelyLoop uses the Developer Certificate of
   Origin instead of a CLA — every commit needs a `Signed-off-by:` trailer.
   Just commit with `-s`:
   ```bash
   git commit -s -m "feat(adapter): add Apache Solr adapter"
   ```
   A CI check and a local `commit-msg` hook both enforce it.
5. **Run the tests.** `make test` runs unit, integration, and contract layers.
6. **Open a PR against `main`.** The PR template prompts for what changed, why,
   and how you tested. CI runs lint, type-check, tests, secret scanning, and
   the frontend build; a maintainer reviews and squash-merges.

## Adding an adapter

RelyLoop's engine, LLM-provider, and Git-provider adapters are built for
community extension. Each implements a Protocol, passes the contract test
suite, and documents its auth flow and quirks. See the
[adapters architecture doc](https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/adapters.md)
and the spec's adapter sections.

## Code of Conduct

A short kindness ask, not a long rulebook —
[`CODE_OF_CONDUCT.md`](https://github.com/SoundMindsAI/relyloop/blob/main/CODE_OF_CONDUCT.md).

## Reporting issues

- **Bugs / feature requests** — use the issue templates on
  [GitHub Issues](https://github.com/SoundMindsAI/relyloop/issues).
- **Security vulnerabilities** — do **not** file a public issue; see
  [Security](security.md).
- **Questions / design discussions** — use
  [GitHub Discussions](https://github.com/SoundMindsAI/relyloop/discussions).
