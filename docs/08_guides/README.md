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
- [`quick-tour.md`](quick-tour.md) — 10-minute click-through tour for a
  search-relevance engineer who has never seen the product. Skips the
  operator setup ceremony and goes straight to the value prop: the
  overnight optimization loop, the metric lift it produces, and the
  PR-based ship discipline. Pairs with `make seed-demo` (pre-bakes 4
  realistic scenarios). Use this instead of `tutorial-first-study.md`
  when you want a short narrative tour rather than a hands-on build.
  Presenter notes embedded as HTML comments.
- [`workflows-overview.md`](workflows-overview.md) — complete inventory of the
  30 distinct workflows a search engineer can execute in RelyLoop today,
  grouped by phase (setup → build relevance assets → run the loop → review
  and ship → conversational introspection → operate the stack).

## In-app walkthrough guides

Annotated screenshot decks rendered inside the UI via the
[`GuideViewer`](../../ui/src/components/guides/guide-viewer.tsx) component
and surfaced contextually by the floating
[`GuideTrigger`](../../ui/src/components/guides/guide-trigger.tsx) button.

Each guide is:
- **Captured** by a Playwright spec under [`ui/tests/e2e/guides/`](../../ui/tests/e2e/guides/)
  running against the live `make up` stack
- **Stored** under [`ui/public/guides/<NN_slug>/`](../../ui/public/guides/) —
  Next.js serves the PNGs directly with no copy step
- **Described** by a per-guide `metadata.json` (title, captions, screenshot
  order) consumed by the GuideViewer
- **Registered** in [`GUIDE_REGISTRY`](../../ui/src/components/guides/guide-types.ts)
  for the `/guide` catalog page + [`GUIDE_MAP`](../../ui/src/components/guides/guide-types.ts)
  for the floating-button route bindings

Shipped guides:

| # | Guide ID | Route prefix | Description |
|---|---|---|---|
| 01 | [`01_register_first_cluster`](../../ui/public/guides/01_register_first_cluster/) | `/clusters` | Add cluster → configure auth → verify health probe |
| 02 | [`02_review_a_proposal`](../../ui/public/guides/02_review_a_proposal/) | `/proposals` | Open pending proposal → read config diff → decide Open PR or Reject |
| 03 | [`03_create_query_template`](../../ui/public/guides/03_create_query_template/) | `/templates` | Author the Jinja2 query body + declared params → fork-to-v2 versioning |
| 04 | [`04_create_query_set`](../../ui/public/guides/04_create_query_set/) | `/query-sets` | Create a benchmark set → bulk-load queries via JSON or CSV |
| 05 | [`05_import_judgments_and_calibrate`](../../ui/public/guides/05_import_judgments_and_calibrate/) | `/judgments` | Skip LLM judgment generation via the import path → run Cohen's + linear-weighted κ calibration |
| 06 | [`06_create_and_monitor_study`](../../ui/public/guides/06_create_and_monitor_study/) | `/studies` | Configure a study → watch trials populate live → terminal state + cancel |
| 07 | [`07_browse_proposals`](../../ui/public/guides/07_browse_proposals/) | `/proposals` | Three-axis filter (status / source / cluster) → 30-second pulse-refetch for open PRs |
| 08 | [`08_chat_shell`](../../ui/public/guides/08_chat_shell/) | `/chat` | Conversation list → new chat → secrets warning banner |
| 09 | [`09_generate_judgments_llm`](../../ui/public/guides/09_generate_judgments_llm/) | `/query-sets`, `/judgments` | Trigger the LLM-as-judge worker → wait for terminal state → review populated judgments. Real OpenAI calls; ~$0.02 per run. |
| 10 | [`10_chat_with_agent`](../../ui/public/guides/10_chat_with_agent/) | `/chat` | Send a prompt → watch the SSE tool-call card render → read the assistant's final response. Real LLM, end-to-end. |

**Workflows still NOT covered by a guide:**

- **D4 (full) — Open PR end-to-end**: the trigger is captured in guide 02; the worker's GitHub interaction requires a registered config-repo + real PAT, which is operator-credential territory.
- **UBI judgment generation**: guide 09 covers the LLM-as-judge path; the UBI (click/dwell) alternative needs a cluster with captured behavior traffic, which is operator-data territory. See the [UBI judgment-generation runbook](../03_runbooks/ubi-judgment-generation.md) and the optional UBI upgrade step in [`tutorial-first-study.md`](tutorial-first-study.md).

### Adding or regenerating a guide

1. Write the Playwright spec at `ui/tests/e2e/guides/NN_<slug>.spec.ts`
   — write screenshots to `path.resolve(__dirname, '../../../public/guides/NN_<slug>')`
2. Run it: `cd ui && pnpm playwright test -c playwright.demo.config.ts NN_<slug>`
3. Write `ui/public/guides/NN_<slug>/metadata.json` (title, description,
   screenshots array with file + caption per slide)
4. Write `ui/public/guides/NN_<slug>/script.md` (narrative + reference links)
5. Register the guide in `GUIDE_REGISTRY` and `GUIDE_MAP` in
   `ui/src/components/guides/guide-types.ts`
6. The vitest test `guide-registry.test.ts` will assert metadata.json ↔
   registry parity — keep title and description in sync

Or invoke the [`guide-gen`](../../.claude/skills/guide-gen/SKILL.md) skill,
which does all six steps including cross-model visual review.

## Coming with later releases

- Production install guide (TLS via Caddy, managed Postgres + Redis) — MVP3
- SSO setup (oauth2-proxy / Authelia) — MVP4
- Multi-tenant onboarding — MVP4
