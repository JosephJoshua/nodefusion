
from __future__ import annotations

import pathlib
from pathlib import Path

import pytest

from nodefusion.host.nfelf import Elf64
from nodefusion.host.analyze import _addressable_event_names
from nodefusion.host.record import RecordError, select_watchlist
from nodefusion.model.layout import Function, InlineSite
from nodefusion.model.manifest import (
    EventSpec, ManifestError, WatchSpec, builtin_dir, load_dir)
from nodefusion.model.watchsel import (
    Cand, bare_name, candidates, impl_path, select)


class FakeDw:

    def __init__(self, fns, types=()):
        self.functions = list(fns)
        self.types = set(types)

    def find(self, name):
        return name if name in self.types else None


class FakeSym:
    def __init__(self, name, value):
        self.name = name
        self.value = value


def fn(path, low_pc, decl_file=None, name=None):
    return Function(name=name or path.rsplit("::", 1)[-1], path=path,
                    low_pc=low_pc, decl_file=decl_file)


def w(subsystem, match, args=2, throttle=0):
    return WatchSpec(subsystem=subsystem, match=match, args=args,
                     throttle=throttle)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    ("<os::fs::inode::OSInode as os::fs::File>::read",
     "os::fs::inode::OSInode::read"),
    ("<os::drivers::block::virtio_blk::VirtIOBlock as "
     "easy_fs::block_dev::BlockDevice>::read_block",
     "os::drivers::block::virtio_blk::VirtIOBlock::read_block"),
    ("<alloc::vec::Vec<u8> as core::ops::drop::Drop>::drop",
     "alloc::vec::Vec<u8>::drop"),
    ("os::task::run_next_task", "os::task::run_next_task"),
    ("kalloc", "kalloc"),
    ("<unterminated", "<unterminated"),
])
def test_impl_path_peels_the_trait_impl_wrapper(raw, want):
    assert impl_path(raw) == want


def test_a_trait_impl_method_matches_its_own_module():
    dw = FakeDw([])
    syms = [FakeSym(
        # <os::fs::inode::OSInode as os::fs::File>::read
        "_ZN55_$LT$os..fs..inode..OSInode$u20$as$u20$os..fs..File$GT$"
        "4read17h1111111111111111E", 0x8000)]
    sel = select(dw, [w("fs", {"module": "os::fs"})], symbols=syms)
    assert [s.name for s in sel.picked] == ["read"]
    assert sel.picked[0].path == "os::fs::inode::OSInode::read"


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

def test_symbols_supply_addresses_dwarf_does_not_have():
    dw = FakeDw([fn("os::mm::memory_set::from_elf", None)])
    syms = [FakeSym("_ZN2os2mm10memory_set9MemorySet8from_elf"
                    "17h0e4bf92a766ebb69E", 0x802045bc)]

    only_dwarf = select(dw, [w("mm", {"module": "os::mm"})])
    assert only_dwarf.picked == []
    assert only_dwarf.no_address == {"mm": 1}
    both = select(dw, [w("mm", {"module": "os::mm"})], symbols=syms)
    assert [(s.name, s.addr) for s in both.picked] == [("from_elf", 0x802045bc)]
    assert both.picked[0].path == "os::mm::memory_set::MemorySet::from_elf"


def test_only_addressable_functions_count_as_live_event_paths():
    dw = FakeDw([fn("os::heap::__rust_alloc_zeroed", None),
                 fn("os::mm::PageTable::new", 0x80200000)])
    assert _addressable_event_names(dw, []) == {
        "os::mm::PageTable::new", "new"}


def test_conditional_watch_selects_one_layer_of_an_allocator():
    dw = FakeDw([fn("__rust_alloc", 0x1000),
                 fn("os::nodefusion_heap::ObservedHeap::alloc", 0x2000)],
                types=["os::nodefusion_heap::ObservedHeap"])
    rules = [
        WatchSpec(subsystem="heap", match={"fn": ["__rust_alloc"]},
                  skip=True, when={"type_exists": "os::nodefusion_heap::ObservedHeap"}),
        WatchSpec(subsystem="heap", match={"module": "os::nodefusion_heap",
                                                 "fn": ["alloc"]},
                  when={"type_exists": "os::nodefusion_heap::ObservedHeap"}),
        WatchSpec(subsystem="heap", match={"fn": ["__rust_alloc"]}),
    ]
    assert [entry.path for entry in select(dw, rules).picked] == [
        "os::nodefusion_heap::ObservedHeap::alloc"]

def test_dwarf_keeps_decl_file_even_when_the_symbol_wins_the_path():
    dw = FakeDw([fn("kalloc", 0x80001000, decl_file="kernel/kalloc.c")])
    got = {c.addr: c for c in candidates(dw, [FakeSym("kalloc", 0x80001000)])}
    assert got[0x80001000].decl_file == "kernel/kalloc.c"


def test_a_function_only_dwarf_knows_is_still_a_candidate():
    dw = FakeDw([fn("os::task::helper", 0x9000)])
    got = [c.path for c in candidates(dw, [])]
    assert got == ["os::task::helper"]


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

def test_a_no_mangle_symbol_stays_matchable_under_its_abi_name():
    dw = FakeDw([fn("os::lang_items::panic", 0x8020a2f8)])
    syms = [FakeSym("rust_begin_unwind", 0x8020a2f8)]
    sel = select(dw, [w("panic", {"fn": ["rust_begin_unwind"]})], symbols=syms)
    assert [s.addr for s in sel.picked] == [0x8020a2f8]


def test_the_compiler_bucket_does_not_steal_a_function_from_its_crate():
    addr = 0xFFFFFFC08020FD66
    dw = FakeDw([fn("axalloc::default_impl::_::__rust_alloc", addr)])
    syms = [FakeSym("_RNvCsfgbAw4TbAFe_7___rustc12___rust_alloc", addr)]

    sel = select(dw, [w("ax-alloc", {"module": "axalloc"})], symbols=syms)
    assert [s.addr for s in sel.picked] == [addr]
    assert sel.picked[0].path == "axalloc::default_impl::_::__rust_alloc"

    sel2 = select(dw, [w("ax-alloc", {"fn": ["__rust_alloc"]})], symbols=syms)
    assert [s.addr for s in sel2.picked] == [addr]


def test_an_assembly_function_is_reachable_through_its_v0_symbol():
    addr = 0xFFFFFFC08020F184
    sel = select(
        FakeDw([]), [w("ax-cpu", {"module": "axcpu"})],
        symbols=[FakeSym(
            "_RNvNtNtCsjYlnCewdh4Q_5axcpu5riscv7context14context_switch", addr)])
    assert [(s.name, s.addr) for s in sel.picked] == [("context_switch", addr)]


def test_icf_folding_does_not_let_one_name_erase_the_other():
    dw = FakeDw([])
    mangled = "_ZN2os2mm14heap_allocator18handle_alloc_error17h2222222222222222E"
    for order in ([FakeSym("__rust_alloc_error_handler", 0x8020e1f0),
                   FakeSym(mangled, 0x8020e1f0)],
                  [FakeSym(mangled, 0x8020e1f0),
                   FakeSym("__rust_alloc_error_handler", 0x8020e1f0)]):
        sel = select(dw, [w("panic", {"fn": ["__rust_alloc_error_handler"]})],
                     symbols=order)
        assert [s.addr for s in sel.picked] == [0x8020e1f0], order[0].name
        sel2 = select(dw, [w("mm", {"fn": ["handle_alloc_error"]})],
                      symbols=order)
        assert [s.addr for s in sel2.picked] == [0x8020e1f0], order[0].name


def test_mapping_symbols_are_not_functions():
    dw = FakeDw([])
    syms = [FakeSym("$x.0", 0x8020e1f0),
            FakeSym("__rust_alloc_error_handler", 0x8020e1f0),
            FakeSym("$x.1", 0x8020e200)]
    got = {c.addr: c for c in candidates(dw, syms)}
    assert got[0x8020e1f0].path == "__rust_alloc_error_handler"
    assert 0x8020e200 not in got


def test_assembler_local_labels_do_not_become_watchpoint_names():
    dw = FakeDw([])
    syms = [FakeSym(".L0 ", 0xFFFFFFC0802005CA),
            FakeSym("__rust_alloc_error_handler", 0xFFFFFFC0802005CA),
            FakeSym(".LBB3_1", 0xFFFFFFC080200600)]
    sel = select(dw, [w("panic", {"fn": ["__rust_alloc_error_handler"]})],
                 symbols=syms)
    assert [s.name for s in sel.picked] == ["__rust_alloc_error_handler"]
    assert 0xFFFFFFC080200600 not in {c.addr for c in candidates(dw, syms)}


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

def test_two_different_functions_named_find_both_get_selected():
    dw = FakeDw([fn("easy_fs::vfs::Inode::find", 0x1000),
                 fn("os::fs::table::Table::find", 0x2000)])
    sel = select(dw, [w("fs", {"module": ["easy_fs", "os::fs"]})])
    assert [(s.name, s.addr) for s in sel.picked] == [
        ("find", 0x1000), ("Table::find", 0x2000)]


def test_identical_paths_at_different_addresses_are_both_kept():
    dw = FakeDw([fn("os::sync::UPSafeCell::exclusive_access", 0x1000),
                 fn("os::sync::UPSafeCell::exclusive_access", 0x2000)])
    sel = select(dw, [w("sync", {"module": "os::sync"})])
    assert [s.name for s in sel.picked] == [
        "exclusive_access", "UPSafeCell::exclusive_access"]


def test_the_same_address_is_never_selected_twice():
    dw = FakeDw([fn("os::task::spawn", 0x1000)])
    sel = select(dw, [w("a", {"module": "os::task"}),
                      w("b", {"module": "os::task"})])
    assert [s.subsystem for s in sel.picked] == ["a"]


def test_nested_inline_paths_at_one_address_remain_matchable():
    addr = 0xFFFFFFFF802CB306
    dw = FakeDw([])
    dw.inline_sites = [
        InlineSite("unlikely", "core::intrinsics::unlikely", addr),
        InlineSite("map_page",
                   "page_table_generic::table::PageTableRef::map_page", addr),
    ]
    got = [c.path for c in candidates(dw) if c.addr == addr]
    assert got == ["core::intrinsics::unlikely",
                   "page_table_generic::table::PageTableRef::map_page"]

    rule = WatchSpec(
        subsystem="mm",
        match={"module": "page_table_generic::table", "fn": ["map_page"]},
        inlined=True,
    )
    picked = select(dw, [rule]).picked
    assert [(s.addr, s.path) for s in picked] == [
        (addr, "page_table_generic::table::PageTableRef::map_page")]


def test_two_matching_inline_meanings_still_make_one_watchpoint():
    addr = 0x1000
    dw = FakeDw([])
    dw.inline_sites = [
        InlineSite("outer", "crate::outer", addr),
        InlineSite("inner", "crate::inner", addr),
    ]
    picked = select(dw, [WatchSpec(
        subsystem="t", match={"module": "crate"}, inlined=True)]).picked
    assert [(s.addr, s.path) for s in picked] == [(addr, "crate::outer")]


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

def test_module_matches_exactly_or_as_a_prefix_segment():
    dw = FakeDw([fn("axtask", 0x1000), fn("axtask::run_queue::spawn", 0x2000),
                 fn("axtask_extra::helper", 0x3000)])
    sel = select(dw, [w("t", {"module": "axtask"})])
    assert sorted(s.addr for s in sel.picked) == [0x1000, 0x2000]


def test_module_prefix_with_star_derives_the_subsystem_from_the_path():
    dw = FakeDw([fn("subsystems::vfs::open", 0x1000),
                 fn("subsystems::net::send", 0x2000)])
    sel = select(dw, [w("*", {"module_prefix": "subsystems::"})])
    assert sorted((s.subsystem, s.name) for s in sel.picked) == [
        ("net", "send"), ("vfs", "open")]


def test_a_list_of_crates_with_star_names_each_point_after_its_own_crate():
    dw = FakeDw([fn("mem::alloc_frame", 0x1000),
                 fn("vfs::open", 0x2000),
                 fn("ksync::Mutex::lock", 0x3000),
                 fn("subsystems::mem::alloc_frame", 0x4000)])
    sel = select(dw, [w("*", {"module": ["mem", "vfs", "ksync"]})])
    assert sorted((s.subsystem, s.addr) for s in sel.picked) == [
        ("ksync", 0x3000), ("mem", 0x1000), ("vfs", 0x2000)]


def test_a_crate_name_does_not_prefix_match_a_longer_crate_name():
    dw = FakeDw([fn("mem::alloc", 0x1000), fn("mem_extra::alloc", 0x2000)])
    sel = select(dw, [w("*", {"module": ["mem", "vfs"]})])
    assert [s.addr for s in sel.picked] == [0x1000]


def test_file_matches_by_suffix_because_dwarf_paths_vary():
    dw = FakeDw([fn("kalloc", 0x1000, decl_file="/build/xv6/kernel/kalloc.c"),
                 fn("kfree", 0x2000, decl_file="kernel/kalloc.c"),
                 fn("bread", 0x3000, decl_file="kernel/bio.c")])
    sel = select(dw, [w("mem", {"file": "kernel/kalloc.c"})])
    assert sorted(s.addr for s in sel.picked) == [0x1000, 0x2000]


def test_fn_globs_narrow_within_the_matched_scope():
    dw = FakeDw([fn("axtask::spawn", 0x1000), fn("axtask::spawn_raw", 0x2000),
                 fn("axtask::yield_now", 0x3000)])
    sel = select(dw, [w("t", {"module": "axtask", "fn": ["spawn*"]})])
    assert sorted(s.addr for s in sel.picked) == [0x1000, 0x2000]


def test_an_empty_match_selects_nothing_rather_than_everything():
    dw = FakeDw([fn("os::task::spawn", 0x1000)])
    sel = select(dw, [w("t", {})])
    assert sel.picked == []
    assert len(sel.empty_rules) == 1


def test_a_rule_that_matches_nothing_is_reported():
    dw = FakeDw([fn("axtask::spawn", 0x1000)])
    sel = select(dw, [w("t", {"module": "ax_task"})])
    assert sel.picked == []
    assert "ax_task" in sel.empty_rules[0]


def test_matched_but_unaddressable_is_counted_apart_from_not_matched():
    dw = FakeDw([fn("os::mm::inlined_away", None),
                 fn("os::mm::real", 0x1000)])
    sel = select(dw, [w("mm", {"module": "os::mm"})])
    assert [s.addr for s in sel.picked] == [0x1000]
    assert sel.no_address == {"mm": 1}
    assert sel.empty_rules == []


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path, want", [
    ("axtask::run_queue::{impl#1}::drop<NoPreempt>", "drop"),
    ("core::ptr::drop_in_place<axstd::thread::JoinHandle>", "drop_in_place"),
    ("kalloc", "kalloc"),
])
def test_bare_name_strips_generics_before_taking_the_last_segment(path, want):
    assert bare_name(path) == want


def test_args_and_throttle_come_from_the_rule_that_matched():
    dw = FakeDw([fn("os::syscall::sys_write", 0x1000),
                 fn("os::mm::alloc", 0x2000)])
    sel = select(dw, [w("syscall", {"module": "os::syscall"}, args=3),
                      w("mm", {"module": "os::mm"}, throttle=64)])
    got = {s.name: (s.args, s.throttle) for s in sel.picked}
    assert got == {"sys_write": (3, 0), "alloc": (2, 64)}


def test_cand_names_lists_the_bare_name_first():
    c = Cand(path="os::lang_items::panic", addr=1,
             aliases=("rust_begin_unwind",))
    assert c.names == ("panic", "rust_begin_unwind")


def test_snapshot_comes_from_the_rule_and_first_match_wins():
    dw = FakeDw([fn("kfork", 0x1000, decl_file="kernel/proc.c"),
                 fn("scheduler", 0x2000, decl_file="kernel/proc.c")])
    rules = [WatchSpec("proc", {"fn": ["fork", "kfork"]}, snapshot="event"),
             w("proc", {"file": "kernel/proc.c"})]
    got = {s.name: s.snapshot for s in select(dw, rules).picked}
    assert got == {"kfork": "event", "scheduler": "none"}


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

def test_build_from_manifest_maps_snapshot_onto_snap_and_throttle():
    from nodefusion.host.watchlist import build_from_manifest

    class FakeElf:
        symbols = [FakeSym("panic", 0x1000), FakeSym("kfork", 0x2000),
                   FakeSym("scheduler", 0x3000)]

        def sym(self, n):
            return next((s for s in self.symbols if s.name == n), None)

        def functions(self):
            return self.symbols

    for s in FakeElf.symbols:
        s.is_func, s.sym_type = True, 2

    dw = FakeDw([fn("panic", 0x1000, decl_file="kernel/printf.c"),
                 fn("kfork", 0x2000, decl_file="kernel/proc.c"),
                 fn("scheduler", 0x3000, decl_file="kernel/proc.c")])
    watches = [
        WatchSpec("panic", {"fn": ["panic"]}, snapshot="always"),
        WatchSpec("proc", {"fn": ["kfork"]}, snapshot="event"),
        WatchSpec("proc", {"file": "kernel/proc.c"}),
    ]
    wl = build_from_manifest(FakeElf(), dw, watches)
    got = {e.name: (e.snap, e.throttle) for e in wl.entries}
    assert got == {"panic": (True, False), "kfork": (True, True),
                   "scheduler": (False, False)}
    assert any("nftrace_commit_point" in m for m in wl.missing)


def test_args_and_rate_survive_into_the_watchlist():
    from nodefusion.host.watchlist import build_from_manifest

    class FakeElf:
        symbols = [FakeSym("walk", 0x1000)]

        def sym(self, n):
            return next((s for s in self.symbols if s.name == n), None)

        def functions(self):
            return self.symbols

    for s in FakeElf.symbols:
        s.is_func, s.sym_type = True, 2

    dw = FakeDw([fn("walk", 0x1000, decl_file="kernel/vm.c")])
    wl = build_from_manifest(FakeElf(), dw, [
        WatchSpec("vm", {"file": "kernel/vm.c"}, args=3, throttle=64)])
    e = next(x for x in wl.entries if x.name == "walk")
    assert (e.args, e.rate, e.throttle, e.snap) == (3, 64, False, False)
    assert wl.to_json()["entries"][0]["rate"] == 64


def test_event_operation_survives_into_the_watchlist():
    from nodefusion.host.watchlist import build_from_manifest

    class FakeElf:
        symbols = [FakeSym("read_block", 0x1000)]

        def sym(self, n):
            return next((s for s in self.symbols if s.name == n), None)

    for s in FakeElf.symbols:
        s.is_func, s.sym_type = True, 2

    dw = FakeDw([fn("device::read_block", 0x1000)])
    wl = build_from_manifest(
        FakeElf(), dw, [w("disk", {"fn": ["read_block"]})],
        events={"device::read_block": EventSpec(
            kind="disk.io", operation="read")})
    assert wl.entries[0].operation == "read"
    assert wl.to_json()["entries"][0]["operation"] == "read"


def test_event_classifier_survives_into_the_watchlist():
    """Runtime classification must not depend on whichever manifest is installed later."""
    from nodefusion.host.watchlist import build_from_manifest

    class FakeElf:
        symbols = [FakeSym("sys_clone", 0x1000)]

        def sym(self, n):
            return next((s for s in self.symbols if s.name == n), None)

    for s in FakeElf.symbols:
        s.is_func, s.sym_type = True, 2

    dw = FakeDw([fn("kernel::sys_clone", 0x1000)])
    classifier = {"arg": "flags", "mask": 0x10000, "set": "thread.create"}
    wl = build_from_manifest(
        FakeElf(), dw, [w("proc", {"fn": ["sys_clone"]})],
        events={"kernel::sys_clone": EventSpec(
            kind="proc.fork", args=["return_slot", "uctx", "flags"],
            classify=classifier)})
    assert wl.entries[0].classify == classifier
    assert wl.to_json()["entries"][0]["classify"] == classifier


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

def _load(tmp_path, body: str):
    from nodefusion.model.manifest import load
    p = tmp_path / "k.toml"
    p.write_text('[kernel]\nname = "k"\n\n' + body, encoding="utf-8")
    return load(p)


def test_a_misspelt_match_key_is_rejected(tmp_path):
    with pytest.raises(ManifestError) as e:
        _load(tmp_path, '[[watch]]\nsubsystem = "t"\n'
                        'match = { modul = "axtask" }\n')
    assert "modul" in str(e.value) and "module" in str(e.value)


def test_a_watch_without_match_is_rejected(tmp_path):
    with pytest.raises(ManifestError) as e:
        _load(tmp_path, '[[watch]]\nsubsystem = "t"\n')
    assert "match" in str(e.value)


def test_an_unknown_snapshot_kind_is_rejected(tmp_path):
    with pytest.raises(ManifestError) as e:
        _load(tmp_path, '[[watch]]\nsubsystem = "t"\n'
                        'match = { fn = ["x"] }\nsnapshot = "sometimes"\n')
    assert "sometimes" in str(e.value)


def test_a_valid_watch_block_round_trips(tmp_path):
    mf = _load(tmp_path, '[[watch]]\nsubsystem = "t"\n'
                         'match = { module = "axtask", fn = ["spawn*"] }\n'
                         'args = 3\nthrottle = 64\nsnapshot = "event"\n')
    assert len(mf.watches) == 1
    got = mf.watches[0]
    assert (got.subsystem, got.args, got.throttle, got.snapshot) == (
        "t", 3, 64, "event")


def test_event_operation_is_closed_and_round_trips(tmp_path):
    mf = _load(tmp_path, '[event]\n'
                         'read_block = { kind = "disk.io", operation = "read" }\n')
    assert mf.events["read_block"].operation == "read"

    with pytest.raises(ManifestError) as e:
        _load(tmp_path, '[event]\n'
                        'read_block = { kind = "disk.io", operation = "fetch" }\n')
    assert "operation" in str(e.value) and "fetch" in str(e.value)

    with pytest.raises(ManifestError) as e:
        _load(tmp_path, '[event]\n'
                        'read_block = { kind = "bcache.read", operation = "read" }\n')
    assert "disk.io" in str(e.value) and "bcache.read" in str(e.value)


def test_a_skip_rule_removes_functions_from_every_later_rule():
    dw = FakeDw([fn("mycpu", 0x10), fn("fork", 0x20)])
    picked = select(dw, [
        WatchSpec(subsystem="proc", match={"fn": ["mycpu"]}, skip=True),
        WatchSpec(subsystem="proc", match={"fn": ["mycpu", "fork"]}),
    ]).picked
    assert [s.name for s in picked] == ["fork"]


def test_a_skip_rule_placed_after_a_broad_rule_does_nothing():
    dw = FakeDw([fn("mycpu", 0x10)])
    picked = select(dw, [
        WatchSpec(subsystem="proc", match={"fn": ["mycpu"]}),
        WatchSpec(subsystem="proc", match={"fn": ["mycpu"]}, skip=True),
    ]).picked
    assert [s.name for s in picked] == ["mycpu"]


def test_skip_and_snapshot_together_are_rejected(tmp_path):
    with pytest.raises(ManifestError) as e:
        _load(tmp_path, '[[watch]]\nsubsystem = "t"\n'
                        'match = { fn = ["x"] }\nskip = true\n'
                        'snapshot = "always"\n')
    assert "skip" in str(e.value)


def test_skip_round_trips_through_the_manifest(tmp_path):
    mf = _load(tmp_path, '[[watch]]\nsubsystem = "t"\n'
                         'match = { fn = ["mycpu", "cpuid"] }\nskip = true\n')
    assert mf.watches[0].skip is True


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent.parent
def _archived(kind: str):
    from nodefusion.host.kernels import archived_elf
    p = archived_elf(kind)
    return p if p is not None else pathlib.Path(f"/nonexistent/{kind}.elf")
_XV6 = _archived("xv6")

needs_xv6 = pytest.mark.skipif(
    not _XV6.exists(),
    reason=f"要 xv6 teacher 内核 ELF（{_XV6}），是 build 产物，没有就跳过")


def test_the_builtin_manifest_dir_is_findable_from_the_package():
    d = builtin_dir()
    assert d.is_dir(), d
    got = load_dir(d)
    assert {"xv6", "rcore"} <= set(got)


@needs_xv6
def test_the_default_is_the_rules_now():
    wl, source, trace = select_watchlist(Elf64(_XV6), _XV6, kind="xv6")
    assert source == "manifest:xv6"
    assert wl.entries
    assert any("xv6: 匹配" in t for t in trace)


@needs_xv6
def test_the_table_path_says_it_is_the_table():
    elf = Elf64(_XV6)
    wl, source, trace = select_watchlist(
        elf, _XV6, kind="xv6", prefer_table=True)
    assert source == "table"
    assert trace == []
    assert wl.entries


@needs_xv6
def test_the_manifest_path_covers_every_watchpoint_the_table_had():
    elf = Elf64(_XV6)
    table, _, _ = select_watchlist(elf, _XV6, kind="xv6", prefer_table=True)
    rules, source, trace = select_watchlist(elf, _XV6, kind="xv6")

    assert source == "manifest:xv6"
    assert any("xv6: 匹配" in t for t in trace)

    lost = {e.addr for e in table.entries} - {e.addr for e in rules.entries}
    assert not lost, sorted(hex(a) for a in lost)


@needs_xv6
def test_a_kernel_with_no_table_just_works(monkeypatch):
    wl, source, _ = select_watchlist(Elf64(_XV6), _XV6, kind="arceos")
    assert source == "manifest:xv6"
    assert wl.entries


@needs_xv6
def test_asking_for_a_table_that_does_not_exist_stops(monkeypatch):
    with pytest.raises(RecordError) as e:
        select_watchlist(Elf64(_XV6), _XV6, kind="arceos", prefer_table=True)
    assert "没有名为 'arceos' 的名单" in str(e.value)
    assert "rcore" in str(e.value) and "xv6" in str(e.value)


@needs_xv6
def test_an_unrecognised_kernel_stops_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr("nodefusion.model.manifest.load_dir", lambda d: {})
    with pytest.raises(RecordError) as e:
        select_watchlist(Elf64(_XV6), _XV6, kind="xv6")
    assert "认不出" in str(e.value)


@needs_xv6
def test_the_manifest_path_does_not_thin_anything_the_table_watched():
    elf = Elf64(_XV6)
    table, _, _ = select_watchlist(elf, _XV6, kind="xv6", prefer_table=True)
    rules, _, _ = select_watchlist(elf, _XV6, kind="xv6")

    by_addr = {e.addr: e for e in rules.entries}
    thinned = [(e.name, by_addr[e.addr].rate) for e in table.entries
               if e.addr in by_addr and by_addr[e.addr].rate]
    assert not thinned, thinned


@needs_xv6
def test_lint_warnings_ride_along_in_the_detection_trace(monkeypatch):
    monkeypatch.setattr("nodefusion.model.manifest.lint",
                        lambda m: ["第 2 条 watch 永远轮不到"])
    _, source, trace = select_watchlist(Elf64(_XV6), _XV6, kind="xv6")
    assert source == "manifest:xv6"
    assert any("lint：第 2 条 watch 永远轮不到" in t for t in trace)


@needs_xv6
def test_a_lint_warning_does_not_stop_the_recording(monkeypatch):
    monkeypatch.setattr("nodefusion.model.manifest.lint",
                        lambda m: ["随便什么可疑写法"])
    wl, _, _ = select_watchlist(Elf64(_XV6), _XV6, kind="xv6")
    assert wl.entries



from nodefusion.tests import kernelelf as _ke

_RCORE = _ke.kernel_elf("rcore")
needs_rcore = _ke.needs("rcore")


@needs_xv6
def test_build_refuses_to_guess_which_table_you_meant():
    from nodefusion.host import watchlist as W
    with pytest.raises(TypeError):
        W.build(Elf64(_XV6))          # type: ignore[call-arg]


@needs_rcore
def test_a_table_that_matches_nothing_is_a_wrong_table_not_a_thin_one():
    from nodefusion.host import watchlist as W
    with pytest.raises(ValueError, match="一个都没解出来"):
        W.build(Elf64(str(_RCORE)), kind="xv6")


@needs_rcore
def test_the_right_table_on_the_same_elf_still_works():
    from nodefusion.host import watchlist as W
    wl = W.build(Elf64(str(_RCORE)), kind="rcore")
    assert len(wl.entries) > 20, "换对名单也解不出来，那问题在别处"



def test_an_unrecognised_kernel_dir_is_not_probed_as_xv6(tmp_path):
    from nodefusion.host.layout import LayoutError, probe

    (tmp_path / "src").mkdir()
    (tmp_path / "Cargo.toml").write_text("[package]\nname='axos'\n")

    with pytest.raises(LayoutError, match="认不出"):
        probe(tmp_path, sh=None)      # type: ignore[arg-type]


def test_the_error_says_where_to_go_instead():
    from nodefusion.host.layout import LayoutError, probe
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        try:
            probe(Path(d), sh=None)   # type: ignore[arg-type]
        except LayoutError as e:
            msg = str(e)
        else:
            pytest.fail("认不出的内核居然没报错")

    assert "manifest" in msg
    assert "--layout-override" in msg



_ALLOC_PAGES = ("_RNvMs2_NtCsgJF2hh0hqRz_8ax_alloc10buddy_slab"
                "NtB5_15GlobalAllocator11alloc_pages")


def test_a_v0_inherent_impl_is_reachable_by_a_module_rule():
    dw = FakeDw([fn("ax_alloc::buddy_slab::alloc_pages", None)])
    syms = [FakeSym(_ALLOC_PAGES, 0x80413970)]
    got = select(dw, [w("ax-alloc", {"module": "ax_alloc"})], symbols=syms)
    assert [(s.name, s.addr) for s in got.picked] == [("alloc_pages", 0x80413970)]
    assert got.picked[0].path == "ax_alloc::buddy_slab::GlobalAllocator::alloc_pages"


def test_dwarf_still_wins_the_spelling_when_it_has_the_address():
    dw = FakeDw([fn("ax_alloc::buddy_slab::{impl#5}::alloc_pages", 0x80413970)])
    got = {c.addr: c for c in candidates(dw, [FakeSym(_ALLOC_PAGES, 0x80413970)])}
    assert got[0x80413970].path == "ax_alloc::buddy_slab::{impl#5}::alloc_pages"
