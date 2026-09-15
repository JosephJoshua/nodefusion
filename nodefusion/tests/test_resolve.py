
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.layout import StructLayout
from nodefusion.model import resolve as R
from nodefusion.model.resolve import (
    ABSENT, PRESENT, refcounted_payload_die, resolve_path)


class FakeDw:

    def __init__(self, structs: dict[int, StructLayout],
                 pointers: dict[int, int] | None = None,
                 arrays: dict[int, tuple[int, int | None]] | None = None,
                 sizes: dict[int, int] | None = None) -> None:
        self._s = structs
        self._p = pointers or {}
        self._a = arrays or {}
        self._sz = sizes or {}

    def struct_at(self, off):
        return self._s.get(off)

    def type_name(self, off):
        if off in self._p:
            return f"*const {self.type_name(self._p[off])}"
        s = self._s.get(off)
        return (s.path or s.name) if s else None

    def pointee(self, off):
        return self._p.get(off)

    def array_of(self, off):
        return self._a.get(off)

    def size_of(self, off):
        return self._sz.get(off)

    def find(self, name):
        for s in self._s.values():
            if name in (s.path, s.name):
                return s
        return None


def chain() -> tuple[FakeDw, StructLayout]:
    payload = StructLayout(
        name="Inner", path="k::Inner", size=264,
        fields={f: i * 8 for i, f in enumerate(
            ("memory_set", "trap_cx_ppn", "base_size", "task_cx", "children",
             "fd_table", "parent", "heap_bottom", "program_brk", "exit_code",
             "task_status"))},
        field_types={"children": 7})
    rawvec = StructLayout(
        name="RawVec<Arc<Tcb, Global>, Global>",
        path=("alloc::raw_vec::RawVec<alloc::sync::Arc<k::Tcb, "
              "alloc::alloc::Global>, alloc::alloc::Global>"),
        size=24, fields={"ptr": 0, "cap": 8, "alloc": 16})
    ucell_inner = StructLayout(name="UnsafeCell<Inner>", path="core::UnsafeCell<Inner>",
                               size=264, fields={"value": 0}, field_types={"value": 6})
    ucell_isize = StructLayout(name="UnsafeCell<isize>", path="core::UnsafeCell<isize>",
                               size=8, fields={"value": 0})
    cell = StructLayout(name="Cell<isize>", path="core::Cell<isize>", size=8,
                        fields={"value": 0}, field_types={"value": 5})
    refcell = StructLayout(name="RefCell<Inner>", path="core::RefCell<Inner>",
                           size=272, fields={"borrow": 0, "value": 8},
                           field_types={"borrow": 3, "value": 4})
    upsafe = StructLayout(name="UPSafeCell<Inner>", path="k::UPSafeCell<Inner>",
                          size=272, fields={"inner": 0}, field_types={"inner": 2})
    tcb = StructLayout(name="Tcb", path="k::Tcb", size=288,
                       fields={"inner": 0, "pid": 272}, field_types={"inner": 1})
    return FakeDw({1: upsafe, 2: refcell, 3: cell, 4: ucell_inner,
                   5: ucell_isize, 6: payload, 7: rawvec}), tcb



def test_descends_through_three_wrappers():
    dw, tcb = chain()
    got = resolve_path(dw, tcb, "inner.task_status")
    assert got.state == PRESENT
    assert got.offset == 8 + 80
    assert got.hops == ["inner", "inner", "value", "value", "task_status"]


def test_plain_field_needs_no_descent():
    dw, tcb = chain()
    got = resolve_path(dw, tcb, "pid")
    assert got.state == PRESENT and got.offset == 272 and got.hops == ["pid"]



def test_missing_field_is_absent_not_a_failure():
    dw, tcb = chain()
    assert resolve_path(dw, tcb, "inner.priority").state == ABSENT


def test_missing_field_names_the_payload_type_not_just_the_wrapper():
    dw, tcb = chain()
    why = resolve_path(dw, tcb, "inner.priority").reason or ""

    assert "k::Inner" in why, f"没点名载荷类型：{why}"
    assert "task_status" in why, f"没列出载荷类型的字段，人无从判断：{why}"

    noise = why.find("UnsafeCell<isize>")
    assert noise == -1 or why.find("k::Inner") < noise, \
        f"载荷被无关的壳挤到后面了：{why}"


def test_missing_field_offers_both_explanations():
    why = resolve_path(*chain(), "inner.priority").reason or ""
    assert "optional" in why, "没提缺席可以靠 optional 表达"
    assert "unwrap" in why, "没提可能是要穿指针"


def test_candidate_type_is_listed_in_full_runners_up_are_clipped():
    why = resolve_path(*chain(), "inner.priority").reason or ""

    for f in ("memory_set", "task_status", "trap_cx_ppn"):
        assert f in why, f"头名的字段 {f} 没列出来：{why}"

    long_path = ("alloc::raw_vec::RawVec<alloc::sync::Arc<k::Tcb, "
                 "alloc::alloc::Global>, alloc::alloc::Global>")
    assert long_path not in why, "陪衬的长名字没截断"
    assert "alloc::raw_vec::RawVec<" in why, "截过头了，认不出是哪个类型"


def test_reason_stays_one_line_and_bounded():
    why = resolve_path(*chain(), "inner.priority").reason or ""
    assert "\n" not in why
    assert len(why) < 600, f"太长了（{len(why)} 字）：{why}"



#:     Arc<Mutex<BlockCache>, Global>  size 8   .ptr@0 .phantom@8 .alloc@8
#:       NonNull<ArcInner<Mutex<…>>>   size 8   .pointer@0
#:         *const ArcInner<…>                   -> pointee
#:           ArcInner<Mutex<…>>        size 576 .strong@0 .weak@8 .data@16
def arc_chain() -> tuple[FakeDw, int]:
    payload = StructLayout(name="Mutex<BlockCache>",
                           path="spin::mutex::Mutex<easy_fs::block_cache::BlockCache>",
                           size=560, fields={"inner": 0})
    arcinner = StructLayout(
        name="ArcInner<Mutex<BlockCache>>",
        path="alloc::sync::ArcInner<spin::mutex::Mutex<easy_fs::block_cache::BlockCache>>",
        size=576, fields={"strong": 0, "weak": 8, "data": 16},
        field_types={"strong": 40, "weak": 40, "data": 10})
    nonnull = StructLayout(
        name="NonNull<ArcInner<Mutex<BlockCache>>>",
        path="core::ptr::non_null::NonNull<alloc::sync::ArcInner<…>>",
        size=8, fields={"pointer": 0}, field_types={"pointer": 30})
    arc = StructLayout(
        name="Arc<Mutex<BlockCache>, Global>",
        path=("alloc::sync::Arc<spin::mutex::Mutex<easy_fs::block_cache::BlockCache>, "
              "alloc::alloc::Global>"),
        size=8, fields={"ptr": 0, "phantom": 8, "alloc": 8},
        field_types={"ptr": 20, "phantom": 41, "alloc": 42})
    atomic = StructLayout(name="AtomicUsize", path="core::AtomicUsize", size=8,
                          fields={"v": 0})
    dw = FakeDw({10: payload, 11: arcinner, 20: nonnull, 40: atomic,
                 41: atomic, 42: atomic, 50: arc},
                pointers={30: 11})
    return dw, 50


def test_arc_payload_type_comes_from_dwarf_not_from_the_name():
    dw, arc = arc_chain()
    got = refcounted_payload_die(dw, arc)
    assert got == 10
    assert dw.type_name(got) == \
        "spin::mutex::Mutex<easy_fs::block_cache::BlockCache>"


def test_arc_payload_walks_the_named_pointer_field_not_the_first_one():
    dw, arc = arc_chain()
    nn = dw.struct_at(20)
    nn.fields = {"decoy": 0, "pointer": 8}
    nn.field_types = {"decoy": 40, "pointer": 30}
    assert refcounted_payload_die(dw, arc) == 10


def test_a_shell_without_a_ptr_field_is_refused():
    dw, _ = arc_chain()
    assert refcounted_payload_die(dw, 10) is None


def test_both_payload_spellings_at_once_is_refused():
    dw, arc = arc_chain()
    inner = dw.struct_at(11)
    inner.fields = {"strong": 0, "weak": 8, "data": 16, "value": 24}
    inner.field_types = {"strong": 40, "weak": 40, "data": 10, "value": 10}
    assert refcounted_payload_die(dw, arc) is None


def test_unknown_die_is_none_not_a_guess():
    dw, _ = arc_chain()
    assert refcounted_payload_die(dw, None) is None
    assert refcounted_payload_die(dw, 9999) is None



#:     BTreeMap   { root: 0, length: 16 }
#:     LeafNode   { parent: 0, keys: 8, vals: 96, parent_idx: 184, len: 186 }
#:     InternalNode { data: 0, edges: 192 }
_BT_MAP, _BT_OPT, _BT_REF, _BT_NN = 100, 101, 102, 103
_BT_LEAF, _BT_KEYS, _BT_VALS, _BT_K, _BT_V, _BT_INT = 104, 105, 106, 107, 108, 109


def btree_dw(*, internal: bool = True, leaf_fields: dict | None = None):
    leaf = StructLayout(
        name="LeafNode<K, V>", path="alloc::…::node::LeafNode<K, V>", size=192,
        fields=leaf_fields if leaf_fields is not None else
        {"parent": 0, "keys": 8, "vals": 96, "parent_idx": 184, "len": 186},
        field_types={"keys": _BT_KEYS, "vals": _BT_VALS})
    structs = {
        _BT_MAP: StructLayout(
            name="BTreeMap<K, V, A>", path="alloc::…::map::BTreeMap<K, V, A>",
            size=24, fields={"root": 0, "length": 16},
            field_types={"root": _BT_OPT}),
        _BT_OPT: StructLayout(
            name="Option<NodeRef<K, V>>",
            path="core::option::Option<alloc::…::node::NodeRef<K, V>>",
            size=16, fields={}, field_types={}),
        _BT_REF: StructLayout(
            name="NodeRef<K, V>", path="alloc::…::node::NodeRef<K, V>",
            size=16, fields={"node": 0, "height": 8},
            field_types={"node": _BT_NN}),
        _BT_LEAF: leaf,
    }
    if internal:
        structs[_BT_INT] = StructLayout(
            name="InternalNode<K, V>",
            path="alloc::…::node::InternalNode<K, V>", size=288,
            fields={"data": 0, "edges": 192}, field_types={})
    return FakeDw(structs,
                  pointers={_BT_NN: _BT_LEAF},
                  arrays={_BT_KEYS: (_BT_K, 11), _BT_VALS: (_BT_V, 11)},
                  sizes={_BT_K: 8, _BT_V: 8})


def test_btree_opts_measures_the_whole_node_layout():
    got = R.btree_opts(btree_dw(), _BT_MAP)
    assert got == {"btree_noderef_height": 8, "btree_noderef_node": 0,
                   "btree_len": 186, "btree_keys": 8, "btree_vals": 96,
                   "btree_key_size": 8, "btree_val_size": 8,
                   "btree_edges": 192}


def test_btree_opts_reaches_noderef_through_the_option_name():
    dw = btree_dw()
    assert dw.struct_at(_BT_OPT).fields == {}
    assert R.btree_opts(dw, _BT_MAP)["btree_noderef_node"] == 0


def test_btree_opts_key_and_val_sizes_come_from_the_array_element():
    got = R.btree_opts(btree_dw(), _BT_MAP)
    assert got["btree_key_size"] == 8 and got["btree_val_size"] == 8


def test_btree_opts_without_internal_node_still_reports_the_leaf_layout():
    got = R.btree_opts(btree_dw(internal=False), _BT_MAP)
    assert "btree_edges" not in got
    assert got["btree_len"] == 186


def test_btree_opts_refuses_a_half_measured_layout_entirely():
    leaf = {"parent": 0, "keys": 8, "len": 186}
    assert R.btree_opts(btree_dw(leaf_fields=leaf), _BT_MAP) == {}


def test_btree_opts_on_something_that_is_not_a_map_is_empty():
    dw = btree_dw()
    assert R.btree_opts(dw, _BT_REF) == {}


def test_reader_layer_die_reaches_btreemap_inside_spinlock():
    dw = btree_dw()
    outer, base = 110, 111
    dw._s[outer] = StructLayout(
        name="SpinLock<BTreeMap<K, V, A>>", path="k::SpinLock<alloc::BTreeMap<K,V,A>>",
        size=32, fields={"__0": 0}, field_types={"__0": base})
    dw._s[base] = StructLayout(
        name="BaseSpinLock<G, BTreeMap<K, V, A>>",
        path="k::BaseSpinLock<G,alloc::BTreeMap<K,V,A>>", size=32,
        fields={"lock": 0, "data": 8},
        field_types={"lock": _BT_K, "data": _BT_MAP})
    dw._sz.update({base: 32, _BT_MAP: 24})

    got = R.reader_layer_die(
        dw, "spinlock<btreemap<newtype<u64>, struct>>", outer, "btreemap")

    assert got == _BT_MAP
    assert R.btree_opts(dw, got)["btree_len"] == 186
    assert R.btree_opts(dw, outer) == {}
