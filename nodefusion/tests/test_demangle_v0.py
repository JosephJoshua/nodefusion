
from __future__ import annotations

import pytest

from nodefusion.model.symbols import demangle, demangle_v0, is_synthetic_path


GOOD = [
    ("_RNvNtNtCsjYlnCewdh4Q_5axcpu5riscv7context14context_switch",
     "axcpu::riscv::context::context_switch"),
    ("_RNvNtNtCsjYlnCewdh4Q_5axcpu5riscv4init9init_trap",
     "axcpu::riscv::init::init_trap"),
    ("_RNvNtNtCsjYlnCewdh4Q_5axcpu5riscv4trap17handle_page_fault",
     "axcpu::riscv::trap::handle_page_fault"),
    ("_RNvNtNtCskEMqVauhSLE_5axstd2io5stdio12___print_impl",
     "axstd::io::stdio::__print_impl"),
    ("_RNvNtCs8MUOdSUZJDZ_6axtask3api4exit", "axtask::api::exit"),
]


@pytest.mark.parametrize("mangled,path", GOOD)
def test_plain_paths_come_out_verbatim(mangled, path):
    assert demangle_v0(mangled) == path


@pytest.mark.parametrize("mangled,path", GOOD)
def test_demangle_dispatches_to_v0(mangled, path):
    assert demangle(mangled) == path


def test_a_crate_root_alone_is_a_path():
    assert demangle_v0("_RNvCsfgbAw4TbAFe_7___rustc17rust_begin_unwind") \
        == "__rustc::rust_begin_unwind"



DECLINED = {
    "泛型实参": "_RINvNtCsivw7crLiTTs_4core3ptr13drop_in_placeINtNtCslAbAbPWKaMU_"
              "14event_listener3sys9ListGuarduEECskEMqVauhSLE_5axstd",
    "反向引用": "_RNvMsn_NtCs5OyQsprxpnx_5alloc4syncINtB5_3ArcINtNtNtCskEMqVauhSLE_"
              "5axstd6thread5multi6PacketlEE9drop_slowCsb8MtakFV5HR_16arceos_childtask",
    "trait impl": "_RNvXs1g_NtCsivw7crLiTTs_4core3fmtRlNtB6_5Debug3fmtCsb8MtakFV5HR_"
                  "16arceos_childtask",
    "空串": "",
    "不是 Rust 修饰": "memcpy",
    "旧版修饰不该走这条": "_ZN2os4mainE",
    "将来的编码版本": "_R1NvC5axcpu4main",
    "punycode": "_RNvNtCs1234_5cratau1ax_4main",
}


@pytest.mark.parametrize("why,sym", sorted(DECLINED.items()))
def test_what_it_will_not_guess_at(why, sym):
    assert demangle_v0(sym) is None, why


def test_a_truncated_name_is_not_half_decoded():
    assert demangle_v0("_RNvNtNtCsjYlnCewdh4Q_5axcpu5riscv7context14conte") is None


def test_a_path_that_does_not_use_up_the_whole_string_is_refused():
    ok = "_RNvNtCs8MUOdSUZJDZ_6axtask3api4exit"
    assert demangle_v0(ok) == "axtask::api::exit"
    assert demangle_v0(ok + "Csb8MtakFV5HR_16arceos_childtask") is None




def test_the_compiler_bucket_is_recognised_as_not_a_real_crate():
    assert is_synthetic_path("__rustc::__rust_alloc")
    assert is_synthetic_path("__rustc::rust_begin_unwind")
    assert not is_synthetic_path("axalloc::default_impl::_::__rust_alloc")
    assert not is_synthetic_path("")



GOOD_IMPL = [
    ("_RNvMs2_NtCsgJF2hh0hqRz_8ax_alloc10buddy_slabNtB5_15GlobalAllocator11alloc_pages",
     "ax_alloc::buddy_slab::GlobalAllocator::alloc_pages"),
    ("_RNvMs2_NtCsgJF2hh0hqRz_8ax_alloc10buddy_slabNtB5_15GlobalAllocator13dealloc_pages",
     "ax_alloc::buddy_slab::GlobalAllocator::dealloc_pages"),
]


@pytest.mark.parametrize("mangled,path", GOOD_IMPL)
def test_inherent_impl_needs_the_flag(mangled, path):
    assert demangle_v0(mangled, impls=True) == path
    assert demangle_v0(mangled) is None
    assert demangle(mangled) is None


def test_backref_only_points_backwards():
    ok = "_RNvMs2_NtCsgJF2hh0hqRz_8ax_alloc10buddy_slabNtB5_15GlobalAllocator11alloc_pages"
    assert demangle_v0(ok, impls=True) is not None
    bad = ok.replace("NtB5_15GlobalAllocator", "NtBz_15GlobalAllocator")
    assert demangle_v0(bad, impls=True) is None


def test_trait_impl_still_refuses():
    x = ("_RNvXNtCs4CTdTkWKlqf_5ax_mm7backendNtB2_7BackendNtNtCs9lWT2njJ6Ae_"
         "13ax_memory_set7backend14MappingBackend3map")
    assert demangle_v0(x, impls=True) is None
    assert demangle_v0(x) is None


def test_a_trailing_instantiating_crate_is_refused():
    s = ("_RNvMs2_NtCsi9evzWap6xG_20buddy_slab_allocator5buddyNtB5_"
         "14BuddyAllocator11alloc_pagesCsgJF2hh0hqRz_8ax_alloc")
    assert demangle_v0(s, impls=True) is None



JBD2_COMMIT = ("_RNvMs0_NtNtCsfIx1CLPCe0Y_6rsext48blockdev7journalINtB5_7Jbd2Dev"
               "NtNtNtNtCs55q5zN7B1Nk_8ax_fs_ng2fs4ext46rsext48Ext4DiskE6commitB17_")

CONST_GENERIC = ("_RINvMNtCsi9evzWap6xG_20buddy_slab_allocator5buddyNtB3_12BuddySection"
                 "37compute_region_layout_with_heap_alignKj1000_"
                 "ECsgJF2hh0hqRz_8ax_alloc")

PAGE_MAPS = (
    ("_RNvMs3_NtCs6i6v73ahkdy_18page_table_generic5tableINtB5_12PageTableRef"
     "NtNtCslSLvBP1Ll6j_6ax_cpu6paging14ArchPagingMeta"
     "NtNtCsccEvrMlVIC8_6ax_hal6paging15PagingAllocatorE8map_page"
     "Cs4CTdTkWKlqf_5ax_mm"),
    ("_RNvMs3_NtCs6i6v73ahkdy_18page_table_generic5tableINtB5_12PageTableRef"
     "NtNtCslSLvBP1Ll6j_6ax_cpu6paging14ArchPagingMeta"
     "NtNtCsccEvrMlVIC8_6ax_hal6paging15PagingAllocatorE8map_page"
     "CsbHqjjIBrUUW_13starry_kernel"),
)


def test_generic_instantiation_resolves_the_jbd2_commit():
    assert demangle_v0(JBD2_COMMIT, impls=True, generics=True) == \
        "rsext4::blockdev::journal::Jbd2Dev::commit"


def test_instantiating_crate_does_not_change_the_page_map_path():
    for mangled in PAGE_MAPS:
        assert demangle_v0(mangled, impls=True, generics=True) == \
            "page_table_generic::table::PageTableRef::map_page"


def test_the_new_constructs_stay_behind_the_generics_flag():
    assert demangle_v0(JBD2_COMMIT) is None
    assert demangle_v0(JBD2_COMMIT, impls=True) is None


def test_widening_never_changes_an_answer_it_already_had():
    for mangled, path in GOOD:
        assert demangle_v0(mangled) == path
        assert demangle_v0(mangled, impls=True, generics=True) == path


def test_trait_impl_resolves_only_once_generics_is_on():
    x = ("_RNvXNtCs4CTdTkWKlqf_5ax_mm7backendNtB2_7BackendNtNtCs9lWT2njJ6Ae_"
         "13ax_memory_set7backend14MappingBackend3map")
    assert demangle_v0(x, impls=True) is None
    assert demangle_v0(x, impls=True, generics=True) == "ax_mm::backend::Backend::map"


def test_malformed_generics_are_refused_not_guessed():
    assert demangle_v0(JBD2_COMMIT.replace("E6commitB17_", "6commitB17_"),
                       impls=True, generics=True) is None


def test_const_generic_and_its_backref_must_be_well_formed():
    assert demangle_v0(CONST_GENERIC, impls=True, generics=True) == \
        "buddy_slab_allocator::buddy::BuddySection::compute_region_layout_with_heap_align"
    # `Bzz_` decodes past the current position instead of back into the prefix.
    assert demangle_v0(CONST_GENERIC.replace("Kj1000_", "KBzz_"),
                       impls=True, generics=True) is None
