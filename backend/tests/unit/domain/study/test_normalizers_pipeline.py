# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the typed normalizer pipeline (feat_query_normalizer_typed_pipeline).

Covers AC-1 (canonical-order application, incl. scrambled declaration),
AC-6 (U+2019 smart-quote expansion), I-1 (permutation invariance), the
empty-pipeline identity, the strip_punctuation + collapse_whitespace + trim
whitespace-interaction example, the inert ``expand_contractions_custom``
step (Q-1), and the label/step round-trip helpers (AC-4).
"""

from __future__ import annotations

import pytest

from backend.app.domain.study.normalizers import (
    LABEL_ORDER,
    STEP_ORDER,
    NormalizerStep,
    _label_for_subset,
    _pipeline_labels,
    normalize_pipeline,
    steps_for_label,
)

S = NormalizerStep


# --- AC-1: canonical-order application --------------------------------------


def test_empty_pipeline_is_identity() -> None:
    assert normalize_pipeline("  HeLLo What's ", []) == "  HeLLo What's "


def test_lowercase_then_trim_canonical_order() -> None:
    assert normalize_pipeline("  Foo BAR  ", [S.lowercase, S.trim]) == "foo bar"


def test_declaration_order_does_not_matter_scrambled() -> None:
    # AC-1: declared order is ignored; STEP_ORDER governs application.
    scrambled = normalize_pipeline("  Foo BAR  ", [S.trim, S.lowercase])
    canonical = normalize_pipeline("  Foo BAR  ", [S.lowercase, S.trim])
    assert scrambled == canonical == "foo bar"


def test_strip_punctuation_excludes_apostrophe() -> None:
    # Apostrophe must survive so the contraction step can match it.
    assert normalize_pipeline("don't, stop!", [S.strip_punctuation]) == "don't stop"


def test_whitespace_cleanup_runs_last() -> None:
    # strip_punctuation can leave doubled spaces; collapse_whitespace + trim
    # run LAST in STEP_ORDER (D-11), so the output has no doubled/edge spaces.
    out = normalize_pipeline(
        " a , b  c ",
        [S.strip_punctuation, S.collapse_whitespace, S.trim],
    )
    assert out == "a b c"


def test_lowercase_before_contraction_invariant() -> None:
    # lowercase runs before expand_contractions_en (STEP_ORDER), so the
    # mixed-case contraction matches against the lowercased token.
    assert (
        normalize_pipeline("WHAT'S up", [S.lowercase, S.expand_contractions_en, S.trim])
        == "what is up"
    )


# --- AC-6: smart-quote expansion --------------------------------------------


def test_smart_quote_apostrophe_expands() -> None:
    assert (
        normalize_pipeline("what’s the policy?", [S.lowercase, S.trim, S.expand_contractions_en])
        == "what is the policy?"
    )


def test_smart_quote_matches_ascii_apostrophe_byte_for_byte() -> None:
    smart = normalize_pipeline("what’s up", [S.lowercase, S.expand_contractions_en])
    ascii_ = normalize_pipeline("what's up", [S.lowercase, S.expand_contractions_en])
    assert smart == ascii_ == "what is up"


# --- I-1: permutation invariance --------------------------------------------


@pytest.mark.parametrize(
    "declared",
    [
        [S.lowercase, S.strip_punctuation, S.trim],
        [S.trim, S.strip_punctuation, S.lowercase],
        [S.strip_punctuation, S.lowercase, S.trim],
    ],
)
def test_permutation_invariant_same_set_same_output(declared: list[NormalizerStep]) -> None:
    canonical = normalize_pipeline("  Hello, WORLD!  ", [S.lowercase, S.strip_punctuation, S.trim])
    assert normalize_pipeline("  Hello, WORLD!  ", declared) == canonical


# --- Q-1: expand_contractions_custom is inert -------------------------------


def test_expand_contractions_custom_is_inert_no_op() -> None:
    # Declaring the reserved custom step is accepted but applies no transform.
    with_custom = normalize_pipeline("don't stop", [S.expand_contractions_custom])
    assert with_custom == "don't stop"
    # And it composes without affecting the en-expansion result.
    composed = normalize_pipeline(
        "don't stop",
        [S.lowercase, S.expand_contractions_en, S.expand_contractions_custom],
    )
    assert composed == "do not stop"


# --- AC-4 + label/step round-trip helpers -----------------------------------


def test_pipeline_labels_exact_list_for_two_steps() -> None:
    assert _pipeline_labels([S.lowercase, S.trim]) == [
        "none",
        "lowercase",
        "trim",
        "lowercase+trim",
    ]


def test_pipeline_labels_ordered_by_size_then_lexicographic() -> None:
    labels = _pipeline_labels([S.lowercase, S.trim, S.strip_punctuation])
    # 2**3 = 8 labels, the empty subset first.
    assert len(labels) == 8
    assert labels[0] == "none"
    sizes = [0 if lbl == "none" else lbl.count("+") + 1 for lbl in labels]
    assert sizes == sorted(sizes)  # ascending by subset size


def test_label_for_subset_uses_phase1_compatible_token() -> None:
    # expand_contractions_en serializes to the Phase-1 "expand_contractions"
    # token and LABEL_ORDER keeps it byte-identical to the bundle string.
    label = _label_for_subset(frozenset({S.lowercase, S.trim, S.expand_contractions_en}))
    assert label == "lowercase+trim+expand_contractions"


def test_label_for_empty_subset_is_none() -> None:
    assert _label_for_subset(frozenset()) == "none"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("none", ()),
        ("lowercase", (S.lowercase,)),
        ("lowercase+trim", (S.lowercase, S.trim)),
        (
            "lowercase+trim+expand_contractions",
            (S.lowercase, S.expand_contractions_en, S.trim),  # STEP_ORDER
        ),
        ("strip_punctuation", (S.strip_punctuation,)),
    ],
)
def test_steps_for_label_round_trip(label: str, expected: tuple[NormalizerStep, ...]) -> None:
    assert steps_for_label(label) == expected


def test_steps_for_label_rejects_unknown_token() -> None:
    with pytest.raises(ValueError, match="unknown normalizer label token"):
        steps_for_label("lowercase+bogus")


def test_label_then_steps_is_a_bijection_over_powerset() -> None:
    # Every subset's label resolves back to the same step set.
    all_steps = list(STEP_ORDER)
    for size in range(len(all_steps) + 1):
        from itertools import combinations

        for combo in combinations(all_steps, size):
            label = _label_for_subset(frozenset(combo))
            assert set(steps_for_label(label)) == set(combo)


def test_step_and_label_orders_differ() -> None:
    # The two orderings are intentionally decoupled (D-11 vs D-12).
    assert STEP_ORDER != LABEL_ORDER
