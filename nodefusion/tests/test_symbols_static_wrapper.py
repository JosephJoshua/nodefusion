"""Static-symbol selection must not confuse lazy_static's public wrapper.

Some rustc versions emit both a zero-sized DWARF variable at address zero and
the real hidden ``LAZY`` storage in the ELF symbol table.  The wrapper is a
type-level handle, not storage.
"""

from dataclasses import dataclass

from nodefusion.model.symbols import SymbolIndex, _lazy_shape


@dataclass
class _Var:
    addr: int
    type_off: int = 7
    path: str = "filepool"


@dataclass
class _ElfSym:
    name: str
    value: int
    size: int


class _Elf:
    symbols = []


class _Dw:
    def __init__(self, *, size: int) -> None:
        self.size = size

    def var(self, _path):
        return _Var(0)

    def size_of(self, _off):
        return self.size

    def var_decl(self, _path):
        return None


def test_zero_address_zero_size_wrapper_does_not_shadow_lazy_storage():
    path = "easy_fs::block_cache::BLOCK_CACHE_MANAGER"
    idx = SymbolIndex(_Elf(), _Dw(size=0))
    idx._by_demangled[_lazy_shape(path)] = [
        _ElfSym("hidden", 0x8223_C340, 56)
    ]
    got, why = idx.resolve(path)
    assert why == ""
    assert (got.addr, got.size, got.how) == (0x8223_C340, 56, "lazy_static")


def test_positive_sized_object_at_address_zero_remains_a_real_variable():
    path = "kernel::ZERO_BASED_STORAGE"
    idx = SymbolIndex(_Elf(), _Dw(size=8))
    got, why = idx.resolve(path)
    assert why == ""
    assert (got.addr, got.how, got.type_off) == (0, "dwarf", 7)


def test_elf_address_joins_unique_dwarf_extern_declaration_type():
    class DeclDw(_Dw):
        def var(self, _path):
            return None

        def var_decl(self, path):
            return _Var(0, type_off=91) if path == "filepool" else None

    elf = _Elf()
    elf.symbols = [_ElfSym("filepool", 0x8123_4000, 81920)]
    got, why = SymbolIndex(elf, DeclDw(size=81920)).resolve("filepool")

    assert why == ""
    assert (got.addr, got.size, got.type_off) == (0x8123_4000, 81920, 91)
    assert got.how == "elf_raw+DWARF声明(filepool)"
