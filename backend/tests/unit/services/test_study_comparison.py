# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the study-comparison service (feat_ubi_llm_study_comparison Story 1.1).

``classify_judgment_kind`` is covered over all branches; ``validate_compare_pair``
is covered with stubbed ``repo`` rows (no DB) for every hard gate + the three
non-fatal warnings.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services import study_comparison as sc

# --- classify_judgment_kind --------------------------------------------------


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"generation_kind": "ubi"}, "ubi"),
        ({"generation_kind": "ubi", "converter": "hybrid_ubi_llm"}, "ubi"),
        (None, "llm"),
        ({}, "llm"),
        ({"generation_kind": "something_else"}, "llm"),
        ("not-a-dict", "llm"),
        (["list"], "llm"),
        ({"generation_kind": None}, "llm"),
    ],
)
def test_classify_judgment_kind(params: object, expected: str) -> None:
    assert sc.classify_judgment_kind(params) == expected


# --- validate_compare_pair (stubbed repo) ------------------------------------


def _study(
    sid: str,
    *,
    status: str = "completed",
    query_set_id: str = "qs",
    cluster_id: str = "c1",
    target: str = "products",
    judgment_list_id: str = "jl",
    objective: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=sid,
        status=status,
        query_set_id=query_set_id,
        cluster_id=cluster_id,
        target=target,
        judgment_list_id=judgment_list_id,
        objective=objective or {"metric": "ndcg", "direction": "maximize", "k": 10},
    )


def _jl(kind: str | None) -> SimpleNamespace:
    gp = (
        {"generation_kind": "ubi"}
        if kind == "ubi"
        else ({"generation_kind": kind} if kind else None)
    )
    return SimpleNamespace(generation_params=gp)


def _wire(monkeypatch, studies: dict[str, object], lists: dict[str, object]) -> None:
    async def fake_get_study(_db, sid):  # noqa: ANN001
        return studies.get(sid)

    async def fake_get_jl(_db, jlid):  # noqa: ANN001
        return lists.get(jlid)

    monkeypatch.setattr(sc.repo, "get_study", fake_get_study)
    monkeypatch.setattr(sc.repo, "get_judgment_list", fake_get_jl)


async def test_happy_pair_no_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        {"a": _study("a", judgment_list_id="jl_llm"), "b": _study("b", judgment_list_id="jl_ubi")},
        {"jl_llm": _jl("llm"), "jl_ubi": _jl("ubi")},
    )
    pairing = await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert pairing.a_kind == "llm"
    assert pairing.b_kind == "ubi"
    assert pairing.query_set_id == "qs"
    assert pairing.warnings == []


async def test_missing_study_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, {"a": _study("a")}, {})
    with pytest.raises(sc.CompareValidationError) as exc:
        await sc.validate_compare_pair(None, "a", "missing")  # type: ignore[arg-type]
    assert exc.value.status == 404
    assert exc.value.code == "STUDY_NOT_FOUND"


async def test_not_completed_raises_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        {"a": _study("a", status="running"), "b": _study("b")},
        {"jl": _jl("llm")},
    )
    with pytest.raises(sc.CompareValidationError) as exc:
        await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert exc.value.code == "COMPARE_STUDY_NOT_COMPLETED"


async def test_query_set_mismatch_raises_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        {"a": _study("a", query_set_id="qs1"), "b": _study("b", query_set_id="qs2")},
        {"jl": _jl("llm")},
    )
    with pytest.raises(sc.CompareValidationError) as exc:
        await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert exc.value.code == "COMPARE_QUERY_SET_MISMATCH"


async def test_not_llm_ubi_pair_raises_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two LLM studies.
    _wire(
        monkeypatch,
        {"a": _study("a", judgment_list_id="j1"), "b": _study("b", judgment_list_id="j2")},
        {"j1": _jl("llm"), "j2": _jl("llm")},
    )
    with pytest.raises(sc.CompareValidationError) as exc:
        await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert exc.value.code == "COMPARE_NOT_LLM_UBI_PAIR"


async def test_cross_cluster_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        {
            "a": _study("a", cluster_id="c1", judgment_list_id="j1"),
            "b": _study("b", cluster_id="c2", judgment_list_id="j2"),
        },
        {"j1": _jl("llm"), "j2": _jl("ubi")},
    )
    pairing = await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert [w.code for w in pairing.warnings] == ["CROSS_CLUSTER"]


async def test_target_mismatch_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        {
            "a": _study("a", target="products", judgment_list_id="j1"),
            "b": _study("b", target="catalog", judgment_list_id="j2"),
        },
        {"j1": _jl("llm"), "j2": _jl("ubi")},
    )
    pairing = await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert "TARGET_MISMATCH" in [w.code for w in pairing.warnings]


async def test_objective_mismatch_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        {
            "a": _study(
                "a", judgment_list_id="j1", objective={"metric": "ndcg", "direction": "maximize"}
            ),
            "b": _study(
                "b", judgment_list_id="j2", objective={"metric": "map", "direction": "maximize"}
            ),
        },
        {"j1": _jl("llm"), "j2": _jl("ubi")},
    )
    pairing = await sc.validate_compare_pair(None, "a", "b")  # type: ignore[arg-type]
    assert "OBJECTIVE_MISMATCH" in [w.code for w in pairing.warnings]
