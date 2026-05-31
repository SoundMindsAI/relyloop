# Contributing with AI agents

!!! abstract "Summary"
    RelyLoop is built agent-first and **spec-driven**: every change starts as a
    reviewed specification, and code is implemented *from* that approved spec —
    not the other way around. The repo ships a set of **Claude Code skills**
    that drive features from idea → spec → plan → implementation → PR, with
    cross-model review built in. This page shows how to point your agent at the
    codebase, which skills to use, how the `planned_features/` →
    `implemented_features/` workflow operates, and what changes if you run
    Claude Code without a second model.

## We assume Claude Code — but you're not locked in

RelyLoop's contribution workflow is built around
[Claude Code](https://claude.com/claude-code) and the committed skills in
[`.claude/skills/`](https://github.com/SoundMindsAI/relyloop/tree/main/.claude/skills).
If you use Claude Code, everything below works out of the box.

!!! tip "Using Codex, Cursor, or another agent?"
    You're welcome here too. The skills are Markdown playbooks — they encode
    *process*, not Claude-specific magic — so you can read them and follow the
    same steps manually in any agent. Even better: **if you want to port the
    skills to a Codex-friendly (or other-agent) format, we'll happily accept
    that Pull Request.** Open an issue first so we can agree on where the
    ported skills live and how they stay in sync with the canonical ones.

You can also contribute the old-fashioned way — read
[CONTRIBUTING.md](https://github.com/SoundMindsAI/relyloop/blob/main/CONTRIBUTING.md),
write the code by hand, and open a PR. The agent workflow is an accelerant,
not a requirement.

## This is spec-driven development

RelyLoop is developed **spec-first**. You don't start by writing code — you
start by writing down *what* should be true, get that reviewed, and only then
implement it. The pipeline is the embodiment of that discipline:

- An **idea** captures the problem and rough shape.
- A **spec** (`feature_spec.md`) turns it into a precise contract — API shapes,
  data model, error codes, acceptance criteria, non-goals. This is the durable
  source of truth, and it's reviewed (including by a second model) *before any
  code exists*, so design mistakes get caught while they're still cheap to fix.
- A **plan** (`implementation_plan.md`) decomposes the spec into ordered,
  independently verifiable stories.
- **Implementation** executes the plan story-by-story, and each story's tests
  assert the spec's acceptance criteria — so the code is verified *against the
  spec*, not just "does it run."

The payoff for a contributor: the hard thinking happens in prose, where it's
fast to review and cheap to change, and the agent does the mechanical
implementation against an agreed contract. That's also why the pipeline pauses
for your approval between stages — you sign off on the *spec* and the *plan*
before any implementation effort is spent.

Two levels of spec, same idea: `CLAUDE.md` is the standing specification for
the *whole project* (its conventions and Absolute Rules); each `feature_spec.md`
is the specification for *one change*.

## Step 1 — Teach your agent the codebase

RelyLoop keeps three compressed-context files at the repo root that are
designed to bootstrap an agent fast. Start every session by having your agent
read them. Suggested opening prompts:

=== "Orient"

    ```text
    Read CLAUDE.md, architecture.md, and state.md at the repo root, then
    summarize: (1) what RelyLoop is and its engine-adapter boundary, (2) the
    release matrix and where we are now, (3) the current active branch and
    in-flight work, and (4) every "Absolute Rule" I must never violate. Be
    concise — I'll ask follow-ups.
    ```

=== "Learn the conventions"

    ```text
    From CLAUDE.md, summarize the rules I'll trip over as a new contributor:
    the secrets-via-mounted-files rule, the SearchAdapter Protocol boundary,
    the testing layers and the 80% coverage gate, Conventional Commits, and
    the DCO sign-off requirement. Show me the exact commit command I should
    use.
    ```

=== "Find a first task"

    ```text
    Run /pipeline status to list every planned feature in priority order.
    Recommend a good first contribution for someone new to the codebase,
    explain its dependencies, and tell me which pipeline stage it's at.
    ```

=== "Understand one feature"

    ```text
    Read the idea/spec/plan docs under
    docs/00_overview/planned_features/02_mvp2/<feature>/ and tell me what's
    already specced, what design questions are still open, and what the next
    pipeline stage is.
    ```

These work because [`CLAUDE.md`](https://github.com/SoundMindsAI/relyloop/blob/main/CLAUDE.md)
is the authoritative rulebook, `architecture.md` is the system map, and
`state.md` is a one-page snapshot of current reality (active branch, last
merges, known debt). Point the agent at those before it writes anything.

## Step 2 — Use the skills

The skills live in
[`.claude/skills/`](https://github.com/SoundMindsAI/relyloop/tree/main/.claude/skills)
and are invoked by typing `/<skill-name>` in Claude Code. They move a feature
through a fixed pipeline:

```
  idea.md ──▶ /spec-gen ──▶ /impl-plan-gen ──▶ /impl-execute ──▶ merged PR
    IDEA         SPEC            PLAN              IMPLEMENT         DONE
```

| Skill | What it does | Example |
|---|---|---|
| **`/pipeline`** | Orchestrates the whole flow; detects the current stage and advances it. | `/pipeline status` · `/pipeline docs/00_overview/planned_features/02_mvp2/feat_my_thing` |
| **`/idea-preflight`** | Audits an `idea.md` against the live codebase before the pipeline runs — verifies file paths, counts, and claims; patches drift. | `/idea-preflight docs/00_overview/planned_features/02_mvp2/feat_my_thing/idea.md` |
| **`/spec-gen`** | Turns an approved idea into a `feature_spec.md`, with cross-model review. | `/spec-gen docs/00_overview/planned_features/02_mvp2/feat_my_thing/idea.md` |
| **`/impl-plan-gen`** | Turns the spec into a story-by-story `implementation_plan.md`, cross-model reviewed. | `/impl-plan-gen .../feat_my_thing/feature_spec.md` |
| **`/impl-execute`** | Implements the plan story-by-story with verification gates, opens the PR, watches CI, adjudicates review comments. | `/impl-execute .../feat_my_thing/implementation_plan.md --all` |
| **`/bug-fix`** | Drives a bug through CLAUDE.md's Bug Fix Protocol (reproduce → root-cause → regression test → fix). | `/bug-fix docs/00_overview/planned_features/02_mvp2/bug_my_bug` |
| **`/guide-gen`** | Generates/audits tenant-facing walkthrough guides with screenshots. (Run automatically by `/impl-execute` post-implementation.) | `/guide-gen` |

!!! example "The fast path for a new feature"
    ```text
    # 1. Write a short idea.md under the right bucket (see below), then:
    /idea-preflight docs/00_overview/planned_features/02_mvp2/feat_my_thing/idea.md

    # 2. Run the whole pipeline, pausing for your approval between stages:
    /pipeline docs/00_overview/planned_features/02_mvp2/feat_my_thing

    # ...or run a single stage at a time:
    /spec-gen      .../feat_my_thing/idea.md
    /impl-plan-gen .../feat_my_thing/feature_spec.md
    /impl-execute  .../feat_my_thing/implementation_plan.md --all
    ```
    `/pipeline … --auto` runs end-to-end without inter-stage approval — but the
    verification gates, test suites, and cross-model review still run; those
    are hard gates, not skippable.

!!! example "Fixing a bug"
    ```text
    /bug-fix docs/00_overview/planned_features/02_mvp2/bug_chat_truncation
    ```
    The skill reproduces the bug first, traces it to the right layer, writes a
    focused bug-fix doc, implements the fix **with a regression test**, and
    (with `--ship`) takes it through the PR ceremony.

## Step 3 — Understand the directory structure

Feature work lives in two sibling trees under
[`docs/00_overview/`](https://github.com/SoundMindsAI/relyloop/tree/main/docs/00_overview):

### `planned_features/` — work not yet shipped

Organized into **MVP-grouping buckets**, each holding feature folders:

```
docs/00_overview/planned_features/
  00_unsure/        # scope not yet decided
  01_mvp1/          # (MVP1 shipped — now empty/historical)
  02_mvp2/          # current release in progress
  03_mvp3/          # next release
  04_ga/            # GA v1
  99_backlog/       # captured, not scheduled
  feature_templates/  # idea / spec / plan templates
```

Each feature folder uses a **single-axis work-type prefix** so its intent is
obvious at a glance:

| Prefix | Meaning |
|---|---|
| `feat_` | new product capability |
| `infra_` | tooling, CI, test framework, deploy infra |
| `chore_` | non-feature cleanup (debt, doc rot, naming) |
| `bug_` | a defect / regression |
| `epic_` | a multi-feature umbrella |

A folder accumulates artifacts as it moves through the pipeline:
`idea.md` → `feature_spec.md` → `implementation_plan.md`. Start from the
templates in
[`feature_templates/`](https://github.com/SoundMindsAI/relyloop/tree/main/docs/00_overview/planned_features/feature_templates).

### `implemented_features/` — shipped work

When a feature merges, its folder is **finalized and moved** to a flat,
date-prefixed location:

```
docs/00_overview/implemented_features/
  2026_05_31_infra_adapter_solr/
  2026_05_29_feat_ubi_judgments/
  ...
```

This is the historical record. The [Roadmap](../roadmap.md) is generated
directly from these two trees, so it always reflects reality. The internal
[`MVPn_DASHBOARD.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/00_overview/MVP2_DASHBOARD.md)
files (also generated) give the full engineering view — priorities,
dependencies, and debt.

## Step 4 — Cross-model review

RelyLoop's quality bar leans on **a second model checking the first**. Two
mechanisms, at two stages:

1. **Specs and plans — Opus ↔ GPT-5.5.** `/spec-gen` and `/impl-plan-gen`
   send the artifact to **GPT-5.5** (model `gpt-5.5`, via the OpenAI API) for
   an independent review. Opus 4.x *creates*; GPT-5.5 *reviews*. Opus then
   adjudicates each finding (accept / reject with cited counter-evidence /
   defer) and re-reviews if a major element changed — up to three cycles. The
   value comes from a **different model family** catching the primary model's
   blind spots.
2. **Code — Gemini on the PR.** When `/impl-execute` opens a Pull Request,
   **Gemini Code Assist** posts a review, and the skill adjudicates every
   line-level finding with the same accept/reject/defer rubric before merge.

The GPT-5.5 key is read from the project `.env`
(`OPENAI_API_KEY`) — it is never required to *boot* the stack, only to run the
spec/plan review.

### What if I only have Claude Code (no GPT-5.5)?

You can still contribute fully. Here's exactly what happens:

- **`/spec-gen` and `/impl-plan-gen` detect the missing key, tell you, and
  proceed with Opus-only internal review passes.** They never *silently* skip
  cross-model review — you'll see a note that it was skipped and why. You still
  get a reviewed, structured spec/plan; it just isn't double-checked by a
  second model family on your machine.
- **Your PR still gets an independent review.** Gemini Code Assist runs on the
  repository itself (a GitHub app), not on your local setup — so opening a PR
  still triggers a cross-model code review regardless of what you have
  installed.
- **Maintainers run the full Opus ↔ GPT-5.5 review before merge** for specs
  and plans, per the project's
  [cross-model review policy](https://github.com/SoundMindsAI/relyloop/blob/main/CLAUDE.md).
  So nothing reaches `main` without cross-model scrutiny — your local setup
  just determines whether you see it before you push.

!!! tip "Enabling GPT-5.5 locally"
    Add `OPENAI_API_KEY=sk-...` to your repo-root `.env`. The skills resolve it
    with `grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2-` (`.env` is not sourced
    into your shell). The reviewer model is fixed at `gpt-5.5` — the point is a
    *different family*, so don't substitute another OpenAI model.

## Before you open the PR

Whatever agent you use, the same rules apply (the skills enforce them; do them
by hand otherwise):

- [ ] Sign every commit: `git commit -s` (DCO — enforced by CI).
- [ ] [Conventional Commits](https://www.conventionalcommits.org/) format.
- [ ] Tests at every layer the change touches; backend stays ≥80% covered.
- [ ] `make fmt && make lint && make test` clean before pushing.
- [ ] Branch off `main`; never commit to `main` directly.

See [Contributing](contributing.md) for environment setup and the full PR
checklist.
