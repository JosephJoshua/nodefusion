
from __future__ import annotations

import struct

import pytest

from nodefusion.host import guest as G

PG = G.PGSIZE
ENTRY_CODE = bytes(range(64))


class _Elf:

    def __init__(self, entry: int, code: bytes = ENTRY_CODE, vaddr: int | None = None):
        self.e_entry = entry
        seg_vaddr = entry if vaddr is None else vaddr
        d = entry - seg_vaddr
        body = b"\xaa" * d + code
        self.e_phoff, self.e_phentsize, self.e_phnum = 0, 56, 1
        ph = struct.pack("<IIQQQQQQ", 1, 5, 56, seg_vaddr, seg_vaddr,
                         len(body), len(body), PG)
        self.data = ph + body


def _ram(base: int = 0x8000_0000, mb: int = 4) -> G.RamImage:
    return G.RamImage(base, mb << 20)


def _place(ram: G.RamImage, pa: int, blob: bytes) -> None:
    idx = (pa - ram.base) // PG
    at = pa - ram.base - idx * PG
    page = bytearray(PG)
    page[at:at + len(blob)] = blob
    ram.apply({idx: bytes(page)})



def test_a_direct_mapped_kernel_is_found_at_its_entry(tmp_path):
    ram, entry = _ram(), 0x8000_0000
    _place(ram, entry, ENTRY_CODE)
    fit = ram.find_kernel_image(_Elf(entry))
    assert fit.found and fit.direct and fit.offset == 0 and fit.paddr == entry


def test_check_kernel_mapping_still_means_direct_mapped():
    ram, entry = _ram(), 0x8000_0000
    _place(ram, entry, ENTRY_CODE)
    assert ram.check_kernel_mapping(_Elf(entry)) is True



def test_a_higher_half_kernel_is_found_at_the_shifted_address():
    ram = _ram()
    entry, pa = 0xffff_ffc0_8020_0000, 0x8020_0000
    _place(ram, pa, ENTRY_CODE)
    fit = ram.find_kernel_image(_Elf(entry))
    assert fit.found and fit.paddr == pa
    assert fit.offset == 0xffff_ffc0_0000_0000


def test_finding_it_elsewhere_is_not_a_direct_mapping():
    ram = _ram()
    _place(ram, 0x8020_0000, ENTRY_CODE)
    assert ram.find_kernel_image(_Elf(0xffff_ffc0_8020_0000)).direct is False


def test_finding_it_at_all_proves_the_elf_pairs():
    ram = _ram()
    _place(ram, 0x8020_0000, ENTRY_CODE)
    assert ram.find_kernel_image(_Elf(0xffff_ffc0_8020_0000)).found is True


def test_the_page_offset_of_the_entry_is_preserved():
    ram = _ram()
    entry, pa = 0xffff_ffc0_8020_0100, 0x8020_0100
    _place(ram, pa, ENTRY_CODE)
    fit = ram.find_kernel_image(_Elf(entry, vaddr=entry - 0x100))
    assert fit.found and fit.paddr == pa



def test_an_elf_that_is_nowhere_is_reported_as_not_found():
    ram = _ram()
    _place(ram, 0x8020_0000, b"\x99" * 64)
    fit = ram.find_kernel_image(_Elf(0x8020_0000))
    assert not fit.found and "找不到" in fit.reason


def test_unobserved_pages_are_not_counted_as_mismatches():
    ram = _ram()
    assert not ram.find_kernel_image(_Elf(0x8020_0000)).found



def test_two_matches_are_reported_as_ambiguous():
    ram = _ram()
    _place(ram, 0x8020_0000, ENTRY_CODE)
    _place(ram, 0x8030_0000, ENTRY_CODE)
    fit = ram.find_kernel_image(_Elf(0xffff_ffc0_8020_0000))
    assert fit.ambiguous and not fit.direct and "不止一处" in fit.reason


def test_an_elf_without_an_entry_says_so():
    fit = _ram().find_kernel_image(_Elf(0))
    assert not fit.found and "e_entry" in fit.reason


def test_an_entry_outside_every_load_segment_says_so():
    e = _Elf(0x8020_0000)
    e.e_entry = 0x9000_0000
    fit = _ram().find_kernel_image(e)
    assert not fit.found and "PT_LOAD" in fit.reason



@pytest.mark.corpus
def test_the_real_runs_split_into_the_three_cases():
    import json
    from pathlib import Path

    from nodefusion.host import nftrace as T
    from nodefusion.host.nfelf import Elf64

    runs = Path(__file__).resolve().parents[1] / "runs"
    if not runs.is_dir():
        pytest.skip("这台机器上没有录好的 run")

    from conftest import corpus_run_dirs

    seen = set()
    for d in corpus_run_dirs(runs):
        man = d / "manifest.json"
        if not man.is_file():
            continue
        elfp = json.loads(man.read_text(encoding="utf-8")).get("kernel_elf")
        if not elfp or not Path(elfp).is_file() or not (d / "trace.nfb").is_file():
            continue
        tr = T.load(str(d / "trace.nfb"))
        if not tr.snapshots:
            continue
        ram = G.RamImage(tr.snapshots[0].ram_base,
                         max(s.pages_total for s in tr.snapshots) * PG)
        for s in tr.snapshots:
            ram.apply(s.pages)
        f = ram.find_kernel_image(Elf64(elfp))
        seen.add("direct" if f.direct else "shifted" if f.found else "missing")

    if not seen:
        pytest.skip("没有一个 run 的 kernel_elf 还在这台机器上")
    assert "direct" in seen and "shifted" in seen
