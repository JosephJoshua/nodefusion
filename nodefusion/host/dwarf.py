
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from .nfelf import Elf64


class DwarfError(Exception):
    pass


TAG_structure_type = 0x13
TAG_union_type = 0x17
TAG_class_type = 0x02
TAG_member = 0x0D
TAG_namespace = 0x39
TAG_variant_part = 0x33
TAG_subprogram = 0x2E
TAG_enumeration_type = 0x04
TAG_enumerator = 0x28
TAG_array_type = 0x01
TAG_subrange_type = 0x21

AT_name = 0x03
AT_byte_size = 0x0B
AT_const_value = 0x1C
AT_data_member_location = 0x38
AT_type = 0x49
AT_declaration = 0x3C
AT_count = 0x37
AT_upper_bound = 0x2F

_STRUCT_TAGS = (TAG_structure_type, TAG_union_type, TAG_class_type)

_OP_PLUS_UCONST = 0x23


@dataclass
class StructLayout:
    name: str
    size: int | None
    fields: dict[str, int] = field(default_factory=dict)
    path: str = ""
    field_types: dict[str, int] = field(default_factory=dict)

    def off(self, fname: str) -> int:
        if fname not in self.fields:
            raise DwarfError(
                f"结构体 {self.path or self.name} 里没有字段 {fname!r}。"
                f"已有字段：{', '.join(sorted(self.fields)) or '（无）'}")
        return self.fields[fname]

    def has(self, fname: str) -> bool:
        return fname in self.fields


class _Reader:

    __slots__ = ("d", "p")

    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def _need(self, n: int) -> None:
        if self.p + n > len(self.d):
            raise DwarfError(
                f"DWARF 数据在偏移 {self.p} 处越界（还要 {n} 字节，"
                f"只剩 {len(self.d) - self.p}）：调试信息被截断或损坏")

    def u8(self) -> int:
        self._need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self) -> int:
        self._need(2)
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        self._need(4)
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def u64(self) -> int:
        self._need(8)
        v = struct.unpack_from("<Q", self.d, self.p)[0]
        self.p += 8
        return v

    def skip(self, n: int) -> None:
        if n < 0:
            raise DwarfError(f"DWARF 里出现负长度 {n}，数据已损坏")
        self._need(n)
        self.p += n

    def take(self, n: int) -> bytes:
        self._need(n)
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def uleb(self) -> int:
        out = 0
        shift = 0
        while True:
            b = self.u8()
            out |= (b & 0x7F) << shift
            if not (b & 0x80):
                return out
            shift += 7
            if shift > 128:
                raise DwarfError("LEB128 长度异常，DWARF 数据已损坏")

    def sleb(self) -> int:
        out = 0
        shift = 0
        while True:
            b = self.u8()
            out |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                if b & 0x40:
                    out -= 1 << shift
                return out
            if shift > 128:
                raise DwarfError("LEB128 长度异常，DWARF 数据已损坏")

    def cstr(self) -> str:
        end = self.d.find(b"\x00", self.p)
        if end < 0:
            raise DwarfError("DWARF 字符串没有结束符，数据已损坏")
        s = self.d[self.p:end].decode("utf-8", "replace")
        self.p = end + 1
        return s


@dataclass(frozen=True)
class _AbbrevDecl:
    tag: int
    has_children: bool
    attrs: tuple[tuple[int, int, int | None], ...]


def _parse_abbrev(data: bytes, offset: int) -> dict[int, _AbbrevDecl]:
    r = _Reader(data, offset)
    table: dict[int, _AbbrevDecl] = {}
    while True:
        code = r.uleb()
        if code == 0:
            return table
        tag = r.uleb()
        has_children = bool(r.u8())
        attrs: list[tuple[int, int, int | None]] = []
        while True:
            at = r.uleb()
            form = r.uleb()
            ic: int | None = None
            if form == 0x21:
                ic = r.sleb()
            if at == 0 and form == 0:
                break
            attrs.append((at, form, ic))
        table[code] = _AbbrevDecl(tag, has_children, tuple(attrs))


class _FormReader:

    def __init__(self, r: _Reader, *, addr_size: int, offset_size: int,
                 debug_str: bytes, line_str: bytes):
        self.r = r
        self.addr_size = addr_size
        self.offset_size = offset_size
        self.debug_str = debug_str
        self.line_str = line_str

    def _strp(self, tab: bytes, off: int, which: str) -> str:
        if off >= len(tab):
            raise DwarfError(
                f"{which} 偏移 {off} 超出该节大小 {len(tab)}，DWARF 已损坏")
        end = tab.find(b"\x00", off)
        if end < 0:
            raise DwarfError(f"{which} 里的字符串没有结束符")
        return tab[off:end].decode("utf-8", "replace")

    def read(self, form: int, implicit: int | None):
        r = self.r
        if form == 0x0B: return r.u8()          # data1
        if form == 0x05: return r.u16()         # data2
        if form == 0x06: return r.u32()         # data4
        if form == 0x07: return r.u64()         # data8
        if form == 0x0D: return r.sleb()        # sdata
        if form == 0x0F: return r.uleb()        # udata
        if form == 0x1E: return r.take(16)      # data16
        if form == 0x21: return implicit
        if form == 0x01: return r.take(self.addr_size)          # addr
        if form == 0x17: return (r.u32() if self.offset_size == 4
                                 else r.u64())                  # sec_offset
        if form == 0x08: return r.cstr()                        # string
        if form == 0x0E:                                        # strp
            off = r.u32() if self.offset_size == 4 else r.u64()
            return self._strp(self.debug_str, off, ".debug_str")
        if form == 0x1F:                                        # line_strp
            off = r.u32() if self.offset_size == 4 else r.u64()
            return self._strp(self.line_str, off, ".debug_line_str")
        if form == 0x11: return r.u8()          # ref1
        if form == 0x12: return r.u16()         # ref2
        if form == 0x13: return r.u32()         # ref4
        if form == 0x14: return r.u64()         # ref8
        if form == 0x15: return r.uleb()        # ref_udata
        if form == 0x10:                                        # ref_addr
            return r.u32() if self.offset_size == 4 else r.u64()
        if form == 0x20: return r.u64()         # ref_sig8
        if form == 0x18: return r.take(r.uleb())    # exprloc
        if form == 0x09: return r.take(r.uleb())    # block
        if form == 0x0A: return r.take(r.u8())      # block1
        if form == 0x03: return r.take(r.u16())     # block2
        if form == 0x04: return r.take(r.u32())     # block4
        if form == 0x0C: return r.u8()          # flag
        if form == 0x19: return True
        if form == 0x16:
            return self.read(r.uleb(), None)
        raise DwarfError(
            f"DWARF 里出现未支持的 DW_FORM 0x{form:x}（偏移 {r.p}）。"
            f"不认识它就算不出该跳多少字节，继续解析会让后面所有偏移错位，"
            f"因此这里直接失败而不是猜。")


def _member_offset(v) -> int | None:
    if isinstance(v, int):
        return v
    if isinstance(v, (bytes, bytearray)) and len(v) >= 2 and v[0] == _OP_PLUS_UCONST:
        try:
            return _Reader(bytes(v), 1).uleb()
        except DwarfError:
            return None
    return None


class DwarfInfo:

    def __init__(self, path: str | Path, *, elf: Elf64 | None = None):
        self.path = Path(path)
        e = elf if elf is not None else Elf64(self.path)
        info = e.section(".debug_info")
        abbrev = e.section(".debug_abbrev")
        if not info or not abbrev:
            raise DwarfError(
                f"{self.path} 里没有 .debug_info / .debug_abbrev。"
                f"这个内核不是带调试信息编出来的，结构体偏移无法读取。")
        self._str = e.section(".debug_str") or b""
        self._line_str = e.section(".debug_line_str") or b""

        self.structs: dict[str, StructLayout] = {}
        self._by_short: dict[str, list[StructLayout]] = {}
        self.conflicts: dict[str, str] = {}
        self._die: dict[int, tuple[int, str | None, int | None]] = {}
        self.arrays: dict[int, tuple[int | None, int | None]] = {}
        self._struct_by_die: dict[int, StructLayout] = {}
        self.enums: dict[str, dict[str, int]] = {}

        self._parse(info, abbrev)
        self._index_short()


    def _parse(self, info: bytes, abbrev: bytes) -> None:
        abbrev_cache: dict[int, dict[int, _AbbrevDecl]] = {}
        pos = 0
        n = len(info)
        while pos < n:
            if pos + 4 > n:
                break
            unit_len = struct.unpack_from("<I", info, pos)[0]
            offset_size = 4
            hdr = pos + 4
            if unit_len == 0xFFFFFFFF:
                unit_len = struct.unpack_from("<Q", info, hdr)[0]
                offset_size = 8
                hdr += 8
            elif unit_len >= 0xFFFFFFF0:
                raise DwarfError(
                    f".debug_info 偏移 {pos} 处的单元长度 0x{unit_len:x} 是保留值，"
                    f"数据已损坏")
            if unit_len == 0:
                break
            end = hdr + unit_len
            if end > n:
                raise DwarfError(
                    f".debug_info 里某个编译单元声称长到 {end}，但该节只有 {n} 字节："
                    f"调试信息被截断")
            self._parse_cu(info, pos, hdr, end, offset_size, abbrev, abbrev_cache)
            pos = end

    def _parse_cu(self, info: bytes, cu_start: int, hdr: int, end: int,
                  offset_size: int, abbrev: bytes, cache: dict) -> None:
        r = _Reader(info, hdr)
        version = r.u16()
        if version <= 4:
            abbrev_off = r.u32() if offset_size == 4 else r.u64()
            addr_size = r.u8()
        elif version == 5:
            _unit_type = r.u8()
            addr_size = r.u8()
            abbrev_off = r.u32() if offset_size == 4 else r.u64()
        else:
            return

        if abbrev_off not in cache:
            cache[abbrev_off] = _parse_abbrev(abbrev, abbrev_off)
        table = cache[abbrev_off]
        fr = _FormReader(r, addr_size=addr_size, offset_size=offset_size,
                         debug_str=self._str, line_str=self._line_str)

        ns: list[str] = []
        stack: list[tuple[bool, StructLayout | None,
                          tuple[str, dict[str, int]] | None, int | None]] = []

        def enclosing_struct() -> StructLayout | None:
            return stack[-1][1] if stack else None

        def enclosing_enum() -> dict[str, int] | None:
            return stack[-1][2][1] if stack and stack[-1][2] else None

        def enclosing_array() -> int | None:
            return stack[-1][3] if stack else None

        while r.p < end:
            die_off = r.p
            code = r.uleb()
            if code == 0:
                if not stack:
                    continue
                pushed_ns, done, en, _arr = stack.pop()
                if pushed_ns:
                    ns.pop()
                if done is not None:
                    self._commit(done)
                if en is not None and en[1]:
                    self.enums.setdefault(en[0], {}).update(en[1])
                continue
            decl = table.get(code)
            if decl is None:
                raise DwarfError(
                    f"DIE 引用了缩写表里没有的编号 {code}（偏移 {r.p}）："
                    f"调试信息不自洽，停止解析")

            name: str | None = None
            byte_size: int | None = None
            mloc = None
            declaration = False
            type_ref: int | None = None
            const_value: int | None = None
            count: int | None = None
            upper: int | None = None
            for at, form, ic in decl.attrs:
                v = fr.read(form, ic)
                if at == AT_name and isinstance(v, str):
                    name = v
                elif at == AT_byte_size and isinstance(v, int):
                    byte_size = v
                elif at == AT_data_member_location:
                    mloc = v
                elif at == AT_declaration:
                    declaration = bool(v)
                elif at == AT_const_value and isinstance(v, int):
                    const_value = v
                elif at == AT_count and isinstance(v, int):
                    count = v
                elif at == AT_upper_bound and isinstance(v, int):
                    upper = v
                elif at == AT_type and isinstance(v, int):
                    if form in (0x11, 0x12, 0x13, 0x14, 0x15):
                        type_ref = cu_start + v
                    elif form == 0x10:
                        type_ref = v

            if name is not None or byte_size is not None:
                self._die[die_off] = (decl.tag, name, byte_size)

            made: StructLayout | None = None
            made_enum: tuple[str, dict[str, int]] | None = None
            made_array: int | None = None
            if decl.tag == TAG_array_type:
                self.arrays[die_off] = (type_ref, None)
                made_array = die_off
            elif decl.tag == TAG_subrange_type:
                host_arr = enclosing_array()
                if host_arr is not None:
                    n = count if count is not None else (
                        upper + 1 if upper is not None else None)
                    if n is not None:
                        elem, _ = self.arrays.get(host_arr, (None, None))
                        self.arrays[host_arr] = (elem, n)
            elif decl.tag == TAG_enumerator:
                slot = enclosing_enum()
                if slot is not None and name and const_value is not None:
                    slot[name] = const_value
            elif decl.tag == TAG_enumeration_type and name:
                made_enum = ("::".join(ns + [name]), {})
            elif decl.tag == TAG_member:
                host = enclosing_struct()
                off = _member_offset(mloc)
                if host is not None and name and off is not None:
                    host.fields[name] = off
                    if type_ref is not None:
                        host.field_types[name] = type_ref
            elif decl.tag in _STRUCT_TAGS and name and not declaration:
                made = StructLayout(name=name, size=byte_size,
                                    path="::".join(ns + [name]))
                self._struct_by_die[die_off] = made
                if not decl.has_children:
                    self._commit(made)
                    made = None

            if decl.has_children:
                pushed_ns = decl.tag == TAG_namespace and bool(name)
                if pushed_ns:
                    ns.append(name)         # type: ignore[arg-type]
                stack.append((pushed_ns, made, made_enum, made_array))
            elif made_enum is not None:
                self.enums.setdefault(made_enum[0], {})

        while stack:
            pushed_ns, done, en, _arr = stack.pop()
            if pushed_ns:
                ns.pop()
            if done is not None:
                self._commit(done)
            if en is not None and en[1]:
                self.enums.setdefault(en[0], {}).update(en[1])

    def _commit(self, s: StructLayout) -> None:
        old = self.structs.get(s.path)
        if old is None:
            self.structs[s.path] = s
            return
        if old.fields == s.fields and old.size == s.size:
            return
        if not old.fields and s.fields:
            self.structs[s.path] = s
            return
        if old.fields and not s.fields:
            return
        self.conflicts[s.path] = (
            f"{s.path} 在调试信息里有多套不同布局，无法确定用哪一套")

    def _index_short(self) -> None:
        for s in self.structs.values():
            self._by_short.setdefault(s.name, []).append(s)


    def find(self, name: str) -> StructLayout | None:
        if name in self.structs:
            return self.structs[name]
        cands = self._by_short.get(name)
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        first = cands[0]
        if all(c.fields == first.fields and c.size == first.size for c in cands):
            return first
        paths = "、".join(sorted(c.path for c in cands))
        self.conflicts[name] = (
            f"短名 {name} 对应多个布局不同的类型（{paths}），"
            f"请用完整路径指定")
        return None

    def type_of(self, layout: StructLayout, fname: str) -> str | None:
        ref = layout.field_types.get(fname)
        if ref is None:
            return None
        arr = self.arrays.get(ref)
        if arr is not None:
            elem_ref, n = arr
            elem = self._die.get(elem_ref) if elem_ref is not None else None
            elem_name = (elem[1] if elem and elem[1] else "?")
            return f"[{elem_name}; {n if n is not None else '?'}]"
        die = self._die.get(ref)
        if die is None:
            return None
        return die[1]

    def array_of_field(self, layout: StructLayout, fname: str
                       ) -> tuple[str | None, int | None] | None:
        ref = layout.field_types.get(fname)
        if ref is None:
            return None
        arr = self.arrays.get(ref)
        if arr is None:
            return None
        elem_ref, n = arr
        elem = self._die.get(elem_ref) if elem_ref is not None else None
        return (elem[1] if elem else None), n

    def struct_of_array_elem(self, layout: StructLayout, fname: str
                             ) -> StructLayout | None:
        ref = layout.field_types.get(fname)
        if ref is None:
            return None
        arr = self.arrays.get(ref)
        if arr is None or arr[0] is None:
            return None
        return self._struct_by_die.get(arr[0])

    def struct_of_field(self, layout: StructLayout, fname: str) -> StructLayout | None:
        ref = layout.field_types.get(fname)
        if ref is None:
            return None
        return self._struct_by_die.get(ref)

    def size_of_type(self, layout: StructLayout, fname: str) -> int | None:
        ref = layout.field_types.get(fname)
        if ref is None:
            return None
        die = self._die.get(ref)
        return die[2] if die else None

    def find_prefix(self, prefix: str) -> list[StructLayout]:
        return [s for s in self.structs.values() if s.name.startswith(prefix)]
