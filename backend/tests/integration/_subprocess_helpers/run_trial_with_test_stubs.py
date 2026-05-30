# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Subprocess entrypoint for partial-failure tests (Story 3.1 / AC-8b).

Pytest monkeypatches do NOT survive into a fresh Python interpreter, so the
``test_run_trial_partial_failure.py`` tests cannot use the parent's stubs.
This helper script reinstalls the test doubles (qrels loader + stub adapter)
inside the child process from env-var-passed JSON, then invokes
``run_trial`` with ``INFRA_OPTUNA_EVAL_FAULT`` set by the parent.

Environment variables:

* ``INFRA_OPTUNA_EVAL_TEST_QRELS_JSON`` — JSON blob, deserialized into the
  qrels dict returned by the monkeypatched ``load_qrels``.
* ``INFRA_OPTUNA_EVAL_TEST_HITS_JSON`` — JSON blob mapping ``query_id`` →
  list of ``[doc_id, score]`` pairs; returned by the stub adapter's
  ``search_batch``.
* ``INFRA_OPTUNA_EVAL_TEST_STUDY_ID`` — UUID of the app study row.
* ``INFRA_OPTUNA_EVAL_TEST_TRIAL_NUMBER`` — pre-allocated Optuna trial number.
* ``INFRA_OPTUNA_EVAL_FAULT`` — fault seam name (forwarded into the worker's
  os._exit logic).

The script exits 0 on normal completion, 1 on ``os._exit(1)`` from a seam,
and a non-1 non-zero code on any other failure (test should fail loud).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any
from unittest.mock import AsyncMock


async def _main() -> None:
    qrels_json = os.environ["INFRA_OPTUNA_EVAL_TEST_QRELS_JSON"]
    hits_json = os.environ["INFRA_OPTUNA_EVAL_TEST_HITS_JSON"]
    study_id = os.environ["INFRA_OPTUNA_EVAL_TEST_STUDY_ID"]
    trial_number = int(os.environ["INFRA_OPTUNA_EVAL_TEST_TRIAL_NUMBER"])

    qrels: dict[str, dict[str, int]] = json.loads(qrels_json)
    hits_raw: dict[str, list[tuple[str, float]]] = json.loads(hits_json)

    # Build a stub adapter inline (can't import the fixture module's
    # StubAdapter because of the path setup); use a tiny class here.
    from backend.app.adapters.protocol import ScoredHit
    from backend.tests.integration.fixtures.stub_adapter import StubAdapter

    hits_response: dict[str, list[ScoredHit]] = {
        qid: [ScoredHit(doc_id=d, score=s) for d, s in pairs] for qid, pairs in hits_raw.items()
    }
    stub = StubAdapter(search_batch_response=hits_response)

    # Patch the worker module's external dependencies BEFORE importing run_trial
    # (so the import-time bindings see the stubs).
    import backend.workers.trials as trials_mod

    # Mypy is strict about replacing module-level functions with mocks; the
    # runtime contract is fine because trials_mod is the source of those
    # bindings (it imports build_adapter and load_qrels from elsewhere). We
    # use ``setattr`` to bypass attribute-typing for the override.
    setattr(trials_mod, "build_adapter", lambda _c: stub)  # noqa: B010
    setattr(trials_mod, "load_qrels", AsyncMock(return_value=qrels))  # noqa: B010

    # Seed ctx with a real Optuna storage; the helper script does what
    # WorkerSettings.on_startup would do.
    from backend.app.core.settings import get_settings
    from backend.app.eval.optuna_runtime import build_storage

    storage = build_storage(get_settings().database_url)
    ctx: dict[str, Any] = {"optuna_storage": storage}

    await trials_mod.run_trial(ctx=ctx, study_id=study_id, optuna_trial_number=trial_number)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"helper failed: {exc}", file=sys.stderr)
        sys.exit(2)
