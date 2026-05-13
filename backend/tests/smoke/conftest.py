"""Smoke-test conftest (chore_tutorial_polish Story 3.1).

Defines a single fixture, ``api_base_url``, that resolves the API base URL
from the ``RELYLOOP_API_BASE`` env var (CI uses this to point the smoke at
``http://127.0.0.1:8000`` after ``make up`` brings the stack up). Local
operator: ``RELYLOOP_API_BASE`` unset → defaults to the host port published
by the api Compose service.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def api_base_url() -> str:
    return os.environ.get("RELYLOOP_API_BASE", "http://127.0.0.1:8000")
