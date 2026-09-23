from pathlib import Path
from types import SimpleNamespace

from nodefusion.host.record import (Recorder, RunConfig, _calibration_watchlist,
                                    _program_start_from_trace,
                                    _snapshot_focus_start)
from nodefusion.host.watchlist import NFTRACE_COMMIT, WatchEntry, WatchList


def _command(cpus, *, function_returns=False, calibrating=False):
    recorder = Recorder.__new__(Recorder)
    recorder.cfg = RunConfig(Path("/kernel"), "program", "test", Path("/runs"),
                             cpus=cpus, function_returns=function_returns)
    recorder.sh = SimpleNamespace(path=str)
    recorder.plugin_so = Path("/plugin/libnf.so")
    recorder.profile = SimpleNamespace(
        ram_bytes=lambda: (128 * 1048576, ""),
        event_snapshot_min_insns=0,
        machine_args=lambda kernel_dir: ["-M virt"])
    recorder.warnings = []
    recorder._calibrating = calibrating
    return recorder._qemu_cmd(Path("/runs/trace.nfb"), None, 1000, 12345)


def test_single_vcpu_keeps_deterministic_icount():
    assert "-icount shift=3" in _command(1)


def test_smp_omits_incompatible_icount():
    command = _command(2)
    assert "-smp 2" in command
    assert "-icount" not in command


def test_return_capture_is_opt_in():
    assert "returns=0" in _command(1)
    assert "returns=1" in _command(1, function_returns=True)
    assert "returns=0" in _command(1, function_returns=True, calibrating=True)


def test_headless_first_scheduler_switch_marks_app_start():
    idle = (1 << 64) - 1
    trace = SimpleNamespace(watch_hits=[], nftrace=[
        SimpleNamespace(insn=10, type=4, a=(3, idle)),
        SimpleNamespace(insn=40, type=4, a=(idle, 0)),
        SimpleNamespace(insn=80, type=4, a=(0, 1)),
    ])
    assert _program_start_from_trace(trace, {"entries": []}, interactive=False) == 40
    assert _program_start_from_trace(trace, {"entries": []}, interactive=True) == 0


def test_exec_entry_keeps_priority_over_scheduler_fallback():
    trace = SimpleNamespace(
        watch_hits=[SimpleNamespace(watch_id=2, insn=60)],
        nftrace=[SimpleNamespace(insn=40, type=4, a=((1 << 64) - 1, 0))])
    assert _program_start_from_trace(trace, {
        "entries": [{"index": 2, "kind": "proc.exec"}]}, interactive=False) == 60


def test_interactive_execs_do_not_pretend_to_mark_a_compound_workload():
    trace = SimpleNamespace(watch_hits=[
        SimpleNamespace(watch_id=2, insn=30),
        SimpleNamespace(watch_id=2, insn=300)], nftrace=[])
    assert _program_start_from_trace(trace, {
        "entries": [{"index": 2, "kind": "proc.exec"}]}, interactive=True) == 0


def test_interactive_snapshot_density_does_not_claim_a_program_boundary():
    assert _snapshot_focus_start(0, 1_000_000, interactive=True) == 850_000
    assert _snapshot_focus_start(0, 1_000_000, interactive=False) == 0
    assert _snapshot_focus_start(123, 1_000_000, interactive=True) == 123


def test_headless_first_task_entry_when_no_semantic_scheduler():
    trace = SimpleNamespace(
        watch_hits=[SimpleNamespace(watch_id=3, insn=25)], nftrace=[])
    assert _program_start_from_trace(trace, {"entries": [
        {"index": 3, "symbol": "os::task::run_first_task"}]},
        interactive=False) == 25


def test_headless_switch_entry_follows_lazy_task_manager_init():
    trace = SimpleNamespace(watch_hits=[
        SimpleNamespace(watch_id=3, insn=25),
        SimpleNamespace(watch_id=4, insn=45)], nftrace=[])
    assert _program_start_from_trace(trace, {"entries": [
        {"index": 3, "symbol": "os::task::run_first_task"},
        {"index": 4, "kind": "sched.switch"}]}, interactive=False) == 45


def test_calibration_omits_bulk_function_watches_but_keeps_boundary_ids():
    def entry(index, name, *, kind=""):
        return WatchEntry(index, name, f"os::{name}", 0x1000 + index * 4,
                          "task", False, kind=kind)

    full = WatchList([
        entry(0, "hot_function"), entry(1, "exec", kind="proc.exec"),
        entry(2, NFTRACE_COMMIT), entry(3, "__switch", kind="sched.switch"),
        entry(4, "run_first_task"), entry(5, "another_hot_function"),
    ], [], 2)
    small = _calibration_watchlist(full)
    assert [e.index for e in small.entries] == [0, 1, 2, 3]
    assert [e.name for e in small.entries] == [
        "exec", NFTRACE_COMMIT, "__switch", "run_first_task"]
    assert small.nftrace_index == 1
    assert "hot_function" not in small.to_file_text()
