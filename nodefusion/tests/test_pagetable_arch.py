
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                # noqa: E402

from nodefusion.host import guest as G                       # noqa: E402
from nodefusion.host.guest import (                          # noqa: E402
    EM_RISCV, PGSHIFT, PGSIZE, walk_pagetable)

BASE = 0x8000_0000
EM_AARCH64 = 183
EM_X86_64 = 62


class FakeRam:

    def __init__(self, npg: int = 64):
        self.base, self.size = BASE, npg * PGSIZE
        self.buf = bytearray(self.size)
        self.seen = set(range(npg))

    def _off(self, pa: int):
        o = pa - self.base
        return o if 0 <= o < self.size else None

    def blob(self, pa: int, n: int):
        o = self._off(pa)
        return None if o is None or o + n > self.size else bytes(
            self.buf[o:o + n])

    def page_seen(self, idx: int) -> bool:
        return idx in self.seen

    def u64(self, pa: int):
        o = self._off(pa)
        return None if o is None or o + 8 > self.size else int.from_bytes(
            self.buf[o:o + 8], "little")

    def put_pte(self, pa: int, idx: int, child_pa: int, flags: int) -> None:
        o = self._off(pa) + idx * 8
        self.buf[o:o + 8] = (((child_pa >> PGSHIFT) << 10)
                             | flags).to_bytes(8, "little")


def _one_leaf() -> tuple[FakeRam, int]:
    r = FakeRam()
    root, l1, l0, leaf = (BASE, BASE + PGSIZE, BASE + 2 * PGSIZE,
                          BASE + 3 * PGSIZE)
    r.put_pte(root, 0, l1, G.PTE_V)
    r.put_pte(l1, 0, l0, G.PTE_V)
    r.put_pte(l0, 0, leaf, G.PTE_V | G.PTE_R | G.PTE_W | G.PTE_U)
    return r, root


def test_the_sv39_tree_still_walks_on_riscv():
    r, root = _one_leaf()
    maps, ptpages, err = walk_pagetable(r, root, machine=EM_RISCV)
    assert err is None
    assert len(maps) == 1 and len(ptpages) == 3


@pytest.mark.parametrize("machine, word", [
    (EM_AARCH64, "aarch64"),
    (EM_X86_64, "x86_64"),
    (0xBEEF, "e_machine"),
])
def test_other_arches_refuse_instead_of_decoding_the_same_bytes(machine, word):
    r, root = _one_leaf()
    maps, ptpages, err = walk_pagetable(r, root, machine=machine)
    assert maps == [] and ptpages == []
    assert err and word in err


def test_machine_has_no_default():
    r, root = _one_leaf()
    with pytest.raises(TypeError):
        walk_pagetable(r, root)                              # type: ignore[call-arg]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
