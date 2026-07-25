"""Image visibility in filestore listings.

Regression tests for the Session 142 "verification-blind" false diagnosis:
185 PNGs existed on disk while filestore_list returned an empty file list,
so the swarm concluded image generation had failed — twice (July 4 and
July 13). Images must be visible in listings (with byte sizes) even though
they stay outside the text read/search/zip lanes.
"""
import pytest

import swarm_filestore as fs


def _put_png(rel_path: str, n_bytes: int = 64) -> None:
    """Drop a fake PNG straight onto disk — image bytes never travel through
    write_file (which is text-lane only), mirroring how imagegen persists."""
    target = fs._storage_root() / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (n_bytes - 8))


def test_list_images_sees_pngs_with_sizes(storage):
    _put_png("artifacts/images/portfolio-intake.png", 128)
    _put_png("artifacts/images/council-scene.PNG", 96)  # case-insensitive suffix

    imgs = fs.list_images("artifacts/images")
    paths = {i["path"]: i["bytes"] for i in imgs}
    assert paths["artifacts/images/portfolio-intake.png"] == 128
    assert paths["artifacts/images/council-scene.PNG"] == 96


def test_images_stay_out_of_text_lanes(storage):
    fs.write_file("artifacts/notes.md", "text file")
    _put_png("artifacts/images/x.png")

    assert "artifacts/images/x.png" not in fs.list_files("artifacts")
    assert "artifacts/notes.md" in fs.list_files("artifacts")
    assert fs.list_images("artifacts") == [
        {"path": "artifacts/images/x.png", "bytes": 64}
    ]


def test_list_images_skips_underscore_and_unsafe_dirs(storage):
    _put_png("artifacts/_hidden.png")
    assert fs.list_images("artifacts") == []
    assert fs.list_images("../etc") == []


def test_filestore_list_tool_reports_images_field(storage):
    """The dispatch result must show images even when `files` is empty —
    the exact shape that produced the false 'pipeline broken' conviction."""
    # swarm_tools pulls the web stack (requests); CI is stdlib-only by design.
    swarm_tools = pytest.importorskip("swarm_tools")
    _put_png("artifacts/images/kyle-tie.png", 100)

    out = swarm_tools._dispatch_filestore_list("artifacts/images")
    assert out["files"] == []
    assert out["images"] == [{"path": "artifacts/images/kyle-tie.png", "bytes": 100}]
