
from __future__ import annotations

import pathlib
from pathlib import Path

import pytest

from nodefusion.host.analyze import FUNC_EVENTS, event_shape

_ROOT = Path(__file__).resolve().parent.parent.parent
def _archived(kind: str):
    from nodefusion.host.kernels import archived_elf
    p = archived_elf(kind)
    return p if p is not None else pathlib.Path(f"/nonexistent/{kind}.elf")
_XV6 = _archived("xv6")

needs_xv6 = pytest.mark.skipif(
    not _XV6.exists(),
    reason=f"要 xv6 teacher 内核 ELF（{_XV6}），是 build 产物，没有就跳过")



def test_the_hand_written_names_win_where_it_has_them():
    kind, res, args = event_shape("panic", {"params": ["s"]},
                                  kernel_kind="xv6")
    assert kind == "kernel.panic"
    assert args == ["msg"]


def test_dwarf_fills_in_where_the_table_says_nothing():
    kind, res, args = event_shape(
        "sys_write", {"resource": "file", "params": ["fd", "buf", "len"]},
        kernel_kind="rcore")
    assert kind == "func.sys_write"
    assert res == "file"
    assert args == ["fd", "buf", "len"]


def test_a_table_entry_with_no_arg_names_still_gets_dwarf_names():
    _, _, args = event_shape("kspawn", {"params": ["path"]},
                             kernel_kind="xv6")
    assert args == ["path"]
    _, _, none = event_shape("kfork", {"params": []}, kernel_kind="xv6")
    assert none == []


def test_an_old_bundle_without_params_behaves_exactly_as_before():
    assert event_shape("kalloc", {}, kernel_kind="xv6")[2] == []
    assert event_shape("nope", {"resource": "vm"}, kernel_kind="xv6") == (
        "func.nope", "vm", [])


def test_a_nameless_parameter_holds_its_slot():
    _, _, args = event_shape("whatever", {"params": [None, "len"]},
                             kernel_kind="rcore")
    assert args == [None, "len"], "占位没了的话 len 会被安到第 0 个寄存器上"



@needs_xv6
def test_dwarf_parameter_order_matches_the_hand_written_table():
    from nodefusion.model.dwarfsrc import DwarfSource
    dw = DwarfSource(str(_XV6))
    by_name: dict[str, list] = {}
    for f in dw.functions:
        by_name.setdefault(f.name, f.params)

    swapped = []
    for name, (_k, _r, hand) in FUNC_EVENTS.items():
        got = by_name.get(name)
        if got is None or not hand:
            continue
        for i, h in enumerate(hand):
            if i < len(got) and got[i] != h and h in got:
                swapped.append(f"{name}: 手写第 {i} 位是 {h!r}，"
                               f"DWARF 里它在第 {got.index(h)} 位")
    assert not swapped, "\n".join(swapped)


@needs_xv6
def test_the_functions_only_the_rules_watch_get_names_too():
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist

    wl, _, _ = select_watchlist(Elf64(_XV6), _XV6, kind="xv6")
    by = {e.name: e for e in wl.entries}
    for name, want in [("walk", ["pagetable", "va", "alloc"]),
                       ("namex", ["path", "nameiparent", "name"]),
                       ("either_copyout", ["user_dst", "dst", "src", "len"])]:
        assert name in by, f"{name} 不在规则选出来的点里"
        assert name not in FUNC_EVENTS, f"{name} 进手写表了，这条测试就没意义了"
        assert by[name].params == want, name
