"""Smoke tests for the shared pipeline registry (no network)."""

from __future__ import annotations

from pipelines.registry import PIPELINES, get_pipeline, list_pipeline_ids, script_path


def test_registry_has_core_markets():
    ids = set(list_pipeline_ids())
    assert "norway" in ids
    assert "germany" in ids
    assert "jodi" in ids


def test_jodi_not_in_default_batch():
    batch = set(list_pipeline_ids(default_batch_only=True))
    assert "norway" in batch
    assert "jodi" not in batch


def test_script_paths_exist():
    for pid in PIPELINES:
        path = script_path(pid)
        assert path.is_file(), path


def test_get_pipeline_unknown():
    try:
        get_pipeline("atlantis")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass
