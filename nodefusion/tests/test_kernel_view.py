
from __future__ import annotations

from nodefusion.host import guest as G

PG = G.PGSIZE
BASE = 0x8000_0000
OFF = 0xffff_ffc0_0000_0000


def _ram(mb: int = 4) -> G.RamImage:
    return G.RamImage(BASE, mb << 20)


def _put(ram: G.RamImage, pa: int, blob: bytes) -> None:
    idx = (pa - ram.base) // PG
    at = pa - ram.base - idx * PG
    page = bytearray(PG)
    page[at:at + len(blob)] = blob
    ram.apply({idx: bytes(page)})



def test_a_kernel_virtual_address_reads_the_right_bytes():
    ram = _ram()
    _put(ram, 0x8020_0000, b"\x11\x22\x33\x44\x55\x66\x77\x88")
    v = G.KernelView(ram, OFF)
    assert v.u64(0xffff_ffc0_8020_0000) == 0x8877_6655_4433_2211


def test_the_raw_image_cannot_read_it_at_all():
    ram = _ram()
    _put(ram, 0x8020_0000, b"\x11" * 8)
    assert ram.u64(0xffff_ffc0_8020_0000) is None


def test_every_width_translates():
    ram = _ram()
    _put(ram, 0x8020_0000, bytes(range(1, 17)) + b"hi\x00")
    v, va = G.KernelView(ram, OFF), 0xffff_ffc0_8020_0000
    assert v.u8(va) == 1
    assert v.u16(va) == 0x0201
    assert v.u32(va) == 0x04030201
    assert v.u64(va) == 0x0807060504030201
    assert v.i32(va) == 0x04030201
    assert v.blob(va, 4) == b"\x01\x02\x03\x04"
    assert v.cstr(va + 16, 8) == "hi"


def test_a_negative_i32_survives_the_translation():
    ram = _ram()
    _put(ram, 0x8020_0000, (-5).to_bytes(4, "little", signed=True))
    assert G.KernelView(ram, OFF).i32(0xffff_ffc0_8020_0000) == -5



def test_a_physical_address_is_passed_through():
    ram = _ram()
    _put(ram, 0x8020_0000, b"\xab" * 8)
    assert G.KernelView(ram, OFF).u64(0x8020_0000) == 0xabab_abab_abab_abab


def test_the_two_address_spaces_do_not_overlap():
    v = G.KernelView(_ram(), OFF)
    assert v._t(0x8020_0000) == 0x8020_0000
    assert v._t(0xffff_ffc0_8020_0000) == 0x8020_0000


def test_an_address_outside_the_window_is_left_alone():
    v = G.KernelView(_ram(), OFF)
    assert v._t(0xdead_beef) == 0xdead_beef



def test_a_zero_offset_is_the_identity():
    ram = _ram()
    _put(ram, BASE, b"\x77" * 8)
    v = G.KernelView(ram, 0)
    assert v._t(BASE) == BASE
    assert v.u64(BASE) == ram.u64(BASE)


def test_a_direct_mapped_decoder_does_not_wrap_at_all():
    ram = _ram()
    d = object.__new__(G.GuestDecoder)
    d.ram, d._fit = ram, G.KernelImageFit(True, offset=0, paddr=BASE)
    assert d.kmem_view is ram


def test_a_higher_half_decoder_wraps():
    ram = _ram()
    d = object.__new__(G.GuestDecoder)
    d.ram, d._fit = ram, G.KernelImageFit(True, offset=OFF, paddr=0x8020_0000)
    assert isinstance(d.kmem_view, G.KernelView)


def test_an_unlocated_image_is_not_wrapped():
    ram = _ram()
    d = object.__new__(G.GuestDecoder)
    d.ram, d.elf, d._fit = ram, None, G.KernelImageFit(False, reason="找不到")
    ram.find_kernel_image = lambda e: G.KernelImageFit(False, reason="还是找不到")
    assert d.kmem_view is ram



def test_the_fit_is_not_cached_until_it_is_found():
    class _Elf:
        e_entry = 0

    ram = _ram()
    d = object.__new__(G.GuestDecoder)
    d.ram, d.elf, d._fit = ram, _Elf(), None

    calls = []
    real = ram.find_kernel_image
    ram.find_kernel_image = lambda e: (calls.append(1), real(e))[1]

    d.image_fit
    d.image_fit
    assert len(calls) == 2


def test_once_found_it_stops_measuring():
    ram = _ram()
    d = object.__new__(G.GuestDecoder)
    d.ram, d.elf, d._fit = ram, None, G.KernelImageFit(True, offset=OFF, paddr=1)

    calls = []
    ram.find_kernel_image = lambda e: calls.append(1)
    assert d.image_fit.offset == OFF
    assert calls == []



IMG_OFF = 0xffff_fffe_ffe0_0000      # 0xffffffff80000000 - 0x80200000
MAP_OFF = 0xffff_ffc0_0000_0000


def test_two_windows_each_read_their_own_side():
    ram = _ram(8)
    _put(ram, 0x8020_0000, b"\xaa" * 8)
    _put(ram, 0x8060_0000, b"\xbb" * 8)
    v = G.KernelView(ram, [IMG_OFF, MAP_OFF])
    assert v.u64(0xffff_ffff_8000_0000) == 0xaaaa_aaaa_aaaa_aaaa
    assert v.u64(0xffff_ffc0_8060_0000) == 0xbbbb_bbbb_bbbb_bbbb


def test_one_window_alone_cannot_read_the_other_side():
    ram = _ram(8)
    _put(ram, 0x8060_0000, b"\xbb" * 8)
    assert G.KernelView(ram, [IMG_OFF]).u64(0xffff_ffc0_8060_0000) is None


def test_a_single_int_offset_still_works():
    ram = _ram()
    _put(ram, 0x8020_0000, b"\x11" * 8)
    assert G.KernelView(ram, OFF).u64(0xffff_ffc0_8020_0000) == 0x1111_1111_1111_1111


def test_zero_offsets_are_dropped():
    v = G.KernelView(_ram(), [0, OFF, 0])
    assert v.offsets == [OFF]


def test_duplicate_offsets_are_dropped():
    v = G.KernelView(_ram(), [OFF, OFF, IMG_OFF, OFF])
    assert v.offsets == [OFF, IMG_OFF]


def test_offset_is_the_first_one():
    assert G.KernelView(_ram(), [IMG_OFF, MAP_OFF]).offset == IMG_OFF


def test_no_offsets_is_identity():
    ram = _ram()
    _put(ram, 0x8020_0000, b"\x11" * 8)
    v = G.KernelView(ram, [])
    assert v.u64(0x8020_0000) == 0x1111_1111_1111_1111
    assert v.u64(0xffff_ffc0_8020_0000) is None



def _decoder(ram: G.RamImage, roots=(), machine=G.EM_RISCV) -> G.GuestDecoder:
    d = object.__new__(G.GuestDecoder)
    d.ram, d.e_machine, d._roots = ram, machine, list(roots)
    return d


def test_no_roots_says_so_rather_than_blaming_the_architecture():
    wins, why = _decoder(_ram())._derive_windows(())
    assert wins == []
    assert "没有观测到页表根" in why


def test_a_non_riscv_binary_says_which_architecture():
    wins, why = _decoder(_ram(), machine=0x3e)._derive_windows([0x8020_0000])
    assert wins == []
    assert "Sv39" in why


def test_an_unwalkable_root_is_reported_not_guessed():
    wins, why = _decoder(_ram())._derive_windows([0x9d51_2000])
    assert wins == []
    assert why


def _pte(pa: int, flags: int) -> int:
    return ((pa >> G.PGSHIFT) << 10) | flags


def _gig_map(ram: G.RamImage, root_pa: int, entries) -> None:
    page = bytearray(G.PGSIZE)
    leaf = G.PTE_V | G.PTE_R | G.PTE_W
    for va, pa in entries:
        i = (va >> 30) & 0x1ff
        page[i * 8:i * 8 + 8] = _pte(pa, leaf).to_bytes(8, "little")
    ram.apply({(root_pa - ram.base) // G.PGSIZE: bytes(page)})


def test_a_window_is_measured_from_the_page_table():
    ram = _ram(8)
    root = 0x8010_0000
    _gig_map(ram, root, [(0xffff_ffc0_8000_0000, 0x8000_0000)])
    wins, why = _decoder(ram, roots=[root])._derive_windows([root])
    assert why == ""
    assert wins == [MAP_OFF]


def test_user_side_mappings_do_not_become_windows():
    ram = _ram(8)
    root = 0x8010_0000
    _gig_map(ram, root, [(0xffff_ffc0_8000_0000, 0x8000_0000),
                         (0x0000_0000_4000_0000, 0x8040_0000)])
    wins, _ = _decoder(ram, roots=[root])._derive_windows([root])
    assert wins == [MAP_OFF]


def test_two_windows_come_out_biggest_first():
    ram = _ram(8)
    root = 0x8010_0000
    _gig_map(ram, root, [(0xffff_ffc0_8000_0000, 0x8000_0000),
                         (0xffff_ffc0_c000_0000, 0x8000_0000 + (1 << 30)),
                         (0xffff_ffff_8000_0000, 0x8000_0000)])
    wins, _ = _decoder(ram, roots=[root])._derive_windows([root])
    assert wins[0] == MAP_OFF
    assert len(wins) == 2


def test_a_lone_small_page_is_not_a_window():
    ram = _ram(8)
    va = 0xffff_ffc0_8000_0000
    root, mid, low = 0x8010_0000, 0x8011_0000, 0x8012_0000

    def _tbl(pa: int, idx: int, target: int, flags: int) -> None:
        page = bytearray(G.PGSIZE)
        page[idx * 8:idx * 8 + 8] = _pte(target, flags).to_bytes(8, "little")
        ram.apply({(pa - ram.base) // G.PGSIZE: bytes(page)})

    _tbl(root, (va >> 30) & 0x1ff, mid, G.PTE_V)
    _tbl(mid, (va >> 21) & 0x1ff, low, G.PTE_V)
    _tbl(low, (va >> 12) & 0x1ff, 0x8020_0000, G.PTE_V | G.PTE_R)

    wins, why = _decoder(ram, roots=[root])._derive_windows([root])
    assert wins == []
    assert "MiB" in why



def _small_leaves(ram: G.RamImage, root: int, va0: int, pa0: int,
                  slots) -> None:
    mid, low = 0x8011_0000, 0x8012_0000
    top = bytearray(G.PGSIZE)
    i = (va0 >> 30) & 0x1ff
    top[i * 8:i * 8 + 8] = _pte(mid, G.PTE_V).to_bytes(8, "little")
    ram.apply({(root - ram.base) // G.PGSIZE: bytes(top)})

    midp = bytearray(G.PGSIZE)
    j = (va0 >> 21) & 0x1ff
    midp[j * 8:j * 8 + 8] = _pte(low, G.PTE_V).to_bytes(8, "little")
    ram.apply({(mid - ram.base) // G.PGSIZE: bytes(midp)})

    lowp = bytearray(G.PGSIZE)
    base = (va0 >> 12) & 0x1ff
    for s in slots:
        k = base + s
        lowp[k * 8:k * 8 + 8] = _pte(pa0 + s * G.PGSIZE,
                                     G.PTE_V | G.PTE_R).to_bytes(8, "little")
    ram.apply({(low - ram.base) // G.PGSIZE: bytes(lowp)})


def test_a_small_but_contiguous_run_is_a_window():
    ram = _ram(8)
    root, va0, pa0 = 0x8010_0000, 0xffff_ffc0_8000_0000, 0x8000_0000
    _small_leaves(ram, root, va0, pa0, range(16))
    wins, why = _decoder(ram, roots=[root])._derive_windows([root])
    assert why == ""
    assert wins == [MAP_OFF]


def test_the_same_bytes_scattered_are_not_a_window():
    ram = _ram(8)
    root, va0, pa0 = 0x8010_0000, 0xffff_ffc0_8000_0000, 0x8000_0000
    _small_leaves(ram, root, va0, pa0, range(0, 32, 2))
    wins, why = _decoder(ram, roots=[root])._derive_windows([root])
    assert wins == []
    assert why


def test_a_run_shorter_than_the_floor_is_still_refused():
    ram = _ram(8)
    root, va0, pa0 = 0x8010_0000, 0xffff_ffc0_8000_0000, 0x8000_0000
    _small_leaves(ram, root, va0, pa0, range(8))
    wins, _ = _decoder(ram, roots=[root])._derive_windows([root])
    assert wins == []


def test_the_small_window_sorts_after_the_big_ones():
    ram = _ram(8)
    root = 0x8010_0000
    page = bytearray(G.PGSIZE)
    leaf = G.PTE_V | G.PTE_R | G.PTE_W
    i = (0xffff_ffc0_8000_0000 >> 30) & 0x1ff
    page[i * 8:i * 8 + 8] = _pte(0x8000_0000, leaf).to_bytes(8, "little")
    mid, low = 0x8011_0000, 0x8012_0000
    va0 = 0xffff_ffe0_8000_0000
    j = (va0 >> 30) & 0x1ff
    page[j * 8:j * 8 + 8] = _pte(mid, G.PTE_V).to_bytes(8, "little")
    ram.apply({(root - ram.base) // G.PGSIZE: bytes(page)})

    midp = bytearray(G.PGSIZE)
    k = (va0 >> 21) & 0x1ff
    midp[k * 8:k * 8 + 8] = _pte(low, G.PTE_V).to_bytes(8, "little")
    ram.apply({(mid - ram.base) // G.PGSIZE: bytes(midp)})

    lowp = bytearray(G.PGSIZE)
    b = (va0 >> 12) & 0x1ff
    for s in range(16):
        lowp[(b + s) * 8:(b + s) * 8 + 8] = _pte(
            0x8010_0000 + s * G.PGSIZE, G.PTE_V | G.PTE_R).to_bytes(8, "little")
    ram.apply({(low - ram.base) // G.PGSIZE: bytes(lowp)})

    wins, why = _decoder(ram, roots=[root])._derive_windows([root])
    assert why == ""
    assert len(wins) == 2
    assert wins[0] == MAP_OFF
