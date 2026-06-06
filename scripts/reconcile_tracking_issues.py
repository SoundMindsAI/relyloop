#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0
"""Reconcile ``planned_features/`` folders with their GitHub tracking issues.

This is the **surface-independent** backstop for the tracking-issue lifecycle:
it runs on GitHub's servers (via ``.github/workflows/reconcile-tracking-issues.yml``)
after every push to ``main`` and on a daily cron, so it does not matter whether a
merge was driven from the VS Code extension, the Claude Code iPhone app, or the
desktop app — the reconciliation happens regardless.

Two directions, both automatic (the "B" option):

1. **Close** any open tracking issue whose slug now lives under
   ``implemented_features/`` (the feature shipped — close-on-merge was missed).
2. **Create** a templated tracking issue for any ``planned_features/<bucket>/<slug>/``
   folder that has no open issue yet.

Idempotency / dedup is **marker-keyed**: every issue this script creates carries a
hidden ``<!-- tracking-slug: <slug> -->`` marker. A folder is considered "tracked"
when an open issue matches by marker, by ``<slug>:`` title prefix, or by a slug
substring in the title/body (the last is the legacy-plain-title fallback).

Run ``python scripts/reconcile_tracking_issues.py --dry-run`` to preview with zero
mutations. Requires the ``gh`` CLI authenticated (``GH_TOKEN`` in CI).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

REPO = os.environ.get("GH_REPO", "SoundMindsAI/relyloop")
ROOT = pathlib.Path(__file__).resolve().parent.parent
PLANNED = ROOT / "docs/00_overview/planned_features"
IMPL = ROOT / "docs/00_overview/implemented_features"

# Two-level walk: MVP-grouping buckets under planned_features/.
BUCKETS = ["00_unsure", "01_mvp1", "02_mvp2", "03_mvp3", "04_ga", "99_backlog"]
# Auto-CREATE is scoped to roadmap-active buckets only — 99_backlog
# (defer-until-incident) and 00_unsure (genuinely-uncertain) are deliberately
# dormant, so opening tracking issues for them is noise. Auto-CLOSE always
# covers every bucket (closing a shipped feature's issue is always correct).
CREATE_BUCKETS = {"02_mvp2", "03_mvp3", "04_ga"}
RELEASE_LABEL = {"01_mvp1": "mvp1", "02_mvp2": "mvp2", "03_mvp3": "mvp3", "04_ga": "ga"}
TYPE_LABEL = {
    "feat": "type/feature",
    "infra": "type/infra",
    "chore": "type/chore",
    "bug": "type/bug",
    "epic": "type/epic",
}

MARKER_RE = re.compile(r"<!--\s*tracking-slug:\s*([a-z0-9_]+)\s*-->")
TITLE_SLUG_RE = re.compile(r"^([a-z]+_[a-z0-9_]+):")
H1_RE = re.compile(r"^#\s+(.*)$", re.MULTILINE)
PRIORITY_RE = re.compile(r"^\*\*Priority:\*\*\s*([A-Za-z0-9]+)", re.MULTILINE)

DRY = "--dry-run" in sys.argv


def gh(*args: str, check: bool = True) -> str:
    """Run a ``gh`` subcommand and return stdout."""
    cmd = ["gh", *args]  # noqa: S607 — gh is a trusted, fixed executable on PATH
    proc = subprocess.run(cmd, check=check, text=True, capture_output=True)  # noqa: S603
    return proc.stdout


def log(action: str, msg: str) -> None:
    prefix = "[dry-run] " if DRY else ""
    print(f"{prefix}{action}: {msg}", flush=True)


def existing_labels() -> set[str]:
    data = json.loads(gh("label", "list", "--repo", REPO, "--limit", "300", "--json", "name"))
    return {row["name"] for row in data}


def implemented_slugs() -> set[str]:
    out: set[str] = set()
    if IMPL.is_dir():
        for d in IMPL.iterdir():
            if d.is_dir():
                out.add(re.sub(r"^\d{4}_\d{2}_\d{2}_", "", d.name))
    return out


def planned_folders() -> list[tuple[str, str, pathlib.Path]]:
    res: list[tuple[str, str, pathlib.Path]] = []
    for bucket in BUCKETS:
        bp = PLANNED / bucket
        if not bp.is_dir():
            continue
        for d in sorted(bp.iterdir()):
            if not d.is_dir():
                continue
            if (d / "idea.md").exists() or (d / "feature_spec.md").exists():
                res.append((bucket, d.name, d))
    return res


def open_issues() -> list[dict]:
    return json.loads(
        gh(
            "issue",
            "list",
            "--repo",
            REPO,
            "--state",
            "open",
            "--limit",
            "300",
            "--json",
            "number,title,body",
        )
    )


def identity_slug(issue: dict) -> str | None:
    """The issue's OWN slug (marker first, then title prefix). Body mentions are
    cross-links, not identity, so they are deliberately excluded here."""
    m = MARKER_RE.search(issue.get("body") or "")
    if m:
        return m.group(1)
    m = TITLE_SLUG_RE.match(issue.get("title") or "")
    if m:
        return m.group(1)
    return None


def mentions_slug(issue: dict, slug: str) -> bool:
    """Loose match for dedup: marker, title prefix, OR slug substring anywhere."""
    return slug in (issue.get("title") or "") or slug in (issue.get("body") or "")


def prefix_of(slug: str) -> str:
    return slug.split("_", 1)[0]


def parse_idea(folder: pathlib.Path, slug: str) -> tuple[str, str]:
    """Return (summary, priority_tier) from idea.md (falls back to feature_spec.md)."""
    src = folder / "idea.md"
    if not src.exists():
        src = folder / "feature_spec.md"
    text = src.read_text(encoding="utf-8") if src.exists() else ""

    summary = slug
    h1 = H1_RE.search(text)
    if h1:
        line = h1.group(1).strip()
        # Strip a leading "<slug> — " or "<slug>: " so the summary reads cleanly.
        line = re.sub(rf"^{re.escape(slug)}\s*[—:-]\s*", "", line)
        line = re.sub(r"^Idea\s*[—:-]\s*", "", line)
        if line:
            summary = line

    tier = "P2"
    pr = PRIORITY_RE.search(text)
    if pr:
        raw = pr.group(1)
        if raw.upper() in {"P0", "P1", "P2"}:
            tier = raw.upper()
        elif raw.upper() == "P3":  # dashboard convention: P3 buckets as P2
            tier = "P2"
        elif raw.lower() == "backlog":
            tier = "backlog"
    return summary, tier


def build_body(bucket: str, slug: str, folder: pathlib.Path, summary: str, tier: str) -> str:
    rel = folder.relative_to(ROOT)
    pr_disp = "Backlog" if tier == "backlog" else tier
    return f"""<!-- tracking-slug: {slug} -->
## Problem
{summary}

_(Auto-created by `reconcile-tracking-issues` from the planned-feature folder — the
idea.md is the source of detail; run `/idea-preflight` to verify claims against the
current tree before execution.)_

## Status
- **Stage:** IDEA
- **Priority:** {pr_disp}

## Definition of done
- [ ] See the acceptance criteria in the linked idea.md (backfill this checklist at the SPEC stage).

## Artifacts
- **Idea:** [{rel}/idea.md]({rel}/idea.md)

## How to execute
Run `/idea-preflight`, then `/pipeline {rel} --auto`.
"""


def labels_for(bucket: str, slug: str, tier: str, available: set[str]) -> list[str]:
    wanted = [RELEASE_LABEL.get(bucket), TYPE_LABEL.get(prefix_of(slug))]
    wanted.append("priority/backlog" if tier == "backlog" else f"priority/{tier}")
    wanted.append("needs-preflight")
    # Only apply labels that already exist, so `gh issue create` never fails on a
    # missing label (e.g. no `mvp3`/`ga` label yet).
    return [lbl for lbl in wanted if lbl and lbl in available]


def main() -> int:
    impl = implemented_slugs()
    planned = planned_folders()
    planned_slugs = {slug for _, slug, _ in planned}
    issues = open_issues()
    available = existing_labels()

    closed = created = 0

    # --- Direction 1: close shipped-but-open tracking issues. ---
    for issue in issues:
        slug = identity_slug(issue)
        if not slug:
            continue
        if slug in impl and slug not in planned_slugs:
            num = issue["number"]
            folder = next(iter(IMPL.glob(f"*_{slug}")), None)
            ptr = f"`{folder.relative_to(ROOT)}/`" if folder else "implemented_features/"
            log("CLOSE", f"#{num} {slug} (shipped → {ptr})")
            if not DRY:
                gh(
                    "issue",
                    "close",
                    str(num),
                    "--repo",
                    REPO,
                    "--reason",
                    "completed",
                    "--comment",
                    f"Shipped — finalized at {ptr}. Auto-closed by "
                    f"`reconcile-tracking-issues` (close-on-merge backstop).",
                )
            closed += 1

    # --- Direction 2: create issues for untracked planned folders. ---
    for bucket, slug, folder in planned:
        if bucket not in CREATE_BUCKETS:
            continue  # dormant bucket (99_backlog / 00_unsure) — no auto-create
        if any(mentions_slug(i, slug) for i in issues):
            continue
        summary, tier = parse_idea(folder, slug)
        title = f"{slug}: {summary}"
        body = build_body(bucket, slug, folder, summary, tier)
        labels = labels_for(bucket, slug, tier, available)
        log("CREATE", f"{title}  [{', '.join(labels)}]")
        if not DRY:
            args = ["issue", "create", "--repo", REPO, "--title", title, "--body", body]
            for lbl in labels:
                args += ["--label", lbl]
            url = gh(*args).strip()
            print(f"  -> {url}", flush=True)
        created += 1

    print(
        f"\nReconcile summary: {closed} closed, {created} created"
        f"{' (dry-run — no mutations)' if DRY else ''}.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
