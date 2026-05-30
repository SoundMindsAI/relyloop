# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Source-inspection tests for the Story 2.2 auto-followup trigger
in :mod:`backend.workers.digest`.

These tests read `backend/workers/digest.py` and verify that the
auto-followup trigger block has the expected shape. They guard against
silent regressions to the trigger condition (`is not None` vs `> 0`)
or the deterministic `_job_id` (the layer-1 idempotency mechanism per
D-11).

Why source-inspection rather than running the trigger end-to-end?
``generate_digest`` requires a complete Optuna study + OpenAI mock +
~10 other fixtures to exercise. The trigger logic itself is 30 lines;
the surface area worth locking is the condition and the _job_id, both
of which can drift via a typo. Locking them at the source level gives
a fast, deterministic regression guard without standing up the full
digest worker.

The end-to-end trigger behavior is exercised via
``backend/tests/integration/test_auto_followup.py`` once a chain
seed is in place — that file requires real Postgres + Redis so it
runs in CI, not on a host without service containers.
"""

from __future__ import annotations

import re
from pathlib import Path


def test_trigger_block_exists_in_digest_worker() -> None:
    """The Story 2.2 trigger comment is present at the end of generate_digest."""
    digest_src = Path("backend/workers/digest.py").read_text()
    assert "feat_auto_followup_studies Story 2.2" in digest_src, (
        "Story 2.2 trigger block not found in backend/workers/digest.py"
    )


def test_trigger_condition_uses_is_not_none_not_gt_zero() -> None:
    """Per FR-1 + D-12: trigger fires on `is not None` (including 0), NOT
    on `> 0`. A regression to `> 0` would silently break AC-5 (depth-0
    leaf must emit its own auto_followup_depth_exhausted event)."""
    digest_src = Path("backend/workers/digest.py").read_text()
    # Find the trigger block by the comment delimiter we wrote in Story 2.2.
    trigger_section = re.search(
        r"feat_auto_followup_studies Story 2\.2.*?(?=^\s*finally:)",
        digest_src,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert trigger_section is not None, (
        "Could not locate the Story 2.2 trigger block between the comment "
        "and the enclosing `finally:` clause"
    )
    block = trigger_section.group(0)
    assert "auto_followup_depth" in block, (
        "Trigger block does not reference auto_followup_depth — must check "
        "study.config.get('auto_followup_depth')"
    )
    assert "is not None" in block, (
        "Trigger condition must use `is not None` per D-12 so depth-0 leaves "
        "trigger their own enqueue_followup_study invocation"
    )
    # The substring before "is not None" must NOT contain "> 0" as a
    # condition gate on auto_followup_depth.
    pre = block.split("is not None")[0]
    assert "auto_followup_depth" not in pre or "> 0" not in pre, (
        "Trigger uses a `auto_followup_depth > 0` check before `is not None` — "
        "regression to the pre-D-12 design. The trigger must fire when "
        "auto_followup_depth is not None (including 0)."
    )


def test_trigger_uses_deterministic_job_id() -> None:
    """Per D-11 + spec §9 layer-1 idempotency: the trigger MUST enqueue
    with `_job_id=f"enqueue_followup_study:{study_id}"` so Arq drops
    duplicate deliveries at the queue level."""
    digest_src = Path("backend/workers/digest.py").read_text()
    # Either single or double quotes are valid Python; accept both.
    pattern_a = 'f"enqueue_followup_study:{study_id}"'
    pattern_b = "f'enqueue_followup_study:{study_id}'"
    assert pattern_a in digest_src or pattern_b in digest_src, (
        "Story 2.2 trigger must use the deterministic _job_id "
        "f'enqueue_followup_study:{study_id}' for Arq queue-level dedup (D-11). "
        "Without it, retries would create duplicate children."
    )


def test_trigger_failure_events_use_digest_followup_prefix() -> None:
    """Per cycle-1 finding C1-5 + cycle-2 C2-3: failure-warning events
    emitted by the digest trigger MUST use the `digest_followup_*`
    event_type prefix (NOT `auto_followup_*`). Keeping the trigger's
    warning events out of the `auto_followup_*` namespace preserves the
    FR-9 8-event catalog's exact count."""
    digest_src = Path("backend/workers/digest.py").read_text()
    # The two failure-warning event_types from the trigger block:
    assert 'event_type="digest_followup_enqueue_pool_missing"' in digest_src, (
        "Story 2.2 trigger missing digest_followup_enqueue_pool_missing event "
        "(emitted when ctx['arq_pool'] is None). Per C1-5 the prefix MUST be "
        "`digest_followup_*` not `auto_followup_*` to preserve the FR-9 catalog."
    )
    assert 'event_type="digest_followup_enqueue_failed"' in digest_src, (
        "Story 2.2 trigger missing digest_followup_enqueue_failed event "
        "(emitted when arq_pool.enqueue_job raises). Per C1-5 the prefix MUST "
        "be `digest_followup_*` not `auto_followup_*`."
    )


def test_trigger_lands_after_digest_complete_log() -> None:
    """The trigger fires on the success path only — after digest_complete
    is logged. Trigger placement before the success log would mean it
    fires on early-return paths too (zero-trials, budget-exceeded, etc.),
    which would silently violate the spec's "only on completion" contract."""
    digest_src = Path("backend/workers/digest.py").read_text()
    # The digest_complete log must appear before the auto-followup trigger
    # comment in source order.
    complete_pos = digest_src.find('event_type="digest_complete"')
    trigger_pos = digest_src.find("feat_auto_followup_studies Story 2.2")
    assert complete_pos != -1, "digest_complete log not found"
    assert trigger_pos != -1, "Story 2.2 trigger block not found"
    assert complete_pos < trigger_pos, (
        "Story 2.2 trigger appears BEFORE the digest_complete success log — "
        "would fire on early-return paths too. Move the trigger to land after "
        "the success log."
    )
