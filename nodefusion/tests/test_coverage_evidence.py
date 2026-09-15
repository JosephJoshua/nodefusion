"""The shipped strict-coverage claim must remain structured and auditable."""

from __future__ import annotations

import json
from pathlib import Path


EVIDENCE = (Path(__file__).resolve().parents[2] / "artifacts" /
            "coverage-100pct-2026-09-15.json")


def test_strict_coverage_evidence_has_no_blockers():
    doc = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert doc["schema"] == "nodefusion.coverage-evidence/1"
    runs = {item["run"]: item for item in doc["runs"]}
    assert set(runs) == {"starry-100pct-final", "rcore-ch7-100pct-final",
                         "ucore-ch8-100pct-final"}
    for item in runs.values():
        coverage = item["coverage"]
        assert coverage["status"] == "complete"
        assert coverage["percent"] == 100.0
        assert coverage["blockers"] == []
        assert coverage["semantic_unknown"] == 0
        assert coverage["semantic_dropped_from_interactive"] == 0
        assert coverage["snapshot_failures"] == 0
        assert coverage["manifest_unresolved"] == 0
        for artifact in item["artifacts"].values():
            assert artifact["bytes"] > 0
            assert len(artifact["sha256"]) == 64


def test_non_journaled_kernels_do_not_count_log_commit_as_a_gap():
    doc = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    by_run = {item["run"]: item for item in doc["runs"]}
    for name in ("rcore-ch7-100pct-final", "ucore-ch8-100pct-final"):
        coverage = by_run[name]["coverage"]
        assert coverage["metrics_not_applicable"] == ["log_commits"]
        assert coverage["metrics_covered"] == coverage["metrics_applicable"]


def test_ucore_chapter_matrix_is_strict_complete():
    base = Path(__file__).resolve().parents[2] / "artifacts" / "ucoreos"
    docs = [json.loads((base / f"ch{chapter}" / "coverage.json").read_text())
            for chapter in range(1, 9)]
    assert docs[0]["strict_invariants"] == {
        "blockers": 0,
        "semantic_dropped_from_interactive": 0,
        "snapshot_failures": 0,
        "manifest_unresolved": 0,
    }
    chapters = [doc["chapter"] for doc in docs]
    assert [row["chapter"] for row in chapters] == list(range(1, 9))
    for row in chapters:
        assert row["status"] == "complete"
        assert row["percent"] == 100.0
        assert row["semantic_unknown"] == 0
        assert row["metrics_applicable"] >= 0
        assert row["trace_bytes"] > 0
        assert row["html_bytes"] > 0
        assert len(row["trace_sha256"]) == 64
        assert len(row["html_sha256"]) == 64
        assert len(row["kernel_elf_sha256"]) == 64
