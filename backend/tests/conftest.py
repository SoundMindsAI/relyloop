"""Pytest fixtures for the RelyLoop backend test suite.

This module is intentionally empty for the bootstrap (Story 1.2) — fixtures land
with the stories that need them:

- ``async_client`` (httpx.AsyncClient against the FastAPI app) — Story 3.1+
- ``db_session`` (async SQLAlchemy session against a test database) — Story 2.1+
- ``redis_client`` (aioredis client against the test Redis) — Story 3.3+
- ``mock_llm`` (OpenAI client stub) — Story 3.3+
"""
