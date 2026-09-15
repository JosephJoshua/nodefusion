
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

STT_NOTYPE = 0
STT_OBJECT = 1
STT_FUNC = 2


@dataclass(frozen=True)
class Symbol:
    name: str
    value: int
    size: int
    info: int
    shndx: int

    @property
    def sym_type(self) -> int:
        return self.info & 0xF

    @property
    def is_func(self) -> bool:
        return self.sym_type == STT_FUNC

    @property
    def is_object(self) -> bool:
        return self.sym_type == STT_OBJECT


class ElfError(Exception):
    pass


class Elf64:

    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = self.path.read_bytes()
        self.data = data

        if len(data) < 64 or data[:4] != b"\x7fELF":
            raise ElfError(f"{path} 不是 ELF 文件")
        if data[4] != 2:
            raise ElfError(f"{path} 不是 64 位 ELF（NodeFusion 只支持 RV64）")
        if data[5] != 1:
            raise ElfError(f"{path} 不是小端 ELF")

        (self.e_type, self.e_machine, _ver, self.e_entry, self.e_phoff,
         self.e_shoff, self.e_flags, _ehsize, self.e_phentsize, self.e_phnum,
         self.e_shentsize, self.e_shnum, self.e_shstrndx) = struct.unpack_from(
            "<HHIQQQIHHHHHH", data, 16)

        self._sections = self._read_sections()
        self.symbols: list[Symbol] = self._read_symbols()

        self.by_name: dict[str, Symbol] = {}
        for s in self.symbols:
            if s.name and (s.name not in self.by_name or self.by_name[s.name].value == 0):
                self.by_name[s.name] = s

        self._func_index = sorted(
            ((s.value, s.size, s.name) for s in self.symbols
             if s.is_func and s.value and s.name),
            key=lambda t: t[0])


    def _read_sections(self) -> list[dict]:
        out = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            (name, s_type, flags, addr, offset, size, link, info,
             align, entsize) = struct.unpack_from("<IIQQQQIIQQ", self.data, off)
            out.append(dict(name_off=name, type=s_type, flags=flags, addr=addr,
                            offset=offset, size=size, link=link, info=info,
                            align=align, entsize=entsize))
        if self.e_shstrndx < len(out):
            strtab = out[self.e_shstrndx]
            base = strtab["offset"]
            for s in out:
                s["name"] = self._cstr(base + s["name_off"])
        return out

    def _cstr(self, off: int) -> str:
        end = self.data.find(b"\x00", off)
        if end < 0:
            end = len(self.data)
        return self.data[off:end].decode("utf-8", "replace")


    def _read_symbols(self) -> list[Symbol]:
        syms: list[Symbol] = []
        SHT_SYMTAB, SHT_DYNSYM = 2, 11
        for sec in self._sections:
            if sec["type"] not in (SHT_SYMTAB, SHT_DYNSYM):
                continue
            strtab = self._sections[sec["link"]]
            str_base = strtab["offset"]
            n = sec["size"] // 24 if sec["entsize"] == 0 else sec["size"] // sec["entsize"]
            for i in range(n):
                off = sec["offset"] + i * 24
                (nameoff, info, other, shndx, value, size) = struct.unpack_from(
                    "<IBBHQQ", self.data, off)
                name = self._cstr(str_base + nameoff) if nameoff else ""
                syms.append(Symbol(name, value, size, info, shndx))
        if not syms:
            raise ElfError(f"{self.path} 里没有符号表；请确认内核不是 strip 过的")
        return syms


    def section(self, name: str) -> bytes | None:
        SHT_NOBITS = 8
        for sec in self._sections:
            if sec.get("name") == name:
                if sec["type"] == SHT_NOBITS:
                    return None
                return self.data[sec["offset"]:sec["offset"] + sec["size"]]
        return None

    def section_names(self) -> list[str]:
        return [s.get("name", "") for s in self._sections]

    def addr_of(self, name: str) -> int | None:
        s = self.by_name.get(name)
        return s.value if s else None

    def sym(self, name: str) -> Symbol | None:
        return self.by_name.get(name)

    def require(self, name: str) -> Symbol:
        s = self.by_name.get(name)
        if s is None:
            raise ElfError(
                f"内核符号 '{name}' 不存在。NodeFusion 需要它来重建系统状态；"
                f"如果内核确实没有这个符号，应当把对应资源显式标为不可用，"
                f"而不是继续往下猜。")
        return s

    def functions(self) -> list[Symbol]:
        return [s for s in self.symbols if s.is_func and s.value and s.name]

    def resolve_pc(self, pc: int) -> tuple[str | None, int]:
        idx = self._func_index
        if not idx:
            return None, 0
        lo, hi = 0, len(idx) - 1
        best = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if idx[mid][0] <= pc:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best < 0:
            return None, 0
        addr, size, name = idx[best]
        if size and pc >= addr + size:
            return None, 0
        return name, pc - addr
