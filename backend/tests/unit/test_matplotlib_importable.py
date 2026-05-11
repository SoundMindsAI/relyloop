"""Smoke test for the matplotlib dependency added in feat_github_pr_worker Story 1.4a.

The open_pr worker uses matplotlib to render the parameter-importance PNG
that gets committed alongside each proposal's params edit. If the dep is
missing from the worker image (or pinned at an incompatible version), the
worker raises ImportError on first job and `pr_open_error` is populated
with a stack trace. This unit test fails loudly at CI time instead.
"""

from __future__ import annotations


def test_pyplot_imports() -> None:
    import matplotlib

    matplotlib.use("Agg")  # headless — no display required
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.bar(["a", "b"], [1.0, 2.0])
    plt.close(fig)
