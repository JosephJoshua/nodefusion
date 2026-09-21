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


def test_all_chapter_and_app_artifacts_are_present():
    files = list(ARTIFACTS.rglob("*.evidence.json"))
    runs = {json.loads(path.read_text(encoding="utf-8"))["run"] for path in files}
    normalized = {name if not name.startswith(("rcore-", "ucore-"))
                  else "-".join(name.split("-")[:2]) for name in runs}
    assert EXPECTED_RUNS <= normalized


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
    sidecar.write_text(json.dumps({"html_sha256": sha256(html)}), encoding="utf-8")
    assert finalize(sidecar) == 1
    assert finalize(sidecar) == 0
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert record["html_sha256"] == sha256(html)
    assert record["event_selection"]["retained"] == 1
    assert smoke_report(html)["dict"]["funcs"][0].endswith("CowBackend::clone_map")


@pytest.mark.parametrize("evidence", sorted(ARTIFACTS.rglob("*.evidence.json")))
def test_regenerated_artifact_matches_evidence(evidence):
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert len(record["kernel_elf_sha256"]) == 64
    assert set(record["source_sha256"]) == {
        "trace.nfb", "manifest.json", "watchlist.json", "kernel_layout.json"
    }
    assert all(len(value) == 64 for value in record["source_sha256"].values())
    html = evidence.with_name(evidence.name.removesuffix(".evidence.json") + ".html")
    assert html.stat().st_size == record["html_bytes"]
    assert sha256(html) == record["html_sha256"]
    data = smoke_report(html)
    assert data["meta"]["function_entries"] == {
        key: record["function_trace"][key] for key in ("raw", "retained")
    }
    assert data["meta"]["event_selection"] == record["event_selection"]
    assert data["meta"]["capability"]["coverage"] == record["coverage"]
