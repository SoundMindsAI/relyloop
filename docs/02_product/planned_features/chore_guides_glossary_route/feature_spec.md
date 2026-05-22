# Feature Specification — Glossary route in the Guides catalog

**Date:** 2026-05-22
**Status:** Draft
**Owners:** soundminds.ai (product + engineering)
**Related docs:**
- [`idea.md`](idea.md) — origin + locked decisions
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — Next.js / shadcn / Tailwind frontend pattern
- [`docs/00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md`](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md) — precedent for the glossary source-of-truth file and the InfoTooltip / HelpPopover wrappers this feature renders into a browsable surface

---

## 1) Purpose

`ui/src/lib/glossary.ts` is the single source of truth for every tooltip and HelpPopover in RelyLoop — **109 entries** across 8 key-prefix groups (`cluster`, `confidence`, `datatable`, `digest`, `judgment`, `proposal`, `study`, `trial`) as of `feat_pr_metric_confidence`'s 6-entry confidence block at lines 578–618. The entries are content-rich (each `long` field is up to ~800 chars of curated copy with examples and decision rubrics) but are **only discoverable via the inline `<InfoTooltip>` / `<HelpPopover>` triggers** that live next to specific UI elements. Operators reading a PR body in GitHub, browsing `/judgments` without hovering each label, or asking "what's the difference between `runner_up_gap` and `runner_up_metric`?" have no canonical reference surface — they would need to grep `ui/src/lib/glossary.ts` on disk, which isn't viable for non-engineers.

- **Problem:** the glossary file is load-bearing terminology (109 entries; parity-tested against `ui/src/lib/enums.ts`; cited 100+ times across the codebase via `<InfoTooltip glossaryKey="…">`) but has no operator-facing reference surface. Discovery is gated by happening-to-hover a specific UI element.
- **Outcome:** the [`/guide`](../../../../ui/src/app/guide/page.tsx) catalog page gains a third section — **Glossary** — that renders every entry in a single browsable, searchable, deep-linkable page at `/guide/glossary`. Operators can find a term by category (8 prefix-derived facets) or substring search. The route exposes a stable `#<glossary-key>` anchor scheme (FR-4) so future surfaces — FAQ entries, blog posts, and an opt-in "Read more →" tooltip affordance (deferred per D-3) — can deep-link straight to the canonical entry. **This feature does not modify the `<HelpPopover>` body to add a "Read more →" link;** that affordance is explicitly out of scope (§3, D-3).
- **Non-goal:** this feature does **not** introduce an editor UI, per-tenant copy configuration, multi-language support, or any backend persistence. The page is a pure render layer over the existing TypeScript `glossary` constant.

## 2) Current state audit

### Existing implementations

| File / surface | What it does | Notes |
|---|---|---|
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) (676 LOC, 109 entries) | Single TypeScript constant — keyed by dotted wire-style identifiers (e.g., `study.metric.ndcg`). Each entry is one of three shapes: `{ short, ariaLabel? }` (used by `InfoTooltip`), `{ long, ariaLabel? }` (used by `HelpPopover` only), or `{ short, long, ariaLabel? }` (both). Derived types `GlossaryKey`, `ShortGlossaryKey`, `LongGlossaryKey` narrow at compile time. | Helpers `listGlossaryKeysWithPrefix(prefix)` and `expectGlossaryGroundedAgainstEnums(prefix, wireValues)` already exist (FR-4 of `feat_contextual_help`); the parity test at [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) enforces backend-enum grounding for 11 wire-value groups. **This feature reuses the existing data structure verbatim — no schema change.** |
| [`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx) (66 LOC) | Renders the `short` field of a glossary entry inside a Radix Tooltip. `ShortGlossaryKey` narrows the prop type at compile time. | Establishes the "read from glossary" pattern this feature inherits. |
| [`ui/src/components/common/help-popover.tsx`](../../../../ui/src/components/common/help-popover.tsx) (60 LOC) | Renders the `long` field inside a Radix Popover via `<ReactMarkdown disallowedElements={['script', 'iframe', 'style']} unwrapDisallowed>`. Subset-safe markdown (paragraphs, lists, bold, inline code) per the glossary entry length budget (≤800 chars `long`). | **The glossary route MUST use the same safety filter** — see FR-6. |
| [`ui/src/app/guide/page.tsx`](../../../../ui/src/app/guide/page.tsx) (98 LOC) | The `/guide` catalog renders two sections today: "Long-form documentation" backed by `DOC_REGISTRY` (tutorial + workflows-overview) and "Visual walkthroughs" backed by `GUIDE_REGISTRY` (10 shipped guides). Each section is a grid of `<Card>` tiles. | **The glossary route adds a third section** of the same shape — see FR-5. The page already imports `GUIDE_REGISTRY` and `DOC_REGISTRY` from [`ui/src/components/guides/guide-types.ts`](../../../../ui/src/components/guides/guide-types.ts); the catalog card for the glossary will be added there. |
| [`ui/src/components/guides/guide-types.ts`](../../../../ui/src/components/guides/guide-types.ts) (196 LOC) | Defines `DocRegistryEntry`, `GuideRegistryEntry`, `GuideMapEntry`, the populated `DOC_REGISTRY` (2 entries), `GUIDE_REGISTRY` (10 entries), and `GUIDE_MAP` (11 mappings) + the `guidesForPath()` matcher. | No type changes required — the glossary catalog card is rendered ad-hoc in `/guide/page.tsx` (one-off, not a registry shape). See §11 IA. |
| [`ui/src/app/guide/docs/[slug]/page.tsx`](../../../../ui/src/app/guide/docs/[slug]/page.tsx) (32 LOC) | Renders long-form markdown docs at `/guide/docs/<slug>` via `<MarkdownDoc>`. | Establishes the "nested `/guide` subroute" pattern. The glossary route follows the same shape: own page at `/guide/glossary` with a "← All guides" back link. |
| [`ui/src/components/layout/top-nav.tsx:15`](../../../../ui/src/components/layout/top-nav.tsx) | `{ href: '/guide', label: 'Guides' }` — the top-nav entry that exposes the catalog. | **Unchanged** — the glossary route lives under `/guide/glossary`; the existing top-nav link suffices. |
| [`docs/08_guides/README.md:1-20`](../../../../docs/08_guides/README.md) | Lists "Tutorials, install docs, migration notes, FAQs, and cookbook-style how-to content" — note: the README's header mentions "FAQs" (line 3) but no FAQ artifact exists. Out of scope here; see sibling [`chore_guides_faq`](../chore_guides_faq/idea.md). | **Add a new section: "In-app glossary route"** to the README's MVP1 list, citing `/guide/glossary` — see §15 Doc updates. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| [`ui/src/app/guide/page.tsx`](../../../../ui/src/app/guide/page.tsx) (catalog page) | n/a | Add a third `<section>` ("Glossary") with one `<Card>` linking to `/guide/glossary`. |
| [`ui/public/guides/<id>/script.md`](../../../../ui/public/guides/) (10 walkthrough script files) | n/a | Append a one-line footer to each: `> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.` (FR-7). |
| [`ui/src/components/common/help-popover.tsx`](../../../../ui/src/components/common/help-popover.tsx) | n/a | **Out of scope.** The "Read more →" deep-link affordance from tooltip-bodies into the glossary is documented in §3 Out of scope and Decision log entry D-3. |

The top-nav stays unchanged (the existing "Guides" link covers it). No existing route is being renamed, removed, or redirected.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) (186 LOC) | Existing parity tests against `enums.ts` for 11 wire-value groups + length/markdown safety checks on every entry. | 1 file | **No required change.** The glossary route is a render layer over the same constant; the existing parity / length / safety contracts continue to hold. |
| `ui/src/__tests__/app/guide/page.test.tsx` (if it exists — verify in §2 audit before plan) | If a catalog test exists, it asserts on two sections (`doc-section`, `walkthrough-section`). | TBD | Extend (or add) to assert on a third section `glossary-section` with one card linking to `/guide/glossary`. |
| `ui/tests/e2e/guide-*.spec.ts` (E2E glossary spec) | New | 0 | **Add new spec** `ui/tests/e2e/glossary.spec.ts` exercising the route end-to-end against the real backend (page load → search interaction → category-facet toggle → deep-link anchor scroll). Use the established Playwright pattern from [`ui/tests/e2e/dashboard.spec.ts`](../../../../ui/tests/e2e/dashboard.spec.ts). No `page.route()` mocking. |

Audit confirms the catalog page test file may not exist yet; the plan must verify and either extend or create it.

### Existing behaviors affected by scope change

- **`/guide` catalog page layout**: extended (third section appended below "Visual walkthroughs"). No tile is renamed, removed, or reordered. Decision needed: **no** — the section ordering convention is well-established by `feat_contextual_help`'s catalog pattern.
- **Tooltip / HelpPopover behavior**: **unchanged.** Tooltips still open on hover/focus and Popovers on click; the body content still comes from `glossary[key]`. The "Read more →" deep-link affordance is explicitly out-of-scope (Decision D-3).
- **Search engine indexing**: the page is client-rendered (Next.js `'use client'`), which limits SEO surfacing. Decision needed: **no** — RelyLoop is a self-hosted operator tool; SEO is irrelevant.

---

## 3) Scope

### In scope

- New route `/guide/glossary` at `ui/src/app/guide/glossary/page.tsx`, client-rendered (`'use client'`), rendering all entries from `ui/src/lib/glossary.ts` in a single browsable page.
- **Search:** a text input that filters entries by case-insensitive substring match over key, `short`, and `long`. Filtering is purely client-side (no debounce timer needed beyond React's natural batching) since the dataset is bounded at ~150 entries.
- **Category facets:** filter chips derived from the **8 unique top-level key prefixes** (`cluster`, `confidence`, `datatable`, `digest`, `judgment`, `proposal`, `study`, `trial`) — derived at module load via `listGlossaryKeysWithPrefix()` or equivalent, no hand-maintained taxonomy. Multiple chips can be selected (OR semantics within facets); search + facets compose (AND semantics across the two filter axes).
- **Entry rendering:** each entry shows the key as `<code>` (anchor target), the `short` form as the primary label, and the `long` form rendered via `<ReactMarkdown disallowedElements={['script', 'iframe', 'style']} unwrapDisallowed>` immediately below — same safety filter the `HelpPopover` component already uses (see [`ui/src/components/common/help-popover.tsx:54`](../../../../ui/src/components/common/help-popover.tsx)). When an entry only has `long` (no `short`), the `<code>` key serves as the label and `long` becomes the body; when an entry only has `short`, the body is the short text and no markdown block is rendered.
- **Deep-link anchors:** each entry gets an `id` attribute set to its glossary key (e.g., `id="study.metric.ndcg"`) so URLs like `/guide/glossary#study.metric.ndcg` scroll the target into view on initial load.
- **Catalog card:** a new `<section>` in [`ui/src/app/guide/page.tsx`](../../../../ui/src/app/guide/page.tsx) — appended below "Visual walkthroughs" — with one `<Card>` linking to `/guide/glossary` ("Glossary — every term defined", 109 entries).
- **Script.md footer cross-link:** each of the 10 walkthrough script files at [`ui/public/guides/<id>/script.md`](../../../../ui/public/guides/) gets a one-line footer `> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.` Mechanical text addition.
- **Process integration — three skill-file edits** (per the idea's locked-decisions section, in leverage order):
  - [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) Step 3 ("Guide impact assessment — MANDATORY GATE", currently at lines 591-614) — extend the questionnaire with **two glossary-shaped questions** (new terminology + drift on existing entries) per FR-8a.
  - [`.claude/skills/spec-gen/SKILL.md`](../../../../.claude/skills/spec-gen/SKILL.md) Step 3 item 11 (line 84 — "Tooltips and contextual help (Section 11)") — extend the verification to **require every tooltip-inventory entry to cite either an existing glossary key (verifiable by grep of `ui/src/lib/glossary.ts`) or name a new key to be added in a specific story** per FR-8b.
  - [`.claude/skills/impl-plan-gen/SKILL.md`](../../../../.claude/skills/impl-plan-gen/SKILL.md) line 111 (Tooltips and contextual help requirement) — extend the per-tooltip plan checklist to **require the glossary key column and the source-of-truth file path** per FR-8c.

### Out of scope

- **"Read more →" deep-link affordance from tooltip / popover bodies into the glossary route.** Decision D-3 — defer until the glossary route ships and we can measure whether operators actually click through from tooltips before adding the affordance. The deep-link anchors (FR-4) are designed in now so the affordance can be added later without changing the route surface.
- **Search highlighting (yellow-highlight of matched substrings inside the entry body).** Decision D-4 — adds rendering complexity; substring filter is sufficient for v1.
- **Sticky "jump to category" sidebar nav.** Decision D-5 — defer; the category facet chips at the top of the page serve the same need at less render cost.
- **Per-entry inline edit / "Suggest a correction" UI.** Out of MVP1 — copy lives in source; edits flow through the spec → plan → execute pipeline.
- **`StartHereChecklist` integration.** The idea's "Discoverability" section proposes adding a glossary step to the home page's [`StartHereChecklist`](../../../../ui/src/components/dashboard/start-here-checklist.tsx). Decision D-6: out of scope — the checklist is shaped as a 3-step Stripe-style **action** sequence (Register cluster → Create query set → Run study) where each step auto-completes when state changes; "Learn the terminology" is a read-only step with no completion signal and would break the component's structural invariant. The top-nav "Guides" link + the new catalog card are sufficient discoverability surfaces.
- **Multi-language support.** Single-language (English) per CLAUDE.md MVP1 scope.
- **Backend persistence / API surface.** This is purely a frontend render layer; no router, model, migration, or settings change.
- **FAQ surface.** Sibling planned feature [`chore_guides_faq`](../chore_guides_faq/idea.md) — out of scope here. The FAQ route depends on this route landing first so its entries can deep-link into glossary anchors.

### API convention check

- **No new endpoints.** This feature is frontend-only.
- **No router changes.** No file under `backend/app/api/` is modified.
- **Error envelope:** N/A — no API surface added.
- **Auth pattern:** N/A — no API surface added. MVP1 is single-tenant, no auth (per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).
- **Endpoint prefix convention check:** N/A.

### Phase boundaries

**Single-phase feature.** All in-scope items ship together. Rationale: total scope is ~200 LOC of frontend + ~10 lines of markdown footers + 3 surgical skill-file edits + ~120 LOC of tests; splitting introduces more coordination cost than it saves.

No `phase2_idea.md` artifact required (no deferred phases).

---

## 4) Product principles and constraints

- **The glossary constant is the single source of truth.** The glossary route never duplicates copy — it imports `glossary` directly from `ui/src/lib/glossary.ts` and renders it. If a copy edit is needed, it lands in the constant; the route picks it up at next build.
- **No new dependency.** The route uses only packages already in [`ui/package.json`](../../../../ui/package.json): `react-markdown` + `remark-gfm` (already used by `MarkdownDoc`), `lucide-react` (icons), Radix UI primitives, shadcn `<Card>`. No fuzzy-search library — substring filter is sufficient at this corpus size.
- **Markdown rendering uses the established safety filter.** `react-markdown` with `disallowedElements={['script', 'iframe', 'style']}` and `unwrapDisallowed` — exact pattern from [`help-popover.tsx:54`](../../../../ui/src/components/common/help-popover.tsx) and [`markdown-doc.tsx:189`](../../../../ui/src/components/guides/markdown-doc.tsx). Defense-in-depth alongside the glossary entry length / content-shape checks that already run in [`glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts).
- **Category facets are derived, not configured.** Categories come from key prefixes via `Object.keys(glossary)`. No hand-maintained taxonomy file; a new prefix (added when a new feature ships glossary entries) appears in the facet bar automatically.
- **Process integration is the single most-leveraged piece.** The route is half the value; the skill-file edits make sure the glossary doesn't rot. Both must ship together — shipping just the route without the gates means the glossary will silently drift the moment a feature introduces new UI terms without entries.

### Anti-patterns

- **Do not** inline glossary entries into the page component. Always import from `ui/src/lib/glossary.ts`. Inline copies break the single-source-of-truth invariant and re-introduce the drift problem `feat_contextual_help` solved.
- **Do not** introduce a hand-maintained category taxonomy. Categories are derived from key prefixes; if a new prefix appears, it shows up in the facet bar automatically. Hand-maintained taxonomies always drift.
- **Do not** add a fuzzy-search dependency (`fuse.js`, `match-sorter`, etc.). Substring search is sufficient at ~150 entries; adding a dep introduces bundle weight and a runtime dependency for a fixed-size dataset.
- **Do not** server-render the page (`'use client'` is required). The search + facets are client-state-driven; server-rendering would mean rebuilding the page on every state change, which defeats the React render model for filter UIs.
- **Do not** make the markdown filter laxer than `HelpPopover`'s. The same source content renders in both surfaces; if one allows `<iframe>` and the other doesn't, the markup contract diverges and reviewers cannot trust that a copy edit is safe.
- **Do not** stash the skill-file edits into a follow-up PR. The gate edits and the route ship together — the user explicitly asked for one PR covering all three chore_guides_* items, and a route without gates is unfinished work.

## 5) Assumptions and dependencies

- **Dependency:** `ui/src/lib/glossary.ts` exists with at least the 109 entries shipped by `feat_contextual_help` + the 6 `confidence.*` entries from `feat_pr_metric_confidence`.
  - Why required: this feature is a render layer over that constant.
  - Status: **implemented** (verified 2026-05-22 — 109 entries; 8 prefix groups).
  - Risk if missing: route renders empty / fails type-check. Zero risk — the file is referenced by every shipped tooltip in the app; deleting it would break the production build.
- **Dependency:** `react-markdown` + `remark-gfm` in `ui/package.json`.
  - Why required: long-form rendering of `long` entries.
  - Status: **implemented** (used by `HelpPopover` + `MarkdownDoc` today).
- **Dependency:** Playwright real-backend pattern from [`ui/tests/e2e/dashboard.spec.ts`](../../../../ui/tests/e2e/dashboard.spec.ts).
  - Why required: glossary E2E follows the same shape (real backend at `localhost:8000`, no `page.route()` mocking).
  - Status: **implemented**.
- **Cross-feature coordination:** sibling planned feature [`chore_guides_faq`](../chore_guides_faq/idea.md) **depends on this route landing first** so its FAQ entries can deep-link into glossary anchors (`/guide/glossary#study.metric.ndcg`). FAQ does not block this feature; this feature blocks FAQ. Coordination handled at the branch level — both ship on `feature/guides-glossary-faq-and-regen` per the operator's "one branch, one PR" plan.
- **No backend / migration / settings dependency.**

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (the MVP1 operator persona — runs studies, reads PR bodies, reviews proposals). Secondary: Approver and Viewer personas (per CLAUDE.md §"Personas") — both read-only.
- **Role model:** **N/A — single-tenant install, no auth surface.** RelyLoop is single-tenant + no auth through MVP3 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md).
- **Permission boundaries:** N/A.

### Authorization

**N/A — single-tenant install, no auth surface.** When MVP4 lands and the auth surface arrives, `/guide/glossary` should remain accessible to every authenticated role (it's an operator reference page, not a state-mutating surface) — but that's MVP4 scope and not enforced here.

### Audit events

**N/A — `audit_log` lands at MVP2** per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md). This feature has no state mutations regardless (read-only page).

---

## 7) Functional requirements

### FR-1: New route at `/guide/glossary`
- Requirement:
  - The system **MUST** serve a new page at `/guide/glossary` rendering every entry from `ui/src/lib/glossary.ts` as an ordered list of cards or rows, grouped by category (top-level key prefix).
  - The page **MUST** be a client component (`'use client'`) — the search/facet UI is interactive.
  - The page **MUST** include a `← All guides` back link to `/guide`, matching the pattern at [`ui/src/app/guide/docs/[slug]/page.tsx:20-26`](../../../../ui/src/app/guide/docs/[slug]/page.tsx).
- Notes: render shape mirrors the existing `/guide/docs/[slug]` route — a `<main>` with a top breadcrumb bar above the content area.

### FR-2: Substring search
- Requirement:
  - The page **MUST** include a `<input type="search">` element that filters entries by case-insensitive substring match against (a) the key, (b) the `short` field if present, (c) the `long` field if present. An entry is shown if **any** of the three fields contains the search string.
  - Filtering **MUST** be purely client-side, with React state holding the current query.
  - Empty query **MUST** show all entries.
  - The search input **MUST** have `aria-label="Search glossary"` and a visible placeholder (e.g., "Search 109 terms…" with the count derived from `Object.keys(glossary).length`).
- Notes: at ~150 entries, a per-keystroke filter pass is O(150) substring matches — well under a single frame budget. No debounce needed.

### FR-3: Category facets (derived, not configured)
- Requirement:
  - The page **MUST** render filter chips for the 8 top-level key prefixes — derived at render time from `Object.keys(glossary).map(k => k.split('.')[0])` deduplicated and sorted alphabetically.
  - Multiple chips **MUST** be toggleable independently; selecting zero chips shows all categories.
  - Selected chips compose with the search query via AND (an entry must match the search AND be in one of the selected categories).
  - Each chip **MUST** show the category name + a count of entries in that category (e.g., "study (47)").
- Notes: derivation is keyed off the live `glossary` constant — when a new feature adds entries under a new prefix, the chip bar updates on next build with no manual taxonomy edit.

### FR-4: Deep-linkable anchors
- Requirement:
  - Each entry **MUST** render an element with `id="<glossary-key>"` (the key verbatim, dot-separators included).
  - Navigating to `/guide/glossary#<key>` **MUST** scroll the target into view on initial load, using the browser's native fragment-scroll behavior (no custom scroll logic).
  - Anchored entries **MUST NOT** be hidden by an active search or facet filter on initial load — if a fragment is present in the URL, the route **MUST** reset filters to defaults so the anchored entry is visible. If the user subsequently types in the search box or toggles a facet, normal filtering resumes.
- Notes: this is the affordance that makes the glossary linkable from FAQ entries, blog posts, and (eventually, post-MVP) tooltip "Read more →" links. The anchor scheme matches the natural key shape — no slug rewriting.

### FR-5: Glossary catalog card on `/guide`
- Requirement:
  - [`ui/src/app/guide/page.tsx`](../../../../ui/src/app/guide/page.tsx) **MUST** render a new `<section>` titled "Glossary" below the existing "Visual walkthroughs" section.
  - The section **MUST** contain one `<Card>` linking to `/guide/glossary`, styled consistently with the existing `DOC_REGISTRY` and `GUIDE_REGISTRY` cards (same `<CardHeader>` / `<CardTitle>` / `<CardContent>` shape).
  - The card's body **MUST** state the entry count dynamically (e.g., "109 terms, 8 categories — search and browse").
  - The card **MUST** have `data-testid="glossary-card"` so the catalog vitest can assert on it.

### FR-6: Markdown rendering of `long` entries
- Requirement:
  - Entries with a `long` field **MUST** render their content via `<ReactMarkdown disallowedElements={['script', 'iframe', 'style']} unwrapDisallowed>` — the same safety filter used at [`ui/src/components/common/help-popover.tsx:54`](../../../../ui/src/components/common/help-popover.tsx).
  - Entries with only a `short` field render the `short` content as plain text (no markdown pass needed).
  - Entries with only a `long` field render via the markdown pass and use the key (rendered as `<code>`) as the visible label.
- Notes: a vitest case **MUST** assert the disallowedElements list matches `HelpPopover`'s exactly so the two surfaces can't drift.

### FR-7: Discoverability cross-links
- Requirement:
  - Each of the 10 walkthrough `script.md` files under [`ui/public/guides/<id>/`](../../../../ui/public/guides/) **MUST** gain a one-line footer:
    ```
    > See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.
    ```
  - The footer **MUST** be the last content in the file, separated from the prior content by a blank line. The existing script.md convention ends each file with a `## Reference` section listing the API call and helper commands (verified on `01_register_first_cluster/script.md`); the footer line is appended **after** the `## Reference` section, separated by a blank line. Files without a `## Reference` section take the footer at the end of the existing content.
  - Files affected: `01_register_first_cluster`, `02_review_a_proposal`, `03_create_query_template`, `04_create_query_set`, `05_import_judgments_and_calibrate`, `06_create_and_monitor_study`, `07_browse_proposals`, `08_chat_shell`, `09_generate_judgments_llm`, `10_chat_with_agent` (per `GUIDE_REGISTRY`).
- Notes: this is mechanical — 10 single-line additions. No screenshot, video, or metadata change.

### FR-8: Process integration — three skill-file edits

#### FR-8a: `impl-execute` Step 3 questionnaire extension
- Requirement:
  - [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) Step 3 ("Guide impact assessment — MANDATORY GATE", lines 591-614) **MUST** be extended with two new bullet items in the per-PR questionnaire:
    1. **New terminology:** "Did this PR introduce any new product term (status value, metric name, parameter type, error code, role, regime label) that operators will see in the UI or in a PR body? If yes, list the term + the glossary key it would live under + whether the entry exists in `ui/src/lib/glossary.ts`. **The default action is to add the missing entry in the SAME PR — that's what shipped the term, so that's what should document it.** A `chore_glossary_<slug>` idea file is an *escape hatch only* for explicitly-approved out-of-scope deferrals (e.g., the term is backend-only and won't surface in the UI until a later PR); the deferral must be acknowledged by the operator in the PR description. Otherwise missing entries block Step 8 finalization."
    2. **Drift on existing entries:** "Did this PR change the behavior of an already-documented term (e.g., a metric formula changed, a status transition rule shifted, a default value moved)? If yes, the matching entry in `ui/src/lib/glossary.ts` must have its `long` (or `short`) form updated in the same PR — silent semantic drift in glossary copy is its own bug class. There is no idea-file escape hatch here; drift fixes ship with the behavior change."
  - The edits **MUST** preserve the existing 3 questionnaire items (regenerate / new guide / route mapping) and Step 3's MANDATORY-GATE framing.
  - The Step's enforcement language (blocks Step 8 finalization) **MUST** extend to the new questions.

#### FR-8b: `spec-gen` Step 3 item 11 extension
- Requirement:
  - [`.claude/skills/spec-gen/SKILL.md`](../../../../.claude/skills/spec-gen/SKILL.md) Step 3 item 11 (line 84 — "Tooltips and contextual help (Section 11)") **MUST** be extended to require the tooltip inventory to enumerate the glossary keys each entry will reference.
  - Specifically, the wording change is: *"verify the spec includes a tooltip inventory **and that every entry cites either an existing glossary key (verifiable by `grep` of `ui/src/lib/glossary.ts`) or names a new key to be added in a specific story.**"*
  - The existing rationale (length budget, hover/focus pattern) **MUST** be preserved.

#### FR-8c: `impl-plan-gen` line 111 extension
- Requirement:
  - [`.claude/skills/impl-plan-gen/SKILL.md`](../../../../.claude/skills/impl-plan-gen/SKILL.md) line 111 (Tooltip plan requirement) **MUST** be extended to require the per-tooltip plan checklist to include the **glossary key** and the **source-of-truth comment target** (the existing `// Source-of-truth: <backend/path.py> <Symbol>` comment shape used in `ui/src/lib/glossary.ts` and `ui/src/lib/enums.ts`, not just a bare file path).
  - Specifically, the existing list "tooltip text, trigger, placement, and actual JSX/markup pattern" **MUST** become "tooltip text, trigger, placement, **glossary key, source-of-truth comment target**, and actual JSX/markup pattern from the codebase."
  - The edit **MUST** include a parenthetical naming the literal comment marker so implementers can grep for it: *"(the `// Source-of-truth: <backend/path.py> <Symbol>` comment shape used in `ui/src/lib/glossary.ts` and `ui/src/lib/enums.ts`)"*. Without the marker, the gate's "comment target" phrasing is too vague to teach implementers what to grep for.

#### Why these three and not others (per the idea's locked-decisions section):

The idea explicitly considered and rejected adding equivalent checks to `bug-fix/SKILL.md` (chains into `impl-execute --ad-hoc` which already runs Step 3), `pipeline/SKILL.md` (inherits the impl-execute change), `guide-gen/SKILL.md` (out of scope — generates screenshots, not glossary entries), `idea-preflight/SKILL.md` (audits a single idea, not a general process gate), and a new `glossary-gen` skill (overkill — entries are 2–5 lines of TS; the friction is *remembering* to add them, not *authoring* them). **Gates beat tools here.**

---

## 8) API and data contract baseline

### 7.1 Endpoint surface

**N/A — frontend-only feature.** No new endpoint added.

### 7.2 Contract rules

N/A.

### 7.3 Response examples

N/A.

### 7.4 Enumerated value contracts

**N/A — this feature does not introduce any new filter, sort key, status badge, role label, or dropdown that the backend validates against an allowlist.**

The category-facet chips (FR-3) are populated from `Object.keys(glossary).map(k => k.split('.')[0])` deduplicated — derived from the data, not sent to a backend. There is no wire-value contract to lock against a backend Literal.

### 7.5 Error code catalog

N/A.

## 9) Data model and state transitions

**N/A — no new tables, no schema change, no migration.** Read-only frontend route over the existing in-memory `glossary` constant.

### State transitions

The only stateful behavior is client-side UI state in the page component:
- Search query: `string` (empty by default)
- Selected category chips: `Set<string>` (empty by default; an entry passes the facet if either no chips are selected OR the entry's prefix is in the set)

No data is persisted. URL fragment (`#<key>`) is the only persistent state, written by the browser on link click and read on page load.

### Required invariants

- **No `<script>`, `<iframe>`, or `<style>` element renders inside an entry body.** Enforced by the `react-markdown` `disallowedElements` filter (FR-6). Defense-in-depth alongside the content-shape vitest assertion at [`glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts).
- **Every entry visible on page load is also accessible via its anchor.** The set of anchors `{ id : id ∈ Object.keys(glossary) }` is a bijection with the rendered entries (FR-4).
- **Category-chip labels match key-prefix substrings character-for-character.** The chip "study" filters entries whose key starts with `study.`; no display-name mapping. (Why: avoids a separate label-to-prefix mapping that would need maintenance.)

---

## 10) Security, privacy, and compliance

- **Threats:**
  - **XSS via glossary copy.** Mitigated by the `react-markdown` `disallowedElements` filter (FR-6) — same protection `HelpPopover` ships today. A content-shape vitest case (existing in `glossary.test.ts`) also asserts no entry body contains a raw `<script>` substring.
  - **Open redirect via deep-link fragment.** A URL fragment is not a redirect target; the browser scrolls but does not navigate. Not a real threat surface.
- **Controls:** the `react-markdown` filter is identical to existing surfaces; no new attack surface introduced.
- **Secrets / key handling:** N/A — no secrets touched.
- **Auditability:** N/A — read-only page, no state mutations.
- **Data retention / deletion / export impact:** N/A — no PII, no user-generated data.

---

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** new route `/guide/glossary` lives under the existing "Guides" top-nav entry ([`ui/src/components/layout/top-nav.tsx:15`](../../../../ui/src/components/layout/top-nav.tsx) — `{ href: '/guide', label: 'Guides' }`). No top-nav change. Users arrive via: (a) clicking the new "Glossary" card on `/guide`, (b) following a `/guide/glossary#<key>` deep link from elsewhere, (c) the footer link added to each walkthrough's `script.md` (FR-7).
- **Labeling taxonomy:**
  - Page title (browser tab + page heading): **"Glossary"**.
  - Page description (subhead): **"Every term defined. Search by name or browse by category."** — matches the tone of the existing `/guide` catalog subheads.
  - Search input placeholder: **"Search 109 terms…"** (count derived dynamically from `Object.keys(glossary).length`).
  - Category chip labels: the lowercase key prefix (e.g., `study`, `judgment`, `confidence`) — no Title-Case rewrite, mirrors the keys themselves.
  - Empty-search state heading: **"No terms match."** with a one-line helper "Try fewer characters or clear the category filters."
  - Catalog card title (on `/guide/page.tsx`): **"Glossary"** — same tone as "Tutorial" and "Workflows overview".
  - Catalog card description: **"Browse all 109 terms used across RelyLoop. Search by name or filter by category."** (count derived dynamically.)
- **Content hierarchy** (top → bottom on `/guide/glossary`):
  1. Top breadcrumb bar with `← All guides` link (same shape as `/guide/docs/[slug]`).
  2. Page heading "Glossary" + description.
  3. Search input (full-width on mobile, max-width 480px on desktop, left-aligned).
  4. Category chip row (horizontal scroll on narrow viewports).
  5. Entry list — vertically stacked, grouped by category with a small section header (`<h2>`) per group when no search query is active; flat list (no group headers) when a search query is active so the user sees the global match set.
- **Progressive disclosure:** every entry's `short` and `long` content is visible inline. No collapse/expand. The corpus is small enough (~150 entries) that scroll is acceptable; collapse adds interaction cost without commensurate scan benefit.
- **Relationship to existing pages:** sits alongside the existing `/guide/docs/[slug]` route and the in-page `<GuideViewer>` walkthrough modal. The three surfaces serve three distinct content shapes: long-form prose (docs), screenshot decks (walkthroughs), per-term reference (glossary).

### Tooltips and contextual help

**N/A — this feature *is* the contextual help surface.** No new tooltips introduced; the route renders existing glossary entries in a new view. The only new UI elements (search input, category chips, entry cards) are self-explanatory and don't need tooltips per the spec-gen Step 3 #11 rubric ("non-obvious settings, limits, status indicators, or actions with consequences" — none of which apply here).

### Primary flows

1. **Browse by category** — user clicks the "Glossary" card on `/guide` → arrives at `/guide/glossary` → sees the 8 category sections with headers → scrolls to the section of interest → reads the entries.
2. **Search by name** — user types into the search input → entries filter to those matching → user clicks (mouse) or focuses (keyboard) the desired entry → reads the body.
3. **Deep link from a walkthrough or FAQ** — user follows `/guide/glossary#study.metric.ndcg` → page loads → browser scrolls the targeted entry into view → user reads.
4. **Compose search + category filter** — user toggles the "confidence" chip → list narrows → user types "convergence" → list narrows further to the matching `confidence.convergence_regime` entry.

### Edge / error flows

- **Empty search result:** user types a string with no matches → the entry area shows the "No terms match" message + helper. User clears the query → all entries restore.
- **All categories filtered out:** user toggles every chip off → if zero are selected, all entries show (selecting zero is treated as "no facet filter active"). If the user toggles all 8 chips ON, all entries show (every entry matches at least one selected facet). The only "empty" state is when search+facet compose to zero matches.
- **Malformed URL fragment:** `/guide/glossary#nonexistent.key` — page loads, no entry has that id, the browser scrolls to top, the user sees the full list. No error, no warning.
- **Slow page load:** the page imports `glossary` directly (a single TypeScript constant in the bundle), so there's no fetch. First paint shows the full list immediately.
- **JavaScript disabled:** the route requires `'use client'` so the search + facet UI is JS-driven. With JS disabled, the entry list still renders (Next.js does SSR on initial paint even for client components) but search + facets + deep-link scroll don't work. **Acceptable** — operators run RelyLoop in a modern browser with JS; the no-JS audience is null.

---

## 12) Given/When/Then acceptance criteria

### AC-1: Route serves a static glossary page
- Given the dev server is running and the user navigates to `/guide/glossary`
- When the page loads
- Then the response status is 200 AND the page renders a `<main>` containing a heading "Glossary", a search input, a category chip row, and entry cards for every key in `glossary`.
- Example values:
  - Entry count visible on page: **`Object.keys(glossary).length`** (109 at spec time)

### AC-2: Substring search filters entries
- Given the page is loaded with no active filters
- When the user types `ndcg` into the search input
- Then only entries whose key, `short`, or `long` contains "ndcg" (case-insensitive) remain visible. Other entries are removed from the DOM (not just hidden via CSS) so a screen reader user navigating the entry list doesn't encounter unmatched cruft.
- Example values:
  - Input: `ndcg`
  - Expected visible keys include: `study.metric.ndcg` AND `study.metric` (whose `long` body mentions `ndcg`). Empty-match case: `xyz123` → "No terms match" message.

### AC-3: Category facet narrows entries
- Given the page is loaded with no active filters
- When the user clicks the "confidence" category chip
- Then only entries whose key starts with `confidence.` remain visible; the search input is unchanged; clicking the chip again deselects it and restores all categories.
- Example values:
  - Selecting "confidence" alone: 6 entries shown (`confidence.ci_95`, `confidence.runner_up_gap`, `confidence.late_trial_stddev`, `confidence.convergence_regime`, `confidence.per_query_outcomes`, `confidence.comparison_against`)

### AC-4: Search + facet compose with AND semantics
- Given the page is loaded and the "study" chip is selected
- When the user types `metric` into the search input
- Then only entries whose key starts with `study.` AND whose key/short/long matches "metric" remain visible.

### AC-5: Deep-link fragment scrolls anchored entry into view
- Given the user navigates to `/guide/glossary#study.metric.ndcg`
- When the page loads
- Then the browser scrolls the `<element id="study.metric.ndcg">` entry into view AND the entry is visible regardless of any default-state filters.
- Example values:
  - URL: `/guide/glossary#study.metric.ndcg`
  - Expected: element with `id="study.metric.ndcg"` is in the viewport after page paint.

### AC-6: Malformed fragment falls back to full list
- Given the user navigates to `/guide/glossary#not-a-real-key`
- When the page loads
- Then the page renders normally with no error AND no entry is highlighted AND all entries are visible.

### AC-7: Markdown safety filter matches HelpPopover (behavioral assertion)
- Given a vitest test renders the `/guide/glossary` page with a stub glossary entry whose `long` field contains a hostile payload (e.g., `Hello <script>window.alert(1)</script> world` and `<iframe src="evil"></iframe>` and `<style>body{color:red}</style>`)
- When the page renders into RTL's container
- Then querying for `script`, `iframe`, and `style` elements in the rendered DOM returns **zero** matches for each AND the literal text content "Hello world" is present (proving `unwrapDisallowed` preserved the safe inner content).
- Example values:
  - Test setup: monkey-patch `glossary` via vitest module mock, OR add a single test-only fixture entry under a `__test__` prefix that gets excluded from non-test runs.
  - Assertion: `expect(container.querySelectorAll('script')).toHaveLength(0)` + same for `iframe`, `style`. Optionally cross-check the same payload renders the same shape through `<HelpPopover>` in a sibling test, asserting the two surfaces converge on identical safe-render output.
- Rationale: a source-grep assertion (e.g., grep the page module for the literal `disallowedElements={['script', 'iframe', 'style']}`) is brittle — it can pass on a stale comment or a dead-code path. A behavioral DOM assertion proves the runtime filter actually fires.

### AC-8: Catalog card appears on /guide with dynamic count
- Given the user navigates to `/guide`
- When the page renders
- Then a third `<section>` titled "Glossary" appears below "Visual walkthroughs" with one `<Card>` linking to `/guide/glossary` AND the card body contains the literal string `109 terms` (or whatever `Object.keys(glossary).length` evaluates to at build time).
- Example values:
  - Test assertion: `expect(screen.getByTestId('glossary-card')).toBeInTheDocument()` AND `expect(screen.getByTestId('glossary-card').textContent).toMatch(/\d+ terms/)`.

### AC-9: Script.md footer link present on every shipped guide
- Given each shipped guide's `script.md` file at [`ui/public/guides/<id>/script.md`](../../../../ui/public/guides/)
- When inspected
- Then every file ends with the literal line `> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.`
- Example values:
  - Files asserted: all 10 entries in `GUIDE_REGISTRY` (01..10).
  - A vitest case reads each script.md and asserts the footer is present.

### AC-10: impl-execute Step 3 has glossary questions AND the enforcement clauses that make them effective
- Given the source file [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md)
- When the post-implementation `Step 3: Guide impact assessment` section is read
- Then the questionnaire contains **all** of the following literal substrings:
  1. `"New terminology"` (the bullet header).
  2. `"Drift on existing entries"` (the bullet header).
  3. `ui/src/lib/glossary.ts` (the cited file — must appear at least once in each bullet's scope).
  4. **Same-PR default for new terminology** — at least one of: `"in the SAME PR"` / `"in the same PR — that's what shipped the term"` (capturing the default-add framing).
  5. **Escape-hatch gating** — the literal substring `"escape hatch"` AND `"explicitly-approved"` (capturing that the deferral is not a free-pass).
  6. **No drift escape hatch** — the literal substring `"no idea-file escape hatch"` (so the drift bullet's stricter rule is locked).
  7. **Step 8 blocking** — at least one of: `"Step 8"` / `"blocks Step 8 finalization"` (capturing the gate's enforcement strength).
- Note: enforcement is verified by `ui/src/__tests__/skills/glossary-gate-skill-edits.test.ts` (one file asserts all three skill-file gate edits — AC-10 / AC-11 / AC-12). **Path resolution from a vitest test running with `cwd=ui/`:** the test reads each skill file via `path.resolve(fileURLToPath(new URL('.', import.meta.url)), '../../../../.claude/skills/<file>')` — the `__tests__/skills/` directory sits four levels below the repo root. Verify the resolved path exists in `beforeAll`; fail loudly on resolution miss.

### AC-11: spec-gen Step 3 item 11 cites glossary keys AND requires per-entry grep verification
- Given the source file [`.claude/skills/spec-gen/SKILL.md`](../../../../.claude/skills/spec-gen/SKILL.md)
- When Step 3 item 11 ("Tooltips and contextual help") is read
- Then the text contains **all** of the following literal substrings:
  1. `"every entry cites either an existing glossary key"` (the core requirement).
  2. `ui/src/lib/glossary.ts` (the cited file).
  3. At least one of: `"grep"` / `"verifiable by"` (locking the verification method, not just the assertion).
  4. The phrase **"or names a new key to be added in a specific story"** (locking the new-key path as legitimate).

### AC-12: impl-plan-gen tooltip checklist requires glossary key + source-of-truth comment target
- Given the source file [`.claude/skills/impl-plan-gen/SKILL.md`](../../../../.claude/skills/impl-plan-gen/SKILL.md)
- When line ~111 (Tooltip plan requirement bullet) is read
- Then the text contains **all** of the following literal substrings:
  1. `"glossary key, source-of-truth comment target"` (the new locked phrase inside the per-tooltip checklist).
  2. The reference comment shape — at least one of: `"// Source-of-truth:"` (so reviewers know the exact comment marker to grep for; matches the convention in `ui/src/lib/glossary.ts` and `ui/src/lib/enums.ts`).

### AC-13: E2E real-backend route smoke
- Given the stack is running (`make up`)
- When the Playwright test at `ui/tests/e2e/glossary.spec.ts` runs
- Then it can: (a) navigate to `/guide/glossary` and assert the search input is present, (b) type a substring and assert the entry count decreases, (c) click a category chip and assert filtering works, (d) navigate to `/guide/glossary#study.metric.ndcg` and assert the target element is in view via `await expect(page.locator('#study\\.metric\\.ndcg')).toBeInViewport()`.
- Example values:
  - All four sub-assertions in a single spec file.

---

## 13) Non-functional requirements

- **Performance:**
  - First contentful paint: **≤ 500ms** on a localhost dev server (no backend fetch; one TypeScript constant import).
  - Search keystroke → DOM update: **≤ 16ms** at corpus = 200 entries (the next likely ceiling). At 109 entries, expected ≤ 5ms per keystroke. No debouncing needed.
- **Reliability:** the page is a pure render layer with no fetch — no network failure modes.
- **Operability:** no new logs, metrics, or alerts. The page lives on the same Next.js dev server / Compose `ui` service as the rest of the frontend.
- **Accessibility:**
  - Search input has `aria-label="Search glossary"`.
  - Category chips are `<button type="button" aria-pressed="true|false">` (Radix Toggle pattern); each shows its current state to screen readers.
  - Entry headings are semantic `<h3>` (or appropriate level relative to the page's `<h1>` / `<h2>` hierarchy).
  - `<code>` keys are read aloud as code (browsers + screen readers handle this natively).
  - Keyboard navigation: Tab moves between search → chips → first entry; arrow keys do not change focus within the list (no listbox semantics).
  - Color contrast: chip selected vs unselected states meet WCAG AA — verified by the existing Tailwind `text-muted-foreground` + `bg-secondary` palette which all sibling shadcn components ship.

---

## 14) Test strategy requirements (spec-level)

| Layer | Files | Coverage |
|---|---|---|
| Unit (vitest) | `ui/src/__tests__/app/guide/glossary/page.test.tsx` (new) | Render assertions, search filter logic, facet toggle logic, AND-composition between search + facets, empty-state copy, anchor `id` on every entry, dynamic count rendering. |
| Unit (vitest) | `ui/src/__tests__/app/guide/page.test.tsx` (new — verified no existing file at this path) | Asserts the third `<section>` "Glossary" + `<Card data-testid="glossary-card">` is present and links to `/guide/glossary` (AC-8). |
| Unit (vitest) | `ui/src/__tests__/skills/glossary-gate-skill-edits.test.ts` (new) | Reads `.claude/skills/impl-execute/SKILL.md`, `.claude/skills/spec-gen/SKILL.md`, `.claude/skills/impl-plan-gen/SKILL.md` from disk and asserts the literal phrases per AC-10, AC-11, AC-12 are present. Locks the gate language against silent drift. |
| Unit (vitest) | `ui/src/__tests__/guides/script-footer.test.ts` (new) | Reads all 10 `ui/public/guides/<id>/script.md` files via `fs.readFileSync(path.join(process.cwd(), 'public/guides/<id>/script.md'))` and asserts each ends with the FR-7 footer (AC-9). |
| Component (vitest + RTL) | Same as unit page test | Search input typing, chip toggling, "No terms match" empty state copy. |
| E2E (Playwright real-backend) | `ui/tests/e2e/glossary.spec.ts` (new) | AC-13 — route smoke, search interaction, facet toggle, anchor scroll-into-view. |
| Integration / contract / backend | N/A | Frontend-only feature, no backend touched. |

**No `page.route()` mocking in the E2E spec** — per CLAUDE.md absolute rule. Page is a pure render layer; no backend calls to mock anyway.

---

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md`: add a sub-section ("Glossary route") under the appropriate parent section describing the new `/guide/glossary` surface, its source-of-truth pattern (renders `ui/src/lib/glossary.ts` directly), and the deep-link anchor scheme. **MUST** cite [`feature_spec.md`](feature_spec.md) for the contract.
- `docs/02_product/`: no edit (this spec is the docs surface).
- `docs/03_runbooks/`: no edit (no operator-facing runbook change).
- `docs/04_security/`: no edit (no new security surface — the markdown safety filter is documented at the call site).
- `docs/05_quality/`: no edit (test coverage rules unchanged; the new vitest + Playwright cases inherit existing conventions).
- `docs/08_guides/README.md`: add an "In-app glossary route" line under the MVP1 list with a one-line description, pointing at `/guide/glossary` and noting that the canonical content lives in `ui/src/lib/glossary.ts`.
- `CLAUDE.md`: add a one-line entry to "Common Pitfalls" — **"Do not inline glossary entries into the `/guide/glossary` page or any other surface — always import from `ui/src/lib/glossary.ts`."**
- `state.md`: update on finalization per CLAUDE.md convention (28th MVP1 feature, etc. — handled by `impl-execute` Step 8).

---

## 16) Rollout and migration readiness

- **Feature flag / staged rollout:** none. The route is read-only, single-tenant, and discoverable only via explicit navigation — no traffic-shaping needed.
- **Migration / backfill:** N/A. No schema change.
- **Operational readiness gates:** the route ships with the rest of `make up`; no separate runbook, no separate deploy concern.
- **Release gate:** the standard PR gate (CI green: backend unit / integration / contract / lint / typecheck + frontend lint / typecheck / vitest / Playwright real-backend smoke + Docker buildx for `relyloop/api`). No additional gate.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories (per impl-plan-gen output) | Test files / suites | Docs to update |
|---|---|---|---|---|
| FR-1 (route) | AC-1 | F-1 (create page), F-2 (catalog card) | `glossary/page.test.tsx`, `glossary.spec.ts` | `docs/01_architecture/ui-architecture.md`, `docs/08_guides/README.md` |
| FR-2 (search) | AC-2, AC-4 | F-1 | `glossary/page.test.tsx`, `glossary.spec.ts` | — |
| FR-3 (facets) | AC-3, AC-4 | F-1 | `glossary/page.test.tsx`, `glossary.spec.ts` | — |
| FR-4 (anchors) | AC-5, AC-6 | F-1 | `glossary/page.test.tsx`, `glossary.spec.ts` | — |
| FR-5 (catalog card) | AC-8 | F-2 | `app/guide/page.test.tsx` | `docs/01_architecture/ui-architecture.md` |
| FR-6 (markdown filter) | AC-7 | F-1 | `glossary/page.test.tsx` (filter-arg assertion) | — |
| FR-7 (script.md footers) | AC-9 | F-3 | `script-footer.test.ts` | `docs/08_guides/README.md` |
| FR-8a (impl-execute gate) | AC-10 | F-4 | `glossary-gate-skill-edits.test.ts` | — |
| FR-8b (spec-gen gate) | AC-11 | F-4 | `glossary-gate-skill-edits.test.ts` | — |
| FR-8c (impl-plan-gen gate) | AC-12 | F-4 | `glossary-gate-skill-edits.test.ts` | — |

Stories (F-1, F-2, F-3, F-4) are placeholders for the implementation-plan output; final story IDs are assigned by `impl-plan-gen`.

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-13) pass in CI.
- [ ] vitest layer green (`ui/src/__tests__/app/guide/glossary/`, `ui/src/__tests__/app/guide/page.test.tsx`, `ui/src/__tests__/skills/glossary-gate-skill-edits.test.ts`, `ui/src/__tests__/guides/script-footer.test.ts`).
- [ ] Playwright E2E green (`ui/tests/e2e/glossary.spec.ts` against real backend).
- [ ] Three SKILL.md edits applied verbatim per AC-10, AC-11, AC-12; vitest assertion locks the gate language.
- [ ] Catalog card appears on `/guide` with dynamic entry count (AC-8).
- [ ] Footer present on all 10 script.md files (AC-9).
- [ ] Doc updates merged: `ui-architecture.md`, `docs/08_guides/README.md`, `CLAUDE.md` "Common Pitfalls" line.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None remaining at spec-completion time.

### Decision log

- **2026-05-22 — D-1 — Single-phase delivery, no `phase2_idea.md`.** Total scope ≈ 200 LOC frontend + 10 markdown footers + 3 skill edits + ~120 LOC tests. Splitting adds coordination cost > savings. Idea's "Discoverability" / `StartHereChecklist` proposal moved to **out of scope** (D-6 below) so the phase boundary is genuinely clean.

- **2026-05-22 — D-2 — Substring search, not fuzzy.** Corpus is 109 entries (≤200 ceiling for the foreseeable future). Substring filter is sufficient; no new dep (`fuse.js` / `match-sorter` rejected as bundle weight for negligible UX gain).

- **2026-05-22 — D-3 — "Read more →" tooltip / popover affordance deferred.** The HelpPopover body currently renders the entry's `long` field with no exit point. Adding "Read more →" linking to `/guide/glossary#<key>` is a natural follow-up but defer until the route ships and we can measure click-through. The deep-link anchors (FR-4) are designed now so this follow-up is non-breaking.

- **2026-05-22 — D-4 — No search highlighting.** Yellow-highlight of matched substrings inside entry bodies adds rendering complexity (re-tokenize + wrap match runs in `<mark>`); substring filter alone is sufficient for v1. Re-evaluate if operators report difficulty locating their search term within a long entry.

- **2026-05-22 — D-5 — No sticky sidebar nav.** The category facet chips at the top of the page serve the same "jump to category" need at less render cost. A sticky sidebar is the default React pattern for this corpus shape but adds layout complexity without commensurate scan benefit at 109 entries.

- **2026-05-22 — D-6 — No `StartHereChecklist` integration.** The idea's "Discoverability" section proposes adding a glossary step. The component at [`ui/src/components/dashboard/start-here-checklist.tsx`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) is shaped as a 3-step **action** sequence where each step auto-completes when state changes; "Learn the terminology" is a read-only step with no completion signal and would break the component's structural invariant. The top-nav "Guides" link + the new catalog card (FR-5) + the script.md footers (FR-7) are sufficient discoverability surfaces. Re-evaluate at MVP2 if operator feedback says the route is hard to find.

- **2026-05-22 — D-7 — Process integration ships in the same PR as the route, not a follow-up.** Per the idea's locked decisions and the user's explicit "one branch, one PR" directive for the three sibling chore_guides_* items. Shipping just the route without the gates means the glossary drifts the moment a feature ships new UI terms without entries — exactly the failure mode the gates exist to prevent.

- **2026-05-22 — D-8 — Glossary entry rendering preserves the same shape across `short` / `long` / dual.** Entries with only `short` render the short text plain; entries with `long` render the markdown body; entries with both render the short as a primary label and the long as a body below. No render-time field promotion (e.g., synthesizing a `short` from the first sentence of `long`). Avoids drift between the rendered surface and the source-of-truth shape.
