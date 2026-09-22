import json
from pathlib import Path

import pytest

from nodefusion.host.bundle import encode
from scripts.finalize_artifacts import finalize
from scripts.regenerate_artifact import sha256, smoke_report


ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"

EXPECTED_RUNS = {
    "arceos-helloworld", "arceos-lazymapping", "arceos-tracecomplete",
    "arceos-userprivilege", "lab3-cowtest-mac", "starry-100pct-final",
    "starry-forkecho-ram512", "starry-fsprobe-ram512",
    *{f"rcore-ch{n}" for n in range(1, 9)},
    *{f"ucore-ch{n}" for n in range(1, 9)},
}


def report_sidecars():
    entries = []
    for path in sorted(ARTIFACTS.rglob("*.evidence.json")):
        entries.append((path, path.with_name(path.name.removesuffix(".evidence.json") + ".html")))
    for path in sorted(ARTIFACTS.glob("ucoreos/ch*/coverage.json")):
        htmls = list(path.parent.glob("ucore-*.html"))
        assert len(htmls) == 1
        entries.append((path, htmls[0]))
    for path in sorted(ARTIFACTS.rglob("*.json")):
        if path.name == "coverage.json" or path.name.endswith(".evidence.json"):
            continue
        sidecar = json.loads(path.read_text(encoding="utf-8"))
        if sidecar.get("report", {}).get("schema") == "nodefusion.artifact-evidence/1":
            entries.append((path, path.with_name(sidecar["html"])))
    return sorted(entries)


def record_from(path):
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    return sidecar.get("report", sidecar)


def test_all_chapter_and_app_artifacts_are_present():
    entries = report_sidecars()
    assert len(entries) == 24
    runs = {record_from(path)["run"] for path, _ in entries}
    assert len(runs) == 24
    normalized = {name if not name.startswith(("rcore-", "ucore-"))
                  else "-".join(name.split("-")[:2]) for name in runs}
    assert EXPECTED_RUNS <= normalized


def test_tracecomplete_reuses_its_recording_folder():
    folder = ARTIFACTS / "arceos/apps/tracecomplete"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    evidence = record_from(folder / "tracecomplete.evidence.json")
    assert evidence["run"] == manifest["run_name"]
    assert evidence["kernel_elf_sha256"] == manifest["kernel_elf_identity"]["sha256"]
    assert sha256(folder / "tracecomplete.html") == evidence["html_sha256"]


def test_merged_video_evidence_matches_recording():
    for path, _ in report_sidecars():
        sidecar = json.loads(path.read_text(encoding="utf-8"))
        if sidecar.get("format") != "nodefusion.video-evidence/1":
            continue
        report = sidecar["report"]
        assert sidecar["info"]["runs"] == [report["run"]]
        assert sidecar["info"]["kernel_elf_sha256"] == report["kernel_elf_sha256"]
        mp4 = path.with_name(sidecar["mp4"])
        assert mp4.stat().st_size == sidecar["bytes"]
        assert sha256(mp4) == sidecar["mp4_sha256"]


def _report(path: Path, entries: list[int], retained: int) -> None:
    data = {
        "events": {"insn": list(range(len(entries))), "entry": entries,
                   "caller": [-1] * len(entries),
                   "entry_name": [-1] * len(entries)},
        "meta": {
            "function_entries": {"raw": 4, "retained": retained},
            "event_selection": {"retained": len(entries)},
        },
    }
    path.write_text(
        '<div id="panel-functions"></div>'
        f'<script type="application/nodefusion">{encode(data)}</script>',
        encoding="utf-8")


def test_smoke_report_checks_function_entry_count(tmp_path):
    path = tmp_path / "report.html"
    _report(path, [1, 0, 1], 2)
    assert smoke_report(path)["meta"]["function_entries"]["raw"] == 4


def test_smoke_report_rejects_mismatched_entry_count(tmp_path):
    path = tmp_path / "report.html"
    _report(path, [1, 0, 1], 3)
    with pytest.raises(ValueError, match="function-entry counts"):
        smoke_report(path)


def test_smoke_report_rejects_browser_overflow(tmp_path):
    path = tmp_path / "report.html"
    _report(path, [1, 0, 1], 2)
    data = {
        "events": {"insn": [0, 1, 2], "entry": [1, 0, 1],
                   "caller": [-1] * 3, "entry_name": [-1] * 3},
        "meta": {"function_entries": {"raw": 4, "retained": 2},
                 "event_selection": {"retained": 3, "target_limit": 2}},
    }
    path.write_text(
        '<div id="panel-functions"></div>'
        f'<script type="application/nodefusion">{encode(data)}</script>',
        encoding="utf-8")
    with pytest.raises(ValueError, match="browser budget"):
        smoke_report(path)


def test_finalize_demangles_and_updates_verified_evidence(tmp_path):
    raw = ("_RNvXs5_NtNtNtNtCsaZSK9boPIKd_13starry_kernel2mm6aspace"
           "7backend3cowNtB5_10CowBackendNtB7_10BackendOps9clone_map")
    html = tmp_path / "report.html"
    data = {
        "events": {"insn": [1], "entry": [1], "caller": [0],
                   "entry_name": [1]},
        "dict": {"funcs": [raw, "map_page"]},
        "meta": {"function_entries": {"raw": 1, "retained": 1},
                 "event_selection": {"retained": 1, "target_limit": 10}},
    }
    html.write_text('<div id="panel-functions"></div>'
                    f'<script type="application/nodefusion">{encode(data)}</script>',
                    encoding="utf-8")
    sidecar = tmp_path / "report.evidence.json"
    sidecar.write_text(json.dumps({"schema": "nodefusion.artifact-evidence/1",
                                   "html_sha256": sha256(html)}), encoding="utf-8")
    assert finalize(sidecar) == 1
    assert finalize(sidecar) == 0
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert record["html_sha256"] == sha256(html)
    assert record["event_selection"]["retained"] == 1
    assert smoke_report(html)["dict"]["funcs"][0].endswith("CowBackend::clone_map")


@pytest.mark.parametrize("evidence,html", report_sidecars())
def test_regenerated_artifact_matches_evidence(evidence, html):
    record = record_from(evidence)
    assert len(record["kernel_elf_sha256"]) == 64
    assert set(record["source_sha256"]) == {
        "trace.nfb", "manifest.json", "watchlist.json", "kernel_layout.json"
    }
    assert all(len(value) == 64 for value in record["source_sha256"].values())
    assert html.stat().st_size == record["html_bytes"]
    assert sha256(html) == record["html_sha256"]
    data = smoke_report(html)
    assert data["meta"]["function_entries"] == {
        key: record["function_trace"][key] for key in ("raw", "retained")
    }
    if record["function_trace"].get("returns"):
        assert data["meta"]["function_returns"] == {
            "raw": record["function_trace"]["returns"],
            "matched": record["function_trace"]["matched_returns"],
            "nested_entries": record["function_trace"]["nested_entries"],
        }
    assert data["meta"]["event_selection"] == record["event_selection"]
    assert data["meta"]["capability"]["coverage"] == record["coverage"]
