
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.exec import Executor                # noqa: E402
from nodefusion.model.plan import Op, Plan                # noqa: E402
from nodefusion.model.rt import DictMemory, ReadCtx       # noqa: E402


def u64(v: int) -> bytes:
    return int.to_bytes(v, 8, "little")


def u16(v: int) -> bytes:
    return int.to_bytes(v, 2, "little")


MAP = 0x8020_0000
LEAF = 0x8021_0000

NODE_OPTS = {
    "btree_noderef_height": 8, "btree_noderef_node": 0,
    "btree_len": 186, "btree_keys": 8, "btree_vals": 96,
    "btree_key_size": 8, "btree_val_size": 8, "btree_edges": 192,
}

LAYOUT = {"BTreeMap<u64, T, Global>": {"root": 0, "length": 16}}

VAL0, VAL1 = LEAF + 96, LEAF + 104


def _mem(n: int = 2, length: int | None = None) -> DictMemory:
    length = n if length is None else length
    m = DictMemory()
    m.write(MAP, u64(LEAF) + u64(0) + u64(length))  # root.node/root.height/length
    m.write(LEAF + 8, u64(7) + u64(9))             # keys[0..2]
    m.write(LEAF + 96, u64(0xAA) + u64(0xBB))
    m.write(LEAF + 186, u16(n))
    return m


def _run(mem, **extra):
    p = Plan("vm")
    p.ops = [Op("load_static", {"name": "VMS", "addr": MAP}),
             Op("iter", {"container": "btreemap", "key": "u64",
                         "btree_map_type": "BTreeMap<u64, T, Global>",
                         **NODE_OPTS, **extra})]
    p.compiled = True
    return Executor(mem, ReadCtx(layout=LAYOUT)).run(p)


def test_iter_btreemap_walks_out_the_values_not_the_pairs():
    w = _run(_mem())
    assert [n.addr for n in w.nodes] == [VAL0, VAL1], w.problems
    assert not w.problems, w.problems


def test_iter_btreemap_keeps_the_key_in_the_step_label():
    w = _run(_mem())
    tail = [n.path.split("/")[-1] if hasattr(n, "path") else str(n)
            for n in w.nodes]
    assert any("7" in t for t in tail), tail
    assert any("9" in t for t in tail), tail


def test_iter_btreemap_empty_map_is_empty_not_broken():
    m = DictMemory()
    m.write(MAP, u64(0) + u64(0) + u64(0))
    w = _run(m)
    assert w.nodes == []
    assert not w.problems, w.problems


def test_iter_btreemap_without_a_key_reader_refuses():
    p = Plan("vm")
    p.ops = [Op("load_static", {"name": "VMS", "addr": MAP}),
             Op("iter", {"container": "btreemap",
                         "btree_map_type": "BTreeMap<u64, T, Global>",
                         **NODE_OPTS})]
    p.compiled = True
    w = Executor(_mem(), ReadCtx(layout=LAYOUT)).run(p)
    assert w.nodes == []
    assert any("key" in str(x.reason) for x in w.problems), w.problems


def test_iter_btreemap_length_mismatch_is_reported_not_swallowed():
    assert not _run(_mem(n=2)).problems
    w = _run(_mem(n=2, length=5))
    assert w.problems, "length 对不上却一声不吭"
    assert any("5" in str(x.reason) for x in w.problems), w.problems
    assert [n.addr for n in w.nodes] == [VAL0, VAL1]


def test_iter_reports_items_that_are_not_addresses_instead_of_dropping_them():
    class Weird:

        def __call__(self, mem, addr, ctx):
            return ["not-an-address", "me-neither"]

    p = Plan("vm")
    p.ops = [Op("load_static", {"name": "VMS", "addr": MAP}),
             Op("iter", {"container": "weird"})]
    p.compiled = True
    w = Executor(_mem(), ReadCtx(layout=LAYOUT),
                 readers={"weird": Weird()}).run(p)
    assert w.nodes == []
    assert len(w.problems) == 2, w.problems
    assert "str" in str(w.problems[0].reason), w.problems[0]
