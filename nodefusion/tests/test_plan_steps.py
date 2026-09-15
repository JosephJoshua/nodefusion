
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.layout import StructLayout       # noqa: E402
from nodefusion.model.manifest import SourceSpec       # noqa: E402
from nodefusion.model.plan import compile_source       # noqa: E402

ANON, BUF, ARR, SPIN, PBUF = 10, 20, 30, 40, 50

BCACHE_ADDR = 0x8023_BCE8


class FakeVar:
    def __init__(self, name, addr, type_off):
        self.name = self.path = name
        self.addr, self.type_off = addr, type_off


class FakeDw:

    def __init__(self):
        self._structs = {
            ANON: StructLayout(
                name="", path="", size=101216,
                fields={"lock": 0, "buf": 24, "head": 100104},
                field_types={"lock": SPIN, "buf": ARR, "head": BUF}),
            BUF: StructLayout(
                name="buf", path="buf", size=1112,
                fields={"valid": 0, "disk": 4, "dev": 8, "blockno": 12,
                        "refcnt": 64}),
            SPIN: StructLayout(name="spinlock", path="spinlock", size=24,
                               fields={"locked": 0}),
        }
        self._names = {BUF: "buf", ARR: "[buf; 90]", SPIN: "spinlock",
                       PBUF: "*buf"}

    def struct_at(self, off):
        return self._structs.get(off)

    def type_name(self, off):
        return self._names.get(off)

    def find(self, name):
        return next((s for s in self._structs.values()
                     if s.path == name or s.name == name), None)

    def var(self, name):
        return FakeVar(name, BCACHE_ADDR, ANON) if name == "bcache" else None

    def var_at(self, _addr):
        return None

    def array_of(self, off):
        return (BUF, 90) if off == ARR else None

    def size_of(self, off):
        s = self._structs.get(off)
        return s.size if s else None

    def pointee(self, off):
        return BUF if off == PBUF else None


def _plan(steps, *, struct_path="buf"):
    return compile_source(FakeDw(), "bcache",
                          SourceSpec(kind="table", completeness="total",
                                     steps=steps),
                          struct_path=struct_path)


def test_explicit_none_source_compiles_to_an_empty_plan():
    src = SourceSpec(kind="batch", completeness="none", steps=[])
    p = compile_source(FakeDw(), "task", src)
    assert p.compiled and p.ops == []


def test_an_accidentally_empty_normal_source_is_still_rejected():
    src = SourceSpec(kind="table", completeness="total", steps=[])
    p = compile_source(FakeDw(), "task", src)
    assert not p.compiled and "没有 steps" in p.reason


def test_iter_via_keeps_element_pointer_shells():
    p = _plan([{"static": "bcache"}, {"field": "head"},
               {"iter": "vec", "via": ["Vec", "Option", "Arc"]}])
    assert p.compiled, p.reason
    assert p.ops[-1].args["container"] == "vec<option<arc>>"


def test_iter_rejects_a_via_for_a_different_container():
    p = _plan([{"static": "bcache"}, {"field": "head"},
               {"iter": "vec", "via": ["VecDeque", "Arc"]}])
    assert not p.compiled and "必须一致" in p.reason



def test_field_resolves_inside_an_anonymous_struct():
    p = _plan([{"static": "bcache"}, {"field": "buf"}, {"iter": "array"}])
    assert p.compiled, p.reason
    kinds = [o.kind for o in p.ops]
    assert "field_dyn" not in kinds, (
        f"退成运行期解析了：{p.trace}。运行期没有类型信息，这条 source 会走出"
        f"0 个实体，而且不报错")
    assert p.ops[1].kind == "offset" and p.ops[1].args["n"] == 24, p.ops[1]


def test_array_bound_and_element_size_come_from_dwarf():
    p = _plan([{"static": "bcache"}, {"field": "buf"}, {"iter": "array"}])
    it = p.ops[-1]
    assert it.kind == "iter"
    assert it.args["count"] == 90 and it.args["elem_size"] == 1112, it.args
    assert it.args["elem_type"] == "buf", it.args


def test_field_is_not_looked_up_in_the_entity_type():
    p = _plan([{"static": "bcache"}, {"field": "buf"}, {"iter": "array"}],
              struct_path="buf")
    assert p.ops[1].args["n"] == 24


def test_entity_type_is_still_the_fallback():
    p = _plan([{"field": "refcnt"}], struct_path="buf")
    assert p.compiled, p.reason
    assert p.ops[0].kind == "offset" and p.ops[0].args["n"] == 64, p.ops[0]



def test_deref_moves_the_cursor_to_the_pointee():
    p = _plan([{"static": "bcache"}, {"field": "head"}])
    assert p.ops[-1].args["n"] == 100104

    p2 = _plan([{"static": "bcache"}, {"field": "head"}, {"field": "refcnt"}])
    assert p2.ops[-1].kind == "offset" and p2.ops[-1].args["n"] == 64, p2.trace


def test_unwrap_does_not_leave_a_stale_die_behind():
    p = _plan([{"static": "bcache"}, {"unwrap": ["Lazy"]}, {"iter": "array"}])
    it = p.ops[-1]
    assert it.kind == "iter"
    assert "count" not in it.args, (
        f"unwrap 之后还拿得到数组上界，说明 cur_off 是过期的：{it.args}")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))



A_ARC, A_NN, A_PTR, A_INNER, A_MUTEX, A_ATOMIC = 60, 61, 62, 63, 64, 65

ARC_NAME = ("alloc::sync::Arc<spin::mutex::Mutex<easy_fs::block_cache::"
            "BlockCache>, alloc::alloc::Global>")
MUTEX_NAME = "spin::mutex::Mutex<easy_fs::block_cache::BlockCache>"


class ArcDw:

    def __init__(self):
        self._structs = {
            A_ARC: StructLayout(
                name="Arc<Mutex<BlockCache>, Global>", path=ARC_NAME, size=8,
                fields={"ptr": 0, "phantom": 8, "alloc": 8},
                field_types={"ptr": A_NN, "phantom": A_ATOMIC,
                             "alloc": A_ATOMIC}),
            A_NN: StructLayout(name="NonNull<ArcInner<…>>",
                               path="core::ptr::non_null::NonNull<…>", size=8,
                               fields={"pointer": 0},
                               field_types={"pointer": A_PTR}),
            A_INNER: StructLayout(
                name="ArcInner<Mutex<BlockCache>>",
                path="alloc::sync::ArcInner<…>", size=576,
                fields={"strong": 0, "weak": 8, "data": 16},
                field_types={"strong": A_ATOMIC, "weak": A_ATOMIC,
                             "data": A_MUTEX}),
            A_MUTEX: StructLayout(name="Mutex<BlockCache>", path=MUTEX_NAME,
                                  size=560, fields={"inner": 0}),
            A_ATOMIC: StructLayout(name="AtomicUsize", path="core::AtomicUsize",
                                   size=8, fields={"v": 0}),
        }

    def struct_at(self, off):
        return self._structs.get(off)

    def type_name(self, off):
        if off == A_PTR:
            return "*const alloc::sync::ArcInner<…>"
        s = self._structs.get(off)
        return (s.path or s.name) if s else None

    def find(self, name):
        return next((s for s in self._structs.values()
                     if s.path == name or s.name == name), None)

    def type_off(self, name):
        return next((o for o, s in self._structs.items()
                     if s.path == name or s.name == name), None)

    def var(self, name):
        return FakeVar(name, 0x8022_D2E8, A_ARC) if name == "cache" else None

    def var_at(self, _addr):
        return None

    def array_of(self, _off):
        return None

    def size_of(self, off):
        s = self._structs.get(off)
        return s.size if s else None

    def pointee(self, off):
        return A_INNER if off == A_PTR else None


def _arc_plan(steps):
    return compile_source(ArcDw(), "blockcache",
                          SourceSpec(kind="table", completeness="total",
                                     steps=steps),
                          struct_path=MUTEX_NAME)


def test_unwrap_gets_arc_payload_type_from_dwarf_when_the_name_wont_peel():
    p = _arc_plan([{"static": "cache"}, {"unwrap": ["Arc", "Mutex"]}])
    assert p.compiled, p.reason
    unwrap = next(o for o in p.ops if o.kind == "unwrap")
    assert unwrap.args["types"] == [ARC_NAME, MUTEX_NAME], unwrap.args


def test_inline_shells_do_not_take_the_pointer_shortcut():
    from nodefusion.model.readers.registry import is_refcounted_shell
    assert is_refcounted_shell("Arc") and is_refcounted_shell("weak")
    assert not is_refcounted_shell("Lazy")
    assert not is_refcounted_shell("UPSafeCell")
    assert not is_refcounted_shell("Ptr")
