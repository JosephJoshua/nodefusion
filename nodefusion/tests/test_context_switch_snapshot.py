
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import analyze as A
from nodefusion.model.manifest import load

REPO = Path(__file__).resolve().parents[2]
MANI = REPO / "nodefusion" / "manifests"
RUNS = Path(__file__).resolve().parents[1] / "runs"
ARCEOS = MANI / "arceos.toml"

PHASE = (67_497_711, 67_511_354)
TASK_EVENTS = 6
CHILD_PID = 4
FIRST_EXIT = 67_505_429


# ------------------------------------------------------------------ manifest

def _sched_rule():
    for w in load(ARCEOS).watches:
        m = w.match if isinstance(w.match, dict) else {}
        if m.get("module") == "axcpu" and "context_switch" in (m.get("fn") or []):
            return w
    pytest.fail("arceos.toml 里找不到那条 context_switch 的规则")


def test_the_context_switch_rule_takes_a_frame():
    assert _sched_rule().snapshot == "event"


def test_it_is_still_its_own_rule_so_the_name_does_not_change():
    assert _sched_rule().subsystem == "sched"



def _phase_frames(name: str):
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    a = A.analyze(d)
    return [s for s in a.states if PHASE[0] <= s.insn <= PHASE[1]], a


def _procs(state):
    return [p if isinstance(p, dict) else vars(p) for p in state.procs]


@pytest.mark.corpus
def test_every_task_event_gets_its_own_frame():
    frames, _ = _phase_frames("arceos-ctxsnap500")
    assert len(frames) == TASK_EVENTS, [s.insn for s in frames]


@pytest.mark.corpus
def test_the_child_is_seen_while_it_is_still_alive():
    frames, _ = _phase_frames("arceos-ctxsnap500")
    alive = {p.get("pid") for s in frames if s.insn < FIRST_EXIT
             for p in _procs(s)}
    assert CHILD_PID in alive, f"子任务活着的时候还是没看见：{sorted(alive)}"


@pytest.mark.corpus
def test_the_childs_blank_name_is_empty_not_undecodable():
    frames, _ = _phase_frames("arceos-ctxsnap500")
    child = [p for s in frames for p in _procs(s) if p.get("pid") == CHILD_PID]
    assert child, "一帧都没看见 pid 4"
    for p in child:
        assert p.get("name") == "", p
        assert p.get("pid") == CHILD_PID, f"名字空的同时 pid 也没了，那才是故障：{p}"


@pytest.mark.corpus
def test_the_snapshot_key_alone_would_have_bought_nothing():
    a, _ = _phase_frames("arceos-tracecomplete")
    b, _ = _phase_frames("arceos-ctxsnap")
    assert len(a) == len(b) == 3, (len(a), len(b))


@pytest.mark.corpus
def test_the_two_keys_together_double_the_tasks_observed():
    before, ab = _phase_frames("arceos-tracecomplete")
    after, aa = _phase_frames("arceos-ctxsnap500")
    nb = sum(len(s.procs) for s in ab.states)
    na = sum(len(s.procs) for s in aa.states)
    assert (nb, na) == (6, 12), (nb, na)
