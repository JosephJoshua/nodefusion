
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model import plan as P                   # noqa: E402
from nodefusion.model import resolve as R                # noqa: E402
from nodefusion.model.layout import StructLayout         # noqa: E402
from nodefusion.model.readers import containers as C     # noqa: E402
from nodefusion.model.readers.registry import make       # noqa: E402

(LIST, RAWLIST, OPT, NN, PTR_FIFO, FIFO, LINKS, UCELL, ENTRY, TASK,
 SPIN, SPIN_UC, SCHED, PHANTOM, TWO_REAL) = range(1, 16)

TASK_NAME = "axtask::task::TaskInner"
FIFO_NAME = f"axsched::fifo::FifoTask<{TASK_NAME}>"
ARC_NAME = f"alloc::sync::Arc<{FIFO_NAME}, alloc::alloc::Global>"
LIST_NAME = f"linked_list_r4l::linked_list::List<{ARC_NAME}>"
RAWLIST_NAME = f"linked_list_r4l::raw_list::RawList<{ARC_NAME}>"
OPT_NAME = f"Option<core::ptr::non_null::NonNull<{FIFO_NAME}>>"
SPIN_NAME = ("spinlock::base::BaseSpinLock<kernel_guard::NoOp, "
             f"axsched::fifo::FifoScheduler<{TASK_NAME}>>")
SCHED_NAME = f"axsched::fifo::FifoScheduler<{TASK_NAME}>"

LINKS_AT = 256
ENTRY_AT = 8


class ListDw:

    def __init__(self):
        self._structs = {
            LIST: StructLayout(name="List<Arc<FifoTask<TaskInner>>>",
                               path=LIST_NAME, size=8,
                               fields={"list": 0},
                               field_types={"list": RAWLIST}),
            RAWLIST: StructLayout(name="RawList<Arc<FifoTask<TaskInner>>>",
                                  path=RAWLIST_NAME, size=8,
                                  fields={"head": 0},
                                  field_types={"head": OPT}),
            FIFO: StructLayout(name="FifoTask<TaskInner>", path=FIFO_NAME,
                               size=280,
                               fields={"inner": 0, "links": LINKS_AT},
                               field_types={"inner": TASK, "links": LINKS}),
            TASK: StructLayout(name="TaskInner", path=TASK_NAME, size=256,
                               fields={"id": 24}, field_types={}),
            LINKS: StructLayout(name="Links<FifoTask<TaskInner>>",
                                path=f"linked_list_r4l::raw_list::Links<{FIFO_NAME}>",
                                size=24,
                                fields={"entry": ENTRY_AT, "inserted": 16},
                                field_types={"entry": UCELL,
                                             "inserted": TASK}),
            UCELL: StructLayout(name="UnsafeCell<ListEntry<…>>",
                                path="core::cell::UnsafeCell<…>", size=16,
                                fields={"value": 0},
                                field_types={"value": ENTRY}),
            ENTRY: StructLayout(name="ListEntry<FifoTask<TaskInner>>",
                                path=f"linked_list_r4l::raw_list::ListEntry<{FIFO_NAME}>",
                                size=16, fields={"next": 0, "prev": 8},
                                field_types={"next": OPT, "prev": OPT}),
            SPIN: StructLayout(name="BaseSpinLock<NoOp, FifoScheduler<…>>",
                               path=SPIN_NAME, size=8,
                               fields={"_phantom": 0, "data": 0},
                               field_types={"_phantom": PHANTOM,
                                            "data": SPIN_UC}),
            SPIN_UC: StructLayout(name="UnsafeCell<FifoScheduler<…>>",
                                  path="core::cell::UnsafeCell<FifoScheduler>",
                                  size=8, fields={"value": 0},
                                  field_types={"value": SCHED}),
            SCHED: StructLayout(name="FifoScheduler<TaskInner>",
                                path=SCHED_NAME, size=8,
                                fields={"ready_queue": 0},
                                field_types={"ready_queue": LIST}),
            PHANTOM: StructLayout(name="PhantomData<NoOp>",
                                  path="core::marker::PhantomData<NoOp>",
                                  size=0, fields={}, field_types={}),
            TWO_REAL: StructLayout(name="NotAShell", path="test::NotAShell",
                                   size=16, fields={"a": 0, "b": 8},
                                   field_types={"a": TASK, "b": TASK}),
        }
        self._opaque = {OPT: (OPT_NAME, 8)}
        self._ptr_names = {PTR_FIFO: f"*const {FIFO_NAME}"}
        self._pointees = {PTR_FIFO: FIFO}

    def struct_at(self, off):
        return self._structs.get(off)

    def type_name(self, off):
        if off in self._opaque:
            return self._opaque[off][0]
        if off in self._ptr_names:
            return self._ptr_names[off]
        s = self._structs.get(off)
        return (s.path or s.name) if s else None

    def find(self, name):
        return next((s for s in self._structs.values()
                     if s.path == name or s.name == name), None)

    def type_off(self, name):
        for o, s in self._structs.items():
            if s.path == name or s.name == name:
                return o
        return next((o for o, (n, _sz) in self._opaque.items()
                     if n == name), None)

    def size_of(self, off):
        if off in self._opaque:
            return self._opaque[off][1]
        s = self._structs.get(off)
        return s.size if s else None

    def size_by_name(self, name):
        return self.size_of(self.type_off(name))

    def pointee(self, off):
        return self._pointees.get(off)

    def array_of(self, _off):
        return None

    def var(self, _name):
        return None



def test_next_offset_walks_every_shell_and_sums_them():
    dw = ListDw()
    o = R.list_opts(dw, dw.type_off(LIST_NAME))
    assert o["list_next_off"] == LINKS_AT + ENTRY_AT, o
    assert o["list_link_off"] == 0, o


def test_a_missing_shell_hop_gives_nothing_rather_than_half_an_offset():
    dw = ListDw()
    dw._structs[LINKS] = StructLayout(
        name="Links<…>", path=dw._structs[LINKS].path, size=24,
        fields={"mystery": ENTRY_AT, "inserted": 16},
        field_types={"mystery": UCELL, "inserted": TASK})
    o = R.list_opts(dw, dw.type_off(LIST_NAME))
    assert "list_next_off" not in o, o


def test_the_container_shell_is_peeled_by_being_a_single_field_struct():
    dw = ListDw()
    outer = R.list_opts(dw, dw.type_off(LIST_NAME))
    inner = R.list_opts(dw, dw.type_off(RAWLIST_NAME))
    assert outer == inner, (outer, inner)


def test_a_vec_is_not_mistaken_for_a_list():
    dw = ListDw()
    assert R.list_opts(dw, dw.type_off(TASK_NAME)) == {}



def test_element_type_comes_out_of_an_option_with_no_member_table():
    dw = ListDw()
    assert dw.struct_at(OPT) is None, "前提：这个枚举没有成员表"
    assert R.list_elem_die(dw, dw.type_off(LIST_NAME)) == FIFO
    assert R.list_opts(dw, dw.type_off(LIST_NAME))["elem_type"] == FIFO_NAME


def test_peeling_stops_at_an_unrecognised_wrapper_instead_of_going_all_the_way():
    dw = ListDw()
    dw._opaque[OPT] = ("Option<u32>", 8)
    assert R.list_elem_die(dw, dw.type_off(LIST_NAME)) is None



def test_a_zero_sized_phantom_does_not_count_as_the_payload():
    dw = ListDw()
    assert P._sole_field_type(dw, SPIN_NAME) == \
        "core::cell::UnsafeCell<FifoScheduler>"


def test_two_byte_carrying_fields_still_refuse():
    dw = ListDw()
    assert P._sole_field_type(dw, "test::NotAShell") is None



_OPTS = {"list_head_off": 0, "list_link_off": 0, "list_next_off": LINKS_AT}


def test_a_list_without_a_terminator_is_refused():
    r, why = make("list<struct>", opts=dict(_OPTS))
    assert r is None
    assert "terminator" in why, why


def test_the_three_terminators_and_an_integer_sentinel_all_build():
    for term, want in (("null", C.NullTerminated),
                       ("circular", C.Circular),
                       ("circular_headed", C.CircularHeaded),
                       (0, C.NullTerminated),
                       (0xFFFF_FFFF, C.NullTerminated)):
        r, why = make("list<struct>", opts={**_OPTS, "terminator": term})
        assert r is not None, (term, why)
        assert isinstance(r.terminator, want), (term, r.terminator)


def test_an_integer_sentinel_is_carried_through_not_flattened_to_zero():
    r, _ = make("list<struct>", opts={**_OPTS, "terminator": 0xDEAD})
    assert r.terminator.sentinel == 0xDEAD


def test_a_misspelt_terminator_is_refused_rather_than_ignored():
    r, why = make("list<struct>", opts={**_OPTS, "terminator": "circlar"})
    assert r is None
    assert "circlar" in why, why


def test_a_missing_next_offset_is_refused():
    o = {k: v for k, v in _OPTS.items() if k != "list_next_off"}
    r, why = make("list<struct>", opts={**o, "terminator": "circular_headed"})
    assert r is None
    assert "list_next_off" in why, why



def _src(steps):
    from nodefusion.model.manifest import SourceSpec
    return SourceSpec(kind="registry", completeness="partial", steps=steps)


def test_a_misspelt_step_argument_stops_the_plan():
    dw = ListDw()
    p = P.compile_source(dw, "task", _src([
        {"iter": "list", "linkk": "links", "terminator": "circular_headed"}]))
    assert not p.compiled
    assert "linkk" in (p.reason or ""), p.reason


def test_the_real_step_arguments_are_accepted():
    dw = ListDw()
    p = P.compile_source(dw, "task", _src([
        {"iter": "list", "link": "links", "next": "next",
         "terminator": "circular_headed"}]))
    assert "不认识的参数" not in (p.reason or ""), p.reason
