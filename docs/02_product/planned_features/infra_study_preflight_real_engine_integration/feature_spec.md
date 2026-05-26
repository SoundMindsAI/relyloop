# Feature Specification — infra_study_preflight_real_engine_integration

**Date:** 2026-05-25
**Status:** Draft
**Owners:** RelyLoop maintainers
**Related docs:**
- [idea.md](idea.md)
- Upstream feature: [`feat_study_preflight_overlap_probe`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md) — shipped PR #193, squash-merged as `ca835e0` on 2026-05-22
- [`docs/05_quality/testing.md`](../../../05_quality/testing.md) — test-layer convention + 80% coverage gate
- [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) — local ES reachability + service-container pattern

**Depends on:** [`feat_study_preflight_overlap_probe`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md) — **satisfied** (PR #193, merged 2026-05-22). This is a pure test-infra investment on top of the shipped probe; no product behavior changes.

---

## 1) Purpose

- **Problem:** Integration cases AC-1 through AC-4b in [`backend/tests/integration/test_studies_api.py:791-901`](../../../../backend/tests/integration/test_studies_api.py#L791-L901) currently exercise the `POST /api/v1/studies` overlap-probe threshold logic by monkeypatching `backend.app.api.v1.studies.probe_judgment_overlap` to return fabricated `OverlapProbeResult` values. They lock the cap-aware formula `overlap < min(MIN_OVERLAP, max(judged_doc_count, 1))` and the 422 envelope shape, but they never invoke the real probe end-to-end. The actual SQL round-trips (`find_first_judged_query`, `count_judgments_for_list_and_query`, `list_doc_ids_for_list_and_query`), the `acquire_adapter()` build, and the `_search` round-trip against a real index are all stubbed away. The dict-key unpacking + adapter-call-shape locking IS already covered by AC-10 + AC-11 via `_FakeProbeAdapter` capture, so the adapter-Protocol contract is verified — but the chain "real DB rows → real `ids`-query → real ES `_search` decode → real `OverlapProbeResult`" is unverified.
- **Outcome:** Replace AC-1 through AC-4b with real-engine variants that (a) seed `judgments.doc_id` rows for a representative query, (b) bulk-index a controlled subset of those `doc_id` values into the ES service-container index, (c) POST `/api/v1/studies` against a cluster whose `base_url` points at the real ES, and (d) assert the same 422/201 outcomes the monkeypatch versions assert today. AC-10 + AC-11 stay as adapter-call-shape locks (different bug class). The change is invisible to product users — the value is hardening the regression boundary against drift in the probe → repo → adapter chain.
- **Non-goal:** Adding `bulk_index` to the `SearchAdapter` Protocol. The Protocol is engine-agnostic *query-time* search; bulk-indexing is a test-time concern that does not generalize across `ElasticAdapter` + future `FusionAdapter` (Fusion's bulk-index surface differs structurally). Locked at idea D-1.

## 2) Current state audit

### Existing implementations

- **[`backend/tests/integration/test_studies_api.py:791-901`](../../../../backend/tests/integration/test_studies_api.py#L791-L901)** — the five test functions that will be rewritten:
  - `test_post_study_insufficient_overlap_returns_422` (AC-1, lines 791-823)
  - `test_post_study_sufficient_overlap_returns_201` (AC-2, lines 826-840)
  - `test_post_study_overlap_at_threshold_returns_201` (AC-3, lines 843-860)
  - `test_post_study_overlap_one_below_threshold_returns_422` (AC-4, lines 863-877)
  - `test_post_study_cap_aware_threshold_allows_small_judgment_lists` (AC-4b, lines 880-900)

  Each currently calls `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)` with a `_make_fake_probe_result(...)` stub (helper at lines 773-788).

- **[`backend/tests/integration/test_studies_api.py:61-115`](../../../../backend/tests/integration/test_studies_api.py#L61-L115)** — `_seed_minimum_for_post_studies()`. Seeds a cluster row with `base_url="http://stub:9200"`, `auth_kind="es_basic"`, `credentials_ref="ref"` (an opaque string NOT present in CI's mounted `cluster_credentials.yaml`), and a judgment list with `target="stub-index"`. This fixture stays; a new sibling fixture introduced by this feature returns IDs against the real ES cluster.

- **[`backend/tests/integration/test_studies_api.py:740-770`](../../../../backend/tests/integration/test_studies_api.py#L740-L770)** — `_seed_judgments(judgment_list_id, query_set_id, doc_ids)`. Seeds one `queries` row + N `judgments` rows (one per `doc_id`), returns the seeded `query_id`. The real-engine variants reuse this helper unchanged.

- **[`backend/tests/integration/test_studies_api.py:33-58`](../../../../backend/tests/integration/test_studies_api.py#L33-L58)** — the autouse `_default_overlap_probe_passes` fixture. Monkeypatches the probe symbol to a sufficient-result stub on every test in the file. The rewritten tests must override this default by registering a real probe BEFORE the test body executes (see B5).

- **[`backend/tests/integration/test_seed_es.py:37-57`](../../../../backend/tests/integration/test_seed_es.py#L37-L57)** — `_es_base_url()` + the `es_required` skip marker. The canonical pattern for "probe `http://localhost:9200` first (host-shell), fall back to `http://elasticsearch:9200` (in-container)" and skip the test when neither responds. The new fixture reuses this exact pattern by importing the helper.

- **[`backend/app/scripts/seed_es.py:36-114`](../../../../backend/app/scripts/seed_es.py#L36-L114)** — the canonical NDJSON `/_bulk` pattern used by `make seed-es`. The new fixture's bulk-index implementation mirrors the DELETE+PUT+POST-`/_bulk` shape (lines 49-91), scoped to the per-test index name + the small per-test doc set (no chunking — test doc counts stay under 250).

- **[`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml)** "Seed cluster credentials" step — bakes the YAML mapping `local-es: {username: elastic, password: changeme}` into `./secrets/cluster_credentials.yaml` so the api container's `CLUSTER_CREDENTIALS_FILE` resolves `local-es` to a usable credential. The new real-engine cluster row this feature seeds MUST use `credentials_ref="local-es"` (NOT the existing fixture's `"ref"` opaque string) so `acquire_adapter()` reaches the real ES.

- **[`backend/app/services/cluster.py:233-260`](../../../../backend/app/services/cluster.py#L233-L260)** — `acquire_adapter()`. Raises `ClusterUnreachable` when `CredentialsMissing` is raised during adapter construction. The real-engine fixture relies on CI's `local-es` YAML entry being present; locally, operators must have `./secrets/cluster_credentials.yaml` populated by `bash scripts/install.sh` (already a `make up` prerequisite).

- **[`backend/app/services/study_preflight.py:66-184`](../../../../backend/app/services/study_preflight.py#L66-L184)** — `probe_judgment_overlap(...)`. The real probe the rewritten tests exercise end-to-end. No changes to this module.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (no URL/route changes — test infra only) | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", ...)` in AC-1..AC-4b | 5 | Replace each with the real-engine variant per FR-1. The monkeypatch lines at 806, 836, 857, 873, 897 are removed; the test bodies seed ES + assert against the real probe. |
| `backend/tests/integration/test_studies_api.py` | The autouse `_default_overlap_probe_passes` fixture (lines 33-58) | 1 | No change — the rewritten tests opt out via the same pattern AC-7/8/10/11 use (`monkeypatch.setattr` to bind back to the real `study_preflight.probe_judgment_overlap`). |
| `backend/tests/integration/test_studies_api.py` | AC-5 (FK short-circuit), AC-6 (Tier-1 mismatch), AC-7..AC-9 (probe-skipped / empty-judgments paths), AC-10, AC-11 (adapter-call-shape locks), AC-12 (read-path tolerance), AC-13 (FR-4 exception matrix) | 9 | **No change.** These exercise different boundaries that the real-engine rewrite does not subsume. |
| `backend/tests/contract/test_studies_error_codes.py` | `INSUFFICIENT_JUDGMENT_OVERLAP` contract assertions | 1 | No change — the 422 envelope shape is unchanged. |
| `backend/tests/unit/services/test_study_preflight.py` | Unit-level probe orchestration tests (mocked adapter, mocked repo) | 4 | No change — these stay as the fast inner-loop coverage. |

### Existing behaviors affected by scope change

- **Test execution time:** Current: AC-1..AC-4b run in milliseconds (monkeypatch returns fakes synchronously). New: each adds one DELETE + one PUT + one `/_bulk` + one `_refresh` + one `_search` round-trip to ES, plus the existing 3 SQL SELECTs in the real probe. Expected per-test latency: 200-400 ms on the CI service-container ES. Aggregate budget addition: ~1-2 s across 5 tests. **Decision needed: no** — well under the integration suite's existing minute-scale budget.
- **Host-shell test runs (no ES container):** Current: AC-1..AC-4b pass because the monkeypatch makes ES unnecessary. New: the 5 rewritten tests skip via `@es_required` when neither `http://localhost:9200` nor `http://elasticsearch:9200` responds. **Decision needed: no** — matches the existing `test_seed_es.py` pattern and `docs/03_runbooks/local-dev.md` guidance ("integration tests requiring ES skip cleanly off the host shell").
- **Operator-visible product behavior:** Current and new are identical. The probe + 422 envelope are byte-for-byte unchanged.

---

## 3) Scope

### In scope

- **(B1a) New shared reachability helper** `backend/tests/integration/fixtures/es_reachability.py` (~30 LOC) — extracted from `test_seed_es.py` to break the anti-pattern of importing a test-collected module from a helper. Exports:
  - `_es_base_url() -> str` — verbatim move of the existing helper at `test_seed_es.py:37-47` (probe `localhost:9200` then `elasticsearch:9200`, return `""` on failure).
  - `es_required` — verbatim move of the existing `pytest.mark.skipif(not _es_base_url(), reason="...")` marker.

  **Refactor side-effect**: `backend/tests/integration/test_seed_es.py` MUST be updated to `from backend.tests.integration.fixtures.es_reachability import _es_base_url, es_required` at the top, removing the original definitions (lines 37-57). The module-level `ES_URL = _es_base_url()` assignment + the `cleanup_index` fixture stay in place.

- **(B1b) New fixture helper module** `backend/tests/integration/fixtures/es_overlap_probe.py` (~120 LOC) exposing:
  - `_es_base_url` + `es_required` — re-exports from `fixtures.es_reachability` (`from .es_reachability import _es_base_url, es_required`).
  - `async def seed_minimum_for_overlap_probe_real_engine() -> dict[str, str]` — sibling to `_seed_minimum_for_post_studies()`. Acquires its own DB session via `get_session_factory()` (mirroring the existing helper's pattern at [`test_studies_api.py:62-64`](../../../../backend/tests/integration/test_studies_api.py#L62-L64)) — does NOT accept `db: AsyncSession` as an argument; the helper opens and commits its own session. Seeds a cluster with `base_url=<resolved ES URL>`, `auth_kind="es_basic"`, `credentials_ref="local-es"` (matching CI's mounted YAML; locally requires `./secrets/cluster_credentials.yaml` populated by `bash scripts/install.sh`); a query_set; a judgment_list with `target=<per-test unique index name>`; a query_template. **Returns exactly six keys**: `{cluster_id, template_id, query_set_id, judgment_list_id, target_index, es_base_url}`. The first four match `_seed_minimum_for_post_studies()`'s return shape; `target_index` is the per-test uuid-suffixed index name; `es_base_url` is the resolved ES URL (so callers don't probe twice and the URL the cluster row points at is byte-identical to the URL the helper writes to). Callers MUST use the returned `es_base_url` value when invoking `bulk_index_overlap_probe_docs(...)`.
  - `async def bulk_index_overlap_probe_docs(es_base_url: str, target_index: str, doc_ids: list[str]) -> None` — DELETE the index (idempotent — accept 200 or 404), PUT it with a minimal mapping (`{"properties": {"_id_marker": {"type": "keyword"}}}` — the probe only needs `_id`, so any mapping that accepts the `_id` field is sufficient). **If `doc_ids` is empty**, SKIP the `/_bulk` step entirely (an empty NDJSON body is malformed and ES returns 400 `parse_exception: request body is required`) and proceed directly to `_refresh`, leaving the index empty but searchable. **If `doc_ids` is non-empty**, POST one `/_bulk` body with N `{"index": {"_index": <target>, "_id": <doc_id>}}` header + minimal document body lines (`{"_id_marker": "ok"}` per doc), then POST `/<target>/_refresh` to make the documents visible to the immediately-following `_search`. Wraps the same httpx pattern as `seed_es.py:48-91` but scoped to the per-test index — no chunking (test doc counts stay under 250), and no basic-auth headers (per the established `seed_es.py` precedent the CI ES service container at [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml) runs with `xpack.security.enabled: "false"` and CLAUDE.md "Do not install ES + OpenSearch with security plugins enabled in the local Compose" rule guarantees the same locally).
  - `async def delete_overlap_probe_index(es_base_url: str, target_index: str) -> None` — DELETE the per-test index, idempotent (200 or 404 both accepted). **MUST** swallow transport-level errors (`httpx.HTTPError`, `httpx.ConnectError`, `httpx.TimeoutException`) — log a WARN via the same module-level structlog logger and return normally; do NOT re-raise. Rationale: this helper runs in `finally:` blocks where re-raising would mask the original test failure (e.g., a probe-assertion failure followed by ES going down would surface as `ConnectError` instead of `AssertionError`). The 32-hex uuid suffix provides isolation; cleanup is best-effort, not the line of defense.

- **(B2) Per-test index naming.** Each rewritten test owns an index name `overlap-probe-test-<32-hex>` where `<32-hex>` is the full `uuid.uuid4().hex` (128 random bits → collision probability negligible for any realistic CI run rate). The name is generated at fixture entry, included in the seeded `judgment_list.target` and the POST `/studies` body. Rationale: tests can run in parallel (pytest-xdist) without colliding on a shared index name in practice, and one test's cleanup failure cannot poison the next test's assertions. ES enforces a 255-char index name limit; `overlap-probe-test-<32-hex>` is 51 chars, well under.

- **(B3) Rewrite AC-1 through AC-4b** in `backend/tests/integration/test_studies_api.py` to use the real-engine fixture. The five test functions stay in the same file, retain the same docstrings + AC# references, but their bodies become:
  1. `ids = await seed_minimum_for_overlap_probe_real_engine()` (returns `target_index` + `es_base_url` plus the existing 4 IDs).
  2. Open the `try: ... finally: await delete_overlap_probe_index(ids["es_base_url"], ids["target_index"])` block IMMEDIATELY after step 1 — the index name exists in the cluster row from step 1's `seed_minimum_for_overlap_probe_real_engine()` even though PUT hasn't run yet, and `delete_overlap_probe_index` accepts 404 cleanly. This guarantees cleanup runs even if `_seed_judgments` or `bulk_index_overlap_probe_docs` raises mid-call.
  3. Inside the `try:` — `await _seed_judgments(ids["judgment_list_id"], ids["query_set_id"], doc_ids_in_judgments)` (existing helper, unchanged).
  4. Inside the `try:` — `await bulk_index_overlap_probe_docs(ids["es_base_url"], ids["target_index"], doc_ids_in_index)` — the controlled overlap subset.
  5. Inside the `try:` — Override the autouse `_default_overlap_probe_passes` by re-binding the symbol back to the real probe: `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", study_preflight.probe_judgment_overlap)`. (Same pattern as AC-13 service-layer at lines 1293-1296.)
  6. Inside the `try:` — `resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids, target=ids["target_index"]))` and assert status + envelope.

- **(B4) Per-test (`doc_ids_in_judgments`, `doc_ids_in_index`) tuples lock the 5 cap-aware scenarios:**
  | Test | `doc_ids_in_judgments` | `doc_ids_in_index` | Real overlap | `judged_doc_count` | `required = min(3, max(jdc,1))` | Expected status |
  |---|---|---|---|---|---|---|
  | AC-1 | 50 distinct `"doc_<NNN>"` IDs | 0 (none indexed) | 0 | 50 | min(3, 50)=3 | 422 |
  | AC-2 | 50 distinct IDs | all 50 | 50 | 50 | 3 | 201 |
  | AC-3 | 5 IDs | first 3 | 3 | 5 | 3 | 201 (boundary `>=`) |
  | AC-4 | 5 IDs | first 2 | 2 | 5 | 3 | 422 (`2 < 3`) |
  | AC-4b | 2 IDs | both 2 | 2 | 2 | min(3, 2)=2 | 201 (cap-aware) |

  The exact `judged_doc_count` per test must match the count of `judgments` rows seeded for the representative qid (the only qid). The exact `overlap_size` must equal the intersection of `doc_ids_in_judgments` ∩ `doc_ids_in_index`. The test assertions stay byte-identical to the current monkeypatch versions: the 422 message check `"X of Y probed"` + `"judged_doc_count=Z"`, the `INSUFFICIENT_JUDGMENT_OVERLAP` error_code, the `retryable: false` flag.

- **(B5) Override the autouse passing-probe.** Each rewritten test re-binds `backend.app.api.v1.studies.probe_judgment_overlap` to `backend.app.services.study_preflight.probe_judgment_overlap` (the real symbol). This is the established pattern at lines 1293-1296 of the existing AC-13 service-layer test. The autouse fixture only covers tests that DON'T rebind — the rewritten tests opt in to the real probe by rebinding back to the real symbol.

- **(B6) Skip behavior.** All 5 rewritten tests carry `@es_required` (the marker imported from `backend.tests.integration.fixtures.es_reachability` per B1a). When `_es_base_url()` returns `""` (neither `http://localhost:9200` nor `http://elasticsearch:9200` reachable), all 5 skip with reason `"Elasticsearch not reachable on localhost:9200 or elasticsearch:9200 — see docs/03_runbooks/local-dev.md."`. This matches `test_seed_es.py`'s existing behavior (now itself importing from the shared module).

- **(B7) Documentation refresh.**
  - Update [`docs/05_quality/testing.md`](../../../05_quality/testing.md) §"Integration test mocking policy" with one line noting that AC-1..AC-4b of `feat_study_preflight_overlap_probe` now run end-to-end via a dedicated test-only bulk-index helper (citing this feature's `feature_spec.md`) and that bulk-index is intentionally NOT in the `SearchAdapter` Protocol per D-1.
  - Update [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) §"Running integration tests locally" to note that the new tests require ES reachable at `localhost:9200` and skip cleanly otherwise — same gate as `test_seed_es.py`.

### Out of scope

- **Adding `bulk_index` (or any write method) to `SearchAdapter` Protocol.** Locked at idea D-1; rationale repeated in §4 Anti-patterns.
- **OpenSearch coverage at this layer.** Locked at idea D-2 — OpenSearch's `_msearch` body shape is already covered by the parametrized adapter unit tests at [`backend/tests/unit/adapters/test_elastic_engine_branch.py:43-127`](../../../../backend/tests/unit/adapters/test_elastic_engine_branch.py#L43-L127) (mocked HTTP handlers, both `engine_type` values) and [`backend/tests/unit/adapters/test_elastic_msearch.py`](../../../../backend/tests/unit/adapters/test_elastic_msearch.py). The `ids`-query body the probe ships is wire-compatible across ES and OpenSearch; running the same probe scenarios against OpenSearch's real engine would double CI runtime without exercising any new code path.
- **Migrating AC-10, AC-11 (adapter-call-shape locks) to real-engine.** They lock the `NativeQuery` body shape + `search_batch` kwargs via captured kwargs on `_FakeProbeAdapter`. A real-engine variant would not validate the same kwargs (the real adapter doesn't expose them post-`search_batch`), so the value-to-cost ratio is unfavorable. They stay as-is.
- **Migrating AC-5, AC-6 (short-circuit paths) to real-engine.** They specifically assert the probe is NOT invoked. A real-engine variant would have no observable difference and add ES round-trips that prove a negative.
- **Migrating AC-7, AC-8, AC-9 (probe-skipped + empty-judgments paths) to real-engine.** AC-7/8 exercise specific exception classes (`ClusterUnreachableError`, `QueryTimeoutError`) that require injecting failure modes the real ES service container does not naturally produce on demand. AC-9 exercises the empty-judgments short-circuit which never invokes the adapter. Synthetic failure injection via `_FakeProbeAdapter` is the right tool here; real-engine adds no signal.
- **Replacing the autouse `_default_overlap_probe_passes` fixture with a real probe.** The fixture exists so the 30+ pre-overlap-probe tests in `test_studies_api.py` (testing study POST, cancel, GET-trials, etc.) don't have to seed ES + judgments to satisfy the new probe gate. Replacing it would force every unrelated test to maintain ES state — out of scope.
- **Migration / new DB columns.** None — the change is test-infra-only.
- **Audit-event emission.** Pre-MVP2 — not applicable.

### API convention check

- **Endpoint prefix:** N/A. No new endpoints; the rewritten tests still POST `/api/v1/studies` (existing).
- **Router file:** `backend/app/api/v1/studies.py` — unchanged.
- **Non-auth error envelope shape:** Unchanged. The `INSUFFICIENT_JUDGMENT_OVERLAP` 422 envelope at `backend/app/services/study_preflight.py` → caller in [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) is byte-identical to today: `{"detail": {"error_code": "INSUFFICIENT_JUDGMENT_OVERLAP", "message": "<human>", "retryable": false}}`.
- **Auth error shape:** N/A — MVP1.

### Phase boundaries

Single phase. Test-infra-only feature; one PR.

## 4) Product principles and constraints

- **Test value over test pageantry.** The point of the rewrite is to lock the real probe → repo → adapter → ES chain. If a test's assertion would be identical against a fake (e.g., the 422 envelope shape), keep the fake; replace only the assertions that uniquely benefit from real ES.
- **Tests skip cleanly off the host shell.** The `@es_required` marker is mandatory. Operators running `make test-integration` without `docker compose up -d elasticsearch` first must see "skipped" with a clear reason, not a connection error.
- **Per-test index isolation.** Each test owns a uuid-suffixed index name. No shared `overlap-probe-test` index across tests; no shared state across runs.
- **Cleanup is best-effort.** A test failure must not leak an ES index that poisons the next test. Use `try: ... finally: await delete_overlap_probe_index(...)`. If DELETE itself fails (ES down mid-test), the per-test uuid suffix isolates the damage — the next test's unique name avoids the leaked one.
- **Credentials per the established mounted-YAML pattern.** The new cluster row uses `credentials_ref="local-es"` matching CI's `secrets/cluster_credentials.yaml` entry and `bash scripts/install.sh`'s local equivalent. No bare env-var credentials per Absolute Rule #2.
- **Engine-specific code lives in the test fixture's httpx client, NOT in the `SearchAdapter` Protocol.** Per CLAUDE.md Absolute Rule #4 + idea D-1. **Why this is consistent with Rule #4:** the rule says "engine-specific *production* code lives only in `backend/app/adapters/<engine>.py`". Two established precedents already use raw httpx against ES outside the adapters module for analogous purposes: (a) [`backend/app/scripts/seed_es.py`](../../../../backend/app/scripts/seed_es.py) (an operator script, not a service), and (b) [`backend/tests/integration/test_seed_es.py:37-47`](../../../../backend/tests/integration/test_seed_es.py#L37-L47) (test setup, not product code). The new fixture follows pattern (b).

### Anti-patterns

- **Do not** add `bulk_index` (or any write method) to `SearchAdapter` Protocol. Bulk-index is a test-time concern; the Protocol's role is engine-agnostic query-time search. Putting bulk-index on the Protocol would force `FusionAdapter` (MVP3) to implement a method it never uses in production. Locked at idea D-1.
- **Do not** share an ES index name across the 5 rewritten tests. A single shared `overlap-probe-test` index forces serial ordering, breaks pytest-xdist, and makes one test's cleanup failure cascade to the next test. Always use a per-test uuid suffix.
- **Do not** rely on the autouse `_default_overlap_probe_passes` fixture continuing to monkeypatch the probe — explicitly rebind to the real probe symbol in each rewritten test. Future edits to the autouse fixture must not silently re-stub the probe these tests rely on running for real.
- **Do not** skip the `_refresh` call after `/_bulk`. ES indexes documents to a buffer that is not immediately searchable; `_search` will return zero hits unless `/<index>/_refresh` is POSTed first. The `seed_es.py:106` pattern is the reference.
- **Do not** assert against ES log content, latency, or operational state — only against the POST `/studies` response envelope. The tests verify product behavior, not ES internals.
- **Do not** parallel-run the rewritten tests against a shared OpenSearch instance "for symmetry". OpenSearch coverage at the `search_batch` layer is satisfied via the existing adapter Protocol contract tests; doubling here adds CI minutes without bug-class coverage.

## 5) Assumptions and dependencies

- **Dependency:** Elasticsearch 8.11+ / 9.x service container in CI.
  - Why required: the rewritten tests issue real `_search` calls; the `ids` query, `_bulk` body shape, and `_refresh` semantics must match production ES behavior. The CI service container is already configured at `elasticsearch:9.4.0` in [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml).
  - Status: implemented — CI service container exists and is reachable at `elasticsearch:9200` from within the runner.
  - Risk if missing — local: tests skip cleanly via `@es_required`, no false-positive failure. Risk if missing — CI: the FR-8 sentinel test FAILS loudly (it does NOT carry `@es_required`); silent CI skip is explicitly NOT a tolerated outcome. The 5 rewritten tests still carry `@es_required` to keep local skips clean, but the sentinel acts as the CI gate.
- **Dependency:** `./secrets/cluster_credentials.yaml` with a `local-es:` entry.
  - Why required: `acquire_adapter()` calls `resolve_credentials()` which reads this mounted file; the new cluster row's `credentials_ref="local-es"` resolves to the basic-auth credentials.
  - Status: implemented — CI writes the file in the workflow's "Seed cluster credentials" step; locally `bash scripts/install.sh` generates an equivalent entry (or `make seed-clusters` provides defaults). See [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md).
  - Risk if missing: `acquire_adapter()` raises `CredentialsMissing` → `ClusterUnreachable`; the probe falls through with a `reason="unreachable"` WARN log and returns `None`. The handler then accepts the study (the FR-4 fall-through path), and the test assertion of "422 expected" fails. The `@es_required` skip marker does NOT catch this case (it only checks reachability of `_es_base_url()`, not credentials availability). The fixture MUST raise a clear `pytest.skip(...)` if the credentials YAML doesn't contain `local-es` — see FR-6.
- **Dependency:** Postgres service container (already required by every integration test).
  - Why required: real probe runs 3 SELECTs against `queries` + `judgments`.
  - Status: implemented.
  - Risk if missing: existing `pytestmark = [..., pytest.mark.skipif(not postgres_reachable(), ...)]` (lines 24-30) handles this.

## 6) Actors and roles

- **Primary actor(s):** CI pipeline (GitHub Actions) + local developer running `make test-integration`. No end-user actor.
- **Role model:** N/A — single-tenant install, no auth surface.
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface (MVP1 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md). Test-infra-only feature in any case.

## 7) Functional requirements

### FR-1: Real-engine rewrite of AC-1..AC-4b
- Requirement:
  - The system **MUST** rewrite the five test functions enumerated in §2 ("Existing implementations") so each invokes the real `probe_judgment_overlap` against a real ES index whose document set is controlled by `bulk_index_overlap_probe_docs`.
  - The rewritten tests **MUST** assert the same HTTP status, `error_code`, and message-substring conditions as the current monkeypatch versions. The 422-message substring assertions (`"X of Y probed"`, `"judged_doc_count=Z"`) **MUST** stay verbatim — these are the user-visible message format locks.
  - The rewritten tests **MUST NOT** carry `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", ...)` calls binding to a `_make_fake_probe_result(...)` stub. The autouse default-passing-probe fixture is overridden by re-binding to the real symbol, not by stubbing.
- Notes: see B3 + B4 for the exact rewrite pattern + the 5 per-test data tuples.

### FR-2: Dedicated test-only bulk-index helper, not on the Protocol
- Requirement:
  - The bulk-index helper `bulk_index_overlap_probe_docs` **MUST** live in `backend/tests/integration/fixtures/es_overlap_probe.py` (a new module). It **MUST** import `httpx` directly and construct its own `httpx.AsyncClient` against the resolved ES base URL.
  - The `SearchAdapter` Protocol at [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py) **MUST NOT** gain a `bulk_index` method, an `index_doc` method, or any other write-side method as part of this work.
  - When `doc_ids` is non-empty, the helper **MUST** mirror the NDJSON `/_bulk` body shape used by `backend/app/scripts/seed_es.py:77-91` (one header line + one doc line per record, terminated by `"\n"`, with `Content-Type: application/x-ndjson`).
  - When `doc_ids` is empty, the helper **MUST** skip the `/_bulk` POST entirely (an empty NDJSON body returns ES 400 `parse_exception`) and still POST `/<target>/_refresh` to leave the empty index searchable for the immediately-following probe. The empty-`doc_ids` branch is required by AC-1 (zero-overlap → 422 case).
  - The helper **MUST NOT** add basic-auth headers — both CI (`xpack.security.enabled: "false"` at [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml)) and local Compose (per CLAUDE.md "Do not install ES + OpenSearch with security plugins enabled in the local Compose") run ES with security disabled.
- Notes: locked at idea D-1.

### FR-3: ES service-container only
- Requirement:
  - The rewritten tests **MUST** run only against the Elasticsearch service container (or host-bound ES at `localhost:9200`); they **MUST NOT** issue `_bulk` writes to OpenSearch.
  - The `@es_required` skip marker **MUST** decorate all 5 rewritten tests so they skip cleanly when neither `http://localhost:9200` nor `http://elasticsearch:9200` responds within 2 seconds.
- Notes: locked at idea D-2. The `_es_base_url()` probe pattern at `test_seed_es.py:37-47` is the reference.

### FR-4: Per-test index isolation
- Requirement:
  - Each rewritten test **MUST** seed a fresh judgment_list with `target` set to a uuid-suffixed index name `overlap-probe-test-<32-hex>`.
  - Each rewritten test **MUST** `try: ... finally: await delete_overlap_probe_index(...)` to clean up its own index. The delete helper **MUST** accept 200 or 404 as success (idempotent — the index may have failed to create, or a prior cleanup may have already removed it).
- Notes: see B2.

### FR-5: Pre-existing AC coverage stays intact
- Requirement:
  - The 9 other AC test functions (AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13 — adapter-layer and service-layer subsets) **MUST NOT** be modified.
  - The autouse `_default_overlap_probe_passes` fixture (lines 33-58) **MUST NOT** be removed or modified — pre-overlap-probe tests in the file still depend on it.

### FR-6: Fail-loud on missing local-es credentials
- Requirement:
  - `seed_minimum_for_overlap_probe_real_engine()` is a plain async helper (not a pytest fixture) — callers `await` it as the first line of their test body. Before any DB write or HTTP call, it **MUST** call `get_settings().cluster_credentials_yaml` (the `@cached_property` accessor at [`backend/app/core/settings.py:361`](../../../../backend/app/core/settings.py) which reads the path from the `CLUSTER_CREDENTIALS_FILE` env var and returns the **file content** as a YAML string — NOT the path). It **MUST** then `yaml.safe_load(...)` the returned string inside a `try: ... except yaml.YAMLError:` and check whether the resulting mapping contains a top-level `local-es` key.
  - The helper **MUST** route to the skip/RuntimeError fallback when ANY of the following holds: (a) `cluster_credentials_yaml` is `None` (mount missing); (b) `yaml.safe_load` raises `yaml.YAMLError` (malformed YAML); (c) the parsed value is not a `dict`; (d) `"local-es"` is absent from the mapping's top-level keys.
  - Behavior of the fallback: when `os.environ.get("CI") == "true"`, raise `RuntimeError(<message + 'workflow regression — see .github/workflows/pr.yml \"Seed cluster credentials\" step'>)` so CI fails loudly. Otherwise, call `pytest.skip(...)` with a reason matching the substrings `r"local-es"`, `r"cluster_credentials\.yaml"`, AND `r"scripts/install\.sh"` (all three must appear; exact wording free).
  - `pytest.skip(...)` raises `pytest.skip.Exception`, which pytest catches and converts to a skipped result even when raised from a regular async helper.
  - Rationale: without the credentials entry, `acquire_adapter()` raises `CredentialsMissing` → `ClusterUnreachable`, the probe falls through with a WARN log, the handler accepts the study (FR-4 fall-through), and the test's "422 expected" assertion fails with no signal that credentials were the root cause. Explicit skip-with-reason is the correct UX locally; explicit failure is the correct UX in CI.
- Notes: the `@es_required` marker only checks reachability of the ES base URL; it does NOT check credentials availability. Both gates are needed. The credentials check happens before the ES reachability check inside the helper so a clean operator-guidance message wins over a "unreachable" guess.

### FR-7: Match the existing pattern for re-binding the probe symbol
- Requirement:
  - Each rewritten test **MUST** rebind `backend.app.api.v1.studies.probe_judgment_overlap` to `backend.app.services.study_preflight.probe_judgment_overlap` via `monkeypatch.setattr(...)` BEFORE issuing the POST `/api/v1/studies` call. This overrides the autouse `_default_overlap_probe_passes` fixture.
  - The rebind **MUST** target the same symbol path the autouse fixture targets (`backend.app.api.v1.studies.probe_judgment_overlap`, not `backend.app.services.study_preflight.probe_judgment_overlap` directly) — the handler captured the reference at import time, so patching the source location has no effect.
- Notes: same pattern as `test_post_study_fr4_service_layer_cluster_unreachable` at lines 1293-1296.

### FR-8: CI-only sentinels guarantee the real-engine tests don't silently skip
- Requirement:
  - The new helper-smoke test module **MUST** include TWO sentinels, both decorated `@pytest.mark.skipif(os.environ.get("CI") != "true", reason="CI-only sentinel — local runs use @es_required graceful skip")` and **NOTHING ELSE** (no `@es_required` — that would skip the sentinel before its assertion runs):
    1. `test_overlap_probe_real_engine_sentinel` — asserts `_es_base_url() != ""` with a failure message naming the missing service container, the ports it probes (`localhost:9200` and `elasticsearch:9200`), and a pointer to the workflow step that provisions ES ([`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml) — search for `elasticsearch:9.4.0`).
    2. `test_overlap_probe_real_engine_credentials_sentinel` — asserts the mounted YAML contains a `local-es` key (using `yaml.safe_load(get_settings().cluster_credentials_yaml or "{}")`) with a failure message pointing at the workflow's "Seed cluster credentials" step.
  - Rationale: `@es_required` graceful skip is correct off the host shell (no ES expected), but masks a broken CI workflow setup. Two failure modes can silently strip the regression coverage this feature delivers: (a) the CI ES service container fails to start, (b) the CI step that writes `local-es:` to `cluster_credentials.yaml` is removed. Both sentinels turn silent CI skip into loud test failures; FR-6's `RuntimeError`-in-CI branch covers the third pathway (credentials YAML mounted but truncated).
- Notes: see AC-INFRA-7. The sentinels do NOT replace `@es_required` on the 5 rewritten tests; the marker stays so local skips remain clean.

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new endpoints. Existing endpoint exercised:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | Create a study; preflight probe runs as part of validator chain | `INSUFFICIENT_JUDGMENT_OVERLAP` (422), `JUDGMENT_TARGET_MISMATCH` (422), `JUDGMENT_LIST_NOT_FOUND` (404) |

### 7.2 Contract rules

Unchanged from the upstream `feat_study_preflight_overlap_probe` spec. The 422 envelope shape, error_code, and message format are byte-identical.

### 7.3 Response examples

**Success (201) — AC-2, AC-3, AC-4b paths:**
```json
{
  "id": "01990000-0000-7000-8000-000000000000",
  "status": "queued",
  "name": "overlap-probe-<32-hex>",
  "cluster_id": "...",
  "target": "overlap-probe-test-<32-hex>",
  "template_id": "...",
  "query_set_id": "...",
  "judgment_list_id": "...",
  "search_space": {"params": {"bm25_k1": {"type": "float", "low": 0.1, "high": 2.0}}},
  "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
  "config": {"max_trials": 20},
  "trials_summary": {"total": 0, "completed": 0, "running": 0, "failed": 0, "pruned": 0, "best_metric": null}
}
```

**Failure (422) — AC-1, AC-4 paths:**
```json
{
  "detail": {
    "error_code": "INSUFFICIENT_JUDGMENT_OVERLAP",
    "message": "<human-readable: '0 of 50 probed' / 'judged_doc_count=50' / cluster + target + judgment_list names>",
    "retryable": false
  }
}
```

The exact message format is owned by [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) and is verified by the existing `test_studies_error_codes.py` contract test. The rewritten tests assert substrings (`"X of Y probed"`, `"judged_doc_count=Z"`); they do NOT lock the full message format (that's the contract test's job).

### 7.4 Enumerated value contracts

Not applicable — this feature introduces no new filter values, sort keys, status enums, or dropdown options. The `engine_type="elasticsearch"` value used in the new cluster row is already covered by the upstream `EngineType` `Literal` at [`backend/app/adapters/protocol.py:27`](../../../../backend/app/adapters/protocol.py#L27).

### 7.5 Error code catalog

No new error codes. The rewritten tests exercise the existing `INSUFFICIENT_JUDGMENT_OVERLAP` 422 envelope and the standard 201 success envelope.

## 9) Data model and state transitions

### New/changed entities

None — no schema changes, no migration. The rewrite is test-infra-only.

### Required invariants

- **Per-test index name uniqueness (in practice):** every rewritten test's `target` value **MUST** be drawn from `f"overlap-probe-test-{uuid.uuid4().hex}"`. With 128 bits of entropy, the birthday-collision probability for any realistic CI run rate is effectively zero — not a hard combinatorial guarantee, but a practical one strong enough to treat as an invariant.
- **Index cleanup is best-effort but mandatory in `finally`:** if the test body raises, the `finally:` block still runs the DELETE. If DELETE itself raises, the uuid-suffixed naming guarantees the leaked index does not collide with the next test.

### State transitions

N/A.

### Idempotency/replay behavior

The `bulk_index_overlap_probe_docs` helper is idempotent at the index level — it always DELETE-then-PUT-then-`/_bulk`. Re-running the same test against the same index name (e.g., after a debugger pause) would re-seed identically. The uuid suffix means in practice this doesn't happen — each test run gets a fresh index.

## 10) Security, privacy, and compliance

- **Threats:** None new. The test fixture uses ES basic-auth credentials already mounted in CI (`local-es: {username: elastic, password: changeme}`) — the same credentials used by the production-shape integration tests today.
- **Controls:** The credentials YAML is mounted from `./secrets/cluster_credentials.yaml` (Docker secrets / `_FILE` env-var pattern per Absolute Rule #2). Never echoed, never logged.
- **Secrets/key handling:** No new secrets. Reuses `CLUSTER_CREDENTIALS_FILE`.
- **Auditability:** N/A (test-infra; no audit_log writes).
- **Data retention:** Per-test ES indexes are DELETE'd in `finally:` blocks. CI runners are ephemeral. Local dev: leaked indexes (uuid-suffixed) accumulate in `./data/elasticsearch/` over many failed test runs but are harmless — operators can `make reset` or DELETE `/overlap-probe-test-*` directly.

## 11) UX flows and edge cases

N/A — test-infra-only feature with no user-facing surface. There is no UI, no operator-facing command, and no flow to specify.

## 12) Given/When/Then acceptance criteria

### AC-1 (real-engine): zero overlap → 422

- **Given** a registered ES cluster with `credentials_ref="local-es"`, a judgment_list seeded with 50 judgments for a single qid (doc IDs `doc_000`..`doc_049`), and a target index `overlap-probe-test-<32-hex>` that contains ZERO of those doc IDs
- **When** the test POSTs `/api/v1/studies` against that cluster + target with the autouse default-probe overridden back to the real `probe_judgment_overlap`
- **Then** the response is `422` with `detail.error_code == "INSUFFICIENT_JUDGMENT_OVERLAP"`, `detail.retryable is False`, the message contains the substring `"0 of 50 probed"` AND `"judged_doc_count=50"`, AND no `studies` row is inserted
- Example values:
  - Input: 50 seeded judgments, 0 indexed docs, `target="overlap-probe-test-<32-hex>"`
  - Expected: `response.status_code == 422`, `response.json()["detail"]["error_code"] == "INSUFFICIENT_JUDGMENT_OVERLAP"`

### AC-2 (real-engine): full overlap → 201

- **Given** 50 judgments AND the target index contains all 50 doc IDs
- **When** POST `/api/v1/studies`
- **Then** `201`, `response.json()["status"] == "queued"`, the new `studies` row is committed

### AC-3 (real-engine): boundary 3-of-5 → 201

- **Given** 5 judgments AND the target index contains the first 3 doc IDs
- **When** POST `/api/v1/studies`
- **Then** `201`. (Required threshold = `min(3, max(5,1)) = 3`; overlap=3 satisfies `3 >= 3` strict-less-than is FALSE.)

### AC-4 (real-engine): boundary one-below 3 → 422

- **Given** 5 judgments AND the target index contains the first 2 doc IDs
- **When** POST `/api/v1/studies`
- **Then** `422 INSUFFICIENT_JUDGMENT_OVERLAP`. (Required = 3; overlap = 2; `2 < 3` ⇒ reject.)

### AC-4b (real-engine): cap-aware threshold → 201

- **Given** 2 judgments AND the target index contains both 2 doc IDs
- **When** POST `/api/v1/studies`
- **Then** `201`. (Required = `min(3, max(2,1)) = 2`; overlap = 2; `2 >= 2`.)

### AC-INFRA-1: skip when ES unreachable

- **Given** `_es_base_url()` returns `""` (neither `http://localhost:9200` nor `http://elasticsearch:9200` responds within 2s)
- **When** any of the 5 rewritten tests is collected
- **Then** the test is reported as **skipped** with reason matching `"Elasticsearch not reachable on localhost:9200 or elasticsearch:9200"`, exit code 0

### AC-INFRA-2: skip when local-es credentials absent

- **Given** ES is reachable but `cluster_credentials.yaml` lacks a `local-es:` entry (`CredentialsMissing` would be raised by `acquire_adapter()` for any test that gets that far)
- **When** the `seed_minimum_for_overlap_probe_real_engine()` fixture is invoked
- **Then** the test is reported as **skipped** with a reason directing the operator to `bash scripts/install.sh` (NOT a confusing test failure on the 422-expected assertion)

### AC-INFRA-3: per-test index isolation

- **Given** the 5 rewritten tests run in any order, possibly under pytest-xdist
- **When** any one test's `bulk_index_overlap_probe_docs` runs
- **Then** the index name it targets is unique to that test (uuid-suffixed) AND no test's success/failure affects another test's outcome

### AC-INFRA-4: cleanup runs in `finally:` and uuid-suffixing prevents cross-test contamination

- **Given** the test body raises an `AssertionError` between `bulk_index_overlap_probe_docs` and `delete_overlap_probe_index`
- **When** pytest tears down
- **Then** the `finally:` block executes `delete_overlap_probe_index(...)`. WHEN ES remains reachable, a follow-up GET on `/overlap-probe-test-<32-hex>` returns 404. WHEN ES is unreachable mid-test (cleanup itself fails), the per-test uuid suffix guarantees the next test's unique index name avoids the leaked one — no test's outcome depends on another test's cleanup succeeding.

### AC-INFRA-6: missing local-es credentials skip path (FR-6)

- **Given** ES is reachable but `Settings.cluster_credentials_yaml` parses to a mapping that does NOT contain a `local-es:` entry
- **When** `seed_minimum_for_overlap_probe_real_engine()` is invoked
- **Then** the helper raises `pytest.skip.Exception` with a message containing the substring `"local-es"` AND directing the operator to `bash scripts/install.sh`. The POST `/api/v1/studies` call MUST NOT execute (otherwise `acquire_adapter()` would return a degraded `ClusterUnreachable` → silent probe-skip → 201 → confusing 422-vs-201 assertion failure).

### AC-INFRA-7: CI sentinels fail loudly when ES container or local-es credentials missing in CI

- **Given** the workflow is running in CI (`os.environ.get("CI") == "true"`)
- **When** `test_overlap_probe_real_engine_sentinel` runs
- **Then** the test asserts `_es_base_url() != ""` and FAILS loudly (NOT skipped) if false; the failure message names the missing service container, the probed ports, and the workflow file
- **And When** `test_overlap_probe_real_engine_credentials_sentinel` runs
- **Then** the test asserts `"local-es" in yaml.safe_load(get_settings().cluster_credentials_yaml or "{}")` and FAILS loudly (NOT skipped) if false; the failure message names the workflow's "Seed cluster credentials" step
- **And When** the helper `seed_minimum_for_overlap_probe_real_engine()` runs in CI without `local-es` credentials
- **Then** it raises `RuntimeError` (per FR-6 CI branch) — NOT `pytest.skip` — so the per-rewritten-test failure surface is also loud
- **AND When** running off the CI shell (`CI` env var unset or != `"true"`)
- **Then** both sentinels report as skipped (per their `@pytest.mark.skipif`); the helper falls back to `pytest.skip(...)` for missing credentials

### AC-INFRA-5: SearchAdapter Protocol stays unchanged

- **Given** the current `backend/app/adapters/protocol.py` Protocol definition (8 methods + 8 Pydantic types)
- **When** this feature ships
- **Then** `grep -n "bulk_index\|index_doc\|put_doc\|index_bulk" backend/app/adapters/protocol.py` returns no matches AND `git diff main -- backend/app/adapters/protocol.py` shows no changes

## 13) Non-functional requirements

- **Performance:** Aggregate test-suite latency addition: ≤2 seconds across all 5 rewritten tests (each ~200-400 ms incremental). Verified by comparing `pytest backend/tests/integration/test_studies_api.py -k overlap --durations=10` before and after the change.
- **Reliability:** Each test must pass deterministically — no flaky behavior from the `_refresh` call or from `_bulk` partial-failure races. The helper raises on `bulk_resp.json()["errors"] is True` (matching `seed_es.py:93-103`).
- **Operability:** The `@es_required` skip mark + the FR-6 credentials-missing skip mean operators get clear "skipped" messages off the host shell, never confusing failures.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

This feature IS a test rewrite — the "test strategy" is the feature itself. The minimum coverage requirements:

- **Unit tests:** N/A — the rewrite touches no production code.
- **Integration tests:** 5 rewritten cases in `backend/tests/integration/test_studies_api.py` (AC-1..AC-4b real-engine variants).
- **Contract tests:** N/A — `INSUFFICIENT_JUDGMENT_OVERLAP` envelope shape is unchanged; existing `test_studies_error_codes.py` coverage stands.
- **E2E tests:** N/A — no UI surface.

**Additionally**, the new fixture module itself needs minimal smoke coverage:

- `backend/tests/integration/test_es_overlap_probe_helpers.py` (new file, ~140 LOC): six tests —
  - **(a)** `bulk_index_overlap_probe_docs` indexes the expected doc IDs and they're searchable after `_refresh` — carries `@es_required`.
  - **(b)** `bulk_index_overlap_probe_docs` with `doc_ids=[]` PUTs the index, SKIPs `/_bulk`, refreshes, and `/<idx>/_count` returns 0 (FR-2 empty-`doc_ids` branch) — carries `@es_required`.
  - **(c)** `delete_overlap_probe_index` returns cleanly on both 200 (index existed) and 404 (index didn't exist) paths — carries `@es_required`.
  - **(d)** FR-6 / AC-INFRA-6 — a single parametrized test `test_seed_helper_missing_local_es_credentials` with two cases `[("ci_true", "RuntimeError"), ("ci_false", "Skipped")]`. Each case monkeypatches `get_settings().__dict__["cluster_credentials_yaml"]` to a YAML string lacking `local-es:` (e.g., `"unrelated-cluster:\n  username: x\n  password: y\n"`) AND monkeypatches `os.environ["CI"]` to the case-specific value, then calls `seed_minimum_for_overlap_probe_real_engine()` and asserts the expected outcome. **Monkeypatch target is the INSTANCE's `__dict__`** (via `get_settings()`), not the class — `@cached_property` writes to the instance dict on first access, and instance `__dict__` is mutable. Cycle-3 reviewer A-1 caught the original "class `__dict__`" wording was wrong (class `__dict__` is a read-only `mappingproxy`). Does NOT carry `@es_required` (short-circuits before any HTTP call). NOTE — the existing autouse `_restore_settings_mutations` conftest fixture at [`backend/tests/integration/conftest.py:18-26`](../../../../backend/tests/integration/conftest.py) already snapshots+restores `settings.__dict__` mutations across tests; this test relies on that fixture.
  - **(e)** FR-8 / AC-INFRA-7 — CI sentinel `test_overlap_probe_real_engine_sentinel` that asserts `_es_base_url() != ""`. Decorated **only** with `@pytest.mark.skipif(os.environ.get("CI") != "true", reason="CI-only sentinel — local runs use @es_required graceful skip")`. **MUST NOT** carry `@es_required` — that decorator would skip the sentinel before its assertion runs, defeating the fail-loud guarantee.
  - **(f)** FR-8 CI credentials sentinel — `test_overlap_probe_real_engine_credentials_sentinel`. Decorated only with the same `@pytest.mark.skipif(os.environ.get("CI") != "true", ...)`. Asserts `"local-es" in yaml.safe_load(get_settings().cluster_credentials_yaml or "{}")` with a failure message naming the workflow step that provisions the YAML.

  **Helper-smoke ES-touching tests (a, b, c) — same isolation discipline as the 5 rewritten tests:** each MUST use `f"overlap-probe-helper-test-{uuid.uuid4().hex}"` as its target index name and MUST wrap its ES interactions in `try: ... finally: await delete_overlap_probe_index(...)`. This prevents helper-test failures from leaking indexes that would poison subsequent rewritten tests under pytest-xdist.

  Lives at the integration-test root (alongside `test_seed_es.py` and other helper-targeted integration tests) — NOT under `fixtures/`, which is reserved for helper modules.

## 15) Documentation update requirements

- `docs/01_architecture`: none (no architectural change; the Protocol's "query-time only" boundary is reinforced by NOT adding `bulk_index`).
- `docs/02_product`: the existing `feat_study_preflight_overlap_probe/feature_spec.md` §"Existing test impact" row for AC-1..AC-4b becomes inaccurate after this lands. Update that row (in the implemented-features copy at [`docs/00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md)) to note "AC-1..AC-4b were migrated to real-engine in `infra_study_preflight_real_engine_integration` (PR #___, ___)".
- `docs/03_runbooks`: update [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) §"Running integration tests locally" with one line noting the new real-engine tests require ES + `local-es` credentials, citing this spec.
- `docs/04_security`: none.
- `docs/05_quality`: update [`docs/05_quality/testing.md`](../../../05_quality/testing.md) §"Integration test mocking policy" with one line noting that overlap-probe integration coverage now runs end-to-end against the ES service container via a test-only bulk-index helper, and that bulk-index is intentionally NOT on the `SearchAdapter` Protocol per D-1 of this spec.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — test-infra change.
- **Migration/backfill expectations:** None — no schema change.
- **Operational readiness gates:** None — CI workflow already provisions the ES service container + the `local-es` credentials YAML.
- **Release gate:**
  - All 5 rewritten tests pass in CI.
  - `make test-integration` passes locally with ES up.
  - `make test-integration` skips (does not fail) the 5 rewritten tests with ES down locally.
  - All 6 helper smoke tests (a-f per §14 — note (d) is a single parametrized test with two cases covering local-skip + CI-loud-failure branches) pass in CI; in CI the two sentinels (e, f) MUST NOT report `skipped`.
  - GPT-5.5 final review clean.
  - Gemini Code Assist review adjudicated.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-3, AC-4, AC-4b | Rewrite 5 test functions in `test_studies_api.py` | `backend/tests/integration/test_studies_api.py` (rewrites in-place) | `feat_study_preflight_overlap_probe/feature_spec.md` §"Existing test impact" |
| FR-2 | AC-INFRA-5 | Create `backend/tests/integration/fixtures/es_overlap_probe.py` with `bulk_index_overlap_probe_docs`; verify no Protocol changes via diff | `backend/tests/integration/fixtures/es_overlap_probe.py` + `backend/tests/integration/test_es_overlap_probe_helpers.py` | `docs/05_quality/testing.md` |
| FR-3 | AC-INFRA-1 | Apply `@es_required` to all 5 rewritten tests; reuse `_es_base_url()` | `backend/tests/integration/test_studies_api.py` | `docs/03_runbooks/local-dev.md` |
| FR-4 | AC-INFRA-3, AC-INFRA-4 | Per-test uuid-suffixed `target_index`; `try: ... finally: delete_overlap_probe_index(...)` | `backend/tests/integration/test_studies_api.py` | — |
| FR-5 | (regression — covered by full suite running green) | Verify AC-5..AC-13 + autouse fixture unchanged via `git diff` | `backend/tests/integration/test_studies_api.py` | — |
| FR-6 | AC-INFRA-2, AC-INFRA-6 | Pre-flight check in `seed_minimum_for_overlap_probe_real_engine()` reads mounted YAML and `pytest.skip(...)` if `local-es` absent | `backend/tests/integration/fixtures/es_overlap_probe.py` + `test_es_overlap_probe_helpers.py` smoke test (d) | `docs/03_runbooks/local-dev.md` |
| FR-7 | (covered by AC-1..AC-4b passing) | Re-bind `backend.app.api.v1.studies.probe_judgment_overlap` to `study_preflight.probe_judgment_overlap` in each rewritten test | `backend/tests/integration/test_studies_api.py` | — |
| FR-8 | AC-INFRA-7 | Add two CI-only sentinels — `test_overlap_probe_real_engine_sentinel` (ES reachability) + `test_overlap_probe_real_engine_credentials_sentinel` (`local-es` in mounted YAML); neither carries `@es_required` | `backend/tests/integration/test_es_overlap_probe_helpers.py` | — |

## 18) Definition of feature done

- [ ] All 5 real-engine variants (AC-1..AC-4b) pass in CI.
- [ ] All 6 helper smoke tests (a-f per §14 — (d) is parametrized over CI-true/CI-false) pass; the two CI sentinels (e + f) MUST NOT report `skipped` when running in CI.
- [ ] All 9 pre-existing AC tests (AC-5..AC-13) and the 30+ unrelated tests in `test_studies_api.py` still pass.
- [ ] `git diff main -- backend/app/adapters/protocol.py` returns empty (no Protocol changes).
- [ ] `grep -nE "bulk_index|index_doc|put_doc" backend/app/adapters/` returns no production-code matches.
- [ ] 80% coverage gate still green.
- [ ] `docs/05_quality/testing.md`, `docs/03_runbooks/local-dev.md`, and the upstream `feat_study_preflight_overlap_probe/feature_spec.md` §"Existing test impact" row are updated.
- [ ] Pre-push gate clean (`make fmt && make lint && make typecheck && make test-unit && make test-contract`).
- [ ] No open questions remain in §19.
- [ ] Final GPT-5.5 review pass clean.
- [ ] Gemini Code Assist line-level findings adjudicated.

## 19) Open questions and decision log

### Open questions

None — the two scope forks (bulk-index mechanism, OpenSearch coverage) are locked at D-1 and D-2 of the idea.

### Decision log

- **2026-05-22 — D-1: bulk-index mechanism.** The test fixture uses a dedicated test-only httpx client initialized from the cluster's `base_url` + credentials inside the fixture module. Do NOT extend the `SearchAdapter` Protocol. **Rationale:** the Protocol's role is engine-agnostic *query-time* search; bulk-indexing is a test-time concern that doesn't generalize across `ElasticAdapter` + future `FusionAdapter` (Fusion's bulk-index surface differs significantly and would never share an interface with ES's `_bulk`). Locking this at spec time prevents the spec from re-litigating Protocol-vs-fixture-helper.
- **2026-05-22 — D-2: CI engine.** The test fixture indexes against the ES service container only. **Rationale:** OpenSearch coverage at the `search_batch` layer is already satisfied via the adapter Protocol contract tests; running both ES + OpenSearch for this fixture would double CI runtime without exercising any code path the Protocol contract doesn't already cover.
- **2026-05-25 — D-3: per-test uuid-suffixed index names.** Each rewritten test owns `overlap-probe-test-<32-hex>` rather than a shared `overlap-probe-test` index. **Rationale:** enables pytest-xdist, prevents cleanup-failure cascades, isolates state for debuggability.
- **2026-05-25 — D-4: `credentials_ref="local-es"` in the real-engine fixture (not `"ref"` like the stub fixture).** **Rationale:** `acquire_adapter()` calls `resolve_credentials()` which requires the ref to exist in the mounted YAML; `"local-es"` is the entry CI bakes in and `bash scripts/install.sh` generates locally. The stub `"ref"` would raise `CredentialsMissing` → `ClusterUnreachable` → silent probe-skip → 201 (not 422) — exactly the confusing failure mode FR-6 exists to prevent.
- **2026-05-25 — D-5: FR-6 fails the fixture with `pytest.skip(...)` rather than letting the probe degrade silently.** **Rationale:** the existing `@es_required` skip marker doesn't cover the credentials-missing case; without an explicit pre-flight check, missing local-es credentials would manifest as "test failed: expected 422, got 201" with no hint that the probe was silently skipped. The pre-flight YAML-read is fast (≤5ms) and the explicit skip gives operators a one-shot fix path.
- **2026-05-25 — D-6: AC-10/AC-11 (adapter-call-shape locks) stay as `_FakeProbeAdapter` capture, NOT migrated to real-engine.** **Rationale:** they assert on captured kwargs (`captured_kwargs["target"]`, `captured_kwargs["timeout"]`, `nq.body["query"]`) that the real adapter doesn't expose post-`search_batch`. A real-engine variant of AC-10/11 would lose the precise assertion surface that makes those tests valuable. Idea §"Proposed capabilities" #3 captures this.
- **2026-05-25 — D-7: AC-7/AC-8/AC-9 (probe-skipped + empty-judgments paths) stay as `_FakeProbeAdapter` synthetic failures.** **Rationale:** producing on-demand `ClusterUnreachableError` / `QueryTimeoutError` against a healthy service-container ES would require external tooling (toxiproxy, kill -STOP on the container, etc.) — high CI fragility for no bug-class coverage gain.
- **2026-05-25 — D-8: helper handles empty `doc_ids` by skipping `/_bulk`, not by posting an empty body.** **Rationale:** an empty NDJSON body returns ES 400 `parse_exception: request body is required` — AC-1 (zero-overlap test) would fail before exercising the probe. The helper PUTs the index + skips `/_bulk` + still POSTs `/_refresh` so the empty index is searchable. Added to FR-2 + smoke test (b).
- **2026-05-25 — D-9: helper writes to ES without basic auth.** **Rationale:** matches the established `seed_es.py:48` pattern (no auth); CI runs ES with `xpack.security.enabled: "false"` and CLAUDE.md mandates the same locally ("Do not install ES + OpenSearch with security plugins enabled in the local Compose"). Sharing the adapter's credential-resolution path was raised by cycle-1 reviewer but rejected — over-engineering for a test fixture that should mirror the existing operator-script pattern.
- **2026-05-25 — D-11: extract `_es_base_url` + `es_required` to `fixtures/es_reachability.py`.** **Rationale:** importing a test-collected module (`test_seed_es.py`) from a fixture helper is brittle (pytest's collection vs import ordering, and a refactor that renames the test file silently breaks the helper). Cycle-3 reviewer A-3. The shared module is ~30 LOC and `test_seed_es.py` updates to one import line.
- **2026-05-25 — D-12: `delete_overlap_probe_index` swallows transport errors in `finally:` blocks.** **Rationale:** re-raising a `ConnectError` in `finally:` masks the original test failure with a less-informative one. The 32-hex uuid suffix provides isolation; cleanup is best-effort, not the line of defense. Cycle-3 reviewer B-7.
- **2026-05-25 — D-13: 128-bit uuid index suffix (`uuid.uuid4().hex`, 32 hex chars) replaces the original 8-char truncation.** **Rationale:** 32 bits is probabilistically unique-enough but the spec's "MUST be unique" wording overclaims; 128 bits keeps the invariant intact in prose without compromise. ES's 255-char index name limit accommodates this comfortably. Cycle-3 reviewer B-6.
- **2026-05-25 — D-14: `(d)` is parametrized over `CI=true` / `CI=false` rather than split into `(d)` + `(d2)`.** **Rationale:** keeps the helper-smoke test count at 6 (matching the §16 + §18 numerical claims), and the two cases share enough fixture setup that parametrization is cleaner than duplication. Cycle-3 reviewer B-4.

- **2026-05-25 — D-10: TWO CI-only sentinels + FR-6 CI-loud-failure branch close the silent-skip gap.** **Rationale:** `@es_required` graceful skip is correct off the host shell but masks broken CI setup. Three failure modes could silently strip the regression coverage: (i) the CI ES service container fails to start, (ii) the `cluster_credentials.yaml` "Seed cluster credentials" step is removed from the workflow, (iii) the YAML mounts but lacks the `local-es:` key. Sentinel (e) covers (i); sentinel (f) covers (ii) + (iii) at module level; FR-6's CI-branch `RuntimeError` covers (iii) at per-test level (defense in depth). All sentinels MUST NOT carry `@es_required` (it would defeat the fail-loud guarantee — cycle-2 reviewer F3). Locked in FR-8.
