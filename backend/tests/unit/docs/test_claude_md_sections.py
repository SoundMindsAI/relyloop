"""Regression tests for the ``## Working in sibling worktrees`` section in CLAUDE.md.

Locks the historically-observed failure modes for the section added by
`infra_agent_sibling_worktree_isolation` Phase 1 (Story 1.1): silent
deletion, accidental re-ordering, re-introduction of a bare
``DATABASE_URL=postgresql://`` env var in the recipe (Rule #2 regression),
mis-attribution of the ``worker`` service in the leaky-path catalog rows
(the original idea brief's error — caught at /spec-gen), and duplication
of the one-shot container recipe.

The tests intentionally do NOT enforce ``docker-compose.yml`` line-number
freshness — that would be brittle (line numbers shift on every Compose
edit) and the alternative (parsing YAML) is exactly what OQ-2 deferred to
Phase 2. Line-number quality is a PR-review concern.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# CLAUDE.md is at repo root. backend/tests/unit/docs/ is 4 levels deep —
# same parent count as backend/tests/unit/scripts/test_dashboard_truncation.py:14.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"
_SECTION_HEADER = "## Working in sibling worktrees"
_NEXT_HEADER = "## Bug Fix Protocol"


@pytest.fixture(scope="module")
def claude_md_text() -> str:
    """Read CLAUDE.md once; tests share the text."""
    return _CLAUDE_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def section_body(claude_md_text: str) -> str:
    """Return the body between the section header and the next ``## `` heading.

    Excludes both the section header line and the next-heading line.
    """
    lines = claude_md_text.split("\n")
    try:
        start = lines.index(_SECTION_HEADER)
    except ValueError as exc:
        raise AssertionError(f"Section header {_SECTION_HEADER!r} not found in CLAUDE.md") from exc
    # Scan forward from start+1 until we hit the next top-level heading or EOF.
    for offset, line in enumerate(lines[start + 1 :], start=start + 1):
        if line.startswith("## "):
            return "\n".join(lines[start + 1 : offset])
    # EOF without another heading — return everything after the header.
    return "\n".join(lines[start + 1 :])


def _parse_catalog_rows(section_body: str) -> dict[str, str]:
    """Parse the Compose-anchored paths catalog table into a row map.

    Locates the markdown table by its canonical header ``| Host path |``
    (locked in Story 1.1) and returns a dict mapping each path (the
    text in the first cell, stripped of backticks) to the full row text.
    Rows are accumulated until a blank line or a non-table line is hit.

    The parser is deliberately strict: it expects the markdown-table
    format Story 1.1 commits to. If a future PR converts the catalog to
    a different shape, that PR must update both the catalog markup and
    this parser in the same commit (caught in CI by test #4 failing).
    """
    lines = section_body.split("\n")
    rows: dict[str, str] = {}
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| Host path |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            # End of the table (blank line or other content).
            break
        if set(stripped.replace("|", "").strip()) <= {"-", ":", " "}:
            # Table separator row (`|---|---|...`); skip.
            continue
        # Row line. Extract the first cell.
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        first_cell = cells[0].strip("`")
        if first_cell.startswith("./"):
            rows[first_cell] = stripped
    return rows


class TestWorkingInSiblingWorktreesSection:
    def test_working_in_sibling_worktrees_section_exists(self, claude_md_text: str) -> None:
        """FR-7 test #1 — section header appears exactly once in CLAUDE.md.

        Fails on accidental deletion (count 0) or accidental copy-paste
        (count 2+).
        """
        count = claude_md_text.count(_SECTION_HEADER + "\n")
        assert count == 1, (
            f"Expected the literal line {_SECTION_HEADER!r} to appear exactly "
            f"once in CLAUDE.md, found {count} occurrences. If the count is 0, "
            f"the section was deleted (restore from infra_agent_sibling_worktree_"
            f"isolation Story 1.1). If the count is 2+, a copy-paste error "
            f"duplicated the section — keep one and delete the rest."
        )

    def test_section_ordering_between_pitfalls_and_bugfix(self, claude_md_text: str) -> None:
        """FR-7 test #2 — section sits between Common Pitfalls and Bug Fix Protocol.

        Locks the OQ-1 placement decision; cross-references elsewhere in
        CLAUDE.md assume this ordering.
        """
        lines = claude_md_text.split("\n")
        try:
            pitfalls_idx = lines.index("## Common Pitfalls")
        except ValueError as exc:
            raise AssertionError("Expected '## Common Pitfalls' section in CLAUDE.md") from exc
        try:
            section_idx = lines.index(_SECTION_HEADER)
        except ValueError as exc:
            raise AssertionError(f"Expected {_SECTION_HEADER!r} section in CLAUDE.md") from exc
        try:
            bugfix_idx = lines.index(_NEXT_HEADER)
        except ValueError as exc:
            raise AssertionError(f"Expected {_NEXT_HEADER!r} section in CLAUDE.md") from exc
        assert pitfalls_idx < section_idx < bugfix_idx, (
            f"Expected ordering 'Common Pitfalls' ({pitfalls_idx}) < "
            f"'Working in sibling worktrees' ({section_idx}) < "
            f"'Bug Fix Protocol' ({bugfix_idx}). Found out-of-order placement; "
            f"check whether the section was moved by a recent doc reorganization."
        )

    def test_section_has_no_bare_database_url_assignment(self, section_body: str) -> None:
        """FR-7 test #3 — section body contains no bare ``DATABASE_URL=postgresql://``.

        Catches re-introduction of a bare env var in the shell example
        (CLAUDE.md Rule #2 regression). Prose that mentions the
        anti-pattern (e.g., "the ``DATABASE_URL=...`` anti-pattern") is
        allowed because the pattern is specific to ``postgresql://``.
        """
        match = re.search(r"DATABASE_URL=postgresql://", section_body, re.IGNORECASE)
        assert match is None, (
            "Found a bare 'DATABASE_URL=postgresql://...' assignment inside "
            "the 'Working in sibling worktrees' section body. This violates "
            "CLAUDE.md Absolute Rule #2 (secrets via mounted files, not bare "
            "env vars). The shell example must use the *_FILE-mounted-secret "
            "pattern: -e DATABASE_URL_FILE=/run/secrets/database_url plus a "
            "read-only bind mount of the host secret file. If you are writing "
            "prose that names the anti-pattern, drop 'postgresql://' from the "
            "literal (e.g., 'DATABASE_URL=...') so the regression check stays "
            "outside the regex."
        )

    def test_section_leakypath_catalog_attribution(self, section_body: str) -> None:
        """FR-7 test #4 — catalog rows have correct ``worker`` service attribution.

        Parses the Compose-anchored paths catalog table by row (NOT a
        section-wide regex sweep — section prose legitimately mentions
        ``worker`` outside the catalog). Asserts:

        - The rows for ``./migrations/``, ``./alembic.ini``, and
          ``./samples/`` do NOT list ``worker`` as an owning service
          (catches the original idea-brief's mis-attribution).
        - The row for ``./data/repo-clones/`` DOES list ``worker`` (catches
          accidental removal of the legitimate worker mount mention).

        First asserts all four required rows EXIST in the parsed catalog;
        silent deletion of a row would otherwise pass.
        """
        rows = _parse_catalog_rows(section_body)
        required = ("./migrations/", "./alembic.ini", "./samples/", "./data/repo-clones/")
        missing = [k for k in required if k not in rows]
        assert not missing, (
            f"Expected catalog rows for {required} in the 'Compose-anchored "
            f"host paths' table; missing: {missing}. The Story 1.1 catalog is "
            f"locked to include all six bind-mount sources; a row was deleted "
            f"without removing the corresponding mount from docker-compose.yml."
        )
        for path in ("./migrations/", "./alembic.ini", "./samples/"):
            row = rows[path]
            assert "worker" not in row.lower(), (
                f"Catalog row for {path!r} lists 'worker' as an owning service, "
                f"but the worker container does NOT bind {path!r} (verified "
                f"against docker-compose.yml: worker only mounts "
                f"./data/repo-clones at line 167). Reproducing the original "
                f"idea-brief error. Row text: {row!r}"
            )
        repo_clones_row = rows["./data/repo-clones/"]
        assert "worker" in repo_clones_row.lower(), (
            f"Catalog row for './data/repo-clones/' does NOT list 'worker' as "
            f"an owning service, but docker-compose.yml line 167 binds "
            f"./data/repo-clones into the worker container. Restore the "
            f"worker attribution. Row text: {repo_clones_row!r}"
        )

    def test_section_has_exactly_one_fenced_bash_block(self, section_body: str) -> None:
        """FR-7 test #5 — section contains exactly one fenced ``bash`` code block.

        FR-4 mandates exactly one one-shot container recipe. Copy-paste
        or competing recipes have historically caused agents to follow
        the wrong one.
        """
        bash_fence_count = sum(1 for line in section_body.split("\n") if line.rstrip() == "```bash")
        assert bash_fence_count == 1, (
            f"Expected exactly one '```bash' fenced code block in the "
            f"'Working in sibling worktrees' section, found {bash_fence_count}. "
            f"If 0, the one-shot container recipe was deleted (Story 1.1 FR-4). "
            f"If 2+, a duplicate or competing recipe was added — keep one and "
            f"remove the rest."
        )
