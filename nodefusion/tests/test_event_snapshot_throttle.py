
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import analyze as A
from nodefusion.host.kernels import KernelProfile
from nodefusion.model.manifest import load

REPO = Path(__file__).resolve().parents[2]
MANI = REPO / "nodefusion" / "manifests"
RUNS = Path(__file__).resolve().parents[1] / "runs"
ARCEOS = MANI / "arceos.toml"



def test_the_manifest_can_set_the_event_snapshot_gap():
    p = load(ARCEOS).profile
    assert p is not None and p.event_snapshot_min_insns > 0


def test_it_carries_into_the_profile_the_recorder_actually_uses():
    spec = load(ARCEOS).profile
    k = KernelProfile.from_spec("arceos", spec)
    assert k.event_snapshot_min_insns == spec.event_snapshot_min_insns


def test_the_default_is_zero_so_other_kernels_keep_the_plugin_default():
    for f in sorted((MANI).glob("*.toml")):
        p = load(f).profile
        if p is None or f.name == "arceos.toml":
            continue
        assert p.event_snapshot_min_insns == 0, f.name


def test_the_gap_is_narrower_than_the_phase_it_has_to_resolve():
    phase = 67_511_354 - 67_497_711
    assert load(ARCEOS).profile.event_snapshot_min_insns < phase


_TASK_EVENTS = [67_497_711, 67_498_926, 67_499_614,
                67_505_429, 67_510_025, 67_511_354]


def test_the_gap_clears_the_measured_minimum_between_two_task_events():
    gaps = [b - a for a, b in zip(_TASK_EVENTS, _TASK_EVENTS[1:])]
    assert min(gaps) == 688, gaps
    assert load(ARCEOS).profile.event_snapshot_min_insns < min(gaps)



def _run(name: str):
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    return A.analyze(d)


def _procs(a) -> int:
    return sum(len(s.procs) for s in a.states)


@pytest.mark.corpus
def test_the_old_recording_saw_no_tasks_and_the_new_one_does():
    assert _procs(_run("arceos-childtask")) == 0
    assert _procs(_run("arceos-childtask-evsnap")) > 0


@pytest.mark.corpus
def test_the_new_frames_land_inside_the_multitask_phase():
    a = _run("arceos-childtask-evsnap")
    inside = [s.insn for s in a.states if 67_497_711 <= s.insn <= 67_511_354]
    assert len(inside) >= 2, [s.insn for s in a.states]


@pytest.mark.corpus
def test_the_tail_note_stops_firing_once_the_tail_is_covered():
    old = [n for n in _run("arceos-childtask").notes if "不等于内核里没有" in n]
    new = [n for n in _run("arceos-childtask-evsnap").notes
           if "不等于内核里没有" in n]
    assert len(old) == 1 and new == []


@pytest.mark.corpus
def test_the_new_recording_finished_properly():
    d = RUNS / "arceos-childtask-evsnap"
    if not (d / "qemu.log").is_file():
        pytest.skip("这台机器上没有这趟")
    log = (d / "qemu.log").read_text()
    assert "结束：指令" in log, log[-400:]
    assert "assertion failed" not in log
