# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Regression: the seed script's DB access must work INSIDE the api container.

PR #539 moved the install.sh auto-seed to run inside the api container (for
Python-version portability) and fixed the HTTP URL constants for the container
context — but missed the DB-access path. `_psql` and `count_existing_clusters`
still shelled out to `docker compose exec postgres psql`, which fails inside a
container with no `docker`/`psql` binary:

    FileNotFoundError: [Errno 2] No such file or directory: 'docker'

(User-reported on a fresh corp-network `make up`: stack came up Healthy but the
auto-seed crashed in count_existing_clusters.)

Fix: inside the container, reach Postgres directly via psycopg2 (a main project
dep, present in the image) using the app's DATABASE_URL; on the host, keep the
`docker compose exec` path. These tests pin both branches.
"""

from __future__ import annotations

from typing import Any

import pytest

import scripts.seed_meaningful_demos as seed

_FAKE_CONN_KWARGS = {
    "host": "postgres",
    "port": 5432,
    "user": "relyloop",
    "password": "pw",
    "dbname": "relyloop",
}


class _FakeCursor:
    def __init__(self, fetch_value: tuple[Any, ...] | None) -> None:
        self._fetch = fetch_value
        self.executed: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetch


class _FakeConn:
    def __init__(self, fetch_value: tuple[Any, ...] | None = (0,)) -> None:
        self.autocommit = False
        self.cursor_obj = _FakeCursor(fetch_value)
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def _forbid_subprocess(*_a: object, **_k: object) -> None:
    raise AssertionError("subprocess.run (docker) must NOT be called in the container path")


def test_psql_uses_psycopg2_in_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "_INSIDE_CONTAINER", True)
    monkeypatch.setattr(seed, "_container_db_conn_kwargs", lambda: dict(_FAKE_CONN_KWARGS))
    fake_conn = _FakeConn()
    monkeypatch.setattr("psycopg2.connect", lambda **_kw: fake_conn)
    monkeypatch.setattr("scripts.seed_meaningful_demos.subprocess.run", _forbid_subprocess)

    seed._psql("TRUNCATE demo CASCADE;")

    assert "TRUNCATE demo CASCADE;" in fake_conn.cursor_obj.executed
    assert fake_conn.autocommit is True
    assert fake_conn.closed is True


def test_count_existing_clusters_uses_psycopg2_in_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seed, "_INSIDE_CONTAINER", True)
    monkeypatch.setattr(seed, "_container_db_conn_kwargs", lambda: dict(_FAKE_CONN_KWARGS))
    fake_conn = _FakeConn(fetch_value=(3,))
    monkeypatch.setattr("psycopg2.connect", lambda **_kw: fake_conn)
    monkeypatch.setattr("scripts.seed_meaningful_demos.subprocess.run", _forbid_subprocess)

    assert seed.count_existing_clusters() == 3
    assert fake_conn.cursor_obj.executed == [seed._COUNT_LIVE_CLUSTERS_SQL]


def test_count_existing_clusters_retries_past_transient_then_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient psycopg2 error (postgres warming up) is retried, not fatal."""
    import psycopg2

    monkeypatch.setattr(seed, "_INSIDE_CONTAINER", True)
    monkeypatch.setattr(seed, "_container_db_conn_kwargs", lambda: dict(_FAKE_CONN_KWARGS))
    monkeypatch.setattr("scripts.seed_meaningful_demos.time.sleep", lambda _s: None)

    calls = {"n": 0}

    def flaky(_sql: str, *, fetch: bool) -> int | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg2.OperationalError("connection refused")
        return 5

    monkeypatch.setattr(seed, "_run_sql_in_container", flaky)
    monkeypatch.setattr("scripts.seed_meaningful_demos.subprocess.run", _forbid_subprocess)

    assert seed.count_existing_clusters(max_attempts=3, backoff_s=0) == 5
    assert calls["n"] == 2


def test_psql_uses_docker_on_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "_INSIDE_CONTAINER", False)
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **_k: object) -> Any:
        captured["cmd"] = cmd

        class _R:
            stdout = "0"
            stderr = ""

        return _R()

    monkeypatch.setattr("scripts.seed_meaningful_demos.subprocess.run", fake_run)

    def _forbid_psycopg(*_a: object, **_k: object) -> None:
        raise AssertionError("psycopg2 must NOT be used on the host path")

    monkeypatch.setattr("psycopg2.connect", _forbid_psycopg)

    seed._psql("SELECT 1;")

    assert captured["cmd"][0] == "docker"
    assert "psql" in captured["cmd"]


def test_container_db_conn_kwargs_handles_base64_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a base64 password (with /, +, =) must not corrupt the port.

    install.sh generates the postgres password via `openssl rand -base64 32`
    and drops it RAW into the DATABASE_URL. Passing that URL string to psycopg2
    made libpq misparse it — "invalid integer value '<pw>' for connection
    option 'port'". Discrete kwargs via SQLAlchemy's make_url extract the
    password verbatim and a real integer port.
    """
    pw = "uOLUgx/Wb6+SJKht5pNL53FC="  # base64-shaped: contains / + =
    raw_url = f"postgresql+asyncpg://relyloop:{pw}@postgres/relyloop"

    class _FakeSettings:
        database_url = raw_url

    monkeypatch.setattr("backend.app.core.settings.get_settings", lambda: _FakeSettings())

    kwargs = seed._container_db_conn_kwargs()

    assert kwargs["password"] == pw
    assert kwargs["host"] == "postgres"
    assert kwargs["user"] == "relyloop"
    assert kwargs["dbname"] == "relyloop"
    # The bug: the password landed in `port`. Port must be a real int.
    assert isinstance(kwargs["port"], int)


def test_container_db_conn_kwargs_filters_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """libpq query params (sslmode, ...) pass through; asyncpg-only ones drop.

    A managed Postgres at GA may carry `?sslmode=require`. Those libpq keywords
    must reach psycopg2, while driver-specific params (e.g. asyncpg's `ssl=`)
    must be dropped — passing them would raise a psycopg2 TypeError.
    """
    raw_url = (
        "postgresql+asyncpg://relyloop:pw@db.example.com:6432/relyloop"
        "?sslmode=require&ssl=true&application_name=relyloop-seed"
    )

    class _FakeSettings:
        database_url = raw_url

    monkeypatch.setattr("backend.app.core.settings.get_settings", lambda: _FakeSettings())

    kwargs = seed._container_db_conn_kwargs()

    assert kwargs["sslmode"] == "require"  # libpq keyword — preserved
    assert kwargs["application_name"] == "relyloop-seed"  # libpq keyword — preserved
    assert "ssl" not in kwargs  # asyncpg-only — dropped (would TypeError psycopg2)
    assert kwargs["port"] == 6432
