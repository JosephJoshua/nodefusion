
from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from . import kinds as _kinds
from .roles import check_role


class ManifestError(Exception):
    pass


@dataclass
class FieldSpec:

    name: str
    path: str
    reader: str
    optional: bool = False
    role: str | None = None
    links_to: str | None = None
    inverse: str | None = None
    enum: str | None = None
    verified: bool = True
    feature: str | None = None


@dataclass
class SourceSpec:

    kind: str
    completeness: str
    steps: list[dict] = field(default_factory=list)
    when: dict | None = None
    reason: str | None = None
    nested: list[dict] = field(default_factory=list)


@dataclass
class EntitySpec:
    name: str
    type: str
    label: str = ""
    role: str = ""
    sources: list[SourceSpec] = field(default_factory=list)
    source_combine: str = "first"
    fields: list[FieldSpec] = field(default_factory=list)
    relations: list[FieldSpec] = field(default_factory=list)
    liveness: dict | None = None
    table: TableSpec | None = None


@dataclass
class ColumnSpec:

    key: str
    label: str
    format: str = ""
    values: list[str] = field(default_factory=list)
    optional: bool = False
    synthetic: bool = False


@dataclass
class TableSpec:

    columns: list[ColumnSpec] = field(default_factory=list)
    show_when_any: list[str] = field(default_factory=list)
    empty_text: str = ""


@dataclass
class WatchSpec:

    subsystem: str
    match: dict
    args: int = 2
    throttle: int = 0
    skip: bool = False
    inlined: bool = False
    snapshot: str = "none"
    when: dict | None = None


@dataclass
class EventSpec:

    kind: str
    args: list[str] = field(default_factory=list)
    resource: str = ""
    operation: str = ""
    coverage_group: str = ""
    classify: dict | None = None
    when: dict | None = None
    alts: tuple["EventSpec", ...] = ()


@dataclass(frozen=True)
class AbsentSpec:

    kind: str
    why: str
    evidence: str
    when: dict | None = None


@dataclass(frozen=True)
class Device:
    file: str
    opts: tuple[str, ...] = ()
    built_when: tuple[str, str] | None = None


@dataclass
class ProfileSpec:
    kernel_elf: str
    kernel_image: str
    build: str
    detect_files: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    machine_opts: list[str] = field(default_factory=list)
    interactive: bool = False
    prompt: str = ""
    ready_markers: list[str] = field(default_factory=list)
    done_markers: list[str] = field(default_factory=list)
    panic_markers: list[str] = field(default_factory=lambda: ["panic"])
    exit_marker: str = ""
    halt_markers: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    build_deviation: str = ""
    devices: list["Device"] = field(default_factory=list)
    protect: list[str] = field(default_factory=list)
    shell_probe: dict = field(default_factory=dict)
    shell_prompt: str = ""
    shell_ready_marker: str = ""
    stdin_preload: bool = False
    stdin_pad: str = ""
    #: （2,000,000）。
    event_snapshot_min_insns: int = 0


@dataclass(frozen=True)
class SyscallSpec:
    files: list[str]
    pattern: str


@dataclass
class Manifest:
    name: str
    family: str = ""
    arches: list[str] = field(default_factory=list)
    detect: dict = field(default_factory=dict)
    #: Some kernel families evolve feature-by-feature across multiple source
    #: releases while deliberately sharing one manifest.  When enabled, a
    #: declared event kind is a feature-level N/A for a particular build only
    #: if none of that kind's implementation symbols exist in the resolved
    #: ELF/DWARF.  A symbol that exists but was not watched remains a gap.
    derive_feature_absence_from_symbols: bool = False
    cache_hit_derivation: str = "unverified"
    clone_completion_channel: str = "entry"
    builds_on: str = ""
    entities: list[EntitySpec] = field(default_factory=list)
    watches: list[WatchSpec] = field(default_factory=list)
    events: dict[str, EventSpec] = field(default_factory=dict)
    absent: dict[str, AbsentSpec] = field(default_factory=dict)
    profile: ProfileSpec | None = None
    syscalls: SyscallSpec | None = None
    path: Path | None = None

    def entity(self, name: str) -> EntitySpec | None:
        return next((e for e in self.entities if e.name == name), None)

    def entity_for(self, role: str, *, fallback: str = "") -> EntitySpec | None:
        hit = next((e for e in self.entities if e.role == role), None)
        return hit if hit is not None else (
            self.entity(fallback) if fallback else None)



_FIELD_KEYS = frozenset({
    "path", "reader", "role", "links_to", "inverse", "enum", "verified",
    "feature"})


def _fields(d: dict, *, optional: bool, where: str = "字段",
            p: Path | None = None) -> list[FieldSpec]:
    out: list[FieldSpec] = []
    for name, spec in (d or {}).items():
        if not isinstance(spec, dict):
            raise ManifestError(f"字段 {name!r} 应该是个表，实际是 {type(spec).__name__}")
        if "path" not in spec:
            raise ManifestError(f"字段 {name!r} 缺 path")
        _reject_unknown(spec, _FIELD_KEYS, f"{where} {name!r}",
                        p if p is not None else Path("(manifest)"))
        try:
            check_role(spec.get("role"), f"字段 {name!r}")
        except ValueError as e:
            raise ManifestError(str(e)) from None
        if spec.get("inverse") and not spec.get("links_to"):
            raise ManifestError(
                f"{where} {name!r} 写了 inverse={spec['inverse']!r} 却没有 "
                "links_to：反向边得知道挂到哪个实体上")
        out.append(FieldSpec(
            name=name, path=spec["path"], reader=spec.get("reader", ""),
            optional=optional, role=spec.get("role"),
            links_to=spec.get("links_to"), inverse=spec.get("inverse"),
            enum=spec.get("enum"),
            verified=bool(spec.get("verified", True)),
            feature=spec.get("feature")))
    return out


_SOURCE_KEYS = frozenset({
    "kind", "completeness", "steps", "when", "reason", "nested"})

_COMPLETENESS: dict[str, bool | None] = {
    "total": True,
    "partial": False,
    "reachable_only": False,
    "ready_only": False,
    "none": False,
    "unknown": None,
}


def _sources(raw: list, ename: str, p: Path) -> list[SourceSpec]:
    out: list[SourceSpec] = []
    for i, s in enumerate(raw or []):
        _reject_unknown(s, _SOURCE_KEYS, f"实体 {ename!r} 的第 {i} 条 source", p)
        if "steps" not in s and s.get("kind") != "batch":
            raise ManifestError(f"实体 {ename} 的第 {i} 条 source 缺 steps")
        c = s.get("completeness", "unknown")
        if c not in _COMPLETENESS:
            raise ManifestError(
                f"{p} 的实体 {ename!r} 第 {i} 条 source 的 "
                f"completeness={c!r} 不认识，只能是 "
                f"{'/'.join(sorted(_COMPLETENESS))}。")
        out.append(SourceSpec(
            kind=s.get("kind", ""),
            completeness=c,
            steps=list(s.get("steps", [])),
            when=s.get("when"), reason=s.get("reason"),
            nested=list(s.get("nested", []))))
    return out


_ENTITY_KEYS = frozenset({
    "name", "type", "label", "role", "source", "source_combine", "fields",
    "optional_fields", "relations", "optional_relations", "liveness",
    "address_space", "table"})
_SOURCE_COMBINE = frozenset({"first", "union"})
_TABLE_KEYS = frozenset({"column", "show_when_any", "empty"})
_WATCH_KEYS = frozenset({"subsystem", "match", "args", "throttle",
                         "snapshot", "skip", "inlined", "when"})
_SNAPSHOT_KINDS = frozenset({"none", "always", "event"})
_WATCH_MATCH_KEYS = frozenset({"module", "module_prefix", "file", "fn"})
_ENTITY_COLUMN_KEYS = frozenset({
    "key", "label", "format", "values", "optional", "synthetic"})
_KERNEL_KEYS = frozenset({
    "name", "family", "arches", "detect", "builds_on",
    "derive_feature_absence_from_symbols", "cache_hit_derivation",
    "clone_completion_channel"})
_DETECT_KEYS = frozenset({"any_type", "any_symbol", "all_symbol"})


def _reject_unknown(d: dict, known: frozenset, where: str, p: Path) -> None:
    unknown = sorted(set(d) - known)
    if not unknown:
        return
    bits = []
    for k in unknown:
        near = difflib.get_close_matches(k, sorted(known), n=1, cutoff=0.7)
        bits.append(f"{k!r}" + (f"（是不是想写 {near[0]!r}？）" if near else ""))
    raise ManifestError(
        f"{p} 的 {where} 里有不认识的键：{'，'.join(bits)}。"
        f"认识的键有：{'、'.join(sorted(known))}。"
        f"这里不忽略不认识的键 —— 忽略的话这条声明会静悄悄地不生效。")


def _table(raw: dict, ename: str, known_fields: set[str], p: Path) -> TableSpec:
    _reject_unknown(raw, _TABLE_KEYS, f"实体 {ename!r} 的 [entity.table]", p)
    cols: list[ColumnSpec] = []
    for c in raw.get("column", []):
        key = c.get("key")
        _reject_unknown(
            c, _ENTITY_COLUMN_KEYS,
            f"实体 {ename!r} 的 [[entity.table.column]]（key={key!r}）", p)
        if not key:
            raise ManifestError(
                f"{p} 的实体 {ename!r} 里有一列没有 key")
        synthetic = bool(c.get("synthetic", False))
        if not synthetic and key not in known_fields:
            near = difflib.get_close_matches(key, sorted(known_fields), n=1,
                                             cutoff=0.6)
            raise ManifestError(
                f"{p} 的实体 {ename!r} 有一列 key={key!r}，但 "
                f"[entity.fields] 里没有这个字段"
                + (f"（是不是想写 {near[0]!r}？）" if near else "")
                + "。列只管显示，值得从某个已声明的字段来 —— "
                  "对不上的话这一列会整列空着，看起来像这个内核没有这个字段。")
        cols.append(ColumnSpec(
            key=key, label=c.get("label", key), format=c.get("format", ""),
            values=list(c.get("values", [])),
            optional=bool(c.get("optional", False)), synthetic=synthetic))
    if not cols:
        raise ManifestError(
            f"{p} 的实体 {ename!r} 写了 [entity.table] 却一列都没有")
    return TableSpec(columns=cols,
                     show_when_any=list(raw.get("show_when_any", [])),
                     empty_text=raw.get("empty", ""))


def load(path: str | Path) -> Manifest:
    p = Path(path)
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(
            f"{p} 不是合法 TOML：{e}。"
            f"注意 TOML 的行内表 {{ ... }} 不能跨行。") from e

    k = raw.get("kernel")
    if not k or "name" not in k:
        raise ManifestError(f"{p} 缺 [kernel] 或它的 name")
    _reject_unknown(k, _KERNEL_KEYS, "[kernel]", p)
    cache_hit_derivation = k.get("cache_hit_derivation", "unverified")
    if cache_hit_derivation not in {"unverified", "one_to_one", "semantic"}:
        raise ManifestError(
            f"{p} 的 [kernel].cache_hit_derivation 应为 "
            "'unverified'、'one_to_one' 或 'semantic'")
    clone_completion_channel = k.get("clone_completion_channel", "entry")
    if clone_completion_channel not in {"entry", "nftrace"}:
        raise ManifestError(
            f"{p} 的 [kernel].clone_completion_channel 应为 "
            "'entry' 或 'nftrace'")
    detect = k.get("detect", {})
    if not isinstance(detect, dict):
        raise ManifestError(
            f"{p} 的 [kernel].detect 应该是个表，实际是 "
            f"{type(detect).__name__}。")
    _reject_unknown(detect, _DETECT_KEYS, "[kernel].detect", p)
    for key, values in detect.items():
        if not isinstance(values, list) or not values or not all(
                isinstance(value, str) and value for value in values):
            raise ManifestError(
                f"{p} 的 [kernel].detect.{key} 应该是一串非空名字。")

    entities: list[EntitySpec] = []
    for e in raw.get("entity", []):
        if "name" not in e or "type" not in e:
            raise ManifestError(f"{p} 里有 [[entity]] 缺 name 或 type")
        _reject_unknown(e, _ENTITY_KEYS,
                        f"[[entity]]（name={e['name']!r}）", p)
        combine = str(e.get("source_combine", "first"))
        if combine not in _SOURCE_COMBINE:
            raise ManifestError(
                f"{p} 的 [[entity]]（name={e['name']!r}）的 "
                f"source_combine={combine!r} 不认识，只能是 "
                f"{'/'.join(sorted(_SOURCE_COMBINE))}。")
        entities.append(EntitySpec(
            name=e["name"], type=e["type"], label=e.get("label", ""),
            role=e.get("role", ""), source_combine=combine,
            sources=_sources(e.get("source", []), e["name"], p),
            fields=_fields(e.get("fields"), optional=False,
                           where=f"[entity.fields]（name={e['name']!r}）的字段",
                           p=p),
            relations=_fields(e.get("relations"), optional=False,
                              where=f"[entity.relations]（name={e['name']!r}）的字段",
                              p=p),
            liveness=e.get("liveness")))
        entities[-1].fields.extend(
            _fields(e.get("optional_fields"), optional=True,
                    where=f"[entity.optional_fields]（name={e['name']!r}）的字段",
                    p=p))
        entities[-1].relations.extend(
            _fields(e.get("optional_relations"), optional=True,
                    where=(f"[entity.optional_relations]"
                           f"（name={e['name']!r}）的字段"), p=p))
        if "table" in e:
            entities[-1].table = _table(
                e["table"], e["name"],
                {f.name for f in entities[-1].fields}
                | {f.name for f in entities[-1].relations}, p)

    watches = []
    for i, w in enumerate(raw.get("watch", [])):
        _reject_unknown(w, _WATCH_KEYS, f"第 {i} 条 [[watch]]", p)
        m = w.get("match", {})
        _reject_unknown(m, _WATCH_MATCH_KEYS, f"第 {i} 条 [[watch]] 的 match", p)
        if not m:
            raise ManifestError(
                f"{p} 的第 {i} 条 [[watch]]（subsystem={w.get('subsystem')!r}）"
                f"没有 match，选不出任何函数。要选的话至少写一个 "
                f"{'/'.join(sorted(_WATCH_MATCH_KEYS))}。")
        snap = str(w.get("snapshot", "none"))
        if snap not in _SNAPSHOT_KINDS:
            raise ManifestError(
                f"{p} 的第 {i} 条 [[watch]] 的 snapshot={snap!r} 不认识，"
                f"只能是 {'/'.join(sorted(_SNAPSHOT_KINDS))}。")
        skip = bool(w.get("skip", False))
        when = w.get("when")
        if when is not None and (not isinstance(when, dict)
                                 or len(when) != 1
                                 or next(iter(when)) not in {"type_exists", "type_missing"}
                                 or not isinstance(next(iter(when.values())), str)
                                 or not next(iter(when.values())).strip()):
            raise ManifestError(
                f"{p} 的第 {i} 条 [[watch]] 的 when 需要非空的 "
                "type_exists 或 type_missing 类型名。")
        if skip and snap != "none":
            raise ManifestError(
                f"{p} 的第 {i} 条 [[watch]] 同时写了 skip 和 "
                f"snapshot={snap!r}，这两个要求互相矛盾。")
        watches.append(WatchSpec(
            subsystem=w.get("subsystem", ""), match=m,
            args=int(w.get("args", 2)), throttle=int(w.get("throttle", 0)),
            snapshot=snap, skip=skip, inlined=bool(w.get("inlined", False)),
            when=when))

    events: dict[str, EventSpec] = {}
    for fn, spec in (raw.get("event") or {}).items():
        if isinstance(spec, str):
            _kinds.check(spec, f"{p} 的 [event] 里的 {fn!r}")
            events[fn] = EventSpec(kind=spec)
            continue
        if isinstance(spec, list):
            if not spec:
                raise ManifestError(
                    f"{p} 的 [event] 里 {fn!r} 是个空表。要么写一条事件类型，"
                    f"要么整条删掉 —— 空表跟没写这条的区别看不出来。")
            branches = [_event_one(s, fn, p, i) for i, s in enumerate(spec)]
            if branches[-1].when is not None:
                raise ManifestError(
                    f"{p} 的 [event] 里 {fn!r} 的最后一条候选带着 when。"
                    f"最后一条得是无条件的兜底 —— 全都带条件的话，条件都不成立"
                    f"时这个符号会退回 func.<名字>，跟没写过一样，看不出来。")
            for b in branches[:-1]:
                if b.when is None:
                    raise ManifestError(
                        f"{p} 的 [event] 里 {fn!r} 有一条不在末尾的候选没写 "
                        f"when。它会无条件胜出，后面几条永远轮不上。")
            events[fn] = replace(branches[0], alts=tuple(branches[1:]))
            continue
        if not isinstance(spec, dict):
            raise ManifestError(
                f"{p} 的 [event] 里 {fn!r} 应该是个字符串（事件类型）、一个表"
                f"（{{ kind = \"...\", args = [...] }}），或者一串候选表，实际是 "
                f"{type(spec).__name__}。")
        events[fn] = _event_one(spec, fn, p, None)

    absent = _absent(raw.get("absent"), events, p)

    return Manifest(
        name=k["name"], family=k.get("family", ""),
        arches=list(k.get("arches", [])), detect=detect,
        derive_feature_absence_from_symbols=bool(
            k.get("derive_feature_absence_from_symbols", False)),
        cache_hit_derivation=cache_hit_derivation,
        clone_completion_channel=clone_completion_channel,
        builds_on=k.get("builds_on", ""),
        entities=entities, watches=watches, events=events, absent=absent,
        profile=_profile(raw.get("profile"), p),
        syscalls=_syscalls(raw.get("syscalls"), p), path=p)


def _syscalls(raw, p: Path) -> SyscallSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{p} 的 [syscalls] 应该是个表，实际是 {type(raw).__name__}。")
    _reject_unknown(raw, frozenset({"files", "pattern"}), "[syscalls]", p)
    files, pat = raw.get("files"), raw.get("pattern")
    if not isinstance(files, list) or not files or not all(
            isinstance(f, str) and f for f in files):
        raise ManifestError(
            f"{p} 的 [syscalls].files 应该是一串非空 glob（相对 kernel_dir）。")
    if not isinstance(pat, str) or not pat:
        raise ManifestError(f"{p} 的 [syscalls].pattern 应该是个非空正则。")
    try:
        rx = re.compile(pat)
    except re.error as e:
        raise ManifestError(f"{p} 的 [syscalls].pattern 编不过：{e}") from e
    missing = {"num", "name"} - set(rx.groupindex)
    if missing:
        raise ManifestError(
            f"{p} 的 [syscalls].pattern 缺具名组 "
            f"{'、'.join(f'(?P<{g}>…)' for g in sorted(missing))}。"
            f"号和名要各自说清楚 —— 按位置取组，号在前还是名在前就成了"
            f"代码里的假设，而两种写法都真实存在。")
    return SyscallSpec(files=list(files), pattern=pat)


_ABSENT_WHY = frozenset({"feature", "granularity"})
_ABSENT_KEYS = frozenset({"why", "evidence", "when"})
_ABSENT_MIN_EVIDENCE = 24


def _event_one(spec, fn: str, p: Path, idx: int | None) -> EventSpec:
    where = (f"[event] 里的 {fn!r}" if idx is None
             else f"[event] 里 {fn!r} 的第 {idx + 1} 条候选")
    if not isinstance(spec, dict):
        raise ManifestError(
            f"{p} 的 {where} 应该是个表（{{ kind = \"...\" }}），实际是 "
            f"{type(spec).__name__}。")
    _reject_unknown(spec, {"kind", "args", "resource", "operation", "when",
                           "classify", "coverage_group"},
                    where, p)
    if not spec.get("kind"):
        raise ManifestError(f"{p} 的 {where} 缺 kind。")
    _kinds.check(str(spec["kind"]), f"{p} 的 {where}")
    when = spec.get("when")
    if when is not None and not isinstance(when, dict):
        raise ManifestError(
            f"{p} 的 {where} 的 when 应该是个表（比如 "
            f"{{ type_exists = \"...\" }}），实际是 {type(when).__name__}。")
    operation = str(spec.get("operation", ""))
    if operation not in ("", "read", "write"):
        raise ManifestError(
            f"{p} 的 {where} 的 operation={operation!r} 不认识，只能是 "
            "read/write。")
    if operation and str(spec["kind"]) != "disk.io":
        raise ManifestError(
            f"{p} 的 {where} 给 {spec['kind']!r} 写了 operation={operation!r}。"
            "operation 目前只定义了 disk.io 的读写方向，不能借给别的类别。")
    args = list(spec.get("args", []))
    coverage_group = str(spec.get("coverage_group", ""))
    if "coverage_group" in spec and not coverage_group.strip():
        raise ManifestError(f"{p} 的 {where} 的 coverage_group 不能为空。")
    classify = spec.get("classify")
    if classify is not None:
        if not isinstance(classify, dict):
            raise ManifestError(
                f"{p} 的 {where} 的 classify 应该是个表（比如 "
                f"{{ arg = \"flags\", mask = 65536, set = \"thread.create\" }}）。")
        _reject_unknown(classify, {"arg", "mask", "set"},
                        f"{where} 的 classify", p)
        arg = classify.get("arg")
        mask = classify.get("mask")
        set_kind = classify.get("set")
        if not isinstance(arg, str) or not arg:
            raise ManifestError(f"{p} 的 {where} 的 classify.arg 必须是非空参数名。")
        if arg not in args:
            raise ManifestError(
                f"{p} 的 {where} 用 classify.arg={arg!r} 分流，但显式 args 里没有它。"
                "位测试必须钉住 ABI 寄存器位置，不能从 DWARF 形参顺序猜。")
        if args.index(arg) >= 8:
            raise ManifestError(
                f"{p} 的 {where} 的 classify.arg={arg!r} 落在第 {args.index(arg)} 个"
                "参数寄存器之外；WATCHPC 只记录 a0..a7。")
        if isinstance(mask, bool) or not isinstance(mask, int) or mask <= 0:
            raise ManifestError(f"{p} 的 {where} 的 classify.mask 必须是正整数。")
        if not isinstance(set_kind, str) or not set_kind:
            raise ManifestError(f"{p} 的 {where} 的 classify.set 必须是事件类别。")
        _kinds.check(set_kind, f"{p} 的 {where} 的 classify.set")
        if set_kind == str(spec["kind"]):
            raise ManifestError(
                f"{p} 的 {where} 的 classify.set 跟默认 kind 都是 {set_kind!r}，"
                "这条分流没有作用。")
        classify = {"arg": arg, "mask": mask, "set": set_kind}
    return EventSpec(kind=str(spec["kind"]),
                     args=args,
                     resource=str(spec.get("resource", "")),
                     operation=operation,
                     coverage_group=coverage_group,
                     classify=classify,
                     when=when)


def _absent(raw, events: dict[str, EventSpec], p: Path) -> dict[str, AbsentSpec]:
    out: dict[str, AbsentSpec] = {}
    if not raw:
        return out
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{p} 的 [absent] 应该是个表（类别 -> {{ why, evidence }}），"
            f"实际是 {type(raw).__name__}。")

    mapped: dict[str, list[str]] = {}
    for fn, spec in events.items():
        for one in (spec, *spec.alts):
            mapped.setdefault(one.kind, []).append(fn)

    for kind, spec in raw.items():
        where = f"{p} 的 [absent] 里的 {kind!r}"
        _kinds.check(str(kind), where)
        if not isinstance(spec, dict):
            raise ManifestError(
                f"{where} 应该是个表（{{ why = \"...\", evidence = \"...\" }}），"
                f"实际是 {type(spec).__name__}。")
        _reject_unknown(spec, _ABSENT_KEYS, f"[absent] 里的 {kind!r}", p)

        why = str(spec.get("why", ""))
        if why not in _ABSENT_WHY:
            raise ManifestError(
                f"{where} 的 why={why!r} 不认识，只能是 "
                f"{'/'.join(sorted(_ABSENT_WHY))}。"
                f"feature = 内核压根没这件事；"
                f"granularity = 内核做这件事，但没有粒度对得上的符号可挂。")

        evidence = str(spec.get("evidence", "")).strip()
        if len(evidence) < _ABSENT_MIN_EVIDENCE:
            raise ManifestError(
                f"{where} 的 evidence 只有 {len(evidence)} 个字符，"
                f"至少要 {_ABSENT_MIN_EVIDENCE}。这一栏是给读的人复核用的，"
                f"要能指到源码位置或者量出来的数；写不出来就别声明这一条 —— "
                f"「没映射」本来就是个诚实的说法，「查过了，没有」不是。")

        when = spec.get("when")
        if when is not None and (not isinstance(when, dict) or
                                 set(when) != {"type_missing"} or
                                 not isinstance(when["type_missing"], str) or
                                 not when["type_missing"].strip()):
            raise ManifestError(
                f"{where} 的 when 只能是非空的 {{ type_missing = \"...\" }}。")
        if kind in mapped and when is None:
            raise ManifestError(
                f"{where}：这个类别同时出现在 [event] 里，映射它的是 "
                f"{'、'.join(sorted(mapped[kind]))}。"
                f"一边说这些函数产生这类事件、一边说本内核没有这类事件，"
                f"两句话互相取消，不猜哪句是真的。"
                f"补映射的时候多半是忘了删掉当初写的 [absent]。")

        out[str(kind)] = AbsentSpec(kind=str(kind), why=why, evidence=evidence,
                                   when=when)
    return out


_PROFILE_KEYS = {f.name for f in fields(ProfileSpec)} - {"devices"} | {"device"}
_PROFILE_REQUIRED = ("kernel_elf", "kernel_image", "build")


def _profile(raw, p: Path) -> ProfileSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{p} 的 [profile] 应该是个表，实际是 {type(raw).__name__}。")
    _reject_unknown(raw, _PROFILE_KEYS, "[profile]", p)
    missing = [k for k in _PROFILE_REQUIRED if not raw.get(k)]
    if missing:
        raise ManifestError(
            f"{p} 的 [profile] 缺 {'、'.join(missing)}。"
            f"要么补齐，要么整节删掉（不写 [profile] 表示这个内核还录不了，"
            f"是明确的空缺；写一半则会在录到一半时才炸）。")
    probe = raw.get("shell_probe") or {}
    if probe and set(probe) != {"dir", "ident"}:
        raise ManifestError(
            f"{p} 的 [profile.shell_probe] 只认 dir 和 ident，"
            f"实际是 {sorted(probe)}。")
    kw = {k: v for k, v in raw.items() if k not in ("shell_probe", "device")}
    return ProfileSpec(shell_probe=dict(probe),
                       devices=_devices(raw.get("device"), p), **kw)


def _devices(raw, p: Path) -> list[Device]:
    out = []
    for i, d in enumerate(raw or []):
        if not isinstance(d, dict):
            raise ManifestError(
                f"{p} 的第 {i + 1} 条 [[profile.device]] 应该是个表，"
                f"实际是 {type(d).__name__}。")
        _reject_unknown(d, {"file", "opts", "built_when"},
                        "[[profile.device]]", p)
        if not d.get("file"):
            raise ManifestError(
                f"{p} 的第 {i + 1} 条 [[profile.device]] 没写 file。"
                f"没有 file 就没法判断在不在，只能无条件挂 —— "
                f"那种设备写进 machine_opts。")
        bw = d.get("built_when")
        if bw is not None:
            if not isinstance(bw, dict):
                raise ManifestError(
                    f"{p} 的第 {i + 1} 条 [[profile.device]] 的 built_when 应该是"
                    f"个表，实际是 {type(bw).__name__}。")
            _reject_unknown(bw, {"file", "contains"},
                            "[[profile.device]].built_when", p)
            if not bw.get("file") or not bw.get("contains"):
                raise ManifestError(
                    f"{p} 的第 {i + 1} 条 [[profile.device]] 的 built_when 要同时"
                    f"写 file 和 contains，现在是 {bw!r}。")
            bw = (bw["file"], bw["contains"])
        out.append(Device(file=d["file"], opts=tuple(_as_list(d.get("opts"))),
                          built_when=bw))
    return out


def _as_list(v) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def _covers(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer + "::")


def lint(m: Manifest) -> list[str]:
    out: list[str] = []

    pure: list[tuple[int, str, list[str]]] = []
    for i, w in enumerate(m.watches):
        mods = _as_list(w.match.get("module"))
        if not mods:
            continue
        for j, sub, outer in pure:
            if all(any(_covers(o, x) for o in outer) for x in mods):
                out.append(
                    f"[{m.name}] 第 {i + 1} 条 watch（subsystem={w.subsystem!r}）"
                    f"永远轮不到：它的模块被第 {j + 1} 条"
                    f"（subsystem={sub!r}，module={outer}）整个罩住了，而选点是"
                    f"先到先得。窄的那条要排在前面。")
                break
        if not any(k in w.match for k in ("fn", "file")):
            pure.append((i, w.subsystem, mods))

    named = [t for t in ([e.type for e in m.entities]
                         + list(m.detect.get("any_type", []))) if t]
    qualified = [t for t in named if "::" in t]
    for t in named:
        if "::" in t:
            continue
        full = next((q for q in qualified if q.rsplit("::", 1)[-1] == t), None)
        if full:
            out.append(
                f"[{m.name}] 类型 {t!r} 写的是短名，同一份文件里另一处写的是"
                f"全名 {full!r}。短名靠后缀兜底匹配，撞名会被拒，泛型直接查不到。")

    kinds = {e.name for e in m.entities}
    for e in m.entities:
        for f in list(e.fields) + list(e.relations):
            if f.links_to and f.links_to not in kinds:
                out.append(
                    f"[{m.name}] 实体 {e.name!r} 的 {f.name!r} 写着 "
                    f"links_to={f.links_to!r}，可这份文件里没有叫这个名字的"
                    f"实体（有的是 {sorted(kinds)}）。")
    return out


def builtin_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "manifests"


def load_dir(d: str | Path | None = None) -> dict[str, Manifest]:
    out: dict[str, Manifest] = {}
    for f in sorted(Path(builtin_dir() if d is None else d).glob("*.toml")):
        m = load(f)
        if m.name in out:
            raise ManifestError(
                f"内核名 {m.name!r} 重复：{out[m.name].path} 和 {f}")
        out[m.name] = m
    return out
