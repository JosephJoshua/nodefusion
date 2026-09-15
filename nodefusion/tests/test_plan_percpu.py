
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.layout import StructLayout       # noqa: E402
from nodefusion.model.manifest import SourceSpec       # noqa: E402
from nodefusion.model.plan import compile_source       # noqa: E402

WRAP, LAZY, RQ, NN, ARC, FIFO, INNER, U8, PTR = 1, 2, 3, 4, 5, 6, 7, 8, 9

TASK = "axtask::task::TaskInner"
FIFO_NAME = "axsched::fifo::FifoTask<axtask::task::TaskInner>"
ARC_NAME = f"alloc::sync::Arc<{FIFO_NAME}, alloc::alloc::Global>"
LAZY_NAME = f"lazyinit::LazyInit<{ARC_NAME}>"


class FakeVar:
    def __init__(self, name, addr, type_off):
        self.name = self.path = name
        self.addr, self.type_off = addr, type_off


class FakeDw:
    def __init__(self):
        self._structs = {
            WRAP: StructLayout(name="IDLE_TASK_WRAPPER",
                               path="IDLE_TASK_WRAPPER", size=0, fields={}),
            LAZY: StructLayout(name="LazyInit<Arc<FifoTask<TaskInner>>>",
                               path=LAZY_NAME, size=16,
                               fields={"data": 0, "inited": 8},
                               field_types={"data": ARC, "inited": U8}),
            ARC: StructLayout(name="Arc<FifoTask<TaskInner>, Global>",
                              path=ARC_NAME, size=8,
                              fields={"ptr": 0, "phantom": 8, "alloc": 8},
                              field_types={"ptr": NN}),
            NN: StructLayout(name="NonNull<ArcInner<…>>",
                             path="core::ptr::non_null::NonNull<…>", size=8,
                             fields={"pointer": 0},
                             field_types={"pointer": PTR}),
            INNER: StructLayout(name="ArcInner<FifoTask<TaskInner>>",
                                path="alloc::sync::ArcInner<…>", size=600,
                                fields={"strong": 0, "weak": 8, "data": 16},
                                field_types={"data": FIFO}),
            FIFO: StructLayout(name="FifoTask<TaskInner>", path=FIFO_NAME,
                               size=584, fields={"inner": 0, "links": 576},
                               field_types={"inner": RQ}),
            RQ: StructLayout(name="TaskInner", path=TASK, size=256,
                             fields={"id": 24, "name": 32}),
            U8: StructLayout(name="AtomicU8", path="core::AtomicU8", size=1,
                             fields={"v": 0}),
        }
        self._vars = {
            "axtask::run_queue::IDLE_TASK": FakeVar(
                "IDLE_TASK", 0x0, WRAP),
            "axtask::run_queue::__PERCPU_IDLE_TASK": FakeVar(
                "__PERCPU_IDLE_TASK", 0x18, LAZY),
            "axhal::percpu::__PERCPU_CPU_ID": FakeVar(
                "__PERCPU_CPU_ID", 0x70, U8),
        }

    def struct_at(self, off):
        return self._structs.get(off)

    def type_name(self, off):
        if off == PTR:
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
        return self._vars.get(name)

    def var_at(self, _addr):
        return None

    def array_of(self, _off):
        return None

    def size_of(self, off):
        s = self._structs.get(off)
        return s.size if s else None

    def pointee(self, off):
        return INNER if off == PTR else None


PERCPU_BOUNDS = {"_percpu_start": 0xffffffc080224000,
                 "_percpu_end": 0xffffffc080224080,
                 "_percpu_load_start": 0x0,
                 "_percpu_load_end": 0x78}


class FakeSym:
    def __init__(self, value):
        self.value = value


class FakeElf:

    def __init__(self, bounds=None):
        self._b = PERCPU_BOUNDS if bounds is None else bounds

    def sym(self, name):
        v = self._b.get(name)
        return None if v is None else FakeSym(v)


class FakeSyms:
    def __init__(self, bounds=None):
        self.elf = FakeElf(bounds)


def _plan(steps, dw=None, syms=-1):
    return compile_source(dw or FakeDw(), "task",
                          SourceSpec(kind="registry", completeness="partial",
                                     steps=steps), struct_path=TASK,
                          syms=FakeSyms() if syms == -1 else syms)


def test_percpu_carries_the_type_forward():
    p = _plan([{"percpu": "axtask::run_queue::__PERCPU_IDLE_TASK"}])
    assert p.compiled, p.reason
    assert "LazyInit" in p.trace[0], p.trace
    assert "类型未知" not in p.trace[0], p.trace


def test_a_wrapper_name_falls_through_to_the_percpu_sibling():
    p = _plan([{"percpu": "axtask::run_queue::IDLE_TASK"}])
    assert p.compiled, p.reason
    assert "LazyInit" in p.trace[0], p.trace
    assert "__PERCPU_" in p.trace[0], "没说清类型是从哪个符号查到的"


def test_percpu_then_descend_to_compiles_all_the_way_to_a_field():
    p = _plan([{"percpu": "axtask::run_queue::IDLE_TASK"},
               {"unwrap": ["LazyInit", "Arc"]},
               {"descend_to": TASK},
               {"field": "id"}])
    assert p.compiled, f"{p.reason}\n" + "\n".join(p.trace)
    kinds = [o.kind for o in p.ops]
    assert "field_dyn" not in kinds, f"字段退成运行期解析：{p.trace}"
    assert p.ops[-1].kind == "offset" and p.ops[-1].args["n"] == 24, p.trace


def test_an_unknown_percpu_name_refuses_to_compile():
    p = _plan([{"percpu": "axtask::run_queue::NOT_A_REAL_ONE"}])
    assert not p.compiled
    assert "NOT_A_REAL_ONE" in p.reason


def test_a_name_that_already_has_the_prefix_is_not_double_prefixed():
    p = _plan([{"percpu": "axhal::percpu::__PERCPU_CPU_ID"}])
    assert p.compiled, p.reason
    assert "类型未知" not in p.trace[0], p.trace
    assert "__PERCPU_兄弟" not in p.trace[0], "不该走兄弟那条路"


def test_unwrap_reconnects_the_die_when_the_name_peels_but_the_die_drops():
    p = _plan([{"percpu": "axtask::run_queue::__PERCPU_IDLE_TASK"},
               {"unwrap": ["LazyInit", "Arc"]}])
    assert p.compiled, p.reason
    unwrap = next(o for o in p.ops if o.kind == "unwrap")
    assert unwrap.args["types"] == [LAZY_NAME, ARC_NAME], unwrap.args["types"]
