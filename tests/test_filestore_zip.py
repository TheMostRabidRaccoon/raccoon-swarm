"""zip_directory_bytes — the download half of the /filestore/download route.

The route itself is a thin send_file wrapper (untested like its siblings);
the safety and packaging logic lives here in the filestore and is what these
cover. Stdlib-only."""
import io
import zipfile

import swarm_filestore as fs


def test_zips_a_joy_run_folder(storage):
    fs.write_file("joy/runs/2026-07-03_kata-004/artifact.md", "# fixed it")
    fs.write_file("joy/runs/2026-07-03_kata-004/reflection.md", "worked/didn't/next")
    fs.write_file("joy/runs/2026-07-03_kata-004/scorecard.json", "{}")
    fs.write_file("joy/runs/2026-07-04_other/artifact.md", "not this run")

    data = fs.zip_directory_bytes("joy/runs/2026-07-03_kata-004")
    assert data is not None
    names = sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == [
        "joy/runs/2026-07-03_kata-004/artifact.md",
        "joy/runs/2026-07-03_kata-004/reflection.md",
        "joy/runs/2026-07-03_kata-004/scorecard.json",
    ]
    got = zipfile.ZipFile(io.BytesIO(data)).read(names[0]).decode()
    assert got == "# fixed it"


def test_missing_or_empty_dir_returns_none(storage):
    assert fs.zip_directory_bytes("joy/runs/2026-01-01_ghost") is None


def test_unsafe_dir_returns_none(storage):
    fs.write_file("positions/real.md", "x")
    assert fs.zip_directory_bytes("../../etc") is None
    assert fs.zip_directory_bytes("/etc") is None


def test_visibility_matches_list_files(storage):
    # Underscore-prefixed files are invisible to list_files; the zip must not
    # smuggle them out either.
    fs.write_file("logs/audit.md", "public")
    root = fs._storage_root()
    (root / "logs" / "_private.md").write_text("hidden")
    data = fs.zip_directory_bytes("logs")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "logs/audit.md" in names
    assert all("_private" not in n for n in names)
