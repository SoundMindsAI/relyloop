# Walkthrough guides on the public website (relyloop.com)

**Date:** 2026-06-04 (preflight-refreshed 2026-06-04)
**Status:** Idea — user request (operator noticed relyloop.com lacks the guides that ship in the running app)
**Priority:** P2
**Origin:** User request — "our published website https://relyloop.com/ does not contain the guides that are in the running app … add them to the running website, well suited for both web and mobile, fully resizable, with a version including video if possible."
**Depends on:** None (the source guide content already exists in `docs/08_guides/` and `ui/public/guides/`)

## Problem

The public website **relyloop.com** is an MkDocs Material site at [`website/`](../../../../../website/) (deployed via GitHub Pages by [deploy-docs.yml](../../../../../.github/workflows/deploy-docs.yml), `mkdocs build --strict`). It ships **no guides, no screenshots, and no video** — only prose pages (Getting Started, Concepts, Engines, etc.).

Meanwhile the **internal Next.js app** (localhost only, never published) ships a rich guide system the public never sees:
- **4 long-form markdown guides** in [`docs/08_guides/`](../../../../../docs/08_guides/): `tutorial-first-study.md`, `quick-tour.md`, `workflows-overview.md`, `llm-endpoint-setup.md`.
- **10 screenshot walkthrough decks** in [`ui/public/guides/<NN_slug>/`](../../../../../ui/public/guides/) — each with a `metadata.json` (title, description, estimated_time, tags, `screenshots[]` of `{file, caption}`, optional `video`), **48** numbered PNGs total (5/5/5/5/4/5/5/4/5/5 per deck), and a `walkthrough.webm` slow-motion video. Total committed asset footprint ~13 MB (7.6 MB PNG + 5.3 MB WebM, verified at preflight); a parallel MP4 transcode adds another ~5–6 MB if committed.

Prospective users evaluating RelyLoop on relyloop.com get none of this onboarding/visual material. The gap is pure surfacing — the content already exists and is maintained; it simply never reaches the published site.

## Proposed capabilities

User-confirmed decisions (2026-06-04): ship all three slices together; port **all 4** long-form guides; provide **MP4 + WebM** video (WebM alone does not play on iOS Safari).

Preflight-recommended defaults (2026-06-04, confirm at spec-time):

- **Asset strategy: commit-and-mirror.** `ui/public/guides/` already commits PNG + WebM (the canonical source). `build_guides.py` *copies* those into `website/docs/assets/guides/<slug>/`, transcodes WebM→MP4 locally when ffmpeg is available, and commits the MP4 alongside the WebM in the source `ui/public/guides/` tree (so both the in-app `GuideViewer` and the website draw from the same committed assets — one source of truth, no per-target duplicate transcodes). Alternative considered: generate-uncommitted-in-CI — rejected because the deploy runner is Python-only and adding ffmpeg + a transcode step there expands the maintenance surface for a zero-runtime benefit.
- **Freshness gate scope: PNG + WebM only.** The gate re-runs the generator and fails on `git status --porcelain` drift in `website/docs/assets/guides/**/*.{png,webm}` + the generated `.md` files + the nav. MP4 is a derived best-effort artifact — the gate skips it so the deploy runner stays Python-only. Drift between WebM and MP4 (someone regenerated WebM, forgot to retranscode) is left to a local pre-commit warning or a separate looser check.

### Surface the 10 walkthrough decks on the website
- New top-level **Guides** nav tab with a **Walkthroughs** section + an overview/card-grid index page.
- One generated MkDocs page per deck: title, an estimated-time/tags admonition, the responsive video (when present), then each screenshot with its caption.
- Fully resizable / zoomable images via the **mkdocs-glightbox** plugin (auto pinch-zoom lightbox, mobile-friendly, alt text as caption — the MkDocs Material standard).
- Responsive on web and mobile (Material is responsive by default; add screenshot/video CSS so nothing overflows at phone width).

### Embedded video, mobile-safe
- Responsive HTML5 `<video>` (via the already-enabled `md_in_html` extension) listing an **MP4 (H.264) source first**, WebM as fallback, `playsinline` for iOS, with a download-link fallback.
- WebM→MP4 transcode via ffmpeg (present locally; absent in deploy CI) — MP4s committed as artifacts; video never build-blocking (graceful when MP4 absent).

### Port the 4 long-form guides
- Copy `docs/08_guides/*.md` into a **Guides > In-depth guides** nav section.
- Rewrite repo-relative links: off-site repo paths → GitHub blob URLs; intra-guide links → in-site siblings; strip presenter comments; **fail loudly on any unmapped `../` prefix** (a missed mapping would break the `--strict` build).
- De-duplicate the two existing outbound GitHub-blob links in [`website/docs/getting-started/quickstart.md`](../../../../../website/docs/getting-started/quickstart.md) and [`install.md`](../../../../../website/docs/getting-started/install.md) by repointing them at the new in-site pages.

### Generator + freshness gate
- A single Python generator `website/scripts/build_guides.py` (the website CI path is Python-only — no Node) that copies/transcodes assets, emits deck pages + index, ports the long-form guides, and prunes stale output (idempotent, mirroring [`ui/scripts/copy-docs.mjs`](../../../../../ui/scripts/copy-docs.mjs)).
- Keep the hand-written `nav:` block (no nav plugin) and add a CI freshness gate that re-runs the generator and fails on `git status --porcelain` drift — same pattern as the existing [`copy-docs-freshness.yml`](../../../../../.github/workflows/copy-docs-freshness.yml) workflow. `--strict` forbids orphan pages, so generator output and nav must stay in lockstep.

## Scope signals

- **Backend:** None.
- **Frontend (internal app):** None — this is the public MkDocs site, not the Next.js app.
- **Website:** new `website/scripts/build_guides.py`; new `website/docs/guides/{walkthroughs,in-depth}/*.md` (generated); new `website/docs/assets/guides/<slug>/*` (PNG + WebM + MP4, ~12–13 MB committed); new `website/docs/stylesheets/extra.css`; edits to `website/mkdocs.yml` (glightbox plugin, `extra_css`, Guides nav) and `website/requirements.txt` (add `mkdocs-glightbox`).
- **Migration:** None.
- **Config:** New MkDocs plugin (`mkdocs-glightbox`) + `extra_css` entry. ffmpeg required by the local generator (already on dev machines; not on the deploy runner).
- **CI:** Add a freshness gate (in `pr.yml` or a small dedicated workflow). `deploy-docs.yml` build path unchanged (assets pre-committed).
- **Audit events:** N/A (public docs site, no state mutations).

## Why not yet prioritized

P2: high-value for evaluation/onboarding but not blocking any in-flight MVP2 work, and the underlying content is already complete and maintained — this is a surfacing/pipeline task, not new product. Filed in `02_mvp2/` as the active-release bucket. The two main spec-time questions (asset strategy + freshness-gate scope) have preflight-recommended defaults inline above; the remaining open call is the social/OG-image story for the new pages (Material's `social` plugin needs system Cairo and is intentionally off per `website/requirements.txt` — defer to spec-time).

## Relationship to other work

- Source content is produced by the [`guide-gen`](../../../../../.claude/skills/guide-gen/SKILL.md) skill (Playwright screenshots + WebM + cross-model visual review) — this idea consumes that output, it does not change how guides are authored.
- Independent of the internal-app `GuideViewer`/`MarkdownDoc` rendering path; the website gets its own generated MkDocs pages rather than reusing React components.
- When new walkthrough decks are added to `ui/public/guides/` later, the generator + freshness gate keep the website in sync automatically.
