import json
from pathlib import Path

import pytest

from nodefusion.host.bundle import encode
from scripts.finalize_artifacts import finalize, finalize_comparison, refresh_assets, refresh_shell
from scripts.regenerate_artifact import sha256, smoke_report


ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"

EXPECTED_RUNS = {
    "arceos-helloworld", "arceos-lazymapping", "arceos-tracecomplete",
    "arceos-userprivilege", "lab3-cowtest-mac", "boot-trace", "lab3-lazy",
    "rcore-fs", "rcore-panic", "starry-cache-semantic",
    "starry-forkecho-ram512", "starry-fsprobe-ram512",
}
COURSE_RUNS = {"rcore-2026A-ch3-observed", "ucore-2026A-ch3-batch",
               "rcore-2026A-ch1-verified", "ucore-2026A-ch1-verified",
               "rcore-2026A-ch2-reference", "ucore-2026A-ch2-reference",
               "ucore-2026A-ch2-stack-fixed", "ucore-2026A-ch2-faults",
               "rcore-2026A-ch4-observed", "ucore-2026A-ch4-observed",
               "ucore-2026A-ch4-pagetable",
               "rcore-2026A-ch5-basic-observed-v2",
               "rcore-2026A-ch5-extended-observed-v2",
               "ucore-2026A-ch5-observed",
               "rcore-2026A-ch6-basic-observed",
               "rcore-2026A-ch6-extended-observed",
               "ucore-2026A-ch6-basic-observed",
               "rcore-2026A-ch7-basic-observed",
               "rcore-2026A-ch7-signals-peer-observed",
               "rcore-2026A-ch7-signals-all-observed",
               "rcore-2026A-ch7-redirect-observed",
               "ucore-2026A-ch7-basic-observed",
               "ucore-2026A-ch7-pipe-probe-observed",
               "rcore-2026A-ch8-basic-observed-v3",
               "rcore-2026A-ch8-extended-observed-v3",
               "ucore-2026A-ch8-basic-observed"}


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
    assert len(entries) == len(EXPECTED_RUNS) + len(COURSE_RUNS)
    runs = {record_from(path)["run"] for path, _ in entries}
    assert len(runs) == len(entries)
    assert COURSE_RUNS <= runs
    normalized = {name if not name.startswith(("rcore-", "ucore-"))
                  else "-".join(name.split("-")[:2]) for name in runs}
    assert EXPECTED_RUNS <= normalized


def test_course_artifacts_keep_commands_source_identity_and_raw_counts():
    records = [record for path, _ in report_sidecars()
               if (record := json.loads(path.read_text())).get("schema") == "nodefusion.education-recording/1"]
    assert {record["run"] for record in records} == COURSE_RUNS
    for record in records:
        assert record["schema"] == "nodefusion.education-recording/1"
        expected = {"rcore-2026A-ch1-verified": "qemu_exited",
                    "ucore-2026A-ch2-reference": "timeout"}.get(record["run"], "completed")
        assert record["outcome"] == expected and record["trace_complete"]
        assert len(record["source"]["kernel_commit"]) == 40
        assert len(record["source"]["plugin_sha256"]) == 64
        assert "--watch-all" in record["record_command"]
        assert "--function-returns" in record["record_command"]
        observations = record["observations"]
        if observations.get("schema") == "nodefusion.thread-observations/1":
            assert observations["inputs"]["trace.nfb"] == record["report"]["source_sha256"]["trace.nfb"]
            assert observations["inputs"]["manifest.json"] == record["report"]["source_sha256"]["manifest.json"]
            assert observations["record_counts"]["nftrace"] == sum(observations["nftrace_counts"].values())
        elif observations.get("schema") == "nodefusion.process-observations/1":
            assert observations["trace_sha256"] == record["report"]["source_sha256"]["trace.nfb"]
            assert observations["manifest_sha256"] == record["report"]["source_sha256"]["manifest.json"]
            assert record["analysis_source"]["event_selection"] == record["report"]["event_selection"]
        else:
            assert observations["raw_events"] == record["report"]["event_selection"]["raw"]


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
                 "function_returns": {"raw": 5, "matched": 3, "nested_entries": 1},
                 "event_selection": {"retained": 1, "target_limit": 10}},
    }
    html.write_text('<div id="panel-functions"></div>'
                    f'<script type="application/nodefusion">{encode(data)}</script>',
                    encoding="utf-8")
    sidecar = tmp_path / "report.evidence.json"
    sidecar.write_text(json.dumps({"schema": "nodefusion.artifact-evidence/1",
                                   "function_trace": {"returns": 5, "matched_returns": 1, "nested_entries": 0},
                                   "observations": {"report_function_returns": {"raw": 5, "matched": 1, "nested_entries": 0}},
                                   "html_sha256": sha256(html)}), encoding="utf-8")
    assert finalize(sidecar) == 1
    assert finalize(sidecar) == 0
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert record["html_sha256"] == sha256(html)
    assert record["event_selection"]["retained"] == 1
    assert record['function_trace']['matched_returns'] == 3
    assert record['observations']['report_function_returns'] == data['meta']['function_returns']
    assert smoke_report(html)["dict"]["funcs"][0].endswith("CowBackend::clone_map")


def test_refresh_assets_preserves_the_embedded_data_block():
    payload = encode({"value": 7})
    page = ("<style>\nold css\n</style>\n"
            f'<script type="application/nodefusion">{payload}</script>\n'
            "<script>\nold js\n</script>\n</body>")
    refreshed, changed = refresh_assets(page)
    assert changed == 2
    assert payload in refreshed
    assert "old css" not in refreshed
    assert "old js" not in refreshed
    assert (Path(__file__).resolve().parents[1] / "host/assets/app.js").read_text() in refreshed


def test_finalize_comparison_preserves_runs_and_updates_hash(tmp_path):
    html = tmp_path / "comparison.html"
    blocks = ''.join(f'<script type="application/nodefusion">{encode({"run": n})}</script>'
                     for n in (1, 2))
    html.write_text('<!DOCTYPE html><title>Comparison</title>' + blocks)
    record = {"format": "nodefusion.comparison-evidence/1", "html": html.name,
              "html_sha256": sha256(html), "runs": [{"run": "first"}, {"run": "second"}]}
    sidecar = tmp_path / "comparison.json"
    sidecar.write_text(json.dumps(record))
    assert finalize_comparison(sidecar)
    updated = json.loads(sidecar.read_text())
    assert updated["runs"] == record["runs"]
    assert updated["html_sha256"] == sha256(html)
    assert updated["html_bytes"] == html.stat().st_size
    assert blocks in html.read_text().replace('\n', '')
    assert not finalize_comparison(sidecar)
    html.write_text(html.read_text() + 'tampered')
    with pytest.raises(ValueError, match="HTML hash differs"):
        finalize_comparison(sidecar)


def test_refresh_shell_preserves_title_and_all_embedded_runs():
    from nodefusion.host.render import _PAGE

    first = f'<script type="application/nodefusion" data-name="first">{encode({"run": 1})}</script>'
    second = f'<script type="application/nodefusion" data-name="second">{encode({"run": 2})}</script>'
    page = (_PAGE.replace("__TITLE__", "NodeFusion · A &amp; B")
            .replace("__CSS__", "old css")
            .replace("__JS__", "old js")
            .replace("__DATA__", first + "\n" + second))
    refreshed, changed = refresh_shell(page)
    assert changed == 1
    assert "<title>NodeFusion · A &amp; B</title>" in refreshed
    assert first in refreshed and second in refreshed
    assert "old css" not in refreshed and "old js" not in refreshed
    assert refresh_shell(refreshed) == (refreshed, 0)


@pytest.mark.parametrize("evidence,html", report_sidecars())
def test_regenerated_artifact_matches_evidence(evidence, html):
    record = record_from(evidence)
    assert len(record["kernel_elf_sha256"]) == 64
    expected_inputs = {
        "trace.nfb", "manifest.json", "watchlist.json", "kernel_layout.json"
    }
    if 'source.snapshot.zlib' in record['source_sha256']:
        expected_inputs.add('source.snapshot.zlib')
        assert record['source_view']['snapshot_sha256'] == record['source_sha256']['source.snapshot.zlib']
    assert set(record["source_sha256"]) == expected_inputs
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
