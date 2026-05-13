# Guides

Tutorials, install docs, migration notes, FAQs, and cookbook-style how-to
content for RelyLoop operators.

## MVP1

- [`tutorial-first-study.md`](tutorial-first-study.md) — the canonical
  30-minute walkthrough from `git clone` through "PR opened in GitHub":
  bring up the stack, seed sample data, generate LLM judgments, run a
  10-trial Optuna study, read the digest, open a PR against the public
  config repo. Same operator path the CI smoke test exercises.
  (`chore_tutorial_polish`)

## Coming with later releases

- Production install guide (TLS via Caddy, managed Postgres + Redis) — MVP3
- SSO setup (oauth2-proxy / Authelia) — MVP4
- Multi-tenant onboarding — MVP4
