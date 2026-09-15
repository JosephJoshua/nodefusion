
from __future__ import annotations

import sys
from pathlib import Path

from .layout import Function, InlineSite, StructLayout, Variable
from .symbols import demangle, demangle_v0

_VENDOR = Path(__file__).resolve().parent.parent / "_vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from elftools.elf.elffile import ELFFile  # noqa: E402

_STRUCT_TAGS = frozenset((
    "DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"))

_NOT_IN_VARIANT = object()

_TYPE_TAGS = frozenset((
    *_STRUCT_TAGS,
    "DW_TAG_base_type", "DW_TAG_typedef", "DW_TAG_pointer_type",
    "DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type",
    "DW_TAG_array_type", "DW_TAG_enumeration_type", "DW_TAG_subroutine_type",
))

_TRANSPARENT = frozenset((
    "DW_TAG_typedef", "DW_TAG_const_type",
    "DW_TAG_volatile_type", "DW_TAG_restrict_type"))

_CU_RELATIVE_REFS = frozenset((
    "DW_FORM_ref1", "DW_FORM_ref2", "DW_FORM_ref4",
    "DW_FORM_ref8", "DW_FORM_ref_udata"))

_DW_OP_ADDR = 0x03
_DW_OP_PLUS_UCONST = 0x23


def _generic_base(name: str) -> str:
    i = name.find("<")
    return name if i < 0 else name[:i]


def _last_segment(path: str) -> str:
    depth = 0
    kept: list[str] = []
    for ch in path:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            kept.append(ch)
    return "".join(kept).split("::")[-1].strip()


def _uleb(b: bytes, i: int) -> tuple[int | None, int]:
    val = shift = 0
    while i < len(b):
        byte = b[i]
        val |= (byte & 0x7F) << shift
        i += 1
        if not byte & 0x80:
            return val, i
        shift += 7
    return None, i


class DwarfSource:

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.structs: dict[str, StructLayout] = {}
        self.enums: dict[str, dict[str, int]] = {}
        self.variables: dict[str, Variable] = {}
        #: External declarations have a type but no DW_AT_location. The ELF
        #: symbol table supplies the missing address, so retain these instead
        #: of throwing away one half of a valid name-based join. This is
        #: common in C kernels whose defining translation unit emits only the
        #: header's ``extern T name[N]`` DIE.
        self.variable_declarations: dict[str, list[Variable]] = {}
        self.functions: list[Function] = []
        self.inline_sites: list[InlineSite] = []
        self.inline_sites_dropped = 0
        self.functions_tombstoned = 0
        self._exec_ranges: list[tuple[int, int]] = []
        self.conflicts: dict[str, str] = {}
        self.array_counts: dict[int, int] = {}
        self._by_short: dict[str, list[StructLayout]] = {}
        self._by_base: dict[str, list[StructLayout]] = {}
        self._by_addr: dict[int, list[Variable]] | None = None
        self._types: dict[int, tuple[str, str | None, int | None, int | None]] = {}
        self._struct_by_off: dict[int, StructLayout] = {}
        self._off_by_struct: dict[int, int] | None = None

        self._fh = open(self.path, "rb")
        elf = ELFFile(self._fh)
        if not elf.has_dwarf_info():
            raise RuntimeError(f"{self.path} 里没有调试信息（.debug_info）")
        self.e_machine = elf.header["e_machine"]
        self._exec_ranges = self._exec_sections(elf)
        self._parse(elf.get_dwarf_info())
        self._index_short()

    def close(self) -> None:
        self._fh.close()


    def _parse(self, dw) -> None:
        self._dw = dw
        try:
            self._rangelists = dw.range_lists()
        except Exception:
            self._rangelists = None
        for cu in dw.iter_CUs():
            self._parse_cu(cu, self._file_table(dw, cu))

    def _file_table(self, dw, cu) -> list[str]:
        try:
            lp = dw.line_program_for_CU(cu)
        except Exception:
            return []
        if lp is None:
            return []
        base = 0 if lp.header["version"] >= 5 else 1

        def s(v) -> str:
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

        dirs = [s(d) for d in lp.header.get("include_directory", [])]
        out: list[str] = []
        for entry in lp.header.get("file_entry", []):
            name = s(entry.name)
            di = getattr(entry, "dir_index", None)
            if di is not None and not name.startswith("/"):
                k = di - base
                if 0 <= k < len(dirs):
                    name = f"{dirs[k]}/{name}"
            out.append(name)
        return [""] * base + out

    @staticmethod
    def _decl_file(die, files: list[str]) -> str | None:
        a = die.attributes.get("DW_AT_decl_file")
        if a is None or not isinstance(a.value, int):
            return None
        i = a.value
        return files[i] if 0 <= i < len(files) and files[i] else None


    def _origin_path(self, cu, die, depth: int = 0) -> str | None:
        if depth > 4:
            return None
        raw = getattr(die.attributes.get("DW_AT_linkage_name"), "value", None)
        if isinstance(raw, (bytes, bytearray)):
            s = raw.decode("utf-8", "replace")
            #   _RNvMs0_...7journalINtB5_7Jbd2Dev...E6commitB17_
            #     -> rsext4::blockdev::journal::Jbd2Dev::commit
            return demangle(s) or demangle_v0(s, impls=True, generics=True) or s
        for key in ("DW_AT_abstract_origin", "DW_AT_specification"):
            off = self._ref(cu, die.attributes.get(key))
            if off is None:
                continue
            try:
                nxt = self._dw.get_DIE_from_refaddr(off)
            except Exception:
                continue
            got = self._origin_path(cu, nxt, depth + 1)
            if got:
                return got
        return self._name(die)

    @staticmethod
    def _exec_sections(elf) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for sec in elf.iter_sections():
            h = sec.header
            addr = h["sh_addr"]
            if addr and (h["sh_flags"] & 0x4):
                out.append((addr, addr + h["sh_size"]))
        return sorted(out)

    def _in_exec(self, addr: int) -> bool:
        return any(lo <= addr < hi for lo, hi in self._exec_ranges)

    @staticmethod
    def _cu_low_pc(cu) -> int:
        a = cu.get_top_DIE().attributes.get("DW_AT_low_pc")
        return a.value if a is not None and isinstance(a.value, int) else 0

    def _inline_entry(self, cu, die) -> int | None:
        lo = die.attributes.get("DW_AT_low_pc")
        if lo is not None and isinstance(lo.value, int):
            return lo.value
        rg = die.attributes.get("DW_AT_ranges")
        if rg is None or self._rangelists is None or not isinstance(rg.value, int):
            return None
        try:
            entries = self._rangelists.get_range_list_at_offset(rg.value, cu=cu)
        except TypeError:
            try:
                entries = self._rangelists.get_range_list_at_offset(rg.value)
            except Exception:
                return None
        except Exception:
            return None

        base = self._cu_low_pc(cu)
        best: int | None = None
        for ent in entries:
            ba = getattr(ent, "base_address", None)
            if ba is not None:
                base = ba
                continue
            begin = getattr(ent, "begin_offset", None)
            if not isinstance(begin, int):
                continue
            addr = begin if getattr(ent, "is_absolute", False) else base + begin
            if best is None or addr < best:
                best = addr
        return best

    def _inline_site(self, cu, die, files: list[str],
                     host: str | None) -> InlineSite | None:
        path = self._origin_path(cu, die)
        if not path:
            return None
        addr = self._inline_entry(cu, die)
        if addr is None:
            return None
        if self._exec_ranges and not self._in_exec(addr):
            self.inline_sites_dropped += 1
            return None
        return InlineSite(
            name=_last_segment(path), path=path, addr=addr, host=host,
            decl_file=self._decl_file(die, files))

    def _parse_cu(self, cu, files: list[str]) -> None:
        ns: list[str] = []
        stack: list[tuple] = []

        #   structure_type -> variant_part -> variant -> member
        def top_struct() -> StructLayout | None:
            return stack[-1][1] if stack else None

        def top_variant() -> tuple | None:
            return stack[-1][5] if stack else None

        for die in cu.iter_DIEs():
            if die.is_null():
                if not stack:
                    continue
                pushed_ns, done, en, _arr, _fn, _var = stack.pop()
                if pushed_ns:
                    ns.pop()
                if done is not None:
                    self._commit(done)
                if en is not None and en[1]:
                    self.enums.setdefault(en[0], {}).update(en[1])
                continue

            tag = die.tag
            name = self._name(die)
            new_struct: StructLayout | None = None
            new_fn: Function | None = None

            if tag in _TYPE_TAGS:
                bs = die.attributes.get("DW_AT_byte_size")
                self._types[die.offset] = (
                    tag, name,
                    self._ref(cu, die.attributes.get("DW_AT_type")),
                    bs.value if bs is not None else None)

            if tag == "DW_TAG_member":
                host = top_struct()
                off = die.attributes.get("DW_AT_data_member_location")
                vctx = top_variant()
                if host is not None and name and off is not None:
                    v = self._member_offset(off.value)
                    if v is not None:
                        host.fields[name] = v
                        tref = self._ref(cu, die.attributes.get("DW_AT_type"))
                        if tref is not None:
                            host.field_types[name] = tref
                elif vctx is not None and off is not None:
                    vhost, discr = vctx
                    v = self._member_offset(off.value)
                    tref = self._ref(cu, die.attributes.get("DW_AT_type"))
                    if vhost is None or v is None:
                        pass
                    elif discr is _NOT_IN_VARIANT:
                        if name is None:
                            vhost.variant_tag = (v, tref)
                    elif name is not None:
                        vhost.variants[name] = (discr, v, tref)

            elif tag == "DW_TAG_enumerator":
                slot = stack[-1][2] if stack and stack[-1][2] else None
                v = die.attributes.get("DW_AT_const_value")
                if slot is not None and name and v is not None and isinstance(v.value, int):
                    slot[1][name] = v.value

            elif tag == "DW_TAG_subrange_type":
                host_arr = stack[-1][3] if stack else None
                if host_arr is not None:
                    n = die.attributes.get("DW_AT_count")
                    if n is not None and isinstance(n.value, int):
                        self.array_counts[host_arr] = n.value
                    else:
                        ub = die.attributes.get("DW_AT_upper_bound")
                        if ub is not None and isinstance(ub.value, int):
                            self.array_counts[host_arr] = ub.value + 1

            elif tag == "DW_TAG_variable":
                addr = self._static_addr(die)
                type_off = self._ref(cu, die.attributes.get("DW_AT_type"))
                path = "::".join([*ns, name]) if name else ""
                if name and addr is not None:
                    self.variables.setdefault(path, Variable(
                        name=name, path=path, addr=addr,
                        type_off=type_off,
                        decl_file=self._decl_file(die, files)))
                elif name and type_off is not None and self._is_decl(die):
                    self.variable_declarations.setdefault(path, []).append(
                        Variable(name=name, path=path, addr=0,
                                 type_off=type_off,
                                 decl_file=self._decl_file(die, files)))

            elif tag == "DW_TAG_formal_parameter":
                host_fn = stack[-1][4] if stack else None
                if host_fn is not None:
                    host_fn.params.append(name)

            elif tag == "DW_TAG_subprogram":
                low = die.attributes.get("DW_AT_low_pc")
                if name and low is not None and isinstance(low.value, int):
                    addr: int | None = low.value
                    if self._exec_ranges and not self._in_exec(addr):
                        addr = None
                        self.functions_tombstoned += 1
                    new_fn = Function(
                        name=name, path="::".join([*ns, name]),
                        low_pc=addr,
                        decl_file=self._decl_file(die, files))
                    self.functions.append(new_fn)

            elif tag == "DW_TAG_inlined_subroutine":
                host = next((fr[4].path for fr in reversed(stack)
                             if fr[4] is not None), None)
                site = self._inline_site(cu, die, files, host)
                if site is not None:
                    self.inline_sites.append(site)

            new_enum: tuple[str, dict[str, int]] | None = None
            new_array: int | None = None

            if tag in _STRUCT_TAGS and not self._is_decl(die):
                sz = die.attributes.get("DW_AT_byte_size")
                new_struct = StructLayout(
                    name=name or "",
                    size=sz.value if sz is not None else None,
                    path="::".join([*ns, name]) if name else "")
                self._struct_by_off[die.offset] = new_struct
                if not die.has_children:
                    self._commit(new_struct)
                    new_struct = None
            elif tag == "DW_TAG_enumeration_type" and name:
                new_enum = ("::".join([*ns, name]), {})
            elif tag == "DW_TAG_array_type":
                new_array = die.offset

            new_var: tuple | None = None
            if tag == "DW_TAG_variant_part":
                new_var = (top_struct(), _NOT_IN_VARIANT)
            elif tag == "DW_TAG_variant":
                parent = top_variant()
                dv = die.attributes.get("DW_AT_discr_value")
                new_var = (parent[0] if parent else None,
                           dv.value if dv is not None else None)

            if die.has_children:
                pushed_ns = tag == "DW_TAG_namespace" and bool(name)
                if pushed_ns:
                    ns.append(name)
                stack.append((pushed_ns, new_struct, new_enum, new_array,
                              new_fn, new_var))
            elif new_enum is not None:
                self.enums.setdefault(new_enum[0], {})

        while stack:
            pushed_ns, done, en, _, _, _ = stack.pop()
            if pushed_ns and ns:
                ns.pop()
            if done is not None:
                self._commit(done)
            if en is not None and en[1]:
                self.enums.setdefault(en[0], {}).update(en[1])

    @staticmethod
    def _member_offset(v) -> int | None:
        if isinstance(v, int):
            return v
        if isinstance(v, (bytes, bytearray, list)) and len(v) >= 2:
            b = bytes(v)
            if b[0] != 0x23:                    # DW_OP_plus_uconst
                return None
            n = shift = 0
            for byte in b[1:]:
                n |= (byte & 0x7F) << shift
                if not byte & 0x80:
                    return n
                shift += 7
        return None

    @staticmethod
    def _ref(cu, attr) -> int | None:
        if attr is None:
            return None
        if attr.form in _CU_RELATIVE_REFS:
            return cu.cu_offset + attr.value
        if attr.form == "DW_FORM_ref_addr":
            return attr.value
        return None

    @staticmethod
    def _name(die) -> str | None:
        a = die.attributes.get("DW_AT_name")
        if a is None:
            return None
        v = a.value
        return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

    @staticmethod
    def _is_decl(die) -> bool:
        a = die.attributes.get("DW_AT_declaration")
        return bool(a is not None and a.value)

    @staticmethod
    def _static_addr(die) -> int | None:
        a = die.attributes.get("DW_AT_location")
        if a is None or not isinstance(a.value, (list, bytes, bytearray)):
            return None
        b = bytes(a.value)
        try:
            size = die.cu["address_size"]
        except Exception:
            return None
        if len(b) < 1 + size or b[0] != _DW_OP_ADDR:
            return None
        addr = int.from_bytes(b[1:1 + size], "little")
        rest = b[1 + size:]
        if not rest:
            return addr
        if rest[0] != _DW_OP_PLUS_UCONST:
            return None
        k, n = _uleb(rest, 1)
        return None if k is None or n != len(rest) else addr + k

    def _commit(self, s: StructLayout) -> None:
        if not s.path:
            return
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
            base = _generic_base(s.path)
            if base != s.path:
                self._by_base.setdefault(base, []).append(s)
            sbase = _generic_base(s.name)
            if sbase != s.name:
                self._by_base.setdefault(sbase, []).append(s)


    def _pick(self, name: str, cands: list[StructLayout],
              how: str) -> StructLayout | None:
        if len(cands) == 1:
            return cands[0]
        first = cands[0]
        if all(c.fields == first.fields and c.size == first.size for c in cands):
            return first
        paths = "、".join(sorted({c.path for c in cands}))
        self.conflicts[name] = (
            f"{how} {name} 对应多个布局不同的类型（{paths}），请用完整路径指定")
        return None

    def find(self, name: str) -> StructLayout | None:
        if name in self.structs:
            return self.structs[name]
        cands = self._by_short.get(name)
        if cands:
            return self._pick(name, cands, "短名")
        cands = self._by_base.get(name)
        if cands:
            return self._pick(name, cands, "泛型基名")
        return None

    def type_off(self, name: str | None) -> int | None:
        if name is None:
            return None
        s = self.find(name)
        if s is None:
            return None
        if self._off_by_struct is None:
            self._off_by_struct = {id(v): k
                                   for k, v in self._struct_by_off.items()}
        return self._off_by_struct.get(id(s))

    def size_by_name(self, name: str | None) -> int | None:
        if not name:
            return None
        off = self.type_off(name)
        if off is not None:
            return self.size_of(off)
        sizes = {sz for tag, n, _ref, sz in self._types.values()
                 if tag == "DW_TAG_base_type" and n == name and sz is not None}
        return sizes.pop() if len(sizes) == 1 else None


    def _strip(self, off: int | None, *, max_hops: int = 16) -> int | None:
        seen: set[int] = set()
        while off is not None and off in self._types and off not in seen:
            seen.add(off)
            tag, _name, ref, _sz = self._types[off]
            if tag not in _TRANSPARENT or ref is None:
                return off
            off = ref
            if len(seen) > max_hops:
                break
        return off

    def knows_type(self, off: int | None) -> bool:
        return off is not None and off in self._types

    def type_name(self, off: int | None) -> str | None:
        off = self._strip(off)
        if off is None or off not in self._types:
            return None
        tag, name, ref, _sz = self._types[off]
        if name:
            return name
        inner = self.type_name(ref) if ref is not None else None
        if tag == "DW_TAG_pointer_type":
            return f"*{inner}" if inner else "*"
        if tag == "DW_TAG_array_type":
            n = self.array_counts.get(off)
            return f"[{inner or '?'}; {n}]" if n is not None else f"[{inner or '?'}]"
        return None

    def struct_at(self, off: int | None) -> StructLayout | None:
        off = self._strip(off)
        return self._struct_by_off.get(off) if off is not None else None

    def pointee(self, off: int | None) -> int | None:
        off = self._strip(off)
        if off is None or off not in self._types:
            return None
        tag, _n, ref, _s = self._types[off]
        return ref if tag == "DW_TAG_pointer_type" else None

    def size_of(self, off: int | None) -> int | None:
        off = self._strip(off)
        if off is None or off not in self._types:
            return None
        tag, _n, ref, sz = self._types[off]
        if tag == "DW_TAG_array_type":
            n = self.array_counts.get(off)
            es = self.size_of(ref)
            return n * es if n is not None and es is not None else sz
        if sz is not None:
            return sz
        if tag == "DW_TAG_pointer_type":
            return 8 if self.e_machine in ("EM_RISCV", "EM_X86_64", "EM_AARCH64") else None
        return None

    def array_of(self, off: int | None) -> tuple[int | None, int | None] | None:
        off = self._strip(off)
        if off is None or off not in self._types:
            return None
        tag, _n, ref, _s = self._types[off]
        if tag != "DW_TAG_array_type":
            return None
        return ref, self.array_counts.get(off)

    def var_at(self, addr: int) -> Variable | None:
        if self._by_addr is None:
            idx: dict[int, list[Variable]] = {}
            for v in self.variables.values():
                if v.addr:
                    idx.setdefault(v.addr, []).append(v)
            self._by_addr = idx
        cands = self._by_addr.get(addr) or []
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            offs = {c.type_off for c in cands}
            if len(offs) == 1:
                return cands[0]
            self.conflicts[f"@{addr:#x}"] = (
                f"地址 {addr:#x} 上有多个类型不同的静态变量"
                f"（{'、'.join(sorted(c.path for c in cands))}），不据此定类型")
        return None

    def var(self, name: str) -> Variable | None:
        if name in self.variables:
            return self.variables[name]
        cands = [v for v in self.variables.values() if v.name == name]
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            self.conflicts[name] = (
                f"静态变量短名 {name} 对应多个符号"
                f"（{'、'.join(sorted(c.path for c in cands))}），请用完整路径指定")
        return None

    def var_decl(self, name: str) -> Variable | None:
        """Return a unique type-only global declaration.

        A declaration never supplies storage: callers must independently
        resolve the same name in the ELF symbol table. Duplicate DIEs are
        accepted only when their observable type shape agrees; otherwise the
        join is ambiguous and is refused.
        """
        cands = list(self.variable_declarations.get(name, ()))
        if not cands:
            cands = [v for vs in self.variable_declarations.values() for v in vs
                     if v.name == name]
        if not cands:
            return None
        shapes = {(self.type_name(v.type_off), self.size_of(v.type_off))
                  for v in cands}
        if len(shapes) == 1:
            return cands[0]
        self.conflicts[f"declaration:{name}"] = (
            f"全局变量声明 {name!r} 对应多个不同类型，不能把 ELF 地址和任意一个"
            f"声明拼在一起")
        return None
