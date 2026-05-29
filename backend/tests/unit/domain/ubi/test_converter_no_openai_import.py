"""ast-based guard: ``backend.app.domain.ubi.converter`` MUST NOT import
``openai`` or construct an ``AsyncOpenAI`` instance (feat_ubi_judgments
Story 1.2 / FR-2 anti-pattern guard).

This test enforces CLAUDE.md Absolute Rules #3 / #8 / #10: every LLM call
in the codebase goes through the shared ``rate_query_batch`` +
``budget_gate`` path. The hybrid converter takes its LLM-fill callback
as a constructor parameter; the caller (worker) supplies the callback
built around ``rate_query_batch``. The domain code is never allowed to
build its own OpenAI client — that's the failure mode this guard
catches.

ast scan rather than a runtime import check: a regression that adds
``import openai`` inside a function body would not surface at module
load (the import would be lazy), but the ast walk catches it
regardless of where in the module body the import lives.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from backend.app.domain.ubi import converter as _converter_module

# Resolve the path via the actual module file — robust to whatever
# repo / container layout the test runs under (host venv, dev container,
# worktree container). The test fails fast at module import if
# backend.app.domain.ubi.converter moves or disappears.
_CONVERTER_PATH = Path(inspect.getfile(_converter_module)).resolve()


def _walk_module(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def _all_imported_names(tree: ast.Module) -> set[str]:
    """Walks the entire ast (function bodies + class bodies + module top)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _all_called_names(tree: ast.Module) -> set[str]:
    """Collect every Name + Attribute-base used as a call target."""
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                # Walk attribute chains down to the root Name. Typed as `expr`
                # (the union of ast expression types) because Attribute.value
                # can be any expression — we narrow with isinstance below.
                root: ast.expr = func
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    called.add(root.id)
                    called.add(_attr_chain(func))
    return called


def _attr_chain(node: ast.Attribute) -> str:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


class TestConverterAntiPatternGuard:
    def test_converter_does_not_import_openai(self) -> None:
        tree = _walk_module(_CONVERTER_PATH)
        imports = _all_imported_names(tree)
        assert "openai" not in imports, (
            "backend.app.domain.ubi.converter must not import openai — "
            "the hybrid converter accepts an llm_rate callback constructed "
            "by the worker; see CLAUDE.md Absolute Rules #3/#8/#10 + "
            "feat_ubi_judgments FR-2 anti-pattern guard."
        )

    def test_converter_does_not_construct_asyncopenai(self) -> None:
        tree = _walk_module(_CONVERTER_PATH)
        called = _all_called_names(tree)
        # Catch both `AsyncOpenAI(...)` and `openai.AsyncOpenAI(...)` forms.
        forbidden = {"AsyncOpenAI", "openai.AsyncOpenAI"}
        leaked = forbidden & called
        assert not leaked, (
            f"backend.app.domain.ubi.converter constructs an LLM client: "
            f"{sorted(leaked)}. LLM-fill calls MUST be routed through the "
            "worker-supplied llm_rate callback (which wraps rate_query_batch "
            "+ the budget gate). See CLAUDE.md Absolute Rules #3/#8/#10."
        )

    def test_converter_does_not_import_httpx(self) -> None:
        # Defense-in-depth: catching httpx import too, since that's the
        # primary alternative I/O channel.
        tree = _walk_module(_CONVERTER_PATH)
        imports = _all_imported_names(tree)
        assert "httpx" not in imports, (
            "backend.app.domain.ubi.converter must not import httpx — "
            "the converter is pure-domain; any I/O belongs in the caller-"
            "supplied callback."
        )
