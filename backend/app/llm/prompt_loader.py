# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Judgment-generation prompt loader + renderer (feat_llm_judgments Story 1.3).

Loads the three prompt files under ``prompts/`` and exposes a sandboxed Jinja2
renderer for the user-message template:

* ``prompts/judgment_generation.system.md`` — operator-fixed system message
  describing the rater's role and the structured-output contract.
* ``prompts/judgment_generation.user.jinja`` — Jinja2 template for the
  per-query user message; rendered with ``rubric_text``, ``query_text``, and
  ``docs``.
* ``prompts/judgment_generation.rubric_v1.md`` — starter rubric content. The
  worker passes the per-list ``judgment_lists.rubric`` text into the renderer
  so operators can override the v1 rubric per-list (FR-3c).

The renderer uses :class:`jinja2.sandbox.SandboxedEnvironment` to mirror the
existing template-author capability constraint applied by
:mod:`backend.app.domain.study.template_validator` (FR-7 / AC-7). The sandbox
constrains what the TEMPLATE AUTHOR can write (no attribute access, no
callable invocation, no dunder names); it does NOT auto-escape variable
content — values passed into the template render as literal text. That
literal-text contract is what makes the XML-delimited ``<doc>`` / ``<query>``
boundaries safe against prompt injection at the rendering step (spec §10
mitigation 1). The downstream LLM may still be tricked by adversarial content
inside a ``<doc>`` block; that is a system-prompt / model concern, not a
template concern.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2.sandbox import SandboxedEnvironment

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
"""Repo-root ``prompts/`` directory. Resolved relative to this module's path so
the loader works regardless of the process working directory (matches the
``backend.app`` package layout: ``backend/app/llm/prompt_loader.py`` →
parents[3] is the repo root)."""


@dataclass(frozen=True)
class JudgmentPromptBundle:
    """Cached snapshot of the three on-disk prompt artifacts."""

    system_prompt: str
    user_template_src: str
    rubric_v1_text: str


@lru_cache(maxsize=1)
def load_judgment_prompts() -> JudgmentPromptBundle:
    """Read and cache the three judgment-generation prompt files.

    The files are read once at first invocation and held in process memory
    for the lifetime of the worker. Operator edits to the prompt files
    require a worker restart to take effect — the worker is the only
    consumer, and the prompts directory is part of the deployed image.
    """
    system_path = PROMPTS_DIR / "judgment_generation.system.md"
    user_path = PROMPTS_DIR / "judgment_generation.user.jinja"
    rubric_path = PROMPTS_DIR / "judgment_generation.rubric_v1.md"
    return JudgmentPromptBundle(
        system_prompt=system_path.read_text(encoding="utf-8"),
        user_template_src=user_path.read_text(encoding="utf-8"),
        rubric_v1_text=rubric_path.read_text(encoding="utf-8"),
    )


_SANDBOX_ENV = SandboxedEnvironment(keep_trailing_newline=True, autoescape=True)
"""Module-level sandbox. :class:`SandboxedEnvironment` is thread-safe per the
Jinja2 docs; one shared instance avoids per-render setup cost.

``autoescape=True`` HTML-escapes every variable substitution. The XML-style
``<rubric>`` / ``<query>`` / ``<doc id="...">`` delimiters in the template
become injection-resistant: a doc body containing literal ``</doc>`` is
rendered as ``&lt;/doc&gt;`` and cannot break the candidate boundary.
Template literals (the delimiter tags themselves) are not escaped — only the
substituted ``{{ ... }}`` values. Per GPT-5.5 cycle-5 C5-F2."""


def render_user_prompt(
    *,
    rubric_text: str,
    query_text: str,
    docs: Sequence[Mapping[str, str]],
) -> str:
    """Render the per-query user message for the OpenAI judge.

    Args:
        rubric_text: The list-specific rubric body (typically
            :attr:`backend.app.db.models.judgment_list.JudgmentList.rubric`).
            Operators override the starter rubric per-list (FR-3c).
        query_text: The user's natural-language search query.
        docs: Top-K search hits as ``[{"doc_id": str, "body": str}, ...]``.
            The worker builds this list from ``adapter.search_batch`` results;
            bodies are trimmed to a bounded length before reaching this
            function (per spec §13 cost guardrail).

    Returns:
        The rendered user message string, ready to send as the OpenAI
        ``messages[1].content``.
    """
    bundle = load_judgment_prompts()
    template = _SANDBOX_ENV.from_string(bundle.user_template_src)
    return template.render(
        rubric_text=rubric_text,
        query_text=query_text,
        docs=docs,
    )
