
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host.analyze import FUNC_EVENTS, event_shape

_ROOT = Path(__file__).resolve().parent.parent.parent
from nodefusion.tests import kernelelf as _ke

_RCORE = _ke.kernel_elf("rcore")
needs_rcore = _ke.needs("rcore")



def test_another_kernels_exec_does_not_get_xv6s_argument_names():
    kind, _res, args = event_shape("exec", {"params": []}, kernel_kind="rcore")
    assert kind == "func.exec"
    assert args == [], "拿到了 xv6 的 ['path','argv']，那两列会是编出来的"


def test_the_kernels_own_dwarf_names_win_over_the_hand_written_table():
    _kind, _res, args = event_shape(
        "panic", {"params": ["info"]}, kernel_kind="rcore")
    assert args == ["info"]


def test_xv6_still_gets_the_table():
    kind, resource, args = event_shape(
        "panic", {"params": ["s"]}, kernel_kind="xv6")
    tab_kind, tab_res, tab_args = FUNC_EVENTS["panic"]
    assert (kind, args) == (tab_kind, tab_args)
    assert resource == (tab_res or "kernel")


def test_an_unknown_kernel_is_treated_as_not_xv6():
    for kind in (None, "", "arceos", "starry", "XV6"):
        got = event_shape("exec", {"params": []}, kernel_kind=kind)
        assert got == ("func.exec", "kernel", []), kind



@needs_rcore
def test_no_watchpoint_in_rcore_takes_its_names_from_the_xv6_table():
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist

    wl, src, _ = select_watchlist(Elf64(str(_RCORE)), _RCORE, kind="rcore")
    assert src == "manifest:rcore"

    borrowed = []
    for e in wl.entries:
        _k, _r, args = event_shape(
            e.name, {"params": e.params}, kernel_kind="rcore")
        if args != list(e.params):
            borrowed.append(
                f"{e.name} @ {e.addr:#x}：DWARF 说 {e.params}，实际用了 {args}")
    assert not borrowed, "\n".join(borrowed)


@needs_rcore
def test_the_collision_this_guards_against_actually_still_happens():
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist

    wl, _, _ = select_watchlist(Elf64(str(_RCORE)), _RCORE, kind="rcore")
    clashing = sorted({e.name for e in wl.entries if e.name in FUNC_EVENTS})
    assert clashing, "rCore 不再选中任何跟 xv6 手写表同名的函数了"



def _panic_hit(kernel_kind: str, events: dict | None = None,
               params: list | None = ("info",)) -> dict:
    from types import SimpleNamespace

    from nodefusion.host.analyze import Analysis
    from nodefusion.host.nftrace import WatchHit

    stub = SimpleNamespace(
        kernel_kind=kernel_kind,
        kevents=events,
        watch_by_id={7: {"name": "panic", "symbol": "panic", "resource": "kernel",
                         "params": list(params) if params else []}},
        ram=SimpleNamespace(cstr=lambda addr, n: "看着像 panic 消息的东西"),
        elf=SimpleNamespace(resolve_pc=lambda pc: ("panic", 0)),
        _attribute=lambda cpu, si, cur: (1, "init"),
    )
    w = WatchHit(insn=1, cpu=0, flags=0, watch_id=7, priv=1,
                 pc=0x8020a2f8, satp=0, a=[0x80300000], sp=0, ra=0)
    ev = Analysis._watch_event(stub, w, 0, {})
    return ev.detail


def test_a_rust_kernels_panic_argument_is_not_read_as_a_c_string():
    assert "msg" not in _panic_hit("rcore"), \
        "把 &PanicInfo 当 C 字符串读了，读出来的东西会被当成 panic 消息"


def test_xv6s_panic_message_is_still_read():
    assert _panic_hit("xv6")["msg"] == "看着像 panic 消息的东西"



def test_manifest_argument_names_cannot_invent_values_that_were_never_captured():
    from types import SimpleNamespace

    spec = SimpleNamespace(kind="func.panic", args=["info", "line", "col"])
    d = _panic_hit("rcore", events={"panic": spec}, params=None)
    assert list(d) == ["info"], d
    assert "line" not in d and "col" not in d, "给没抓到的寄存器编了值"


def test_a_recorded_argument_name_beats_the_manifests():
    from types import SimpleNamespace

    mani = {"panic": SimpleNamespace(kind="func.panic", args=["from_manifest"])}
    assert list(_panic_hit("rcore", events=mani)) == ["info"]
    assert list(_panic_hit("rcore", events=mani, params=None)) == ["from_manifest"]


def test_manifest_argument_names_come_from_this_kernels_own_manifest():
    from types import SimpleNamespace

    def mk(n):
        return {"panic": SimpleNamespace(kind="func.panic", args=[n])}

    assert list(_panic_hit("rcore", events=mk("info"), params=None)) == ["info"]
    assert list(_panic_hit("arceos", events=mk("msg_and_loc"),
                           params=None)) == ["msg_and_loc"]
