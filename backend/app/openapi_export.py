# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

r"""Offline, deterministic OpenAPI schema exporter.

Emits the canonical OpenAPI document that ``backend.app.main.app.openapi()``
produces, with **no** running server, live Postgres, Redis, Elasticsearch,
OpenSearch, Solr, or OpenAI client. CI uses this exporter to (re)write the
committed ``ui/openapi.json`` snapshot and fail the PR on
``git status --porcelain`` drift — Story 2.1 / FR-4 of
``infra_generated_artifact_freshness_gate``.

Usage::

    python -m backend.app.openapi_export                          # → stdout
    python -m backend.app.openapi_export --out ui/openapi.json    # → atomic file write

All diagnostics go to stderr so stdout is byte-pure JSON.

Import-graph spike (FR-4 / spec §19 — open question resolved here):

The proven recipe is to set the secret-mounted ``*_FILE`` env vars to
dummy tmpdir files (``DATABASE_URL_FILE`` + ``POSTGRES_PASSWORD_FILE``)
+ the non-secret ``REDIS_URL`` to a localhost stub, then ``from
backend.app.main import app`` + ``app.openapi()``. This is **path (a)**
in the spec's two-option fork:

* ``DATABASE_URL_FILE`` / ``POSTGRES_PASSWORD_FILE`` — secret-bearing,
  follow Absolute Rule #2 (``*_FILE``-mounted-only). Dummy files contain
  non-secret placeholder bytes; committing nothing exposes nothing.
* ``REDIS_URL`` — non-secret config (no credentials), allowed as a
  bare env var per the Settings rules.

``app.openapi()`` walks the registered route table + Pydantic models to
synthesize the schema. It does NOT trigger ``lifespan`` (FastAPI runs
``lifespan`` only on app boot), so no asyncpg pool, Redis client, ES /
OpenSearch / Solr client, or OpenAI client is constructed at import time
or at schema-build time. The companion unit test ``test_openapi_export``
runs the exporter with no service containers reachable and asserts it
exits 0 — turning any future regression (a router that opens a
connection at import) into an immediate unit-test failure rather than
a silent CI hang.

Canonical serialization (FR-4 + FR-6 determinism):

``json.dumps(schema, sort_keys=True, separators=(",", ":"),
ensure_ascii=False) + "\\n"``. ``sort_keys=True`` alphabetises top-level
keys (so the document does NOT begin with ``"openapi":`` — tests assert
parsed keys, not a leading byte prefix). Compact separators + trailing
newline keep diffs minimal. Atomic write via tmpfile + ``os.replace``
prevents a torn snapshot if the process is killed mid-write.

Reuses the dummy-``*_FILE`` env setup pioneered by
``backend/tests/contract/test_data_table_query_params.py``.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def _ensure_dummy_settings_env() -> None:
    """Populate the minimum env vars Settings requires to import.

    Only sets a var when it is not already present in the environment —
    callers (CI, the operator's shell) can override any of these with
    the real values if they're available. The dummy files live in a
    ``tempfile.mkdtemp()`` directory whose path is also published in
    ``RELYLOOP_OPENAPI_EXPORT_TMP`` so a parent test process can inspect
    them if needed (purely diagnostic; never required).

    The function is intentionally idempotent so an interactive Python
    session that has already imported the module can re-call without
    pointing at fresh tmpdirs.
    """
    # Already populated → no-op. Avoid the temp-dir churn on hot paths
    # (the unit test calls build_openapi() repeatedly).
    if all(
        os.environ.get(var) for var in ("DATABASE_URL_FILE", "POSTGRES_PASSWORD_FILE", "REDIS_URL")
    ):
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix="relyloop-openapi-export-"))
    # Clean up the dummy-secrets dir at process exit (Gemini Code Assist
    # review finding #1, PR #433). The directory holds <100 bytes of
    # placeholder content, so the leak is small — but accumulating one
    # per CLI invocation is sloppy. The env-var publish below is purely
    # diagnostic and the contract documents it as such; cleanup at exit
    # is compatible.
    atexit.register(shutil.rmtree, tmp_dir, ignore_errors=True)
    os.environ.setdefault("RELYLOOP_OPENAPI_EXPORT_TMP", str(tmp_dir))

    if not os.environ.get("DATABASE_URL_FILE"):
        db_url_file = tmp_dir / "db_url"
        # Driver prefix is `+asyncpg` because the runtime uses the async
        # SQLAlchemy dialect; mismatched dialects are the canonical
        # `bug_postgres_dialect_drift` shape this avoids.
        db_url_file.write_text("postgresql+asyncpg://relyloop:placeholder@localhost/relyloop")
        os.environ["DATABASE_URL_FILE"] = str(db_url_file)

    if not os.environ.get("POSTGRES_PASSWORD_FILE"):
        pw_file = tmp_dir / "pw"
        pw_file.write_text("placeholder")
        os.environ["POSTGRES_PASSWORD_FILE"] = str(pw_file)

    # REDIS_URL is non-secret config per the Settings rules, so the bare
    # env var is the supported form (Absolute Rule #2 governs SECRETS
    # only — see CLAUDE.md "Settings & Secrets").
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


def build_openapi() -> dict[str, Any]:
    """Construct the FastAPI app and return its OpenAPI schema dict.

    Import-clean: no asyncpg pool, Redis client, or engine adapter is
    instantiated at import time or by ``app.openapi()`` — those build
    during ``lifespan``, which FastAPI does not invoke when the schema
    is requested directly. See module docstring for the import-graph
    spike rationale.
    """
    _ensure_dummy_settings_env()

    # The settings cache must be cleared so the dummy env vars take
    # effect even when this function is called from a process that
    # already initialised Settings under different env (e.g. an
    # interactive REPL or a test that imported `backend.app` earlier).
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()

    from backend.app.main import app

    return app.openapi()


def serialize(schema: dict[str, Any]) -> str:
    """Canonical JSON encoding — see module docstring (FR-4 / FR-6).

    ``sort_keys=True`` makes the byte-output deterministic across
    macOS/Linux. ``ensure_ascii=False`` lets non-ASCII bytes flow
    through unescaped (the schema doesn't currently contain any, but
    if a router description ever adds one we don't want the platform's
    JSON-escape behaviour to vary). Compact ``separators`` + a single
    trailing newline keep the diff minimal.
    """
    return (
        json.dumps(
            schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def _write_atomic(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (tmp file + os.replace).

    Avoids a torn snapshot if the process is killed mid-write — readers
    either see the previous content or the new content, never a partial
    file. The tmp file is created in the same directory as ``path`` so
    ``os.replace`` is a same-filesystem rename (atomic on POSIX/NTFS).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # ``delete=False`` because os.replace handles the rename. If anything
    # between the NamedTemporaryFile context and the successful
    # ``os.replace`` raises (write/flush/fsync error, disk full,
    # permission denied on the rename), the orphan ``.tmp`` would
    # otherwise persist next to ``path`` — see Gemini Code Assist review
    # finding #2 on PR #433. ``tmp_path = None`` after a successful
    # replace tells the finally block "the rename took ownership, don't
    # try to delete the now-renamed file".
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                # Best-effort cleanup; never raise from a finally clause
                # masking the original exception.
                pass


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="backend.app.openapi_export",
        description=(
            "Emit the canonical OpenAPI schema for the RelyLoop API. "
            "With --out, atomically writes to that path; without --out, "
            "writes byte-pure JSON to stdout. All diagnostics → stderr."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Destination path (atomic write). Omit for stdout.",
    )
    args = parser.parse_args(argv)

    try:
        schema = build_openapi()
    except Exception as exc:  # noqa: BLE001 — top-level CLI guard
        print(f"openapi-export: failed to build schema: {exc}", file=sys.stderr)
        return 1

    body = serialize(schema)

    if args.out is None:
        sys.stdout.write(body)
        return 0

    _write_atomic(args.out, body)
    print(f"openapi-export: wrote {args.out} ({len(body)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
