"""Shared pytest fixtures for the swarm test suite.

Every filestore/dispatch module resolves its storage root from RRI_STORAGE_DIR
*at call time* (see swarm_filestore._storage_root), so isolating a test is just
a matter of pointing that env var at a fresh tmp dir. No module reloads needed.
"""
import os

import pytest


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Point the swarm filestore at an isolated tmp dir for the duration of a test.

    Returns the <tmp>/swarm root that the modules will actually use.
    """
    monkeypatch.setenv("RRI_STORAGE_DIR", str(tmp_path))
    return tmp_path / "swarm"
