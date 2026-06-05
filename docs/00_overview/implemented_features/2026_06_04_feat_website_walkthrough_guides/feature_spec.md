# Feature Specification — Walkthrough guides on the public website (relyloop.com)

**Date:** 2026-06-04
**Status:** Draft
**Owners:** Product (soundminds.ai) · Engineering (`@SoundMindsAI/relyloop` maintainers)
**Related docs:**
- [`idea.md`](idea.md) — origin brief (preflight-refreshed 2026-06-04)
- [`pipeline_status.md`](pipeline_status.md) — pipeline stage tracker
- [`website/mkdocs.yml`](../../../../../website/mkdocs.yml) — current site config
- [`website/requirements.txt`](../../../../../website/requirements.txt) — Python build deps
- [`.github/workflows/deploy-docs.yml`](../../../../../.github/workflows/deploy-docs.yml) — current site build/deploy
- [`.github/workflows/copy-docs-freshness.yml`](../../../../../.github/workflows/copy-docs-freshness.yml) — own-workflow freshness-gate precedent
- [`ui/scripts/copy-docs.mjs`](../../../../../ui/scripts/copy-docs.mjs) — single-direction-mirror pattern reference
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) — not applicable (no API surface), cited for completeness

---

## 1) Purpose

- **Problem:** The published site at **relyloop.com** ships only prose pages (Home, Roadmap, Getting Started, Concepts, Engines, Community). It contains no screenshots, no walkthroughs, and no video — none of the rich onboarding content that already lives in-repo (4 long-form markdown guides + 10 screenshot/video walkthrough decks). Prospective users evaluating RelyLoop never see the visual proof of "what the product looks like and how it flows," which is precisely the material they need to decide whether to clone and try it.
- **Outcome:** All 10 walkthrough decks (PNG + WebM, plus a locally-generated MP4 for mobile Safari) and all 4 long-form in-depth guides are published to relyloop.com under a new top-level **Guides** nav tab. Pages are responsive, video plays inline on iOS, screenshots are pinch/click-zoomable via `mkdocs-glightbox`. A Python generator + a CI freshness gate keep the site in lockstep with the in-repo source — so when `guide-gen` regenerates screenshots, or a maintainer edits a long-form guide, the website re-publishes automatically and a stale-source PR is rejected.
- **Non-goal:** Reuse of the internal Next.js app's `GuideViewer` / `MarkdownDoc` components; the website renders its own MkDocs pages from the same source assets. No changes to how guides are authored (`guide-gen` skill stays the single producer). No changes to the in-app guide reader.

## 2) Current state audit

### Existing implementations

| Surface | What it does today | Path | Notes from audit |
|---|---|---|---|
| In-app guide reader (internal-only) | Next.js renders the 3 in-app long-form guides via `/guide/docs/[slug]` (a `<MarkdownDoc>` reader); the 10 walkthrough decks render via the `<GuideViewer>` modal triggered from the `/guide` catalog page + per-resource `<GuideTrigger>` buttons. The `<GuideViewer>` consumes `ui/public/guides/<slug>/metadata.json` + the WebM via a plain `<video src="/guides/<slug>/<video>">` (no MP4 source today). | `ui/src/app/guide/`, `ui/src/components/guides/guide-viewer.tsx:305-306`, `ui/scripts/copy-docs.mjs` | Source of truth = `docs/08_guides/` (3 of 4 mirrored into `ui/public/docs/` at build; `llm-endpoint-setup.md` is NOT in the `DOCS` array) + `ui/public/guides/<NN_slug>/` (PNG + WebM + `metadata.json` + `script.md`). The published site does not consume any of this. |
| Public website (MkDocs Material) | 12 prose pages organized into Home / Roadmap / Getting Started / Concepts / Engines / API Reference / Blog / Changelog / Community | `website/docs/**`, `website/mkdocs.yml` | Built `mkdocs build --strict` by `deploy-docs.yml` on push to main, deployed to GitHub Pages. Hand-written `nav:` block — no `awesome-pages`/`literate-nav` plugin. `pymdownx.snippets` is configured with `auto_append: [includes/abbreviations.md]` — already exercised. Theme uses `navigation.tabs + navigation.sections + navigation.expand`. |
| Walkthrough source assets | 10 decks × { `metadata.json`, `script.md`, 4–5 numbered PNGs, `walkthrough.webm` } | `ui/public/guides/0[1-9]_*`, `ui/public/guides/10_*` | Verified at preflight: 48 PNGs total (5/5/5/5/4/5/5/4/5/5 per deck), 10 WebMs, ~7.6 MB on disk. **No MP4s exist yet** — `walkthrough.mp4` absent across all 10 decks. |
| Long-form guides | 4 markdown files: `tutorial-first-study.md` (23.3 K, 30-min E2E tutorial), `quick-tour.md` (17.2 K), `workflows-overview.md` (29.6 K), `llm-endpoint-setup.md` (9.9 K) | `docs/08_guides/` | 3 of the 4 are mirrored into `ui/public/docs/` by `copy-docs.mjs` for the in-app reader. `llm-endpoint-setup.md` is currently NOT in the `DOCS` list of `copy-docs.mjs:67-71` (preserved for backend-context discoverability via `docs/08_guides/` directly). |
| Existing outbound GitHub-blob links on the published site | Two existing absolute links to repo paths under `docs/08_guides/` | `website/docs/getting-started/install.md:85` → `https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/llm-endpoint-setup.md`; `website/docs/getting-started/quickstart.md:66` → `https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md` | These two outbound links MUST be repointed at the new in-site pages once this feature ships. |
| Generated-artifact freshness pattern | Three gates: `generated-artifacts-fresh` (in pr.yml) for `ui/openapi.json` + `ui/src/lib/types.ts`; `copy-docs-freshness.yml` (own workflow) for `ui/public/docs/`; a single canonical fix at `scripts/regen-generated-artifacts.sh` | `.github/workflows/pr.yml` lines 225–272, `.github/workflows/copy-docs-freshness.yml`, `scripts/ci/verify_copy_docs_fresh.sh`, `scripts/ci/test_verify_copy_docs_fresh.sh` | `copy-docs-freshness.yml` deliberately lives in its own workflow to **escape `pr.yml`'s `paths-ignore: ['website/**', 'docs/**']`** so docs-only PRs still validate the sync. The same logic applies to the new website-guides gate. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| `website/docs/getting-started/quickstart.md:66` | `https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md` | `../guides/in-depth/tutorial-first-study.md` (in-site) |
| `website/docs/getting-started/install.md:85` | `https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/llm-endpoint-setup.md` | `../guides/in-depth/llm-endpoint-setup.md` (in-site) |
| `website/mkdocs.yml` `nav:` | Top-level nav has no `Guides` tab | Insert `Guides:` between `Engines:` and `API Reference:` with two children: `Walkthroughs:` (index + 10 decks) and `In-depth:` (4 long-form). Hand-written, no nav plugin. |

No in-app references change. The in-app `GuideViewer` continues to consume `ui/public/guides/` directly; this feature only ADDS a second consumer (the website) on the same source assets.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/scripts/copy-docs.prune.test.ts` | exercises `copy-docs.mjs` prune logic against an in-memory fixture | 1 spec | None — feature does not change `copy-docs.mjs`. The pattern is reused for `build_guides.py` tests. |
| `scripts/ci/test_verify_copy_docs_fresh.sh` | self-test harness for the freshness gate | 1 script | None — feature adds an analogous `test_verify_build_guides_fresh.sh` script following the same harness shape. |
| `backend/tests/unit/scripts/test_run_tests_in_worktree.py` | unit-test precedent for a repo-level Python script | reference only | New unit tests live alongside in `backend/tests/unit/scripts/test_build_guides.py`. |

### Existing behaviors affected by scope change

- **`deploy-docs.yml` build path:** Current: `pip install -r website/requirements.txt && mkdocs build --strict`. New: same — the generator runs locally (developer machine or `guide-gen` skill), assets are pre-committed under `website/docs/assets/guides/` and `ui/public/guides/`, the deploy runner consumes them as-is. No ffmpeg in CI. Decision needed: **no** (locked at preflight as Option A "commit-and-mirror").
- **`pr.yml` `paths-ignore: ['website/**']`:** Current: a website-only PR (edit one `website/docs/*.md`) skips all `pr.yml` jobs. New: the freshness gate's own workflow has NO paths-ignore filter, so a website-only PR still validates the source-↔-website sync. Decision needed: **no** (mirrors the `copy-docs-freshness.yml` precedent).
- **`ui/public/guides/<slug>/walkthrough.mp4`:** Currently absent. New: committed alongside `walkthrough.webm` after the local generator transcodes once per deck. The in-app `GuideViewer` is NOT modified to consume the MP4 in this feature — it continues to play WebM only (Chrome/Firefox/Safari-macOS all play WebM; the MP4 only matters for iOS Safari, which the in-app reader doesn't currently target). Decision needed: **no** — adding MP4 consumption to `GuideViewer` is out-of-scope follow-on work; the file just sits next to the WebM as a static asset the website pulls in.

---

## 3) Scope

### In scope

- A single Python generator at `website/scripts/build_guides.py` that:
  1. Reads `ui/public/guides/<slug>/metadata.json` for each deck, copies the PNGs + WebM + MP4 (when present) into `website/docs/assets/guides/<slug>/`, and emits a generated MkDocs page at `website/docs/guides/walkthroughs/<slug>.md` whose content is title + estimated-time/tags admonition + video block + numbered screenshot rows (caption from `metadata.json`).
  2. Reads each long-form guide in `docs/08_guides/{tutorial-first-study,quick-tour,workflows-overview,llm-endpoint-setup}.md`, rewrites all `[text](path)` link targets according to the rules in §7-FR-2, strips presenter comments matching `<!-- presenter: ... -->`, and writes the result to `website/docs/guides/in-depth/<basename>.md`.
  3. Emits a Walkthroughs index at `website/docs/guides/walkthroughs/index.md` (the overview/card-grid landing page) and an In-depth index at `website/docs/guides/in-depth/index.md`.
  4. Emits/refreshes a managed `nav:` fragment in `website/mkdocs.yml` between BEGIN/END markers so the generator output and the nav stay in lockstep. The non-managed nav remains hand-written.
  5. Prunes any file under `website/docs/guides/walkthroughs/`, `website/docs/guides/in-depth/`, or `website/docs/assets/guides/` whose name is not in the regenerated set (idempotent on a clean tree; mirrors `pruneStale` in `copy-docs.mjs:81-90`).
- A local WebM→MP4 transcode helper (subprocess to `ffmpeg`) that runs only when `ffmpeg` is on PATH, is **never** invoked in CI, and writes the MP4 alongside the WebM in the source `ui/public/guides/<slug>/walkthrough.mp4`. When `ffmpeg` is absent or transcode fails, the generator logs a warning and continues (MP4 is best-effort; WebM-only is still a valid published deck).
- A new top-level **Guides** nav tab inserted into `website/mkdocs.yml` between **Engines** and **API Reference**, with two child sections:
  - **Walkthroughs** — overview index + 10 deck pages.
  - **In-depth** — overview index + 4 long-form guides.
- `mkdocs-glightbox` plugin enabled in `website/mkdocs.yml` for auto-lightbox image zoom, mobile-friendly pinch.
- A small `website/docs/stylesheets/extra.css` (registered via `extra_css:`) sized for: responsive video (`max-width:100%; height:auto`), responsive screenshots (`max-width:100%`), walkthrough-index card grid.
- A CI freshness gate at `.github/workflows/build-guides-freshness.yml` (own workflow, mirroring `copy-docs-freshness.yml`) that re-runs the generator and fails on `git status --porcelain` drift across the gate scope (§7-FR-6).
- A chained fix entry in `scripts/regen-generated-artifacts.sh` so the canonical "one paste" recovery includes `build_guides.py`.
- Two existing outbound GitHub-blob links de-duplicated to point at the new in-site pages (`install.md:85`, `quickstart.md:66`).

### Out of scope

- The Material `social` plugin (OG images for Guides pages). Intentionally deferred — the plugin needs system Cairo libraries that the Pages runner lacks (per `website/requirements.txt` comment). The `imaging` extra is already installed for future opt-in. Captured in §19 Open questions for follow-up.
- Adding native MP4 consumption to the in-app `GuideViewer` / `walkthrough` route. The MP4 file is committed but the in-app reader continues to play the WebM source. Cap captured as a deferred follow-up (no `phase*_idea.md` — this is a one-line component change, not phased scope).
- Any awesome-pages / literate-nav plugin to auto-discover the nav. The idea explicitly states "Keep the hand-written `nav:` block (no nav plugin)" — the generator emits a managed fragment between markers, the rest stays hand-written.
- Reusing the in-app React `GuideViewer` for the website. Diverges from the project's two-renderer split (Next.js for in-app, MkDocs for public). The website gets its own generated MkDocs pages.
- Visual regression review of the new website pages. The screenshots themselves are already cross-model-reviewed by the `guide-gen` skill at capture time; the website is a passive consumer.
- Changes to how `guide-gen` produces the source assets. The generator consumes whatever `guide-gen` writes.
- E2E or unit tests on the in-app `GuideViewer` (no change there).

### API convention check

- **Endpoint prefix convention:** N/A — no API surface. This feature touches only the public docs site, the in-repo source assets, and a CI gate.
- **Router namespace for this feature's endpoints:** N/A.
- **HTTP methods for CRUD:** N/A.
- **Non-auth error envelope shape:** N/A.
- **Auth error shape:** N/A.

### Phase boundaries

**Single phase.** Per user-confirmed decisions at preflight (idea.md §"Proposed capabilities"), all three slices — walkthrough deck surfacing, embedded video (MP4 + WebM), and long-form porting — ship together as one PR. There is no Phase 2. No `phase*_idea.md` is required.

If the implementation plan later splits this into multiple stories spanning weeks of calendar time, that's a story-level sequencing question for `/impl-plan-gen` to resolve; the spec scope is single-shot.

---

## 4) Product principles and constraints

- **Two consumers, one source of truth.** `ui/public/guides/<slug>/*` (PNG + WebM + MP4) and `docs/08_guides/*.md` remain the canonical sources; the in-app reader and the website both copy from them. The generator never edits the source.
- **Deploy CI stays Python-only.** The Pages runner already pins to `setup-python@v6 + python-version: "3.12" + pip install -r website/requirements.txt`; the generator is pure Python (stdlib only — no third-party deps beyond what mkdocs-material + mkdocs-glightbox already require) so the build path needs no Node, no ffmpeg, no platform-specific binary.
- **Hand-written nav stays hand-written.** The generator emits ONE managed fragment between BEGIN/END markers inside `mkdocs.yml`'s `nav:` block; the rest stays hand-written. `--strict` will fail if generated pages exist outside the managed nav, which is the regression signal.
- **Source-of-truth comments on generated files.** Every generated `.md` file begins with `<!-- GENERATED by website/scripts/build_guides.py from <SOURCE> — DO NOT EDIT. -->` so an editor who tries to fix typos in the website tree is redirected to the source.
- **Mobile-safe video.** `<video controls playsinline preload="metadata">` with `<source type="video/mp4">` listed FIRST then `<source type="video/webm">`. iOS Safari needs MP4 + `playsinline`; everyone else falls back to WebM. A download link below the video (`<a href="…webm">Download video</a>`) is a last-resort fallback.
- **Mobile-first responsive.** Material's default responsive behavior covers the page chrome; `extra.css` makes screenshots + the video block fluid-width. No JS, no media queries — `max-width:100%; height:auto` is sufficient for both.
- **No build-time network calls.** The generator is hermetic — reads local files only. No CDN fetches, no remote schema validation.
- **Fail loudly on unmapped links.** If a long-form guide contains a `../` link prefix the generator's rewrite table doesn't recognize, the generator exits non-zero with the offending file:line. `mkdocs build --strict` would already fail on a broken in-site link, but the generator's failure happens earlier with a clearer diagnostic.

### Anti-patterns

- **Do not** invoke `ffmpeg` from `deploy-docs.yml`. The deploy CI is Python-only; adding ffmpeg expands the maintenance surface (apt-cache resolution, codec licensing, runner image drift) for zero runtime benefit since the MP4 is already committed. The transcode runs on developer machines or the `guide-gen` skill's runner only.
- **Do not** consume `ui/public/guides/<slug>/script.md` (the presenter narration). It's a stage script for the screenshot capture pass, not user-facing prose. The website pages render `metadata.json` captions, full stop.
- **Do not** copy the source PNGs and WebMs into `website/docs/assets/guides/` via an unconditional `cp -r`. The generator MUST prune anything in the destination tree that's not in the regenerated set (mirrors `copy-docs.mjs:81-90`), otherwise a renamed or removed deck leaves a stale public copy that ships forever.
- **Do not** add a build-time check that says "MP4 must exist for every deck." MP4 is best-effort — drift between WebM and MP4 is tolerated by the gate so the deploy runner stays Python-only. Surface drift via a local pre-commit warning if you want, but don't block CI.
- **Do not** generate the website pages from the in-app React components via a JSX-to-Markdown shim. The two renderers diverge intentionally — the public site has its own typography, nav, and tooltip vocabulary.
- **Do not** add `<video src="…">` without `<source>` children. The dual-format MP4/WebM source list is the whole point of the iOS-mobile-Safari fix.
- **Do not** edit `website/docs/guides/walkthroughs/<slug>.md` or `website/docs/guides/in-depth/<slug>.md` by hand. They are GENERATED — every push to main re-derives them, hand edits are silently lost. The `<!-- GENERATED -->` header makes this unambiguous.
- **Do not** add `awesome-pages` / `literate-nav` to swap the hand-written nav. Idea D-1 explicitly preserves the hand-written `nav:` block.

## 5) Assumptions and dependencies

- **Dependency:** `ui/public/guides/<slug>/metadata.json` + PNG + WebM are already committed (10 decks × 4-5 PNGs × 1 WebM, verified at preflight: 48 PNGs, 10 WebMs, ~7.6 MB on disk).
  - Why required: the generator copies these into `website/docs/assets/guides/`.
  - Status: implemented (shipped by `guide-gen` runs 2026-05–06).
  - Risk if missing: a deck whose `metadata.json` is absent is skipped with a WARN log; the generator does not fail (so a partial-state working tree is not a CI block). The freshness gate catches it as drift.
- **Dependency:** `docs/08_guides/*.md` source for the 4 long-form guides.
  - Why required: the generator rewrites links + ports the content into the website.
  - Status: implemented (`tutorial-first-study.md`, `quick-tour.md`, `workflows-overview.md`, `llm-endpoint-setup.md` all present and being actively maintained).
  - Risk if missing: same WARN-then-skip behavior. The 4-file list is hard-coded in the generator (mirrors the explicit `DOCS` array in `copy-docs.mjs:67-71`) so a NEW guide that ships into `docs/08_guides/` does NOT auto-publish — it must be added to the generator's list. This is deliberate (matches the in-app reader's behavior and gives editorial control).
- **Dependency:** `mkdocs-glightbox` PyPI package, latest v0.5.2 (per `https://pypi.org/pypi/mkdocs-glightbox/json` at spec time). MIT-licensed; depends on `selectolax>=0.3.29`.
  - Why required: provides auto-lightbox image zoom (mobile pinch + desktop click-to-zoom) without per-page wrapper markup.
  - Status: external dependency, well-maintained, used by `mkdocs-material`-stack sites.
  - Risk if missing: screenshots don't zoom — pages still render, just less usable on small screens.
- **Dependency:** `ffmpeg` on developer machine or `guide-gen` skill's runner.
  - Why required: WebM→MP4 transcode (H.264 baseline for iOS Safari).
  - Status: verified locally at `/usr/local/bin/ffmpeg` (v8.1.1 at spec time). The `guide-gen` skill already requires ffmpeg for the WebM capture step, so any environment that produces WebMs can also produce MP4s.
  - Risk if missing: the generator skips the MP4 step with a warning. The website pages still ship; iOS Safari users see the download-link fallback instead of inline playback.
- **Dependency:** `pip install -r website/requirements.txt` in `deploy-docs.yml` (lines 27, 37).
  - Why required: installs `mkdocs-material[imaging]` + `pymdown-extensions` + (new) `mkdocs-glightbox` on the runner.
  - Status: already implemented. Feature adds one line to `requirements.txt` and re-pins the new entry.
  - Risk if missing: deploy fails with a clear `mkdocs build` plugin-not-found error.
- **Dependency:** None on backend, frontend (Next.js app), DB, or any RelyLoop services. This feature touches only the website + repo source-assets + one CI gate.

---

## 6) Actors and roles

- Primary actor: **Public-site visitor** (prospective RelyLoop user evaluating the project) — anonymous read-only.
- Secondary actor: **Maintainer** who regenerates screenshots/long-form guides — runs `bash website/scripts/build_guides.py` (or `bash scripts/regen-generated-artifacts.sh`) locally, commits the result.
- Tertiary actor: **CI** — runs the freshness gate on every PR + the deploy workflow on push to main.

### Authorization

N/A — single-tenant install, no auth surface. Public website is a static site served by GitHub Pages.

### Audit events

N/A — public docs site, no state mutations.

---

## 7) Functional requirements

### FR-1: Walkthrough deck pages generated from source assets

- Requirement:
  - The generator **MUST** emit one MkDocs page per deck at `website/docs/guides/walkthroughs/<slug>.md`, where `<slug>` is the deck folder name (`01_register_first_cluster`, …, `10_chat_with_agent`).
  - Each page **MUST** contain, in order: (a) the `<!-- GENERATED -->` source comment, (b) the deck title as an `# H1`, (c) an MkDocs `!!! info` admonition listing `metadata.json`'s `estimated_time` and `tags`, (d) the responsive `<video>` block (FR-3) when `metadata.json.video` is set and the file exists, (e) each screenshot as `## Step N — <caption first 8 words>` followed by `![<full caption>](../../assets/guides/<slug>/<file>)`, (f) a footer link "← Back to walkthroughs" pointing at `index.md`.
  - The generator **MUST** copy every referenced PNG + WebM + MP4 from `ui/public/guides/<slug>/` into `website/docs/assets/guides/<slug>/` (idempotent on a clean tree).
  - The generator **SHOULD** preserve PNG file ordering by sorting on the leading `NN-` numeric prefix so screenshots render in capture order.
- Notes: H2 captions are `## Step N — <first-N-words>` (not the full caption) so the auto-generated table-of-contents stays readable; the full caption sits under the screenshot as alt+visible text. Existing `metadata.json` captions are sentences, not headings.

### FR-2: Long-form guide pages with link rewriting

- Requirement:
  - The generator **MUST** read each guide in `LONG_FORM_GUIDES = ["tutorial-first-study.md", "quick-tour.md", "workflows-overview.md", "llm-endpoint-setup.md"]` and write to `website/docs/guides/in-depth/<basename>`.
  - **Scope (C1-A10).** The link rewriter applies ONLY to **inline Markdown links** of the form `[text](url)` (the `]\((?P<url>[^)]+)\)` syntax). Image links (`![alt](url)`), reference-style links (`[text][ref]` + `[ref]: url`), HTML `<a href="...">`, autolinks (`<https://...>`), and anything inside fenced code blocks (` ``` ... ``` `) or inline code (`` `…` ``) are **NOT rewritten**. The generator MUST detect any of these unsupported link syntaxes pointing at a relative repo path (per the "relative detection" definition below) and emit a non-zero exit with `file:line` plus the offending syntax.
  - **Relative-path detection (addresses C3-A2).** A target is "relative" (and thus a candidate for rewriting OR for fail-loud unsupported-syntax detection) if and only if `urllib.parse.urlsplit(target)` returns `scheme == ""` AND `netloc == ""`. This is the correct discriminator: a `mailto:foo@bar` URL has `scheme == "mailto"` and is therefore absolute (not relative), so it never trips the unsupported-syntax check. Similarly `tel:`, `data:`, `javascript:`, etc., are all absolute by this definition.
  - **Rule ordering (addresses C3-A1).** The generator parses the URL with `urllib.parse.urlsplit(url)` into `(scheme, netloc, path, query, fragment)`, then applies rules in this order, checking on the parsed object — NOT on the raw URL string — for rules 1+2:
    1. **Absolute URLs** — `scheme != ""` (covers `https`, `http`, `mailto`, `tel`, `data`, `javascript`, …) → passed through unchanged. The generator MAY emit a WARN if `scheme in {"javascript", "data"}` (potential security flag).
    2. **Bare in-page anchors** — `scheme == "" AND netloc == "" AND path == "" AND fragment != ""` (`^#anchor`-only target) → passed through unchanged.
    3. **Intra-list links** (path-only rule) — `path` matches `^(?:\./)?<basename>$` where `<basename>` is one of the four in `LONG_FORM_GUIDES` → rewrite to `<basename>` (the leading `./` is stripped; MkDocs strips `.md` per `use_directory_urls: true`). The original `query` + `fragment` are reattached unchanged via `urlunsplit`.
    4. **Off-site repo-relative links** (path-only rule) — `path` starts with `../` (escapes the `docs/08_guides/` directory). Normalize against the source file's `docs/08_guides/` location to yield a repo-rooted path (e.g., `../../backend/tests/smoke/test_tutorial_path.py` → `backend/tests/smoke/test_tutorial_path.py`; `../01_architecture/` → `docs/01_architecture/`). Reject any normalized path that escapes the repo root (`..` beyond `<repo-root>/`). Then:
       - **(a) Validates the resolved repo path exists in the working tree.** A file or directory at `<repo-root>/<resolved-path>` MUST exist — if absent, the generator exits 1 with `ERROR: <source-file>:<line> unresolved repo link "<original-target>" (resolved to "<resolved-path>", not found in tree)` (addresses C1-A1).
       - **(b) Emits a GitHub URL keyed on file-vs-dir:** files → `https://github.com/SoundMindsAI/relyloop/blob/main/<resolved-path>`; directories (the resolved path is `os.path.isdir()` or the original `path` ends with `/`) → `https://github.com/SoundMindsAI/relyloop/tree/main/<resolved-path>` (addresses C1-A3). The original `query` + `fragment` are reattached via `urlunsplit` after the GitHub-URL substitution.
  - The generator **MUST** fail with exit code 1, a clear error message naming `file:line` and the offending target, when an inline-Markdown link does not match any rule above.
  - The generator **MUST** strip HTML comments matching `<!-- presenter: ... -->` (presenter narration that leaks into source occasionally).
  - The generator **MUST** prepend the `<!-- GENERATED -->` source comment to the top of each output file.
- Notes: Verified at preflight, the four guides currently contain **at least 8 off-site repo-relative inline links**: `tutorial-first-study.md:12` (1 link → `backend/tests/smoke/...`), `quick-tour.md:382` (1 → `docs/01_architecture/`, **directory target → `/tree/` URL**), `workflows-overview.md:48, 54, 198, 204` (4 → `docs/03_runbooks/*.md`, `docs/01_architecture/llm-orchestration.md`), `llm-endpoint-setup.md:211` (2 — `docs/01_architecture/llm-orchestration.md` + `docs/03_runbooks/local-dev.md`). Plus intra-list links between guides (`quick-tour.md` ↔ `tutorial-first-study.md`; `workflows-overview.md` ↔ `tutorial-first-study.md`). AC-2 is generic (`all repo-relative `../` links are rewritten`) rather than counting; FR-2's path-existence check is the authoritative guard.

### FR-3: Embedded video, mobile-safe

- Requirement:
  - **Locked filename contract (addresses C1-A4 + C1-B7).** `metadata.json.video` **MUST equal `"walkthrough.webm"`** for every deck — the generator validates this and exits 1 on any other value (`ERROR: deck=<slug> metadata.json.video must be "walkthrough.webm", got "<value>"`). The paired MP4 filename is **derived**, never read from metadata: `walkthrough.mp4`. This eliminates the path-traversal class entirely (`metadata.json` cannot influence the video pathnames).
  - The generator **MUST** emit an HTML5 `<video>` block (inside `md_in_html` — already enabled in `mkdocs.yml`) for every deck whose `metadata.json.video == "walkthrough.webm"` AND whose source `walkthrough.webm` file exists on disk under `ui/public/guides/<slug>/`.
  - The video block **MUST** have this shape (MP4 source FIRST so iOS Safari picks it):
    ```html
    <video controls playsinline preload="metadata" class="walkthrough-video">
      <source src="../../assets/guides/<slug>/walkthrough.mp4" type="video/mp4">
      <source src="../../assets/guides/<slug>/walkthrough.webm" type="video/webm">
      <p>Your browser cannot play the embedded video.</p>
    </video>
    <p class="walkthrough-video-download">Trouble playing? <a href="../../assets/guides/<slug>/walkthrough.webm">Download the walkthrough video</a>.</p>
    ```
  - **iOS-Safari-no-decode fallback (addresses C1-A5).** The download-link paragraph **MUST** be emitted as a **sibling element** below the `<video>` block, NOT nested inside it. HTML5 `<video>` inner fallback content renders only when the browser doesn't support `<video>` at all (legacy IE); a browser that supports `<video>` but cannot decode any of the listed `<source>` elements (iOS Safari with no MP4 source available) shows a broken-video icon, NOT the inner `<p>`. Emitting a sibling download link guarantees the fallback is always visible. The inner `<p>` is kept as belt-and-suspenders for true legacy.
  - The generator **MUST** omit the MP4 `<source>` line entirely when `<slug>/walkthrough.mp4` is absent in the source tree. (WebM-only is valid; the always-visible sibling download link remains the iOS recovery path.)
  - The generator **MUST NOT** call `ffmpeg` automatically as part of the website build. The transcode is a SEPARATE local helper invoked on demand — `python website/scripts/build_guides.py --transcode`. The default invocation (no flag) does NOT touch source assets.
  - When invoked with `--transcode`, the generator **MUST** detect `ffmpeg` on PATH and, for each `ui/public/guides/<slug>/walkthrough.webm` whose paired `walkthrough.mp4` is missing OR older than the WebM (mtime compare), invoke this **exact argv** (no shell):
    ```
    ffmpeg -y -i <slug>/walkthrough.webm
      -c:v libx264 -profile:v baseline -level 3.1
      -pix_fmt yuv420p -movflags +faststart -an
      <slug>/walkthrough.mp4.tmp
    ```
    On success, the generator **MUST** atomic-rename `walkthrough.mp4.tmp` → `walkthrough.mp4` (`os.replace`). On non-zero ffmpeg exit, the `.tmp` file is removed and the existing MP4 (if any) is left untouched. If `ffmpeg` is absent on PATH, the generator **MUST** log a clear warning naming each affected deck and continue without failing.
- Notes: The flags address C1-A6 in detail:
  - `-y` — non-interactive overwrite (subprocess won't deadlock on a prompt)
  - `-pix_fmt yuv420p` — iOS Safari requires 4:2:0 chroma subsampling; libx264's default is whatever the source had, often 4:4:4 which iOS rejects
  - tmp+`os.replace` — interrupt-safe; partial files never replace good ones
  - `-an` strips audio (silent demos)
  - `-movflags +faststart` — moov-atom-first for HTTP-range streaming
  - `baseline` profile — iOS Safari maximum compat
  Verified locally — ffmpeg 8.1.1 at `/usr/local/bin/ffmpeg`.

### FR-4: Walkthroughs + In-depth index pages

- Requirement:
  - The generator **MUST** emit `website/docs/guides/walkthroughs/index.md` containing: an `<!-- GENERATED -->` header, an H1 (`# Walkthroughs`), a 1-paragraph blurb, and a 10-row card grid (one per deck) with: deck title (linked to `<slug>/`), `estimated_time`, the deck's first tag, the first screenshot as a thumbnail, and an explicit "Open walkthrough →" link at the bottom of the card.
  - The card grid **MUST** render acceptably on phone widths — MkDocs Material's CSS Grid utility classes (`<div class="grid cards" markdown>` + 10 child `- <content>`) are the canonical pattern and respond to viewport size automatically.
  - The generator **MUST** emit `website/docs/guides/in-depth/index.md` with the same structure: H1 + blurb + 4-row card grid pointing at the 4 long-form guides.
  - The card order on the Walkthroughs index **MUST** be the lexicographic order of the deck slug (matches the existing `metadata.json.order` field for the 10 current decks since they're `01_*` … `10_*`).
  - **glightbox skip-class on index thumbnails (addresses C1-B6 + C2-A1).** The generator **MUST** emit each index card thumbnail with the literal class attribute `glightbox-skip` on the `<img>` tag (e.g., `![…](…){.glightbox-skip}` using Material's `attr_list` syntax — already enabled in `mkdocs.yml:55`). mkdocs-glightbox's `auto_lightbox_image` behavior wraps every `<img>` it sees; the `glightbox-skip` class is the canonical opt-out per [mkdocs-glightbox docs](https://blueswen.github.io/mkdocs-glightbox/configuration/#disable-glightbox). **The matching plugin config (`skip_classes: ["glightbox-skip"]`) is a hand-edit to `mkdocs.yml`'s `plugins:` block done as part of Story 2.x (alongside adding `mkdocs-glightbox` to requirements.txt + registering the plugin) — the generator does NOT manage `plugins:`; only the `nav:` fragment is generator-managed per FR-5.** Without both the class marker AND the plugin config, clicking a card thumbnail opens a lightbox instead of navigating to the deck page — observable regression caught by AC-14.
- Notes: The Material `grid cards` pattern is supported without additional plugins. The "Open walkthrough →" link is the unambiguous primary action; the thumbnail acts as a navigational aid (Material renders thumbnails as part of the card link surface). Per-page screenshots INSIDE walkthrough pages keep glightbox behavior (clicking opens lightbox) since they have no link wrapper.

### FR-5: Managed nav fragment in `mkdocs.yml`

- Requirement:
  - The generator **MUST** maintain a managed YAML fragment in `website/mkdocs.yml` between literal sentinels `# >>> GENERATED Guides nav — DO NOT EDIT` and `# <<< END GENERATED Guides nav`. The fragment is the `Guides:` block (label values shown unquoted for readability; the emitter quotes them per the YAML safe-quoting rule below):
    ```yaml
      - Guides:
          - Walkthroughs:
              - Overview: guides/walkthroughs/index.md
              - Register your first cluster: guides/walkthroughs/01_register_first_cluster.md
              - … (8 more)
              - Chat with the agent: guides/walkthroughs/10_chat_with_agent.md
          - In-depth:
              - Overview: guides/in-depth/index.md
              - Tutorial — first study: guides/in-depth/tutorial-first-study.md
              - Quick tour: guides/in-depth/quick-tour.md
              - Workflows overview: guides/in-depth/workflows-overview.md
              - LLM endpoint setup: guides/in-depth/llm-endpoint-setup.md
    ```
  - **YAML safe-quoting (addresses C1-A7 + C3-A3).** Walkthrough nav labels are derived from `metadata.json.title` which is free text and may legally contain characters that break YAML when unquoted (`:`, `#`, `-` at start, `'`, `"`, `[`, `]`, `{`, `}`, `,`, `&`, `*`, `!`, `|`, `>`, `%`, `@`, `\``, leading whitespace, leading `?`). The generator **MUST emit every generated nav label as a single-quoted YAML scalar** using a STDLIB-only encoder — no PyYAML dependency (the generator's "pure stdlib" promise per D-8 is upheld). The encoder is the literal YAML 1.2 single-quoted-scalar rule: `f"'{label.replace(chr(39), chr(39)*2)}'"` — wrap in single quotes, escape internal `'` by doubling. Example: `It's "fun"` → `'It''s "fun"'`. The In-depth labels (`Tutorial — first study`, `Quick tour`, `Workflows overview`, `LLM endpoint setup`) are static + hard-coded in the generator (not data-driven from a free-text field), so quoting them is optional but the generator emits them with the same single-quote rule for uniformity. The `mkdocs build --strict` step (FR-9 + the new strict-build CI step in FR-6) is the regression signal if a label slips through unquoted.
  - The generator **MUST** insert the fragment between the existing `- Engines:` block (lines 138–142 of `mkdocs.yml` at spec time, ending at `Apache Solr: engines/solr.md`) and the `- API Reference:` line (`mkdocs.yml:143` at spec time) so it appears as a top-level nav tab between them.
  - **Anchor validation (addresses C1-A8).** Before editing, the generator **MUST** validate `mkdocs.yml`'s shape. Failure modes that exit 1 with a clear diagnostic:
    1. Zero or more-than-one occurrences of the literal anchor line `  - API Reference: api/index.md` → `ERROR: mkdocs.yml expected exactly one '- API Reference: api/index.md' anchor, found <N>`.
    2. Partial markers: only `# >>> GENERATED Guides nav` present (or only `# <<< END`) → `ERROR: mkdocs.yml has a partial GENERATED Guides nav marker — restore both or remove both`.
    3. Marker pair found outside the top-level `nav:` block → `ERROR: mkdocs.yml GENERATED Guides nav markers are not inside the nav: block`.
  - The generator **MUST** preserve every other line of `mkdocs.yml` byte-for-byte (single-direction-mirror discipline). It rewrites ONLY between the BEGIN/END markers + ONE-time inserts those markers on first run.
  - On first run (no markers present, exactly one anchor line found), the generator inserts both markers + the fragment at the anchor position and writes the file. Subsequent runs are pure-rewrite of the existing fragment.
- Notes: Hand-written nav is a hard constraint from the idea (D-1: "no nav plugin"). The managed-fragment approach lets the generator stay in sync without rewriting nav entries the maintainer cares about manually. Walkthrough titles are pulled from `metadata.json.title` and emitted safely-quoted.

### FR-6: CI freshness gate (own workflow file)

- Requirement:
  - A new workflow at `.github/workflows/build-guides-freshness.yml` **MUST** run on every PR to main (with NO `paths-ignore` filter) and on every push to main. The workflow uses `pull_request` (not `pull_request_target`) so it never sees write-scope secrets on fork PRs.
  - The workflow **MUST** install Python deps via `pip install -r website/requirements.txt`, run `python website/scripts/build_guides.py` (default invocation, no `--transcode`), and fail if `git status --porcelain` over the gate scope is non-empty.
  - **Gate scope with explicit MP4 exclude (addresses C1-B1).** The exact pathspec form **MUST** be:
    ```
    git status --porcelain -- \
      website/docs/guides/ \
      website/docs/assets/guides/ \
      ':!website/docs/assets/guides/**/*.mp4' \
      website/mkdocs.yml
    ```
    The `:!…/*.mp4` exclude pathspec keeps MP4 drift outside the gate's view per D-2 ("MP4 best-effort, deploy CI is Python-only"). PNG, WebM, generated `.md`, and the managed nav fragment ARE gated. Local pre-commit can add a softer MP4↔WebM drift warning as a separate follow-up.
  - **Strict-build gate on PR (addresses C1-B2).** After the freshness check passes, the workflow **MUST** run a second step `(cd website && mkdocs build --strict)` and fail if exit is non-zero. This catches broken nav, broken in-site links, or `--strict`-rejected output BEFORE merge — without this, a website-only PR (skipped by `pr.yml`'s `paths-ignore`) can land a broken site that only fails on the post-merge `deploy-docs.yml` run. The strict-build step uses the same checked-out tree as the freshness check; cost is ~10 seconds.
  - **Unit-test step (addresses C3-B1).** Because `pr.yml`'s `paths-ignore: ['website/**']` skips the standard backend Python test suite on website-only PRs, the freshness workflow **MUST** run `uv run pytest backend/tests/unit/scripts/test_build_guides.py -q` as a step BEFORE the main gate. This brings the generator's unit tests AND the AC-14 markup / plugin-config assertions into the website-only-PR signal path — without this, AC-14's unit-testable half silently skips on website-only PRs. The step uses the same `uv sync --frozen` pattern as `generated-artifacts-fresh` in `pr.yml`.
  - The workflow **MUST** include a self-test step that runs `bash scripts/ci/test_verify_build_guides_fresh.sh` BEFORE the main gate (mirrors `copy-docs-freshness.yml` → `test_verify_copy_docs_fresh.sh` precedent). The self-test exercises four sub-cases:
    1. **Clean fixture** → guard exit 0.
    2. **Source-drift** (edit a source PNG/metadata.json/long-form guide) → guard exit 1, `M`/`??` in diagnostic.
    3. **Untracked `git rm --cached`** (existing copy, removed from index, still on disk) → guard exit 1.
    4. **Genuinely-new dest file (addresses C1-B3 + C2-B2)** — add a NEW source asset to the fixture that the fixture's HEAD never tracked (e.g., a new `ui/public/guides/99_test_new_deck/` dir with `metadata.json` + one PNG + a WebM stub), then re-run the gate. The gate's regen emits new dest files under `website/docs/guides/walkthroughs/99_test_new_deck.md` and `website/docs/assets/guides/99_test_new_deck/*` that the fixture's HEAD never tracked. Those appear as `??` lines in `git status --porcelain`. Guard exit 1. This sub-case is OBSERVABLY DISTINCT from sub-case 3 — sub-case 3 puts an EXISTING tracked file's working-tree copy out of sync with the index (the file was tracked, `git rm --cached` removed it); sub-case 4 produces a path that was NEVER tracked. A flawed guard that special-cases the "previously tracked" path could pass sub-case 3 while missing sub-case 4.
  - The workflow **MUST** print the canonical fix command on failure: `bash scripts/regen-generated-artifacts.sh` (the chained fix) followed by the standalone form: `python website/scripts/build_guides.py && git add website/docs/guides website/docs/assets/guides website/mkdocs.yml`.
- Notes: The MP4 exclusion via `:!` pathspec is the explicit C1-B1 fix. The strict-build PR step (C1-B2) is the only way to PR-gate `mkdocs build --strict` without modifying `pr.yml` (which skips `website/**`). Operational reality (addresses C1-B4): RelyLoop currently has NO branch protection (the ruleset was removed 2026-05-31 per `state.md`), so the gate is **informational** until protection is re-enabled at GA hardening — when that happens, add `build-guides-freshness / build-guides-freshness` to the required-checks list. Fork PRs from first-time contributors require maintainer "Approve and run workflow" before any check runs (GitHub default); the spec assumes this baseline.

### FR-7: De-duplicate existing outbound GitHub-blob links

- Requirement:
  - The implementation **MUST** rewrite `website/docs/getting-started/quickstart.md:66` from `[…](https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md)` to `[…](../guides/in-depth/tutorial-first-study.md)`.
  - The implementation **MUST** rewrite `website/docs/getting-started/install.md:85` from `[…](https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/llm-endpoint-setup.md)` to `[…](../guides/in-depth/llm-endpoint-setup.md)`.
  - Both rewrites are one-time edits to hand-written files (NOT generator output); the generator does NOT manage `quickstart.md` or `install.md`.
- Notes: These two links are the entire current public-site outbound surface for `docs/08_guides/`. Verified at preflight via `grep -RnE 'docs/08_guides' website/docs/`. No other refs exist.

### FR-8: Chained regen script update

- Requirement:
  - `scripts/regen-generated-artifacts.sh` **MUST** be extended to include a fourth step that runs the generator (`python website/scripts/build_guides.py`) after the existing three.
  - The script **MUST** continue to honor `REGEN_NO_STAGE=1` (the existing CI determinism-check flag).
  - The script **MUST** continue to `git add` the regenerated artifacts only when `REGEN_NO_STAGE` is unset; the new step adds `website/docs/guides website/docs/assets/guides website/mkdocs.yml` to the stage list.
- Notes: The script today is the "one-paste fix" referenced by every freshness-gate failure message. Keeping it the single canonical entry point means a maintainer never needs to remember which gate flagged drift.

### FR-9: `mkdocs build --strict` continues to pass

- Requirement:
  - After the generator runs, `mkdocs build --strict` (executed from `website/`) **MUST** succeed.
  - No generated page may be orphaned (every generated `.md` is referenced in the nav fragment); `--strict` errors on orphans.
  - No generated link may be broken; the link rewriter's output is round-tripped through MkDocs's link resolver.
  - No glightbox-related warning may surface (the plugin is mature; this is a regression signal if it does).
- Notes (addresses C2-B1): Verified at two places: (1) PR-time inside `build-guides-freshness.yml` as a second step after the freshness check (added per FR-6 + C1-B2), so a website-only PR's broken nav/link is caught BEFORE merge; (2) post-merge inside `deploy-docs.yml`'s existing `mkdocs build --strict` step, so the deploy pipeline can't drift. Both run from `website/` against the post-generator working tree.

---

## 8) API and data contract baseline

N/A — no API surface. This feature touches only static-site generation, source assets, and CI.

### 7.4 Enumerated value contracts

N/A — no filter, sort, status, or dropdown surface.

### 7.5 Error code catalog

N/A — no API surface. Generator error messages are operator-facing CLI output, not user-facing API codes.

---

## 9) Data model and state transitions

N/A — no DB tables touched. No migration. Alembic head stays `0022_solr_engine_auth_check`.

### Required invariants

- **The following three destination directories are fully generator-owned (addresses C1-A9).** Any file present in them that the generator did not emit on the most recent run is pruned silently. Maintainers MUST NOT place hand-maintained assets there:
  - `website/docs/guides/walkthroughs/`
  - `website/docs/guides/in-depth/`
  - `website/docs/assets/guides/`
  Hand-maintained images, illustrations, or attachments that should ship with the website live under `website/docs/assets/images/` (existing dir) or a new sibling dir like `website/docs/assets/diagrams/` — outside the prune scope. The `<!-- GENERATED -->` header at the top of each emitted `.md` is the deterrent for hand-edits.
- The set of generated `.md` files under `website/docs/guides/walkthroughs/` equals `{index.md} ∪ {<slug>.md for slug in metadata-json-decks}`. A removed deck → pruned page.
- The set of generated `.md` files under `website/docs/guides/in-depth/` equals `{index.md} ∪ {<basename> for basename in LONG_FORM_GUIDES}` (currently 5 files: index + 4 guides).
- The set of files under `website/docs/assets/guides/<slug>/` equals exactly the union of PNGs declared in `metadata.json.screenshots`, the source `walkthrough.webm` (when declared and the source file exists), plus the source `walkthrough.mp4` **when present locally — best-effort, not CI-enforced (addresses C2-B3)**. PNGs and WebMs are CI-enforced by the freshness gate; MP4s are **explicitly excluded from the gate's pathspec** per D-18 (the deploy CI is Python-only and cannot transcode). Drift between source `walkthrough.webm` and dest `walkthrough.mp4` is tolerated — a maintainer who regenerates the WebM but forgets to retranscode ships a deck whose iOS-Safari users fall back to the always-visible sibling download link. A local pre-commit warning that compares WebM↔MP4 mtimes in `ui/public/guides/` could close this gap as a follow-up; not in scope here. All files OUTSIDE this set (PNG/WebM/MP4) are pruned by the generator on the next run.
- The managed nav fragment in `mkdocs.yml` lists every generated page and no others — a generated page outside the fragment fails `mkdocs build --strict` (orphan), a fragment entry pointing at a non-existent page fails `--strict` (broken link).

### Idempotency/replay behavior

- The generator is idempotent on a clean tree: a second run produces no changes.
- The generator is hermetic: no network, no DB, no clock-sensitive output. (No `Date.now()` in output; the source-comment header is static.)
- **The CI gate's self-test step (mirror of `test_verify_copy_docs_fresh.sh`) exercises FOUR cases (addresses C3-B2)** against a tmp-dir fixture: (1) clean tree → exit 0, (2) edit a source guide → drift detected → exit 1, (3) `git rm --cached` a generated copy (untracked-but-previously-tracked case) → drift detected → exit 1, (4) add a brand-new source asset never tracked by fixture HEAD → regen emits a never-tracked dest path that appears as `??` → drift detected → exit 1. See AC-10 for the full sub-case rubric.

---

## 10) Security, privacy, and compliance

- **Threats:**
  1. A malicious source-asset PR (e.g. `metadata.json` with a path-traversal value) tricks the generator into writing outside `website/docs/`.
  2. A long-form guide link rewriter mis-classifies a URL and emits an open-redirect-style anchor.
  3. The `<video>` block embeds untrusted attributes through `metadata.json.video`.
  4. The CI freshness gate executes attacker-controlled Python.
  5. The MP4 transcode subprocess shells out unsafely.
- **Controls:**
  1. Generator MUST validate `slug` against `^[a-zA-Z0-9_-]+$` before joining paths. Reject metadata files whose paths escape the source dir (`..`, leading `/`).
  2. Link rewriter accepts ONLY the rule set in FR-2; unmapped patterns fail loudly. Generated URLs are either absolute GitHub blob URLs, in-site relative siblings, or in-page anchors — no `javascript:`, no `data:`.
  3. `metadata.json.video` is consumed as a basename only (`os.path.basename`), not as a URL component. The `<video src>` is computed from `<slug>` + the literal filename, not from user-supplied JSON.
  4. The freshness-gate workflow runs `python website/scripts/build_guides.py` with no untrusted-input args. `pull_request_target` is NOT used (the workflow uses `pull_request`); secrets are not exposed.
  5. The ffmpeg subprocess is invoked with `subprocess.run([…], shell=False)` and a fully-controlled argv list (no string interpolation from `metadata.json`). MP4 transcode runs only locally with `--transcode` flag; not in CI.
- **Secrets/key handling:** N/A — public docs site, no secrets.
- **Auditability:** N/A — no actor/reason/target/timestamp surface. Site is read-only public.
- **Data retention/deletion/export impact:** N/A — public docs site.

---

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** New top-level nav tab labeled **Guides**, inserted between **Engines** and **API Reference**. Two subsections: **Walkthroughs** (10 numbered decks) and **In-depth** (4 long-form guides). Material `navigation.tabs + navigation.sections + navigation.expand` features are already on (per `mkdocs.yml:50-53`).
- **Labeling taxonomy:**
  - Nav tab label: `Guides`
  - Subsection labels: `Walkthroughs`, `In-depth`
  - Walkthrough page titles: derived from `metadata.json.title` (existing copy, e.g. "Register your first cluster", "Review a proposal", …)
  - Long-form titles: derived from each guide's `# H1` (existing copy)
  - "Back to walkthroughs" / "Back to in-depth guides" — placed at the bottom of every leaf page, links to the matching section index
- **Content hierarchy:** Each walkthrough page's primary content (top-to-bottom): H1 → estimated-time/tags admonition → video block (when present) → numbered screenshot rows (Step 1 → Step N) → "Back" link. Each long-form page is the existing markdown unchanged structurally, with rewritten links.
- **Progressive disclosure:** Material's default sidebar TOC + per-page heading-anchor navigation already covers progressive disclosure within long pages. The walkthrough card grid acts as the discoverable landing.
- **Relationship to existing pages:** The two new outbound links from `getting-started/install.md` and `getting-started/quickstart.md` now point at the new in-site `Guides → In-depth` pages instead of off-site GitHub blob URLs. No other existing page is structurally affected.

### Tooltips and contextual help

N/A — this is a public docs site with no settings, status indicators, or actions with consequences. Standard MkDocs Material UI controls (nav, search, palette toggle) keep their built-in tooltips. The site's existing `abbr` (auto-appended `includes/abbreviations.md`) continues to provide term-level hover tooltips.

### Primary flows

1. **Cold visitor lands on Guides → Walkthroughs index → opens a deck.** Sees the H1 title, the estimated time admonition, the video (autoplay-free, control-bar visible), and the screenshot sequence. Clicks a screenshot → lightbox opens, pinch-zooms on phone. Reads → returns via "← Back to walkthroughs".
2. **Search-engine visitor lands directly on a deck page.** Same content; the Material sidebar TOC scopes navigation within the deck.
3. **Cold visitor lands on Guides → In-depth → opens tutorial-first-study.** Sees the 30-min E2E tutorial with code blocks (Material's existing `content.code.copy` + `pymdownx.highlight` apply). Internal sibling link to `quick-tour.md` works (rewriter rule 1). Outbound link to `https://github.com/SoundMindsAI/relyloop/blob/main/backend/tests/smoke/test_tutorial_path.py` works (rewriter rule 2).
4. **Maintainer regenerates screenshots for deck 06.** Runs `guide-gen`, which updates `ui/public/guides/06_create_and_monitor_study/*.png`. Then runs `bash scripts/regen-generated-artifacts.sh` (the canonical chained fix). Sees the new copies in `website/docs/assets/guides/06_*`. Commits, pushes; the freshness gate confirms green; merging triggers deploy.
5. **iOS Safari visitor on Guides → Walkthroughs → deck 01.** Video element loads; the `<source type="video/mp4">` is picked (the iOS Safari WebM gap), playback starts inline (the `playsinline` attribute), `controls` shows the standard player. If MP4 absent → download-link fallback paragraph renders.

### Edge/error flows

- **Source asset missing.** A `metadata.json.screenshots[].file` references a PNG that doesn't exist on disk → generator logs `WARN: deck=<slug> missing screenshot=<file>` and skips the row. The page still renders. The freshness gate catches this as drift (the generated `.md` content doesn't match the committed copy).
- **Unmapped link in long-form guide.** A new long-form-guide edit introduces a `../06_runbooks/something.md` path that doesn't match FR-2's rule table → generator exits non-zero with `ERROR: <file>:<line> unmapped link rewrite for "../06_runbooks/something.md"`. Maintainer either extends the rewriter (update rule table) or fixes the source link.
- **ffmpeg absent locally during `--transcode`.** Generator emits `WARN: ffmpeg not on PATH; skipping MP4 transcode for <N> decks (iOS Safari users will see the download-link fallback)`. Exits 0 anyway. The CI gate doesn't care (MP4 is out-of-scope).
- **First-run insertion of nav-fragment markers in `mkdocs.yml`.** Generator detects no markers, locates the position just before `- API Reference:`, inserts both markers + the fragment, writes the file. Second run finds the markers and rewrites between them only.
- **`mkdocs build --strict` fails on a generated link.** Generator's link rewriter has a bug → strict-mode build fails with the offending source location. The freshness gate catches this at PR time via its `mkdocs build --strict` second step (per FR-6 + C1-B2); the deploy workflow re-runs strict on push to main as belt-and-suspenders.
- **Hand-edit to a generated `.md` file.** Maintainer's edit is silently overwritten on the next generator run. The `<!-- GENERATED -->` header is the deterrent. If they commit the hand-edit, the freshness gate catches the drift on PR.

---

## 12) Given/When/Then acceptance criteria

### AC-1: Walkthrough deck pages render with all screenshots in capture order

- Given the 10 decks present in `ui/public/guides/`, each with a `metadata.json` + numbered PNGs + WebM,
- When `python website/scripts/build_guides.py` is run on a clean repo,
- Then `website/docs/guides/walkthroughs/<slug>.md` exists for each of the 10 decks, contains an H1 = `metadata.json.title`, an `!!! info` admonition with `estimated_time` + tags, an H2 + image per screenshot in numeric order (01_, 02_, …), and the assets are copied into `website/docs/assets/guides/<slug>/`.
- Example: `website/docs/guides/walkthroughs/01_register_first_cluster.md` first H1 line = `# Register your first cluster`, then admonition listing `3 minutes`, then 5 `## Step N — ...` H2s in order, with each `![…](../../assets/guides/01_register_first_cluster/0[1-5]-*.png)`.

### AC-2: Long-form guides are ported with ALL repo-relative links rewritten + directory-vs-file URL discipline

- Given `docs/08_guides/{tutorial-first-study,quick-tour,workflows-overview,llm-endpoint-setup}.md` are present,
- When the generator runs,
- Then `website/docs/guides/in-depth/<basename>` exists for each AND every inline-Markdown `[…](url)` link whose URL matched FR-2 rule 4 (off-site repo-relative) resolves to a `https://github.com/SoundMindsAI/relyloop/{blob|tree}/main/<rest>` URL — `/blob/main/…` for resolved file paths, `/tree/main/…` for resolved directory paths — AND every inline-Markdown link whose URL matched FR-2 rule 3 (intra-list) resolves to a relative sibling stripped of the `./` prefix.
- Example values (verified by a directed test):
  - `tutorial-first-study.md:12` `[smoke test](../../backend/tests/smoke/test_tutorial_path.py)` → `[smoke test](https://github.com/SoundMindsAI/relyloop/blob/main/backend/tests/smoke/test_tutorial_path.py)` (file → `/blob/`).
  - `quick-tour.md:382` `[`docs/01_architecture/`](../01_architecture/)` → `[`docs/01_architecture/`](https://github.com/SoundMindsAI/relyloop/tree/main/docs/01_architecture/)` (directory → `/tree/`).
  - `quick-tour.md` reference to `[`tutorial-first-study.md`](tutorial-first-study.md)` is unchanged in the generated output (intra-list rule 3, no rewrite).
  - All occurrences are rewritten — count is not pinned in the assertion (it's whatever the current sources contain), but a CI-aware scan asserts ZERO remaining inline `[…](../…)` patterns in the four generated in-depth files.

### AC-3: Unmapped or non-existent path causes generator exit 1 with file:line

- Given a source guide containing `[broken](../99_unknown/path.md)` (resolved repo path `docs/99_unknown/path.md` does NOT exist in the working tree),
- When the generator runs,
- Then the generator prints `ERROR: docs/08_guides/<file>:<line> unresolved repo link "../99_unknown/path.md" (resolved to "docs/99_unknown/path.md", not found in tree)` to stderr and exits 1.
- Also covered: a tutorial-style `[link][ref]` reference-style syntax pointing at a relative repo path triggers a separate `unsupported link syntax` error per FR-2 (the rewriter applies only to inline `[…](…)` links). And a relative path that resolves to a file outside the repo root (e.g., `../../../../etc/passwd`) is rejected by the path-normalization step before the existence check.
- Example: a test fixture (`backend/tests/unit/scripts/test_build_guides.py::test_unresolved_link_fails_loudly`) writes a tiny long-form guide containing one off-spec link, runs the generator's link-rewrite function via a public entry point, and asserts the exception/exit message.

### AC-4: Video block uses MP4-first source order with playsinline + always-visible sibling download link

- Given a deck whose `metadata.json.video == "walkthrough.webm"` (locked per FR-3) and whose `walkthrough.mp4` exists locally,
- When the generator runs,
- Then the page's `<video>` block contains, in order, `<source src="…walkthrough.mp4" type="video/mp4">` THEN `<source src="…walkthrough.webm" type="video/webm">`, AND the `<video>` element carries `controls playsinline preload="metadata"` attributes, AND a sibling `<p class="walkthrough-video-download">` element appears IMMEDIATELY BELOW the `<video>` (not nested inside) containing an `<a href="…webm">` download link.
- When the MP4 is absent, the `<source type="video/mp4">` element is omitted; the WebM `<source>` is present; the sibling download `<p>` is still present (always visible; no nesting).
- When `metadata.json.video` is set to anything other than the literal `"walkthrough.webm"`, the generator exits 1 with `ERROR: deck=<slug> metadata.json.video must be "walkthrough.webm", got "<value>"`.

### AC-5: MP4 transcode opt-in does not run on CI

- Given a default invocation `python website/scripts/build_guides.py` (no `--transcode`),
- When the generator runs,
- Then no `subprocess.run(["ffmpeg", ...])` call is made, AND the working tree's `ui/public/guides/<slug>/walkthrough.mp4` files are not touched (mtime unchanged).
- Verified by a unit test that monkeypatches `subprocess.run` to record calls and asserts none target `ffmpeg`.

### AC-6: Idempotent re-run produces no working-tree changes

- Given a clean working tree where the generator was last run,
- When the generator runs a second time with no source changes,
- Then `git status --porcelain` is empty across `website/docs/guides/`, `website/docs/assets/guides/`, and `website/mkdocs.yml`.

### AC-7: Removed deck → pruned generated page + assets

- Given the 10 decks present and previously generated,
- When `ui/public/guides/10_chat_with_agent/` is deleted and the generator re-runs,
- Then `website/docs/guides/walkthroughs/10_chat_with_agent.md`, `website/docs/assets/guides/10_chat_with_agent/`, and the deck's entry in the managed nav fragment are all removed.

### AC-8: Freshness gate fails on stale source

- Given a PR that edits `ui/public/guides/01_register_first_cluster/metadata.json` (e.g., changes a caption) WITHOUT re-running the generator,
- When the `build-guides-freshness` workflow runs,
- Then the workflow exits non-zero, the failure log identifies the stale generated file, and prints the canonical fix command `bash scripts/regen-generated-artifacts.sh`.

### AC-9: Untracked drift case (AC-9 of prior gates) is caught

- Given a developer who renames a screenshot file in `ui/public/guides/`, runs the generator, but forgets to `git add` the new copy in `website/docs/assets/guides/`,
- When the freshness gate runs against the PR head,
- Then `git status --porcelain` reports the untracked file (`??` marker), the gate exits 1, and the fix command is printed.

### AC-10: Self-test harness for the freshness gate passes all FOUR sub-cases

- Given the new self-test at `scripts/ci/test_verify_build_guides_fresh.sh`,
- When the self-test runs (either locally or as the workflow's first step),
- Then four sub-cases all pass:
  - (a) clean fixture → guard exit 0
  - (b) source-drift fixture (edit a source PNG/metadata.json/long-form guide) → guard exit 1
  - (c) `git rm --cached` of an existing generated dest file → guard exit 1 (the file was tracked in fixture HEAD; cache removal leaves a `??` in the working tree)
  - (d) **add a brand-new source asset absent from fixture HEAD** (addresses C2-B2) — e.g., introduce a `ui/public/guides/99_test_new_deck/` deck whose `metadata.json` + PNG + WebM the fixture's HEAD never tracked, then run the guard. The regen emits new dest paths under `website/docs/guides/walkthroughs/99_test_new_deck.md` + `website/docs/assets/guides/99_test_new_deck/*` that are pure `??` lines (no index history for those paths) → guard exit 1. Sub-case (d) is observably distinct from sub-case (c) because (c)'s `??` belongs to a previously-tracked path while (d)'s `??` belongs to a never-tracked path; a guard that special-cases the previously-tracked path would pass (c) but fail (d).

### AC-11: Existing outbound links de-duplicated

- Given the post-merge `main` branch,
- When `grep -RnE 'docs/08_guides' website/docs/` runs,
- Then zero matches are returned (the two pre-existing GitHub-blob refs at `quickstart.md:66` + `install.md:85` are rewritten to in-site refs).

### AC-12: `mkdocs build --strict` is PR-gated by the freshness workflow + post-merge deploy

- Given a clean post-generator working tree,
- When `(cd website && mkdocs build --strict)` runs as the second step of `build-guides-freshness.yml` (after the freshness check itself),
- Then exit code is 0, no `WARNING` or `ERROR` lines appear in stdout/stderr referencing missing pages, broken links, or orphans.
- The same step also runs in `deploy-docs.yml` on push to main (existing, unchanged) as the deploy gate; the freshness workflow's added PR-time strict-build step ensures the failure surfaces BEFORE merge (addresses C1-B2 — without it, `pr.yml`'s `paths-ignore: ['website/**']` lets website-only PRs land broken pages that fail only on the post-merge deploy run).

### AC-13: Nav fragment is byte-stable across regenerations AND YAML-safe under exotic titles

- Given the generator has produced the managed nav fragment once,
- When the generator runs again with no source changes,
- Then the BEGIN/END markers and every intervening line are unchanged (no whitespace drift, no key reordering).
- Verified by a unit test that loads the file pre + post and asserts byte equality on the fragment slice.
- Additionally (addresses C1-A7): a fixture deck whose `metadata.json.title` is set to `Search: it's "fun" — guide #1` produces a nav-fragment line that loads cleanly under PyYAML's `safe_load` (label value is properly single-quoted with internal `'` doubled).

### AC-14: glightbox skip-class on index thumbnails (unit-testable markup + manual click verification)

**Unit-testable (in CI):**
- Given the generator runs against the fixture,
- When the generated `website/docs/guides/walkthroughs/index.md` and `in-depth/index.md` are inspected,
- Then EVERY card thumbnail `<img>` (or Markdown image syntax that compiles to `<img>`) carries the literal `{.glightbox-skip}` attribute-list marker.
- And the committed `website/mkdocs.yml` `plugins:` block contains `skip_classes: ["glightbox-skip"]` under the `glightbox:` entry (a static-file assertion, since the plugin config is hand-edited, not generator-managed per C2-A1).

**Manual verification (post-merge per §16):**
- Given the deployed `relyloop.com/guides/walkthroughs/` page,
- When a maintainer clicks an index card's thumbnail,
- Then the browser navigates to the deck page (the `<a>` wrapper wins, NOT a glightbox overlay).
- Conversely, when a maintainer clicks a screenshot INSIDE a walkthrough deck page (where the image is NOT inside an `<a>` wrapper), the glightbox overlay opens as intended.

The unit-testable parts run on every PR via `backend/tests/unit/scripts/test_build_guides.py`; the browser-click parts live in the §16 post-merge verification checklist because the spec deliberately keeps E2E coverage off the website (no Playwright runner targets relyloop.com — see §14 "E2E tests: N/A").

---

## 13) Non-functional requirements

- **Performance:** Generator runs in under 3 seconds locally on the existing 10-deck + 4-guide set (no network, no ffmpeg in the default invocation). The MP4 transcode (`--transcode`) takes ~5–10 seconds per deck on a modern laptop (~1 minute for the full set). MkDocs `--strict` build adds ~10 seconds to the deploy pipeline on top of the existing ~15-second baseline.
- **Reliability:** Generator is hermetic + deterministic — no clock, no network, no random. Idempotent re-runs produce byte-identical output. Failures during link rewriting surface with `file:line` for fast triage.
- **Operability:** All operator commands are documented in `CLAUDE.md`'s "Build, Test, and Lint Commands" section. Freshness-gate failures point at `bash scripts/regen-generated-artifacts.sh` (the canonical fix). The generator's stdout/stderr are short and direct — no log spam.
- **Accessibility/usability:**
  - Every screenshot's `<img alt="...">` uses the caption (from `metadata.json.screenshots[].caption`) — already meaningful, descriptive sentences. Existing.
  - `<video controls>` exposes the browser's accessible player UI.
  - The download-link fallback inside the `<video>` element doubles as the legacy/screen-reader path.
  - Walkthrough page H2s (`## Step N — <first words>`) are short, scannable, and match the screenshot order — so a screen-reader user navigates via headings rather than via images.
  - Material's existing `navigation.top`, `toc.follow`, `content.tooltips`, `search.suggest` features remain on.

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/scripts/test_build_guides.py`):**
  - Link rewriter happy paths for each FR-2 rule (intra-list, off-site, absolute, in-page anchor, source-relative)
  - Link rewriter failure path: unmapped pattern exits with the expected message + non-zero
  - Pruning behavior: a tmp fixture pre-seeded with stale `walkthroughs/99_dead.md` + stale assets dir, generator runs, stale files removed
  - Nav-fragment idempotence: two consecutive generator runs produce byte-identical `mkdocs.yml`
  - Nav-fragment first-run insertion: a tmp fixture with `mkdocs.yml` lacking the markers, generator runs, markers + fragment inserted at the documented position, every other line unchanged
  - Video block shape: MP4-present → MP4 source line first + WebM second; MP4-absent → only WebM + download fallback
  - Slug validation: a malicious `slug = "../etc"` is rejected with a clear error (no path traversal)
  - `metadata.json` missing required keys → clear error, no traceback
  - The generator does NOT invoke `subprocess.run(["ffmpeg", ...])` on the default code path (monkeypatched `subprocess.run` records calls)
- **Integration tests (`backend/tests/unit/scripts/` or a new home — discussed in implementation plan):**
  - End-to-end fixture run: the generator processes a 2-deck + 2-guide fixture and the result passes `mkdocs build --strict` against a tmp mkdocs.yml. (Optional — could be deferred if `mkdocs` install in test env is heavyweight.)
- **Contract tests:** N/A (no API surface).
- **E2E tests (`ui/tests/e2e/`):** N/A — no in-app change. (The website itself is not in the Playwright scope; an HTTP smoke check could be added later if needed.)
- **Freshness-gate self-test (`scripts/ci/test_verify_build_guides_fresh.sh`):** mirrors `test_verify_copy_docs_fresh.sh` — **four sub-cases (addresses C3-B2):** clean fixture, source-drift fixture, `git rm --cached`-of-tracked fixture, and brand-new-source-asset fixture (see AC-10 for the full rubric). Bash + git init in tmp dir.
- **Local smoke:** running `mkdocs serve` from `website/` after the generator produces a navigable site with the Guides tab visible, deck pages clickable, lightbox image-zoom working, video controls visible. Documented in `docs/03_runbooks/website-guides-regen.md` (new).

## 15) Documentation update requirements

- `docs/01_architecture/` — N/A (no architectural surface added)
- `docs/02_product/` — N/A (no in-app product surface added)
- `docs/03_runbooks/` — ADD `docs/03_runbooks/website-guides-regen.md` covering: (a) how to regenerate (`bash scripts/regen-generated-artifacts.sh` is the canonical fix; `python website/scripts/build_guides.py [--transcode]` is the standalone form), (b) how the freshness gate identifies stale source, (c) how to add a new long-form guide (extend `LONG_FORM_GUIDES` list + run generator), (d) how to add a new walkthrough deck (run `guide-gen`, regenerate, commit), (e) **MP4/iOS operational details (addresses C1-B8):** installing ffmpeg on macOS/Linux for the `--transcode` step, the exact transcode command (matches FR-3 — `-y -pix_fmt yuv420p -movflags +faststart` + temp+rename), how to verify a produced MP4 carries `yuv420p` (`ffprobe -show_streams walkthrough.mp4 | grep pix_fmt`) and `+faststart` (`mediainfo walkthrough.mp4 | grep -i "muxing time"` or equivalent), how to test iOS Safari playback (real device or BrowserStack — opens the live URL `relyloop.com/guides/walkthroughs/<slug>/`).
- `docs/04_security/` — N/A
- `docs/05_quality/` — UPDATE `docs/05_quality/testing.md` §"Generated-artifact freshness gates" to list the new `build-guides-freshness` gate alongside `generated-artifacts-fresh` and `copy-docs-freshness`.
- `CLAUDE.md` — UPDATE "Generated artifacts" section to list `website/docs/guides/` + `website/docs/assets/guides/` + `mkdocs.yml` managed nav fragment as CI-freshness-gated, and add the new gate name to the canonical fix-command callout.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The website republishes on every push to main; the new Guides tab is visible immediately on merge.
- **Migration/backfill expectations:** None — no DB.
- **Operational readiness gates:** None unique to this feature. The deploy workflow (`deploy-docs.yml`) already gates on `mkdocs build --strict`; the freshness gate runs on every PR with an added PR-time strict-build step (FR-6 + AC-12).
- **Release gate:** Merge gates: (a) `build-guides-freshness` green (informational only — see below), (b) `generated-artifacts-fresh` green (unaffected, but still gating), (c) `copy-docs-freshness` green (unaffected), (d) `pr.yml` paths-not-ignore checks green (won't run on a website-only PR since `website/**` is in paths-ignore), (e) the cross-model review pass per `/impl-execute` ceremony.
- **Branch-protection status (addresses C1-B4):** RelyLoop currently has **NO branch protection on `main`** — the operator removed the `required_status_checks` rule from ruleset `protect-main-require-pr-ci` (id 16179144) on 2026-05-31, and no classic branch protection exists. The new `build-guides-freshness` workflow's failures are therefore **informational, not merge-blocking** at the platform level — a maintainer can technically merge a red PR. When branch protection is re-enabled at GA hardening (post-public-launch), the operator MUST add `build-guides-freshness / build-guides-freshness` to the required-checks list to make this gate enforcing. The spec calls this out so a future GA-hardening checklist captures the dependency.
- **Fork-PR caveat:** A first-time external contributor's PR requires a maintainer to click "Approve and run workflow" before any workflow (including `build-guides-freshness`) runs. This is GitHub's default fork-PR protection; the spec does not change this behavior. Maintainers should verify the workflow ran (not just that the PR has green checks) before merging fork contributions touching the guides.
- **Post-merge verification:** Open `https://relyloop.com/guides/walkthroughs/` after deploy succeeds (typically <5 minutes from merge). Confirm: nav tab visible, index card grid renders, clicking a card's thumbnail NAVIGATES to the deck (not lightbox — verifies AC-14 glightbox skip-class), opening the deck plays the video (try one on iOS Safari — verifies the MP4-first source order from AC-4), and clicking a screenshot inside the deck DOES open a glightbox overlay.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (deck pages) | AC-1, AC-6, AC-7, AC-13 | Story 1.1 (generator scaffold + deck page emit), Story 1.4 (prune) | `backend/tests/unit/scripts/test_build_guides.py` | `docs/03_runbooks/website-guides-regen.md` |
| FR-2 (link rewriting + path-existence + tree-vs-blob) | AC-2, AC-3 | Story 1.2 (link rewriter + tests) | `backend/tests/unit/scripts/test_build_guides.py` (intra-list + tree-vs-blob + unresolved + unsupported-syntax) | `docs/03_runbooks/website-guides-regen.md` |
| FR-3 (video block + locked filename + sibling download + transcode) | AC-4, AC-5 | Story 1.3 (video block + `--transcode` flag + atomic-rename + pix_fmt) | `backend/tests/unit/scripts/test_build_guides.py` | `docs/03_runbooks/website-guides-regen.md` |
| FR-4 (index pages + glightbox-skip on thumbnails) | AC-1, AC-12, AC-14 | Story 1.1 (alongside deck page emit) | `backend/tests/unit/scripts/test_build_guides.py` (smoke on index emit + skip-class assertion) | `docs/03_runbooks/website-guides-regen.md` |
| FR-5 (nav fragment + YAML safe-quoting + anchor validation) | AC-6, AC-12, AC-13 | Story 1.5 (managed nav fragment) | `backend/tests/unit/scripts/test_build_guides.py` (idempotence + first-run insertion + exotic-title quoting + missing/duplicated anchor) | `CLAUDE.md`, `docs/05_quality/testing.md` |
| FR-6 (CI freshness gate + MP4 pathspec exclude + PR-time strict-build) | AC-8, AC-9, AC-10, AC-12 | Story 2.1 (workflow + self-test) | `scripts/ci/test_verify_build_guides_fresh.sh` (four sub-cases) | `docs/05_quality/testing.md`, `CLAUDE.md` |
| FR-7 (de-dupe outbound links) | AC-11 | Story 2.2 (one-time rewrite of `install.md:85` + `quickstart.md:66`) | grep-based smoke in self-test | none beyond AC-11 |
| FR-8 (chained regen script) | AC-6, AC-8 | Story 2.3 (extend `scripts/regen-generated-artifacts.sh`) | manual smoke + AC-6 indirectly | none |
| FR-9 (strict-mode build passes — now PR-gated) | AC-12 | implicit via Story 1.1 + Story 1.5 + Story 2.1 PR-step | `(cd website && mkdocs build --strict)` in `build-guides-freshness.yml` AND existing `deploy-docs.yml` | none |

(Story IDs are placeholders for the implementation plan to refine.)

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 … AC-14) pass in CI.
- [ ] `build-guides-freshness` workflow runs on every PR and includes BOTH the freshness check (with the `*.mp4` pathspec exclude) AND the PR-time `mkdocs build --strict` step. Note: not merge-blocking at the platform level until branch protection is re-enabled (see §16); maintainers treat red as "do not merge."
- [ ] `mkdocs-glightbox==0.5.2` (or latest at impl time) is pinned in `website/requirements.txt` AND the plugin block in `mkdocs.yml` carries `skip_classes: ["glightbox-skip"]`.
- [ ] All 10 walkthrough decks + 4 long-form guides are reachable on relyloop.com from the new Guides nav tab.
- [ ] `install.md:85` and `quickstart.md:66` no longer link to GitHub blob URLs for guide content.
- [ ] `docs/03_runbooks/website-guides-regen.md` is published with MP4/iOS operational details, `CLAUDE.md` + `docs/05_quality/testing.md` are updated, the chained regen script includes the new step.
- [ ] iOS Safari (real device or BrowserStack) plays one walkthrough video inline (verifies the MP4-first source order + `pix_fmt yuv420p` + `playsinline`).
- [ ] Clicking an index card thumbnail navigates to the deck page (NOT a glightbox overlay), verifying AC-14.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- **OQ-1: Social/OG-image story for the new Guides pages.** Material's `social` plugin generates per-page OG images but needs system Cairo libraries that the GitHub-Pages runner image lacks (per the comment in `website/requirements.txt`). Options: (a) defer to a separate `infra_website_og_images` follow-up; (b) inline `imaging` is already installed for future opt-in — could be flipped on later. **Recommendation:** defer. Capture as an idea file in `02_mvp2/` after merge if the missing OG previews are a measurable friction. Owner: maintainers. Due: post-merge follow-up, not blocking.

### Decision log

- **2026-06-04 — D-1: Asset strategy.** Commit-and-mirror chosen (Option A): `ui/public/guides/` is canonical source; the generator copies PNG + WebM + MP4 into `website/docs/assets/guides/<slug>/`; MP4 transcode runs locally only, not in deploy CI. Rationale: deploy runner stays Python-only; one source of truth for both consumers; rejected the generate-uncommitted-in-CI option because adding ffmpeg to the runner expands the maintenance surface for zero runtime benefit. Confirmed at preflight (idea.md §"Proposed capabilities").
- **2026-06-04 — D-2: Freshness gate scope.** PNG + WebM + generated `.md` + nav fragment, MP4 excluded. Rationale: gate must run in Python-only deploy CI; MP4 is best-effort. WebM-↔-MP4 drift tolerated; if it becomes a real problem, a local pre-commit warning is a cheap follow-up. Confirmed at preflight.
- **2026-06-04 — D-3: Ship all three slices together.** No phasing. Rationale: user-confirmed at preflight; the source content already exists, so the work is bounded (~Python generator + workflow + small CSS) and splitting introduces churn (two PRs, two reviews, two deploys) for zero shipping-velocity gain.
- **2026-06-04 — D-4: Port all 4 long-form guides.** Including `llm-endpoint-setup.md`, which is currently not in the in-app reader's `DOCS` list. Rationale: user explicitly requested all four; the LLM endpoint setup is a high-evaluation-value piece for prospects deciding whether to try the local-stack install path. The in-app reader staying as-is is an independent product decision.
- **2026-06-04 — D-5: MP4 + WebM both shipped.** Per user — WebM alone does not play on iOS Safari. The `<source>`-order discipline (MP4 first) is the source-selection mechanism.
- **2026-06-04 — D-6: Hand-written nav stays hand-written.** No `awesome-pages` plugin. The generator manages a single fragment between BEGIN/END markers. Rationale: idea explicitly preserves the hand-written approach; the maintainers care about full control over nav ordering for non-Guides sections.
- **2026-06-04 — D-7: Own workflow file for the freshness gate.** `build-guides-freshness.yml`, NOT a new job inside `pr.yml`. Rationale: mirrors the `copy-docs-freshness.yml` precedent (own workflow needed to escape `pr.yml`'s `paths-ignore: ['website/**']` so docs-only PRs still validate the sync). Verified at preflight by inspecting `pr.yml:72-91`.
- **2026-06-04 — D-8: Generator is pure stdlib Python.** No third-party deps in the generator itself. Rationale: deploy CI is Python-only and ships only `mkdocs-material[imaging] + pymdown-extensions + mkdocs-glightbox`; the generator runs at PR time too via the freshness gate and we want zero extra `pip install` cost there. `mkdocs-glightbox` is the only new pinned dep at the site level; the generator's link rewriter and `<video>` block emit use stdlib `re`, `pathlib`, `json`, `subprocess`, `urllib.parse` (for FR-2 URL splitting per D-26), and a tiny hand-rolled single-quote YAML encoder (per FR-5 + D-14 — `f"'{label.replace(chr(39), chr(39)*2)}'"`, ~1 line of code) so the generator can run before `pip install -r website/requirements.txt` and still produce correct nav-fragment YAML.
- **2026-06-04 — D-9: FR-2 rule 4 validates resolved-path existence (C1-A1).** The earlier wording let unmapped `../` paths slip through and reach GitHub as 404s. The corrected rule normalizes the relative path against `docs/08_guides/`, then asserts the resulting repo-rooted path exists in the working tree. Tradeoff: this makes the generator's correctness depend on the working tree being a full checkout (no missing submodules / shallow clone). The CI workflow already does a full checkout for the gate to compare `git status --porcelain`, so this is consistent.
- **2026-06-04 — D-10: Directory-vs-file URL discipline (C1-A3).** GitHub returns 404-style for `/blob/main/<dir>/`; the correct form is `/tree/main/<dir>/`. The generator emits the right one based on whether the resolved repo path is a file or a directory at generation time.
- **2026-06-04 — D-11: Locked video filename (C1-A4 + C1-B7).** `metadata.json.video` must equal `"walkthrough.webm"` or the generator exits 1. Trade-off: future renames require updating the generator. Benefit: eliminates the path-traversal class entirely; eliminates the renamed-MP4 ambiguity; matches what all 10 current decks already do.
- **2026-06-04 — D-12: Sibling download link, not nested fallback (C1-A5).** The iOS Safari "supports `<video>` but can't decode any source" case shows a broken-video icon, NOT the inner `<p>` fallback. Emitting a visible sibling `<p class="walkthrough-video-download">` is the documented workaround; the inner fallback stays as legacy belt-and-suspenders.
- **2026-06-04 — D-13: ffmpeg invocation hardening (C1-A6).** `-y` (non-interactive), `-pix_fmt yuv420p` (iOS Safari requirement), `+faststart` (HTTP-range streaming), temp+`os.replace` for crash-safety. Locked argv form in FR-3.
- **2026-06-04 — D-14: YAML safe-quoting for generated nav labels (C1-A7).** Single-quoted scalars with internal `'` doubled. Catches future title strings containing YAML metacharacters before they break the build.
- **2026-06-04 — D-15: Anchor validation in `mkdocs.yml` (C1-A8).** Exactly one `- API Reference: api/index.md` anchor line + both markers or neither — partial corruption from hand-edits exits 1 with a diagnostic. Catches the "half-restore" failure mode where a maintainer manually deletes one marker.
- **2026-06-04 — D-16: Three destination dirs are fully generator-owned (C1-A9).** `website/docs/guides/walkthroughs/`, `website/docs/guides/in-depth/`, `website/docs/assets/guides/` are exclusively the generator's. Hand-maintained images live under `website/docs/assets/images/` (existing) or new sibling dirs.
- **2026-06-04 — D-17: FR-2 scoped to inline Markdown links only (C1-A10).** Reference-style, image, HTML `<a>`, autolinks, fenced-code links — all fail loudly if they point at a repo-relative path. Image links inside guides currently don't reference `../` paths; if a future guide adds one, the generator surfaces the gap rather than silently mis-handling it.
- **2026-06-04 — D-18: `*.mp4` pathspec exclude on the freshness gate (C1-B1).** Without the explicit `:!website/docs/assets/guides/**/*.mp4` git pathspec, MP4 drift would trip the gate, contradicting D-2. The exclude is the canonical fix.
- **2026-06-04 — D-19: PR-time `mkdocs build --strict` step (C1-B2).** Adding the strict-build check to `build-guides-freshness.yml` (post-freshness step) is the only way to PR-gate it without modifying `pr.yml` (which paths-ignores `website/**`). Cost: ~10 seconds per PR.
- **2026-06-04 — D-20: Four-case self-test for the freshness gate (C1-B3).** Sub-case (d) `rm` a generated dest file (NOT `git rm --cached`) is the genuinely-new-file case; without it, a flawed guard could pass the existing fixtures while missing a real `?? new file` case.
- **2026-06-04 — D-21: AC-2 counts ALL repo-relative links, not "four known" (C1-B5).** The grep at preflight found at least 8 off-site repo-relative inline links across the 4 guides, plus intra-list links. AC-2's assertion is generic ("all repo-relative `../` links are rewritten"), not pinned to a count, and the path-existence check + the `mkdocs build --strict` step are the authoritative regression signals.
- **2026-06-04 — D-22: glightbox skip-class on index thumbnails (C1-B6).** Without `glightbox-skip` + the matching plugin config, clicking an index card thumbnail opens a lightbox instead of navigating. AC-14 catches the regression.
- **2026-06-04 — D-23: All generated pages are searchable by default (C1-B9).** Material's built-in `search` plugin indexes every page; the spec deliberately makes no exclusion. Walkthrough captions are short + targeted; long-form guides are high-value entry points. If search noise becomes a real complaint, individual pages can be excluded via `search: exclude: true` in front-matter as a future tweak.
- **2026-06-04 — D-24: No custom CSP for GitHub Pages (C1-B10).** GitHub Pages' default Content-Security-Policy is permissive enough for mkdocs-glightbox + the existing MkDocs Material assets. The spec records this as a deliberate non-change rather than a forgotten consideration. Re-evaluate if the deployment moves off GitHub Pages.
- **2026-06-04 — D-25: glightbox `skip_classes` config is hand-edited, not generator-managed (C2-A1).** FR-5 restricts the generator to the `nav:` fragment only. The matching plugin config (`plugins.glightbox.skip_classes: ["glightbox-skip"]`) is a one-time hand-edit done in the same PR that adds `mkdocs-glightbox` to `requirements.txt` and registers the plugin. AC-14's unit-testable half asserts both the marker AND the static plugin config are present — the generator emits the `{.glightbox-skip}` markup, the maintainer commits the plugin config.
- **2026-06-04 — D-26: `urlsplit`/`urlunsplit` semantics for the link rewriter (C2-A2).** All FR-2 rules operate on the URL's path component only; query and fragment are split off via `urllib.parse.urlsplit`, preserved verbatim, and reattached via `urlunsplit` after the path rewrite. Without this, filesystem-existence checks would include `?query#frag` and false-fail on otherwise-valid URLs.
- **2026-06-04 — D-27: AC-14 is split into unit-testable + manual halves (C2-A3).** The markup-and-config half runs in CI (unit tests on the generator output + static assertion on `mkdocs.yml`); the browser-click half lives in §16 post-merge verification. The spec deliberately keeps E2E coverage off the website (no Playwright runner targets relyloop.com), so AC-14's browser part cannot run in CI; calling it out explicitly avoids the "DoD says CI passes but the click behavior isn't actually tested in CI" trap.
- **2026-06-04 — D-28: Strict-build runs PR-time AND post-merge (C2-B1).** The earlier "freshness gate doesn't run --strict" wording in FR-9 + §11 was stale after C1-B2 added the PR-time step. Both surfaces updated to match: `build-guides-freshness.yml` step 2 + `deploy-docs.yml` existing step.
- **2026-06-04 — D-29: Self-test sub-case (d) introduces a brand-new source asset (C2-B2).** The earlier wording (`rm` a generated dest file + regen re-creates it) doesn't actually produce a `??` line — if the file was tracked in fixture HEAD, regen restores it to its tracked state and `git status` is clean. The correct distinct sub-case introduces a new source deck that the fixture's HEAD never tracked, so regen emits a never-before-tracked dest path that genuinely appears as `??`.
- **2026-06-04 — D-30: Invariant softening: MP4 is best-effort (C2-B3).** §9 now explicitly calls out the PNG/WebM-CI-enforced vs MP4-best-effort split. The `:!*.mp4` pathspec exclude per D-18 is the mechanism; the soft-invariant language is the spec's acknowledgement.
- **2026-06-04 — D-31: FR-2 rule ordering uses parsed-URL scheme/anchor checks BEFORE path rules (C3-A1).** The cycle-2 wording put `^https?://` and `^mailto:` patterns inside the "path-only" rule block, which doesn't work — after `urlsplit`, the `path` component no longer contains the scheme. Corrected ordering: split URL → check `scheme != ""` first (rule 1, absolute passthrough) → check bare-`#` (rule 2, in-page anchor) → THEN path-only rules 3+4 with `urlunsplit` reattaching query/fragment.
- **2026-06-04 — D-32: Relative-path detection uses `scheme == "" AND netloc == ""` (C3-A2).** Earlier wording said "starting with `./`, `../`, or a bare basename without `://`" which mishandles `mailto:` (a `:` but no `://`). The corrected definition uses `urlsplit` to compute `scheme == "" AND netloc == ""` as the relative discriminator — catches `tel:`, `data:`, `mailto:`, etc., as absolute correctly.
- **2026-06-04 — D-33: Pytest step added to the freshness workflow (C3-B1).** Without it, `pr.yml`'s `paths-ignore: ['website/**']` would skip the AC-14 unit assertions on website-only PRs. The new step runs `uv run pytest backend/tests/unit/scripts/test_build_guides.py -q` inside `build-guides-freshness.yml` so AC-14's unit-testable half is exercised on every PR that touches `website/**` (or anything else triggering the workflow).
- **2026-06-04 — D-34: Stdlib-only YAML single-quoter (C3-A3).** Earlier wording referenced `yaml.safe_dump` (PyYAML) which would break the "pure stdlib" claim of D-8 if a developer ran the generator before `pip install -r website/requirements.txt`. The corrected approach uses a 1-line stdlib-only single-quoter (`f"'{label.replace(chr(39), chr(39)*2)}'"`) — covers every YAML 1.2 metacharacter case relevant to nav labels.
- **2026-06-04 — D-35: §9 + §14 updated from "three" → "four" self-test sub-cases (C3-B2).** Lingering "three sub-cases" wording from before C2-B2 caught the new-source-asset case; consistency restored across §9 idempotency, §14 self-test bullet, FR-6 enumeration, and AC-10.
