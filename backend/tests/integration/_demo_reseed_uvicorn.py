"""In-process uvicorn helpers for ``POST /api/v1/_test/demo/reseed`` tests.

The reseed handler's ``api_client`` self-calls ``http://localhost:8000``
(FR-1c). The default integration-test fixture uses ``ASGITransport(app=app)``
which has no listening socket — the self-call would fail with
``ConnectError``. This helper boots uvicorn on a real loopback port so
both the test client AND the handler's self-call hit the same in-process
``app`` object via the network stack.

Why same-process matters (per spec §5 + plan §3.2 topology decision):

* ``app.dependency_overrides[...]`` and ``monkeypatch.setattr(...)`` apply
  to BOTH the test-side request AND the handler's loopback self-call —
  because both hit the same Python process via uvicorn.
* ``caplog`` captures route-handler logs (AC-13 commit-ordering proof).
* A sibling ``engine.connect()`` from the same process can query
  ``pg_locks`` against the shared Postgres container (AC-16 pin observer).

The fixtures themselves live in each test file (``test_demo_seeding.py``
module-scoped; ``test_demo_seeding_timeout.py`` function-scoped) — this
module exposes the lifecycle primitive ``running_uvicorn()``.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import uvicorn


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


class _UvicornBackgroundServer:
    """Run uvicorn in a background thread + signal stop via the SDK's API.

    Uses ``uvicorn.Server.should_exit = True`` + the SDK's
    ``handle_exit`` flow rather than killing the thread, which would
    leak sockets across tests.
    """

    def __init__(self, app: Any, host: str, port: int) -> None:
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="uvicorn-demo-reseed")

    def start(self) -> None:
        self.thread.start()
        # Poll for the listening socket. Bounded loop — fail fast if
        # uvicorn never comes up.
        deadline = 5.0
        elapsed = 0.0
        step = 0.05
        while elapsed < deadline:
            if _port_open("127.0.0.1", self.server.config.port):
                return
            time.sleep(step)
            elapsed += step
        raise RuntimeError(
            f"uvicorn never came up on 127.0.0.1:{self.server.config.port} within {deadline}s"
        )

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10.0)
        if self.thread.is_alive():
            self.server.force_exit = True
            self.thread.join(timeout=2.0)


# Port 8000 is the canonical value the route handler self-calls.
DEMO_RESEED_PORT = 8000


def _assert_port_free() -> None:
    """Fail loudly when 127.0.0.1:8000 is already bound.

    The handler uses a fixed ``base_url="http://localhost:8000"``, so the
    integration tests MUST own that port. Stop the API container with
    ``docker compose stop api`` before running these tests locally.
    """
    if _port_open("127.0.0.1", DEMO_RESEED_PORT):
        raise RuntimeError(
            f"127.0.0.1:{DEMO_RESEED_PORT} is occupied — stop the API "
            "container with `docker compose stop api` before running "
            "demo-reseed integration tests."
        )


@contextlib.contextmanager
def running_uvicorn() -> Iterator[str]:
    """Start uvicorn on 127.0.0.1:8000, apply migrations, yield base URL."""
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    _assert_port_free()
    server = _UvicornBackgroundServer(app, host="127.0.0.1", port=DEMO_RESEED_PORT)
    server.start()
    try:
        yield f"http://127.0.0.1:{DEMO_RESEED_PORT}"
    finally:
        server.stop()


__all__ = ["DEMO_RESEED_PORT", "running_uvicorn"]
