from pathlib import Path

import pytest

from scripts.serve_presentation_assets import CONTENT_DIRECTORIES, content_directory


def test_presentation_content_roots_are_explicit_and_local():
    assert set(CONTENT_DIRECTORIES) == {"benchmarks", "distribution", "noise"}
    root = Path(__file__).parents[2].resolve()
    assert all(path.resolve().is_relative_to(root) for path in CONTENT_DIRECTORIES.values())


def test_missing_presentation_content_has_actionable_error(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setitem(CONTENT_DIRECTORIES, "noise", missing)

    with pytest.raises(FileNotFoundError, match="Generate that visualization"):
        content_directory("noise")
