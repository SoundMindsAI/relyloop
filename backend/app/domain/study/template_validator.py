# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-template create-time validator (Story 1.2).

Pure-domain helper invoked by ``POST /api/v1/query-templates`` (Story 3.1
router) at create time to:

1. Reject syntactically broken Jinja2.
2. Reject sandbox-illegal expressions (function calls, attribute access,
   dunder/private names) **before** the declared/undeclared cross-check
   so AC-7 (``{{ os.system('rm -rf /') }}``) surfaces as
   :exc:`InvalidTemplateSyntax` rather than the less-specific
   :exc:`UndeclaredParamUsed` (``os`` is undeclared but the sandbox
   violation is the real concern).
3. Enforce the declared-params ↔ body cross-check from spec FR-2.

The runtime renderer (``backend.app.domain.query.render``) was switched
to ``SandboxedEnvironment`` in the same story for defense-in-depth —
that swap is below.
"""

from __future__ import annotations

from jinja2 import meta, nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment


class InvalidTemplateSyntax(ValueError):
    """Jinja2 parse failed OR AST walk rejected a dangerous construct.

    Router translates to HTTP 400 ``INVALID_TEMPLATE_SYNTAX`` per spec §7.5.
    """


class UndeclaredParamUsed(ValueError):
    """Template body references a param not in ``declared_params``.

    Router translates to HTTP 400 ``UNDECLARED_PARAM_USED`` per spec §7.5.
    """


class DeclaredParamUnused(ValueError):
    """``declared_params`` lists a param not referenced in body.

    Router translates to HTTP 400 ``DECLARED_PARAM_UNUSED`` per spec §7.5.
    """


class ReservedParamReferenced(ValueError):
    """Template body references a reserved non-render param.

    Reserved non-render params (e.g. ``query_normalizer``) are consumed by
    the adapter's pre-render hook and MUST NOT appear in the template body.
    Router translates to HTTP 400 ``RESERVED_PARAM_REFERENCED`` (spec §8.5).
    """


_RESERVED_NONRENDER_PARAMS: frozenset[str] = frozenset({"query_normalizer"})
"""Params an operator may *declare* (so they enter the search space) but
that are consumed by the adapter before render — never substituted into the
template body. Declaring one without referencing it is allowed (it is
exempt from the unused-declaration check); referencing one in the body is a
hard error (:exc:`ReservedParamReferenced`)."""


_SANDBOX_ENV = SandboxedEnvironment()
"""Module-level sandbox. Jinja docs state ``SandboxedEnvironment`` is
thread-safe; reusing one instance avoids per-call setup."""


_IMPLICIT_PARAMS: frozenset[str] = frozenset({"query_text"})
"""Names every template implicitly receives at render time. ``query_text``
carries the user's natural-language query (see
``backend.app.adapters.elastic.ElasticAdapter.render``) — template
authors do NOT need to declare it."""


def validate_template_body(body: str, declared_params: dict[str, str]) -> None:
    """Validate a Jinja2 template body against the declared param set.

    Three-step validation:

      1. **Parse** via :meth:`SandboxedEnvironment.parse` — raises
         :exc:`jinja2.TemplateSyntaxError` for syntactic errors → mapped
         to :exc:`InvalidTemplateSyntax`.
      2. **AST walk** for sandbox-illegal constructs: any
         :class:`jinja2.nodes.Call`, any :class:`jinja2.nodes.Getattr`
         (attribute access), any :class:`jinja2.nodes.Getitem` whose
         source is a dunder/private name, OR any plain
         :class:`jinja2.nodes.Name` whose name starts with ``_``. Each
         raises :exc:`InvalidTemplateSyntax` BEFORE step 3 so AC-7
         classifies `{{ os.system(...) }}` correctly.
      3. **Cross-check** :func:`jinja2.meta.find_undeclared_variables`
         against ``set(declared_params) | _IMPLICIT_PARAMS``:
         referenced ∖ declared → :exc:`UndeclaredParamUsed`;
         declared ∖ referenced → :exc:`DeclaredParamUnused`.
    """
    try:
        ast = _SANDBOX_ENV.parse(body)
    except TemplateSyntaxError as exc:
        raise InvalidTemplateSyntax(f"jinja2 parse error: {exc.message}") from exc

    # Step 2 — AST walk for dangerous constructs (Call / Getattr / Getitem).
    for node in ast.find_all((nodes.Call, nodes.Getattr, nodes.Getitem)):
        if isinstance(node, nodes.Call):
            raise InvalidTemplateSyntax(
                "template body contains a call expression; Jinja2 sandbox "
                "forbids function/method invocation in query templates"
            )
        if isinstance(node, nodes.Getattr):
            raise InvalidTemplateSyntax(
                f"template body contains attribute access (.{node.attr}); "
                "Jinja2 sandbox forbids attribute access in query templates"
            )
        if isinstance(node, nodes.Getitem):
            target = node.node
            if isinstance(target, nodes.Name) and target.name.startswith("_"):
                raise InvalidTemplateSyntax(
                    f"template body subscripts a dunder/private name ({target.name!r})"
                )

    # Step 2b — reject any reference to a dunder/private name (C2-F6 fix).
    for name_node in ast.find_all(nodes.Name):
        if name_node.name.startswith("_"):
            raise InvalidTemplateSyntax(
                f"template body references dunder/private name "
                f"({name_node.name!r}); Jinja2 sandbox forbids underscore-"
                "prefixed identifiers in query templates"
            )

    # Step 3 — declared / undeclared cross-check.
    referenced: set[str] = meta.find_undeclared_variables(ast)
    declared: set[str] = set(declared_params) | _IMPLICIT_PARAMS

    undeclared_uses = referenced - declared
    if undeclared_uses:
        raise UndeclaredParamUsed(
            f"template references undeclared param(s): {sorted(undeclared_uses)}"
        )

    # Reserved non-render params are consumed by the adapter pre-render hook;
    # the template body must never substitute them (FR-2).
    reserved_referenced = referenced & _RESERVED_NONRENDER_PARAMS
    if reserved_referenced:
        raise ReservedParamReferenced(
            f"template body references reserved non-render param(s): "
            f"{sorted(reserved_referenced)}; these are consumed by the adapter "
            "and MUST NOT appear in the template body"
        )

    # Reserved params are exempt from the unused-declaration check — a
    # template MAY declare query_normalizer (to enter the search space)
    # without referencing it in the body.
    unused_declarations = set(declared_params) - referenced - _RESERVED_NONRENDER_PARAMS
    if unused_declarations:
        raise DeclaredParamUnused(
            f"declared param(s) unused in template: {sorted(unused_declarations)}"
        )
