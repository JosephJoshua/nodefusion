
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.readers import containers as C   # noqa: E402
from nodefusion.model.rt import (                      # noqa: E402
    DictMemory, ReadCtx, Unavailable, is_ok,
)



def u16(v: int) -> bytes:
    return int.to_bytes(v, 2, "little")


def u32(v: int) -> bytes:
    return int.to_bytes(v, 4, "little")


def u64(v: int) -> bytes:
    return int.to_bytes(v, 8, "little")


def read_u32(mem, addr, ctx):
    v = mem.u32(addr)
    return Unavailable("读不到 u32", addr) if v is None else v


def read_u64(mem, addr, ctx):
    v = mem.u64(addr)
    return Unavailable("读不到 u64", addr) if v is None else v



def test_array_of_scalars():
    mem = DictMemory().write(0x1000, u32(11) + u32(22) + u32(33) + u32(44))
    got = C.array(4, 4, read_u32)(mem, 0x1000, ReadCtx())
    assert got == [11, 22, 33, 44], got
    assert C.incomplete_of(got) is None


def test_array_count_comes_from_caller_not_from_size():
    mem = DictMemory().write(0x1000, u32(11) + u32(22) + u32(33) + b"\xff" * 4)
    got = C.array(4, 3, read_u32)(mem, 0x1000, ReadCtx())
    assert got == [11, 22, 33], got


def test_array_broken_element_stays_at_its_index():
    mem = (DictMemory().write(0x1000, u32(11) + u32(22))
                       .write(0x100C, u32(44)))
    got = C.array(4, 4, read_u32)(mem, 0x1000, ReadCtx())
    assert len(got) == 4, got
    assert got[0] == 11 and got[1] == 22 and got[3] == 44
    assert isinstance(got[2], Unavailable) and not is_ok(got[2])
    assert C.incomplete_of(got) is None


def test_array_truncation_is_visible():
    mem = DictMemory().write(0x1000, b"".join(u32(i) for i in range(10)))
    got = C.array(4, 10, read_u32)(mem, 0x1000, ReadCtx(max_items=3))
    assert got[:3] == [0, 1, 2], got
    t = C.incomplete_of(got)
    assert isinstance(t, C.Truncated), got
    assert "10" in t.reason and "max_items" in t.reason
    assert len(got) == 4


def test_array_zero_count_is_genuinely_empty():
    got = C.array(4, 0, read_u32)(DictMemory(), 0x1000, ReadCtx())
    assert got == []


def test_array_rejects_bad_elem_size():
    got = C.array(0, 4, read_u32)(DictMemory(), 0x1000, ReadCtx())
    assert isinstance(got, Unavailable) and "DW_AT_byte_size" in got.reason


# =============================================================== Vec

VEC_LAYOUT = {
    "Vec<u32>": {"buf": 0, "len": 16},
    "RawVec<u32>": {"cap": 0, "ptr": 8, "alloc": 16},
    "Unique<u32>": {"pointer": 0, "_marker": 8},
}


def _vec(**kw):
    kw.setdefault("raw_type", "RawVec<u32>")
    return C.vec("Vec<u32>", kw.pop("elem_size", 4), read_u32, **kw)


def _vec_mem(*, ptr=0x3000, cap=8, ln=3, at=0x2000, elems=(11, 22, 33)):
    mem = DictMemory().write(at, u64(cap) + u64(ptr) + u64(ln))
    if elems:
        mem.write(ptr, b"".join(u32(e) for e in elems))
    return mem


def test_vec_with_cap_before_ptr():
    assert _vec()(_vec_mem(), 0x2000, ReadCtx(layout=VEC_LAYOUT)) == [11, 22, 33]


def test_vec_reproduces_measured_rcore_ch6_offsets():
    base = 64
    mem = DictMemory().write(base, u64(4) + u64(0x9000) + u64(2))
    mem.write(0x9000, u32(101) + u32(202))
    ctx = ReadCtx(layout=VEC_LAYOUT)
    assert _vec()(mem, base, ctx) == [101, 202]

    off, why = _vec()._offsets(ctx)
    assert off is not None, why
    assert {k: base + v for k, v in off.items()} == {
        "cap": 64, "ptr": 72, "len": 80}, off


def test_vec_unique_is_transparent_by_default():
    mem, ctx = _vec_mem(), ReadCtx(layout=VEC_LAYOUT)
    assert _vec()(mem, 0x2000, ctx) == [11, 22, 33]
    assert _vec(unique_type="Unique<u32>")(mem, 0x2000, ctx) == [11, 22, 33]


def test_vec_with_ptr_before_cap():
    mem = DictMemory().write(0x2000, u64(0x3000) + u64(8) + u64(3))
    mem.write(0x3000, u32(11) + u32(22) + u32(33))
    lay = {"Vec<u32>": {"buf": 0, "len": 16},
           "RawVec<u32>": {"ptr": 0, "cap": 8}}
    assert _vec()(mem, 0x2000, ReadCtx(layout=lay)) == [11, 22, 33]


def test_vec_explicit_offsets_bypass_ctx():
    r = C.vec("Vec<u32>", 4, read_u32,
              offsets={"cap": 0, "ptr": 8, "len": 16})
    assert r(_vec_mem(), 0x2000, ReadCtx()) == [11, 22, 33]


def test_vec_flat_offsets_still_tolerated():
    lay = {"Vec<u32>": {"cap": 0, "ptr": 8, "len": 16}}
    r = C.vec("Vec<u32>", 4, read_u32)
    assert r(_vec_mem(), 0x2000, ReadCtx(layout=lay)) == [11, 22, 33]


def test_vec_unreadable_pointer_field_is_unavailable():
    mem = DictMemory().write(0x3000, u32(11) + u32(22) + u32(33))
    got = _vec()(mem, 0x2000, ReadCtx(layout=VEC_LAYOUT))
    assert isinstance(got, Unavailable), got
    assert not is_ok(got)
    assert got.addr is not None


def test_vec_pointer_into_unmapped_memory():
    mem = DictMemory().write(0x2000, u64(8) + u64(0xDEAD0000) + u64(3))
    got = _vec()(mem, 0x2000, ReadCtx(layout=VEC_LAYOUT))
    assert len(got) == 3 and all(isinstance(e, Unavailable) for e in got), got


def test_vec_null_pointer_is_not_an_empty_vec():
    mem = DictMemory().write(0x2000, u64(0) + u64(0) + u64(0))
    got = _vec()(mem, 0x2000, ReadCtx(layout=VEC_LAYOUT))
    assert isinstance(got, Unavailable), got
    assert "0" in got.reason


def test_vec_len_over_cap_rejected():
    got = _vec()(_vec_mem(cap=2, ln=9999), 0x2000, ReadCtx(layout=VEC_LAYOUT))
    assert isinstance(got, Unavailable) and "cap" in got.reason


def test_vec_genuinely_empty():
    mem = DictMemory().write(0x2000, u64(0) + u64(4) + u64(0))
    assert _vec()(mem, 0x2000, ReadCtx(layout=VEC_LAYOUT)) == []


def test_vec_missing_offset_names_the_field():
    lay = {"Vec<u32>": {"buf": 0, "len": 16},
           "RawVec<u32>": {"ptr": 8}}
    got = _vec()(_vec_mem(), 0x2000, ReadCtx(layout=lay))
    assert isinstance(got, Unavailable) and "cap" in got.reason, got


def test_vec_without_raw_type_explains_why():
    lay = {"Vec<u32>": {"buf": 0, "len": 16},
           "RawVec<u32>": {"cap": 0, "ptr": 8}}
    got = C.vec("Vec<u32>", 4, read_u32)(_vec_mem(), 0x2000,
                                         ReadCtx(layout=lay))
    assert isinstance(got, Unavailable), got
    assert "RawVec" in got.reason and "raw_type" in got.reason, got


def test_vec_truncation_is_visible():
    mem = _vec_mem(cap=16, ln=10, elems=tuple(range(10)))
    got = _vec()(mem, 0x2000, ReadCtx(layout=VEC_LAYOUT, max_items=4))
    assert got[:4] == [0, 1, 2, 3], got
    assert isinstance(C.incomplete_of(got), C.Truncated)


# =================================================================== VecDeque
#     VecDeque  size 32  { buf: 0, head: 16, len: 24 }
#     RawVec    size 16  { cap: 0, ptr: 8, alloc: 16 }

DEQ_LAYOUT = {
    "VecDeque<u32>": {"buf": 0, "head": 16, "len": 24},
    "RawVec<u32>": {"cap": 0, "ptr": 8, "alloc": 16},
}


def _deq(**kw):
    kw.setdefault("raw_type", "RawVec<u32>")
    return C.vecdeque("VecDeque<u32>", kw.pop("elem_size", 4), read_u32, **kw)


def _deq_mem(*, ptr=0x3000, cap=8, head=0, ln=3, at=0x2000, ring=None):
    mem = DictMemory().write(at, u64(cap) + u64(ptr) + u64(head) + u64(ln))
    slots = list(ring if ring is not None else range(cap))
    mem.write(ptr, b"".join(u32(v) for v in slots))
    return mem


def test_vecdeque_reads_in_queue_order_not_slot_order():
    mem = _deq_mem(cap=8, head=6, ln=5, ring=range(8))
    assert _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT)) == [6, 7, 0, 1, 2]


def test_vecdeque_without_wrap_is_still_offset_by_head():
    mem = _deq_mem(cap=8, head=3, ln=3, ring=range(8))
    assert _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT)) == [3, 4, 5]


def test_vecdeque_empty_with_zero_cap_does_not_divide_by_zero():
    mem = DictMemory().write(0x2000, u64(0) + u64(4) + u64(0) + u64(0))
    assert _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT)) == []


def test_vecdeque_head_outside_the_ring_is_refused():
    mem = _deq_mem(cap=8, head=9, ln=2, ring=range(8))
    got = _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT))
    assert isinstance(got, Unavailable) and not is_ok(got)
    assert "head" in got.reason and "cap" in got.reason, got.reason


def test_vecdeque_len_greater_than_cap_is_refused():
    mem = _deq_mem(cap=2, head=0, ln=9999, ring=range(2))
    got = _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT))
    assert isinstance(got, Unavailable) and not is_ok(got)


def test_vecdeque_null_pointer_is_not_an_empty_deque():
    mem = DictMemory().write(0x2000, u64(8) + u64(0) + u64(0) + u64(0))
    got = _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT))
    assert isinstance(got, Unavailable) and not is_ok(got)


def test_vecdeque_missing_head_offset_is_named():
    lay = {"VecDeque<u32>": {"buf": 0, "head": 16, "tail": 24},
           "RawVec<u32>": {"cap": 0, "ptr": 8}}
    got = _deq()(_deq_mem(), 0x2000, ReadCtx(layout=lay))
    assert isinstance(got, Unavailable)
    assert "len" in got.reason, got.reason


def test_vecdeque_truncation_points_at_the_next_ring_slot():
    mem = _deq_mem(cap=8, head=6, ln=5, ring=range(8))
    got = _deq()(mem, 0x2000, ReadCtx(layout=DEQ_LAYOUT, max_items=3))
    assert got[:3] == [6, 7, 0], got
    tail = C.incomplete_of(got)
    assert isinstance(tail, C.Truncated)
    assert tail.addr == 0x3000 + 1 * 4, tail.addr      # (6+3) % 8 == 1


def test_vecdeque_explicit_offsets_bypass_ctx():
    r = C.vecdeque("VecDeque<u32>", 4, read_u32,
                   offsets={"cap": 0, "ptr": 8, "head": 16, "len": 24})
    mem = _deq_mem(cap=8, head=6, ln=3, ring=range(8))
    assert r(mem, 0x2000, ReadCtx()) == [6, 7, 0]



def _null_list_mem(last_next=0):
    mem = DictMemory().write(0x100, u64(0x1000))
    for at, ident, nxt in ((0x1000, 1, 0x1100),
                           (0x1100, 2, 0x1200),
                           (0x1200, 3, last_next)):
        mem.write(at, u32(ident) + u32(0) + u64(nxt))
    return mem


def _circular_list_mem():
    mem = DictMemory().write(0x200, u64(0x1010))          # head.next -> e1.link
    for at, ident, nxt in ((0x1000, 1, 0x1110),
                           (0x1100, 2, 0x1210),
                           (0x1200, 3, 0x200)):
        buf = bytearray(32)
        buf[0:4] = u32(ident)
        buf[16:24] = u64(nxt)
        mem.write(at, bytes(buf))
    return mem


def test_list_null_terminated():
    got = C.list(0, 8, read_u32)(_null_list_mem(), 0x100, ReadCtx())
    assert got == [1, 2, 3], got
    assert C.incomplete_of(got) is None


def test_list_circular_terminates():
    r = C.list(16, 0, read_u32, terminator=C.Circular())
    got = r(_circular_list_mem(), 0x200, ReadCtx())
    assert got == [1, 2, 3], got
    assert C.incomplete_of(got) is None


def test_list_cycle_is_reported_not_swallowed():
    got = C.list(0, 8, read_u32)(_null_list_mem(last_next=0x1000), 0x100,
                                 ReadCtx())
    assert got[:3] == [1, 2, 3], got
    c = C.incomplete_of(got)
    assert isinstance(c, C.Cycle), got
    assert c.addr == 0x1000


def test_list_truncation_is_visible():
    got = C.list(0, 8, read_u32)(_null_list_mem(), 0x100, ReadCtx(max_items=2))
    assert got[:2] == [1, 2], got
    assert isinstance(C.incomplete_of(got), C.Truncated)
    assert len(got) == 3


def test_list_empty_null_terminated():
    mem = DictMemory().write(0x100, u64(0))
    assert C.list(0, 8, read_u32)(mem, 0x100, ReadCtx()) == []


def test_list_empty_circular():
    mem = DictMemory().write(0x200, u64(0x200))            # head.next == head
    r = C.list(16, 0, read_u32, terminator=C.Circular())
    assert r(mem, 0x200, ReadCtx()) == []


def test_list_head_unreadable_is_unavailable():
    got = C.list(0, 8, read_u32)(DictMemory(), 0x100, ReadCtx())
    assert isinstance(got, Unavailable) and not is_ok(got)


def test_list_broken_next_pointer():
    mem = DictMemory().write(0x100, u64(0x1000))
    mem.write(0x1000, u32(1) + u32(0) + u64(0x1100))
    mem.write(0x1100, u32(2) + u32(0))
    got = C.list(0, 8, read_u32)(mem, 0x100, ReadCtx())
    assert got[:2] == [1, 2], got
    assert isinstance(C.incomplete_of(got), C.Broken), got


def test_list_rejects_unknown_terminator():
    got = C.list(0, 8, read_u32, terminator=object())(
        _null_list_mem(), 0x100, ReadCtx())
    assert isinstance(got, Unavailable) and "终止规则" in got.reason


# =============================================================== BTreeMap

BT_LAYOUT = {"BTreeMap<u32,u32>": {"root": 0, "length": 16}}

#:   parent(8) @0 | parent_idx u16 @8 | len u16 @10 | keys[11] @12 | vals[11] @56
BT_NODE = C.BTreeNodeLayout(noderef_height=8, noderef_node=0,
                            len=10, keys=12, vals=56,
                            key_size=4, val_size=4, edges=104)


def _leaf(keys, vals) -> bytes:
    b = bytearray(104)
    b[10:12] = u16(len(keys))
    for i, k in enumerate(keys):
        b[12 + 4 * i:16 + 4 * i] = u32(k)
    for i, v in enumerate(vals):
        b[56 + 4 * i:60 + 4 * i] = u32(v)
    return bytes(b)


def _internal(keys, vals, edges) -> bytes:
    b = bytearray(_leaf(keys, vals)) + bytearray(96)       # edges[12] @104
    for i, e in enumerate(edges):
        b[104 + 8 * i:112 + 8 * i] = u64(e)
    return bytes(b)


def _map_head(root: int, height: int, length: int) -> bytes:
    return u64(root) + u64(height) + u64(length)


def _bt(*, node=BT_NODE):
    return C.btreemap("BTreeMap<u32,u32>", read_u32, read_u32, node=node)


def test_btreemap_empty_needs_no_node_layout():
    mem = DictMemory().write(0x1000, _map_head(0, 0, 0))
    for node in (BT_NODE, None):
        got = _bt(node=node)(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
        assert got == [], (node, got)


def test_btreemap_without_node_layout_still_reports_length():
    mem = DictMemory().write(0x1000, _map_head(0x2000, 0, 3))
    got = _bt(node=None)(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    assert isinstance(got, Unavailable), got
    assert "3 项" in got.reason and "LeafNode" in got.reason


def test_btreemap_leaf_only():
    mem = (DictMemory().write(0x1000, _map_head(0x2000, 0, 3))
                       .write(0x2000, _leaf([10, 20, 30], [100, 200, 300])))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    assert got == [[10, 100], [20, 200], [30, 300]], got
    assert C.incomplete_of(got) is None


def test_btreemap_internal_node_in_order():
    mem = (DictMemory()
           .write(0x1000, _map_head(0x3000, 1, 5))
           .write(0x3000, _internal([50], [500], [0x2000, 0x4000]))
           .write(0x2000, _leaf([10, 20], [100, 200]))
           .write(0x4000, _leaf([70, 80], [700, 800])))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    assert got == [[10, 100], [20, 200], [50, 500],
                   [70, 700], [80, 800]], got


def test_btreemap_internal_without_edges_offset_refuses():
    node = C.BTreeNodeLayout(noderef_height=8, noderef_node=0, len=10,
                             keys=12, vals=56, key_size=4, val_size=4)
    mem = (DictMemory()
           .write(0x1000, _map_head(0x3000, 1, 5))
           .write(0x3000, _internal([50], [500], [0x2000, 0x4000])))
    got = _bt(node=node)(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    b = C.incomplete_of(got)
    assert isinstance(b, C.Broken) and "edges" in b.reason, got


def test_btreemap_len_over_capacity_rejected():
    buf = bytearray(_leaf([1], [2]))
    buf[10:12] = u16(99)
    mem = (DictMemory().write(0x1000, _map_head(0x2000, 0, 99))
                       .write(0x2000, bytes(buf)))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    b = C.incomplete_of(got)
    assert isinstance(b, C.Broken) and str(C.BTREE_CAPACITY) in b.reason, got


def test_btreemap_length_mismatch_is_reported():
    mem = (DictMemory().write(0x1000, _map_head(0x2000, 0, 7))
                       .write(0x2000, _leaf([10, 20], [100, 200])))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    b = C.incomplete_of(got)
    assert isinstance(b, C.Broken) and "7" in b.reason, got


def test_btreemap_root_none_but_nonzero_length():
    mem = DictMemory().write(0x1000, _map_head(0, 0, 4))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    assert isinstance(got, Unavailable) and "length=4" in got.reason, got


def test_btreemap_cycle_is_reported():
    mem = (DictMemory()
           .write(0x1000, _map_head(0x3000, 1, 2))
           .write(0x3000, _internal([50], [500], [0x3000, 0x3000])))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    assert isinstance(C.incomplete_of(got), C.Cycle), got


def test_btreemap_node_budget_stops_leafless_tree():
    mem = DictMemory().write(0x1000, _map_head(0x3000, 4, 1))
    for i, at in enumerate((0x3000, 0x4000, 0x5000, 0x6000)):
        nxt = at + 0x1000
        mem.write(at, _internal([1], [2], [nxt, nxt]))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT, max_items=2))
    assert isinstance(C.incomplete_of(got), C.Truncated), got


def test_btreemap_absurd_height_rejected():
    mem = DictMemory().write(0x1000, _map_head(0x2000, 1 << 40, 3))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT))
    assert isinstance(got, Unavailable) and "height" in got.reason, got


def test_btreemap_missing_map_offsets():
    mem = DictMemory().write(0x1000, _map_head(0x2000, 0, 3))
    got = _bt()(mem, 0x1000, ReadCtx(layout={"BTreeMap<u32,u32>": {"root": 0}}))
    assert isinstance(got, Unavailable) and "length" in got.reason, got


def test_btreemap_truncation_is_visible():
    mem = (DictMemory().write(0x1000, _map_head(0x2000, 0, 5))
                       .write(0x2000, _leaf([1, 2, 3, 4, 5],
                                            [10, 20, 30, 40, 50])))
    got = _bt()(mem, 0x1000, ReadCtx(layout=BT_LAYOUT, max_items=2))
    assert got[:2] == [[1, 10], [2, 20]], got
    assert isinstance(C.incomplete_of(got), C.Truncated)


# =============================================================== strongmap

SM_NODE = C.BTreeNodeLayout(noderef_height=8, noderef_node=0,
                            len=10, keys=12, vals=56,
                            key_size=4, val_size=8)
SM_LAYOUT = {"BTreeMap<u32,Arc<Thing>>": {"root": 0, "length": 16},
             "ArcInner<Thing>": {"data": 16}}


def _arc_leaf(keys, ptrs) -> bytes:
    b = bytearray(144)
    b[10:12] = u16(len(keys))
    for i, k in enumerate(keys):
        b[12 + 4 * i:16 + 4 * i] = u32(k)
    for i, p in enumerate(ptrs):
        b[56 + 8 * i:64 + 8 * i] = u64(p)
    return bytes(b)


def _strongmap(value=read_u32):
    return C.strongmap(
        lambda v: C.btreemap("BTreeMap<u32,Arc<Thing>>", read_u32, v,
                             node=SM_NODE),
        arcinner_type="ArcInner<Thing>", value=value)


def test_strongmap_hops_through_arc():
    mem = (DictMemory()
           .write(0x1000, _map_head(0x2000, 0, 2))
           .write(0x2000, _arc_leaf([7, 9], [0x5000, 0x6000]))
           .write(0x5010, u32(777))
           .write(0x6010, u32(999)))
    got = _strongmap()(mem, 0x1000, ReadCtx(layout=SM_LAYOUT))
    assert got == [[7, 777], [9, 999]], got


def test_strongmap_missing_arcinner_offset():
    mem = (DictMemory()
           .write(0x1000, _map_head(0x2000, 0, 1))
           .write(0x2000, _arc_leaf([7], [0x5000]))
           .write(0x5010, u32(777)))
    lay = {"BTreeMap<u32,Arc<Thing>>": {"root": 0, "length": 16}}
    got = _strongmap()(mem, 0x1000, ReadCtx(layout=lay))
    assert len(got) == 1 and isinstance(got[0][1], Unavailable), got
    assert "ArcInner" in got[0][1].reason


def test_strongmap_accepts_an_injected_hop():
    mem = (DictMemory()
           .write(0x1000, _map_head(0x2000, 0, 1))
           .write(0x2000, _arc_leaf([7], [0x5000]))
           .write(0x5010, u32(777)))

    def my_hop(m, addr, ctx):
        p = m.u64(addr)
        return Unavailable("读不到", addr) if p is None else read_u32(m, p + 16, ctx)

    r = C.strongmap(lambda v: C.btreemap("BTreeMap<u32,Arc<Thing>>",
                                         read_u32, v, node=SM_NODE),
                    hop=my_hop)
    assert r(mem, 0x1000, ReadCtx(layout=SM_LAYOUT)) == [[7, 777]], r


def test_strongmap_refuses_half_wired_construction():
    try:
        C.strongmap(lambda v: None)
    except ValueError as e:
        assert "hop" in str(e)
    else:
        raise AssertionError("缺 arcinner_type/value 时没有报错")


def test_strongmap_null_arc_is_not_a_value():
    mem = (DictMemory()
           .write(0x1000, _map_head(0x2000, 0, 1))
           .write(0x2000, _arc_leaf([7], [0])))
    got = _strongmap()(mem, 0x1000, ReadCtx(layout=SM_LAYOUT))
    assert isinstance(got[0][1], Unavailable) and "NonNull" in got[0][1].reason



def test_incomplete_is_never_mistaken_for_data():
    for cls in (C.Incomplete, C.Truncated, C.Cycle, C.Broken):
        v = cls("测试", 0x10)
        assert isinstance(v, Unavailable) and not is_ok(v) and not v
        assert "0x10" in str(v)


def test_unknown_pointer_width_is_distinct_from_unreadable():
    got = _vec()(_vec_mem(), 0x2000,
                 ReadCtx(layout=VEC_LAYOUT, ptr_size=3))
    assert isinstance(got, Unavailable) and "指针宽度" in got.reason, got


def test_zero_max_items_truncates_rather_than_lying():
    got = _vec()(_vec_mem(), 0x2000,
                 ReadCtx(layout=VEC_LAYOUT, max_items=0))
    assert isinstance(C.incomplete_of(got), C.Truncated), got



def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    fails = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            fails.append((name, f"断言失败：{e}"))
            print(f"  FAIL {name}")
        except Exception as e:                       # noqa: BLE001
            fails.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERR  {name}")
        else:
            print(f"  OK   {name}")
    print()
    if fails:
        print(f"!! {len(fails)}/{len(tests)} 失败:")
        for n, why in fails:
            print(f"   {n}: {why}")
        return 1
    print(f"全部通过（{len(tests)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_vec_elem_size_zero_is_pointer_width_not_illegal():
    mem = DictMemory().write(0x2000, u64(4) + u64(0x3000) + u64(3))
    mem.write(0x3000, u64(0xAA) + u64(0xBB) + u64(0xCC))
    ctx = ReadCtx(layout={"Vec<u64>": {"buf": 0, "len": 16},
                          "RawVec<u64>": {"cap": 0, "ptr": 8}})
    r = C.vec("Vec<u64>", 0, read_u64, raw_type="RawVec<u64>")
    assert r(mem, 0x2000, ctx) == [0xAA, 0xBB, 0xCC]


def test_vec_elem_size_zero_uses_the_ctx_width_not_a_hardcoded_eight():
    mem = DictMemory().write(0x2000, u64(4) + u64(0x3000) + u64(3))
    mem.write(0x3000, u32(1) + u32(2) + u32(3) + u32(4))
    ctx = ReadCtx(layout={"Vec<u32>": {"buf": 0, "len": 16},
                          "RawVec<u32>": {"cap": 0, "ptr": 8}}, ptr_size=4)
    r = C.vec("Vec<u32>", 0, read_u32, raw_type="RawVec<u32>")
    assert r(mem, 0x2000, ctx) == [1, 2, 3]


def test_vec_negative_elem_size_still_rejected():
    ctx = ReadCtx(layout=VEC_LAYOUT)
    v = _vec(elem_size=-4)(_vec_mem(), 0x2000, ctx)
    assert isinstance(v, Unavailable) and "不合法" in v.reason


# =============================================================== String

#:     String            { vec: 0 }
#:     Vec<u8, Global>   { buf: 0, len: 16 }
STR_LAYOUT = {
    "String": {"vec": 0},
    "Vec<u8>": {"buf": 0, "len": 16},
    "RawVec<u8>": {"cap": 0, "ptr": 8},
}
STR_CTX = ReadCtx(layout=STR_LAYOUT)
STR_AT = 0x1000
STR_DATA = 0x2000


def _string_reader(**kw):
    return C.string("Vec<u8>", str_type="String", raw_type="RawVec<u8>", **kw)


def _string_mem(body: bytes, *, cap: int | None = None,
                ptr: int = STR_DATA, ln: int | None = None):
    n = len(body) if ln is None else ln
    c = n if cap is None else cap
    mem = DictMemory().write(STR_AT, u64(c) + u64(ptr) + u64(n))
    if body:
        mem.write(STR_DATA, body)
    return mem


def test_string_reads_utf8_through_the_vec_hop():
    mem = _string_mem("初始化 init".encode())
    assert _string_reader()(mem, STR_AT, STR_CTX) == "初始化 init"


def test_string_with_len_zero_is_a_real_empty_string():
    mem = _string_mem(b"", cap=8, ptr=STR_DATA)
    assert _string_reader()(mem, STR_AT, STR_CTX) == ""


def test_string_with_null_ptr_is_refused_not_reported_empty():
    mem = _string_mem(b"abc", ptr=0)
    got = _string_reader()(mem, STR_AT, STR_CTX)
    assert isinstance(got, Unavailable) and not is_ok(got)
    assert "ptr" in got.reason


def test_string_with_len_over_cap_is_refused():
    mem = _string_mem(b"abc", cap=2, ln=3)
    got = _string_reader()(mem, STR_AT, STR_CTX)
    assert isinstance(got, Unavailable)
    assert "cap" in got.reason


def test_string_longer_than_max_bytes_is_refused_with_the_length_quoted():
    mem = _string_mem(b"", cap=1 << 20, ptr=STR_DATA, ln=1 << 20)
    got = _string_reader(max_bytes=64)(mem, STR_AT, STR_CTX)
    assert isinstance(got, Unavailable)
    assert str(1 << 20) in got.reason and "64" in got.reason


def test_string_with_invalid_utf8_is_refused_not_replaced():
    mem = _string_mem(b"ok\xff\xfe")
    got = _string_reader()(mem, STR_AT, STR_CTX)
    assert isinstance(got, Unavailable)
    assert "utf-8" in got.reason.lower()
    assert "�" not in got.reason


def test_string_without_the_vec_offset_says_which_field_is_missing():
    ctx = ReadCtx(layout={k: v for k, v in STR_LAYOUT.items() if k != "String"})
    got = _string_reader()(_string_mem(b"abc"), STR_AT, ctx)
    assert isinstance(got, Unavailable)
    assert "vec" in got.reason and "String" in got.reason


def test_string_bytes_outside_observed_memory_are_refused():
    mem = DictMemory().write(STR_AT, u64(4) + u64(STR_DATA) + u64(4))
    got = _string_reader()(mem, STR_AT, STR_CTX)
    assert isinstance(got, Unavailable)


def test_string_pointed_straight_at_the_vec_skips_the_hop():
    mem = _string_mem(b"hi")
    r = C.string("Vec<u8>", raw_type="RawVec<u8>")
    assert r(mem, STR_AT, STR_CTX) == "hi"
