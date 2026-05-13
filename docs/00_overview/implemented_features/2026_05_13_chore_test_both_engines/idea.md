# chore — parameterize cluster integration tests over both engines

**Date:** 2026-05-09
**Status:** Idea (deferred from `infra_adapter_elastic` — refactor sweep, 2026-05-09)
**Origin:** Surfaced when the operator asked "any high-value refactoring opportunities now that we have 2 engine types?" against PR #16. Filed as the lowest-priority of the three opportunities considered.

## Problem

`backend/tests/integration/test_clusters_api.py` only registers an
**Elasticsearch** cluster in every test:

```python
def _cluster_body(**overrides):
    return {
        "engine_type": "elasticsearch",
        "credentials_ref": "test-es-ref",
        ...
    }
```

The OpenSearch wire path through the same code is exercised only by:

1. Unit tests with `httpx.MockTransport` (hermetic, but synthesizes the engine).
2. The `make seed-clusters` script's idempotency test (`test_seed_clusters_idempotent.py`) — covers registration but not schema/run_query.

If a future change to the adapter, service, or router silently regresses
the OpenSearch path (e.g. a new branch on `engine_type` that mishandles
OpenSearch, or a credential-resolution change that breaks
`opensearch_basic`), integration tests will not catch it.

## Why deferred

* Out of scope for the original `infra_adapter_elastic` plan, which
  designed for the single-class adapter under the explicit assumption
  that the two engines share the same wire surface (umbrella spec §8).
* Coverage gate already passes at 90.85%.
* MVP1 deployments hold ~2 clusters in practice; the gap is preventative,
  not load-bearing.
* The cross-product engine×auth allowlist that did land in the refactor
  sweep already prevents the most likely misconfiguration (mismatched
  auth_kind), shrinking the "OpenSearch silently broken" surface.

## Proposed work

Parameterize the existing test classes over both engines:

```python
ENGINE_AUTH_PAIRS = [
    pytest.param(("elasticsearch", "es_basic", "test-es-ref"), id="es"),
    pytest.param(("opensearch", "opensearch_basic", "test-os-ref"), id="opensearch"),
]


@pytest.mark.integration
@pytest.mark.parametrize("engine_auth_pair", ENGINE_AUTH_PAIRS)
class TestPostCluster:
    async def test_happy_path_201_with_health(
        self,
        engine_auth_pair: tuple[str, str, str],
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        engine_type, auth_kind, credentials_ref = engine_auth_pair
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(
                engine_type=engine_type,
                auth_kind=auth_kind,
                credentials_ref=credentials_ref,
                base_url=f"http://{engine_type}:9200",
            ),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["engine_type"] == engine_type
        ...
```

Plus update `_stub_credentials_yaml` to write both refs:

```yaml
test-es-ref:
  username: elastic
  password: changeme
test-os-ref:
  username: admin
  password: admin
```

Apply the same pattern to `TestSchemaEndpoint` and `TestRunQuery` so
schema introspection + ad-hoc query are exercised on both engines (with
their respective seeded indices — note OpenSearch defaults to single-shard
so the existing seed pattern works unmodified).

## Scope signals

* **Backend tests:** ~30 LOC of refactoring, no production code change.
* **Frontend:** none.
* **Migration:** none.
* **Config:** none.
* **CI:** the existing pytest job picks up the parametrize automatically;
  test count grows by ~14 (the test classes' cases × 2 engines).

## Why not blocking

The cross-product `engine_type × auth_kind` allowlist that DID land in
the same refactor sweep prevents the most likely class of OpenSearch
regression (operator pairs OpenSearch with the wrong auth method).
Adapter-internal divergence on OpenSearch is unlikely until OpenSearch
3.x lands (per the runbook note); when that happens, this parameterization
becomes more valuable AND we'll likely also split engine-specific
version-detection out of `_enforce_min_version`.

## Acceptance criteria

* [ ] `TestPostCluster`, `TestSchemaEndpoint`, `TestRunQuery` parametrize
      over both `(elasticsearch, es_basic)` and `(opensearch, opensearch_basic)`.
* [ ] Schema seeding helpers handle both engines (mapping body is
      identical; index settings may need a `number_of_replicas: 0` knob
      on the OpenSearch single-node).
* [ ] `make test-integration` passes both passes.
* [ ] CI test count grows by approximately the number of parametrized
      cases × 2.
