# RelyLoop — OSS Launch Readiness Checklist

> A working checklist you tick off as you go. Edit this file directly: change
> `- [ ]` to `- [x]` as you complete each item. Items already verified done in
> the repo are pre-checked with a short note on the evidence.
>
> **How to read it:** Section 0 is the "do this before you announce anything"
> punch list — the gaps a skeptical first visitor (or an HN commenter) would
> notice today. Sections A–D are the full phased plan, validated and corrected
> for RelyLoop's actual situation (already public, three engines shipped,
> Apache 2.0 + DCO).
>
> Last reconciled against the repo: 2026-05-31.

**Legend:** `- [ ]` to do · `- [x]` done · 🔴 blocks announcing · 🟡 strongly recommended before announcing · 🟢 nice-to-have / ongoing

---

## Section 0 — Do before you announce (the immediate punch list)

These are the visible gaps. None are big; all are worth closing before any
outreach so the repo doesn't undersell what's actually shipped.

- [x] 🔴 **Fix the GitHub repo description** — done; no longer references Fusion. Verified via `gh`: "Open-source automated Bayesian relevance tuning for Elasticsearch, OpenSearch, and Apache Solr. Thousands of Optuna/TPE trials across the full query-time search space; winning configs ship as Pull Requests. Apache 2.0."
- [x] 🔴 **Reconcile the "Solr hasn't shipped" docs** — done on this branch (`docs/solr-shipped-reconcile`); all Section A edits made and verified. 8 tracked docs (README, CLAUDE.md, architecture.md, GOVERNANCE.md, the spec, tech-stack/adapters/mvp1-overview/mvp2-overview) now describe Solr as shipped (MVP2, 2026-05-31). Straggler grep clean; Fusion removed from all active docs. (Not yet committed/PR'd — see Section A's "Ship it" line.)
- [x] 🔴 **Enable GitHub Discussions** — done; verified `has_discussions: true` via `gh`. The README's `/discussions` link now resolves.
- [x] 🟡 **Add a Karpathy-loop diagram to the README** — done; a native Mermaid `flowchart` ("## The loop") showing set-up-once → inner Optuna/TPE trial loop → Git-PR apply path, with the "ends at the PR" boundary explicit. Renders on GitHub without image files. Syntax structurally validated (balanced subgraphs, unique nodes, escaped entities).
- [ ] 🟡 **Add a short demo gif to the README** — placeholder + maintainer-TODO note is in place under "## The loop". **Needs you:** record a ~30s screen capture of a study running end-to-end against the tutorial stack, encode as gif, drop in `docs/assets/`, and replace the placeholder. (Can't be produced headlessly — requires running the app + screen recording.)
- [ ] 🟡 **Regenerate stale guide screenshots** (`guide-gen --regen`) — git-driven audit done (2026-05-31, read-only). The 48 in-app guide screenshots under `ui/public/guides/` were last captured 2026-05-27 (commit `1a477168`); the entire MVP2 batch landed after. **Confirmed stale (read against the screenshots + code):**
  - **Guide 06 (create + monitor study):** `04-study-detail.png` / `05-study-terminal-state.png` show the Confidence panel but **not** the `ConvergencePanel` (verdict + best-so-far curve, #352) or the `AutoFollowupChainPanel` (#343) — both now mounted at `ui/src/app/studies/[id]/page.tsx:110-112`.
  - **Guide 01 (register first cluster):** `01-clusters-list.png` engine filter chips show only `all / elasticsearch / opensearch` — but the chips are now driven by `ENGINE_TYPE_VALUES = [...,'solr']` (`ui/src/lib/enums.ts:41`) and `EngineBadge` renders Solr (`engine-badge.tsx:68`). No Solr cluster in the screenshot's demo data either.
  - **Guide 01:** `05-cluster-detail.png` predates the UBI readiness surface (`ubi-rung-badge` / `ubi-onramp-nudge`, shipped with `feat_ubi_judgments`).
  - **Likely (not individually re-read):** guides 02/07 (proposals) predate `currently-live-badge` + `suggested-followups-panel`; the shared `DataTable` toolbar/column-visibility also changed across all table guides.
  - **Regen needs the running stack** (`make up` + `make seed-demo`, then `pnpm playwright test -c playwright.demo.config.ts tests/e2e/guides/...`) — can't run headlessly, so it's a you-run-it step. Separate from the README work; **not** part of PR #354.
- [ ] 🟡 **Seed 10–15 genuinely small `good first issue` tickets** — there are 0 open issues today; the plan calls for a curated on-ramp.
- [x] 🟡 **Add `engine/elasticsearch`, `engine/opensearch`, `engine/solr` labels** — done; all three created (color `1d76db`) and verified via the labels API.
- [x] 🔴 **Restore heavy CI** — done; `SKIP_HEAVY_CI` deleted (verified `gh variable list` now empty). The full `pr.yml` suite (backend lint/typecheck/tests/coverage, frontend, smoke, both docker builds) runs on every PR again. **No cost concern:** standard GitHub-hosted runners (`ubuntu-latest`/`ubuntu-24.04`, all jobs) are unlimited-free on public repos — the original "GHA budget" reason for the skip no longer applies now that the repo is public.
- [ ] 🟡 **Restore branch protection on `main`** — the required-status-checks rule was removed 2026-05-31. Before external PRs arrive, require PR review + passing CI again (the `protect-main-require-pr-ci` ruleset, or classic protection). Operator action.
- [ ] 🟢 **Run a trademark search** for "RelyLoop" (USPTO + EUIPO). Cheap now, painful later. (Needs you.)

---

## Section A — Doc-staleness fixes (Solr shipped; Fusion removed)

Solr shipped 2026-05-31 (`infra_adapter_solr` PR #336 + #348), so every
"ships at MVP2 / at MVP2 / arrives with MVP2" reference now reads as stale.
Each item below is a concrete edit with the location.

- [x] **README.md** — status line, engine list (line 5), "What's coming" block (line 50), and "Engine-neutral" bullet (line 61) updated to "all three engines live." *(Done this session on branch `docs/solr-shipped-reconcile`.)*
- [x] **CLAUDE.md** line 17 — "(Solr ships at MVP2)" → "(all three engines shipped)"; release-matrix MVP2 row reframed to "in progress; Solr + UBI shipped" with dates.
- [x] **tech-stack.md** (canonical matrix) — MVP1 row no longer says "no Solr yet" (now notes it shipped in MVP2); MVP2 row reframed past-tense with ship dates + the `solr.UBIComponent`-not-in-stock caveat; engine-targets row + "Reserved for later releases" both updated.
- [x] **architecture.md** line 11 — now "Elasticsearch, OpenSearch, and Apache Solr — all three shipped."
- [x] **docs/01_architecture/adapters.md** — status line, protocol-siblings line, explain note, parameter-table header, `solr_basic`/`solr_apikey` rows, the `### SolrAdapter` heading, and the UBI-on-Solr note all de-futured.
- [x] **docs/01_architecture/mvp1-overview.md** — "Reserved for MVP2" → "Shipped in MVP2" with dates; removed the contradictory "Reserved for v2+ → SolrAdapter" line.
- [x] **docs/01_architecture/mvp2-overview.md** — "Status: Planning" → "In progress" (Solr + UBI shipped; remaining items Idea-stage).
- [x] **docs/00_overview/relyloop-spec.md** — §1 engine line, the ASCII architecture + cluster diagrams, the `### SolrAdapter` section, the UBI-on-Solr bullet, the docker-compose paragraph, the edismax-template heading, the apply-path heading, and the tech-stack engine-targets row all reconciled. *(Left intact: legitimate roadmap-history mentions like §27's "Solr was promoted to MVP2" and the decision-rationale paragraphs.)*
- [x] **GOVERNANCE.md** — dropped "(Solr ships at MVP2)".
- [x] **docs/07_research/comparison.md** — already read "(MVP2 shipped)" / "(MVP2)" correctly in the competitive matrix; no edit needed (verified current).
- [x] **release-notes-v0.1.0-draft.md** — Fusion line removed; stale six-release roadmap corrected to the current four-stop matrix. *(File is gitignored/maintainer-local, so this fix is local-only and won't appear in the PR diff.)*
- [x] **Verified no stragglers** — `grep` for "ships at MVP2 / arrives with MVP2 / Solr in MVP2 / Solr (MVP2)" across all active tracked docs returns clean; "Lucidworks Fusion / Fusion adapter / Fusion Signals" across active tracked docs returns clean. (Remaining Fusion strings live only in the historical record: `implemented_features/`, `state_history.md`, the auto-generated dashboards, and test fixtures using `"fusion"` as a deliberately-invalid engine value — these are the *record of dropping Fusion*, not advertisements for it.)
- [ ] **Ship it** — commit on `docs/solr-shipped-reconcile`, push, open the single PR, watch CI, merge. (Docs-only; no migration, no coverage impact.)

---

## Section B — Pre-launch hygiene (Phase 1)

Most of this is already done — pre-checked with evidence.

**Legal & licensing**
- [x] Apache 2.0 `LICENSE` present.
- [x] `NOTICE` present with dependency attribution.
- [x] Dependency license audit — `scripts/gen_license_inventory.py` → `docs/04_security/license-inventory.md`, 786 deps / 0 GPL/AGPL violations, with a `license-inventory` CI gate. *(PR #330.)*
- [x] SPDX headers on every source file via FSFE REUSE (1477/1477) + `reuse-lint` gate. *(PR #322.)*
- [x] CLA-vs-DCO decided → **DCO**, enforced (`dco.yml`, `commit-msg` signoff hook, CONTRIBUTING.md). ⚠️ *Note: DCO does not preserve relicensing optionality — Apache-2.0 + DCO is a deliberate one-way door. Confirm that's intended.*
- [x] Full git-history secret scan (gitleaks full-history + manual sweep; runbook at `docs/03_runbooks/oss-history-audit.md`) — repo cleared for visibility flip.

**The five files contributors look for**
- [x] `README.md` — niche-first, working 5-minute quickstart, scorecard badge. *(Still wants a loop diagram/gif — see Section 0.)*
- [x] `CONTRIBUTING.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `SECURITY.md`
- [x] `GOVERNANCE.md` + `MAINTAINERS.md` (honest single-vendor stewardship stated openly).

**Repo plumbing**
- [x] Issue templates (bug, feature, config) + PR template + `CODEOWNERS`.
- [x] CI on PR (`pr.yml`) + OpenSSF Scorecard + a secrets-defense workflow (ahead of the baseline plan).
- [x] Dependabot configured.
- [ ] 🟡 `CHANGELOG.md` — missing. Add one (Keep a Changelog, or generate from conventional commits).
- [ ] 🟡 `release.yml` workflow — missing; releases are hand-cut today. Automate before cadence picks up.
- [ ] 🟢 `CITATION.cff` — cheap academic-credibility win in the relevance/IR community.
- [ ] (See Section 0) Branch protection on `main`; Discussions; labels.

**Make it runnable fast**
- [x] One-command setup (`make up` → `make migrate` → `make seed-*`).
- [x] Worked walkthrough exists (`docs/08_guides/tutorial-first-study.md`, samples in `samples/`).
- [ ] 🟢 Consider a top-level `examples/` with a self-contained "run this, watch the loop propose a change" demo (the single biggest try-it lever for this category).

---

## Section C — Launch day (Phase 2)

- [x] Repo is public; Apache-2.0 detected by GitHub.
- [x] Tagged releases with story-style notes (v0.1.0 → v0.1.3).
- [ ] 🟡 Pin a "Roadmap & where we want help" Discussion (after enabling Discussions).
- [ ] 🟡 Pull at least one reproducible benchmark forward (MS MARCO / BEIR NDCG/MRR). The relevance community is empirical; the full Optuna-vs-SRW benchmark is parked at GA v1 — a small reproducible number at launch buys credibility.
- [ ] Announce, spaced over ~48h and **only after Section 0 is clear**: r/elasticsearch + r/solr → Relevance/Haystack Slack → Show HN (Tue–Thu AM ET, demo gif, *one shot — make it bulletproof*) → LinkedIn → a soundminds.ai "why we built it" post.
- [ ] Email Doug Turnbull / OSC and the Haystack organizers directly — frame as **complementary**, not a Quepid killer. Don't surprise the ecosystem.
- [ ] Submit a Haystack conference CFP.
- [ ] 🟡 Community channel: **join the existing Haystack/Relevance Slack** rather than spinning up an empty Discord (a dead Discord reads worse than none). Link it everywhere.
- [ ] Be honest about engine reach in the announcement: three engines are implemented, but ES + OpenSearch share one Lucene-family adapter — say "ES, OpenSearch, and Solr," not anything that implies three independent stacks.

---

## Section D — First 90 days + RelyLoop-specifics (Phases 3–4)

- [ ] Respond to every issue/PR within 48h (even just "thanks, looking this week") — the strongest predictor of repeat contributors.
- [ ] Keep 10–15 curated `good first issue` tickets stocked as they get claimed.
- [ ] Public roadmap as a GitHub Project (translate the internal MVP2/§-language into issues outsiders can read).
- [ ] Recognize external contributors publicly (release notes; `all-contributors` bot / `CONTRIBUTORS`).
- [ ] Biweekly community call once you have >5 external users (3 people is enough to start).
- [ ] One real relevance-tuning case-study blog post per month — how you out-compete OSC mindshare (visible expertise, not feature parity).
- [ ] Add a public FAQ entry answering "is there a hosted/SaaS option?" — the no-SaaS stance needs a clear public answer so it doesn't become a recurring objection.
- [ ] Publish a "design-partner / how soundminds funds this" page — transparency consistent with the §29 stewardship stance.

---

## Verification still owed (I couldn't confirm these from the repo)

- [ ] Trademark search result (USPTO + EUIPO) recorded somewhere.
- [ ] Decision recorded: keep README/docs describing `main` (three engines, pre-1.0) vs. pinning to the last tagged release — this checklist assumes **describe `main`**.
