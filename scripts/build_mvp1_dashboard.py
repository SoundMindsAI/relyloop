#!/usr/bin/env python3
"""Build the RelyLoop MVP1 dashboard HTML.

Walks `docs/02_product/planned_features/` and `docs/00_overview/implemented_features/`,
parses each feature folder's pipeline artifacts (idea.md / feature_spec.md /
implementation_plan.md / pipeline_status.md), and writes a single self-contained
HTML dashboard at `docs/00_overview/mvp1_dashboard.html`.

Source of truth is the folder structure + the feature artifacts, not
mvp1-user-stories.md (which is a curated narrative that drifts). The dashboard
shows:

* KPI row — features done / remaining, MVP1 percentage, open bugs, open chores
* Kanban — Idea / Spec / Plan / Implement / Done columns
* Dependency graph — Mermaid render of "X depends on Y"
* Per-card detail — type badge, one-liner, status, PR number, merged date

Run via `make dashboard` or `python3 scripts/build_mvp1_dashboard.py` from
the repo root. No third-party dependencies — stdlib only.
"""

from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLANNED_DIR = REPO_ROOT / "docs/02_product/planned_features"
IMPLEMENTED_DIR = REPO_ROOT / "docs/00_overview/implemented_features"
OUTPUT_HTML = REPO_ROOT / "docs/00_overview/mvp1_dashboard.html"
OUTPUT_MD = REPO_ROOT / "docs/00_overview/MVP1_DASHBOARD.md"

# Feature directory name → human title fragment. Anything not in this map
# falls back to the folder name with the prefix stripped.
PREFIX_LABELS = {
    "feat": "Feature",
    "infra": "Infra",
    "chore": "Chore",
    "bug": "Bug",
    "epic": "Epic",
}

STAGES = ["idea", "spec", "plan", "implement", "done"]
STAGE_LABELS = {
    "idea": "Idea",
    "spec": "Spec",
    "plan": "Plan",
    "implement": "Implementing",
    "done": "Done",
}


@dataclass
class Feature:
    folder: str  # full folder name (e.g., "feat_study_lifecycle")
    prefix: str  # "feat" | "infra" | "chore" | "bug" | "epic"
    short_name: str  # folder name without prefix (e.g., "study_lifecycle")
    path: Path  # absolute path to the folder
    location: str  # "planned" | "implemented"
    stage: str  # one of STAGES
    status_line: str  # one-line status from the latest stage's artifact
    one_liner: str  # the Outcome / Problem one-liner
    depends_on: list[str] = field(default_factory=list)  # folder names
    pr_number: int | None = None
    merged_date: str | None = None
    deferred_phase: str | None = None  # human note if a phase*_idea.md is present

    @property
    def display_name(self) -> str:
        return self.short_name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _split_prefix(folder: str) -> tuple[str, str]:
    """Return (prefix, short_name). Folder is like 'feat_study_lifecycle'."""
    if "_" not in folder:
        return ("", folder)
    head, _, tail = folder.partition("_")
    if head not in PREFIX_LABELS:
        return ("", folder)
    return (head, tail)


def _strip_date_prefix(folder: str) -> str:
    """Implemented features are dated: '2026_05_10_infra_adapter_elastic'."""
    m = re.match(r"^\d{4}_\d{2}_\d{2}_(.+)$", folder)
    return m.group(1) if m else folder


def _extract_status_line(text: str) -> str:
    """Pull the `**Status:**` value from a markdown header block."""
    m = re.search(r"^\*\*Status:\*\*\s*(.+)$", text, flags=re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_one_liner(text: str) -> str:
    """Best-effort: prefer Outcome bullet, fall back to Problem bullet."""
    for label in ("Outcome", "Problem"):
        m = re.search(
            rf"^- \*\*{label}:\*\*\s*(.+?)$",
            text,
            flags=re.MULTILINE,
        )
        if m:
            line = m.group(1).strip()
            # Strip wrapping markdown links/code; keep first sentence.
            sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0]
            return sentence
    return ""


def _extract_idea_problem(text: str) -> str:
    """Pull the first paragraph under the `## Problem` heading."""
    m = re.search(r"^##\s+Problem\s*$", text, flags=re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end() :]
    # First non-empty paragraph.
    para = next((p for p in rest.split("\n\n") if p.strip()), "")
    para = re.sub(r"\s+", " ", para).strip()
    # Cap length.
    if len(para) > 240:
        para = para[:237] + "..."
    return para


def _extract_depends_on(text: str) -> list[str]:
    """Parse `- Depends on: ...` line into a list of folder names."""
    m = re.search(r"^-\s+Depends on:\s*(.+)$", text, flags=re.MULTILINE)
    if not m:
        return []
    line = m.group(1)
    # Match `[`name`]` or bare backticked names; strip out punctuation.
    folders = re.findall(r"`([a-z0-9_]+)`", line)
    # Filter to folder-like patterns (must contain underscore + recognized prefix).
    return [f for f in folders if any(f.startswith(p + "_") for p in PREFIX_LABELS)]


def _extract_pr_number(pipe: str, plan: str, spec: str) -> int | None:
    """Find this feature's PR number, not dependency cites.

    Priority order:
    1. The `## Implement` section of pipeline_status.md — most authoritative
       for shipped features. Accepts both `PR #N` and `[#N]` markdown-link
       formats.
    2. The plan's `**Status:**` header (catches in-flight features).
    3. A `merged`-context match across all artifacts (catches features
       described in narrative form elsewhere).
    4. First `#N` reference, as a last-resort fallback.
    """
    # 1. Scope to pipeline_status.md's Implement section first.
    impl = re.search(
        r"^##\s+Implement[^\n]*\n(.+?)(?=^##|\Z)",
        pipe,
        flags=re.MULTILINE | re.DOTALL,
    )
    if impl:
        m = re.search(r"#(\d+)", impl.group(1))
        if m:
            return int(m.group(1))
    # 2. Plan's Status header.
    m = re.search(r"^\*\*Status:\*\*[^\n]*PR\s*#(\d+)", plan, flags=re.MULTILINE)
    if m:
        return int(m.group(1))
    # 3. Merged-context across all sources.
    combined = pipe + "\n" + plan + "\n" + spec
    m = re.search(r"PR[^a-zA-Z\n]{0,5}#(\d+)[^.\n]{0,80}merged", combined)
    if m:
        return int(m.group(1))
    m = re.search(r"merged[^.\n]{0,80}PR[^a-zA-Z\n]{0,5}#(\d+)", combined)
    if m:
        return int(m.group(1))
    # 4. Last-resort: first PR reference.
    matches = re.findall(r"PR[^a-zA-Z\n]{0,5}#(\d+)", combined)
    return int(matches[0]) if matches else None


def _extract_merged_date(text: str) -> str | None:
    """Look for `merged YYYY-MM-DD` in any artifact."""
    m = re.search(r"merged\s+(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def _detect_deferred_phase(folder_path: Path) -> str | None:
    """A `phase*_idea.md` file flags partial-feature shipping."""
    deferred = sorted(folder_path.glob("phase*_idea.md"))
    if not deferred:
        return None
    return ", ".join(d.stem.replace("_idea", "").replace("phase", "Phase ") for d in deferred)


def _detect_implement_status(text: str) -> str:
    """Return 'complete' / 'in_progress' / 'not_started' from pipeline_status.md."""
    impl = re.search(
        r"^##\s+Implement(?:[^\n]*)\s*$(.+?)(?=^##|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not impl:
        return "not_started"
    body = impl.group(1)
    if re.search(r"Status[^\n]*Complete", body):
        return "complete"
    if re.search(r"Status[^\n]*\bIn Progress\b", body, flags=re.IGNORECASE):
        return "in_progress"
    if re.search(r"Status[^\n]*Not started", body):
        return "not_started"
    return "not_started"


# ---------------------------------------------------------------------------
# Feature loaders
# ---------------------------------------------------------------------------


def _load_planned(folder_path: Path) -> Feature | None:
    folder = folder_path.name
    if folder == "feature_templates":
        return None
    prefix, short = _split_prefix(folder)
    if not prefix:
        return None

    idea = _read(folder_path / "idea.md")
    spec = _read(folder_path / "feature_spec.md")
    plan = _read(folder_path / "implementation_plan.md")
    pipe = _read(folder_path / "pipeline_status.md")
    deferred = _detect_deferred_phase(folder_path)

    # Stage derivation — most-advanced-artifact wins, but pipeline_status's
    # Implement section can downgrade to "implement" stage with in-progress.
    stage = "idea"
    if spec:
        stage = "spec"
    if plan:
        stage = "plan"
    if pipe:
        impl_status = _detect_implement_status(pipe)
        if impl_status == "complete":
            # Check if there's deferred phase work — if so, stay at "implement"
            # (partial-completion); else "done".
            stage = "implement" if deferred else "done"
        elif impl_status == "in_progress":
            stage = "implement"
        # not_started: leave at "plan"

    # Status line — pick the most informative artifact for the current stage.
    status_text = pipe or plan or spec or idea
    status_line = _extract_status_line(status_text) or ""

    # One-liner.
    one_liner = _extract_one_liner(spec) if spec else _extract_idea_problem(idea)

    feature = Feature(
        folder=folder,
        prefix=prefix,
        short_name=short,
        path=folder_path,
        location="planned",
        stage=stage,
        status_line=status_line,
        one_liner=one_liner,
        depends_on=_extract_depends_on(spec),
        pr_number=_extract_pr_number(pipe, plan, spec),
        merged_date=_extract_merged_date(pipe + plan + spec),
        deferred_phase=deferred,
    )
    return feature


def _load_implemented(folder_path: Path) -> Feature | None:
    folder = folder_path.name
    short_with_prefix = _strip_date_prefix(folder)
    prefix, short = _split_prefix(short_with_prefix)
    if not prefix:
        return None

    spec = _read(folder_path / "feature_spec.md")
    plan = _read(folder_path / "implementation_plan.md")
    pipe = _read(folder_path / "pipeline_status.md")

    one_liner = _extract_one_liner(spec)
    pr = _extract_pr_number(pipe, plan, spec)
    merged = _extract_merged_date(pipe + plan + spec)

    # Date prefix from the folder is the canonical merged date.
    m = re.match(r"^(\d{4})_(\d{2})_(\d{2})_", folder)
    if m and not merged:
        merged = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return Feature(
        folder=short_with_prefix,
        prefix=prefix,
        short_name=short,
        path=folder_path,
        location="implemented",
        stage="done",
        status_line=_extract_status_line(pipe + plan + spec) or "Complete",
        one_liner=one_liner,
        depends_on=_extract_depends_on(spec),
        pr_number=pr,
        merged_date=merged,
    )


def _data_freshness() -> dt.datetime:
    """Return the most-recent mtime across feature folders + this script.

    Determines the "data as-of" date displayed on the dashboard. Using
    mtime instead of `datetime.now()` keeps regeneration idempotent so
    the pre-commit hook doesn't produce churn on every unrelated commit.
    The script itself is included so layout/parser changes shift the
    timestamp.
    """
    candidates: list[float] = [Path(__file__).stat().st_mtime]
    for root in (PLANNED_DIR, IMPLEMENTED_DIR):
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            candidates.append(path.stat().st_mtime)
    return dt.datetime.fromtimestamp(max(candidates), tz=dt.UTC)


def load_all() -> list[Feature]:
    features: list[Feature] = []
    if PLANNED_DIR.exists():
        for child in sorted(PLANNED_DIR.iterdir()):
            if not child.is_dir():
                continue
            f = _load_planned(child)
            if f:
                features.append(f)
    if IMPLEMENTED_DIR.exists():
        for child in sorted(IMPLEMENTED_DIR.iterdir()):
            if not child.is_dir():
                continue
            f = _load_implemented(child)
            if f:
                features.append(f)
    return features


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


CSS = """
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f6f7fb;
  color: #1f2530;
}
header {
  padding: 24px 32px 16px;
  border-bottom: 1px solid #e2e6ee;
  background: #fff;
  position: sticky;
  top: 0;
  z-index: 5;
}
header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
header .meta {
  margin-top: 4px;
  color: #5b6477;
  font-size: 13px;
}
main { padding: 24px 32px 64px; max-width: 1600px; margin: 0 auto; }
section { margin-bottom: 32px; }
section > h2 {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #6b7385;
}

/* KPI row */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.kpi {
  background: #fff;
  border: 1px solid #e2e6ee;
  border-radius: 10px;
  padding: 16px 18px;
}
.kpi .label { color: #5b6477; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
.kpi .value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.kpi .sub { color: #6b7385; font-size: 12px; margin-top: 2px; }
.kpi.complete .value { color: #15803d; }
.kpi.warn .value { color: #b45309; }
.kpi.bug .value { color: #b91c1c; }
.kpi-secondary {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  font-size: 12px;
  color: #5b6477;
}

/* Progress bar */
.bar {
  margin-top: 8px;
  height: 6px;
  background: #eaecf2;
  border-radius: 3px;
  overflow: hidden;
}
.bar > span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #4f46e5, #14b8a6);
}

/* Kanban */
.kanban {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.col {
  background: #fff;
  border: 1px solid #e2e6ee;
  border-radius: 10px;
  padding: 12px;
  min-height: 200px;
}
.col h3 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.col h3 .count {
  font-weight: 500;
  color: #6b7385;
  background: #eaecf2;
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 11px;
}
.col.idea       h3 { color: #475569; }
.col.spec       h3 { color: #1d4ed8; }
.col.plan       h3 { color: #b45309; }
.col.implement  h3 { color: #c2410c; }
.col.done       h3 { color: #15803d; }
.col.idea       { border-top: 3px solid #94a3b8; }
.col.spec       { border-top: 3px solid #3b82f6; }
.col.plan       { border-top: 3px solid #eab308; }
.col.implement  { border-top: 3px solid #f97316; }
.col.done       { border-top: 3px solid #22c55e; }

/* Cards */
.card {
  background: #fbfcfe;
  border: 1px solid #e2e6ee;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  font-size: 13px;
  position: relative;
}
.card .name {
  font-weight: 600;
  margin-bottom: 4px;
  word-break: break-word;
}
.card .name a { color: inherit; text-decoration: none; }
.card .name a:hover { text-decoration: underline; }
.card .one-liner {
  color: #4b5360;
  font-size: 12px;
  margin-bottom: 6px;
}
.card .meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
  align-items: center;
  font-size: 11px;
  color: #6b7385;
}
.card .meta .badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.card .deps { font-size: 11px; color: #6b7385; margin-top: 4px; }
.card .deps .dep-chip {
  display: inline-block;
  padding: 1px 6px;
  margin-right: 3px;
  margin-top: 2px;
  border-radius: 10px;
  background: #eef2f7;
  color: #475569;
  font-size: 10px;
}

/* Type accents on the left edge */
.card.feat   { border-left: 3px solid #6366f1; }
.card.infra  { border-left: 3px solid #f59e0b; }
.card.chore  { border-left: 3px solid #64748b; }
.card.bug    { border-left: 3px solid #ef4444; }
.card.epic   { border-left: 3px solid #0ea5e9; }
.badge.feat  { background: #eef2ff; color: #4338ca; }
.badge.infra { background: #fef3c7; color: #92400e; }
.badge.chore { background: #f1f5f9; color: #475569; }
.badge.bug   { background: #fee2e2; color: #991b1b; }
.badge.epic  { background: #e0f2fe; color: #075985; }

.card .pr {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: #dcfce7;
  color: #14532d;
  font-weight: 600;
}
.card .deferred {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: #fef3c7;
  color: #92400e;
  font-size: 10px;
  font-weight: 600;
  margin-top: 4px;
}

/* Filters */
.filters {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 16px;
}
.filters span.label { color: #6b7385; font-size: 12px; margin-right: 6px; }
.filters button {
  font: inherit;
  background: #fff;
  border: 1px solid #d4d9e3;
  border-radius: 16px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
  color: #475569;
}
.filters button.active { background: #1f2530; color: #fff; border-color: #1f2530; }
.filters button:hover { border-color: #1f2530; }

/* Dependency graph */
.mermaid-wrap {
  background: #fff;
  border: 1px solid #e2e6ee;
  border-radius: 10px;
  padding: 16px;
  overflow-x: auto;
}
.mermaid-wrap pre { margin: 0; font-size: 12px; }

footer {
  text-align: center;
  color: #6b7385;
  font-size: 12px;
  padding: 16px 0 32px;
}

/* Hidden via filter */
.card[data-hidden="1"] { display: none; }
"""


def _classify_kpi(features: list[Feature]) -> dict[str, int]:
    """Distinguish *scoped* MVP1 work (anything past the idea stage in
    feat_/infra_/chore_/epic_) from idea-only backlog items and from open
    bugs. CLAUDE.md's canonical MVP1 list has 12 entries — 8 features +
    3 infra + 1 chore (`chore_tutorial_polish` is a release-readiness gate,
    not a debt item) — so scoped chores count toward the same bucket.
    """
    kpi = {
        "scoped_features": 0,  # feat_/infra_/chore_/epic_ with at least a spec
        "done_features": 0,
        "open_bugs": 0,
        "open_chores_idea": 0,  # idea-only chore_* (debt, not MVP1 scope)
        "backlog_ideas": 0,  # idea-only feat_/infra_ (not yet scoped)
        "remaining": 0,  # scoped not-done + open bugs + open chores-idea
    }
    for f in features:
        if f.prefix in ("feat", "infra", "chore", "epic"):
            if f.stage == "idea":
                if f.prefix == "chore":
                    kpi["open_chores_idea"] += 1
                else:
                    kpi["backlog_ideas"] += 1
                continue
            kpi["scoped_features"] += 1
            if f.stage == "done":
                kpi["done_features"] += 1
        elif f.prefix == "bug":
            if f.stage != "done":
                kpi["open_bugs"] += 1
    kpi["remaining"] = (
        (kpi["scoped_features"] - kpi["done_features"]) + kpi["open_bugs"] + kpi["open_chores_idea"]
    )
    return kpi


def _card_html(f: Feature) -> str:
    spec_path = f.path / "feature_spec.md"
    target = (
        spec_path.relative_to(REPO_ROOT) if spec_path.exists() else f.path.relative_to(REPO_ROOT)
    )
    href = f"../../{target}"

    deps_html = ""
    if f.depends_on:
        chips = "".join(f'<span class="dep-chip">{html.escape(d)}</span>' for d in f.depends_on)
        deps_html = f'<div class="deps">depends on: {chips}</div>'

    pr_html = ""
    if f.pr_number:
        pr_link = f"https://github.com/SoundMindsAI/relyloop/pull/{f.pr_number}"
        pr_html = f'<a class="pr" href="{pr_link}">PR #{f.pr_number}</a>'

    merged_html = ""
    if f.merged_date:
        merged_html = f"<span>merged {html.escape(f.merged_date)}</span>"

    deferred_html = ""
    if f.deferred_phase:
        deferred_html = f'<div class="deferred">deferred: {html.escape(f.deferred_phase)}</div>'

    one_liner = (f.one_liner or f.status_line)[:200]
    return f"""
<div class="card {f.prefix}" data-prefix="{f.prefix}">
  <div class="name"><a href="{html.escape(href)}">{html.escape(f.display_name)}</a></div>
  <div class="meta">
    <span class="badge {f.prefix}">{html.escape(PREFIX_LABELS.get(f.prefix, f.prefix))}</span>
    {pr_html}{merged_html}
  </div>
  <div class="one-liner">{html.escape(one_liner)}</div>
  {deferred_html}
  {deps_html}
</div>
"""


def _column_html(stage: str, features: list[Feature]) -> str:
    cards = "\n".join(_card_html(f) for f in features)
    return f"""
<div class="col {stage}">
  <h3>{STAGE_LABELS[stage]} <span class="count">{len(features)}</span></h3>
  {cards}
</div>
"""


def _mermaid_graph(features: list[Feature]) -> str:
    """Generate a Mermaid graph showing the dependency DAG."""
    lines = ["graph LR"]
    # Style classes per stage.
    lines.append("  classDef done fill:#dcfce7,stroke:#14532d,color:#14532d;")
    lines.append("  classDef implement fill:#ffedd5,stroke:#9a3412,color:#9a3412;")
    lines.append("  classDef plan fill:#fef9c3,stroke:#854d0e,color:#854d0e;")
    lines.append("  classDef spec fill:#dbeafe,stroke:#1e40af,color:#1e40af;")
    lines.append("  classDef idea fill:#f1f5f9,stroke:#334155,color:#334155;")

    # Show every scoped MVP1 node (feat_/infra_ + scoped chore_/epic_);
    # idea-only debt items aren't part of the dependency DAG.
    scoped = {
        f.folder
        for f in features
        if f.prefix in ("feat", "infra", "chore", "epic") and f.stage != "idea"
    }
    for f in features:
        if f.folder not in scoped:
            continue
        node_id = f.folder
        label = f.short_name.replace("_", " ")
        lines.append(f'  {node_id}["{label}"]')
        lines.append(f"  class {node_id} {f.stage};")

    for f in features:
        if f.folder not in scoped:
            continue
        for dep in f.depends_on:
            if dep not in scoped:
                continue
            lines.append(f"  {dep} --> {f.folder}")

    return "\n".join(lines)


def render_html(features: list[Feature]) -> str:
    kpi = _classify_kpi(features)
    pct = (
        round(kpi["done_features"] * 100 / kpi["scoped_features"]) if kpi["scoped_features"] else 0
    )
    by_stage: dict[str, list[Feature]] = {s: [] for s in STAGES}
    for f in features:
        by_stage[f.stage].append(f)

    # Inside each stage, prioritize feat/infra over chore/bug for visual scan.
    type_order = {"feat": 0, "infra": 1, "epic": 2, "chore": 3, "bug": 4}
    for s in STAGES:
        by_stage[s].sort(key=lambda f: (type_order.get(f.prefix, 99), f.short_name))

    columns = "".join(_column_html(s, by_stage[s]) for s in STAGES)
    mermaid = _mermaid_graph(features)
    # Use the most-recent mtime of any feature-folder file (or this script
    # itself) instead of `now()` — keeps regeneration idempotent so the
    # pre-commit hook doesn't churn the dashboard on every unrelated commit.
    now = _data_freshness().strftime("%Y-%m-%d")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RelyLoop MVP1 Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>RelyLoop MVP1 Dashboard</h1>
  <div class="meta">
    Reflects feature-folder state as of {now} (latest mtime of any
    <code>docs/02_product/planned_features/</code> or
    <code>docs/00_overview/implemented_features/</code> file).
    See <a href="../../state.md">state.md</a> for the active branch context,
    <a href="../../CLAUDE.md">CLAUDE.md</a> for conventions, and
    <a href="../02_product/mvp1-user-stories.md">mvp1-user-stories.md</a>
    for the user-story narrative.
  </div>
</header>

<main>

<section>
  <h2>MVP1 Progress</h2>
  <div class="kpi-row">
    <div class="kpi {"complete" if pct == 100 else ""}">
      <div class="label">Features done</div>
      <div class="value">{kpi["done_features"]} / {kpi["scoped_features"]}</div>
      <div class="sub">{pct}% of scoped MVP1 features</div>
      <div class="bar"><span style="width:{pct}%"></span></div>
    </div>
    <div class="kpi {"warn" if kpi["remaining"] else "complete"}">
      <div class="label">Path to MVP1</div>
      <div class="value">{kpi["remaining"]}</div>
      <div class="sub">items left = features + bugs + chores</div>
    </div>
    <div class="kpi {"bug" if kpi["open_bugs"] else ""}">
      <div class="label">Open bugs</div>
      <div class="value">{kpi["open_bugs"]}</div>
      <div class="sub">tracked bug_* idea files</div>
    </div>
    <div class="kpi {"warn" if kpi["open_chores_idea"] else ""}">
      <div class="label">Open chores</div>
      <div class="value">{kpi["open_chores_idea"]}</div>
      <div class="sub">idea-stage chore_* (debt)</div>
    </div>
  </div>
  <div class="kpi-secondary">
    <span>
      <strong>Backlog ideas:</strong>
      {kpi["backlog_ideas"]} idea-only feat/infra folders (not yet scoped into MVP1)
    </span>
    <span>
      <strong>In flight:</strong>
      {len(by_stage["implement"])} feature(s) actively shipping
    </span>
  </div>
</section>

<section>
  <h2>Pipeline</h2>
  <div class="filters">
    <span class="label">Filter:</span>
    <button class="active" data-filter="all">All</button>
    <button data-filter="feat">Features</button>
    <button data-filter="infra">Infra</button>
    <button data-filter="chore">Chores</button>
    <button data-filter="bug">Bugs</button>
  </div>
  <div class="kanban">{columns}</div>
</section>

<section>
  <h2>Dependency graph (feat_ + infra_)</h2>
  <div class="mermaid-wrap">
    <div class="mermaid">{html.escape(mermaid)}</div>
    <noscript><pre>{html.escape(mermaid)}</pre></noscript>
  </div>
</section>

</main>

<footer>
  Single source of truth: the feature folder structure.
  Regenerate after any spec/plan/pipeline_status change with
  <code>make dashboard</code>.
</footer>

<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";
  mermaid.initialize({{ startOnLoad: true, theme: "default", securityLevel: "loose" }});
</script>
<script>
  // Filter chips
  document.querySelectorAll(".filters button").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".filters button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const f = btn.dataset.filter;
      document.querySelectorAll(".card").forEach(c => {{
        c.dataset.hidden = (f === "all" || c.dataset.prefix === f) ? "0" : "1";
      }});
    }});
  }});
</script>
</body>
</html>
"""


def _strip_trailing_ws(text: str) -> str:
    """Match pre-commit's trailing-whitespace hook so re-runs are idempotent."""
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


# ---------------------------------------------------------------------------
# Markdown renderer (GitHub-native view alongside the rich HTML)
# ---------------------------------------------------------------------------


def _md_escape_cell(text: str) -> str:
    """Escape characters that break GitHub markdown table cells."""
    if not text:
        return ""
    return text.replace("|", "\\|").replace("\n", " ")


def _md_link(label: str, target: Path) -> str:
    """Build a relative markdown link from the markdown output's location.

    Markdown lives at `docs/00_overview/MVP1_DASHBOARD.md`, so paths are
    computed relative to `docs/00_overview/` (using os.path.relpath which
    correctly emits `../` segments for parent traversal).
    """
    rel = os.path.relpath(target, OUTPUT_MD.parent)
    # POSIX-style separators so GitHub renders correctly on any platform.
    return f"[{label}]({Path(rel).as_posix()})"


def _md_feature_link(f: Feature) -> str:
    """Link the feature name to its primary artifact."""
    primary = f.path / "feature_spec.md"
    if not primary.exists():
        primary = f.path / "idea.md"
    if not primary.exists():
        primary = f.path
    return _md_link(f.folder, primary)


def _md_status_cell(f: Feature) -> str:
    pr_url = f"https://github.com/SoundMindsAI/relyloop/pull/{f.pr_number}"
    if f.pr_number and f.merged_date:
        return f"[PR #{f.pr_number}]({pr_url}) merged {f.merged_date}"
    if f.pr_number:
        return f"[PR #{f.pr_number}]({pr_url})"
    if f.deferred_phase:
        return f"deferred: {f.deferred_phase}"
    return _md_escape_cell(f.status_line) or "—"


def _md_deps_cell(f: Feature) -> str:
    if not f.depends_on:
        return "—"
    return " ".join(f"`{d}`" for d in f.depends_on)


def _md_stage_section(stage: str, features: list[Feature]) -> str:
    if not features:
        return f"### {STAGE_LABELS[stage]} (0)\n\n_None._\n"
    rows = ["| Feature | Type | One-liner | Depends on | Status |", "|---|---|---|---|---|"]
    for f in features:
        rows.append(
            "| "
            + " | ".join(
                [
                    _md_feature_link(f),
                    PREFIX_LABELS.get(f.prefix, f.prefix),
                    _md_escape_cell((f.one_liner or f.status_line)[:200]),
                    _md_deps_cell(f),
                    _md_status_cell(f),
                ]
            )
            + " |"
        )
    return f"### {STAGE_LABELS[stage]} ({len(features)})\n\n" + "\n".join(rows) + "\n"


def render_markdown(features: list[Feature]) -> str:
    """Render the GitHub-native dashboard view.

    Mirrors the HTML's information architecture using GitHub-native
    primitives (tables + Mermaid block) so the file renders inline when
    browsed on github.com without any preview proxy.
    """
    kpi = _classify_kpi(features)
    pct = (
        round(kpi["done_features"] * 100 / kpi["scoped_features"]) if kpi["scoped_features"] else 0
    )
    by_stage: dict[str, list[Feature]] = {s: [] for s in STAGES}
    for f in features:
        by_stage[f.stage].append(f)
    type_order = {"feat": 0, "infra": 1, "epic": 2, "chore": 3, "bug": 4}
    for s in STAGES:
        by_stage[s].sort(key=lambda f: (type_order.get(f.prefix, 99), f.short_name))

    asof = _data_freshness().strftime("%Y-%m-%d")
    mermaid = _mermaid_graph(features)

    lines: list[str] = []
    lines.append("# RelyLoop MVP1 Dashboard")
    lines.append("")
    lines.append(
        f"_Reflects feature-folder state as of **{asof}** "
        "(latest mtime of any planned/implemented feature `.md` file). "
        "Regenerated by `make dashboard` and the `mvp1-dashboard-regen` pre-commit hook. "
        "For the rich local view (filter chips, type colors), open "
        "[`mvp1_dashboard.html`](mvp1_dashboard.html) in a browser._"
    )
    lines.append("")
    lines.append("## MVP1 Progress")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(
        f"| Features done | **{kpi['done_features']} / {kpi['scoped_features']}** ({pct}%) |"
    )
    lines.append(
        f"| Path to MVP1 | **{kpi['remaining']}** items remaining (features + bugs + chores) |"
    )
    lines.append(f"| Open bugs | {kpi['open_bugs']} |")
    lines.append(f"| Open chores | {kpi['open_chores_idea']} (idea-stage debt) |")
    lines.append(
        f"| Backlog ideas | {kpi['backlog_ideas']} idea-only feat/infra "
        "(not yet scoped into MVP1) |"
    )
    lines.append(f"| In flight | {len(by_stage['implement'])} feature(s) actively shipping |")
    lines.append("")
    lines.append("## Pipeline")
    lines.append("")
    # Done first (most useful at the top), then the active stages, then idea backlog.
    for stage in ("done", "implement", "plan", "spec", "idea"):
        lines.append(_md_stage_section(stage, by_stage[stage]))
    lines.append("## Dependency graph")
    lines.append("")
    lines.append("Scoped feat/infra/chore nodes only. Idea-stage debt is omitted.")
    lines.append("")
    lines.append("```mermaid")
    lines.append(mermaid)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "Source of truth: feature folders under "
        "[`docs/02_product/planned_features/`](../02_product/planned_features/) and "
        "[`docs/00_overview/implemented_features/`](implemented_features/). "
        "See [`state.md`](../../state.md) for active-branch context and "
        "[`CLAUDE.md`](../../CLAUDE.md) for conventions."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    features = load_all()
    output_html = _strip_trailing_ws(render_html(features))
    OUTPUT_HTML.write_text(output_html, encoding="utf-8")
    output_md = _strip_trailing_ws(render_markdown(features))
    OUTPUT_MD.write_text(output_md, encoding="utf-8")
    print(
        f"wrote {OUTPUT_HTML.relative_to(REPO_ROOT)} + "
        f"{OUTPUT_MD.relative_to(REPO_ROOT)} ({len(features)} features)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
