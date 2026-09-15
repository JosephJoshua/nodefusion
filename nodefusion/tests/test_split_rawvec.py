
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model import resolve as R                # noqa: E402
from nodefusion.model.layout import StructLayout         # noqa: E402
from nodefusion.model.readers import containers as C     # noqa: E402
from nodefusion.model.readers import scalars as S        # noqa: E402
from nodefusion.model.readers.registry import make       # noqa: E402
from nodefusion.model.rt import ReadCtx                  # noqa: E402

(VEC, RAW, INNER, UNIQ_U8, PTR_U8, U8, MARKER, ARC, NN, PTR_AI, AINNER,
 FIFO, TASK, STR, VEC_U8, RAW_U8, MARKER_U8, UNIQ_ARC, PTR_ARC,
 NOT_A_STRING, USIZE) = range(1, 22)

TASK_NAME = "axtask::task::TaskInner"
FIFO_NAME = f"axsched::fifo::FifoTask<{TASK_NAME}>"
ARC_NAME = f"alloc::sync::Arc<{FIFO_NAME}, alloc::alloc::Global>"
RAW_NAME = f"alloc::raw_vec::RawVec<{ARC_NAME}, alloc::alloc::Global>"
INNER_NAME = "alloc::raw_vec::RawVecInner<alloc::alloc::Global>"
VEC_NAME = f"alloc::vec::Vec<{ARC_NAME}, alloc::alloc::Global>"
RAW_U8_NAME = "alloc::raw_vec::RawVec<u8, alloc::alloc::Global>"
VEC_U8_NAME = "alloc::vec::Vec<u8, alloc::alloc::Global>"
STR_NAME = "alloc::string::String"


class SplitDw:

    def __init__(self):
        self._structs = {
            VEC: StructLayout(name="Vec<Arc<FifoTask<TaskInner>>>",
                              path=VEC_NAME, size=24,
                              fields={"buf": 0, "len": 16},
                              field_types={"buf": RAW, "len": USIZE}),
            RAW: StructLayout(name="RawVec<Arc<…>, Global>", path=RAW_NAME,
                              size=16, fields={"inner": 0, "_marker": 16},
                              field_types={"inner": INNER, "_marker": MARKER}),
            INNER: StructLayout(name="RawVecInner<Global>", path=INNER_NAME,
                                size=16,
                                fields={"cap": 0, "ptr": 8, "alloc": 16},
                                field_types={"ptr": UNIQ_U8}),
            UNIQ_U8: StructLayout(name="Unique<u8>",
                                  path="core::ptr::unique::Unique<u8>", size=8,
                                  fields={"pointer": 0},
                                  field_types={"pointer": PTR_U8}),
            MARKER: StructLayout(name=f"PhantomData<{ARC_NAME}>",
                                 path=f"core::marker::PhantomData<{ARC_NAME}>",
                                 size=0, fields={}, field_types={}),
            ARC: StructLayout(name="Arc<FifoTask<TaskInner>, Global>",
                              path=ARC_NAME, size=8,
                              fields={"ptr": 0, "phantom": 8, "alloc": 8},
                              field_types={"ptr": NN}),
            NN: StructLayout(name="NonNull<ArcInner<…>>",
                             path="core::ptr::non_null::NonNull<…>", size=8,
                             fields={"pointer": 0},
                             field_types={"pointer": PTR_AI}),
            AINNER: StructLayout(name="ArcInner<FifoTask<TaskInner>>",
                                 path="alloc::sync::ArcInner<…>", size=600,
                                 fields={"strong": 0, "weak": 8, "data": 16},
                                 field_types={"data": FIFO}),
            FIFO: StructLayout(name="FifoTask<TaskInner>", path=FIFO_NAME,
                               size=584, fields={"inner": 0},
                               field_types={"inner": TASK}),
            TASK: StructLayout(name="TaskInner", path=TASK_NAME, size=256,
                               fields={"id": 24}),
            STR: StructLayout(name="String", path=STR_NAME, size=24,
                              fields={"vec": 0}, field_types={"vec": VEC_U8}),
            VEC_U8: StructLayout(name="Vec<u8, Global>", path=VEC_U8_NAME,
                                 size=24, fields={"buf": 0, "len": 16},
                                 field_types={"buf": RAW_U8,
                                              "len": USIZE}),
            RAW_U8: StructLayout(name="RawVec<u8, Global>", path=RAW_U8_NAME,
                                 size=16, fields={"inner": 0, "_marker": 16},
                                 field_types={"inner": INNER,
                                              "_marker": MARKER_U8}),
            MARKER_U8: StructLayout(name="PhantomData<u8>",
                                    path="core::marker::PhantomData<u8>",
                                    size=0, fields={}, field_types={}),
        }
        self._prim = {U8: "u8", USIZE: "usize"}
        self._ptr_names = {PTR_U8: "*const u8",
                           PTR_AI: "*const alloc::sync::ArcInner<…>"}
        self._pointees = {PTR_U8: U8, PTR_AI: AINNER}
        self._base = {"u8": 1, "usize": 8, "u32": 4}

    def struct_at(self, off):
        return self._structs.get(off)

    def type_name(self, off):
        if off in self._ptr_names:
            return self._ptr_names[off]
        if off in self._prim:
            return self._prim[off]
        s = self._structs.get(off)
        return (s.path or s.name) if s else None

    def find(self, name):
        return next((s for s in self._structs.values()
                     if s.path == name or s.name == name), None)

    def type_off(self, name):
        return next((o for o, s in self._structs.items()
                     if s.path == name or s.name == name), None)

    def size_by_name(self, name):
        off = self.type_off(name)
        if off is not None:
            return self._structs[off].size
        return self._base.get(name)

    def size_of(self, off):
        if off in self._prim:
            return self._base[self._prim[off]]
        s = self._structs.get(off)
        return s.size if s else None

    def pointee(self, off):
        return self._pointees.get(off)

    def array_of(self, _off):
        return None

    def var(self, _name):
        return None


def _old_dw():
    dw = SplitDw()
    dw._structs[RAW] = StructLayout(
        name="RawVec<Arc<…>, Global>", path=RAW_NAME, size=16,
        fields={"cap": 0, "ptr": 8, "alloc": 16},
        field_types={"ptr": UNIQ_ARC})
    dw._structs[UNIQ_ARC] = StructLayout(
        name="Unique<Arc<…>>", path="core::ptr::unique::Unique<Arc<…>>",
        size=8, fields={"pointer": 0}, field_types={"pointer": PTR_ARC})
    dw._ptr_names[PTR_ARC] = f"*const {ARC_NAME}"
    dw._pointees[PTR_ARC] = ARC
    return dw



def test_element_type_comes_from_the_phantom_marker_not_from_ptr():
    dw = SplitDw()
    got = R.elem_die(dw, dw.type_off(RAW_NAME))
    assert got == ARC, f"元素类型拿成了 {dw.type_name(got)!r}"


def test_the_erased_u8_is_never_reported_as_the_element_size():
    dw = SplitDw()
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    assert o.get("elem_size") == 8, o


def test_a_split_rawvec_without_a_marker_refuses_instead_of_guessing():
    dw = SplitDw()
    raw = dw._structs[RAW]
    dw._structs[RAW] = StructLayout(
        name=raw.name, path=raw.path, size=raw.size,
        fields={"inner": 0}, field_types={"inner": INNER})
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    assert "elem_size" not in o, f"没有 _marker 还报了大小：{o}"


def test_a_primitive_element_type_still_gets_a_size():
    dw = SplitDw()
    o = R.vec_opts(dw, dw.type_off(VEC_U8_NAME))
    assert o.get("elem_size") == 1, o


def test_the_old_shape_still_chases_ptr():
    dw = _old_dw()
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    assert o.get("elem_size") == 8, o
    assert o.get("raw_type") == RAW_NAME, o
    assert o.get("raw_base", 0) == 0, o



def test_vec_opts_names_the_type_that_actually_carries_ptr_and_cap():
    dw = SplitDw()
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    assert o.get("raw_type") == INNER_NAME, o
    assert o.get("raw_base") == 0, "inner 实测在 +0"


def test_the_inner_offset_is_measured_not_assumed():
    dw = SplitDw()
    raw = dw._structs[RAW]
    dw._structs[RAW] = StructLayout(
        name=raw.name, path=raw.path, size=raw.size,
        fields={"inner": 8, "_marker": 24}, field_types=raw.field_types)
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    assert o.get("raw_base") == 8, o


def test_an_unrecognised_raw_shape_gives_no_raw_type_at_all():
    dw = SplitDw()
    raw = dw._structs[RAW]
    dw._structs[RAW] = StructLayout(name=raw.name, path=raw.path,
                                    size=raw.size, fields={"_marker": 16},
                                    field_types={"_marker": MARKER})
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    assert "raw_type" not in o and "raw_base" not in o, o



def test_reader_adds_raw_base_when_composing_the_offset():
    layout = {VEC_NAME: {"buf": 0, "len": 16},
              INNER_NAME: {"cap": 0, "ptr": 8}}
    r = C.vec(VEC_NAME, 8, S.u64, raw_type=INNER_NAME, raw_base=8)
    got, why = r._offsets(ReadCtx(layout=layout))
    assert got is not None, why
    assert got["cap"] == 8 and got["ptr"] == 16, got


def test_raw_base_defaults_to_zero_so_the_old_call_shape_is_unchanged():
    layout = {VEC_NAME: {"buf": 0, "len": 16},
              RAW_NAME: {"cap": 0, "ptr": 8}}
    r = C.vec(VEC_NAME, 8, S.u64, raw_type=RAW_NAME)
    got, why = r._offsets(ReadCtx(layout=layout))
    assert got is not None, why
    assert got["cap"] == 0 and got["ptr"] == 8, got



def test_string_opts_walks_the_split_shape():
    dw = SplitDw()
    o = R.string_opts(dw, dw.type_off(STR_NAME))
    assert o.get("string_vec_type") == VEC_U8_NAME, o
    assert o.get("string_raw_type") == INNER_NAME, o
    assert o.get("string_raw_base") == 0, o


def test_string_shape_check_still_rejects_a_mere_vec_field():
    dw = SplitDw()
    dw._structs[NOT_A_STRING] = StructLayout(
        name="NotAString", path="k::NotAString", size=16,
        fields={"vec": 0}, field_types={"vec": TASK})
    assert R.string_opts(dw, NOT_A_STRING) == {}


def test_registry_builds_a_vec_reader_from_split_shape_opts():
    dw = SplitDw()
    o = R.vec_opts(dw, dw.type_off(VEC_NAME))
    r, why = make("vec<arc>", type_name=VEC_NAME, opts=o)
    assert r is not None, why
    assert r.raw_type == INNER_NAME and r.raw_base == 0


def test_registry_builds_a_string_reader_from_split_shape_opts():
    dw = SplitDw()
    o = R.string_opts(dw, dw.type_off(STR_NAME))
    r, why = make("string", type_name=STR_NAME, opts=o)
    assert r is not None, why
    assert r.raw_type == INNER_NAME and r.raw_base == 0
