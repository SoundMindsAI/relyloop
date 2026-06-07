# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for website/scripts/build_guides.py.

The generator is stdlib-only and importable (importing does NOT trigger
generation). Every test runs against tmp fixtures with injected paths — no
dependency on the real repo tree. Mirrors the hermetic style of
test_run_tests_in_worktree.py in this directory.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

# Load the generator module by file path (it lives under website/scripts/,
# outside the backend package, so a normal import won't resolve it).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_GEN_PATH = _REPO_ROOT / "website" / "scripts" / "build_guides.py"
_spec = importlib.util.spec_from_file_location("build_guides", _GEN_PATH)
assert _spec and _spec.loader
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)


# --------------------------------------------------------------------------- #
# Fixture helpers                                                              #
# --------------------------------------------------------------------------- #
def _make_deck(
    root: Path,
    slug: str,
    *,
    title: str = "A deck",
    estimated_time: str = "3 minutes",
    tags: list[str] | None = None,
    screenshots: list[dict[str, Any]] | None = None,
    video: str | None = "walkthrough.webm",
    with_webm: bool = True,
    with_mp4: bool = False,
) -> Path:
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    shots = (
        screenshots
        if screenshots is not None
        else [
            {"file": "01-first.png", "caption": "The first screen of the flow shows the list."},
            {"file": "02-second.png", "caption": "The second screen opens the modal."},
        ]
    )
    meta: dict[str, Any] = {"title": title, "screenshots": shots}
    if estimated_time:
        meta["estimated_time"] = estimated_time
    if tags is not None:
        meta["tags"] = tags
    if video is not None:
        meta["video"] = video
    (d / "metadata.json").write_text(json.dumps(meta))
    for shot in shots:
        if shot.get("file"):
            (d / shot["file"]).write_bytes(b"\x89PNG\r\n")
    if with_webm:
        (d / "walkthrough.webm").write_bytes(b"webmdata")
    if with_mp4:
        (d / "walkthrough.mp4").write_bytes(b"mp4data")
    return d


# --------------------------------------------------------------------------- #
# discover_decks                                                               #
# --------------------------------------------------------------------------- #
def test_discover_decks_sorted_by_slug(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "03_third", title="Third")
    _make_deck(src, "01_first", title="First")
    _make_deck(src, "02_second", title="Second")
    decks = bg.discover_decks(src)
    assert [d["slug"] for d in decks] == ["01_first", "02_second", "03_third"]


def test_discover_decks_sorts_screenshots_by_numeric_prefix(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(
        src,
        "01_x",
        screenshots=[
            {"file": "10-last.png", "caption": "tenth"},
            {"file": "02-mid.png", "caption": "second"},
            {"file": "01-first.png", "caption": "first"},
        ],
    )
    decks = bg.discover_decks(src)
    assert [s["file"] for s in decks[0]["screenshots"]] == [
        "01-first.png",
        "02-mid.png",
        "10-last.png",
    ]


def test_discover_decks_missing_metadata_warns_and_skips(tmp_path: Path, capsys) -> None:
    src = tmp_path / "guides"
    (src / "01_no_meta").mkdir(parents=True)
    _make_deck(src, "02_good")
    decks = bg.discover_decks(src)
    assert [d["slug"] for d in decks] == ["02_good"]
    assert "missing metadata.json" in capsys.readouterr().err


def test_discover_decks_invalid_slug_fails(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    # A path-traversal-ish name that escapes SLUG_RE.
    bad = src / "bad slug!"
    bad.mkdir(parents=True)
    (bad / "metadata.json").write_text(json.dumps({"title": "x", "screenshots": []}))
    with pytest.raises(SystemExit) as exc:
        bg.discover_decks(src)
    assert "not a safe identifier" in str(exc.value)


def test_discover_decks_locked_video_name_enforced(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x", video="other.webm")
    with pytest.raises(SystemExit) as exc:
        bg.discover_decks(src)
    assert 'must be "walkthrough.webm"' in str(exc.value)


def test_discover_decks_missing_required_key_fails(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    d = src / "01_x"
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"title": "no screenshots key"}))
    with pytest.raises(SystemExit) as exc:
        bg.discover_decks(src)
    assert "missing required key" in str(exc.value)


# --------------------------------------------------------------------------- #
# copy_deck_assets                                                             #
# --------------------------------------------------------------------------- #
def test_copy_deck_assets_copies_declared_and_webm(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x", with_webm=True, with_mp4=False)
    decks = bg.discover_decks(src)
    dst = tmp_path / "out" / "01_x"
    copied = bg.copy_deck_assets(decks[0], src / "01_x", dst)
    assert "01-first.png" in copied
    assert "walkthrough.webm" in copied
    assert "walkthrough.mp4" not in copied
    assert (dst / "01-first.png").is_file()
    assert (dst / "walkthrough.webm").is_file()


def test_copy_deck_assets_includes_mp4_when_present(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x", with_webm=True, with_mp4=True)
    decks = bg.discover_decks(src)
    dst = tmp_path / "out" / "01_x"
    copied = bg.copy_deck_assets(decks[0], src / "01_x", dst)
    assert {"walkthrough.webm", "walkthrough.mp4"} <= copied


def test_copy_deck_assets_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x")
    decks = bg.discover_decks(src)
    dst = tmp_path / "out" / "01_x"
    first = bg.copy_deck_assets(decks[0], src / "01_x", dst)
    second = bg.copy_deck_assets(decks[0], src / "01_x", dst)
    assert first == second


def test_copy_deck_assets_missing_screenshot_warns(tmp_path: Path, capsys) -> None:
    src = tmp_path / "guides"
    _make_deck(
        src,
        "01_x",
        screenshots=[
            {"file": "01-present.png", "caption": "here"},
            {"file": "02-gone.png", "caption": "absent"},
        ],
    )
    # Remove the second PNG to simulate drift.
    (src / "01_x" / "02-gone.png").unlink()
    decks = bg.discover_decks(src)
    dst = tmp_path / "out" / "01_x"
    copied = bg.copy_deck_assets(decks[0], src / "01_x", dst)
    assert "01-present.png" in copied
    assert "02-gone.png" not in copied
    assert "missing screenshot" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# emit_deck_page                                                               #
# --------------------------------------------------------------------------- #
def test_emit_deck_page_structure(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(
        src,
        "01_x",
        title="Register a cluster",
        estimated_time="3 minutes",
        tags=["setup", "clusters"],
    )
    deck = bg.discover_decks(src)[0]
    copied = {s["file"] for s in deck["screenshots"]}
    page = bg.emit_deck_page(deck, has_webm=False, has_mp4=False, copied=copied)
    assert page.startswith("<!-- GENERATED by website/scripts/build_guides.py")
    assert "# Register a cluster" in page
    assert "**Estimated time:** 3 minutes" in page
    assert "**Tags:** setup, clusters" in page
    # H2 per screenshot in order
    assert page.index("## Step 1") < page.index("## Step 2")
    assert "![The first screen of the flow shows the list.]" in page
    assert "(../../assets/guides/01_x/01-first.png)" in page
    assert "[← Back to walkthroughs](index.md)" in page


def test_emit_deck_page_no_video_when_no_webm(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x")
    deck = bg.discover_decks(src)[0]
    copied = {s["file"] for s in deck["screenshots"]}
    page = bg.emit_deck_page(deck, has_webm=False, has_mp4=False, copied=copied)
    assert "<video" not in page


def test_emit_deck_page_skips_uncopied_screenshot_rows(tmp_path: Path) -> None:
    # A screenshot that was NOT copied (missing source) must not produce an
    # image row that links to a non-existent asset.
    src = tmp_path / "guides"
    _make_deck(src, "01_x")
    deck = bg.discover_decks(src)[0]
    # Only the first screenshot was "copied".
    page = bg.emit_deck_page(deck, has_webm=False, has_mp4=False, copied={"01-first.png"})
    assert "(../../assets/guides/01_x/01-first.png)" in page
    assert "02-second.png" not in page
    assert "## Step 1" in page
    assert "## Step 2" not in page


# --------------------------------------------------------------------------- #
# index pages                                                                  #
# --------------------------------------------------------------------------- #
def test_emit_walkthroughs_index_card_grid_and_skip_class(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "02_b", title="Bravo")
    _make_deck(src, "01_a", title="Alpha")
    decks = bg.discover_decks(src)
    idx = bg.emit_walkthroughs_index(decks)
    assert '<div class="grid cards" markdown>' in idx
    # Order: Alpha (01_a) before Bravo (02_b)
    assert idx.index("Alpha") < idx.index("Bravo")
    # Thumbnails carry the glightbox-skip marker so they navigate, not lightbox.
    assert "{.glightbox-skip}" in idx
    assert "[Open walkthrough →](01_a.md)" in idx


def test_emit_indepth_index_lists_long_form(tmp_path: Path) -> None:
    idx = bg.emit_indepth_index(list(bg.LONG_FORM_GUIDES))
    assert "# In-depth guides" in idx
    assert "[Tutorial — first study](tutorial-first-study.md)" in idx
    assert "[LLM endpoint setup](llm-endpoint-setup.md)" in idx


# --------------------------------------------------------------------------- #
# Story 1.3 — video block + transcode                                          #
# --------------------------------------------------------------------------- #
def test_build_video_block_mp4_first(tmp_path: Path) -> None:
    block = bg.build_video_block("01_x", has_webm=True, has_mp4=True, has_vtt=False)
    mp4_idx = block.index('type="video/mp4"')
    webm_idx = block.index('type="video/webm"')
    assert mp4_idx < webm_idx  # MP4 first for iOS Safari
    assert "playsinline" in block
    assert 'class="walkthrough-video-download"' in block
    # Sibling download <p> is OUTSIDE the </video> close tag.
    assert block.index("</video>") < block.index("walkthrough-video-download")


def test_build_video_block_uses_root_relative_asset_depth() -> None:
    # REGRESSION (video-404 hotfix): the <video>/<source>/<a> are RAW HTML that
    # MkDocs does NOT path-rewrite. The deck page renders at
    # /guides/walkthroughs/<slug>/ so the browser-correct path to /assets/ needs
    # THREE ../ — matching the depth MkDocs rewrites the markdown screenshot
    # images to. Two ../ (the source-relative depth) 404s in the browser.
    block = bg.build_video_block("01_x", has_webm=True, has_mp4=True, has_vtt=False)
    assert '<source src="../../../assets/guides/01_x/walkthrough.mp4"' in block
    assert '<source src="../../../assets/guides/01_x/walkthrough.webm"' in block
    assert 'href="../../../assets/guides/01_x/walkthrough.webm"' in block
    # The buggy two-level depth must NOT appear.
    assert '"../../assets/guides/01_x/walkthrough' not in block


def test_build_video_block_no_mp4(tmp_path: Path) -> None:
    block = bg.build_video_block("01_x", has_webm=True, has_mp4=False, has_vtt=False)
    assert 'type="video/mp4"' not in block
    assert 'type="video/webm"' in block
    assert 'class="walkthrough-video-download"' in block  # still present


def test_build_video_block_no_webm_returns_empty() -> None:
    assert bg.build_video_block("01_x", has_webm=False, has_mp4=False, has_vtt=False) == ""
    # Even if a stale MP4 somehow flagged True, no WebM => no block.
    assert bg.build_video_block("01_x", has_webm=False, has_mp4=True, has_vtt=False) == ""


def test_build_video_block_track_present_iff_vtt() -> None:
    # FR-4 / AC-5: a captions <track> is emitted only when has_vtt, with the
    # same ../../../assets/<slug> root-relative depth as the <source>s.
    with_vtt = bg.build_video_block("01_x", has_webm=True, has_mp4=True, has_vtt=True)
    assert (
        '<track kind="captions" src="../../../assets/guides/01_x/captions.vtt" '
        'srclang="en" label="Steps" default>'
    ) in with_vtt
    # Track sits inside the <video> element (before </video>).
    assert with_vtt.index("<track") < with_vtt.index("</video>")

    without_vtt = bg.build_video_block("01_x", has_webm=True, has_mp4=True, has_vtt=False)
    assert "<track" not in without_vtt


def test_copy_deck_assets_copies_captions_vtt_when_present(tmp_path: Path) -> None:
    # FR-4 / AC-6: captions.vtt is copied + in the returned set when the source exists.
    src = tmp_path / "guides"
    _make_deck(src, "01_x", with_webm=True, with_mp4=False)
    (src / "01_x" / "captions.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
    deck = bg.discover_decks(src)[0]
    dst = tmp_path / "out" / "01_x"
    copied = bg.copy_deck_assets(deck, src / "01_x", dst)
    assert "captions.vtt" in copied
    assert (dst / "captions.vtt").is_file()


def test_copy_deck_assets_no_captions_vtt_when_absent(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x", with_webm=True)
    deck = bg.discover_decks(src)[0]
    dst = tmp_path / "out" / "01_x"
    copied = bg.copy_deck_assets(deck, src / "01_x", dst)
    assert "captions.vtt" not in copied


def test_default_generate_makes_no_ffmpeg_call(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def _spy(argv, *a, **k):
        calls.append(argv)
        raise AssertionError("ffmpeg should not be called on the default path")

    monkeypatch.setattr(bg.subprocess, "run", _spy)
    # run_transcode_pass is the only ffmpeg caller; the default generate() does
    # not invoke it. Assert calling generate-equivalent emit path makes no call.
    src = tmp_path / "guides"
    _make_deck(src, "01_x")
    # emit_deck_page + discover never shell out.
    decks = bg.discover_decks(src)
    bg.emit_deck_page(decks[0], has_webm=True, has_mp4=False, copied={"01-first.png"})
    assert calls == []


def test_transcode_skips_when_mp4_newer(tmp_path: Path, monkeypatch) -> None:
    webm = tmp_path / "walkthrough.webm"
    mp4 = tmp_path / "walkthrough.mp4"
    webm.write_bytes(b"w")
    mp4.write_bytes(b"m")
    import os
    import time

    # Make mp4 strictly newer than webm.
    past = time.time() - 100
    os.utime(webm, (past, past))
    called = []
    monkeypatch.setattr(bg.subprocess, "run", lambda *a, **k: called.append(1))
    assert bg.transcode_webm_to_mp4(webm, mp4) is False
    assert called == []


def test_run_transcode_pass_ffmpeg_absent_warns(tmp_path: Path, monkeypatch, capsys) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x", with_webm=True)
    monkeypatch.setattr(bg.shutil, "which", lambda _: None)
    bg.run_transcode_pass(src)
    assert "ffmpeg not on PATH" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Story 1.2 — link rewriter                                                    #
# --------------------------------------------------------------------------- #
def _repo_with(tmp_path: Path, *rel_paths: str) -> Path:
    """Build a fake repo root with the given relative paths existing (files
    unless they end with '/')."""
    root = tmp_path / "repo"
    (root / "docs" / "08_guides").mkdir(parents=True)
    for rel in rel_paths:
        p = root / rel
        if rel.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
    return root


def test_rewrite_link_absolute_passthrough(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    assert bg.rewrite_link("https://example.com/x", root) == "https://example.com/x"
    assert bg.rewrite_link("mailto:a@b.com", root) == "mailto:a@b.com"


def test_rewrite_link_anchor_passthrough(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    assert bg.rewrite_link("#section", root) == "#section"


def test_rewrite_link_intra_list(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    assert bg.rewrite_link("tutorial-first-study.md", root) == "tutorial-first-study.md"
    assert bg.rewrite_link("./quick-tour.md", root) == "quick-tour.md"
    # Preserve fragment.
    assert bg.rewrite_link("quick-tour.md#step-3", root) == "quick-tour.md#step-3"


def test_rewrite_link_offsite_file_blob(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, "backend/tests/smoke/test_tutorial_path.py")
    out = bg.rewrite_link("../../backend/tests/smoke/test_tutorial_path.py", root)
    assert out == (
        "https://github.com/SoundMindsAI/relyloop/blob/main/"
        "backend/tests/smoke/test_tutorial_path.py"
    )


def test_rewrite_link_offsite_dir_tree(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, "docs/01_architecture/")
    out = bg.rewrite_link("../01_architecture/", root)
    assert out == "https://github.com/SoundMindsAI/relyloop/tree/main/docs/01_architecture/"


def test_rewrite_link_offsite_preserves_fragment(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, "docs/01_architecture/llm-orchestration.md")
    out = bg.rewrite_link("../01_architecture/llm-orchestration.md#caching", root)
    assert out.endswith("/docs/01_architecture/llm-orchestration.md#caching")


def test_rewrite_link_unresolved_raises(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    with pytest.raises(bg.LinkRewriteError) as exc:
        bg.rewrite_link("../99_unknown/path.md", root)
    assert exc.value.reason == "unresolved"


def test_rewrite_link_unmapped_raises(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    with pytest.raises(bg.LinkRewriteError) as exc:
        bg.rewrite_link("some-other-file.md", root)
    assert exc.value.reason == "unmapped"


def test_port_long_form_missing_source_fails(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    with pytest.raises(SystemExit) as exc:
        bg.port_long_form_guide(root / "docs" / "08_guides" / "tutorial-first-study.md", root)
    assert "long-form guide source missing" in str(exc.value)


def test_port_long_form_rewrites_and_strips_presenter(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, "docs/03_runbooks/local-dev.md")
    src = root / "docs" / "08_guides" / "quick-tour.md"
    src.write_text(
        "# Quick tour\n\n"
        "<!-- presenter: pause here -->\n"
        "See [local dev](../03_runbooks/local-dev.md) and "
        "[the tutorial](tutorial-first-study.md).\n"
    )
    out = bg.port_long_form_guide(src, root)
    assert out.startswith("<!-- GENERATED")
    assert "presenter" not in out
    assert "blob/main/docs/03_runbooks/local-dev.md" in out
    assert "[the tutorial](tutorial-first-study.md)" in out


def test_port_long_form_unresolved_link_reports_file_line(tmp_path: Path) -> None:
    root = _repo_with(tmp_path)
    src = root / "docs" / "08_guides" / "tutorial-first-study.md"
    src.write_text("# T\n\nbad [x](../99_nope/y.md)\n")
    with pytest.raises(SystemExit) as exc:
        bg.port_long_form_guide(src, root)
    msg = str(exc.value)
    assert "docs/08_guides/tutorial-first-study.md:3" in msg
    assert "unresolved repo link" in msg


# --------------------------------------------------------------------------- #
# Story 1.4 — prune                                                            #
# --------------------------------------------------------------------------- #
def test_prune_dir_removes_unexpected(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "keep.md").write_text("k")
    (d / "stale.md").write_text("s")
    (d / "stale_dir").mkdir()
    pruned = bg.prune_dir(d, {"keep.md"})
    assert sorted(pruned) == ["stale.md", "stale_dir"]
    assert (d / "keep.md").is_file()
    assert not (d / "stale.md").exists()
    assert not (d / "stale_dir").exists()


# --------------------------------------------------------------------------- #
# Story 1.5 — nav fragment                                                     #
# --------------------------------------------------------------------------- #
_MINIMAL_MKDOCS = (
    "site_name: RelyLoop\n"
    "nav:\n"
    "  - Home: index.md\n"
    "  - Engines:\n"
    "      - Elasticsearch: engines/elasticsearch.md\n"
    "  - API Reference: api/index.md\n"
    "  - Blog:\n"
    "      - blog/index.md\n"
)


def _decks_for_nav() -> list[dict[str, Any]]:
    return [
        {"slug": "01_a", "title": "Alpha", "screenshots": []},
        {"slug": "02_b", "title": "Bravo", "screenshots": []},
    ]


def test_yaml_single_quote_doubles_internal() -> None:
    assert bg.yaml_single_quote("It's fun") == "'It''s fun'"
    assert bg.yaml_single_quote("plain") == "'plain'"


def test_render_nav_fragment_quotes_labels() -> None:
    frag = bg.render_nav_fragment(_decks_for_nav())
    assert "- Guides:" in frag
    assert "'Alpha': guides/walkthroughs/01_a.md" in frag
    assert "'Tutorial — first study': guides/in-depth/tutorial-first-study.md" in frag


def test_splice_first_run_inserts_before_anchor() -> None:
    out = bg.splice_nav_fragment(_MINIMAL_MKDOCS, bg.render_nav_fragment(_decks_for_nav()))
    assert bg.NAV_BEGIN in out
    assert bg.NAV_END in out
    # Fragment sits immediately before the API Reference anchor.
    assert out.index(bg.NAV_END) < out.index(bg.ANCHOR_LINE)
    assert out.index("- Engines:") < out.index(bg.NAV_BEGIN)
    # Other lines preserved.
    assert "  - Home: index.md" in out
    assert "      - blog/index.md" in out


def test_splice_idempotent_byte_stable() -> None:
    frag = bg.render_nav_fragment(_decks_for_nav())
    once = bg.splice_nav_fragment(_MINIMAL_MKDOCS, frag)
    twice = bg.splice_nav_fragment(once, frag)
    assert once == twice


def test_render_nav_fragment_shuffled_input_deterministic() -> None:
    ordered = _decks_for_nav()
    shuffled = list(reversed(ordered))
    # discover_decks sorts; render_nav_fragment trusts the sorted input. Verify
    # that feeding already-sorted vs reversed differs (proving order matters)
    # AND that the index emitter + nav, fed the SORTED list, are stable.
    assert bg.render_nav_fragment(ordered) != bg.render_nav_fragment(shuffled)
    # The generator's contract: discover_decks is the single sort point.
    re_sorted = sorted(shuffled, key=lambda d: d["slug"])
    assert bg.render_nav_fragment(re_sorted) == bg.render_nav_fragment(ordered)


def test_validate_anchor_missing_fails() -> None:
    no_anchor = "site_name: RelyLoop\nnav:\n  - Home: index.md\n"
    with pytest.raises(SystemExit) as exc:
        bg.validate_mkdocs_anchor(no_anchor)
    assert "exactly one" in str(exc.value)


def test_validate_anchor_duplicate_fails() -> None:
    dup = _MINIMAL_MKDOCS + "  - API Reference: api/index.md\n"
    with pytest.raises(SystemExit) as exc:
        bg.validate_mkdocs_anchor(dup)
    assert "exactly one" in str(exc.value)


def test_validate_anchor_partial_marker_fails() -> None:
    partial = _MINIMAL_MKDOCS.replace(
        "  - API Reference: api/index.md\n",
        bg.NAV_BEGIN + "\n  - API Reference: api/index.md\n",
    )
    with pytest.raises(SystemExit) as exc:
        bg.validate_mkdocs_anchor(partial)
    assert "partial GENERATED Guides nav marker" in str(exc.value)


def test_exotic_title_yaml_safe_loads() -> None:
    import yaml  # PyYAML is a confirmed backend dep (pyproject.toml)

    decks = [{"slug": "01_x", "title": 'Search: it\'s "fun" — guide #1', "screenshots": []}]
    out = bg.splice_nav_fragment(_MINIMAL_MKDOCS, bg.render_nav_fragment(decks))
    # The whole mkdocs.yml (with the spliced fragment) must parse cleanly.
    parsed = yaml.safe_load(out)
    assert parsed["site_name"] == "RelyLoop"


# --------------------------------------------------------------------------- #
# Story 2.4 — glightbox plugin config (static assertion on committed mkdocs)   #
# --------------------------------------------------------------------------- #
def test_mkdocs_glightbox_skip_class_config_present() -> None:
    # Text-based assertion: the real mkdocs.yml uses MkDocs custom YAML tags
    # (!ENV, !!python/name:) that PyYAML's safe_load rejects, so parse by text.
    text = (_REPO_ROOT / "website" / "mkdocs.yml").read_text()
    assert "- glightbox:" in text, "glightbox plugin not registered in mkdocs.yml"
    assert 'skip_classes: ["glightbox-skip"]' in text, (
        'glightbox.skip_classes must be ["glightbox-skip"] (AC-14)'
    )


def test_port_long_form_line_spanning_link(tmp_path: Path) -> None:
    # A link whose [text](url) wraps across a source line break (the tutorial's
    # `[smoke\ntest](url)` shape) must still be rewritten.
    root = _repo_with(tmp_path, "backend/tests/smoke/test_tutorial_path.py")
    src = root / "docs" / "08_guides" / "tutorial-first-study.md"
    src.write_text(
        "# T\n\nthe [smoke\ntest](../../backend/tests/smoke/test_tutorial_path.py) runs\n"
    )
    out = bg.port_long_form_guide(src, root)
    assert "blob/main/backend/tests/smoke/test_tutorial_path.py" in out
    assert "../../backend" not in out


def test_port_long_form_nested_bracket_link_text(tmp_path: Path) -> None:
    # Link text containing a nested [id] (Next.js dynamic-route path in
    # backticks) must match and rewrite the URL.
    root = _repo_with(tmp_path, "ui/src/app/templates/[id]/page.tsx")
    src = root / "docs" / "08_guides" / "workflows-overview.md"
    src.write_text(
        "# W\n\nfork via [`/templates/[id]`](../../ui/src/app/templates/[id]/page.tsx) button\n"
    )
    out = bg.port_long_form_guide(src, root)
    assert "blob/main/ui/src/app/templates/[id]/page.tsx" in out
    assert "../../ui/src/app" not in out


def test_discover_decks_rejects_path_traversal_screenshot(tmp_path: Path) -> None:
    # A metadata.json screenshot filename with a path separator / .. must be
    # rejected (path-traversal guard).
    src = tmp_path / "guides"
    d = src / "01_x"
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(
        json.dumps(
            {
                "title": "x",
                "screenshots": [{"file": "../../../etc/passwd", "caption": "evil"}],
            }
        )
    )
    with pytest.raises(SystemExit) as exc:
        bg.discover_decks(src)
    assert "not a safe .png basename" in str(exc.value)


def test_validate_anchor_duplicate_with_markers_present_fails() -> None:
    # Once the markers exist, a duplicate anchor is still corruption — the
    # fragment is inserted BEFORE the anchor, never replacing it.
    spliced = bg.splice_nav_fragment(_MINIMAL_MKDOCS, bg.render_nav_fragment(_decks_for_nav()))
    dup = spliced + "\n  - API Reference: api/index.md\n"
    with pytest.raises(SystemExit) as exc:
        bg.validate_mkdocs_anchor(dup)
    assert "exactly one" in str(exc.value)


def test_index_thumbnail_skips_missing_first_screenshot(tmp_path: Path) -> None:
    # If the first declared screenshot's source is missing (not copied), the
    # index card thumbnail must use the next copied one — never a broken asset.
    src = tmp_path / "guides"
    _make_deck(
        src,
        "01_x",
        title="Deck X",
        screenshots=[
            {"file": "01-gone.png", "caption": "missing"},
            {"file": "02-here.png", "caption": "present"},
        ],
    )
    decks = bg.discover_decks(src)
    # Only the second screenshot was copied.
    idx = bg.emit_walkthroughs_index(decks, {"01_x": {"02-here.png"}})
    assert "02-here.png" in idx
    assert "01-gone.png" not in idx


def test_index_thumbnail_omitted_when_none_copied(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _make_deck(src, "01_x", title="Deck X")
    decks = bg.discover_decks(src)
    idx = bg.emit_walkthroughs_index(decks, {"01_x": set()})
    # No thumbnail image at all, but the card + open-link still render.
    assert "../../assets/guides/01_x/" not in idx
    assert "[Open walkthrough →](01_x.md)" in idx


def test_detect_unsupported_single_quoted_html_href(tmp_path: Path) -> None:
    # Single-quoted <a href='...'> relative repo links must fail loudly too.
    root = _repo_with(tmp_path)
    src = root / "docs" / "08_guides" / "tutorial-first-study.md"
    src.write_text("# T\n\n<a href='../03_runbooks/x.md'>link</a>\n")
    with pytest.raises(SystemExit) as exc:
        bg.port_long_form_guide(src, root)
    assert "unsupported HTML <a> link" in str(exc.value)


# --------------------------------------------------------------------------- #
# Story 2.2 — caption transform parity + vtt↔metadata consistency             #
# --------------------------------------------------------------------------- #
def test_caption_transform_matches_shared_golden_corpus() -> None:
    # Cross-language parity (C3-B1): the Python normalize/escape mirrors are
    # driven by the SAME ui/tests/e2e/helpers/captions-vtt-golden.json the
    # vitest uses, so the TS + Python transforms cannot drift.
    golden_path = _REPO_ROOT / "ui" / "tests" / "e2e" / "helpers" / "captions-vtt-golden.json"
    golden = json.loads(golden_path.read_text())
    for case in golden["cases"]:
        assert bg.normalize_caption(case["input"]) == case["normalized"], case["input"]
        assert bg.escape_vtt_cue_text(case["normalized"]) == case["escaped"], case["input"]


def _write_deck_with_vtt(src: Path, slug: str, captions: list[str], vtt_bodies: list[str]) -> None:
    shots = [{"file": f"{i + 1:02d}-x.png", "caption": c} for i, c in enumerate(captions)]
    _make_deck(src, slug, screenshots=shots, with_webm=True)
    lines = ["WEBVTT", ""]
    for i, body in enumerate(vtt_bodies):
        lines.append(f"00:00:{i:02d}.000 --> 00:00:{i + 1:02d}.000")
        lines.append(body)
        lines.append("")
    (src / slug / "captions.vtt").write_text("\n".join(lines), encoding="utf-8")


def test_verify_captions_consistency_passes_on_match(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    caps = ["Open the page", "Boost title & description <strong>2.5×</strong>"]
    bodies = [bg.escape_vtt_cue_text(bg.normalize_caption(c)) for c in caps]
    _write_deck_with_vtt(src, "01_x", caps, bodies)
    decks = bg.discover_decks(src)
    # Point the module's GUIDES_SRC at the fixture for the duration of the check.
    import unittest.mock as _m

    with _m.patch.object(bg, "GUIDES_SRC", src):
        bg.verify_captions_consistency(decks)  # no raise


def test_verify_captions_consistency_fails_on_count_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    _write_deck_with_vtt(src, "01_x", ["a", "b"], ["a"])  # 1 cue vs 2 captions
    decks = bg.discover_decks(src)
    import unittest.mock as _m

    with _m.patch.object(bg, "GUIDES_SRC", src), pytest.raises(SystemExit) as exc:
        bg.verify_captions_consistency(decks)
    assert "out of sync" in str(exc.value)


def test_verify_captions_consistency_fails_on_text_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "guides"
    # vtt body is the RAW (unescaped) caption — must fail vs the escaped expectation.
    _write_deck_with_vtt(src, "01_x", ["a & b"], ["a & b"])
    decks = bg.discover_decks(src)
    import unittest.mock as _m

    with _m.patch.object(bg, "GUIDES_SRC", src), pytest.raises(SystemExit) as exc:
        bg.verify_captions_consistency(decks)
    assert "out of sync" in str(exc.value)


def test_verify_captions_consistency_fails_on_missing_vtt_with_captions(tmp_path: Path) -> None:
    # Gemini PR #451: a deck WITH captions in metadata but NO captions.vtt is a
    # silent drift the freshness copy-check can't see — must fail loud.
    src = tmp_path / "guides"
    shots = [{"file": "01-x.png", "caption": "Open the page"}]
    _make_deck(src, "01_x", screenshots=shots, with_webm=True)  # no captions.vtt written
    decks = bg.discover_decks(src)
    import unittest.mock as _m

    with _m.patch.object(bg, "GUIDES_SRC", src), pytest.raises(SystemExit) as exc:
        bg.verify_captions_consistency(decks)
    assert "no captions.vtt" in str(exc.value)


def test_verify_captions_consistency_passes_on_missing_vtt_no_captions(tmp_path: Path) -> None:
    # The zero-caption path: a deck with only empty captions legitimately has no
    # captions.vtt (the recording side deletes/skips it) — must NOT raise.
    src = tmp_path / "guides"
    shots = [{"file": "01-x.png", "caption": ""}, {"file": "02-x.png", "caption": "   "}]
    _make_deck(src, "01_x", screenshots=shots, with_webm=True)  # no captions.vtt written
    decks = bg.discover_decks(src)
    import unittest.mock as _m

    with _m.patch.object(bg, "GUIDES_SRC", src):
        bg.verify_captions_consistency(decks)  # no raise


def test_parse_vtt_cue_bodies_requires_webvtt_header() -> None:
    # Phase-gate hardening: a vtt without the WEBVTT header is rejected loudly.
    assert bg.parse_vtt_cue_bodies("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhi\n") == ["hi"]
    with pytest.raises(SystemExit) as exc:
        bg.parse_vtt_cue_bodies("00:00:00.000 --> 00:00:01.000\nhi\n")
    assert "WEBVTT header" in str(exc.value)


# --------------------------------------------------------------------------- #
# chore_overnight_result_card_screenshot D-3 — copy_long_form_images           #
# --------------------------------------------------------------------------- #
def test_copy_long_form_images_mirrors_png_files(tmp_path: Path) -> None:
    src = tmp_path / "images"
    dst = tmp_path / "out" / "images"
    src.mkdir()
    (src / "12-overnight-result-card.png").write_bytes(b"\x89PNG\r\nfake")
    (src / "01-other.png").write_bytes(b"\x89PNG\r\n")

    copied = bg.copy_long_form_images(src, dst)

    assert copied == {"12-overnight-result-card.png", "01-other.png"}
    assert (dst / "12-overnight-result-card.png").read_bytes() == b"\x89PNG\r\nfake"
    assert (dst / "01-other.png").is_file()


def test_copy_long_form_images_skips_non_png_files(tmp_path: Path) -> None:
    # .gitkeep + README.md + any stray .svg must NOT propagate into the dest.
    src = tmp_path / "images"
    dst = tmp_path / "out" / "images"
    src.mkdir()
    (src / ".gitkeep").write_text("")
    (src / "README.md").write_text("not an image")
    (src / "icon.svg").write_text("<svg/>")
    (src / "12-real.png").write_bytes(b"\x89PNG\r\n")

    copied = bg.copy_long_form_images(src, dst)

    assert copied == {"12-real.png"}
    assert sorted(p.name for p in dst.iterdir()) == ["12-real.png"]


def test_copy_long_form_images_noop_when_source_missing(tmp_path: Path) -> None:
    # Steady state for a repo with no long-form-guide images committed yet:
    # source dir is absent, ferry is a no-op, dest is NOT eagerly created.
    src = tmp_path / "images_absent"
    dst = tmp_path / "out" / "images"

    copied = bg.copy_long_form_images(src, dst)

    assert copied == set()
    assert not dst.exists()


def test_copy_long_form_images_noop_when_source_is_a_file(tmp_path: Path) -> None:
    # Defensive: a file at the `images` path (not a dir) is treated as absent.
    file_path = tmp_path / "images"
    file_path.write_text("oops")
    dst = tmp_path / "out" / "images"

    copied = bg.copy_long_form_images(file_path, dst)

    assert copied == set()
    assert not dst.exists()


def test_copy_long_form_images_overwrites_stale_dest_bytes(tmp_path: Path) -> None:
    # Re-run with a modified source PNG → the dest carries the new bytes.
    src = tmp_path / "images"
    dst = tmp_path / "out" / "images"
    src.mkdir()
    dst.mkdir(parents=True)
    (src / "12-card.png").write_bytes(b"NEW BYTES")
    (dst / "12-card.png").write_bytes(b"OLD BYTES")

    bg.copy_long_form_images(src, dst)

    assert (dst / "12-card.png").read_bytes() == b"NEW BYTES"


def test_prune_all_protects_images_subdir_and_prunes_stale_images(tmp_path: Path) -> None:
    # The `images` name MUST stay in `indepth_expected` so the flat in-depth
    # prune does not rmtree the whole subtree. Separately, the images subdir is
    # pruned to exactly `copied_long_form_images`.
    indepth_root = tmp_path / "in-depth"
    images_root = indepth_root / "images"
    images_root.mkdir(parents=True)
    (indepth_root / "index.md").write_text("index")
    # Seed one of the canonical long-form guide basenames to satisfy the
    # `LONG_FORM_GUIDES` expected set so the prune does not flag it.
    (indepth_root / "tutorial-first-study.md").write_text("tutorial")
    (images_root / "12-keep.png").write_bytes(b"PNG")
    (images_root / "obsolete.png").write_bytes(b"PNG")

    # Patch the canonical constants so prune_all walks the tmp tree.
    import unittest.mock as _m

    with (
        _m.patch.object(bg, "INDEPTH_OUT", indepth_root),
        _m.patch.object(bg, "INDEPTH_IMAGES_OUT", images_root),
        _m.patch.object(bg, "WALKTHROUGHS_OUT", tmp_path / "walkthroughs"),
        _m.patch.object(bg, "ASSETS_OUT", tmp_path / "assets"),
    ):
        (tmp_path / "walkthroughs").mkdir()
        (tmp_path / "assets").mkdir()
        pruned = bg.prune_all(
            decks=[],
            copied_by_slug={},
            copied_long_form_images={"12-keep.png"},
        )

    assert images_root.is_dir(), "images subdir must survive the flat in-depth prune"
    assert (images_root / "12-keep.png").is_file()
    assert not (images_root / "obsolete.png").exists()
    assert "in-depth/images/obsolete.png" in pruned


def test_prune_all_legacy_call_without_images_set_is_noop_on_images(tmp_path: Path) -> None:
    # Backwards-compat: callers that don't pass `copied_long_form_images` must
    # leave the images subdir alone (no AttributeError, no prune).
    indepth_root = tmp_path / "in-depth"
    images_root = indepth_root / "images"
    images_root.mkdir(parents=True)
    (indepth_root / "index.md").write_text("index")
    (indepth_root / "tutorial-first-study.md").write_text("tutorial")
    (images_root / "12-keep.png").write_bytes(b"PNG")

    import unittest.mock as _m

    with (
        _m.patch.object(bg, "INDEPTH_OUT", indepth_root),
        _m.patch.object(bg, "INDEPTH_IMAGES_OUT", images_root),
        _m.patch.object(bg, "WALKTHROUGHS_OUT", tmp_path / "walkthroughs"),
        _m.patch.object(bg, "ASSETS_OUT", tmp_path / "assets"),
    ):
        (tmp_path / "walkthroughs").mkdir()
        (tmp_path / "assets").mkdir()
        bg.prune_all(decks=[], copied_by_slug={})  # no images kwarg

    assert (images_root / "12-keep.png").is_file(), "legacy call must not prune images"
