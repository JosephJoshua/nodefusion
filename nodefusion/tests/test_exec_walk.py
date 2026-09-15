
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.exec import Executor                # noqa: E402
from nodefusion.model.plan import Op, Plan                # noqa: E402
from nodefusion.model.rt import DictMemory, ReadCtx       # noqa: E402


def u64(v: int) -> bytes:
    return int.to_bytes(v, 8, "little")


ROOT = 0x8020_0000
HEAP = 0x8030_0000

ARC_DATA = 16
ARC1, ARC2 = 0x8021_0000, 0x8021_1000
KID1, KID2 = ARC1 + ARC_DATA, ARC2 + ARC_DATA

EDGE = 0x40
LAYOUT = {
    "Vec<Arc<T>>": {"buf": 0, "len": 16},
    "RawVec<Arc<T>>": {"cap": 0, "ptr": 8},
}


def _mem() -> DictMemory:
    m = DictMemory()
    m.write(ROOT + EDGE, u64(2) + u64(HEAP) + u64(2))
    m.write(HEAP, u64(ARC1) + u64(ARC2))
    for arc, kid in ((ARC1, KID1), (ARC2, KID2)):
        m.write(arc, u64(1) + u64(1))                      # strong / weak
        m.write(kid + EDGE, u64(0) + u64(HEAP) + u64(0))
    return m


def _walk_plan(**extra) -> Plan:
    p = Plan("task")
    p.ops = [
        Op("load_static", {"name": "INITPROC", "addr": ROOT}),
        Op("walk", {"edge": {"children": "inner.children",
                             "via": ["UPSafeCell", "Vec", "Arc"]},
                    "edge_offset": EDGE, **extra}),
    ]
    return p


def _run(plan: Plan):
    ctx = ReadCtx(layout=LAYOUT)
    return Executor(_mem(), ctx).run(plan)


def test_walk_expands_the_whole_list_without_any_registered_reader():
    w = _run(_walk_plan(reader="vec<arc>",
                        vec_type="Vec<Arc<T>>", raw_type="RawVec<Arc<T>>"))
    assert [n.addr for n in w.nodes] == [ROOT, KID1, KID2], w.problems
    assert w.ok, w.problems


def test_walk_falls_back_to_composing_via_when_the_plan_is_old():
    w = _run(_walk_plan(vec_type="Vec<Arc<T>>", raw_type="RawVec<Arc<T>>"))
    assert [n.addr for n in w.nodes] == [ROOT, KID1, KID2], w.problems


def test_walk_reader_failure_is_reported_not_swallowed():
    w = _run(_walk_plan(reader="vec<arc>"))
    assert [n.addr for n in w.nodes] == [ROOT]
    assert not w.ok
    assert any("vec" in p.reason for p in w.problems), w.problems


def test_walk_missing_offset_is_reported_once_not_per_node():
    p = Plan("task")
    p.ops = [
        Op("load_static", {"name": "INITPROC", "addr": ROOT}),
        Op("walk", {"edge": {"children": "inner.children",
                             "via": ["UPSafeCell", "Vec", "Arc"]},
                    "reader": "vec<arc>", "vec_type": "Vec<Arc<T>>",
                    "raw_type": "RawVec<Arc<T>>"}),
    ]
    w = _run(p)
    assert len(w.problems) == 1, w.problems
    assert "inner.children" in w.problems[0].reason


def test_walk_prefers_the_compile_time_offset_over_the_probe_table():
    ctx = ReadCtx(layout={**LAYOUT, "__edges__": {"inner.children": 0x999}})
    w = Executor(_mem(), ctx).run(
        _walk_plan(reader="vec<arc>", vec_type="Vec<Arc<T>>",
                   raw_type="RawVec<Arc<T>>"))
    assert [n.addr for n in w.nodes] == [ROOT, KID1, KID2], w.problems


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_walk_over_a_map_follows_the_value_and_keeps_the_key():
    class FakeMap:

        def __init__(self) -> None:
            self.seen: set[int] = set()

        def __call__(self, mem, addr, ctx):
            if addr in self.seen:
                return []
            self.seen.add(addr)
            return [[7, KID1]]

    p = Plan("task")
    p.ops = [
        Op("load_static", {"name": "INITPROC", "addr": ROOT}),
        Op("walk", {"edge": {"children": "children"},
                    "edge_offset": EDGE, "reader": "fakemap"}),
    ]
    w = Executor(_mem(), ReadCtx(layout=LAYOUT),
                 readers={"fakemap": FakeMap()}).run(p)
    assert [n.addr for n in w.nodes] == [ROOT, KID1], w.problems
    assert w.ok, w.problems
    kid = [n for n in w.nodes if n.addr == KID1][0]
    assert any("children[7]" in s for s in kid.trail), kid.trail


def test_walk_reports_a_child_that_is_not_an_address():
    class Junk:
        def __call__(self, mem, addr, ctx):
            return ["not-an-address"]

    p = Plan("task")
    p.ops = [
        Op("load_static", {"name": "INITPROC", "addr": ROOT}),
        Op("walk", {"edge": {"children": "children"},
                    "edge_offset": EDGE, "reader": "junk"}),
    ]
    w = Executor(_mem(), ReadCtx(layout=LAYOUT),
                 readers={"junk": Junk()}).run(p)
    assert [n.addr for n in w.nodes] == [ROOT]
    assert not w.ok
    assert any("str" in str(pr.reason) for pr in w.problems), w.problems
