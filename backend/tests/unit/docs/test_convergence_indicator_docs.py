# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Docs assertion tests for feat_study_convergence_indicator Story 7.1.

Locks the AC-19 docs surface:

- The operator runbook exists at the canonical path with substantial content
  (>= 100 lines) and contains the three verdict labels + the FR-7 cross-
  reference to the autopilot soft contract.
- CLAUDE.md's "Key Runbooks" table carries a row pointing at the runbook.
- The glossary's ``convergence_verdict`` entry exists and references the
  runbook so the "Learn more" anchor in the tooltip resolves.

The frontend's runtime existence-of-key checks are covered by vitest at
``ui/src/__tests__/lib/glossary.test.ts`` (existing length-bound + key-set
audits); this suite focuses on cross-document anchor coherence.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Resolve the repo root by walking up to the first parent containing
    ``CLAUDE.md``. Robust to working-directory drift in CI / sibling-
    worktree runs."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "CLAUDE.md").is_file():
            return ancestor
    raise RuntimeError("Could not locate repo root from test file location")


def test_convergence_verdict_runbook_exists(repo_root: Path) -> None:
    runbook = repo_root / "docs" / "03_runbooks" / "convergence-verdict.md"
    assert runbook.is_file(), f"runbook missing at {runbook}"
    body = runbook.read_text(encoding="utf-8")
    # The runbook is operator-facing reference material; it should be at
    # least 100 lines long but shorter than 300 (otherwise it's drifting
    # into spec territory).
    line_count = len(body.splitlines())
    assert 100 <= line_count < 300, f"runbook line count {line_count} outside expected range"


def test_runbook_covers_three_verdicts(repo_root: Path) -> None:
    runbook = repo_root / "docs" / "03_runbooks" / "convergence-verdict.md"
    body = runbook.read_text(encoding="utf-8")
    # Each canonical verdict gets its own section heading.
    assert "### Converged" in body, "missing Converged section heading"
    assert "### Still improving when it stopped" in body, "missing Still improving section heading"
    assert "### Too few trials to tell" in body, "missing Too few trials section heading"
    # The re-run recommendation copy lines up with the digest framing rule
    # so operators see consistent language across the panel + the digest.
    assert "re-run with the next-larger budget preset" in body.lower() or (
        "re-run with at least standard" in body.lower()
    )


def test_runbook_references_autopilot_soft_contract(repo_root: Path) -> None:
    runbook = repo_root / "docs" / "03_runbooks" / "convergence-verdict.md"
    body = runbook.read_text(encoding="utf-8")
    assert "feat_overnight_autopilot" in body, (
        "FR-7 cross-reference to autopilot soft contract missing from runbook"
    )


def test_claude_md_key_runbooks_table_has_convergence_row(repo_root: Path) -> None:
    claude_md = repo_root / "CLAUDE.md"
    body = claude_md.read_text(encoding="utf-8")
    # Anchor: the row must reference the runbook path AND mention the
    # feature folder so future readers can trace ownership.
    assert "docs/03_runbooks/convergence-verdict.md" in body, (
        "CLAUDE.md Key Runbooks table missing convergence-verdict.md link"
    )
    assert "feat_study_convergence_indicator" in body, (
        "CLAUDE.md Key Runbooks row missing feature_folder cite"
    )
    # The "Situation" half of the row carries the canonical phrasing so
    # search-by-symptom works.
    assert "Interpreting the convergence verdict" in body, (
        "CLAUDE.md row missing canonical 'Interpreting the convergence verdict' phrasing"
    )


def test_glossary_convergence_verdict_entry_links_to_runbook(
    repo_root: Path,
) -> None:
    glossary = repo_root / "ui" / "src" / "lib" / "glossary.ts"
    body = glossary.read_text(encoding="utf-8")
    # The three new glossary keys all live in this file.
    assert "convergence_verdict:" in body, "missing convergence_verdict key"
    assert "convergence_curve:" in body, "missing convergence_curve key"
    assert "convergence_window:" in body, "missing convergence_window key"
    # The 'Learn more' anchor on convergence_verdict points at the runbook
    # so AC-19's "the tooltip leads operators to the runbook" path works.
    assert "docs/03_runbooks/convergence-verdict.md" in body, (
        "glossary convergence_verdict entry missing runbook deep-link"
    )
