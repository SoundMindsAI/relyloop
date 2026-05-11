"""Unit tests for pure rendering helpers in backend/workers/git_pr.py.

Covers:

* Branch naming for study-backed vs manual proposals (spec §4).
* Chart raw-URL form uses ``raw/refs/heads/{branch}`` (cycle-2 F4 — the
  default ``raw/{branch}`` form is ambiguous when a branch contains a
  slash like ``relyloop/study-{id}``).
* PR body composition for study-backed proposals (header, metric delta,
  config diff table, suggested follow-ups, optional study link, chart
  embed when PNG render succeeded).
* PR body composition for manual proposals (omits metrics + study link;
  includes the explanatory note).
* Markdown-table chart fallback (spec AC-11).
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.workers.git_pr import (
    _branch_name,
    _chart_raw_url,
    _render_chart_markdown_fallback,
    _render_pr_body_manual,
    _render_pr_body_study_backed,
)


def test_branch_name_study_backed() -> None:
    assert _branch_name(proposal_id="prop-abc", study_id="study-xyz") == "relyloop/study-study-xyz"


def test_branch_name_manual_proposal() -> None:
    assert _branch_name(proposal_id="prop-abc", study_id=None) == "relyloop/proposal-prop-abc"


def test_chart_url_uses_refs_heads_form_for_slashed_branch() -> None:
    """Cycle-2 F4 — the slash in 'relyloop/study-X' makes the bare /raw/{branch}
    form ambiguous. github.com supports the unambiguous /raw/refs/heads/ form."""
    url = _chart_raw_url(
        owner="acme",
        repo_name="search-config",
        branch="relyloop/study-abc123",
        study_id="abc123",
    )
    assert url == (
        "https://github.com/acme/search-config"
        "/raw/refs/heads/relyloop/study-abc123/.relyloop/digest-charts/abc123.png"
    )


def test_pr_body_study_backed_includes_metric_delta_and_diff() -> None:
    proposal = SimpleNamespace(
        metric_delta={
            "ndcg@10": {"baseline": 0.5, "achieved": 0.62, "delta_pct": 24.0},
        },
    )
    study = SimpleNamespace(id="study-abc", name="prod-en-v1")
    digest = SimpleNamespace(suggested_followups=["Try BM25 k1=1.4", "Add english stop words"])
    config_diff = {
        "k1": {"from": 1.2, "to": 1.4},
        "b": {"from": 0.75, "to": 0.6},
    }
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff=config_diff,
        chart_md="",
        base_url="https://relyloop.acme.internal",
    )
    assert "# RelyLoop proposal" in body
    assert "prod-en-v1" in body
    assert "study-abc" in body
    assert "https://relyloop.acme.internal/studies/study-abc" in body
    assert "ndcg@10" in body and "0.5" in body and "0.62" in body
    assert "+24.0%" in body
    assert "| `k1` | `1.2` | `1.4` |" in body
    assert "| `b` | `0.75` | `0.6` |" in body
    assert "Try BM25 k1=1.4" in body
    # No chart section when chart_md is empty.
    assert "## Parameter importance" not in body


def test_pr_body_study_backed_without_base_url_omits_link() -> None:
    proposal = SimpleNamespace(metric_delta=None)
    study = SimpleNamespace(id="study-1", name="study-1")
    digest = SimpleNamespace(suggested_followups=[])
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff={"x": {"from": 1, "to": 2}},
        chart_md="",
        base_url=None,
    )
    assert "**Details:**" not in body
    assert "## Suggested follow-ups" not in body  # empty list → omitted


def test_pr_body_study_backed_includes_chart_md_when_provided() -> None:
    proposal = SimpleNamespace(metric_delta=None)
    study = SimpleNamespace(id="s", name="s")
    digest = SimpleNamespace(suggested_followups=[])
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff={},
        chart_md="| Param | Importance |\n|---|---|\n| `k1` | 0.500 |",
        base_url=None,
    )
    assert "## Parameter importance" in body
    assert "| `k1` | 0.500 |" in body


def test_pr_body_manual_omits_metrics_and_links() -> None:
    proposal = SimpleNamespace(study_id=None)
    body = _render_pr_body_manual(
        proposal=proposal,
        config_diff={"slop": {"from": 1, "to": 2}},
    )
    assert "manual (hand-crafted) proposal" in body
    assert "## Metric delta" not in body
    assert "Suggested follow-ups" not in body
    assert "## Parameter importance" not in body
    assert "**Details:**" not in body
    assert "| `slop` | `1` | `2` |" in body


def test_chart_markdown_fallback_sorts_descending() -> None:
    importance = {"k1": 0.20, "b": 0.50, "tie_breaker": 0.05}
    md = _render_chart_markdown_fallback(importance)
    rows = [line for line in md.splitlines() if line.startswith("| `")]
    assert rows[0].startswith("| `b`")
    assert rows[1].startswith("| `k1`")
    assert rows[2].startswith("| `tie_breaker`")


def test_chart_markdown_fallback_empty_returns_empty_string() -> None:
    assert _render_chart_markdown_fallback({}) == ""
