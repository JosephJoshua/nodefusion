
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.tests.kernelelf import elf_or_skip

MANIFEST = (Path(__file__).resolve().parents[2]
            / "nodefusion/manifests/rcore.toml")

PAIRS = [
    ("os::mm::frame_allocator::frame_dealloc",
     "os::mm::frame_allocator::frame_alloc", "phys.alloc"),
    ("os::mm::page_table::PageTable::map",
     "os::mm::page_table::PageTable::unmap", "pagetable.unmap"),
]


def _elf_or_skip() -> Path:
    return elf_or_skip("rcore")


def _paths() -> set[str]:
    from nodefusion.host.nfelf import Elf64
    from nodefusion.model.symbols import demangle
    e = Elf64(str(_elf_or_skip()))
    return {demangle(s.name) or s.name for s in e.functions()}


def test_one_half_of_each_pair_has_a_symbol_and_the_other_does_not():
    paths = _paths()
    for kept, gone, _ in PAIRS:
        assert kept in paths, f"{kept} 不见了 —— 换构建了？manifest 那段要重写"
        assert gone not in paths, (
            f"{gone} 这回有符号了 —— 那 rcore.toml 里"
            f"「这个构建里它只有内联点」那段就过时了，去按新构建重写")


def test_the_half_without_a_symbol_still_has_addresses_in_dwarf():
    from nodefusion.model.dwarfsrc import DwarfSource
    dw = DwarfSource(_elf_or_skip())
    for _, gone, _ in PAIRS:
        sites = [s for s in dw.inline_sites if s.path == gone]
        assert sites, (
            f"{gone} 在 DWARF 里一处内联点都没有。要么构建变了，要么"
            f"`DwarfSource` 又漏读了一段 —— 先看 inline_sites_dropped="
            f"{dw.inline_sites_dropped}，墓碑值被当成真地址过一次")


def test_the_mapping_for_the_inlined_half_is_live():
    import json
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist
    elf = _elf_or_skip()
    wl, _, _ = select_watchlist(Elf64(str(elf)), elf, kind="rcore")
    kinds = {e.kind for e in wl.entries if e.kind}
    text = MANIFEST.read_text()
    for kept, gone, kind in PAIRS:
        assert f'"{kept}" = ' in text, f"{kept} 没映射到任何事件类别"
        assert f'"{gone}" = ' in text, (
            f"{gone} 没映射 —— 它在这个构建里是能观测的（见上一条），"
            f"缺映射就是白丢一个语义")
        assert kind in kinds, (
            f"manifest 把 {gone} 映射成了 {kind}，但选出来的观察点里没有这个"
            f"类别。多半是那条 `inlined = true` 的规则没匹配上它 —— "
            f"失配是无声的，所以在这儿拦")


def test_the_manifest_says_why_rather_than_leaving_a_hole():
    text = MANIFEST.read_text()
    assert "inline" in text, "manifest must document the inline-only mapping"
    assert "DW_TAG_inlined_subroutine" in text, (
        "manifest must identify the DWARF inline provenance")
    for _, gone, _ in PAIRS:
        short = gone.rsplit("::", 1)[1]
        assert short in text, f"manifest does not name {short}"
