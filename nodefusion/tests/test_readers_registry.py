import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.rt import DictMemory, ReadCtx, Unavailable, is_ok
from nodefusion.model.readers import containers as C
from nodefusion.model.readers.registry import (
    Struct, generic_args, inner_type, known_names, make, outer_name,
    split_spec, unwrap_reader, via_spec,
)

BASE = 0x8000_0000
ADDR = BASE + 0x1000



def test_split_spec_plain():
    assert split_spec("u32") == ("u32", [])
    assert split_spec("  Struct  ") == ("struct", [])


def test_split_spec_nested_keeps_inner_intact():
    assert split_spec("arc<mutex<struct>>") == ("arc", ["mutex<struct>"])


def test_split_spec_splits_on_depth_zero_commas_only():
    assert split_spec("map<u32, arc<t>>") == ("map", ["u32", "arc<t>"])


def test_split_spec_does_not_read_the_arrow_of_a_fn_type_as_a_closing_bracket():
    t = ("Lazy<alloc::sync::Arc<kernel::task::task::Task, alloc::alloc::Global>, "
         "fn() -> alloc::sync::Arc<kernel::task::task::Task, alloc::alloc::Global>, "
         "spin::relax::Spin>")
    assert generic_args(t) == [
        "alloc::sync::Arc<kernel::task::task::Task, alloc::alloc::Global>",
        "fn() -> alloc::sync::Arc<kernel::task::task::Task, alloc::alloc::Global>",
        "spin::relax::Spin",
    ]
    assert inner_type(t) is None


def test_split_spec_rejects_unbalanced():
    for bad in ("arc<u32", "arc<u32>>", "arc>u32<"):
        try:
            split_spec(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} 应该被拒，实际过了")



def test_outer_name_drops_path_and_generics():
    assert outer_name("alloc::sync::Arc<TaskControlBlock>") == "Arc"
    assert outer_name("Processor") == "Processor"


def test_generic_args():
    assert generic_args("Lazy<Arc<T>>") == ["Arc<T>"]
    assert generic_args("Processor") == []


def test_inner_type_peels_one_layer():
    assert inner_type("Lazy<UPSafeCell<Processor>>") == "UPSafeCell<Processor>"
    assert inner_type("UPSafeCell<Processor>") == "Processor"


def test_inner_type_gives_up_rather_than_guessing():
    assert inner_type("Processor") is None
    assert inner_type(None) is None
    assert inner_type("BTreeMap<u32, Arc<T>>") is None



def test_terminals():
    for name in ("u8", "u32", "usize", "i32", "bool", "ptr", "struct"):
        r, why = make(name)
        assert r is not None, f"{name} 该造得出来：{why}"


def test_struct_is_identity_and_never_reads_memory():
    r, _ = make("struct")
    assert r(DictMemory(), ADDR, ReadCtx(layout={})) == ADDR


def test_composition_nests():
    r, why = make("arc<mutex<struct>>", type_name="Arc<Mutex<Foo>>")
    assert r is not None, why
    assert type(r).__name__ == "Arc"


def test_unknown_name_lists_candidates():
    r, why = make("nonsense")
    assert r is None
    assert "nonsense" in why
    for expect in ("arc", "vec", "struct"):
        assert expect in why, f"候选里该有 {expect}：{why}"


def test_option_refuses_unknown_niche():
    r, why = make("option<u32>")
    assert r is None and "niche" in why


def test_option_accepts_the_three_it_can_defend():
    for name in ("option<arc>", "option<weak>", "option<struct>"):
        r, why = make(name)
        assert r is not None, f"{name} 该认：{why}"


def test_missing_required_params_are_refused_not_defaulted():
    for name in ("cstr", "bitfield", "array<usize>"):
        r, why = make(name)
        assert r is None, f"{name} 缺参数居然造出来了"
        assert why, f"{name} 拒了但没说为什么"


def test_enum_needs_a_type_name():
    r, why = make("enum")
    assert r is None and "enum" in why
    r2, _ = make("enum", opts={"enum": "TaskStatus"})
    assert r2 is not None


def test_vec_infers_elem_size_only_for_pointer_width():
    ok, _ = make("vec<arc>", opts={"vec_type": "Vec<Arc<T>>"})
    assert ok is not None
    no, why = make("vec<struct>", opts={"vec_type": "Vec<Foo>"})
    assert no is None and "elem_size" in why


def test_vecdeque_is_a_separate_reader_not_an_alias_for_vec():
    r, why = make("vecdeque<arc>", opts={"vec_type": "VecDeque<Arc<T>>"})
    assert r is not None, why
    assert isinstance(r, C.vecdeque), type(r)
    assert not isinstance(r, C.vec)


def test_vecdeque_also_refuses_without_elem_size():
    no, why = make("vecdeque<struct>", opts={"vec_type": "VecDeque<Foo>"})
    assert no is None and "elem_size" in why


# ------------------------------------------------------------------ unwrap

def test_unwrap_cross_pointer_needs_no_type():
    r, why = unwrap_reader("Arc", None)
    assert r is not None, why


def test_unwrap_inline_without_type_fails_loudly_when_called():
    r, why = unwrap_reader("UPSafeCell", None)
    assert r is not None, why
    got = r(DictMemory(), ADDR, ReadCtx(layout={}))
    assert isinstance(got, Unavailable), f"该报 Unavailable，实际 {got!r}"
    assert not is_ok(got)


def test_unwrap_inline_with_type_resolves_from_dwarf():
    ctx = ReadCtx(layout={"UPSafeCell<Processor>": {"inner": 0},
                          "RefCell<Processor>": {"borrow": 0, "value": 8}})
    r, why = unwrap_reader("UPSafeCell", "UPSafeCell<Processor>")
    assert r is not None, why
    got = r(DictMemory(), ADDR, ctx)
    assert isinstance(got, int), f"内联层该算得出地址，实际 {got!r}"


def test_unwrap_unknown_layer_lists_candidates():
    r, why = unwrap_reader("Bogus", None)
    assert r is None
    assert "Bogus" in why and "arc" in why


def test_unwrap_is_case_insensitive_and_path_tolerant():
    for spelling in ("UPSafeCell", "upsafecell", "sync::up::UPSafeCell<Foo>"):
        r, why = unwrap_reader(spelling, "UPSafeCell<Processor>")
        assert r is not None, f"{spelling} 该认：{why}"


def test_known_names_is_not_empty():
    assert len(known_names()) > 10


def main() -> int:
    fails = []
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try:
                f()
            except Exception as e:                        # noqa: BLE001
                fails.append((n, f"{type(e).__name__}: {e}"))
    if fails:
        print(f"失败 {len(fails)} 项：")
        for n, why in fails:
            print(f"   {n}: {why}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_unwrap_uses_the_nested_type_it_is_given_not_a_spliced_one():
    full = "Once<Arc<TCB>, spin::relax::Spin>"
    ctx = ReadCtx(layout={"Lazy<Arc<TCB>>": {"__0": 0},
                          full: {"status": 8, "data": 0}})
    r, why = unwrap_reader("Lazy", "Lazy<Arc<TCB>>", full)
    assert r is not None, why

    mem = DictMemory()
    mem.write(ADDR + 8, (2).to_bytes(8, "little"))    # status = Complete
    mem.write(ADDR + 0, (ADDR + 0x40).to_bytes(8, "little"))
    got = r(mem, ADDR, ctx)
    assert is_ok(got), f"两跳都该查得到，实际 {got!r}"


def test_unwrap_without_nested_still_falls_back_to_splicing():
    ctx = ReadCtx(layout={"Lazy<Arc<TCB>>": {"__0": 0},
                          "Once<Arc<TCB>>": {"status": 8, "data": 0}})
    r, why = unwrap_reader("Lazy", "Lazy<Arc<TCB>>")
    assert r is not None, why
    mem = DictMemory()
    mem.write(ADDR + 8, (2).to_bytes(8, "little"))
    mem.write(ADDR + 0, (ADDR + 0x40).to_bytes(8, "little"))
    assert is_ok(r(mem, ADDR, ctx))



def test_via_starts_at_the_container_not_at_the_last_layer():
    assert via_spec(["UPSafeCell", "Vec", "Arc"]) == ("vec<arc>", "")


def test_via_nests_everything_after_the_container():
    assert via_spec(["UPSafeCell", "Vec", "Option", "Arc"]) == (
        "vec<option<arc>>", "")


def test_via_finds_vecdeque_as_the_container():
    assert via_spec(["Mutex", "VecDeque", "Arc"]) == ("vecdeque<arc>", "")


def test_via_without_element_type_walks_addresses():
    assert via_spec(["SpinLock", "Vec"]) == ("vec<struct>", "")


def test_via_with_no_container_refuses_rather_than_guessing():
    spec, why = via_spec(["SpinLock", "Mutex"])
    assert spec is None
    assert "vec" in why and "array" in why


def test_via_builds_a_map_when_the_key_is_given():
    assert via_spec(["SpinLock", "btreemap", "Arc"], key="newtype<u32>") == (
        "btreemap<newtype<u32>, arc>", "")
    assert via_spec(["SpinLock", "btreemap"], key="u64") == (
        "btreemap<u64, struct>", "")


def test_via_map_without_a_key_refuses_rather_than_using_the_index():
    spec, why = via_spec(["SpinLock", "btreemap"])
    assert spec is None
    assert "btreemap" in why and "key" in why
    assert "没有一层是会展开成一串的容器" not in why


def test_via_empty_says_so():
    assert via_spec([])[0] is None


# ---------------------------------------------------------------- btreemap

BT_OPTS = {"btree_noderef_height": 8, "btree_noderef_node": 0,
           "btree_len": 186, "btree_keys": 8, "btree_vals": 96,
           "btree_key_size": 8, "btree_val_size": 8, "btree_edges": 192}
BT_TYPE = "BTreeMap<os::mm::address::VirtPageNum, os::…::FrameTracker, Global>"


def test_btreemap_takes_the_measured_layout_whole():
    r, why = make("btreemap<newtype<usize>, struct>",
                  type_name=BT_TYPE, opts=BT_OPTS)
    assert why == "" and r is not None
    assert r.node == C.BTreeNodeLayout(
        noderef_height=8, noderef_node=0, len=186, keys=8, vals=96,
        key_size=8, val_size=8, edges=192)


def test_btreemap_drops_a_half_measured_layout_entirely():
    for miss in BT_OPTS:
        o = {k: v for k, v in BT_OPTS.items() if k != miss}
        r, why = make("btreemap<newtype<usize>, struct>",
                      type_name=BT_TYPE, opts=o)
        assert why == "" and r is not None, (miss, why)
        if miss == "btree_edges":
            assert r.node is not None and r.node.edges is None
        else:
            assert r.node is None, f"少了 {miss} 却还给了一份布局"


def test_btreemap_needs_both_a_key_and_a_value_reader():
    assert make("btreemap<usize>", type_name=BT_TYPE)[0] is None
    assert "键" in make("btreemap<usize>", type_name=BT_TYPE)[1]


def test_btreemap_needs_its_own_type_name():
    r, why = make("btreemap<usize, struct>")
    assert r is None and "DWARF" in why


def test_btreemap_hands_the_generic_args_down_to_key_and_value():
    r, _ = make("btreemap<newtype<usize>, struct>",
                type_name=BT_TYPE, opts=BT_OPTS)
    assert r.key.type_name == "os::mm::address::VirtPageNum"


def test_btreemap_is_in_the_known_names():
    assert "btreemap" in known_names()



def test_unit_is_in_the_known_names():
    assert "unit" in known_names()


def test_unit_reads_nothing_and_that_counts_as_a_reading():
    from nodefusion.model.rt import is_ok
    r, why = make("unit")
    assert r is not None, why
    v = r(None, 0x1000, None)
    assert v is None and is_ok(v)
    assert r.size == 0


def test_a_set_is_a_btreemap_whose_value_reader_is_unit():
    r, why = make("btreemap<newtype<u32>, unit>", type_name=SET_TYPE)
    assert r is not None, why
    assert r.value.size == 0


SET_TYPE = ("BTreeMap<starry_kernel::task::pid::TidNumber, "
            "alloc::collections::btree::set_val::SetValZST, alloc::alloc::Global>")


def test_every_inline_shell_accepts_the_registry_calling_convention():
    from nodefusion.model.readers import registry as R

    bad = []
    for name, cls in R._INLINE.items():
        try:
            cls(None, type_name=f"{name}<Foo>")
        except TypeError as e:
            bad.append(f"{name}（{cls.__name__}）：{e}")
    assert not bad, "这些壳类不接受 registry 的造法：\n  " + "\n  ".join(bad)


# --------------------------------------------------------------- field<>

_PT = ("page_table::table::bits64::PageTable64<"
       "page_table::table::riscv::Sv39MetaData, "
       "page_table::pte::riscv::Rv64PTE, mem::frame::VmmPageAllocator>")


def test_field_is_in_the_known_names():
    assert "field" in known_names()


def test_field_reads_the_named_field_not_the_struct_head():
    r, why = make(f"field<root_paddr, usize>", type_name=_PT)
    assert r is not None, why
    mem = DictMemory({0x1018: (0xA0565000).to_bytes(8, "little")})
    ctx = ReadCtx(layout={_PT: {"root_paddr": 24}})
    assert r(mem, 0x1000, ctx) == 0xA0565000


def test_field_refuses_to_fall_back_to_offset_zero():
    r, _ = make(f"field<root_paddr, usize>", type_name=_PT)
    mem = DictMemory({0x1000: (0xDEAD).to_bytes(8, "little"),
                      0x1018: (0xA0565000).to_bytes(8, "little")})
    got = r(mem, 0x1000, ReadCtx(layout={_PT: {"别的字段": 0}}))
    assert isinstance(got, Unavailable) and not is_ok(got)
    assert got != 0xDEAD, "退回偏移 0 了 —— 这正是不能干的事"


def test_field_without_a_type_name_says_so():
    r, why = make("field<root_paddr, usize>")
    assert r is not None, why
    got = r(DictMemory({}), 0x1000, ReadCtx())
    assert isinstance(got, Unavailable)


def test_field_rejects_bad_specs():
    for spec in ("field<usize>", "field<root_paddr>", "field<, usize>",
                 "field<root_paddr, 没这个 reader>"):
        r, why = make(spec, type_name=_PT)
        assert r is None, f"{spec} 不该造得出来"
        assert why, f"{spec} 造不出来但没给原因"



def test_field_prefers_the_measured_offset_over_the_name_lookup():
    r, why = make("field<__0, u64>", type_name="pid::Live",
                  opts={"layer_chain": [{"name": "pid::Live", "field_off": 0},
                                        {"name": "u64"}]})
    assert r is not None, why
    mem = DictMemory({0x1000: (0xAAAA).to_bytes(8, "little"),
                      0x1008: (0xBBBB).to_bytes(8, "little")})
    got = r(mem, 0x1000, ReadCtx(layout={"pid::Live": {"__0": 8}}))
    assert got == 0xAAAA, f"用了按名字查到的 +8，读成 {got:#x}"


def test_field_still_falls_back_to_the_name_when_nothing_measured_it():
    r, why = make("field<__0, u64>", type_name="pid::Live")
    assert r is not None, why
    mem = DictMemory({0x1008: (0xBBBB).to_bytes(8, "little")})
    got = r(mem, 0x1000, ReadCtx(layout={"pid::Live": {"__0": 8}}))
    assert got == 0xBBBB


# ------------------------------------------------------------------- astype

def test_astype_is_a_known_name():
    assert "astype" in known_names()


def test_astype_names_the_type_that_dwarf_erased():
    r, why = make("astype<some::Thread, field<proc_data, u64>>")
    assert r is not None, why
    mem = DictMemory({0x1010: (0x1234).to_bytes(8, "little")})
    got = r(mem, 0x1000, ReadCtx(layout={"some::Thread": {"proc_data": 0x10}}))
    assert got == 0x1234


def test_astype_rejects_bad_specs():
    for spec in ("astype<some::Thread>", "astype<, u64>",
                 "astype<some::Thread, 没这个 reader>"):
        r, why = make(spec)
        assert r is None, f"{spec} 不该造得出来"
        assert why, f"{spec} 造不出来但没给原因"
