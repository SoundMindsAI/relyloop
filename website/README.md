# RelyLoop website

This directory is the public site published at **[relyloop.com](https://relyloop.com)**.
It's built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
(Python-only — no Node/npm toolchain).

## Preview locally

From this directory:

```bash
python3 -m venv ~/.venvs/relyloop-docs && source ~/.venvs/relyloop-docs/bin/activate
pip install -r requirements.txt
mkdocs serve                                          # http://127.0.0.1:8000
```

> **Note:** Keep the build venv **outside** the repo tree (e.g. `~/.venvs/…`).
> A venv created inside `website/` gets walked by the `reuse` pre-commit hook
> (it scans third-party package files), which fails the SPDX check on an
> otherwise-clean commit.

`mkdocs serve` live-reloads as you edit. To reproduce the CI build exactly:

```bash
mkdocs build --strict       # fails on broken links / nav / config issues
```

## Where to edit what

| You want to change… | Edit… |
|---|---|
| Navigation, theme, extensions, plugins | `mkdocs.yml` |
| Page content | `docs/**/*.md` |
| Logo / favicon | `docs/assets/` (placeholders — replace in place) |
| Custom domain | `docs/CNAME` (copied to the site root on build) |
| Pinned build dependencies | `requirements.txt` |

## Deployment

Publishing is automated. The
[`deploy-docs.yml`](../.github/workflows/deploy-docs.yml) GitHub Actions
workflow runs `mkdocs build --strict` and publishes to GitHub Pages on every
push to `main` that touches `website/**` (or on manual `workflow_dispatch`).
Do **not** run `mkdocs gh-deploy` — there is no `gh-pages` branch; deployment
goes through the Pages artifact + `actions/deploy-pages`.

## Notes

- The `social` plugin (social cards) is intentionally **not** enabled — it
  needs system Cairo libraries. The `mkdocs-material[imaging]` extra is pinned
  in `requirements.txt` so it's a one-line change if we want cards later.
- Site content is licensed the same as the repo (Apache-2.0); there's no
  separate LICENSE here.
