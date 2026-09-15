
from __future__ import annotations

from dataclasses import dataclass, field

from .dwarfsrc import DwarfSource
from .manifest import EntitySpec, Manifest, SourceSpec
from .resolve import ABSENT, PRESENT, UNDECODABLE, eval_when, resolve_path

_ARCH = {
    "EM_RISCV": "riscv64", "EM_X86_64": "x86_64",
    "EM_AARCH64": "aarch64", "EM_LOONGARCH": "loongarch64",
}


@dataclass
class ResolvedField:
    name: str
    path: str
    reader: str
    state: str
    offset: int | None = None
    type_name: str | None = None
    type_off: int | None = None
    reason: str | None = None
    optional: bool = False
    role: str | None = None
    hops: list[str] = field(default_factory=list)
    enum: str | None = None
    links_to: str | None = None
    inverse: str | None = None
    feature: str | None = None


def combined_completeness(sources: list) -> dict:
    if not sources:
        return {"completeness": "unknown", "completeness_reason": None}
    if len(sources) == 1:
        return {"completeness": sources[0].completeness,
                "completeness_reason": sources[0].reason}

    kinds = {s.completeness for s in sources}
    combined = ("total" if "total" in kinds
                else "partial" if "partial" in kinds
                else next(iter(kinds)) if len(kinds) == 1 else "partial")
    why = [f"（{i + 1}）{s.reason}"
           for i, s in enumerate(sources) if s.reason]
    return {"completeness": combined,
            "completeness_reason": (
                f"合了 {len(sources)} 条来源：" + " ".join(why) if why else None)}


@dataclass
class ResolvedEntity:
    name: str
    type: str
    struct_path: str | None = None
    size: int | None = None
    sources: list[SourceSpec] = field(default_factory=list)
    source_trace: list[str] = field(default_factory=list)
    fields: list[ResolvedField] = field(default_factory=list)
    reason: str | None = None

    @property
    def source(self) -> SourceSpec | None:
        return self.sources[0] if self.sources else None

    @property
    def ok(self) -> bool:
        return self.struct_path is not None and bool(self.sources)

    def counts(self) -> dict[str, int]:
        c = {PRESENT: 0, ABSENT: 0, UNDECODABLE: 0}
        for f in self.fields:
            c[f.state] = c.get(f.state, 0) + 1
        return c


@dataclass
class ProbeResult:
    kernel: str
    arch: str | None
    entities: list[ResolvedEntity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def undecodable(self) -> list[ResolvedField]:
        return [f for e in self.entities for f in e.fields
                if f.state == UNDECODABLE]

    def to_json(self) -> dict:
        return {
            "kernel": self.kernel, "arch": self.arch,
            "warnings": self.warnings,
            "entities": [{
                "name": e.name, "type": e.type, "struct": e.struct_path,
                "size": e.size, "reason": e.reason,
                **combined_completeness(e.sources),
                "source_kind": ("+".join(s.kind or "?" for s in e.sources)
                                if e.sources else None),
                "source_trace": e.source_trace,
                "fields": [{
                    "name": f.name, "path": f.path, "reader": f.reader,
                    "state": f.state, "offset": f.offset,
                    "type": f.type_name, "reason": f.reason,
                    "optional": f.optional, "role": f.role,
                    "hops": f.hops,
                } for f in e.fields],
            } for e in self.entities],
        }


def detect(manifests: dict[str, Manifest], dw: DwarfSource) -> tuple[str | None, list[str]]:
    hits: list[str] = []
    trace: list[str] = []
    for name, m in manifests.items():
        d = m.detect or {}
        why: list[str] = []
        ok = bool(d)
        if "any_type" in d:
            got = [t for t in d["any_type"] if dw.find(t) is not None]
            ok = ok and bool(got)
            why.append(f"any_type 命中 {got or '无'}")
        if "any_symbol" in d:
            got = [s for s in d["any_symbol"] if dw.var(s) is not None]
            ok = ok and bool(got)
            why.append(f"any_symbol 命中 {got or '无'}")
        if "all_symbol" in d:
            got = [s for s in d["all_symbol"] if dw.var(s) is not None]
            missing = [s for s in d["all_symbol"] if dw.var(s) is None]
            ok = ok and not missing
            why.append(f"all_symbol 命中 {got or '无'}，缺 {missing or '无'}")
        trace.append(f"{name}: {'匹配' if ok else '不匹配'}（{'；'.join(why) or '没写 detect'}）")
        if ok:
            hits.append(name)
    bases = {manifests[h].builds_on for h in hits if manifests[h].builds_on}
    shadowed = sorted(bases & set(hits))
    if shadowed:
        trace.append(f"{'、'.join(shadowed)} 是更具体那个的底座，让位")
        hits = [h for h in hits if h not in shadowed]

    if len(hits) == 1:
        return hits[0], trace
    if len(hits) > 1:
        trace.append(f"有歧义：{'、'.join(hits)} 都匹配，需要更具体的 detect")
    return None, trace


def _pick_sources(dw: DwarfSource,
                  ent: EntitySpec) -> tuple[list[SourceSpec], list[str]]:
    return _pick_from(dw, list(enumerate(ent.sources)), ent.source_combine)


def _pick_from(dw: DwarfSource,
               numbered: list[tuple[int, SourceSpec]],
               combine: str) -> tuple[list[SourceSpec], list[str]]:
    trace: list[str] = []
    hits: list[SourceSpec] = []
    for i, s in numbered:
        hit, why = eval_when(dw, s.when)
        trace.append(f"[{i}] {s.kind or '?'}/{s.completeness}: "
                     f"{'选中' if hit else '跳过'} —— {why}")
        if not hit:
            continue
        hits.append(s)
        if combine != "union":
            break
    if len(hits) > 1:
        trace.append(f"取并集：{len(hits)} 条都成立，逐条枚举后按地址去重"
                     f"（source_combine = union）")
    return hits, trace


def probe(m: Manifest, dw: DwarfSource) -> ProbeResult:
    arch = _ARCH.get(dw.e_machine)
    res = ProbeResult(kernel=m.name, arch=arch)

    if arch is None:
        res.warnings.append(f"不认识的 e_machine {dw.e_machine}")
    elif m.arches and arch not in m.arches:
        res.warnings.append(
            f"这个二进制是 {arch}，但 manifest 只声明支持 {'、'.join(m.arches)}")

    for ent in m.entities:
        r = ResolvedEntity(name=ent.name, type=ent.type)
        st = dw.find(ent.type)
        if st is None:
            clash = dw.conflicts.get(ent.type)
            # （kind = "batch"、completeness = "none"、
            guarded = [(i, s) for i, s in enumerate(ent.sources) if s.when]
            r.sources, r.source_trace = _pick_from(
                dw, guarded, ent.source_combine)
            if clash:
                r.reason = clash
            elif r.sources:
                kinds = "、".join(s.kind or "?" for s in r.sources)
                r.reason = (
                    f"调试信息里没有类型 {ent.type!r}，但有 source 声明了这个"
                    f"形态（{kinds}）。实体本身解不出来，完整性却是**有断言**的")
            else:
                r.reason = (f"调试信息里没有类型 {ent.type!r}。"
                            f"要么这个内核不长这样，要么 manifest 该更新了")
            res.entities.append(r)
            continue
        r.struct_path, r.size = st.path, st.size
        r.sources, r.source_trace = _pick_sources(dw, ent)
        if not r.sources and ent.sources:
            r.reason = "没有一条 source 的 when 成立"

        for fs in ent.fields + ent.relations:
            got = resolve_path(dw, st, fs.path)
            state = got.state
            if state == ABSENT and not fs.optional:
                state = UNDECODABLE
            reason = got.reason
            if state == ABSENT and fs.feature:
                reason = (f"这个字段只在 cfg feature {fs.feature!r} 打开时才存在，"
                          f"当前这个内核没开，所以编译器根本没生成它。"
                          + (f"（下潜细节：{reason}）" if reason else ""))
            r.fields.append(ResolvedField(
                name=fs.name, path=fs.path, reader=fs.reader, state=state,
                offset=got.offset, type_name=got.type_name,
                type_off=got.type_off,
                reason=reason, optional=fs.optional, role=fs.role,
                hops=got.hops, enum=fs.enum, links_to=fs.links_to,
                inverse=fs.inverse, feature=fs.feature))
        res.entities.append(r)
    return res


def report(res: ProbeResult) -> str:
    out = [f"内核 {res.kernel}  架构 {res.arch or '未知'}"]
    for w in res.warnings:
        out.append(f"  警告：{w}")
    for e in res.entities:
        c = e.counts()
        out.append(f"\n实体 {e.name}  类型 {e.struct_path or e.type}"
                   f"  大小 {e.size}")
        if e.reason:
            out.append(f"  !! {e.reason}")
        for t in e.source_trace:
            out.append(f"  source {t}")
        if e.source and e.source.reason:
            out.append(f"  说明：{e.source.reason}")
        out.append(f"  字段：有 {c[PRESENT]}，本来就没有 {c[ABSENT]}，"
                   f"解不出来 {c[UNDECODABLE]}")
        for f in e.fields:
            if f.state == PRESENT:
                via = ".".join(f.hops)
                extra = f"  [{f.role}]" if f.role else ""
                out.append(f"    +{f.offset:<6} {f.name:<10} {f.type_name}"
                           f"{'  经 ' + via if via != f.path else ''}{extra}")
            elif f.state == ABSENT:
                out.append(f"    （无）  {f.name:<10} 这个内核没有，正常")
            else:
                out.append(f"    !!      {f.name:<10} 解不出来：{f.reason}")
    return "\n".join(out)
