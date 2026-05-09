"""Smoke test proving the toolchain is wired (Story 1.2)."""


def test_python_works() -> None:
    """The simplest possible test: `1 + 1 == 2`. If this fails, pytest itself is broken."""
    assert 1 + 1 == 2


def test_app_import() -> None:
    """The FastAPI app stub from Story 1.2 imports cleanly."""
    from backend.app.main import app

    assert app.title == "RelyLoop"
    assert app.version == "0.1.0"
