
from nodefusion.model.dwarfsrc import DwarfSource, StructLayout, _generic_base


def _src(*layouts: StructLayout) -> DwarfSource:
    dw = DwarfSource.__new__(DwarfSource)
    dw.structs = {s.path: s for s in layouts}
    dw.conflicts = {}
    dw._by_short = {}
    dw._by_base = {}
    dw._index_short()
    return dw


def _s(path: str, size: int, **fields: int) -> StructLayout:
    base, lt, args = path.partition("<")
    short = base.rsplit("::", 1)[-1] + lt + args
    return StructLayout(name=short, path=path, size=size, fields=dict(fields))



def test_base_cuts_at_the_first_angle_bracket():
    assert _generic_base(
        "NonNull<alloc::collections::btree::node::LeafNode<VirtPageNum, "
        "FrameTracker>>") == "NonNull"


def test_a_name_without_generics_is_unchanged():
    assert _generic_base("os::task::task::TaskControlBlock") == \
        "os::task::task::TaskControlBlock"



def test_a_generic_type_is_reachable_by_its_base_path():
    dw = _src(_s("axvm::vcpu::AxVCpu<axvm::arch::RISCVVCpu>", 512, id=0))
    got = dw.find("axvm::vcpu::AxVCpu")
    assert got is not None and got.size == 512


def test_a_generic_type_is_reachable_by_its_bare_base_name():
    dw = _src(_s("axvm::vcpu::AxVCpu<axvm::arch::RISCVVCpu>", 512, id=0))
    assert dw.find("AxVCpu") is not None


def test_instantiations_that_agree_on_layout_count_as_one():
    dw = _src(
        _s("alloc::collections::btree::map::BTreeMap<A, B>", 24,
           root=0, length=16),
        _s("alloc::collections::btree::map::BTreeMap<C, D>", 24,
           root=0, length=16))
    got = dw.find("alloc::collections::btree::map::BTreeMap")
    assert got is not None and got.size == 24


def test_instantiations_that_disagree_are_refused_not_guessed():
    dw = _src(_s("core::ptr::non_null::NonNull<u8>", 8, pointer=0),
              _s("core::ptr::non_null::NonNull<Big>", 16, pointer=0, meta=8))
    assert dw.find("NonNull") is None
    assert "NonNull" in dw.conflicts
    msg = dw.conflicts["NonNull"]
    assert "泛型基名" in msg
    assert "NonNull<u8>" in msg


def test_an_exact_path_still_wins_over_the_base_index():
    dw = _src(_s("k::Wrapper<A>", 8, a=0), _s("k::Wrapper", 99, b=0))
    got = dw.find("k::Wrapper")
    assert got is not None and got.size == 99


def test_a_short_name_still_wins_over_the_base_index():
    dw = _src(_s("k::Thing<A>", 8, a=0), _s("other::Thing", 42, b=0))
    got = dw.find("Thing")
    assert got is not None and got.size == 42
