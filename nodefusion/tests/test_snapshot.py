
from __future__ import annotations

import struct
import pathlib
from pathlib import Path

import pytest

from nodefusion.model import snapshot as snapshot_mod
from nodefusion.model.dwarfsrc import DwarfSource
from nodefusion.model.manifest import ManifestError, SourceSpec, _fields, load_dir
from nodefusion.model.probe import ResolvedField, detect, probe
from nodefusion.model.resolve import ABSENT, EMPTY, PRESENT, UNDECODABLE
from nodefusion.model.roles import ROLES
from nodefusion.model.rt import DictMemory
from nodefusion.model.snapshot import (Field, SnapshotBuilder, is_live,
                                       report)
from nodefusion.host.nfelf import Elf64
from nodefusion.model.symbols import SymbolIndex

_ROOT = Path(__file__).resolve().parents[2]
def _archived(kind: str):
    from nodefusion.host.kernels import archived_elf
    p = archived_elf(kind)
    return p if p is not None else pathlib.Path(f"/nonexistent/{kind}.elf")
_ELF = _archived("xv6")
_MANIFESTS = _ROOT / "nodefusion" / "manifests"

needs_elf = pytest.mark.skipif(
    not _ELF.exists(),
    reason=f"要 xv6 teacher 内核 ELF（{_ELF}），是 build 产物，没有就跳过")



def test_unknown_role_is_refused_with_candidates():
    with pytest.raises(ManifestError) as e:
        _fields({"x": {"path": "p", "role": "pagetable_root"}}, optional=False)
    assert "pagetable_root" in str(e.value)
    for r in ROLES:
        assert r in str(e.value)


def test_field_opts_measure_nested_btreemap_die(monkeypatch):
    class Dw:
        def array_of(self, _off):
            return None

    dw = Dw()
    builder = object.__new__(SnapshotBuilder)
    builder.dw = dw
    field = ResolvedField(
        name="children", path="children",
        reader="spinlock<btreemap<newtype<u32>, arc>>",
        state=PRESENT, type_off=10, type_name="SpinLock<Map>")

    monkeypatch.setattr(snapshot_mod, "vec_opts", lambda *_: {})
    monkeypatch.setattr(snapshot_mod, "string_opts", lambda *_: {})
    monkeypatch.setattr(snapshot_mod, "shell_opts", lambda *_: {})
    monkeypatch.setattr(snapshot_mod, "layer_chain", lambda *_: [])
    monkeypatch.setattr(snapshot_mod, "reader_layer_die",
                        lambda *_: 20)
    monkeypatch.setattr(snapshot_mod, "qualified_name",
                        lambda _dw, off: "alloc::BTreeMap<K,V,A>" if off == 20 else None)
    seen = []

    def measured(_dw, off):
        seen.append(off)
        return {"btree_len": 54}

    monkeypatch.setattr(snapshot_mod, "btree_opts", measured)

    opts = builder._opts(field)
    assert seen == [20]
    assert opts["btree_map_type"] == "alloc::BTreeMap<K,V,A>"
    assert opts["btree_len"] == 54


def test_every_shipped_manifest_uses_only_known_roles():
    for name, m in load_dir(str(_MANIFESTS)).items():
        for e in m.entities:
            for f in e.fields + e.relations:
                assert f.role is None or f.role in ROLES, \
                    f"{name}/{e.name}/{f.name} 用了闭集外的角色 {f.role!r}"


def test_divergent_names_all_carry_a_role():
    ms = load_dir(str(_MANIFESTS))
    want = {
        ("xv6", "task", "pid"): "id",
        ("rcore", "task", "pid"): "id",
        ("rcore", "task", "status"): "state",
        ("rcore", "task", "prio"): "priority",
        ("alien", "task", "tid"): "id",
        ("arceos", "task", "id"): "id",
        ("arceos", "task", "exit"): "exit_code",
        ("xv6", "task", "xstate"): "exit_code",
        ("starry", "thread", "id"): "id",
        ("starry", "process", "pid"): "id",
        ("axvisor", "vm", "vm_id"): "id",
        ("axvisor", "vcpu", "vcpu_id"): "id",
    }
    absent_by_measurement = {
        ("axvisor", "vcpu"):
            "AxVMResources 够不着：rustc 把 Machine<AxVMResources, …> 发成没有成员的"
            "480 字节洞，vm.vcpus 这一跳断了；percpu 两条路也都量过不通。"
            "理由见 axvisor.toml 里 vcpu 那段。",
    }
    for (mk, ek, fk), role in want.items():
        ent = ms[mk].entity(ek)
        if ent is None:
            assert (mk, ek) in absent_by_measurement, \
                f"{mk} 里没有实体 {ek}（若是量过之后确认够不着，写进 absent_by_measurement 并附理由）"
            continue
        f = next((x for x in ent.fields + ent.relations if x.name == fk), None)
        assert f is not None, f"{mk}/{ek} 里没有字段 {fk}"
        assert f.role == role, f"{mk}/{ek}/{fk} 的角色该是 {role!r}，实际 {f.role!r}"



_PROC_SIZE = 504


@pytest.fixture
def xv6():
    dw = DwarfSource(str(_ELF))
    ms = load_dir(str(_MANIFESTS))
    kind, why = detect(ms, dw)
    assert kind == "xv6", f"没认出是 xv6：{why}"
    m = ms[kind]
    return dw, m, probe(m, dw), SymbolIndex(Elf64(str(_ELF)), dw)


_PACK = {"u64": "<Q", "ptr": "<Q", "i64": "<q",
         "u32": "<I", "i32": "<i", "enum": "<i"}


def _plan(res) -> dict[str, tuple[int, str]]:
    e = next(x for x in res.entities if x.name == "task")
    return {f.name: (f.offset, f.reader)
            for f in e.fields if f.state == PRESENT}


def _mem(res, base: int, procs: list[dict]) -> DictMemory:
    plan = _plan(res)
    buf = bytearray(_PROC_SIZE * 64)
    for i, p in enumerate(procs):
        at = i * _PROC_SIZE
        for k, v in p.items():
            o, reader = plan[k]
            if isinstance(v, str):
                buf[at + o:at + o + len(v)] = v.encode()
                continue
            fmt = _PACK.get(reader)
            if fmt is None:
                raise AssertionError(
                    f"字段 {k!r} 的 reader 是 {reader!r}，_PACK 里没有对应的"
                    f"宽度。补一条，别猜 —— 猜错了这个字段会被摆到隔壁去，"
                    f"而测试照样跑得过。")
            struct.pack_into(fmt, buf, at + o, v)
    return DictMemory({base: bytes(buf)})


@needs_elf
def test_decodes_every_field_exactly(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    want = {"pid": 42, "state": 4, "name": "init", "sz": 4096,
            "parent": base + _PROC_SIZE, "pgtbl": 0x87F00000, "chan": 0x80201000,
            "trapframe": 0x87F01000, "kstack": 0x3FFFFF9000, "cwd": 0x80202000,
            "priority": 10, "stride": 20, "pass": 30, "has_mail": 1}
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(_mem(res, base, [want]))
    e = snap.all("task")[0]

    assert e.get("pid") == 42
    assert e.get("state") == "RUNNING"
    assert e.get("name") == "init"
    assert e.get("sz") == 4096
    assert e.get("parent") == base + _PROC_SIZE
    assert e.get("pgtbl") == 0x87F00000
    assert (e.get("priority"), e.get("stride"), e.get("pass")) == (10, 20, 30)
    assert e.get("has_mail") == 1
    assert e.get("trapframe") == 0x87F01000
    assert e.get("kstack") == 0x3FFFFF9000
    assert e.get("cwd") == 0x80202000
    missing = {n: f.state for n, f in e.fields.items() if f.state != PRESENT}
    assert not missing, f"这些字段没解出来：{missing}"


@needs_elf
def test_null_pointer_is_empty_not_zero(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(
        _mem(res, base, [{"pid": 1, "state": 4}]))
    chan = snap.all("task")[0].fields["chan"]

    assert chan.state == EMPTY, f"空指针应当是 empty，实际 {chan.state}"
    assert chan.value is None, f"empty 不该带值，实际 {chan.value!r}"
    assert chan.state != UNDECODABLE, "空指针是正常结果，不是解码失败"
    assert chan.state != ABSENT, "字段在、值为空，不等于这个内核没有这个字段"


@needs_elf
def test_liveness_skips_free_slots_but_all_still_returns_every_slot(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(
        _mem(res, base, [{"pid": 1, "state": 4}]))
    ents = snap.all("task")
    alive = m.entity("task").liveness

    assert len(ents) == 64, "all() 不该替人筛"
    live = [(i, e) for i, e in enumerate(ents) if is_live(e, alive)]
    assert len(live) == 1 and live[0][0] == 0


def test_liveness_defaults_to_live_when_it_cannot_tell():
    class E:
        fields = {"state": Field("state", ABSENT, None)}

    assert is_live(E(), {"skip_when": {"field": "state", "equals": "UNUSED"}})
    assert is_live(E(), None)
    assert is_live(E(), {"skip_when": {"equals": "UNUSED"}})


def test_liveness_only_skips_on_an_exact_match():
    class E:
        def __init__(self, v):
            self.fields = {"state": Field("state", PRESENT, v)}

    spec = {"skip_when": {"field": "state", "equals": "UNUSED"}}
    assert not is_live(E("UNUSED"), spec)
    assert is_live(E("RUNNING"), spec)
    assert is_live(E(2149793408), spec)


@needs_elf
def test_entity_count_comes_from_dwarf_not_a_constant(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    elem, count = dw.array_of(dw.var("proc").type_off)
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(_mem(res, base, []))
    assert len(snap.all("task")) == count
    assert dw.size_of(elem) == _PROC_SIZE


@needs_elf
def test_roles_resolve_across_the_closed_vocabulary(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(_mem(res, base, [
        {"pid": 7, "state": 3, "name": "sh", "priority": 9,
         "pgtbl": 0x87F00000, "xstate": 3}]))
    e = snap.all("task")[0]
    assert e.role("id") == 7
    assert e.role("name") == "sh"
    assert e.role("state") == "RUNNABLE"
    assert e.role("address_space_root") == 0x87F00000
    assert e.role("priority") == 9
    assert e.role("exit_code") == 3


@needs_elf
def test_role_of_an_absent_field_is_none_not_an_error(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(
        _mem(res, base, [{"pid": 7, "state": 3}]))
    e = snap.all("task")[0]

    assert e.fields["pgtbl"].state == EMPTY
    assert e.role("address_space_root") is None
    assert e.role("id") == 7


@needs_elf
def test_zero_pointer_is_empty_not_a_failure(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(
        _mem(res, base, [{"pid": 1, "parent": 0}]))
    f = snap.all("task")[0].fields["parent"]
    assert f.state == EMPTY and f.reason
    assert f.state != UNDECODABLE


@needs_elf
def test_truncation_is_reported_not_silent(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    b = SnapshotBuilder(dw, res, m, syms=syms, max_items=8)
    snap = b.build(_mem(res, base, []))
    s = snap.sets["task"]
    assert s.truncated and len(s.entities) == 8
    assert "至少" in report(snap)


@needs_elf
def test_links_resolve_addresses_into_entities(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(_mem(res, base, [
        {"pid": 1, "parent": 0},
        {"pid": 2, "parent": base},
        {"pid": 3, "parent": base + _PROC_SIZE},
    ]))
    a, b, c = snap.all("task")[:3]
    assert a.link("parent") is None
    assert b.link("parent") is a and b.link("parent").get("pid") == 1
    assert c.link("parent") is b and c.link("parent").get("pid") == 2
    assert snap.at(base) is a
    assert snap.sets["task"].dangling == 0


@needs_elf
def test_dangling_link_is_counted_not_reported_as_failure(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    far = base + _PROC_SIZE * 4096
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(
        _mem(res, base, [{"pid": 1, "parent": far}]))
    e = snap.all("task")[0]
    assert e.link("parent") is None
    assert e.get("parent") == far
    assert e.fields["parent"].state == PRESENT
    s = snap.sets["task"]
    assert s.dangling == 1 and not s.problems
    assert "没枚举到" in report(snap)


@needs_elf
def test_compile_failure_surfaces_as_unavailable(xv6):
    dw, m, res, syms = xv6
    for e in res.entities:
        if e.name == "task":
            e.sources = [SourceSpec(kind="table", completeness="total",
                                    steps=[{"static": "根本不存在的符号"}])]
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(DictMemory({}))
    s = snap.sets["task"]
    assert s.entities == [] and not s.ok
    assert s.unavailable and "根本不存在的符号" in s.unavailable


@needs_elf
def test_completeness_carries_through_from_manifest(xv6):
    dw, m, res, syms = xv6
    base = syms.resolve("proc")[0].addr
    snap = SnapshotBuilder(dw, res, m, syms=syms).build(_mem(res, base, []))
    src = next(e.source for e in res.entities if e.name == "task")
    assert snap.sets["task"].completeness == src.completeness



#     why = [p.reason for p in snap.problems]


def _es(**kw):
    from nodefusion.model.snapshot import EntitySet
    return EntitySet(kind="task", **kw)


def test_problems_from_an_unbuilt_set_are_unavailable_not_str():
    from nodefusion.model.rt import Unavailable
    from nodefusion.model.snapshot import Snapshot

    snap = Snapshot(sets={"task": _es(unavailable="找不到静态符号 X")})
    got = snap.problems

    assert len(got) == 1
    assert isinstance(got[0], Unavailable), f"混进了 {type(got[0]).__name__}"
    assert got[0].reason == "找不到静态符号 X"


def test_every_problem_has_a_reason_attribute():
    from nodefusion.model.rt import Unavailable
    from nodefusion.model.snapshot import Snapshot

    snap = Snapshot(sets={
        "task": _es(unavailable="整组没建起来"),
        "file": _es(problems=[Unavailable("读不了", addr=0x8020_0000)]),
    })
    reasons = [p.reason for p in snap.problems]
    assert sorted(reasons) == ["整组没建起来", "读不了"]


def test_the_unbuilt_field_itself_stays_a_string():
    es = _es(unavailable="找不到静态符号 X")
    assert isinstance(es.unavailable, str)
    assert "找不到" in es.unavailable


def test_a_partly_compiled_entity_reports_a_reason_not_an_empty_one():
    from nodefusion.model.rt import Unavailable
    from nodefusion.model.snapshot import Snapshot

    snap = Snapshot(sets={"task": _es(problems=[Unavailable("")])})
    assert all(isinstance(p, Unavailable) for p in snap.problems)

    import inspect

    from nodefusion.model.snapshot import SnapshotBuilder
    src = inspect.getsource(SnapshotBuilder._one)
    assert '_why.get(r.name, "")' not in src, (
        "兜底又变回空字符串了：没有原因的 problem 会让 ok=False 而界面上一片"
        "空白，跟没有故障长得一样")


# ------------------------------------------------------------------ inverse


def _graph(*ents):
    from nodefusion.model.snapshot import Entity, EntitySet, Snapshot
    snap = Snapshot()
    for e in ents:
        snap.sets.setdefault(e.kind, EntitySet(kind=e.kind)).entities.append(e)
        snap.index.setdefault(e.addr, e)
    return snap


def _ent(kind, addr, **fields):
    from nodefusion.model.snapshot import Entity
    e = Entity(kind=kind, addr=addr)
    e.fields.update(fields)
    return e


def _wire(snap):
    SnapshotBuilder._link(None, snap)   # type: ignore[arg-type]
    return snap


def test_inverse_records_the_edge_on_the_far_side_too():
    proc = _ent("process", 0x1000)
    t1 = _ent("thread", 0x2000, process=Field(
        "process", PRESENT, value=0x1000, links_to="process", inverse="threads"))
    t2 = _ent("thread", 0x3000, process=Field(
        "process", PRESENT, value=0x1000, links_to="process", inverse="threads"))
    _wire(_graph(proc, t1, t2))

    assert t1.link("process") is proc
    assert proc.links["threads"] == [t1, t2]
    assert proc.links["threads"][0] is t1


def test_inverse_does_not_invent_an_edge_when_the_forward_one_missed():
    proc = _ent("process", 0x1000)
    ghost = _ent("thread", 0x2000, process=Field(
        "process", PRESENT, value=0x9999,
        links_to="process", inverse="threads"))
    snap = _wire(_graph(proc, ghost))

    assert ghost.link("process") is None
    assert "threads" not in proc.links
    assert snap.sets["thread"].dangling == 1


def test_inverse_is_skipped_when_the_field_did_not_decode():
    proc = _ent("process", 0x1000)
    broken = _ent("thread", 0x2000, process=Field(
        "process", UNDECODABLE, reason="读不到",
        links_to="process", inverse="threads"))
    _wire(_graph(proc, broken))

    assert "threads" not in proc.links
    assert broken.link("process") is None


def test_inverse_dedups_by_identity_not_by_value():
    proc = _ent("process", 0x1000)
    mk = lambda a: _ent("thread", a, process=Field(
        "process", PRESENT, value=0x1000, links_to="process",
        inverse="threads"))
    t1, t2 = mk(0x2000), mk(0x3000)
    t1.addr = t2.addr = 0x2000
    snap = _wire(_graph(proc, t1, t2))

    got = proc.links["threads"]
    assert len(got) == 2
    assert got[0] is t1 and got[1] is t2


def test_inverse_without_links_to_is_refused_at_load():
    with pytest.raises(ManifestError, match="inverse"):
        _fields({"process": {"path": "task_ext", "inverse": "threads"}},
                optional=False)
