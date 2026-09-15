"""Large-output paths must not consume the last bytes or leave partial artifacts."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from nodefusion.host import analyze as A
from nodefusion.host import cli as C
from nodefusion.host import render as R


def _analysis(tmp_path, events):
    a = object.__new__(A.Analysis)
    a.run_dir = tmp_path
    a.manifest = {"run_name": "tiny", "program": "probe", "outcome": "completed"}
    a.kernel_elf_path = tmp_path / "kernel.elf"
    a.trace = NS(total_insns=99, meta={})
    a.ncpu = 1
    a.states = []
    a.notes = []
    a.events = list(events)
    return a


def test_small_event_stream_estimate_is_exact(tmp_path):
    events = [A.Event(insn=i, cpu=0, kind="proc.fork", resource="task")
              for i in range(3)]
    a = _analysis(tmp_path, events)
    out = tmp_path / "events.jsonl"
    estimate = a.estimate_event_stream_bytes()
    a.write_event_stream(out)
    assert estimate == out.stat().st_size
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["type"] == "meta"


def test_failed_event_stream_keeps_previous_file_and_removes_temporary(tmp_path):
    class Broken:
        def to_json(self):
            raise OSError("simulated full disk")

    a = _analysis(tmp_path, [Broken()])
    out = tmp_path / "events.jsonl"
    out.write_text("previous\n", encoding="utf-8")
    with pytest.raises(OSError, match="simulated full disk"):
        a.write_event_stream(out)
    assert out.read_text(encoding="utf-8") == "previous\n"
    assert not list(tmp_path.glob(".events.jsonl.tmp-*"))


def test_auto_mode_skips_an_oversized_event_stream(tmp_path, monkeypatch, capsys):
    fake = NS(run_dir=tmp_path, estimate_event_stream_bytes=lambda: 300 * 1024 * 1024)
    fake.write_event_stream = lambda path: pytest.fail("oversized auto export was written")
    monkeypatch.setattr(C.shutil, "disk_usage", lambda path: NS(free=10**12))
    C._write_event_stream(fake, "auto")
    assert "自动跳过" in capsys.readouterr().out


def test_forced_event_stream_refuses_to_consume_disk_reserve(tmp_path, monkeypatch):
    fake = NS(run_dir=tmp_path, estimate_event_stream_bytes=lambda: 1000)
    fake.write_event_stream = lambda path: pytest.fail("unsafe export was written")
    monkeypatch.setattr(C.shutil, "disk_usage", lambda path: NS(free=1000))
    with pytest.raises(SystemExit, match="拒绝写 events.jsonl"):
        C._write_event_stream(fake, "always")


def test_cli_exposes_safe_export_modes_and_machine_audit():
    parser = C.build_parser()
    assert parser.parse_args(["render", "--run", "x"]).event_stream == "auto"
    assert parser.parse_args(["render", "--run", "x", "--no-event-stream"]).event_stream == "never"
    assert parser.parse_args(["audit", "--run", "x", "--json"]).json is True


def test_render_replace_failure_keeps_previous_html(tmp_path, monkeypatch):
    out = tmp_path / "report.html"
    out.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(R.bundle_mod, "build", lambda analysis: {"meta": {"run": "x"}})
    monkeypatch.setattr(R.bundle_mod, "encode", lambda bundle: "encoded")
    original_replace = R.Path.replace

    def fail_only_for_report(path, target):
        if target == out:
            raise OSError("simulated rename failure")
        return original_replace(path, target)

    monkeypatch.setattr(R.Path, "replace", fail_only_for_report)
    analysis = NS(manifest={"run_name": "x"})
    with pytest.raises(OSError, match="simulated rename failure"):
        R.render([analysis], out)
    assert out.read_text(encoding="utf-8") == "previous"
    assert not list(tmp_path.glob(".report.html.tmp-*"))


def test_machine_audit_exit_status_and_json(monkeypatch, capsys):
    fake = NS(manifest={"run_name": "x"}, run_dir="unused")
    monkeypatch.setattr(C, "_load", lambda *args, **kwargs: [fake])
    monkeypatch.setattr(C.bundle_mod, "coverage", lambda analysis: {
        "status": "complete", "percent": 100.0,
        "metrics": {"covered": 3, "applicable": 3}, "blockers": [],
    })
    assert C.cmd_audit(NS(run=["x"], runs=".", json=True)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "nodefusion.coverage-audit/1"
    assert report["complete"] is True

    monkeypatch.setattr(C.bundle_mod, "coverage", lambda analysis: {
        "status": "incomplete", "percent": 50.0,
        "metrics": {"covered": 1, "applicable": 2},
        "blockers": [{"check": "metrics", "items": ["forks"]}],
    })
    assert C.cmd_audit(NS(run=["x"], runs=".", json=True)) == 1
