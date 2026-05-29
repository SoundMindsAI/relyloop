"""Service-layer UBI exceptions (feat_ubi_judgments Story 2.1 / FR-1).

Two named classes so the dispatcher (Story 2.2), the worker (Story 3.3),
and the readiness service (Story 2.2 + Story 3.1) can ``except`` against
the precise failure mode rather than string-matching on a generic
``RuntimeError``. Mirrors the adapter-error pattern in
:mod:`backend.app.adapters.errors`.

* :class:`UbiNotEnabledError` — raised by :meth:`UbiReader._probe_enabled`
  when ``get_schema('ubi_queries')`` raises
  :class:`backend.app.adapters.errors.TargetNotFoundError`. The dispatcher
  translates this to HTTP 412 ``UBI_NOT_ENABLED`` (per spec §8.5); the
  worker translates it to terminal ``status='failed'`` with
  ``failed_reason='UBI_NOT_ENABLED'``.

* :class:`UbiInsufficientDataError` — raised when the post-filter
  ``read_features`` result is empty AND the caller wants an exception
  rather than a sentinel empty dict (worker `failed_reason` path; spec
  FR-1 race-condition fallback only — the dispatcher's preflight U-D2
  catches the sync case via a `_count` aggregation before this fires).
  Per FR-1, the reader itself returns ``{}`` (not raise) on the empty
  case; this class is exported for the worker's terminal-flip path.
"""

from __future__ import annotations


class UbiNotEnabledError(RuntimeError):
    """``ubi_queries`` index does not exist on the cluster (rung 0).

    Raised by :meth:`UbiReader._probe_enabled` when the engine returns
    ``index_not_found_exception`` (404) for the ``ubi_queries`` index.
    Carries the engine type in the message so operator-facing logs can
    cite the right install runbook (OpenSearch UBI plugin vs o19s ES UBI
    fork).
    """


class UbiInsufficientDataError(RuntimeError):
    """Post-window UBI data is below ``min_impressions_threshold``.

    Spec FR-1 + FR-4 U-D2: the dispatcher's sync preflight catches the
    obvious case (HTTP 422 ``UBI_INSUFFICIENT_DATA``). This exception is
    the worker's race-condition fallback — fires only when the in-flight
    window's data disappears between the preflight ``_count`` and the
    worker's ``read_features`` call (essentially impossible in practice;
    carried for safety). The worker catches it and flips the row to
    ``status='failed'`` + ``failed_reason='UBI_INSUFFICIENT_DATA'``.

    The reader itself **does NOT raise** this — it returns ``{}`` per
    FR-1 ("MUST return an empty dict when ``ubi_queries`` exists but the
    ``(since, until)`` window yields zero events"). The worker decides
    whether the empty result is terminal.
    """
