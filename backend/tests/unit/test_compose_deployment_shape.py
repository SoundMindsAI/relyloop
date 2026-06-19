# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Compose deployment-shape regression tests (bug_worker_optuna_init_race).

The worker's ``on_startup`` hook constructs Optuna's ``RDBStorage``, which
issues ``CREATE TYPE`` against the ``optuna`` schema. The schema is
created by the ``migrate`` init container (``alembic upgrade head &&
python -m backend.app.db.optuna_schema``). If ``api`` or ``worker``
ever loses its dependency on ``migrate``, the next ``make up`` on a
fresh ``./data/postgres`` volume crashes the worker with
``psycopg2.errors.InvalidSchemaName``.

This file pins the canonical Compose surface so a stray edit can't
silently re-introduce the boot-order race.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[3] / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose_spec() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text())


class TestMigrateInitContainer:
    def test_migrate_service_defined(self, compose_spec: dict[str, Any]) -> None:
        services = compose_spec["services"]
        assert "migrate" in services, (
            "docker-compose.yml lost its `migrate` init container — see bug_worker_optuna_init_race"
        )

    def test_migrate_runs_alembic_and_optuna_schema(self, compose_spec: dict[str, Any]) -> None:
        migrate = compose_spec["services"]["migrate"]
        command = migrate["command"]
        # Command is `sh -c "<cmd>"`; the cmd string must reference both
        # `alembic upgrade head` and the optuna_schema module.
        joined = " ".join(command) if isinstance(command, list) else command
        assert "alembic upgrade head" in joined
        assert "backend.app.db.optuna_schema" in joined

    def test_migrate_depends_on_postgres_healthy(self, compose_spec: dict[str, Any]) -> None:
        depends = compose_spec["services"]["migrate"]["depends_on"]
        assert depends["postgres"]["condition"] == "service_healthy"

    def test_migrate_restart_policy_is_no(self, compose_spec: dict[str, Any]) -> None:
        # Init containers run once and exit; `restart: "no"` is the
        # canonical encoding. `restart: unless-stopped` would keep
        # re-running the migration after a clean exit.
        assert compose_spec["services"]["migrate"]["restart"] == "no"


class TestApiAndWorkerDependOnMigrate:
    @pytest.mark.parametrize("service", ["api", "worker"])
    def test_service_depends_on_migrate_completed_successfully(
        self, compose_spec: dict[str, Any], service: str
    ) -> None:
        depends = compose_spec["services"][service]["depends_on"]
        assert "migrate" in depends, (
            f"{service!r} no longer depends on `migrate` — fresh-stack boots "
            "will race the optuna schema (bug_worker_optuna_init_race)"
        )
        assert depends["migrate"]["condition"] == "service_completed_successfully"


class TestLockedDesignDecisions:
    def test_migrate_reuses_api_image(self, compose_spec: dict[str, Any]) -> None:
        """bug_fix.md Decision #2: migrate reuses the api image — no new
        Dockerfile, no separate build context. A future change that splits
        migrate to its own image would silently drift past the design lock."""
        services = compose_spec["services"]
        assert services["migrate"]["image"] == services["api"]["image"]
        assert services["migrate"]["build"]["context"] == services["api"]["build"]["context"]
        assert services["migrate"]["build"]["dockerfile"] == services["api"]["build"]["dockerfile"]

    def test_worker_has_no_restart_policy(self, compose_spec: dict[str, Any]) -> None:
        """bug_fix.md Decision #5: explicitly rejected adding
        `restart: unless-stopped` to the worker — defense-in-depth would
        mask future genuine worker crashes. The init container removes the
        original failure mode; any future worker crash is its own bug."""
        worker = compose_spec["services"]["worker"]
        assert "restart" not in worker, (
            "worker gained a restart policy — bug_fix.md Decision #5 "
            "explicitly rejected this to avoid masking future genuine crashes"
        )


class TestServiceImageRegistryPrefix:
    """Pulled third-party service images must carry the ${BASE_REGISTRY} prefix.

    Corp networks that block direct docker.io pulls route every image through an
    internal mirror. BASE_REGISTRY already rewrites the Dockerfile FROM lines;
    the pulled Compose service images (postgres/redis/elasticsearch/opensearch/
    solr) must use the same prefix or `make up` fails at pull time with a 403
    ("failed to resolve reference docker.io/opensearchproject/opensearch...").
    The api/ui/worker/migrate images are built locally (not pulled), so they
    intentionally keep their plain `relyloop/...` tag.
    """

    PULLED_SERVICES = ("postgres", "redis", "elasticsearch", "opensearch", "solr", "ollama")
    BUILT_SERVICES = ("api", "ui", "worker", "migrate")

    @pytest.mark.parametrize("service", PULLED_SERVICES)
    def test_pulled_service_image_is_registry_prefixed(
        self, compose_spec: dict[str, Any], service: str
    ) -> None:
        image = compose_spec["services"][service]["image"]
        assert image.startswith("${BASE_REGISTRY:-}"), (
            f"{service} image {image!r} must be prefixed with ${{BASE_REGISTRY:-}} "
            "so corp networks can route the pull through their mirror (the 403 "
            "'failed to resolve reference docker.io/...' failure mode)."
        )

    @pytest.mark.parametrize("service", BUILT_SERVICES)
    def test_built_service_image_is_not_prefixed(
        self, compose_spec: dict[str, Any], service: str
    ) -> None:
        image = compose_spec["services"][service]["image"]
        assert "BASE_REGISTRY" not in image, (
            f"{service} is built locally (has a `build:` section); its image "
            f"tag {image!r} must NOT carry the BASE_REGISTRY pull prefix."
        )

    def test_all_services_are_accounted_for(self, compose_spec: dict[str, Any]) -> None:
        """Drift guard: every Compose service must be classified pulled-vs-built.

        A new service added to docker-compose.yml that lands in neither list
        would silently skip the registry-prefix check above — so a corp-network
        pull of it could 403 without any test catching the gap. Force the
        classification to stay exhaustive.
        """
        defined = set(compose_spec["services"])
        accounted = set(self.PULLED_SERVICES) | set(self.BUILT_SERVICES)
        assert defined == accounted, (
            f"docker-compose.yml services {sorted(defined)} do not match the "
            f"classified set {sorted(accounted)}. Add any new service to "
            "PULLED_SERVICES (pulled image → needs ${BASE_REGISTRY} prefix) or "
            "BUILT_SERVICES (has a `build:` section → no prefix) in "
            "TestServiceImageRegistryPrefix."
        )


class TestBundledLlmService:
    """feat_bundled_local_llm Story 2 — the opt-in `ollama` service shape.

    The bundled LLM is OFF by default: it lives behind the ``bundled-llm``
    Compose profile, so a bare ``make up`` never starts it. The YAML
    ``profiles`` key IS the default-off contract (asserting on ``docker compose
    config`` output is brittle — Compose renders profiled services regardless of
    active profiles across versions).
    """

    def test_ollama_service_defined(self, compose_spec: dict[str, Any]) -> None:
        assert "ollama" in compose_spec["services"], (
            "docker-compose.yml lost the bundled `ollama` service (feat_bundled_local_llm)"
        )

    def test_ollama_is_profile_gated(self, compose_spec: dict[str, Any]) -> None:
        # The profile gate is what keeps the lightweight default LLM-free and CI
        # hermetic (no model pull on a bare `up`/build).
        assert compose_spec["services"]["ollama"]["profiles"] == ["bundled-llm"]

    def test_ollama_image_is_pinned(self, compose_spec: dict[str, Any]) -> None:
        image = compose_spec["services"]["ollama"]["image"]
        assert "ollama/ollama" in image
        # Pinned, never `latest` — reproducibility + the LLM-compatibility gate
        # is recorded against a specific tag.
        assert ":latest" not in image and not image.endswith("ollama/ollama"), (
            f"ollama image {image!r} must pin a concrete non-latest tag"
        )

    @pytest.mark.parametrize("service", ["api", "worker"])
    def test_app_does_not_depend_on_ollama(
        self, compose_spec: dict[str, Any], service: str
    ) -> None:
        # A `depends_on` targeting a profile-gated service breaks the default
        # (non-LLM) `up`. The async Redis-cached capability check reflects LLM
        # readiness instead; install.sh restarts api/worker post-`--wait` under
        # Option B to force a fresh probe.
        depends = compose_spec["services"][service].get("depends_on", {})
        assert "ollama" not in depends, (
            f"{service!r} must NOT depend_on the profile-gated `ollama` service "
            "— it would break the default LLM-free `make up`"
        )

    def test_healthcheck_reads_container_model_var(self, compose_spec: dict[str, Any]) -> None:
        # `$$OLLAMA_MODEL` (double-dollar) makes Compose pass a literal
        # `$OLLAMA_MODEL` to the container shell so the healthcheck reads the
        # CONTAINER env at runtime, not the host env at config-render time.
        test = compose_spec["services"]["ollama"]["healthcheck"]["test"]
        joined = " ".join(test) if isinstance(test, list) else str(test)
        assert "$${OLLAMA_MODEL}" in joined, (
            "ollama healthcheck must use `$${OLLAMA_MODEL}` (double-dollar) so "
            "Compose defers interpolation to the container shell at runtime"
        )

    @pytest.mark.parametrize("service", ["api", "worker"])
    def test_app_reaches_host_native_ollama(
        self, compose_spec: dict[str, Any], service: str
    ) -> None:
        # feat_bundled_llm_native_detection: RELYLOOP_LLM=ollama wires the app at
        # a host-native Ollama via http://host.docker.internal:11434. On Linux
        # that needs the host-gateway mapping (no-op on Mac/Windows).
        hosts = compose_spec["services"][service].get("extra_hosts", [])
        assert "host.docker.internal:host-gateway" in hosts, (
            f"{service!r} must map host.docker.internal:host-gateway so a native "
            "Ollama (RELYLOOP_LLM=ollama) is reachable on Linux"
        )
