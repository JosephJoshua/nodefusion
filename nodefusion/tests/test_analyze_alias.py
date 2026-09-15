
from __future__ import annotations

import pathlib
from pathlib import Path

import pytest

from nodefusion.host.analyze import FUNC_EVENTS
from nodefusion.host.nfelf import Elf64
from nodefusion.host.record import select_watchlist

_ROOT = Path(__file__).resolve().parent.parent.parent
def _archived(kind: str):
    from nodefusion.host.kernels import archived_elf
    p = archived_elf(kind)
    return p if p is not None else pathlib.Path(f"/nonexistent/{kind}.elf")
_XV6 = _archived("xv6")

needs_xv6 = pytest.mark.skipif(
    not _XV6.exists(),
    reason=f"要 xv6 teacher 内核 ELF（{_XV6}），是 build 产物，没有就跳过")


def _by_addr(wl):
    return {e.addr: e for e in wl.entries}


@needs_xv6
def test_the_two_ways_of_picking_agree_on_what_every_shared_point_means():
    elf = Elf64(_XV6)
    table, _, _ = select_watchlist(elf, _XV6, kind="xv6", prefer_table=True)
    rules, _, _ = select_watchlist(elf, _XV6, kind="xv6")

    t, r = _by_addr(table), _by_addr(rules)
    disagree = []
    for addr in sorted(t.keys() & r.keys()):
        a, b = FUNC_EVENTS.get(t[addr].name), FUNC_EVENTS.get(r[addr].name)
        if a != b:
            disagree.append(
                f"{addr:#x}: 名单叫 {t[addr].name!r}->{a}，"
                f"规则叫 {r[addr].name!r}->{b}")
    assert not disagree, "\n".join(disagree)


@needs_xv6
def test_the_course_tree_spellings_are_the_ones_the_rules_actually_pick():
    elf = Elf64(_XV6)
    rules, _, _ = select_watchlist(elf, _XV6, kind="xv6")
    picked = {e.name for e in rules.entries}

    for spelling in ["kfork", "kexit", "kwait", "kexec", "prepare_return"]:
        assert spelling in picked, f"{spelling} 不在规则选出来的点里了"
        assert spelling in FUNC_EVENTS, f"{spelling} 没有语义映射"


def test_an_alias_carries_the_whole_meaning_not_just_the_name():
    for alias, real in [("kfork", "fork"), ("kexit", "exit"),
                        ("kwait", "wait"), ("kkill", "kill"),
                        ("kspawn", "spawn"), ("kexec", "exec"),
                        ("prepare_return", "usertrapret")]:
        assert FUNC_EVENTS[alias] == FUNC_EVENTS[real], alias
