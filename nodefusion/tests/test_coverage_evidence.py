"""Strict coverage claims are checked against the shipped report sidecars."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.regenerate_artifact import sha256

ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"


def _evidence(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _strict(record: dict) -> None:
    assert record["schema"] == "nodefusion.artifact-evidence/1"
    coverage = record["coverage"]
    assert coverage["status"] == "complete"
    assert coverage["percent"] == 100.0
    assert coverage["blockers"] == []
    assert coverage["semantic_events"]["unknown"] == 0
    assert coverage["snapshots"]["incomplete"] == 0
    assert coverage["manifest_fields"]["unresolved"] == 0
    assert all(len(value) == 64 for value in record["source_sha256"].values())


def test_strict_coverage_evidence_has_no_blockers():
    paths = [
        ARTIFACTS / "starryos/showcase/starry-cache-semantic.evidence.json",
        ARTIFACTS / "rcore/ch7/rcore-ch7-100pct-final.evidence.json",
        ARTIFACTS / "rcore/ch8/rcore-ch8-100pct-return.evidence.json",
        ARTIFACTS / "ucoreos/ch8/coverage.json",
    ]
    records = [_evidence(path) for path in paths]
    assert [item["run"] for item in records] == [
        "starry-cache-semantic", "rcore-ch7-observation-final",
        "rcore-ch8-100pct-return", "ucore-ch8-return-aware"
    ]
    for record in records:
        _strict(record)
        assert record["archive_bytes"]["trace.nfb"] > 0
        assert record["archive_bytes"]["kernel_elf"] > 0


def test_non_journaled_kernels_do_not_count_log_commit_as_a_gap():
    for path in (ARTIFACTS / "rcore/ch7/rcore-ch7-100pct-final.evidence.json",
                 ARTIFACTS / "ucoreos/ch8/coverage.json"):
        metrics = _evidence(path)["coverage"]["metrics"]
        assert metrics["not_applicable"] == ["log_commits"]
        assert metrics["covered"] == metrics["applicable"]


def test_all_rcore_chapter_reports_are_strict_and_hashed():
    stems = {1: "bare", 2: "batch", 3: "sched", 4: "exact",
             5: "exact", 6: "usertest", 7: "100pct-final",
             8: "100pct-return"}
    for chapter, suffix in stems.items():
        stem = f"rcore-ch{chapter}-{suffix}"
        folder = ARTIFACTS / "rcore" / f"ch{chapter}"
        sidecar = folder / (stem + (".json" if chapter <= 6 else ".evidence.json"))
        value = _evidence(sidecar)
        record = value.get("report", value)
        report = folder / f"{stem}.html"
        _strict(record)
        assert record["run"].startswith(f"rcore-ch{chapter}-")
        assert report.stat().st_size == record["html_bytes"]
        assert sha256(report) == record["html_sha256"]


def test_ucore_chapter_matrix_is_strict_complete():
    base = ARTIFACTS / "ucoreos"
    for chapter in range(1, 9):
        folder = base / f"ch{chapter}"
        record = _evidence(folder / "coverage.json")
        _strict(record)
        assert record["archive_bytes"]["trace.nfb"] > 0
        assert record["archive_bytes"]["kernel_elf"] > 0
        assert record["run"].startswith(f"ucore-ch{chapter}-")
        reports = list(folder.glob("ucore-*.html"))
        assert len(reports) == 1
        assert reports[0].stat().st_size == record["html_bytes"]
        assert sha256(reports[0]) == record["html_sha256"]
