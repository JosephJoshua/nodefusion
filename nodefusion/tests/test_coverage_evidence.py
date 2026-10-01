"""Strict coverage claims are checked against the shipped report sidecars."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.regenerate_artifact import sha256

ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"


def _evidence(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value.get('report', value)


def _chapter(kernel: str, chapter: int):
    folder = ARTIFACTS / kernel / f'ch{chapter}' / '2026a'
    sidecar = folder / 'recording.json'
    if chapter == 2:
        prefix = 'rcore' if kernel == 'rcore' else 'ucore'
        sidecar = folder / f'{prefix}-2026A-ch2-reference.json'
    value = json.loads(sidecar.read_text(encoding='utf-8'))
    return value['report'], folder / value['html']


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
        ARTIFACTS / "rcore/ch7/2026a/recording.json",
        ARTIFACTS / "rcore/ch8/2026a/recording.json",
        ARTIFACTS / "ucoreos/ch8/2026a/recording.json",
    ]
    records = [_evidence(path) for path in paths]
    assert [item["run"] for item in records] == [
        "starry-cache-semantic", "rcore-2026A-ch7-basic-observed",
        "rcore-2026A-ch8-basic-observed-v3", "ucore-2026A-ch8-basic-observed"
    ]
    for record in records:
        _strict(record)
        assert record["archive_bytes"]["trace.nfb"] > 0
        assert record["archive_bytes"]["kernel_elf"] > 0


def test_non_journaled_kernels_do_not_count_log_commit_as_a_gap():
    for path in (ARTIFACTS / "rcore/ch7/2026a/recording.json",
                 ARTIFACTS / "ucoreos/ch8/2026a/recording.json"):
        metrics = _evidence(path)["coverage"]["metrics"]
        assert metrics["not_applicable"] == ["log_commits"]
        assert metrics["covered"] == metrics["applicable"]


def test_all_rcore_chapter_reports_are_strict_and_hashed():
    for chapter in range(1, 9):
        record, report = _chapter('rcore', chapter)
        _strict(record)
        assert record["run"].startswith(f"rcore-2026A-ch{chapter}-")
        assert report.stat().st_size == record["html_bytes"]
        assert sha256(report) == record["html_sha256"]


def test_ucore_chapter_matrix_is_strict_complete():
    for chapter in range(1, 9):
        record, report = _chapter('ucoreos', chapter)
        _strict(record)
        assert record["archive_bytes"]["trace.nfb"] > 0
        assert record["archive_bytes"]["kernel_elf"] > 0
        assert record["run"].startswith(f"ucore-2026A-ch{chapter}-")
        assert report.stat().st_size == record["html_bytes"]
        assert sha256(report) == record["html_sha256"]
