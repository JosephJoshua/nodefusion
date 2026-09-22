import json
from types import SimpleNamespace

import pytest

from nodefusion.host.bundle import encode
from scripts.consolidate_artifacts import merge_ucore, merge_video
from scripts.finalize_artifacts import finalize
from scripts.regenerate_artifact import (_sidecar_value, evidence_destination,
                                         regenerate, sha256)


def _fixture(tmp_path):
    html = tmp_path / "sample.html"
    data = {
        "events": {"insn": [], "entry": [], "caller": [], "entry_name": []},
        "dict": {"funcs": []},
        "meta": {"capability": {"coverage": {"status": "complete"}},
                 "function_entries": {"raw": 0, "retained": 0},
                 "event_selection": {"retained": 0}},
    }
    html.write_text(
        '<div id="panel-functions"></div>'
        f'<script type="application/nodefusion">{encode(data)}</script>',
        encoding="utf-8")
    evidence = {"schema": "nodefusion.artifact-evidence/1", "run": "sample",
                "kernel_elf_sha256": "e" * 64, "source_sha256": {"trace.nfb": "t" * 64},
                "coverage": {"status": "complete"}, "html_sha256": sha256(html),
                "html_bytes": html.stat().st_size}
    sidecar = tmp_path / "sample.evidence.json"
    sidecar.write_text(json.dumps(evidence), encoding="utf-8")
    return html, sidecar, evidence


def test_merge_video_keeps_both_provenances(tmp_path):
    _, sidecar, evidence = _fixture(tmp_path)
    mp4 = tmp_path / "sample.mp4"
    mp4.write_bytes(b"video")
    video_path = tmp_path / "sample.json"
    video_path.write_text(json.dumps({
        "format": "nodefusion.video-evidence/1", "html": "sample.html",
        "mp4": "sample.mp4", "bytes": 5, "mp4_sha256": sha256(mp4),
        "info": {"runs": ["sample"], "kernel_elf_sha256": "e" * 64},
    }), encoding="utf-8")
    merge_video(video_path, sidecar)
    assert not sidecar.exists()
    assert json.loads(video_path.read_text())["report"] == evidence
    assert finalize(video_path) == 0


def test_merge_video_rejects_different_kernel(tmp_path):
    _, sidecar, _ = _fixture(tmp_path)
    mp4 = tmp_path / "sample.mp4"
    mp4.write_bytes(b"video")
    video_path = tmp_path / "sample.json"
    video_path.write_text(json.dumps({
        "format": "nodefusion.video-evidence/1", "html": "sample.html",
        "mp4": "sample.mp4", "bytes": 5, "mp4_sha256": sha256(mp4),
        "info": {"runs": ["sample"], "kernel_elf_sha256": "different"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="not the same archived run"):
        merge_video(video_path, sidecar)
    assert sidecar.exists()
    assert "report" not in json.loads(video_path.read_text())


def test_merge_ucore_replaces_stale_html_hash(tmp_path):
    html, sidecar, evidence = _fixture(tmp_path)
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"chapter": {"run": "sample",
        "trace_sha256": "t" * 64, "kernel_elf_sha256": "e" * 64,
        "html_sha256": "old"}}), encoding="utf-8")
    merge_ucore(coverage, sidecar, html)
    assert not sidecar.exists()
    assert json.loads(coverage.read_text()) == evidence


def test_regeneration_selects_and_updates_existing_video(tmp_path):
    _, sidecar, report = _fixture(tmp_path)
    mp4 = tmp_path / "sample.mp4"
    mp4.write_bytes(b"video")
    video_path = tmp_path / "sample.json"
    video_path.write_text(json.dumps({
        "format": "nodefusion.video-evidence/1", "html": "sample.html",
        "mp4": "sample.mp4", "bytes": 5, "mp4_sha256": sha256(mp4),
        "info": {"runs": ["sample"], "kernel_elf_sha256": "e" * 64},
        "report": report,
    }), encoding="utf-8")
    assert evidence_destination(tmp_path / "sample.html") == video_path
    assert _sidecar_value(video_path, report)["report"] == report
    changed = {**report, "source_sha256": {"trace.nfb": "other"}}
    with pytest.raises(ValueError, match="different trace"):
        _sidecar_value(video_path, changed)
    sidecar.unlink()


def test_regeneration_selects_chapter_and_retains_archived_sizes(tmp_path):
    html, sidecar, report = _fixture(tmp_path)
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({**report, "archive_bytes": {
        "trace.nfb": 123, "kernel_elf": 456}}), encoding="utf-8")
    assert evidence_destination(html) == coverage
    assert _sidecar_value(coverage, dict(report))["archive_bytes"] == {
        "trace.nfb": 123, "kernel_elf": 456}
    sidecar.unlink()


def test_complete_report_cannot_be_downgraded(tmp_path):
    _, sidecar, report = _fixture(tmp_path)
    sidecar.write_text(json.dumps(report), encoding="utf-8")
    incomplete = {**report, "coverage": {"status": "incomplete"}}
    with pytest.raises(ValueError, match="complete report"):
        _sidecar_value(sidecar, incomplete)


def test_strict_failure_leaves_existing_output_untouched(tmp_path, monkeypatch):
    import scripts.regenerate_artifact as module

    run = tmp_path / "run"
    run.mkdir()
    for name in module._SOURCE_FILES:
        (run / name).write_bytes(b"source")
    elf = run / "kernel.elf"
    elf.write_bytes(b"elf")
    monkeypatch.setattr(module, "analyze", lambda _: SimpleNamespace(
        manifest={"run_name": "sample"}, kernel_elf_path=elf,
        kernel_kind="rcore"))
    def render(_, path):
        data = {
            "events": {"insn": [], "entry": [], "caller": [], "entry_name": []},
            "meta": {"function_entries": {"raw": 0, "retained": 0},
                     "event_selection": {"retained": 0},
                     "capability": {"coverage": {"status": "incomplete",
                                                 "blockers": ["missing"]}}},
        }
        path.write_text('<div id="panel-functions"></div>'
                        f'<script type="application/nodefusion">{encode(data)}</script>',
                        encoding="utf-8")
    monkeypatch.setattr(module, "render", render)
    html = tmp_path / "sample.html"
    sidecar = tmp_path / "sample.evidence.json"
    html.write_text("old", encoding="utf-8")
    sidecar.write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="strict coverage incomplete"):
        regenerate(run, html, sidecar, replace=True, strict=True)
    assert html.read_text() == "old"
    assert sidecar.read_text() == "old"
