
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from nodefusion.model.exec import Executor, Walk
from nodefusion.model.plan import (Op, _peel_to_fields,
                                   _percpu_runtime_layout, _walk_fields)
from nodefusion.model.rt import DictMemory, ReadCtx

REPO = Path(__file__).resolve().parents[2]
STARRY = REPO / "nodefusion" / "kernels" / "builds" / "starry-1f85a279.elf"

MEASURED = {
    "INSTALLED_LAYOUT": 0xFFFFFFFF80D95F08,
    "__PERCPU_IDLE_TASK": 0xFFFFFFFF80D31290,
    "__PERCPU_RUN_QUEUE": 0xFFFFFFFF80D312B8,
    "template_base": 0xFFFFFFFF80D31140,
    "runtime_base": 0xFFFFFFE081002000,
    "area_stride": 0x41000,
    "area_count": 1,
    "run_queue_cpu0": 0xFFFFFFE081002178,
}


@pytest.fixture(scope="module")
def dw():
    if not STARRY.is_file():
        pytest.skip(f"这台机器上没有 {STARRY.name}")
    from nodefusion.model.dwarfsrc import DwarfSource
    src = DwarfSource(str(STARRY))
    yield src
    src.close()



def test_peeling_stops_at_the_layer_that_has_the_fields(dw):
    v = dw.var("ax_percpu::layout::INSTALLED_LAYOUT")
    assert v is not None, "DWARF 里没有 INSTALLED_LAYOUT"
    inner, delta = _peel_to_fields(dw, v.type_off,
                                   ("region", "template_base"))
    assert inner is not None, "剥不到有 region 的那层"
    st = dw.struct_at(inner)
    assert "region" in st.fields and "template_base" in st.fields
    assert delta == 0, f"这份构建里壳的总偏移是 {delta}，不是 0"


def test_peeling_gives_up_instead_of_picking_a_field_at_random(dw):
    v = dw.var("ax_percpu::layout::INSTALLED_LAYOUT")
    assert v is not None, "DWARF 里没有 INSTALLED_LAYOUT"
    inner, _ = _peel_to_fields(dw, v.type_off, ("region", "template_base"))
    region, _ = _walk_fields(dw, inner, ("region",))
    assert region is not None
    assert "PerCpuRegion" in (dw.type_name(region) or "")
    assert _peel_to_fields(dw, region, ("region",)) == (None, 0)



def test_the_runtime_route_hands_back_addresses_not_constants(dw):
    args, tpl, why = _percpu_runtime_layout(
        dw, "ax_task::run_queue::IDLE_TASK",
        "ax_percpu::layout::INSTALLED_LAYOUT")
    assert args is not None, why
    for k in ("base_at", "stride_at", "count_at", "template_base_at"):
        assert k in args, f"少了 {k}"
    assert "base" not in args and "stride" not in args and "ncpu" not in args, \
        "运行期那条路不该出现编译期常量，混在一起会让人以为算过了"
    assert args["template"] == MEASURED["__PERCPU_IDLE_TASK"]
    assert tpl is not None, "得把模板变量的类型带回来，不然后面 unwrap 对不上"
    assert "MaybeUninit" in (dw.type_name(tpl) or "")


def test_a_missing_layout_symbol_says_so_instead_of_falling_back(dw):
    args, tpl, why = _percpu_runtime_layout(
        dw, "ax_task::run_queue::IDLE_TASK", "根本::没有::这个量")
    assert args is None and tpl is None
    assert "根本::没有::这个量" in why


def test_a_layout_without_the_expected_fields_is_refused(dw):
    args, _, why = _percpu_runtime_layout(
        dw, "ax_task::run_queue::IDLE_TASK",
        "ax_task::run_queue::RUN_QUEUES")
    assert args is None
    assert "region" in why or "查不到" in why or "剥不到" in why, why


def test_the_arithmetic_reproduces_a_number_it_never_touched(dw):
    args, _, why = _percpu_runtime_layout(
        dw, "ax_task::run_queue::RUN_QUEUE",
        "ax_percpu::layout::INSTALLED_LAYOUT")
    assert args is not None, why
    got = (MEASURED["runtime_base"]
           + (args["template"] - MEASURED["template_base"]))
    assert got == MEASURED["run_queue_cpu0"], (
        f"算出来 {got:#x}，BSS 里存的是 "
        f"{MEASURED['run_queue_cpu0']:#x}")



_LAY = 0x8000
_BASE_AT, _STRIDE_AT, _COUNT_AT, _TBASE_AT = _LAY, _LAY + 8, _LAY + 16, _LAY + 24

_ARGS = {"base_at": _BASE_AT, "stride_at": _STRIDE_AT, "count_at": _COUNT_AT,
         "template_base_at": _TBASE_AT, "template": 0x9150,
         "name": "IDLE_TASK", "how": "测试"}


def _layout_mem(base: int, stride: int, count: int, tbase: int) -> DictMemory:
    return DictMemory().write(_LAY, struct.pack("<QQI", base, stride, count)
                              + b"\xff\xff\xff\xff"
                              + struct.pack("<Q", tbase))


def _run(mem: DictMemory) -> Walk:
    w = Walk()
    ex = Executor(mem, ReadCtx())
    w.nodes = ex._apply(Op("percpu", _ARGS), [], w)
    return w


def test_the_count_comes_from_memory_not_from_dividing_the_region():
    w = _run(_layout_mem(0xFFFF_FFE0_8100_2000, 0x41000, 1, 0x9000))
    assert len(w.nodes) == 1, [hex(n.addr) for n in w.nodes]
    assert w.nodes[0].addr == 0xFFFF_FFE0_8100_2000 + (0x9150 - 0x9000)


def test_more_cpus_means_more_nodes_one_stride_apart():
    w = _run(_layout_mem(0x1_0000, 0x1000, 3, 0x9000))
    assert [n.addr for n in w.nodes] == [0x10150, 0x11150, 0x12150]


def test_an_uninstalled_layout_is_absent_not_broken():
    w = _run(_layout_mem(0, 0, 0, 0))
    assert w.nodes == []
    assert len(w.problems) == 1
    msg = str(w.problems[0])
    assert "还没排布局" in msg and "IDLE_TASK" in msg


def test_a_layout_that_cannot_be_read_names_which_number_was_missing():
    w = _run(DictMemory())
    assert w.nodes == []
    msg = str(w.problems[0])
    assert "读越界" in msg
    for want in ("基址", "步长", "CPU 个数", "模板基址"):
        assert want in msg, f"{want} 没提到：{msg}"


def test_the_link_script_route_still_takes_compile_time_constants():
    w = Walk()
    ex = Executor(DictMemory(), ReadCtx())
    w.nodes = ex._apply(Op("percpu", {"base": 0x2_0000, "stride": 0x100,
                                      "ncpu": 2, "off": 0xA0,
                                      "name": "RUN_QUEUE"}), [], w)
    assert [n.addr for n in w.nodes] == [0x200A0, 0x201A0]
    assert w.problems == [], "常量那条路不该碰内存"
