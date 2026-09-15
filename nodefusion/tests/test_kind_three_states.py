
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.corpus

from nodefusion.host import analyze as A

RUNS = Path(__file__).resolve().parents[1] / "runs"

SAMPLES = ["rcore-fs-alloc", "lab3-cowtest-mac", "arceos-childtask"]


from conftest import shapes as _shapes  # noqa: E402


def _metrics(name: str) -> dict:
    return _shapes(name).metrics



@pytest.mark.parametrize("run", SAMPLES)
def test_the_three_states_never_overlap(run):
    m = _metrics(run)
    fired = set(m["by_kind"])
    silent = set(m["armed_silent"])
    absent = set(m["absent_declared"])
    assert not (fired & silent), f"又响又静：{sorted(fired & silent)}"
    assert not (fired & absent), f"又响又声明没有：{sorted(fired & absent)}"
    assert not (silent & absent), (
        f"挂上了又声明没有：{sorted(silent & absent)} —— "
        f"要么规则选中了不该选的函数，要么那条 [absent] 过期了")


@pytest.mark.parametrize("run", SAMPLES)
def test_armed_silent_is_exactly_the_armed_minus_the_fired(run):
    s = _shapes(run)
    m = s.metrics
    assert set(m["armed_silent"]) == s.watched_kinds - set(m["by_kind"])


@pytest.mark.parametrize("run", SAMPLES)
def test_the_field_is_always_there_even_when_empty(run):
    m = _metrics(run)
    assert isinstance(m["armed_silent"], list)
    assert m["armed_silent"] == sorted(m["armed_silent"]), "得排好序，diff 才稳"



def test_rcore_inode_alloc_is_a_measured_zero_not_a_missing_row():
    m = _metrics("rcore-fs-alloc")
    assert "inode.alloc" in m["armed_silent"], (
        f"inode.alloc 不在「挂了没响」里。响了？还是映射没了？"
        f"by_kind 里是 {m['by_kind'].get('inode.alloc')}")


def test_the_same_state_shows_up_on_xv6_for_the_same_kind():
    assert "inode.alloc" in _metrics("lab3-cowtest-mac")["armed_silent"]



@pytest.mark.parametrize("run", SAMPLES)
def test_adding_the_third_state_did_not_move_the_denominator(run):
    m = _metrics(run)
    why = m.get("unobservable_reason") or ""
    if not why:
        pytest.skip(f"{run} 没有理由栏，分母无从查起")
    total = int(re.search(r"本趟 (\d+) 项指标", why).group(1))
    scalar = [k for k, v in m.items()
              if v is None or isinstance(v, (int, float)) and not isinstance(v, bool)]
    assert total == len(scalar), (total, sorted(scalar))
