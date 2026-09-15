
from __future__ import annotations

from dataclasses import dataclass, field

from .ctxbuild import build_ctx
from .dwarfsrc import DwarfSource
from .exec import Executor, Node
from .manifest import Manifest
from .plan import Plan, compile_source
from .probe import (ProbeResult, ResolvedEntity, ResolvedField,
                    combined_completeness as _completeness)
from .readers.registry import make as make_reader
from .resolve import (ABSENT, EMPTY, PRESENT, UNDECODABLE, btree_opts,
                      layer_chain, qualified_name, reader_layer_die,
                      shell_opts, string_opts, vec_opts)
from .rt import Memory, ReadCtx, Unavailable, Value


@dataclass
class Field:

    name: str
    state: str
    value: Value = None
    reason: str | None = None
    role: str | None = None
    links_to: str | None = None
    #: `FieldSpec.inverse`。
    inverse: str | None = None
    reader: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == PRESENT


@dataclass
class Entity:

    kind: str
    addr: int
    fields: dict[str, Field] = field(default_factory=dict)
    trail: list[str] = field(default_factory=list)
    links: dict[str, list["Entity"]] = field(default_factory=dict, repr=False)

    def link(self, name: str) -> "Entity | None":
        got = self.links.get(name) or []
        return got[0] if got else None

    def get(self, name: str) -> Value:
        f = self.fields.get(name)
        return f.value if f is not None and f.ok else None

    def role(self, role: str) -> Value:
        for f in self.fields.values():
            if f.role == role and f.ok:
                return f.value
        return None


def is_live(entity: Entity, liveness: dict | None) -> bool:
    sw = (liveness or {}).get("skip_when")
    if not sw or "field" not in sw:
        return True
    f = entity.fields.get(sw["field"])
    if f is None or not f.ok:
        return True
    if "equals" in sw:
        return f.value != sw["equals"]
    return True


@dataclass
class EntitySet:

    kind: str
    entities: list[Entity] = field(default_factory=list)
    completeness: str = "unknown"
    completeness_reason: str | None = None
    problems: list[Unavailable] = field(default_factory=list)
    truncated: bool = False
    cycles: int = 0
    unavailable: str | None = None
    dangling: int = 0

    @property
    def ok(self) -> bool:
        return self.unavailable is None and not self.problems


@dataclass
class Snapshot:

    sets: dict[str, EntitySet] = field(default_factory=dict)
    index: dict[int, Entity] = field(default_factory=dict, repr=False)

    def all(self, kind: str) -> list[Entity]:
        s = self.sets.get(kind)
        return s.entities if s else []

    def at(self, addr: int) -> Entity | None:
        return self.index.get(addr)

    @property
    def problems(self) -> list[Unavailable]:
        out: list[Unavailable] = []
        for s in self.sets.values():
            if s.unavailable is not None:
                out.append(Unavailable(s.unavailable))
            out.extend(s.problems)
        return out

    @property
    def truncated(self) -> bool:
        return any(s.truncated for s in self.sets.values())


class SnapshotBuilder:

    def __init__(self, dw: DwarfSource, res: ProbeResult, m: Manifest,
                 *, syms=None, ptr_size: int = 8,
                 max_items: int = 4096) -> None:
        self.dw = dw
        self.res = res
        self.m = m
        self.ctx: ReadCtx = build_ctx(dw, res, ptr_size=ptr_size,
                                      max_items=max_items)
        self._plans: dict[str, list[Plan]] = {}
        self._why: dict[str, str] = {}
        self._readers: dict[str, dict[str, object]] = {}
        self._compile(syms)


    def _compile(self, syms) -> None:
        by_name = {e.name: e for e in self.m.entities}
        for r in self.res.entities:
            spec = by_name.get(r.name)
            if not r.sources or spec is None:
                self._plans[r.name] = []
                self._why[r.name] = (
                    r.reason or "没有可用的 source —— manifest 里的 when 都不成立")
                continue

            plans, bad = [], []
            for i, src in enumerate(r.sources):
                p = compile_source(self.dw, r.name, src, syms=syms,
                                   struct_path=r.struct_path)
                if p.compiled:
                    plans.append(p)
                else:
                    bad.append(f"[{i}] {p.reason or '计划没编译成功'}")
            self._plans[r.name] = plans
            if bad:
                self._why[r.name] = (
                    "；".join(bad) if not plans else
                    f"{len(r.sources)} 条 source 里有 {len(bad)} 条编不出来，"
                    f"枚举结果少了它们那一部分：" + "；".join(bad))
            self._readers[r.name] = self._field_readers(r)

    def _field_readers(self, r: ResolvedEntity) -> dict[str, object]:
        out: dict[str, object] = {}
        for f in r.fields:
            if f.state != PRESENT:
                continue
            if not f.reader:
                out[f.name] = Unavailable(
                    f"字段 {f.name!r} 在 manifest 里没写 reader，不知道该怎么解")
                continue
            rd, why = make_reader(f.reader, type_name=f.type_name,
                                  opts=self._opts(f))
            out[f.name] = rd if rd is not None else Unavailable(
                f"字段 {f.name!r} 的 reader {f.reader!r} 造不出来：{why}")
        return out

    def _opts(self, f: ResolvedField) -> dict:
        o: dict = {}
        if f.enum:
            o["enum"] = f.enum
            sz = self.dw.size_of(f.type_off)
            if sz:
                o["enum_size"] = sz
        arr = self.dw.array_of(f.type_off)
        if arr is not None:
            elem_off, count = arr
            if count is not None:
                o["count"] = o["maxlen"] = count
            es = self.dw.size_of(elem_off)
            if es is not None:
                o["elem_size"] = es
        else:
            o.update(vec_opts(self.dw, f.type_off))
            if f.type_name:
                o.setdefault("vec_type", f.type_name)
        o.update(string_opts(self.dw, f.type_off))
        if f.reader:
            map_off = reader_layer_die(self.dw, f.reader, f.type_off,
                                       "btreemap")
            if map_off is not None:
                map_type = qualified_name(self.dw, map_off)
                if map_type:
                    o["btree_map_type"] = map_type
                o.update(btree_opts(self.dw, map_off))
        o.update(shell_opts(self.dw, f.type_off))
        if f.reader:
            chain = layer_chain(self.dw, f.reader, f.type_off)
            if chain:
                o["layer_chain"] = chain
        return o


    def compiled(self, name: str) -> bool:
        return bool(self._plans.get(name))

    def entity_for(self, role: str, *, fallback: str = ""):
        """Return the role-bearing entity whose source compiled for this ELF.

        A family manifest may describe structurally exclusive entities.  rCore
        ch1--ch7 expose tasks as processes, while ch8 has a real process object
        plus per-process threads.  ``Manifest.entity_for`` can only see the
        declarations; this builder can also see which declaration applies to
        the current binary.

        Declaration order remains the tie-breaker.  If no candidate compiled,
        return the first declared candidate so callers can report *its actual
        compilation failure* instead of silently falling back to another
        decoder.
        """
        candidates = [e for e in self.m.entities if e.role == role]
        hit = next((e for e in candidates if self.compiled(e.name)), None)
        if hit is not None:
            return hit
        if candidates:
            return candidates[0]
        return self.m.entity(fallback) if fallback else None

    def why_not(self, name: str) -> str:
        return self._why.get(name, "")


    def build(self, mem: Memory) -> Snapshot:
        snap = Snapshot()
        ex = Executor(mem, self.ctx)
        for r in self.res.entities:
            snap.sets[r.name] = self._one(ex, mem, r)
        for s in snap.sets.values():
            for e in s.entities:
                snap.index.setdefault(e.addr, e)
        self._link(snap)
        return snap

    def _link(self, snap: Snapshot) -> None:
        for s in snap.sets.values():
            for e in s.entities:
                for name, f in e.fields.items():
                    if not f.links_to or not f.ok:
                        continue
                    addrs = f.value if isinstance(f.value, list) else [f.value]
                    got: list[Entity] = []
                    for a in addrs:
                        if not isinstance(a, int):
                            continue
                        t = snap.index.get(a)
                        if t is None:
                            s.dangling += 1
                        else:
                            got.append(t)
                    if got:
                        e.links[name] = got
                    if f.inverse:
                        for t in got:
                            back = t.links.setdefault(f.inverse, [])
                            if not any(x is e for x in back):
                                back.append(e)

    def _one(self, ex: Executor, mem: Memory, r: ResolvedEntity) -> EntitySet:
        es = EntitySet(kind=r.name, **_completeness(r.sources))

        plans = self._plans.get(r.name) or []
        if not plans:
            es.unavailable = self._why.get(r.name, "没编出计划")
            return es

        if len(plans) < len(r.sources):
            es.problems.append(Unavailable(
                self._why.get(r.name)
                or f"{r.name} 有 source 没编出计划，但没记下是哪一条"))

        seen: set[int] = set()
        for p in plans:
            w = ex.run(p)
            es.problems.extend(w.problems)
            es.truncated = es.truncated or w.truncated
            es.cycles = es.cycles or w.cycles
            for node in w.nodes:
                if node.addr in seen:
                    continue
                seen.add(node.addr)
                es.entities.append(self._decode(mem, r, node))
        return es

    def _decode(self, mem: Memory, r: ResolvedEntity, node: Node) -> Entity:
        ent = Entity(kind=r.name, addr=node.addr, trail=list(node.trail))
        readers = self._readers.get(r.name, {})
        for f in r.fields:
            ent.fields[f.name] = self._field(mem, f, readers.get(f.name), node)
        return ent

    def _field(self, mem: Memory, f: ResolvedField, rd,
               node: Node) -> Field:
        common = {"role": f.role, "links_to": f.links_to,
                  "inverse": f.inverse, "reader": f.reader}

        if f.state == ABSENT:
            return Field(f.name, ABSENT, reason=f.reason, **common)
        if f.state == UNDECODABLE:
            return Field(f.name, UNDECODABLE, reason=f.reason, **common)
        if isinstance(rd, Unavailable):
            return Field(f.name, UNDECODABLE, reason=rd.reason, **common)
        if rd is None or f.offset is None:
            return Field(f.name, UNDECODABLE,
                         reason=f"字段 {f.name!r} 没有偏移或没有 reader", **common)

        v = rd(mem, node.addr + f.offset, self.ctx)
        if isinstance(v, Unavailable):
            return Field(f.name, UNDECODABLE, reason=v.reason, **common)
        if v is None:
            return Field(f.name, EMPTY, reason="值为空", **common)
        return Field(f.name, PRESENT, value=v, **common)


def report(snap: Snapshot) -> str:
    out: list[str] = []
    for kind, s in snap.sets.items():
        if s.unavailable:
            out.append(f"{kind}：解不出来 —— {s.unavailable}")
            continue
        n = len(s.entities)
        head = f"{kind}：{'至少 ' if s.truncated or s.completeness == 'partial' else ''}{n} 个"
        if s.completeness == "partial":
            head += f"（只枚举得到一部分{'：' + s.completeness_reason if s.completeness_reason else ''}）"
        if s.truncated:
            head += "（到上限被截断）"
        if s.cycles:
            head += f"（遇到 {s.cycles} 次回边）"
        if s.dangling:
            head += f"（{s.dangling} 条边指向没枚举到的对象）"
        out.append(head)
        for e in s.entities[:12]:
            got = [f"{k}={v.value!r}" for k, v in e.fields.items() if v.ok]
            bad = [k for k, v in e.fields.items() if v.state == UNDECODABLE]
            line = f"  @{e.addr:#x}  " + "  ".join(got[:6])
            if bad:
                line += f"   解不出来：{'、'.join(bad)}"
            out.append(line)
        if n > 12:
            out.append(f"  …… 还有 {n - 12} 个")
        if s.problems:
            out.append(f"  路上出的问题 {len(s.problems)} 处：")
            for p in s.problems[:5]:
                where = f" @{p.addr:#x}" if p.addr is not None else ""
                out.append(f"    {p.reason}{where}")
    return "\n".join(out)
