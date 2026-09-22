import json

import pytest

from nodefusion.host.bundle import encode
from scripts.consolidate_artifacts import merge_ucore, merge_video
from scripts.finalize_artifacts import finalize
from scripts.regenerate_artifact import sha256


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
