
from __future__ import annotations

import re
from dataclasses import dataclass


_ESC = {"SP": "@", "BP": "*", "RF": "&", "LT": "<", "GT": ">",
        "LP": "(", "RP": ")", "C": ","}

_HASH = re.compile(r"^h[0-9a-f]{16}$")

_LLVM_SUFFIX = re.compile(r"\.llvm\.\d+$")


def _unescape(t: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(t):
        if t[i] == "$":
            j = t.find("$", i + 1)
            if j > 0:
                code = t[i + 1:j]
                if code in _ESC:
                    out.append(_ESC[code])
                    i = j + 1
                    continue
                if code.startswith("u") and len(code) > 1:
                    try:
                        out.append(chr(int(code[1:], 16)))
                        i = j + 1
                        continue
                    except ValueError:
                        pass
        out.append(t[i])
        i += 1
    return "".join(out)


def demangle(sym: str) -> str | None:
    return _demangle_legacy(sym) or demangle_v0(sym)


def _demangle_legacy(sym: str) -> str | None:
    s = _LLVM_SUFFIX.sub("", sym)
    if not s.startswith("_ZN") or not s.endswith("E"):
        return None
    body, i, parts = s[3:-1], 0, []
    while i < len(body):
        j = i
        while j < len(body) and body[j].isdigit():
            j += 1
        if j == i:
            return None
        n = int(body[i:j])
        seg, i = body[j:j + n], j + n
        if len(seg) != n:
            return None
        parts.append(seg)
    if parts and _HASH.match(parts[-1]):
        parts.pop()
    out = []
    for p in parts:
        if p.startswith("_$"):
            p = p[1:]
        p = _unescape(p).replace("..", "::")
        out.append(p)
    return "::".join(out)




class _Bail(Exception):
    pass


def _v0_disambiguator(s: str, i: int) -> int:
    if i < len(s) and s[i] == "s":
        j = i + 1
        while j < len(s) and s[j].isalnum():
            j += 1
        if j >= len(s) or s[j] != "_":
            raise _Bail
        return j + 1
    return i


def _v0_ident(s: str, i: int) -> tuple[str, int]:
    if i < len(s) and s[i] == "u":
        raise _Bail                   # punycode
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    if j == i:
        raise _Bail
    n = int(s[i:j])
    if j < len(s) and s[j] == "_":
        j += 1
    seg = s[j:j + n]
    if len(seg) != n:
        raise _Bail
    return seg, j + n


_V0_NS = frozenset("tv")


def _v0_base62(s: str, i: int) -> tuple[int, int]:
    j = i
    while j < len(s) and s[j].isalnum():
        j += 1
    if j >= len(s) or s[j] != "_":
        raise _Bail
    digits = s[i:j]
    if not digits:
        return 0, j + 1
    v = 0
    for ch in digits:
        if ch.isdigit():
            d = ord(ch) - 48
        elif ch.islower():
            d = ord(ch) - 97 + 10
        else:
            d = ord(ch) - 65 + 36
        v = v * 62 + d
    return v + 1, j + 1


_V0_BASIC = frozenset("abcdefhijlmnopstuvxyz")


def _v0_lifetime(s: str, i: int) -> int:
    if i < len(s) and s[i] == "L":
        _, i = _v0_base62(s, i + 1)
    return i


def _v0_const(s: str, i: int, impls: bool, generics: bool) -> int:
    if i >= len(s):
        raise _Bail
    if s[i] == "B":
        val, j = _v0_base62(s, i + 1)
        if val >= i:
            raise _Bail
        return j
    if s[i] == "p":
        return i + 1
    i = _v0_type(s, i, impls, generics)
    if i < len(s) and s[i] == "n":
        i += 1
    j = i
    while j < len(s) and s[j] in "0123456789abcdef":
        j += 1
    if j >= len(s) or s[j] != "_":
        raise _Bail
    return j + 1


def _v0_type(s: str, i: int, impls: bool, generics: bool) -> int:
    if i >= len(s):
        raise _Bail
    c = s[i]
    if c in _V0_BASIC:
        return i + 1
    if c in "CNMXYIB":
        _, j = _v0_path(s, i, impls, generics)
        return j
    if c == "A":                              # [T; N]
        return _v0_const(s, _v0_type(s, i + 1, impls, generics), impls, generics)
    if c in "SPO":                            # [T] / *const T / *mut T
        return _v0_type(s, i + 1, impls, generics)
    if c in "RQ":                             # &T / &mut T
        return _v0_type(s, _v0_lifetime(s, i + 1), impls, generics)
    if c == "T":
        i += 1
        while i < len(s) and s[i] != "E":
            i = _v0_type(s, i, impls, generics)
        if i >= len(s):
            raise _Bail
        return i + 1
    raise _Bail


def _v0_path(s: str, i: int, impls: bool = False,
             generics: bool = False) -> tuple[list[str], int]:
    c = s[i] if i < len(s) else ""
    if c == "C":
        i = _v0_disambiguator(s, i + 1)
        name, i = _v0_ident(s, i)
        return [name], i
    if c == "N":
        if i + 1 >= len(s) or s[i + 1] not in _V0_NS:
            raise _Bail
        segs, i = _v0_path(s, i + 2, impls, generics)
        i = _v0_disambiguator(s, i)
        name, i = _v0_ident(s, i)
        return [*segs, name], i
    if (impls or generics) and c == "B":
        val, j = _v0_base62(s, i + 1)
        if val >= i:
            raise _Bail
        segs, _ = _v0_path(s, val, impls, generics)
        return segs, j
    if impls and c == "M":
        i = _v0_disambiguator(s, i + 1)
        _mod, i = _v0_path(s, i, impls, generics)
        tsegs, i = _v0_path(s, i, impls, generics)
        return tsegs, i
    if generics and c == "X":                 # trait impl `<T as Trait>`
        i = _v0_disambiguator(s, i + 1)
        _mod, i = _v0_path(s, i, impls, generics)
        tsegs, i = _v0_path(s, i, impls, generics)
        _trait, i = _v0_path(s, i, impls, generics)
        return tsegs, i
    if generics and c == "I":
        segs, i = _v0_path(s, i + 1, impls, generics)
        while i < len(s) and s[i] != "E":
            if s[i] == "K":
                i = _v0_const(s, i + 1, impls, generics)
            elif s[i] == "L":
                i = _v0_lifetime(s, i)
            else:
                i = _v0_type(s, i, impls, generics)
        if i >= len(s):
            raise _Bail
        return segs, i + 1
    raise _Bail


def demangle_v0(sym: str, *, impls: bool = False,
                generics: bool = False) -> str | None:
    s = _LLVM_SUFFIX.sub("", sym)
    if not s.startswith("_R"):
        return None
    body = s[2:]
    if body[:1].isdigit():
        return None
    try:
        segs, i = _v0_path(body, 0, impls, generics)
        if generics and i < len(body):
            _inst, i = _v0_path(body, i, impls, generics)
    except (_Bail, IndexError, RecursionError):
        return None
    if i != len(body) or not segs:
        return None
    return "::".join(segs)


#: `__rustc::rust_begin_unwind`。
SYNTHETIC_CRATES = frozenset({"__rustc"})


def is_synthetic_path(path: str) -> bool:
    return bool(path) and path.split("::", 1)[0] in SYNTHETIC_CRATES


_LAZY_TAIL = " as core::ops::deref::Deref>::deref::__stability::LAZY"


def _lazy_shape(path: str) -> str:
    return f"<{path}{_LAZY_TAIL}"


def _lazy_inner(demangled: str) -> str | None:
    if demangled.startswith("<") and demangled.endswith(_LAZY_TAIL):
        return demangled[1:-len(_LAZY_TAIL)]
    return None



@dataclass(frozen=True)
class Sym:
    name: str
    addr: int
    size: int
    how: str
    type_off: int | None = None


class SymbolIndex:

    def __init__(self, elf, dw=None) -> None:
        syms = getattr(elf, "symbols", None)
        if syms is None:
            raise TypeError(
                f"SymbolIndex 要一个带 .symbols 的 ELF 对象（host.nfelf.Elf64），"
                f"给到的是 {type(elf).__name__}。传路径的话符号表读不进来，"
                f"查不到的静态量会被报成'内核里没有'，而不是'没去查'。")
        self.elf = elf
        self.dw = dw
        self._by_demangled: dict[str, list] = {}
        self._by_raw: dict[str, list] = {}
        self._v0 = 0
        for s in syms:
            if not s.name or not s.value:
                continue
            self._by_raw.setdefault(s.name, []).append(s)
            if s.name.startswith("_R"):
                self._v0 += 1
                continue
            d = demangle(s.name)
            if d:
                self._by_demangled.setdefault(d, []).append(s)


    @staticmethod
    def _uniq(cands: list) -> tuple[object | None, str]:
        if not cands:
            return None, ""
        addrs = {c.value for c in cands}
        if len(addrs) > 1:
            got = "、".join(f"{c.name}@{c.value:#x}" for c in cands[:3])
            return None, f"{len(addrs)} 个地址都匹配（{got}），无法确定用哪个"
        return cands[0], ""

    def _pick(self, cands: list, path: str, how: str) -> tuple[Sym | None, str]:
        s, why = self._uniq(cands)
        if s is None:
            return None, why
        # C compilers sometimes emit the global's address only in the ELF
        # symbol table and its exact array/struct type only on an ``extern``
        # DWARF declaration. Name equality plus uniqueness is a factual join,
        # just like the existing address-based join used for lazy_static.
        decl = (getattr(self.dw, "var_decl", lambda _name: None)(path)
                if self.dw is not None else None)
        if decl is not None:
            return Sym(name=path, addr=s.value, size=s.size,
                       how=f"{how}+DWARF声明({decl.path})",
                       type_off=decl.type_off), ""
        return Sym(name=path, addr=s.value, size=s.size, how=how), ""


    def resolve(self, path: str) -> tuple[Sym | None, str]:
        if self.dw is not None:
            v = self.dw.var(path)
            # lazy_static also emits a zero-sized public wrapper with the
            # requested path.  Some rustc/DWARF versions describe that wrapper
            # as a variable at address 0, alongside the real hidden ``LAZY``
            # storage in the ELF symbol table.  Address zero plus zero-sized
            # type is not storage, so do not let it shadow the real symbol.
            # A positive-sized object at address zero remains valid (important
            # for bare-metal link layouts which genuinely start at zero).
            size = (self.dw.size_of(v.type_off) if v is not None else None)
            if v is not None and (v.addr != 0 or bool(size)):
                return Sym(name=path, addr=v.addr, size=0, how="dwarf",
                           type_off=v.type_off), ""

        for cands, how in ((self._by_demangled.get(path, []), "elf"),
                           (self._by_demangled.get(_lazy_shape(path), []),
                            "lazy_static"),
                           (self._by_raw.get(path, []), "elf_raw")):
            if cands:
                return self._pick(cands, path, how)

        tail = "::" + path
        hits = []
        for d, ss in self._by_demangled.items():
            inner = _lazy_inner(d)
            name = d if inner is None else inner
            if name == path or name.endswith(tail):
                hits += ss
        if hits:
            return self._pick(hits, path, "suffix")

        extra = (f"（另有 {self._v0} 个 v0 修饰的符号没解，"
                 f"本工具只认旧版修饰）" if self._v0 else "")
        return None, (f"DWARF 变量表和 ELF 符号表里都没有 {path!r}"
                      f"，也没有它的 lazy_static 静态量{extra}")

    def candidates(self, needle: str, limit: int = 8) -> list[str]:
        out = sorted({d for d in self._by_demangled if needle in d})
        return out[:limit]
