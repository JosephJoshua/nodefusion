
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import analyze as A


class _State:
    def __init__(self, insn: int, procs=()) -> None:
        self.insn, self.procs = insn, list(procs)


def _ev(insn: int, kind: str) -> A.Event:
    return A.Event(insn=insn, cpu=0, kind=kind, resource="任意")


def _notes(states, events) -> list[str]:
    a = object.__new__(A.Analysis)
    a.states, a.events, a.notes = list(states), list(events), []
    a._note_recording_tail()
    return a.notes


LATE = [_ev(150, "proc.create"), _ev(160, "sched.switch"), _ev(170, "proc.exit")]



def test_it_speaks_up_when_the_only_task_events_are_past_the_last_frame():
    assert _notes([_State(100)], [_ev(50, "syscall.enter"), *LATE])


def test_it_gives_both_numbers():
    n = _notes([_State(100)], [*LATE])[0]
    assert "100" in n and "170" in n


def test_it_names_the_events_that_only_appear_there():
    n = _notes([_State(100)], [*LATE])[0]
    assert "proc.create" in n and "sched.switch" in n and "proc.exit" in n


def test_it_does_not_claim_the_kernel_had_none():
    n = _notes([_State(100)], [*LATE])[0]
    assert "不等于内核里没有" in n



def test_it_is_silent_when_processes_did_decode():
    assert _notes([_State(100, procs=[object()])], [*LATE]) == []


def test_it_is_silent_when_nothing_happened_after_the_last_frame():
    assert _notes([_State(100)], [_ev(50, "proc.create")]) == []


def test_it_is_silent_when_the_tail_holds_no_task_events():
    assert _notes([_State(100)], [_ev(150, "sbi.call")]) == []


def test_it_is_silent_when_the_same_kind_also_happened_earlier():
    assert _notes([_State(100)],
                  [_ev(50, "proc.create"), _ev(150, "proc.create")]) == []


def test_an_empty_run_says_nothing():
    assert _notes([], []) == [] and _notes([_State(100)], []) == []



def test_the_criterion_is_the_kind_not_the_resource():
    odd = A.Event(insn=150, cpu=0, kind="proc.create", resource="ax-task")
    assert _notes([_State(100)], [odd])



@pytest.mark.corpus
def test_only_arceos_gets_this_note_among_the_recorded_runs():
    runs = Path(__file__).resolve().parents[1] / "runs"
    if not runs.is_dir():
        pytest.skip("这台机器上没有录好的 run")

    from conftest import corpus_run_dirs, shapes  # noqa: PLC0415

    hit = []
    for d in corpus_run_dirs(runs):
        if any("不等于内核里没有" in n for n in shapes(d.name).notes):
            hit.append(d.name)
    if not hit:
        pytest.skip("这台机器上没有 arceos 的 run")
    assert hit == ["arceos-childtask"], hit
