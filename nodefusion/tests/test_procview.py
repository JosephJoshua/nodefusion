
import struct
import sys
import pathlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.host import procview
from nodefusion.model.dwarfsrc import DwarfSource
from nodefusion.model.manifest import load_dir
from nodefusion.model.probe import detect, probe
from nodefusion.model.resolve import ABSENT, EMPTY, PRESENT
from nodefusion.model.rt import DictMemory
from nodefusion.model.snapshot import SnapshotBuilder
from nodefusion.host.nfelf import Elf64
from nodefusion.model.symbols import SymbolIndex

_ROOT = Path(__file__).resolve().parents[2]
def _archived(kind: str):
    from nodefusion.host.kernels import archived_elf
    p = archived_elf(kind)
    return p if p is not None else pathlib.Path(f"/nonexistent/{kind}.elf")
_ELF = _archived("xv6")
_MANIFESTS = _ROOT / "nodefusion" / "manifests"
_PROC_SIZE = 504

needs_elf = pytest.mark.skipif(
    not _ELF.exists(),
    reason=f"要 xv6 teacher 内核 ELF（{_ELF}），是 build 产物，没有就跳过")


@pytest.fixture
def xv6():
    dw = DwarfSource(str(_ELF))
    ms = load_dir(str(_MANIFESTS))
    kind, why = detect(ms, dw)
    assert kind == "xv6", f"没认出是 xv6：{why}"
    return dw, ms[kind], probe(ms[kind], dw), SymbolIndex(Elf64(str(_ELF)), dw)


def _build(xv6, procs: list[dict]):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    e = next(x for x in res.entities if x.name == "task")
    off = {f.name: f.offset for f in e.fields if f.state == PRESENT}

    buf = bytearray(_PROC_SIZE * 64)
    for i, p in enumerate(procs):
        at = i * _PROC_SIZE
        for k, v in p.items():
            o = at + off[k]
            if isinstance(v, str):
                buf[o:o + len(v)] = v.encode()
            elif isinstance(v, list):
                for j, cell in enumerate(v):
                    struct.pack_into("<Q", buf, o + j * 8, cell)
            elif k in ("sz", "parent", "pgtbl", "chan"):
                struct.pack_into("<Q", buf, o, v)
            else:
                struct.pack_into("<i", buf, o, v)
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(
        DictMemory({base: bytes(buf)}))
    return snap, base



@needs_elf
def test_role_driven_keys_come_from_roles_not_field_names(xv6):
    snap, _ = _build(xv6, [{"pid": 7, "state": 3, "name": "sh", "priority": 9,
                            "pgtbl": 0x87F00000, "xstate": 3}])
    r = procview.row(snap.all("task")[0], slot=0)

    assert r["pid"] == 7
    assert r["name"] == "sh"
    assert r["state_name"] == "RUNNABLE"
    assert r["pagetable"] == 0x87F00000
    assert r["priority"] == 9
    assert r["xstate"] == 3


@needs_elf
def test_kernel_specific_keys_come_from_field_names(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4, "sz": 4096,
                            "chan": 0x80201000, "killed": 1}])
    r = procview.row(snap.all("task")[0], slot=0)

    assert (r["sz"], r["chan"], r["killed"]) == (4096, 0x80201000, 1)


@needs_elf
def test_unmapped_state_is_flagged_not_shown_as_a_bare_number(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": -2145173888}])
    r = procview.row(snap.all("task")[0], slot=0)

    assert r["state_name"] == "?0x80233e80", f"实际 {r['state_name']!r}"
    assert not isinstance(r["state_name"], int), "裸数字会被读成状态编号"


def test_render_state_passes_through_real_variant_names():
    assert procview.render_state("RUNNABLE") == "RUNNABLE"
    assert procview.render_state(None) is None


def test_render_state_uses_the_same_bits_as_the_old_decoder():
    assert procview.render_state(-2145173888) == "?0x80233e80"
    assert procview.render_state(2149793408) == "?0x80233e80"


def test_a_question_mark_means_stop_not_a_rendering_footnote():
    from nodefusion.tools.crosscheck_decoder import _unmapped_state as d_bad
    from nodefusion.tools.crosscheck_procinfo import _unmapped_state as p_bad

    for bad in (procview.render_state(-2145173888), "?-2145173888", "?0x1234"):
        assert d_bad(bad), f"{bad!r} 必须判失败，不能归类成渲染差异"
        assert p_bad(bad), f"{bad!r} 必须判失败，不能归类成渲染差异"

    for ok in ("RUNNABLE", "UNUSED", "ZOMBIE", None):
        assert not d_bad(ok)
        assert not p_bad(ok)



@needs_elf
def test_absent_field_is_none_never_zero(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4}])
    r = procview.row(snap.all("task")[0], slot=0)

    assert r["chan"] is None, f"空指针不该变成 {r['chan']!r}"
    assert r["killed"] == 0, "整数字段读到 0 就是 0，这个不能也变 None"


@needs_elf
def test_slot_is_a_row_number_addr_is_the_identity(xv6):
    snap, base = _build(xv6, [{"pid": 1, "state": 4}, {"pid": 2, "state": 4}])
    rows = [procview.row(e, slot=i) for i, e in enumerate(snap.all("task")[:2])]

    assert [r["slot"] for r in rows] == [0, 1]
    assert rows[0]["addr"] == base
    assert rows[1]["addr"] == base + _PROC_SIZE



@needs_elf
def test_fds_lists_occupied_slots(xv6):
    table = [0] * 16
    table[0] = table[1] = table[4] = 0x80300000
    snap, _ = _build(xv6, [{"pid": 1, "state": 4, "ofile": table}])

    assert procview.row(snap.all("task")[0], slot=0)["fds"] == [0, 1, 4]


@needs_elf
def test_empty_fd_table_is_not_the_same_as_no_fd_table(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4}])
    assert procview.row(snap.all("task")[0], slot=0)["fds"] == []

    class NoTable:
        addr = 0
        fields: dict = {}

        def get(self, _n): return None
        def role(self, _r): return None
        def link(self, _n): return None

    assert procview.open_fd_indices(NoTable()) is None


@needs_elf
def test_parent_pid_walks_the_link(xv6):
    at = xv6[3].resolve("proc")[0].addr
    snap, base = _build(xv6, [
        {"pid": 1, "state": 4},
        {"pid": 2, "state": 4, "parent": at},
    ])
    assert base == at
    kids = [e for e in snap.all("task") if e.get("pid") == 2]
    assert kids, "没找到子进程"

    assert procview.row(kids[0], slot=1)["parent_pid"] == 1


@needs_elf
def test_no_parent_is_none_not_a_crash(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4}])
    assert procview.row(snap.all("task")[0], slot=0)["parent_pid"] is None



@needs_elf
def test_generic_view_carries_fields_the_row_does_not_know(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4, "has_mail": 1}])
    e = snap.all("task")[0]

    assert "has_mail" not in procview.row(e, slot=0)
    assert procview.fields_view(e)["has_mail"]["value"] == 1


@needs_elf
def test_generic_view_keeps_absent_and_undecodable_apart(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4}])       # chan -> NULL
    view = procview.fields_view(snap.all("task")[0])

    assert view["chan"]["value"] is None
    assert view["chan"]["state"] == EMPTY
    assert view["chan"]["state"] != ABSENT, "xv6 有 chan，别说成内核没这字段"
    assert view["chan"]["reason"], "empty 得说清为什么"


@needs_elf
def test_generic_view_exposes_roles_so_a_generic_ui_can_find_them(xv6):
    snap, _ = _build(xv6, [{"pid": 7, "state": 3, "pgtbl": 0x87F00000}])
    view = procview.fields_view(snap.all("task")[0])

    assert view["pid"]["role"] == "id"
    assert view["pgtbl"]["role"] == "address_space_root"
    assert view["killed"]["role"] is None


@needs_elf
def test_generic_view_carries_the_declared_type(xv6):
    snap, _ = _build(xv6, [{"pid": 1, "state": 4, "pgtbl": 0x87F00000}])
    view = procview.fields_view(snap.all("task")[0])

    assert view["pgtbl"]["reader"] == "ptr"
    assert view["pid"]["reader"] == "i32"
    assert view["ofile"]["reader"] == "array<ptr>"

    assert view["chan"]["state"] == EMPTY
    assert view["chan"]["reader"] == "ptr", "读不到不代表不知道它是什么类型"


@needs_elf
def test_var_at_joins_dwarf_type_onto_a_symbol_found_by_address(xv6):
    dw, _, _, _ = xv6
    named = next((v for v in dw.variables.values()
                  if v.addr and v.type_off is not None), None)
    assert named is not None, "这个 ELF 里没有带地址且带类型的静态变量"

    got = dw.var_at(named.addr)
    assert got is not None, f"地址 {named.addr:#x} 上查不到变量"
    assert got.type_off == named.type_off, "按地址查到的类型该和按名字查到的一样"


@needs_elf
def test_var_at_says_nothing_when_no_variable_lives_there(xv6):
    dw, _, _, _ = xv6
    assert dw.var_at(0) is None, "0 不是有效地址，不该配上任何变量"
    assert dw.var_at(0xDEAD_BEEF_0000) is None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _ent(kind, addr, ctx=None, **links):
    from nodefusion.model.snapshot import Entity, Field
    e = Entity(kind=kind, addr=addr)
    if ctx is not None:
        e.fields["ctx"] = Field(name="ctx", state=PRESENT, value=ctx,
                                role="sched_context")
    e.links = {k: list(v) for k, v in links.items()}
    return e


def test_sched_contexts_takes_the_entitys_own_context():
    p = _ent("process", 0x8000_1000, ctx=0x8000_1040)
    assert procview.sched_contexts(p) == [0x8000_1040]


def test_sched_contexts_reaches_the_context_on_a_linked_thread():
    t = _ent("thread", 0x8000_2000, ctx=0x8000_2178)
    p = _ent("process", 0x8000_1000, threads=[t])
    assert procview.sched_contexts(p) == [0x8000_2178]


def test_sched_contexts_does_not_follow_a_link_to_the_same_kind():
    kid = _ent("process", 0x8000_3000, ctx=0x8000_3040)
    p = _ent("process", 0x8000_1000, ctx=0x8000_1040, children=[kid])
    assert procview.sched_contexts(p) == [0x8000_1040]


def test_sched_contexts_is_empty_when_nothing_declares_one():
    assert procview.sched_contexts(_ent("process", 0x8000_1000)) == []


def test_row_carries_every_context_not_just_its_own():
    t = _ent("thread", 0x8000_2000, ctx=0x8000_2178)
    p = _ent("process", 0x8000_1000, threads=[t])
    r = procview.row(p, slot=0)
    assert r["sched_ctx"] is None, "进程自己确实没有上下文"
    assert r["sched_ctxs"] == [0x8000_2178], "线程那个得带上"
