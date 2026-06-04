<!-- SPDX-FileCopyrightText: 2026 soundminds.ai -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Runbook — regenerating the website Guides pages

The public site **relyloop.com** publishes the same walkthrough decks and
long-form guides that ship in the running app, under a top-level **Guides**
nav tab. Those pages are **generated** from the in-repo source assets by
[`website/scripts/build_guides.py`](../../website/scripts/build_guides.py) and
held in sync by a CI freshness gate
([`build-guides-freshness.yml`](../../.github/workflows/build-guides-freshness.yml)).
This runbook covers regenerating them, diagnosing a red gate, and adding new
content.

> **The generated trees are generator-owned — never hand-edit them.** Every
> file under `website/docs/guides/walkthroughs/`, `website/docs/guides/in-depth/`,
> and `website/docs/assets/guides/` is re-derived (and stale files pruned) on
> every generator run. Each generated `.md` carries a
> `<!-- GENERATED … DO NOT EDIT -->` header. Edit the **source** instead:
> `ui/public/guides/<slug>/` (decks) or `docs/08_guides/*.md` (long-form).

## Single source of truth

| Source | Feeds | Owned by |
|---|---|---|
| `ui/public/guides/<NN_slug>/` (metadata.json + numbered PNGs + walkthrough.webm [+ .mp4]) | walkthrough deck pages + assets | the `guide-gen` skill |
| `docs/08_guides/{tutorial-first-study,quick-tour,workflows-overview,llm-endpoint-setup}.md` | the 4 in-depth long-form pages | maintainers |

The same `ui/public/guides/` assets also feed the in-app `<GuideViewer>`; the
website is a second consumer, not a fork.

## Regenerate (the canonical fix)

When the `build-guides-freshness` gate is red, run the one-paste chained fix —
it regenerates **all** CI-freshness-gated artifacts and stages them:

```bash
bash scripts/regen-generated-artifacts.sh
git commit -s -m "docs(website): regenerate Guides pages"
```

Or the website generator alone:

```bash
python website/scripts/build_guides.py
git add website/docs/guides website/docs/assets/guides website/mkdocs.yml
```

The generator is **stdlib-only** and **idempotent** — a re-run on an
up-to-date tree produces no diff.

## How the freshness gate flags stale source

`build-guides-freshness.yml` runs on every PR (it has NO `paths-ignore`, so it
fires even on website-only PRs that `pr.yml` skips). It:

1. runs the generator's unit tests,
2. self-tests the freshness guard (`scripts/ci/test_verify_build_guides_fresh.sh`, 4 cases),
3. runs the gate (`scripts/ci/verify_build_guides_fresh.sh`) — regenerates, then fails on any `git status --porcelain` drift across `website/docs/guides/`, `website/docs/assets/guides/` (MP4 **excluded**), and `website/mkdocs.yml`,
4. runs `mkdocs build --strict` to catch broken nav / links before merge.

A failure means a source asset changed without a regen. The gate's log prints
the canonical fix command.

## Adding a new long-form guide

The 4 long-form guides are a **hard-coded** list (a missing source fail-louds —
this prevents a stale generated page surviving a source deletion the gate
can't see, since the gate's scope excludes `docs/08_guides/`):

1. Write the new guide at `docs/08_guides/<basename>.md`.
2. Add its basename to `LONG_FORM_GUIDES` (and a label to `LONG_FORM_TITLES`)
   in [`website/scripts/build_guides.py`](../../website/scripts/build_guides.py).
3. Regenerate + commit.

The link rewriter rewrites every inline `[text](url)`: intra-list links stay
in-site siblings; off-site `../` repo links become GitHub `blob`/`tree` URLs
(after a path-existence check); a typo'd / unresolvable link **fails loudly**
with `file:line`.

## Adding a new walkthrough deck

Decks are discovered dynamically from `ui/public/guides/`:

1. Run the `guide-gen` skill to capture the new deck (PNGs + `walkthrough.webm`
   + `metadata.json`). `metadata.json.video` MUST be `"walkthrough.webm"` (the
   generator enforces this).
2. Transcode the MP4 (see below).
3. Regenerate + commit.

## MP4 transcode + iOS Safari (operational details)

The website embeds a mobile-safe `<video>` with the **MP4 source first** (iOS
Safari ignores WebM) and a WebM fallback, plus an always-visible download link.
MP4s are **best-effort** — the gate does not enforce them (the Python-only
deploy runner cannot transcode), so WebM↔MP4 drift never reds CI; an
un-transcoded deck just shows the download-link fallback on iOS.

Produce / refresh MP4s locally (requires `ffmpeg` on PATH):

```bash
# macOS:  brew install ffmpeg     |  Debian/Ubuntu:  apt-get install ffmpeg
python website/scripts/build_guides.py --transcode
git add ui/public/guides website/docs/assets/guides
```

`--transcode` (re)produces `walkthrough.mp4` next to each `walkthrough.webm`
(skipping ones already newer than their source), using
`ffmpeg -y … -c:v libx264 -profile:v baseline -level 3.1 -pix_fmt yuv420p
-movflags +faststart -an -f mp4` (written to a temp file then atomically
renamed). If `ffmpeg` is absent the step WARNs and continues.

Verify a produced MP4:

```bash
# iOS Safari requires 4:2:0 chroma subsampling:
ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 \
  ui/public/guides/01_register_first_cluster/walkthrough.mp4   # → yuv420p

# +faststart moves the moov atom to the front for progressive playback:
ffprobe -v trace ui/public/guides/01_register_first_cluster/walkthrough.mp4 2>&1 \
  | grep -m1 -i 'moov'   # moov should appear before mdat
```

Confirm real iOS Safari inline playback after deploy: open
`https://relyloop.com/guides/walkthroughs/<slug>/` on a device (or BrowserStack)
and verify the video plays inline (not full-screen-forced) with controls.

## Post-deploy smoke (manual)

After a merge to `main` deploys (~5 min via `deploy-docs.yml`):

- `https://relyloop.com/guides/walkthroughs/` — the card grid renders.
- Click a card **thumbnail** → it NAVIGATES to the deck page (does NOT open a
  lightbox — verifies the `glightbox-skip` class + `skip_classes` config).
- Open a deck → the video plays; click a screenshot INSIDE the deck → a
  glightbox overlay opens (zoomable).
