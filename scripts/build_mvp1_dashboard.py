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
DASHBOARD_DIR = REPO_ROOT / "docs/00_overview"

# Per-release dashboard outputs are keyed by lowercase release tag
# (``mvp1``, ``mvp2``, ``mvp3``, ...). The classifier in
# :func:`_target_release` routes each feature to exactly one release,
# and the renderer emits one ``<TAG>_DASHBOARD.md`` + ``<tag>_dashboard.html``
# pair per release that has at least one item. New releases auto-appear
# the moment a feature folder uses the ``_mvpN`` suffix (or a feature
# spec's status line names ``Held for MVPN``).
DEFAULT_RELEASE = "mvp1"
"""Features without an explicit release tag default to MVP1 (the active scope)."""

# Roadmap matrix — every release the project plans to ship through GA v1+, in
# canonical order. Sourced from `docs/01_architecture/tech-stack.md` §"Canonical
# release matrix" (the single source of truth per CLAUDE.md). Rendered as the
# rows of the top-level roadmap dashboard; releases with no tagged features
# still appear (as "Not yet scoped") so the roadmap shows runway.
#
# Each tuple is (release_tag, display_label, one-liner theme). The release_tag
# matches the `_mvpN` suffix convention used by the per-folder classifier;
# post-MVP4 releases (`ga`, `v2`) are reserved tags that the classifier can
# extend to support when post-MVP4 features start being tagged.
ROADMAP_RELEASES: list[tuple[str, str, str]] = [
    ("mvp1", "MVP1 / v0.1", "The Loop"),
    ("mvp1.5", "MVP1.5 / v0.1.5", "Real Signals"),
    ("mvp2", "MVP2 / v0.2", "Observable"),
    ("mvp3", "MVP3 / v0.3", "Production Stacks"),
    ("mvp4", "MVP4 / v0.4", "Multi-tenant, Multi-LLM"),
    ("ga", "GA v1 / v1.0", "Production-ready"),
    ("v2", "v2+", "post-GA"),
]

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


PRIORITY_VALUES: tuple[str, ...] = ("P0", "P1", "P2", "Backlog")
"""Operator-curated priority tiers parsed from the idea-template's
``**Priority:**`` line. P0 = do next; P1 = high-value scoped, ready to
execute when P0 clears; P2 = important enough to file, not blocking
(default when omitted); Backlog = captured for record, not actively
planned. Folders ending ``_mvpN`` are auto-classified to that release
independent of this value."""

_PRIORITY_ORDER: dict[str, int] = {p: i for i, p in enumerate(PRIORITY_VALUES)}
"""Sort key — lower number = higher priority. Done features sort to the
back regardless of priority (see ``_dashboard_sort_key``)."""

DEFAULT_PRIORITY = "P2"


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
    release: str = DEFAULT_RELEASE  # "mvp1" | "mvp2" | "mvp3" | ...
    priority: str = DEFAULT_PRIORITY  # one of PRIORITY_VALUES

    @property
    def display_name(self) -> str:
        # Strip a trailing _mvpN or _mvpN_M tag from the visible label so
        # the release suffix doesn't double-print on the dashboard card.
        # The release tag is already conveyed by which dashboard the card
        # appears on. Pattern matches both integer (`_mvp2`) and half-step
        # (`_mvp1_5`) forms.
        name = re.sub(r"_mvp\d+(?:_\d+)?$", "", self.short_name)
        return name.replace("_", " ").title()


_RELEASE_SUFFIX_RE = re.compile(r"_mvp(\d+(?:_\d+)?)$")
"""Match ``..._mvp2`` / ``..._mvp3`` / ``..._mvp1_5`` at the END of a folder
short-name. The half-step form (``_mvp1_5``) uses underscore-instead-of-dot
because folder names can't have dots — the classifier normalizes ``"1_5"``
→ ``"1.5"`` before building the release string."""

_RELEASE_STATUS_RE = re.compile(
    r"(?:Held\s+for|anchor\s+(?:feature\s+)?for)\s+MVP\s*(\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)
"""Match the release tag in an idea/spec status line. Two prose framings:

* ``**Status:** Held for MVP2 (decided 2026-05-13)`` — the original deferral
  form (e.g. ``bug_chat_long_conversation_truncation_mvp2``).
* ``**Status:** Idea — anchor feature for MVP1.5 / v0.1.5 "Real Signals"`` —
  the half-step / anchor framing (e.g. ``feat_ubi_judgments``).

Capture group is the version number; supports integer (``"2"``) and decimal
(``"1.5"``) forms."""


def _target_release(short_name: str, status_line: str) -> str:
    """Classify a feature's target release tag.

    Two signals, suffix wins over status:

    1. Folder ``_mvpN`` or ``_mvpN_M`` suffix on ``short_name`` (e.g.,
       ``arq_subprocess_test_mvp2`` → ``mvp2``; ``foo_mvp1_5`` →
       ``mvp1.5``). This is the canonical per-folder hold marker — same
       precedent the ``bug_chat_long_conversation_truncation_mvp2`` rename
       established (state.md 2026-05-13). Half-step folders use
       underscore-instead-of-dot since folder names can't have dots.
    2. ``**Status:** Held for MVPN`` / ``anchor feature for MVPN.M`` line
       in the idea/spec body. Recognizes both integer and decimal
       release tags.

    Falls back to :data:`DEFAULT_RELEASE` (``"mvp1"``) when no signal
    fires. Implemented features always carry their shipped release in
    git history; for dashboard purposes they belong to the release whose
    folder name they live under (suffix-detected first), or MVP1 if
    they shipped before the per-release tagging convention.
    """
    m = _RELEASE_SUFFIX_RE.search(short_name)
    if m:
        # Normalize underscore-form half-step (``"1_5"``) → dot-form
        # (``"1.5"``) so the internal release identifier matches the
        # status-line capture form. Integer suffixes pass through.
        return f"mvp{m.group(1).replace('_', '.')}"
    m2 = _RELEASE_STATUS_RE.search(status_line or "")
    if m2:
        return f"mvp{m2.group(1)}"
    return DEFAULT_RELEASE


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


def _extract_priority(text: str) -> str | None:
    """Pull the `**Priority:**` value (P0 / P1 / P2 / Backlog) from a
    markdown header block. Returns ``None`` when the field is absent
    (so callers can fall through to a different artifact); returns
    :data:`DEFAULT_PRIORITY` only when the field is present but its
    value is unrecognized (e.g., the chevron-placeholder
    ``<P0 | P1 | ...>`` in the template file itself).
    """
    # Match the full line, then explicitly skip the template's chevron
    # placeholder (`<P0 | P1 | P2 | Backlog — …>`). The earlier
    # `[^\n<]+?` form excluded any priority description that legitimately
    # contained a `<` (e.g., "P1 < 2 weeks effort") — Gemini Code Assist
    # PR #183 review finding #2 fix.
    m = re.search(r"^\*\*Priority:\*\*\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if not m or "<P0" in m.group(1):
        return None
    raw = m.group(1).strip()
    # Tolerate "P0 — do next" and similar embellishments by taking the
    # first whitespace-delimited token. Case-insensitive for the Px
    # tiers so an idea authored with lowercase `p0` doesn't silently
    # fall through to the default (Gemini Code Assist PR #183 review
    # finding #1 fix).
    token = raw.split()[0] if raw else ""
    if token.upper() in ("P0", "P1", "P2"):
        return token.upper()
    # Common alternatives.
    if token.lower() in ("backlog", "icebox", "deferred"):
        return "Backlog"
    return DEFAULT_PRIORITY


_DASHBOARD_OVERRIDES_DIR = (
    Path(__file__).resolve().parent.parent / "docs/00_overview/dashboard_overrides"
)
"""Sidecar directory for one-liner overrides.

Lives OUTSIDE ``docs/00_overview/implemented_features/`` so the
"implemented-features folders are frozen historical artifacts" rule
(infra_ir_measures_migration feature_spec.md §2) is preserved. Each
override file is named ``<feature_slug>.md`` matching the implemented-
feature folder's slug (e.g., the row for the implemented
``2026_05_10_infra_optuna_eval`` folder is overridden by
``infra_optuna_eval.md`` in this directory).
"""


def _extract_one_liner(text: str, source_dir: Path | None = None) -> str:
    """Best-effort: prefer override sidecar, then Outcome, then Problem.

    Override sidecar (added by infra_ir_measures_migration Story 1.8): when
    ``docs/00_overview/dashboard_overrides/<feature_slug>.md`` exists, its
    contents override the spec-extracted one-liner. This lets us keep frozen
    historical specs frozen while still keeping the current-state dashboard
    accurate when a sibling feature invalidates a historical row's
    description — e.g., when a library swap in one feature changes what an
    earlier feature's code does today, but the earlier feature's spec
    correctly describes what shipped at the time. The override files live
    OUTSIDE ``implemented_features/`` so the frozen-artifact rule is
    preserved (the historical feature_spec.md is untouched; only the
    dashboard's summary cell is overridden).

    When ``source_dir`` is supplied, any relative markdown link in the
    extracted sentence is rewritten so it resolves correctly from the
    dashboard files' directory. See :func:`_rewrite_markdown_links`.
    """
    if source_dir is not None:
        # Derive feature slug from source_dir basename.
        # For implemented features, the basename looks like
        # "<YYYY_MM_DD>_<slug>" — we strip the date prefix to get the slug.
        # For planned features the basename IS the slug.
        slug = source_dir.name
        date_prefix = re.match(r"^\d{4}_\d{2}_\d{2}_", slug)
        if date_prefix:
            slug = slug[len(date_prefix.group(0)) :]
        override_path = _DASHBOARD_OVERRIDES_DIR / f"{slug}.md"
        if override_path.exists():
            line = override_path.read_text().strip()
            if line:
                sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0]
                return _rewrite_markdown_links(sentence, source_dir, _DASHBOARD_DIR)
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
            if source_dir is not None:
                sentence = _rewrite_markdown_links(sentence, source_dir, _DASHBOARD_DIR)
            return sentence
    return ""


def _strip_unclosed_markdown(text: str) -> str:
    """Walk back to a position where [/]/(/) brackets and `-spans are balanced.

    Drops trailing tokens (word at a time) until the result has matched
    pairs. Returns "" if no balanced prefix exists. Used after a length
    truncation to avoid emitting "[label" or "[label](url" or "`code".
    """
    while text and (
        text.count("[") != text.count("]")
        or text.count("(") != text.count(")")
        or text.count("`") % 2 != 0
    ):
        last_space = text.rfind(" ")
        if last_space <= 0:
            return ""
        text = text[:last_space].rstrip()
    return text


def _safe_truncate_markdown(text: str, max_len: int) -> str:
    """Truncate ``text`` to ≤ ``max_len`` chars, markdown-aware.

    Preference order for the cut point:
      1. Sentence boundary (``. ``, ``! ``, ``? ``) within the last 50 chars.
      2. Word boundary (last space) in the remaining window.
      3. Hard cut at max_len-1 (last-resort; only when input has no spaces).

    Then strip any unclosed markdown link / code-span via
    :func:`_strip_unclosed_markdown` and append a single-char ellipsis (``…``).
    """
    if len(text) <= max_len:
        return text
    budget = max_len - 1  # 1 char reserved for the ellipsis
    candidate = text[:budget]
    window_start = max(0, len(candidate) - 50)
    last_sentence = max(candidate.rfind(s, window_start) for s in (". ", "! ", "? "))
    if last_sentence >= window_start:
        candidate = candidate[: last_sentence + 1]
    else:
        last_space = candidate.rfind(" ")
        if last_space > 0:
            candidate = candidate[:last_space]
    candidate = _strip_unclosed_markdown(candidate)
    return candidate.rstrip() + "…"


_DASHBOARD_DIR = DASHBOARD_DIR
"""Directory the rendered dashboards live in.

Used by :func:`_rewrite_markdown_links` to recompute relative paths in
extracted one-liner text from each feature folder's perspective into the
dashboard's perspective. All ``<release>_dashboard.html`` and
``<RELEASE>_DASHBOARD.md`` pairs live under ``docs/00_overview/``, so a
single directory anchor covers every release.
"""

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
"""Match markdown links of the form ``[label](path)``. Captures label + raw path."""


def _rewrite_markdown_links(text: str, from_dir: Path, to_dir: Path) -> str:
    """Rewrite relative markdown link paths to be valid when ``text`` is moved.

    When a feature's idea.md / feature_spec.md one-liner is extracted and
    embedded into the dashboard files, any relative path inside a markdown
    link breaks: the source file lives at depth 4 (``docs/02_product/
    planned_features/<folder>/idea.md``), but the dashboard files live at
    depth 2 (``docs/00_overview/MVP1_DASHBOARD.md``). A path like
    ``../../../../backend/foo`` correctly resolves to ``<repo>/backend/foo``
    from the source, but resolves to ``../../backend/foo`` (outside the
    repo) when embedded in the dashboard.

    This helper recomputes each relative path. Absolute paths (``/foo``),
    full URLs (``http://...``), in-document anchors (``#section``), and
    ``mailto:`` links pass through unchanged. Fragments (``#L42``) are
    preserved on the rewritten side.

    Surfaced by Gemini Code Assist on PR #106 (broken
    ``backend/tests/integration/...`` links in
    ``MVP1_DASHBOARD.md:91`` + ``mvp1_dashboard.html:479``); tracked as
    option A in ``infra_dashboard_regen_pre_commit_conflict/idea.md`` §4.
    """

    def fix_one(match: re.Match[str]) -> str:
        label = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith(("/", "http://", "https://", "#", "mailto:")):
            return match.group(0)
        # Preserve the fragment (e.g., `#L42`) across rewriting.
        path_part, _sep, fragment = raw.partition("#")
        try:
            target = (from_dir / path_part).resolve()
            # POSIX-style separators so GitHub renders correctly on any
            # platform — matches the convention used by `_md_link` below.
            new_path = Path(os.path.relpath(target, to_dir)).as_posix()
        except (ValueError, OSError):
            return match.group(0)
        suffix = f"#{fragment}" if fragment else ""
        return f"[{label}]({new_path}{suffix})"

    return _MD_LINK_RE.sub(fix_one, text)


def _extract_idea_problem(text: str, idea_dir: Path | None = None) -> str:
    """Pull the first paragraph under the `## Problem` heading.

    When ``idea_dir`` is supplied, any relative markdown link in the
    extracted paragraph is rewritten so it resolves correctly from the
    dashboard files' directory (``docs/00_overview/``). See
    :func:`_rewrite_markdown_links`.
    """
    m = re.search(r"^##\s+Problem\s*$", text, flags=re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end() :]
    # First non-empty paragraph.
    para = next((p for p in rest.split("\n\n") if p.strip()), "")
    para = re.sub(r"\s+", " ", para).strip()
    if idea_dir is not None:
        para = _rewrite_markdown_links(para, idea_dir, _DASHBOARD_DIR)
    return _safe_truncate_markdown(para, 240)


_TRANSITIVE_DEP_PHRASES = (
    "all prior backend features",
    "all prior mvp1 features",
    "all backend",
    "all prior features",
)
"""Prose phrases that resolve to "depends on every sibling feature".

Per :doc:`.claude/skills/pipeline/SKILL.md` "Project-wide status mode":
treat these as a transitive dependency on every other feature whose
folder name starts with ``infra_`` or ``feat_``. Used by feat_chat_agent
("ALL prior backend features") and chore_tutorial_polish ("ALL prior
MVP1 features") — these features genuinely depend on every backend
feature shipping first.

Sentinel values rather than folder names; the caller resolves them
against the live planned/implemented feature set.
"""

DEPS_ALL_BACKEND = "__ALL_BACKEND__"


def _extract_depends_on(text: str) -> list[str]:
    """Parse `- Depends on: ...` line into a list of folder names.

    Recognizes both:
    * Explicit `[`folder`]` references (the common case).
    * Prose phrases like "ALL prior backend features" → returns the
      sentinel :data:`DEPS_ALL_BACKEND` for the loader to expand against
      the live feature set (matches the algorithm in
      :doc:`.claude/skills/pipeline/SKILL.md`).
    """
    m = re.search(r"^-\s+Depends on:\s*(.+)$", text, flags=re.MULTILINE)
    if not m:
        return []
    line = m.group(1)
    line_lower = line.lower()
    # Backticked folder names (must contain underscore + recognized prefix).
    folders = re.findall(r"`([a-z0-9_]+)`", line)
    folders = [f for f in folders if any(f.startswith(p + "_") for p in PREFIX_LABELS)]
    # Transitive-prose marker → sentinel; the loader expands later.
    if any(phrase in line_lower for phrase in _TRANSITIVE_DEP_PHRASES):
        folders.append(DEPS_ALL_BACKEND)
    return folders


_DEP_ROW_RE = re.compile(
    r"^\s*\|.*\b(?:Implemented|Depends on|Depended)\b.*\|.*$",
    flags=re.MULTILINE | re.IGNORECASE,
)


def _strip_dependency_table_rows(text: str) -> str:
    """Drop markdown-table rows whose first column names a dependency.

    Plans cite dependency PR numbers (e.g. ``Implemented (PR #18, #25)``)
    in their Dependencies / Risks tables. Those numbers belong to OTHER
    features and must not be mistaken for this feature's own PR by the
    fallback search.
    """
    return _DEP_ROW_RE.sub("", text)


# Narrative dependency-cite footnotes (single-line form). Catches the
# `**Depends on:** ... PR #N` / `- Depends on: ... PR #N` /
# `**Dependencies:** ... PR #N` patterns that the table-row strip above
# does NOT cover. Per chore_dashboard_regen_priority4_dependency_cite_false_positive
# — without this, priority-4's last-resort `#N` fallback picks up the
# first dependency PR# as the feature's own.
_DEP_FOOTNOTE_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*)?"
    r"(?:Depends on|Dependencies|Dependency|Depended on)"
    r"(?:\*\*)?:\s*[^\n]*$",
    flags=re.MULTILINE | re.IGNORECASE,
)


def _strip_dependency_footnote_lines(text: str) -> str:
    """Drop single-line narrative dependency-cite footnotes.

    Sibling to :func:`_strip_dependency_table_rows`. The table-row strip
    only handles markdown-table rows (lines starting with ``|``); this
    helper handles the inline-footnote shapes commonly used in idea
    bodies and feature specs:

    * ``**Depends on:** foo PR #208 + bar PR #221``
    * ``- Depends on: foo PR #N`` (bullet list)
    * ``**Dependencies:** foo PR #N`` (plural form)
    * ``Depended on: foo PR #N`` (past tense, rarer)

    Composes with :func:`_strip_dependency_table_rows` and
    :func:`_strip_backtick_quoted_segments` at :func:`_extract_pr_number`'s
    priority-3/4 entry point.
    """
    return _DEP_FOOTNOTE_RE.sub("", text)


def _strip_backtick_quoted_segments(text: str) -> str:
    """Remove backtick-fenced segments before fuzzy PR# matching.

    Strips three fence flavors in one pass: multi-line triple-backtick
    blocks (```...``` spanning newlines), single-line triple-backtick
    fences (```...``` on one line), and empty fences (``````). A second
    pass strips inline backtick spans (`...`, including the empty span
    `` per spec AC-11).

    The 3-or-more backtick quantifier (per spec FR-1) accommodates
    markdown's 4+ backtick convention for embedding 3-backtick blocks.

    Composes with _strip_dependency_table_rows in _extract_pr_number's
    priority-3 path (see chore_dashboard_regen_quoted_pr_false_positive
    spec FR-2). Without this strip, quoted PR-merge phrases like
    ``merged via PR #4`` in spec narrative would false-positively match
    the priority-3 fuzzy regex and return another feature's PR# as
    this feature's own.
    """
    # Pass A: triple-backtick fences (multi-line, single-line, empty).
    # Backreference enforces same-width close so a 4-backtick outer fence
    # containing an inner 3-backtick block is stripped as ONE outer unit
    # (the inner 3-fence doesn't match \1's captured 4-backticks).
    text = re.sub(r"(`{3,}).*?\1", "", text, flags=re.DOTALL)
    # Pass B: inline backtick spans of width 1 or 2, with same-width backref close.
    # Width-2 (`` ``foo`` ``) is rare in markdown but appears when a span needs to
    # contain a literal single backtick. Width-1 covers the common `foo` case and
    # the empty `` `` (group 1 = 1 backtick, `[^\n]*?` matches 0 chars, `\1` matches
    # the second backtick). Caught by Gemini Code Assist review on PR #253.
    text = re.sub(r"(`{1,2})[^\n]*?\1", "", text)
    return text


# Spec FR-2 Pattern A — own-PR shipped status with optional markdown link.
# Each \b is immediately after a \d+ capture (digit↔non-digit transition);
# placing \b after `]` or `)` would fail because both are non-word characters.
_IDEA_STATUS_SHIPPED_RE = re.compile(
    r"^\*\*Status:\*\*\s+\*\*Shipped\*\*\s+as\s+PR\s*"
    r"(?:\[#(\d+)\b\]\([^)]*\)|\[#(\d+)\b\]|#(\d+)\b)",
    re.MULTILINE,
)

# Spec FR-2 Pattern B — own-PR implemented status. Markdown-link alternation
# matches Pattern A for symmetry — purely additive, never reduces matches.
_IDEA_STATUS_IMPLEMENTED_RE = re.compile(
    r"^\*\*Status:\*\*\s+\*\*Implemented\s*[—\-]\s*PR\s*"
    r"(?:\[#(\d+)\b\]\([^)]*\)|\[#(\d+)\b\]|#(\d+)\b)",
    re.MULTILINE,
)

# Spec FR-2 Pattern C — own-PR inline shipped dateline at line start.
# Leading ^ is load-bearing: prevents matching dependency cites such as
# `Depends on chore_X (**shipped 2026-05-21 as PR #N**)`.
# Markdown-link alternation matches Pattern A for symmetry.
_IDEA_SHIPPED_DATELINE_RE = re.compile(
    r"^\*\*shipped\s+\d{4}-\d{2}-\d{2}\s+as\s+PR\s*"
    r"(?:\[#(\d+)\b\]\([^)]*\)|\[#(\d+)\b\]|#(\d+)\b)",
    re.MULTILINE,
)

# Spec FR-3 — `**PR:**` frontmatter pattern, applied only to the bounded
# metadata block (see _extract_metadata_block).
_IDEA_PR_FRONTMATTER_RE = re.compile(r"^\*\*PR:\*\*\s+#(\d+)\b", re.MULTILINE)

# Spec FR-3 — metadata-key pattern matching `**Date:**`, `**Status:**`, etc.
# Used by _extract_metadata_block to identify contiguous metadata lines.
_METADATA_KEY_RE = re.compile(r"^\*\*[A-Z][a-zA-Z ]+:\*\*")


def _extract_metadata_block(idea: str) -> str:
    """Return the bounded metadata block at the top of an idea body.

    Per spec FR-3 (chore_dashboard_pr_extraction_from_idea): the block is
    the contiguous prefix of ``idea`` that contains the title line
    (allowed ONLY as the first non-blank line), blank lines, and
    metadata-key lines (e.g., ``**Date:**``, ``**Status:**``,
    ``**Priority:**``, ``**PR:**``). Scanning stops at either (a) a
    ``## `` heading line, OR (b) a non-blank line that is neither the
    initial title nor a metadata-key match. A 30-line ceiling caps
    headingless edge cases.

    The ``title_seen`` flag ensures only the FIRST ``# `` line counts
    as the title — a later ``# `` line in the same idea would be a
    non-metadata body heading and stops the block.

    This is the search scope for the `**PR:**` frontmatter convention
    (spec priority 3.6) — it prevents body-section ``**PR:**``
    references (e.g., inside ``## Related``) from being misread as this
    feature's own PR.
    """
    lines = idea.splitlines()
    cap = min(len(lines), 30)
    nonblank_seen = False
    for idx in range(cap):
        line = lines[idx]
        if line.startswith("## "):
            return "\n".join(lines[:idx])
        stripped = line.strip()
        if not stripped:
            continue
        # The title line is allowed ONLY as the FIRST non-blank line.
        # If any non-blank line (metadata or otherwise) has already been
        # seen, a subsequent `# ` is a body heading and stops the block.
        # GPT-5.5 final review caught the case where metadata-key lines
        # come first and a later `# ` was mistakenly treated as title.
        if stripped.startswith("# ") and not nonblank_seen:
            nonblank_seen = True
            continue
        nonblank_seen = True
        # Anything else that's not a metadata key ends the block.
        if not _METADATA_KEY_RE.match(stripped):
            return "\n".join(lines[:idx])
    return "\n".join(lines[:cap])


def _extract_pr_number(pipe: str, plan: str, spec: str, idea: str = "") -> int | None:
    """Find this feature's PR number, not dependency cites.

    Priority order:
    1. The `## Implement` section of pipeline_status.md — most authoritative
       for shipped features. Accepts both `PR #N` and `[#N]` markdown-link
       formats.
    2. The plan's `**Status:**` header (catches in-flight features).
    3. A `merged`-context match across pipe + plan + spec (catches features
       described in narrative form elsewhere). Backtick-fenced segments
       (multi-line ```...```, single-line ```...```, inline `...`) are
       stripped via _strip_backtick_quoted_segments BEFORE dependency-table
       rows, so quoted PR-merge phrases in spec narrative don't leak through
       either. PR numbers cited as "Implemented (PR #N)" in a Dependencies
       table row are stripped second so they likewise don't leak through.
    3.5. Strict line-anchored idea-body patterns (own-PR assertions: Pattern
       A `**Status:** **Shipped** as PR #N`, Pattern B
       `**Status:** **Implemented — PR #N`, Pattern C line-start
       `**shipped YYYY-MM-DD as PR #N**`). Line-anchoring prevents false
       positives from dependency cites embedded in narrative or table rows.
    3.6. `**PR:**` frontmatter in the bounded metadata block — explicit
       escape hatch for legacy idea-only features that don't fit the
       natural Status patterns. Body-section ``**PR:**`` references do
       NOT match.
    4. First `#N` reference outside any dependency-table row in
       pipe + plan + spec, as a last-resort fallback.

    Priorities 3.5 and 3.6 added by ``chore_dashboard_pr_extraction_from_idea``
    (2026-05-23) so legacy implemented features that have ONLY an
    ``idea.md`` artifact (no spec / plan / pipeline_status) get their PR#
    surfaced in the regenerated dashboard.
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
    # 3 + 4 (split: 3 here, 4 at the end). Strip dependency-table rows
    # before fuzzy matching so cites like ``| feat_study_lifecycle Phase 1
    # | All stories | Implemented (PR #18, #25) | …`` don't masquerade as
    # this feature's PR.
    combined = _strip_dependency_footnote_lines(
        _strip_dependency_table_rows(
            _strip_backtick_quoted_segments(pipe + "\n" + plan + "\n" + spec)
        )
    )
    m = re.search(r"PR[^a-zA-Z\n]{0,5}#(\d+)[^.\n]{0,80}merged", combined)
    if m:
        return int(m.group(1))
    m = re.search(r"merged[^.\n]{0,80}PR[^a-zA-Z\n]{0,5}#(\d+)", combined)
    if m:
        return int(m.group(1))
    # 3.5. Strict idea-body patterns (own-PR assertions).
    # Per spec FR-2: each pattern is line-anchored to prevent dependency-cite
    # false positives. Order matters: A → B → C, first match wins.
    for pattern in (
        _IDEA_STATUS_SHIPPED_RE,
        _IDEA_STATUS_IMPLEMENTED_RE,
        _IDEA_SHIPPED_DATELINE_RE,
    ):
        match = pattern.search(idea)
        if match:
            # Pattern A has 3 alternation groups; exactly one is non-empty.
            for group in match.groups():
                if group:
                    return int(group)
    # 3.6. `**PR:**` frontmatter fallback, scoped to the bounded metadata block.
    # Per spec FR-3: prevents body-section **PR:** narrative references from
    # matching.
    frontmatter_match = _IDEA_PR_FRONTMATTER_RE.search(_extract_metadata_block(idea))
    if frontmatter_match:
        return int(frontmatter_match.group(1))
    # 4. Last-resort fallback.
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
    one_liner = (
        _extract_one_liner(spec, source_dir=folder_path)
        if spec
        else _extract_idea_problem(idea, idea_dir=folder_path)
    )

    # Priority is most informative on the idea (operator authors it at
    # capture time); spec/plan inherit by default. Walk the artifacts in
    # most-authoritative-first order: a spec/plan that explicitly
    # restates the priority wins over the idea (operator may have
    # re-scored during planning). When no artifact carries the field,
    # fall back to DEFAULT_PRIORITY at the end so the dashboard never
    # sees None.
    priority = (
        _extract_priority(spec)
        or _extract_priority(plan)
        or _extract_priority(idea)
        or DEFAULT_PRIORITY
    )

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
        pr_number=_extract_pr_number(pipe, plan, spec, idea),
        merged_date=_extract_merged_date(pipe + plan + spec),
        deferred_phase=deferred,
        # Release classifier reads ONLY the parsed status_line, not the full
        # idea body — body prose may quote release-tag phrases as documentation
        # examples (e.g. `bug_dashboard_classifier_half_step_releases` cites
        # "anchor feature for MVP1.5" in its design doc), which would
        # incorrectly classify the bug folder as an MVP1.5 feature. The
        # status_line is operator-curated and intentional; body prose isn't.
        release=_target_release(short, status_line),
        priority=priority,
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
    idea = _read(folder_path / "idea.md")

    # One-liner: prefer spec; fall back to idea.md's Problem block for
    # legacy idea-only folders. Symmetric with _load_planned per Gemini
    # PR #221 finding #3.
    one_liner = (
        _extract_one_liner(spec, source_dir=folder_path)
        if spec
        else _extract_idea_problem(idea, idea_dir=folder_path)
    )
    pr = _extract_pr_number(pipe, plan, spec, idea)
    merged = _extract_merged_date(pipe + plan + spec)

    # Date prefix from the folder is the canonical merged date.
    m = re.match(r"^(\d{4})_(\d{2})_(\d{2})_", folder)
    if m and not merged:
        merged = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    status_line = _extract_status_line(pipe + plan + spec) or "Complete"
    return Feature(
        folder=short_with_prefix,
        prefix=prefix,
        short_name=short,
        path=folder_path,
        location="implemented",
        stage="done",
        status_line=status_line,
        one_liner=one_liner,
        depends_on=_extract_depends_on(spec),
        pr_number=pr,
        merged_date=merged,
        release=_target_release(short, status_line),
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


def _merge_order_key(f: Feature) -> tuple[str, int, str]:
    """Sort key approximating merge order across the feature set.

    Used by :func:`_expand_transitive_deps` to scope a shipped feature's
    ``DEPS_ALL_BACKEND`` expansion to peers that merged on or before it
    (bug_dashboard_depends_on_column_bloat). Tuple components:

    1. ``merged_date`` (YYYY-MM-DD lexicographic) — primary order.
       Planned features (no merge date) sort to "9999-99-99", placing
       them strictly after every shipped feature.
    2. ``pr_number`` — same-day tiebreaker. Missing PR# sorts last
       within the date.
    3. ``folder`` — final stable tiebreaker (rare path).
    """
    return (
        f.merged_date or "9999-99-99",
        f.pr_number if f.pr_number is not None else 999_999,
        f.folder,
    )


def _expand_transitive_deps(features: list[Feature]) -> None:
    """Expand each feature's ``DEPS_ALL_BACKEND`` sentinel in place.

    For SHIPPED features (those with a ``merged_date``), the expansion
    is filtered to backend peers whose merge order is strictly less
    than this feature's — i.e., everything actually merged before it.
    This is the bug_dashboard_depends_on_column_bloat fix: under the
    prior implementation, ``feat_chat_agent`` (shipped 2026-05-12)
    inherited today's full backend roster, including features that
    shipped weeks later and planned ideas not yet specced. A shipped
    feature can't depend on something that didn't exist yet.

    For PLANNED features that use the transitive marker (defensive —
    none today), the expansion remains the current full snapshot,
    since a planned feature genuinely depends on every backend sibling
    in the queue.
    """
    backend = [f for f in features if f.prefix in ("infra", "feat")]
    for f in features:
        if DEPS_ALL_BACKEND not in f.depends_on:
            continue
        explicit = [d for d in f.depends_on if d != DEPS_ALL_BACKEND]
        if f.merged_date is not None:
            self_key = _merge_order_key(f)
            scoped = {g.folder for g in backend if _merge_order_key(g) < self_key}
        else:
            scoped = {g.folder for g in backend}
        # Self-deps don't make sense; drop f.folder if it slipped in via
        # either the explicit list or the sentinel expansion.
        f.depends_on = sorted((set(explicit) | scoped) - {f.folder})


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
    # Expand the DEPS_ALL_BACKEND sentinel against the live feature set
    # (per the pipeline-skill algorithm). Resolved AFTER both planned +
    # implemented are loaded so transitive deps see every backend
    # sibling regardless of which folder they live in. Time-ordered for
    # shipped features (bug_dashboard_depends_on_column_bloat).
    _expand_transitive_deps(features)
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

/* "Next up" callout — top-of-page recommendation. */
.next-up {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #fff;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 24px;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.18);
}
.next-up .eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.8);
  margin-bottom: 6px;
}
.next-up .title {
  font-size: 22px;
  font-weight: 600;
  margin-bottom: 4px;
}
.next-up .title a { color: #fff; text-decoration: none; }
.next-up .title a:hover { text-decoration: underline; }
.next-up .one-liner {
  color: rgba(255, 255, 255, 0.92);
  font-size: 13px;
  margin-bottom: 12px;
  max-width: 900px;
}
.next-up .stage-hint {
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
  margin-bottom: 8px;
}
.next-up .cmd {
  display: block;
  background: rgba(0, 0, 0, 0.25);
  color: #fff;
  border-radius: 6px;
  padding: 10px 14px;
  font: 13px/1.4 ui-monospace, "SF Mono", Menlo, monospace;
  user-select: all;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.next-up.done {
  background: linear-gradient(135deg, #15803d 0%, #14b8a6 100%);
  box-shadow: 0 4px 12px rgba(20, 184, 166, 0.2);
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
/* Priority chip — color-coded so P0 jumps out on visual scan. */
.badge.priority[data-priority="P0"] {
  background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5;
}
.badge.priority[data-priority="P1"] {
  background: #fed7aa; color: #9a3412; border: 1px solid #fdba74;
}
.badge.priority[data-priority="P2"] {
  background: #e0f2fe; color: #075985; border: 1px solid #bae6fd;
}
.badge.priority[data-priority="Backlog"] {
  background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1;
}

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

/* Back-to-roadmap link at the top of per-release dashboards. */
.back-link {
  font-size: 12px;
  margin-bottom: 6px;
}
.back-link a {
  color: #4f46e5;
  text-decoration: none;
}
.back-link a:hover { text-decoration: underline; }

/* Roadmap roll-up rows */
.roadmap-row {
  background: #fff;
  border: 1px solid #e2e6ee;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 10px;
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(220px, 2fr) auto auto;
  align-items: center;
  gap: 16px;
}
.roadmap-row .release-name {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.roadmap-row .release-name a { color: inherit; text-decoration: none; }
.roadmap-row .release-name a:hover { text-decoration: underline; }
.roadmap-row .theme {
  color: #4b5360;
  font-size: 13px;
}
.roadmap-row .progress {
  color: #5b6477;
  font-size: 13px;
  text-align: right;
  white-space: nowrap;
}
.roadmap-row .state-pill {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.state-pill.complete   { background: #dcfce7; color: #14532d; }
.state-pill.in_progress { background: #ffedd5; color: #9a3412; }
.state-pill.queued     { background: #fef3c7; color: #92400e; }
.state-pill.unscoped   { background: #f1f5f9; color: #475569; }
"""


def _priority_order(features: list[Feature]) -> list[Feature]:
    """Return scoped MVP1 features in dependency-derived priority order.

    Topological sort over the ``depends_on`` DAG. Tiebreaker among
    same-tier features mirrors the kanban sort (feat → infra → epic →
    chore, then alphabetical). Idea-stage backlog and bug_* items are
    excluded — they're not part of the dependency DAG.

    Mirrors the algorithm in :doc:`.claude/skills/pipeline/SKILL.md`
    "Project-wide status mode" so the dashboard's "Next up" callout
    converges on the same answer ``/pipeline status`` would give.
    """
    type_order = {"feat": 0, "infra": 1, "epic": 2, "chore": 3}
    scoped = {
        f.folder: f
        for f in features
        if f.prefix in ("feat", "infra", "epic", "chore") and f.stage != "idea"
    }
    # Edges: dep -> [features that depend on dep]. Ignore deps outside the
    # scoped set (idea-only ancestors, retired features).
    incoming: dict[str, set[str]] = {name: set() for name in scoped}
    for name, f in scoped.items():
        for dep in f.depends_on:
            if dep in scoped:
                incoming[name].add(dep)

    ordered: list[Feature] = []
    placed: set[str] = set()
    # Kahn's: repeatedly pull all roots (features whose unmet-dep set is
    # empty), sort by tiebreaker, append, remove from incoming sets.
    while len(placed) < len(scoped):
        ready = [
            scoped[name] for name, deps in incoming.items() if name not in placed and deps <= placed
        ]
        if not ready:
            # Cycle in the dep DAG — pull remaining in tiebreaker order
            # so we still produce SOME ordering rather than infinite-looping.
            ready = [scoped[name] for name in scoped if name not in placed]
        ready.sort(key=lambda f: (type_order.get(f.prefix, 99), f.short_name))
        # Append the highest-priority ready feature; loop again so each
        # iteration picks one node (preserves Kahn's per-tier emission).
        for f in ready:
            ordered.append(f)
            placed.add(f.folder)
    return ordered


def _next_action(features: list[Feature]) -> tuple[Feature | None, str | None]:
    """Pick the next scoped MVP1 feature to work on.

    Returns ``(feature, suggested_command)`` where ``feature`` is the
    first non-done feature in priority order, and the command is the
    exact ``/pipeline ...`` invocation an operator should run next. The
    command varies by stage (start the pipeline / advance the spec /
    advance the plan / continue implementation). Returns ``(None, None)``
    when everything scoped has shipped.
    """
    ordered = _priority_order(features)
    for f in ordered:
        if f.stage == "done":
            continue
        # Spot a deferred phase too: if the feature is "implement" with a
        # phase*_idea.md, the operator's next move is to start that phase.
        if f.deferred_phase and f.stage in ("implement", "done"):
            phase_idea = sorted(f.path.glob("phase*_idea.md"))
            if phase_idea:
                cmd = f"/pipeline docs/02_product/planned_features/{f.folder}/{phase_idea[0].name}"
                return (f, cmd)
        if f.stage == "idea":
            cmd = f"/pipeline docs/02_product/planned_features/{f.folder} --auto"
        elif f.stage == "spec":
            cmd = f"/pipeline docs/02_product/planned_features/{f.folder} --auto"
        elif f.stage == "plan":
            cmd = (
                f"/impl-execute docs/02_product/planned_features/"
                f"{f.folder}/implementation_plan.md --all"
            )
        elif f.stage == "implement":
            cmd = (
                f"/impl-execute docs/02_product/planned_features/{f.folder}/"
                "implementation_plan.md --all  # resume in-progress"
            )
        else:
            cmd = f"/pipeline docs/02_product/planned_features/{f.folder}"
        return (f, cmd)
    return (None, None)


def _next_action_label(stage: str) -> str:
    """Human-readable description of the next stage transition."""
    return {
        "idea": "Generate spec → run /pipeline (will draft feature_spec.md, then plan, then ship)",
        "spec": "Spec exists; run /pipeline to generate the implementation plan + ship",
        "plan": "Plan approved; run /impl-execute to ship",
        "implement": "Implementation in progress — resume to finish",
        "done": "Already shipped — pick the next item",
    }.get(stage, "Run /pipeline to advance")


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
        # Priority breakdown across EVERY not-done item (regardless of
        # prefix), so the headline KPI can no longer hide feat/infra ideas
        # under "backlog." Operators see "P0: N · P1: N · P2: N · Backlog:
        # N" alongside the legacy single-number Path. Done items are
        # excluded — they don't need priority.
        "priority_p0": 0,
        "priority_p1": 0,
        "priority_p2": 0,
        "priority_backlog": 0,
    }
    priority_keys = {
        "P0": "priority_p0",
        "P1": "priority_p1",
        "P2": "priority_p2",
        "Backlog": "priority_backlog",
    }
    for f in features:
        if f.prefix in ("feat", "infra", "chore", "epic"):
            if f.stage == "idea":
                if f.prefix == "chore":
                    kpi["open_chores_idea"] += 1
                else:
                    kpi["backlog_ideas"] += 1
                kpi[priority_keys.get(f.priority, "priority_p2")] += 1
                continue
            kpi["scoped_features"] += 1
            if f.stage == "done":
                kpi["done_features"] += 1
            else:
                kpi[priority_keys.get(f.priority, "priority_p2")] += 1
        elif f.prefix == "bug":
            if f.stage != "done":
                kpi["open_bugs"] += 1
                kpi[priority_keys.get(f.priority, "priority_p2")] += 1
    kpi["remaining"] = (
        (kpi["scoped_features"] - kpi["done_features"]) + kpi["open_bugs"] + kpi["open_chores_idea"]
    )
    # `total_pending` is the honest "things you might want to work on"
    # count — every not-done item across feat/infra/chore/epic/bug,
    # including feat_ + infra_ at idea stage that the original `remaining`
    # KPI excluded. This is what most operators expect from "Path to MVP1."
    kpi["total_pending"] = (
        kpi["priority_p0"] + kpi["priority_p1"] + kpi["priority_p2"] + kpi["priority_backlog"]
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

    # Priority chip — only render for not-done items (done features
    # don't need a priority signal; they've shipped). Color-coded via
    # the data-priority attribute + matching CSS so P0 visually pops.
    priority_html = ""
    if f.stage != "done":
        prio_label = html.escape(f.priority)
        priority_html = (
            f'<span class="badge priority" data-priority="{prio_label}">{prio_label}</span>'
        )

    one_liner = (f.one_liner or f.status_line)[:200]
    return f"""
<div class="card {f.prefix}" data-prefix="{f.prefix}" data-priority="{html.escape(f.priority)}">
  <div class="name"><a href="{html.escape(href)}">{html.escape(f.display_name)}</a></div>
  <div class="meta">
    <span class="badge {f.prefix}">{html.escape(PREFIX_LABELS.get(f.prefix, f.prefix))}</span>
    {priority_html}
    {pr_html}{" " if pr_html and merged_html else ""}{merged_html}
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


def _release_label(release: str) -> str:
    """Render a release tag like ``mvp1`` as ``MVP1`` for headings + KPI copy."""
    m = re.match(r"^mvp(\d+)$", release)
    return f"MVP{m.group(1)}" if m else release.upper()


ROADMAP_FILENAME_HTML = "dashboard.html"
ROADMAP_FILENAME_MD = "DASHBOARD.md"
"""Roadmap roll-up filenames (no release prefix — these are THE index)."""


def _roadmap_row(release_tag: str, features: list[Feature]) -> dict[str, object]:
    """Compute the roll-up KPIs for a single release row.

    Returns a dict with: ``done`` (int), ``scoped`` (int), ``remaining``
    (int), ``total`` (int — every folder tagged for this release,
    including idea-only chore/backlog), ``state`` (str: "complete" /
    "in_progress" / "queued" / "unscoped"), ``has_dashboard`` (bool —
    whether to emit a drill-down link).
    """
    subset = [f for f in features if f.release == release_tag]
    if not subset:
        return {
            "done": 0,
            "scoped": 0,
            "remaining": 0,
            "total": 0,
            "state": "unscoped",
            "has_dashboard": False,
        }
    kpi = _classify_kpi(subset)
    done = kpi["done_features"]
    scoped = kpi["scoped_features"]
    remaining = kpi["remaining"]
    if scoped > 0 and done == scoped and remaining == 0:
        state = "complete"
    elif done == 0 and scoped == 0:
        # Only idea-stage / bug items captured — pre-scope queue.
        state = "queued"
    else:
        state = "in_progress"
    return {
        "done": done,
        "scoped": scoped,
        "remaining": remaining,
        "total": len(subset),
        "state": state,
        "has_dashboard": True,
    }


def _back_to_roadmap_link_md() -> str:
    """Header line inserted at the top of every per-release markdown dashboard."""
    return f"[← Roadmap overview]({ROADMAP_FILENAME_MD})"


def _back_to_roadmap_link_html() -> str:
    """Header element inserted at the top of every per-release HTML dashboard."""
    return f'<div class="back-link"><a href="{ROADMAP_FILENAME_HTML}">← Roadmap overview</a></div>'


def _next_up_html(features: list[Feature], release: str = DEFAULT_RELEASE) -> str:
    """Render the 'Next up' callout — the prominent banner above the KPIs.

    Tells the operator EXACTLY what feature to start next + the runnable
    command. Uses the dependency-derived priority order from
    ``_priority_order`` so it matches what ``/pipeline status`` would say.
    """
    next_feature, cmd = _next_action(features)
    if next_feature is None:
        release_label = _release_label(release)
        return f"""
<section>
  <div class="next-up done">
    <div class="eyebrow">Next up</div>
    <div class="title">All scoped {html.escape(release_label)} features shipped 🎉</div>
    <div class="one-liner">
      Pull from the Idea backlog or capture a new feature spec.
    </div>
  </div>
</section>
"""
    spec_path = next_feature.path / "feature_spec.md"
    target = (
        spec_path.relative_to(REPO_ROOT)
        if spec_path.exists()
        else next_feature.path.relative_to(REPO_ROOT)
    )
    href = f"../../{target}"
    one_liner = next_feature.one_liner or next_feature.status_line or ""
    stage_hint = _next_action_label(next_feature.stage)
    type_label = PREFIX_LABELS.get(next_feature.prefix, next_feature.prefix)
    stage_label = STAGE_LABELS[next_feature.stage]
    eyebrow = (
        f"Next up — {html.escape(type_label)}, currently in "
        f"<strong>{html.escape(stage_label)}</strong>"
    )
    title_html = f'<a href="{html.escape(href)}">{html.escape(next_feature.display_name)}</a>'
    return f"""
<section>
  <div class="next-up">
    <div class="eyebrow">{eyebrow}</div>
    <div class="title">{title_html}</div>
    <div class="one-liner">{html.escape(one_liner[:240])}</div>
    <div class="stage-hint">{html.escape(stage_hint)}</div>
    <code class="cmd">{html.escape(cmd or "")}</code>
  </div>
</section>
"""


def render_html(features: list[Feature], release: str = DEFAULT_RELEASE) -> str:
    """Render an HTML dashboard for a single release tag.

    ``features`` must already be filtered to the target release — the
    caller is :func:`main`, which loads + classifies + filters once and
    then invokes this renderer once per discovered release.
    """
    kpi = _classify_kpi(features)
    pct = (
        round(kpi["done_features"] * 100 / kpi["scoped_features"]) if kpi["scoped_features"] else 0
    )
    by_stage: dict[str, list[Feature]] = {s: [] for s in STAGES}
    for f in features:
        by_stage[f.stage].append(f)

    # Inside each stage, sort by:
    # 1. Operator-curated priority (P0 → P1 → P2 → Backlog) — surfaces
    #    the highest-leverage idea first regardless of folder name.
    # 2. Type — feat/infra over chore/bug (visual scan order).
    # 3. Alphabetical (deterministic tiebreaker).
    # Done features are excluded from the priority signal entirely (already
    # shipped) and just sort by name.
    type_order = {"feat": 0, "infra": 1, "epic": 2, "chore": 3, "bug": 4}

    def _sort_key(f: Feature) -> tuple[int, int, str]:
        if f.stage == "done":
            return (99, type_order.get(f.prefix, 99), f.short_name)
        return (
            _PRIORITY_ORDER.get(f.priority, _PRIORITY_ORDER[DEFAULT_PRIORITY]),
            type_order.get(f.prefix, 99),
            f.short_name,
        )

    for s in STAGES:
        by_stage[s].sort(key=_sort_key)

    columns = "".join(_column_html(s, by_stage[s]) for s in STAGES)
    mermaid = _mermaid_graph(features)
    next_up = _next_up_html(features, release=release)
    # Use the most-recent mtime of any feature-folder file (or this script
    # itself) instead of `now()` — keeps regeneration idempotent so the
    # pre-commit hook doesn't churn the dashboard on every unrelated commit.
    now = _data_freshness().strftime("%Y-%m-%d")
    release_label = _release_label(release)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RelyLoop {release_label} Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<header>
  {_back_to_roadmap_link_html()}
  <h1>RelyLoop {release_label} Dashboard</h1>
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
{next_up}

<section>
  <h2>{release_label} Progress</h2>
  <div class="kpi-row">
    <div class="kpi {"complete" if pct == 100 else ""}">
      <div class="label">Scoped items done</div>
      <div class="value">{kpi["done_features"]} / {kpi["scoped_features"]}</div>
      <div class="sub">{pct}% of feat_/infra_/chore_/epic_ items past idea stage</div>
      <div class="bar"><span style="width:{pct}%"></span></div>
    </div>
    <div class="kpi {"warn" if kpi["total_pending"] else "complete"}">
      <div class="label">Pending work</div>
      <div class="value">{kpi["total_pending"]}</div>
      <div class="sub">every not-done feat/infra/chore/bug across all priorities</div>
    </div>
    <div class="kpi {"bug" if kpi["open_bugs"] else ""}">
      <div class="label">Open bugs</div>
      <div class="value">{kpi["open_bugs"]}</div>
      <div class="sub">tracked bug_* idea files</div>
    </div>
    <div class="kpi {"warn" if kpi["priority_p0"] else ""}">
      <div class="label">P0 — do next</div>
      <div class="value">{kpi["priority_p0"]}</div>
      <div class="sub">unblocking / paying daily cost</div>
    </div>
  </div>
  <div class="kpi-row">
    <div class="kpi">
      <div class="label">P1</div>
      <div class="value">{kpi["priority_p1"]}</div>
      <div class="sub">high-value, ready when P0 clears</div>
    </div>
    <div class="kpi">
      <div class="label">P2 (default)</div>
      <div class="value">{kpi["priority_p2"]}</div>
      <div class="sub">important to file, not blocking</div>
    </div>
    <div class="kpi">
      <div class="label">Backlog</div>
      <div class="value">{kpi["priority_backlog"]}</div>
      <div class="sub">captured for record, not planned</div>
    </div>
    <div class="kpi">
      <div class="label">Legacy "Path to {release_label}"</div>
      <div class="value">{kpi["remaining"]}</div>
      <div class="sub">scoped not-done + bugs + chore-ideas only (excludes feat/infra ideas)</div>
    </div>
  </div>
  <div class="kpi-secondary">
    <span>
      <strong>Backlog ideas:</strong>
      {kpi["backlog_ideas"]} idea-only feat/infra folders (not yet scoped into {release_label})
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
    rel = os.path.relpath(target, DASHBOARD_DIR)
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
    # Done features don't need a priority column — they've shipped.
    if stage == "done":
        rows = [
            "| Feature | Type | One-liner | Depends on | Status |",
            "|---|---|---|---|---|",
        ]
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
    else:
        # Non-done stages: prepend a `#` column showing the within-stage
        # rank so the exact order (tier + prefix tiebreaker via
        # _md_sort_key — not dependency-aware; that's `_priority_order`'s
        # job for the "Next up" callout) is visually explicit, not just
        # implied by row position. Matches what `/pipeline status`
        # reports for the Idea backlog.
        rows = [
            "| # | Priority | Feature | Type | One-liner | Depends on | Status |",
            "|---|---|---|---|---|---|---|",
        ]
        for idx, f in enumerate(features, start=1):
            rows.append(
                "| "
                + " | ".join(
                    [
                        str(idx),
                        f.priority,
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


def render_markdown(features: list[Feature], release: str = DEFAULT_RELEASE) -> str:
    """Render the GitHub-native dashboard view for a single release tag.

    Mirrors the HTML's information architecture using GitHub-native
    primitives (tables + Mermaid block) so the file renders inline when
    browsed on github.com without any preview proxy. ``features`` is the
    already-filtered subset for ``release``.
    """
    kpi = _classify_kpi(features)
    pct = (
        round(kpi["done_features"] * 100 / kpi["scoped_features"]) if kpi["scoped_features"] else 0
    )
    by_stage: dict[str, list[Feature]] = {s: [] for s in STAGES}
    for f in features:
        by_stage[f.stage].append(f)
    type_order = {"feat": 0, "infra": 1, "epic": 2, "chore": 3, "bug": 4}

    def _md_sort_key(f: Feature) -> tuple[int, int, str]:
        if f.stage == "done":
            return (99, type_order.get(f.prefix, 99), f.short_name)
        return (
            _PRIORITY_ORDER.get(f.priority, _PRIORITY_ORDER[DEFAULT_PRIORITY]),
            type_order.get(f.prefix, 99),
            f.short_name,
        )

    for s in STAGES:
        by_stage[s].sort(key=_md_sort_key)

    asof = _data_freshness().strftime("%Y-%m-%d")
    mermaid = _mermaid_graph(features)
    release_label = _release_label(release)
    html_filename = f"{_release_filename_safe(release)}_dashboard.html"

    lines: list[str] = []
    lines.append(_back_to_roadmap_link_md())
    lines.append("")
    lines.append(f"# RelyLoop {release_label} Dashboard")
    lines.append("")
    lines.append(
        f"_Reflects feature-folder state as of **{asof}** "
        "(latest mtime of any planned/implemented feature `.md` file). "
        "Regenerated by `make dashboard` and the `mvp1-dashboard-regen` pre-commit hook. "
        "For the rich local view (filter chips, type colors), open "
        f"[`{html_filename}`]({html_filename}) in a browser._"
    )
    lines.append("")

    # "Next up" callout — same algorithm as the HTML banner / /pipeline status.
    next_feature, cmd = _next_action(features)
    lines.append("## Next up")
    lines.append("")
    if next_feature is None:
        lines.append(f"All scoped {release_label} features shipped 🎉")
        lines.append("")
        lines.append("Pull from the Idea backlog or capture a new feature spec.")
    else:
        type_label = PREFIX_LABELS.get(next_feature.prefix, next_feature.prefix)
        feature_link = _md_feature_link(next_feature)
        one_liner = next_feature.one_liner or next_feature.status_line or ""
        lines.append(
            f"**{feature_link}** — {type_label}, currently in "
            f"**{STAGE_LABELS[next_feature.stage]}**"
        )
        lines.append("")
        if one_liner:
            lines.append(f"> {_md_escape_cell(one_liner[:240])}")
            lines.append("")
        lines.append(_next_action_label(next_feature.stage))
        lines.append("")
        lines.append("```bash")
        lines.append(cmd or "")
        lines.append("```")
    lines.append("")

    lines.append(f"## {release_label} Progress")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(
        f"| Scoped items done | "
        f"**{kpi['done_features']} / {kpi['scoped_features']}** ({pct}%) "
        f"— feat_/infra_/chore_/epic_ past idea stage |"
    )
    lines.append(
        f"| Pending work | **{kpi['total_pending']}** items "
        "(every not-done feat/infra/chore/bug across all priorities) |"
    )
    lines.append(f"| → P0 — do next | **{kpi['priority_p0']}** unblocking / paying daily cost |")
    lines.append(f"| → P1 | **{kpi['priority_p1']}** high-value, ready when P0 clears |")
    lines.append(f"| → P2 (default) | {kpi['priority_p2']} important to file, not blocking |")
    lines.append(f"| → Backlog | {kpi['priority_backlog']} captured for record, not planned |")
    lines.append(f"| Open bugs | {kpi['open_bugs']} |")
    lines.append(
        f'| Legacy "Path to {release_label}" | {kpi["remaining"]} '
        "items — scoped-not-done + bugs + chore-ideas only (excludes feat/infra ideas) |"
    )
    lines.append(
        f"| Backlog ideas | {kpi['backlog_ideas']} idea-only feat/infra "
        f"(not yet scoped into {release_label}) |"
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


def _maybe_write(path: Path, new_content: str) -> bool:
    """Write ``new_content`` to ``path`` only if it differs from the existing file.

    Returns ``True`` when a write happened, ``False`` when the file was
    already content-equivalent. Pre-commit's "files were modified by this
    hook" check sees a no-op write as a failure (mtime changes are
    irrelevant — pre-commit hashes the file content), so this guard is
    what makes the regen genuinely idempotent: the hook now only fails a
    commit when the dashboard's rendered output actually changed.
    """
    try:
        existing: str | None = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing == new_content:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def _release_filename_safe(release: str) -> str:
    """Normalize a release tag for use in filenames + hrefs.

    Half-step releases like ``"mvp1.5"`` carry a dot in the internal
    identifier (matching the canonical release-matrix label
    ``MVP1.5 / v0.1.5``), but dots in filenames read confusably — they
    could be mistaken for file extensions. This helper produces the
    underscore-form filename token: ``"mvp1.5"`` → ``"mvp1_5"``.

    Used by both :func:`_dashboard_paths` (file write) and every link
    renderer (``render_markdown`` "rich local view" callout,
    ``render_roadmap_html`` cards, ``render_roadmap_markdown`` table) so
    on-disk filenames and inline hrefs converge on the same form. Drift
    between write and link sites caused Gemini-flagged broken links on
    PR #211 cycle 1; this helper is the single point of truth.
    """
    return release.replace(".", "_")


def _dashboard_paths(release: str) -> tuple[Path, Path]:
    """Return ``(html_path, md_path)`` for a release tag.

    File names follow the existing MVP1 precedent — lowercase ``html``
    and uppercase ``MD`` — so the historical paths
    ``mvp1_dashboard.html`` / ``MVP1_DASHBOARD.md`` are preserved while
    new release tags get parallel filenames (``mvp2_dashboard.html`` /
    ``MVP2_DASHBOARD.md``, ...).

    For half-step releases (e.g. ``"mvp1.5"``) the dot in the internal
    release identifier is normalized to an underscore via
    :func:`_release_filename_safe` so ``"mvp1.5"`` produces
    ``MVP1_5_DASHBOARD.md`` / ``mvp1_5_dashboard.html``.
    """
    safe = _release_filename_safe(release)
    return (
        DASHBOARD_DIR / f"{safe}_dashboard.html",
        DASHBOARD_DIR / f"{safe.upper()}_DASHBOARD.md",
    )


# ---------------------------------------------------------------------------
# Roadmap roll-up — top-level index across every release
# ---------------------------------------------------------------------------


def _roadmap_state_label(state: str) -> str:
    """Render the roll-up state machine value as a human pill label."""
    return {
        "complete": "Complete",
        "in_progress": "In progress",
        "queued": "Held / queued",
        "unscoped": "Not yet scoped",
    }.get(state, state.title())


def render_roadmap_html(features: list[Feature]) -> str:
    asof = _data_freshness().strftime("%Y-%m-%d")
    rows_html: list[str] = []
    for release_tag, label, theme in ROADMAP_RELEASES:
        row = _roadmap_row(release_tag, features)
        state = str(row["state"])
        state_pill = (
            f'<span class="state-pill {state}">{html.escape(_roadmap_state_label(state))}</span>'
        )
        if row["has_dashboard"]:
            href = f"{_release_filename_safe(release_tag)}_dashboard.html"
            name_html = f'<a href="{html.escape(href)}">{html.escape(label)}</a>'
            done = int(row["done"])
            scoped = int(row["scoped"])
            remaining = int(row["remaining"])
            if scoped > 0:
                progress = f"{done} / {scoped} scoped done"
                if remaining > 0:
                    progress += f" · {remaining} remaining"
            else:
                total = int(row["total"])
                progress = f"{total} item(s) queued"
        else:
            name_html = html.escape(label)
            progress = "—"
        rows_html.append(
            f"""
<div class="roadmap-row">
  <div class="release-name">{name_html}</div>
  <div class="theme">{html.escape(theme)}</div>
  <div class="progress">{html.escape(progress)}</div>
  {state_pill}
</div>
"""
        )

    rows = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RelyLoop — Release Roadmap</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>RelyLoop — Release Roadmap</h1>
  <div class="meta">
    Top-level index across MVP1 → GA v1+ as of {asof}. Click a release name to
    drill into the per-release dashboard. Theme labels sourced from
    <a href="../01_architecture/tech-stack.md">tech-stack.md §"Canonical
    release matrix"</a>. See <a href="../../state.md">state.md</a> for
    active-branch context and <a href="../../CLAUDE.md">CLAUDE.md</a> for
    conventions.
  </div>
</header>

<main>
<section>
  <h2>Releases</h2>
  {rows}
</section>
</main>

<footer>
  Single source of truth: the feature folder structure + the release matrix in
  <code>tech-stack.md</code>. Regenerate with <code>make dashboard</code>.
</footer>
</body>
</html>
"""


def render_roadmap_markdown(features: list[Feature]) -> str:
    asof = _data_freshness().strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("# RelyLoop — Release Roadmap")
    lines.append("")
    lines.append(
        f"_Top-level index across MVP1 → GA v1+ as of **{asof}**. Click a "
        "release name to drill into the per-release dashboard. Theme labels "
        "sourced from "
        '[`docs/01_architecture/tech-stack.md` §"Canonical release matrix"]'
        "(../01_architecture/tech-stack.md). For the rich local view, open "
        f"[`{ROADMAP_FILENAME_HTML}`]({ROADMAP_FILENAME_HTML}) in a browser._"
    )
    lines.append("")
    lines.append("## Releases")
    lines.append("")
    lines.append("| Release | Theme | Progress | Status |")
    lines.append("|---|---|---|---|")
    for release_tag, label, theme in ROADMAP_RELEASES:
        row = _roadmap_row(release_tag, features)
        state_label = _roadmap_state_label(str(row["state"]))
        if row["has_dashboard"]:
            href = f"{_release_filename_safe(release_tag).upper()}_DASHBOARD.md"
            name_cell = f"[{label}]({href})"
            done = int(row["done"])
            scoped = int(row["scoped"])
            remaining = int(row["remaining"])
            if scoped > 0:
                progress = f"{done} / {scoped} scoped done"
                if remaining > 0:
                    progress += f" · {remaining} remaining"
            else:
                total = int(row["total"])
                progress = f"{total} item(s) queued"
        else:
            name_cell = label
            progress = "—"
        lines.append(
            f"| {_md_escape_cell(name_cell)} | {_md_escape_cell(theme)} | "
            f"{_md_escape_cell(progress)} | **{state_label}** |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "Source of truth: feature folders under "
        "[`docs/02_product/planned_features/`](../02_product/planned_features/) and "
        "[`docs/00_overview/implemented_features/`](implemented_features/), plus "
        "the release matrix in "
        "[`docs/01_architecture/tech-stack.md`](../01_architecture/tech-stack.md). "
        "See [`state.md`](../../state.md) for active-branch context and "
        "[`CLAUDE.md`](../../CLAUDE.md) for conventions."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    features = load_all()
    # Always emit at least the MVP1 dashboard; auto-discover any other
    # release tags from the loaded features (so MVP2/MVP3/... appear as
    # soon as a feature folder uses the matching ``_mvpN`` suffix).
    discovered = sorted({f.release for f in features} | {DEFAULT_RELEASE})

    wrote_paths: list[Path] = []
    for release in discovered:
        subset = [f for f in features if f.release == release]
        html_path, md_path = _dashboard_paths(release)
        output_html = _strip_trailing_ws(render_html(subset, release=release))
        output_md = _strip_trailing_ws(render_markdown(subset, release=release))
        if _maybe_write(html_path, output_html):
            wrote_paths.append(html_path)
        if _maybe_write(md_path, output_md):
            wrote_paths.append(md_path)
        print(f"{release}: {len(subset)} features")

    # Top-level roadmap roll-up. Always emitted (lists every release in the
    # matrix, including those with zero scoped features), so the roadmap
    # shows runway and provides a single entry point that navigates into
    # every per-release dashboard.
    roadmap_html_path = DASHBOARD_DIR / ROADMAP_FILENAME_HTML
    roadmap_md_path = DASHBOARD_DIR / ROADMAP_FILENAME_MD
    roadmap_html = _strip_trailing_ws(render_roadmap_html(features))
    roadmap_md = _strip_trailing_ws(render_roadmap_markdown(features))
    if _maybe_write(roadmap_html_path, roadmap_html):
        wrote_paths.append(roadmap_html_path)
    if _maybe_write(roadmap_md_path, roadmap_md):
        wrote_paths.append(roadmap_md_path)
    print(f"roadmap: {len(ROADMAP_RELEASES)} releases in matrix")

    if wrote_paths:
        rels = " + ".join(str(p.relative_to(REPO_ROOT)) for p in wrote_paths)
        print(f"wrote {rels} ({len(features)} features across {len(discovered)} release(s))")
    else:
        print(f"no changes ({len(features)} features across {len(discovered)} release(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
