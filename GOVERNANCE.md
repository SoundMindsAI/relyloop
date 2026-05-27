# Governance

This document describes who decides what in RelyLoop and how the project
intends to evolve.

## Current state — single-vendor stewardship

RelyLoop is at v0.1 (MVP1 alpha). **All maintainers are soundminds.ai
employees**, and final merge authority on `main` rests with the project
lead. We are stating this openly so that prospective contributors and
enterprise reviewers can size up the bus factor and capture risk
honestly.

We chose this model because the project is still in the foundation-laying
phase: schemas, adapter contracts, and APIs are changing fast, and a small
group of people with full context can move much faster than a committee.
The model is intentionally temporary — see "Transition plan" below.

## Project scope

RelyLoop is an open-source tool for tuning query-time search relevance on
Elasticsearch, OpenSearch, and (in later releases) Lucidworks Fusion. The
authoritative scope statement is the [umbrella spec](docs/00_overview/relyloop-spec.md),
particularly §4 (non-goals). Proposals that materially expand scope
(new engine families, online A/B testing, LTR training, sitting on the live
search-serving path) are decided by the maintainers and the project lead.

## Roles

- **Contributor.** Anyone who opens an issue, comments on a discussion, or
  submits a pull request. No special status is required; see
  [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started.
- **Maintainer.** Has commit rights, reviews and merges pull requests, and
  triages issues. Current maintainers are listed in
  [MAINTAINERS.md](MAINTAINERS.md). Maintainers are expected to follow the
  contribution norms in [CONTRIBUTING.md](CONTRIBUTING.md) — Conventional
  Commits, DCO sign-off, no force-push to `main`.
- **Project lead.** Holds final say on direction, scope, releases, and the
  maintainer roster. At v0.1 this role is held by Eric Starr
  (soundminds.ai).

## How decisions are made

Day-to-day technical decisions use **lazy consensus**: if a maintainer
opens a PR or proposal and no other maintainer objects within a reasonable
review window (typically a few business days), it ships. Substantive
disagreements are resolved through discussion in the PR or issue thread;
where consensus cannot be reached, the project lead decides.

Decisions that change the public API surface, alter the umbrella spec's
non-goals, drop a supported engine or LLM provider, or change the
licensing or governance posture require an explicit `+1` from at least two
maintainers, including the project lead.

**Single-maintainer transitional rule (v0.1):** while there is only one
maintainer, the two-maintainer `+1` requirement is suspended — the project
lead's decision stands, recorded in the PR or issue thread. The rule
activates automatically the moment a second maintainer is added. This is
called out openly in [MAINTAINERS.md](MAINTAINERS.md) so contributors can
size the governance state honestly.

## How to become a maintainer

There is no time-served quota. The realistic bar is:

1. A track record of merged PRs across at least two subsystems
   (backend / frontend / adapters / docs / infra).
2. Demonstrated judgement in code review — catching design issues, not
   just style nits.
3. Willingness to take review and triage shifts, not just ship features.

The nomination flow: an existing maintainer opens an issue proposing the
addition; other maintainers `+1` or raise objections; the project lead
makes the final call. While there is only one maintainer, the project
lead adds the first additional maintainer unilaterally based on the
criteria above — the `+1` flow activates once N≥2. We will document the
first community maintainer addition publicly so that the path is visible.

## Transition plan

We intend to move from single-vendor stewardship toward a multi-organization
maintainer model over **12–24 months** from MVP1's first stable release.
The umbrella spec discusses this in §29 ("OSS positioning & governance").
Concrete milestones we will report on:

- **First external maintainer added** (target: within the first 12 months
  of community contribution).
- **Maintainer roster spans at least two organizations** (target: before
  v1.0 GA).
- **Governance amendment process delegated to the maintainers** (target:
  at v1.0 GA — i.e., the project lead's veto on this document goes away).

We will publish progress against these milestones in release notes.

## Conflict resolution

If a disagreement cannot be resolved through discussion in a PR or issue:

1. Move the conversation to a dedicated issue summarizing the positions.
2. Tag the project lead for a decision. The lead may request input from
   the broader maintainer group before deciding.
3. The decision and its rationale are recorded in the issue and, if
   architecturally material, in `docs/01_architecture/`.

Conduct concerns (as distinct from technical disagreements) follow the
process in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Amending this document

Changes to GOVERNANCE.md require a pull request approved by the project
lead. We will move to a maintainer-vote amendment process at v1.0 GA per
the transition plan above.
