"""Service layer (use-case orchestrators).

Each module composes repositories + domain logic + adapter calls into a
business operation. Per CLAUDE.md "Service Layer", services are async,
take ``db: AsyncSession`` first, and let the caller commit (services may
internally commit when the operation owns its own transaction boundary,
e.g. ``register_cluster``).

Modules arrive with their owning features:

* ``cluster`` — infra_adapter_elastic Story 3.1 (registration, dispatch).
"""
