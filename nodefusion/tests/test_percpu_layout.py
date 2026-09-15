
from __future__ import annotations

from nodefusion.model import plan as P
from nodefusion.model.exec import Executor, Node, Op, Walk

START, END = 0xffffffc080224000, 0xffffffc080224080
LOAD_START, LOAD_END = 0x0, 0x78

IDLE_TASK, RUN_QUEUE, IS_BSP = 0x00, 0x28, 0x68


class _Sym:
    def __init__(self, value: int) -> None:
        self.value = value


class _Elf:
    def __init__(self, **bounds: int) -> None:
        self._b = bounds

    def sym(self, name: str):
        v = self._b.get(name)
        return None if v is None else _Sym(v)


class _Syms:
    def __init__(self, **bounds: int) -> None:
        self.elf = _Elf(**bounds)


class _Var:
    def __init__(self, addr: int) -> None:
        self.addr, self.type_off = addr, 1


class _Dw:

    def __init__(self, vars_: dict[str, int]) -> None:
        self._v = vars_

    def var(self, name: str):
        a = self._v.get(name)
        return None if a is None else _Var(a)

    def type_name(self, _off):
        return "LazyInit<Arc<FifoTask<TaskInner>>>"

    def struct_at(self, _off):
        return None


def _bounds(start=START, end=END, load_start=LOAD_START, load_end=LOAD_END):
    return _Syms(_percpu_start=start, _percpu_end=end,
                 _percpu_load_start=load_start, _percpu_load_end=load_end)


def _layout(spec="axtask::run_queue::__PERCPU_IDLE_TASK", *, syms=-1,
            vars_=None, **kw):
    dw = _Dw(vars_ if vars_ is not None else
             {"axtask::run_queue::__PERCPU_IDLE_TASK": IDLE_TASK,
              "axtask::run_queue::__PERCPU_RUN_QUEUE": RUN_QUEUE,
              "axhal::percpu::__PERCPU_IS_BSP": IS_BSP})
    return P._percpu_layout(dw, _bounds(**kw) if syms == -1 else syms, spec)



def test_the_arceos_layout_is_measured_correctly():
    a, why = _layout()
    assert why == ""
    assert a == {"base": START, "stride": 0x80, "ncpu": 1, "off": 0x00,
                 "name": "axtask::run_queue::__PERCPU_IDLE_TASK",
                 "how": "dwarf"}


def test_the_offset_within_one_area_comes_from_the_symbol():
    a, _ = _layout("axtask::run_queue::__PERCPU_RUN_QUEUE")
    assert a["off"] == 0x28


def test_the_percpu_sibling_is_found_from_the_plain_name():
    a, why = _layout("axtask::run_queue::IDLE_TASK")
    assert a is not None and a["off"] == IDLE_TASK, why
    assert "__PERCPU_" in a["how"]



def test_four_cpus_are_counted_not_assumed():
    a, why = _layout(end=START + 4 * 0x80)
    assert a["ncpu"] == 4 and a["stride"] == 0x80, why


def test_an_unaligned_scheme_is_accepted_when_it_is_the_one_that_divides():
    a, why = _layout(end=START + 0xf0)
    assert a["stride"] == 0x78 and a["ncpu"] == 2, why


def test_the_addresses_of_each_cpu_are_stride_apart():
    a, _ = _layout("axtask::run_queue::__PERCPU_RUN_QUEUE", end=START + 2 * 0x80)
    got = [a["base"] + i * a["stride"] + a["off"] for i in range(a["ncpu"])]
    assert got == [START + 0x28, START + 0x80 + 0x28]



def test_a_span_that_no_alignment_divides_is_refused():
    a, why = _layout(end=START + 0x100 + 1)
    assert a is None and "算不出有几个 CPU" in why


def test_a_missing_boundary_symbol_is_named():
    a, why = _layout(syms=_Syms(_percpu_start=START, _percpu_end=END))
    assert a is None
    assert "_percpu_load_start" in why and "_percpu_load_end" in why
    assert "percpu crate" in why


def test_no_symbol_table_at_all_says_so():
    a, why = _layout(syms=None)
    assert a is None and "没有符号表" in why


def test_an_unknown_variable_is_refused_rather_than_placed_at_zero():
    a, why = _layout("axtask::run_queue::NOPE", vars_={})
    assert a is None and "NOPE" in why


def test_a_zero_length_area_is_refused():
    a, why = _layout(load_end=LOAD_START)
    assert a is None and "边界不成立" in why



def _run(args, nodes=None):
    ex = Executor(mem=None, ctx=None)
    return ex._apply(Op("percpu", args), nodes if nodes is not None else [], Walk())


def test_the_op_expands_to_one_node_per_cpu():
    out = _run({"base": START, "stride": 0x80, "ncpu": 3, "off": 0x28,
                "name": "RUN_QUEUE"})
    assert [n.addr for n in out] == [START + 0x28, START + 0xa8, START + 0x128]


def test_it_produces_nodes_from_an_empty_input():
    assert len(_run({"base": START, "stride": 0x80, "ncpu": 2, "off": 0,
                     "name": "IDLE_TASK"}, nodes=[])) == 2


def test_the_trail_says_which_cpu():
    out = _run({"base": START, "stride": 0x80, "ncpu": 2, "off": 0,
                "name": "IDLE_TASK"})
    assert out[0].trail == ["IDLE_TASK@cpu0"]
    assert out[1].trail == ["IDLE_TASK@cpu1"]


def test_one_cpu_gives_exactly_the_area_base():
    out = _run({"base": START, "stride": 0x80, "ncpu": 1, "off": 0,
                "name": "IDLE_TASK"})
    assert [n.addr for n in out] == [START]
