# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.openapi_export``.

Story 2.1 of ``infra_generated_artifact_freshness_gate`` (FR-4 / AC-4).

The exporter MUST work with **no** live Postgres / Redis / Elasticsearch /
OpenSearch / Solr / OpenAI client. These tests assert that explicitly —
none of them touches the network or `make up` infra. The fixture
intentionally does NOT receive a real ``client``/``db_session`` and
runs in the default ``backend.tests.unit/`` layer (CI's unit job has no
service containers).

Test surface:

1. ``build_openapi()`` returns a dict with the structural keys an
   OpenAPI 3 document must carry (``openapi``, ``info``, ``paths``).
   The plan (§ Tasks 2.1.4) explicitly notes the assertion must check
   *parsed keys*, not a leading-byte prefix, because the canonical
   ``json.dumps(sort_keys=True)`` alphabetises top-level keys (so the
   first key is ``components``, not ``openapi``).

2. ``serialize(build_openapi())`` is byte-stable across repeated calls
   (FR-6 determinism / AC-7 backend half).

3. The exporter runs with **no service env** beyond what
   ``_ensure_dummy_settings_env()`` populates — this is the executable
   enforcement of FR-4's import-graph claim.

4. ``main(['--out', path])`` writes byte-pure JSON to ``path``
   atomically (no partial file on the destination during the write)
   and exits 0.

5. ``main([])`` writes byte-pure JSON to stdout and exits 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app import openapi_export


def test_build_openapi_returns_canonical_openapi_dict() -> None:
    """Parsed keys, not a leading-byte prefix (sort_keys=True moves
    ``components`` to the front)."""
    schema = openapi_export.build_openapi()

    assert isinstance(schema, dict)
    # The four keys every OpenAPI 3 doc the FastAPI helper produces
    # carries. We don't assert order — `sort_keys=True` in serialize()
    # alphabetises, so order is structural ("components" first).
    for required in ("openapi", "info", "paths"):
        assert required in schema, f"missing OpenAPI key: {required!r}"

    # The version field must look like "3.x" — both FastAPI 0.x and 1.x
    # emit "3.0.x" / "3.1.x" depending on version; both are acceptable.
    assert schema["openapi"].startswith("3."), schema["openapi"]

    # And there must be at least one known route (sanity check the app
    # was actually imported, not a stub). `/healthz` is unprefixed +
    # mandatory per CLAUDE.md Rule #6, so it's the most stable target.
    assert "/healthz" in schema["paths"], "healthz route not in schema"


def test_serialize_is_byte_stable_across_repeated_calls() -> None:
    """FR-6: a clean re-run on the same input produces identical bytes."""
    first = openapi_export.serialize(openapi_export.build_openapi())
    second = openapi_export.serialize(openapi_export.build_openapi())
    assert first == second, "serialize() output drifted across calls"


def test_serialize_uses_canonical_form() -> None:
    """sort_keys + compact separators + trailing newline (FR-4)."""
    raw = openapi_export.serialize({"b": 1, "a": 2})
    # sort_keys=True → "a" first.
    assert raw == '{"a":2,"b":1}\n'

    # And the canonical form parses back to the original.
    parsed = json.loads(raw)
    assert parsed == {"a": 2, "b": 1}


def test_serialize_handles_real_schema_round_trip() -> None:
    """The real schema's JSON output parses cleanly back to a dict."""
    schema = openapi_export.build_openapi()
    body = openapi_export.serialize(schema)
    assert body.endswith("\n"), "missing trailing newline"
    reparsed = json.loads(body)
    assert reparsed.keys() == schema.keys()


def test_exporter_runs_with_no_service_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke: FR-4 path (a) holds — no asyncpg pool / Redis / engine
    client is constructed at import or at app.openapi() time. We prove
    it by pointing the env at obviously-unreachable hosts and asserting
    build_openapi() still returns a valid schema."""
    # Point at a deliberately non-resolvable host. If any of the engine
    # / DB / Redis / OpenAI clients were instantiated at import time or
    # by app.openapi(), the call would either hang on DNS or raise
    # ConnectionError. We expect it to succeed.
    monkeypatch.setenv("REDIS_URL", "redis://relyloop-no-such-host.invalid:6379/0")
    # DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE are populated by
    # _ensure_dummy_settings_env() so they already work — we don't
    # override them here. The Settings cache must be cleared to pick
    # up the new REDIS_URL.
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()

    schema = openapi_export.build_openapi()
    assert "/healthz" in schema["paths"]


def test_main_writes_to_stdout_when_out_omitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stdout receives byte-pure JSON; all diagnostics → stderr."""
    rc = openapi_export.main([])
    captured = capsys.readouterr()
    assert rc == 0
    # Stdout must parse as JSON (no diagnostic noise mixed in).
    parsed = json.loads(captured.out)
    assert "openapi" in parsed
    # Stderr is allowed to carry diagnostics but the diagnostic-free
    # path is preferred — main([]) shouldn't print anything to stderr
    # when --out is omitted (the only stderr message is the "wrote N
    # bytes" line guarded by --out).
    assert captured.err == ""


def test_main_writes_atomic_file_when_out_provided(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--out path is atomic-written; the diagnostic goes to stderr."""
    out = tmp_path / "openapi.json"
    rc = openapi_export.main(["--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 0
    assert out.exists()
    body = out.read_text()
    assert body.endswith("\n")
    parsed = json.loads(body)
    assert "/healthz" in parsed["paths"]
    # No stray .tmp file should survive the atomic write.
    leftover_tmps = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftover_tmps == [], f"atomic-write leaked: {leftover_tmps}"
    # Diagnostic about file write went to stderr (not stdout).
    assert captured.out == ""
    assert "wrote" in captured.err.lower()


def test_main_overwrites_existing_out_path(tmp_path: Path) -> None:
    """A pre-existing file is replaced — the gate's re-write path."""
    out = tmp_path / "openapi.json"
    out.write_text("stale-bytes\n")
    rc = openapi_export.main(["--out", str(out)])
    assert rc == 0
    body = out.read_text()
    assert body != "stale-bytes\n"
    # Round-trip parses cleanly.
    parsed = json.loads(body)
    assert parsed.get("openapi", "").startswith("3.")


def test_module_invocation_is_clean(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Belt-and-braces: simulate the CLI by calling main() and capturing
    output the way `python -m backend.app.openapi_export` would. Same
    coverage as test_main_writes_to_stdout, but explicitly framed as the
    `python -m` smoke."""
    rc = openapi_export.main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["openapi"].startswith("3.")


def test_build_openapi_is_idempotent_in_a_single_process() -> None:
    """Calling build_openapi() twice in the same process returns
    structurally equivalent schemas. (Identity is not required — FastAPI
    can rebuild internally — but `sorted(keys)` must match.)"""
    a = openapi_export.build_openapi()
    b = openapi_export.build_openapi()
    assert sorted(a.keys()) == sorted(b.keys())
    assert sorted(a.get("paths", {}).keys()) == sorted(b.get("paths", {}).keys())
