# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Path-safe pattern on CreateQueryTemplateRequest.name (audit 2026-07-12)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.api.v1.schemas.studies import CreateQueryTemplateRequest


def _mk(name: str) -> CreateQueryTemplateRequest:
    return CreateQueryTemplateRequest(
        name=name, engine_type="elasticsearch", body='{"query": {{ query_text | tojson }}}'
    )


@pytest.mark.parametrize("name", ["product-search-v1", "My Template 2", "a.b_c-d"])
def test_valid_names_accepted(name: str) -> None:
    assert _mk(name).name == name


@pytest.mark.parametrize(
    "name", ["../.github/workflows/x", "a/b", "a\\b", "/etc/passwd", ".hidden", "-x"]
)
def test_path_unsafe_names_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        _mk(name)
