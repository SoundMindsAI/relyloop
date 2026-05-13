# Bug fix — bug_digest_param_importance_seam

**Source idea:** [idea.md](./idea.md)
**Branch:** `fix/digest-param-importance-sklearn-dep`
**Type:** bug fix — medium (design surface in triage; small in code)
**Date:** 2026-05-13
**Mode:** Default — all 6 phases.

## Problem

`feat_digest_proposal` AC-7 ([feature_spec.md §AC-7](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/feature_spec.md#L309)) requires `digests.parameter_importance` to contain entries for every continuous param, with values summing to ~1.0. In production today **every digest's `parameter_importance` is silently `{}`** — `optuna.importance.get_param_importances()` defaults to `FanovaImportanceEvaluator` which `import sklearn` internally; the api/worker image has no `scikit-learn`; the call raises `ImportError`; the worker's broad `except Exception` at [digest.py:538-546](../../../../backend/workers/digest.py#L538-L546) catches it and returns `{}`. The misleading `assert parameter_importance is not None` at [test_digest_generate.py:65](../../../../backend/tests/integration/test_digest_generate.py#L65) passes because `{}` is not None, and the dedicated AC-7 test is `xfail`-marked, so CI is green while the contract is broken.

## Reproduction

```bash
# Inside api container (Postgres is internal-only):
docker exec relyloop-api-1 bash -lc 'cd /app && uv run --with pytest --with pytest-asyncio --with pytest-mock --with pytest-cov \
  pytest backend/tests/integration/test_digest_parameter_importance.py -x -v --runxfail'
# → FAILED with AssertionError: assert set() == {'field_boosts.title', ...}
# → WARN log shows error_type=ImportError, error="No module named 'sklearn'"
```

With `--with scikit-learn` added: PASSES. Confirms sklearn is the missing piece, not a fixture seam.

## Root cause

- **Owning layer:** dependency declaration (`pyproject.toml`) → propagates to the production image build.
- **Origin:** [`pyproject.toml`](../../../../pyproject.toml) declares `optuna>=3.6` but not `scikit-learn`. Optuna 4.8 lists scikit-learn only under its `[optional]` extra (which also pulls boto3/matplotlib/plotly/torch/redis — too broad).
- **The default-evaluator dependency:** `optuna.importance.get_param_importances` instantiates `FanovaImportanceEvaluator()` when `evaluator=None`; the FanovaImportanceEvaluator code path imports sklearn ([`optuna/importance/_fanova/_fanova.py`](https://github.com/optuna/optuna/blob/v4.8.0/optuna/importance/_fanova/_fanova.py) — `from sklearn... import RandomForestRegressor`).
- **Why it stayed silent:** the worker's broad `except Exception` at [`backend/workers/digest.py:538-546`](../../../../backend/workers/digest.py#L538-L546) catches ImportError + returns `{}`, AND the happy-path test at [`backend/tests/integration/test_digest_generate.py:65`](../../../../backend/tests/integration/test_digest_generate.py#L65) only asserts `is not None` (which `{}` satisfies), AND the strict AC-7 test was xfail-marked because the idea-author misdiagnosed the failure as a fixture seam.

**The idea's three hypotheses were all wrong.** Test logs show `[I] Using an existing study with name '...' instead of creating a new one` — `load_if_exists=True` correctly resolved the worker's separately-constructed handle to the same RDB row the test seeded. Engine/pool isolation, sampler/pruner mismatch, and schema isolation are not in play.

## Fix design (locked decisions)

1. **Add `scikit-learn>=1.4` as a direct dependency** in `pyproject.toml` `dependencies`. Cites: spec feature_spec.md line 123 calls `get_param_importances` (Fanova default); Optuna's `[optional]` extra is too broad; PedAnova is experimental per Optuna docs and would change importance semantics. Floor `>=1.4` matches the repo's convention of floor-pinning (`optuna>=3.6`, `openai>=1.55`).
2. **Keep the worker's broad `except Exception` at digest.py:538-546.** Cites: defense-in-depth remains useful for legitimate Optuna edge cases (zero-completed-trial studies, schema not initialized). The fix removes the ImportError condition entirely; no worker code change.
3. **Remove the `pytest.mark.xfail(...)` from `test_digest_parameter_importance.py:60-68`.** With sklearn installed the test passes; keeping `xfail strict=False` would let an XPASS-on-some-runs / FAIL-on-others situation hide regressions. Cites: state.md PR #78 lesson — quiet xfail markers are a known masking failure mode in this repo.
4. **Leave `test_digest_generate.py:65` (`assert digest.parameter_importance is not None`) untouched.** Walked back from an earlier draft of this plan. That happy-path test seeds 1 app-DB trial but zero Optuna trials (no `study.tell()`), so the worker's `get_param_importances` legitimately returns `{}` via the zero-trial Optuna branch — the `{}` result there is correct, not a bug-masking artifact. The dedicated AC-7 test is the right regression guard.

## Regression test plan

The previously-xfail'd test becomes the primary regression guard. No new test required.

| Layer | Path | What it asserts |
|---|---|---|
| integration | `backend/tests/integration/test_digest_parameter_importance.py` | All 4 declared continuous param keys present in `digests.parameter_importance`; values are floats in `[0.0, 1.0]`; sum ≈ 1.0. Fails on `main` (ImportError → `{}`); passes on this branch. |

## Rollout

- **uv.lock churn:** running `uv lock` will pull `scikit-learn` + transitive `scipy` + `joblib` + `threadpoolctl`. numpy is already in the lock as an Optuna transitive dep. Image growth: ~30-40MB.
- **Dockerfile:** no change. The image builds via `uv sync --frozen` which picks up the new dep automatically.
- **Migrations:** none.
- **Feature flag:** none. Additive dep — runtime behavior changes from silent `{}` to populated map on every digest going forward.
- **Operator action:** none. After this PR merges, all newly-completed studies produce digests with the full AC-7 importance map. Already-shipped digests with `parameter_importance = {}` stay as-is (re-running the worker would overwrite them, but that's not part of this fix).

## Tangential observations

- The misdiagnosed root cause in the original idea.md is a process lesson: **always read the WARN log's `error_type` field before designing the fix.** The structlog line at [`digest.py:540-545`](../../../../backend/workers/digest.py#L540-L545) explicitly emits `error_type=ImportError, error="No module named 'sklearn'"` — the idea-author assumed `ValueError` without checking. Not capturing this as an idea file; it's a one-time lesson, not a follow-up.
- No other tangential bugs surfaced.

---

**Default-mode completion:** bug_fix.md written, branch `fix/digest-param-importance-sklearn-dep` ready for code + commit (next step) → `/impl-execute --ad-hoc` to ship.
