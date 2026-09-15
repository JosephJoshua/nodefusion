
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.corpus

from functools import lru_cache
from typing import NamedTuple

from nodefusion.host import analyze as A

RUNS = Path(__file__).resolve().parents[1] / "runs"


def _skip_if_missing(name: str) -> Path:
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    return d


from conftest import shapes as _shapes  # noqa: E402


def _notes(name: str) -> list[str]:
    return _shapes(name).notes


def _one(notes: list[str], needle: str) -> str:
    hit = [n for n in notes if needle in n]
    assert len(hit) == 1, f"{needle!r} 命中 {len(hit)} 条：{notes}"
    return hit[0]



@pytest.mark.parametrize("name", ["arceos-childtask", "rcore-ch6-fs"])
def test_a_kernel_whose_process_table_decoded_is_not_told_otherwise(name):
    assert not any("进程表解不出来" in n for n in _notes(name))


@pytest.mark.parametrize("name", ["arceos-childtask", "rcore-ch6-fs"])
def test_no_note_promises_a_reason_and_then_stops(name):
    for n in _notes(name):
        assert not n.rstrip().endswith(("：", ":")), n


@pytest.mark.parametrize("name", ["arceos-childtask", "rcore-ch6-fs"])
def test_the_note_is_gone(name):
    notes = _notes(name)
    assert not any("上下文切换事件无法归属" in n for n in notes), notes


_RUNS_WITH_TASKS = ["arceos-ctxsnap500", "rcore-ch6-fs", "lab3-cowtest-mac"]


@pytest.mark.parametrize("name", _RUNS_WITH_TASKS)
def test_every_decoded_task_carries_its_context_address(name):
    ctxs = _shapes(name).sched_ctxs
    assert ctxs, "一个任务都没解出来，这条测试没验证到东西"
    assert all(c for c in ctxs), f"有任务没拿到上下文地址：{set(ctxs)}"


def test_xv6_still_builds_the_reverse_map_and_says_nothing():
    assert not any("上下文切换事件无法归属" in n
                   for n in _notes("lab3-cowtest-mac"))



def test_a_higher_half_kernel_is_not_told_its_statics_are_unreadable():
    n = _one(_notes("arceos-childtask"), "不是直接映射的")
    assert "读不出来" not in n


def test_it_says_the_offset_is_applied_when_reading_statics():
    n = _one(_notes("arceos-childtask"), "不是直接映射的")
    assert "按这个差换算" in n


def test_it_says_page_table_walking_stays_physical():
    n = _one(_notes("arceos-childtask"), "不是直接映射的")
    assert "satp" in n and "物理地址" in n


def test_it_still_states_the_elf_pairs():
    n = _one(_notes("arceos-childtask"), "不是直接映射的")
    assert "录这趟用的构建" in n


def test_a_direct_mapped_kernel_gets_no_mapping_note_at_all():
    assert not any("不是直接映射的" in n for n in _notes("lab3-cowtest-mac"))
