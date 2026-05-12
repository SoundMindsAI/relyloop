"""Webhook receivers (feat_github_webhook).

Per ``docs/01_architecture/api-conventions.md`` webhook endpoints
mount unprefixed (no ``/api/v1``) so external providers don't have to
encode an unexpected path component. Same exception as ``/healthz``
(CLAUDE.md Rule #6 carve-out).
"""
