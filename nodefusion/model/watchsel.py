
from __future__ import annotations

from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from typing import Iterable

from .dwarfsrc import DwarfSource
from .manifest import WatchSpec
from .symbols import demangle, demangle_v0, is_synthetic_path

DERIVE = "*"


@dataclass(frozen=True)
class Cand:

    path: str
    addr: int | None
    decl_file: str | None = None
    aliases: tuple[str, ...] = ()
    inlined: bool = False

    @property
    def name(self) -> str:
        return bare_name(self.path)

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class Selected:

    name: str
    path: str
    subsystem: str
    addr: int
    args: int
    throttle: int
    snapshot: str = "none"


@dataclass
class Selection:

    picked: list[Selected] = field(default_factory=list)
    no_address: dict[str, int] = field(default_factory=dict)
    empty_rules: list[str] = field(default_factory=list)


def _as_list(v: object) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


def bare_name(path: str, fallback: str = "") -> str:
    depth = 0
    out = []
    for ch in path:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    stripped = "".join(out)
    last = stripped.rsplit("::", 1)[-1].strip()
    return last or fallback or path


def impl_path(path: str) -> str:
    if not path.startswith("<"):
        return path
    depth = 0
    for i, ch in enumerate(path):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                inner, rest = path[1:i], path[i + 1:]
                head = inner.split(" as ", 1)[0].strip()
                if not head:
                    return path
                return head + rest
    return path


def _module_hit(path: str, mods: list[str]) -> str | None:
    for m in mods:
        if path == m or path.startswith(m + "::"):
            return m
    return None


def _file_hit(decl: str | None, files: list[str]) -> str | None:
    if not decl:
        return None
    norm = decl.replace("\\", "/")
    for f in files:
        want = f.replace("\\", "/")
        if norm == want or norm.endswith("/" + want):
            return f
    return None


def _is_mapping_symbol(name: str) -> bool:
    return name.startswith("$") or name.startswith(".")


def candidates(dw: DwarfSource, symbols: Iterable = ()) -> list[Cand]:
    by_addr: dict[int, Cand] = {}
    no_addr: list[Cand] = []

    for fn in dw.functions:
        c = Cand(path=impl_path(fn.path or fn.name or ""), addr=fn.low_pc,
                 decl_file=fn.decl_file)
        if fn.low_pc is None:
            no_addr.append(c)
        else:
            by_addr.setdefault(fn.low_pc, c)

    for s in symbols:
        addr = getattr(s, "value", None)
        nm = getattr(s, "name", "") or ""
        if not addr or not nm or _is_mapping_symbol(nm):
            continue
        path = demangle(nm)
        path = impl_path(path) if path else path
        old = by_addr.get(addr)
        if old is None:
            if not path:
                alt = demangle_v0(nm, impls=True)
                path = impl_path(alt) if alt else path
            by_addr[addr] = Cand(path=path or nm, addr=addr)
            continue

        new = old
        if path and is_synthetic_path(path):
            abi = bare_name(path)
            if abi and abi not in new.names:
                new = replace(new, aliases=(*new.aliases, abi))
        elif path and path != old.path:
            keep = old.name
            new = replace(old, path=path)
            if keep and keep not in new.names:
                new = replace(new, aliases=(*new.aliases, keep))
        elif not path and nm not in new.names:
            new = replace(new, aliases=(*new.aliases, nm))
        by_addr[addr] = new

    inline_alts: list[Cand] = []
    inline_keys: set[tuple[int, str]] = set()
    for site in getattr(dw, "inline_sites", ()):
        path = impl_path(site.path)
        key = (site.addr, path)
        if key in inline_keys:
            continue
        inline_keys.add(key)
        cand = Cand(path=path, addr=site.addr,
                    decl_file=site.decl_file, inlined=True)
        old = by_addr.get(site.addr)
        if old is None:
            by_addr[site.addr] = cand
        elif old.path != path:
            inline_alts.append(cand)

    return sorted([*by_addr.values(), *inline_alts],
                  key=lambda c: c.addr or 0) + no_addr


def _matches(fn: Cand, spec: dict) -> tuple[bool, str | None]:
    path = fn.path or ""
    where: str | None = None
    tested = False

    mods = _as_list(spec.get("module"))
    if mods:
        tested = True
        where = _module_hit(path, mods)
        if where is None:
            return False, None

    prefixes = _as_list(spec.get("module_prefix"))
    if prefixes:
        tested = True
        pre = next((p for p in prefixes if path.startswith(p)), None)
        if pre is None:
            return False, None
        where = path[len(pre):].split("::", 1)[0] or pre

    files = _as_list(spec.get("file"))
    if files:
        tested = True
        where = _file_hit(fn.decl_file, files)
        if where is None:
            return False, None

    pats = _as_list(spec.get("fn"))
    if pats:
        tested = True
        if not any(fnmatchcase(n, p) for n in fn.names for p in pats):
            return False, None

    return tested, where


def _rule_label(w: WatchSpec) -> str:
    bits = []
    for k in ("module", "module_prefix", "file", "fn"):
        if k in w.match:
            bits.append(f"{k}={w.match[k]!r}")
    return f"[{w.subsystem}] " + ("，".join(bits) or "（match 是空的）")


def _unique_name(path: str, taken: set[str]) -> str | None:
    segs = _split_path(path)
    for i in range(len(segs) - 1, -1, -1):
        cand = "::".join(segs[i:])
        if cand and cand not in taken:
            return cand
    return None


def _inline_name(path: str, taken: set[str], base_of: dict[str, str]) -> str:
    base = base_of.get(path)
    if base is None:
        segs = _split_path(path) or [path]
        used = set(base_of.values())
        base = next(("::".join(segs[i:]) for i in range(len(segs) - 1, -1, -1)
                     if "::".join(segs[i:]) not in used), path)
        base_of[path] = base
    i = 0
    while f"{base}@{i}" in taken:
        i += 1
    return f"{base}@{i}"


def _split_path(path: str) -> list[str]:
    out, depth, cur = [], 0, []
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        if depth == 0 and path.startswith("::", i):
            out.append("".join(cur))
            cur = []
            i += 2
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s for s in out if s]


def select(dw: DwarfSource, watches: list[WatchSpec],
           *, symbols: Iterable = ()) -> Selection:
    out = Selection()
    cands = candidates(dw, symbols)
    seen_addr: set[int] = set()
    taken: set[str] = set()
    inline_base: dict[str, str] = {}

    for w in watches:
        n_hit = 0
        for fn in cands:
            if fn.inlined and not w.inlined:
                continue
            hit, where = _matches(fn, w.match or {})
            if not hit:
                continue
            n_hit += 1
            if w.skip:
                if fn.addr is not None:
                    seen_addr.add(fn.addr)
                continue
            sub = where or w.subsystem if w.subsystem == DERIVE else w.subsystem
            if fn.addr is None:
                out.no_address[sub] = out.no_address.get(sub, 0) + 1
                continue
            if fn.addr in seen_addr:
                continue
            nm = (_inline_name(fn.path, taken, inline_base) if fn.inlined
                  else _unique_name(fn.path, taken))
            if nm is None:
                continue
            seen_addr.add(fn.addr)
            taken.add(nm)
            out.picked.append(Selected(
                name=nm, path=fn.path, subsystem=sub, addr=fn.addr,
                args=w.args, throttle=w.throttle, snapshot=w.snapshot))
        if n_hit == 0:
            out.empty_rules.append(_rule_label(w))

    return out
