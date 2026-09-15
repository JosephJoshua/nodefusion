"""Ignored local recordings must not make normal test discovery unbounded."""

from __future__ import annotations

import pytest

from conftest import corpus_run_dirs


def _trace(root, name, size):
    d = root / name
    d.mkdir()
    with (d / "trace.nfb").open("wb") as f:
        f.truncate(size)
    return d


def test_corpus_discovery_has_a_default_size_bound(tmp_path, monkeypatch):
    small = _trace(tmp_path, "small", 2 * 1024 * 1024)
    _trace(tmp_path, "showcase", 300 * 1024 * 1024)
    monkeypatch.delenv("NF_CORPUS_MAX_TRACE_MIB", raising=False)
    assert corpus_run_dirs(tmp_path) == [small]


def test_zero_size_bound_explicitly_enables_exhaustive_corpus(tmp_path, monkeypatch):
    small = _trace(tmp_path, "small", 1)
    large = _trace(tmp_path, "large", 300 * 1024 * 1024)
    monkeypatch.setenv("NF_CORPUS_MAX_TRACE_MIB", "0")
    assert corpus_run_dirs(tmp_path) == [large, small]


def test_invalid_corpus_limit_is_an_actionable_usage_error(tmp_path, monkeypatch):
    monkeypatch.setenv("NF_CORPUS_MAX_TRACE_MIB", "many")
    with pytest.raises(pytest.UsageError, match="must be an integer"):
        corpus_run_dirs(tmp_path)
