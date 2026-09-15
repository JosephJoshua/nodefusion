
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodefusion.host.record import (_PLUGIN_FINISHED, _PLUGIN_MOUNTED,
                                    _trace_incomplete)

REPO = Path(__file__).resolve().parents[2]
RUNS = Path(__file__).resolve().parents[1] / "runs"

_REAL_ABORT = (
    "[nodefusion-plugin] 已挂载：out=/tmp/trace.nfb sample=100000 …\n"
    "**\n"
    "ERROR:../plugins/api.c:506:qemu_plugin_read_memory_hwaddr: "
    "assertion failed: (current_cpu)\n"
    "Bail out! ERROR:../plugins/api.c:506:qemu_plugin_read_memory_hwaddr: "
    "assertion failed: (current_cpu)\n")



def test_a_finished_recording_reports_nothing():
    err = f"{_PLUGIN_MOUNTED}out=x\n{_PLUGIN_FINISHED}指令 123，快照 4 次\n"
    assert _trace_incomplete(err) is None


def test_the_plugin_never_loading_is_called_out_as_such():
    why = _trace_incomplete("qemu-system-riscv64: -plugin: 打不开这个文件\n")
    assert why is not None
    assert "挂载" in why


def test_dying_midway_is_distinguished_from_never_starting():
    why = _trace_incomplete(_REAL_ABORT)
    assert why is not None
    assert "收尾" in why
    assert "挂载" not in why.split("QEMU stderr")[0], (
        "挂上了却没收尾，不该说成没挂上：" + why)


def test_the_assertion_line_survives_into_the_reason():
    why = _trace_incomplete(_REAL_ABORT)
    assert "qemu_plugin_read_memory_hwaddr" in why
    assert "current_cpu" in why


def test_an_empty_stderr_is_incomplete_not_fine():
    assert _trace_incomplete("") is not None


def test_the_finish_line_wins_even_when_something_else_screamed():
    err = (f"{_PLUGIN_MOUNTED}out=x\n"
           "qemu-system-riscv64: warning: 某个无关紧要的警告\n"
           f"{_PLUGIN_FINISHED}指令 999\n")
    assert _trace_incomplete(err) is None



def test_the_markers_are_the_strings_the_plugin_actually_prints():
    c = (REPO / "nodefusion/plugin/nf_plugin.c").read_text(encoding="utf-8")
    assert _PLUGIN_MOUNTED in c, f"nf_plugin.c 里找不到 {_PLUGIN_MOUNTED!r}"
    assert _PLUGIN_FINISHED in c, f"nf_plugin.c 里找不到 {_PLUGIN_FINISHED!r}"


def test_the_finish_line_is_printed_after_the_file_is_closed():
    c = (REPO / "nodefusion/plugin/nf_plugin.c").read_text(encoding="utf-8")
    assert c.index("fclose(nf.out)") < c.index(_PLUGIN_FINISHED), (
        "nf_finish 里收尾行跑到 fclose 前面去了，这行就不再能证明轨迹写完了")



def _runs():
    return [d for d in sorted(RUNS.iterdir())
            if (d / "qemu.log").is_file() and not d.name.startswith("_")]


def test_there_is_at_least_one_run_to_check():
    if not RUNS.is_dir():
        pytest.skip("这台机器上没有 runs 目录")
    assert _runs(), "runs 下一个带 qemu.log 的目录都没有"


def test_every_recorded_run_actually_finished():
    if not RUNS.is_dir():
        pytest.skip("这台机器上没有 runs 目录")
    bad = {d.name: why for d in _runs()
           if (why := _trace_incomplete(
               (d / "qemu.log").read_text(encoding="utf-8", errors="replace")))}
    assert not bad, bad


def test_new_runs_record_the_verdict_in_their_manifest():
    if not RUNS.is_dir():
        pytest.skip("这台机器上没有 runs 目录")
    checked = 0
    for d in _runs():
        mf = d / "manifest.json"
        if not mf.is_file():
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        if "trace_complete" not in m:
            continue
        checked += 1
        assert m["trace_complete"] is True, (d.name, m.get("trace_incomplete_reason"))
        assert m.get("trace_incomplete_reason") is None, d.name
    if not checked:
        pytest.skip("现有的 run 都是加这个键之前录的")



def _a_run_with(tmp_path: Path, **overrides):
    from nodefusion.host import analyze as A

    src = RUNS / "arceos-childtask-evsnap"
    if not (src / "trace.nfb").is_file():
        pytest.skip("这台机器上没有 arceos-childtask-evsnap")

    import shutil
    d = tmp_path / src.name
    shutil.copytree(src, d)
    mf = d / "manifest.json"
    m = json.loads(mf.read_text(encoding="utf-8"))
    m.update(overrides)
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return A.analyze(d)


@pytest.mark.corpus
def test_an_incomplete_trace_says_so_in_the_report(tmp_path):
    a = _a_run_with(tmp_path, trace_complete=False,
                    trace_incomplete_reason="插件挂上了却没打出收尾行")
    hit = [n for n in a.notes if "没有正常收尾" in n]
    assert hit, a.notes
    assert "插件挂上了却没打出收尾行" in hit[0], "原因被吞了：" + hit[0]


@pytest.mark.corpus
def test_a_complete_trace_stays_quiet(tmp_path):
    a = _a_run_with(tmp_path, trace_complete=True,
                    trace_incomplete_reason=None)
    assert not [n for n in a.notes if "没有正常收尾" in n], a.notes


@pytest.mark.corpus
def test_an_old_run_without_the_key_is_unknown_not_broken(tmp_path):
    from nodefusion.host import analyze as A

    src = RUNS / "arceos-childtask-evsnap"
    if not (src / "trace.nfb").is_file():
        pytest.skip("这台机器上没有 arceos-childtask-evsnap")
    import shutil
    d = tmp_path / src.name
    shutil.copytree(src, d)
    mf = d / "manifest.json"
    m = json.loads(mf.read_text(encoding="utf-8"))
    m.pop("trace_complete", None)
    m.pop("trace_incomplete_reason", None)
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    a = A.analyze(d)
    assert not [n for n in a.notes if "没有正常收尾" in n], a.notes
