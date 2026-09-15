
from __future__ import annotations

from dataclasses import dataclass, field

from ..model.manifest import ColumnSpec, EntitySpec, Manifest
from ..model.probe import PRESENT, ProbeResult
from ..model.snapshot import Snapshot, is_live


@dataclass
class ResourceTable:

    name: str
    label: str
    available: bool
    reason: str
    columns: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    show_when_any: list[str] = field(default_factory=list)
    empty_text: str = ""
    notes: list[str] = field(default_factory=list)


def _col_public(c: ColumnSpec) -> dict:
    out = {"key": c.key, "label": c.label}
    if c.format:
        out["format"] = c.format
    if c.values:
        out["values"] = list(c.values)
    return out


def _enum_cell(c: ColumnSpec, v):
    if isinstance(v, int) and 0 <= v < len(c.values):
        return c.values[v]
    return f"?{v}"


def _cell(entity, c: ColumnSpec):
    f = entity.fields.get(c.key)
    return f.value if f is not None and f.ok else None


def _columns(spec: EntitySpec, res: ProbeResult) -> tuple[
        list[ColumnSpec], list[str], str]:
    by_name = {r.name: r for r in res.entities}
    r = by_name.get(spec.name)
    if r is None:
        return [], [], (f"probe 没有实体 {spec.name!r} 的结果，"
                        f"不知道它的字段解没解出来")
    states = {f.name: f for f in r.fields}

    cols: list[ColumnSpec] = []
    notes: list[str] = []
    for c in spec.table.columns:
        if c.synthetic:
            cols.append(c)
            continue
        f = states.get(c.key)
        if f is not None and f.state == PRESENT:
            cols.append(c)
            continue
        why = (f.reason if f is not None and f.reason
               else f"这个内核里没有 {spec.type}.{c.key}")
        if c.optional or (f is not None and f.optional):
            notes.append(f"{why}，少了「{c.label}」一列")
            continue
        return [], [], (f"「{c.label}」这一列读不了（{why}），"
                        f"整张表标记为不可解释")
    return cols, notes, ""


_MAX_REASONS = 3


def _why_none(problems: list) -> str:
    seen: list[str] = []
    for p in problems:
        r = getattr(p, "reason", None) or str(p)
        if r not in seen:
            seen.append(r)
    head = "；".join(seen[:_MAX_REASONS])
    rest = len(seen) - _MAX_REASONS
    return head + (f"（另有 {rest} 种其他原因）" if rest > 0 else "")


def table_of(spec: EntitySpec, res: ProbeResult, snap: Snapshot
             ) -> ResourceTable:
    label = spec.label or spec.name
    es = snap.sets.get(spec.name)
    if es is None:
        return ResourceTable(spec.name, label, False,
                             f"这一帧没有实体 {spec.name!r} 的快照")
    if es.unavailable is not None:
        return ResourceTable(spec.name, label, False, es.unavailable)

    if es.problems and not es.entities:
        return ResourceTable(spec.name, label, False, _why_none(es.problems))

    cols, notes, why = _columns(spec, res)
    if why:
        return ResourceTable(spec.name, label, False, why)

    if es.problems:
        notes = [*notes, f"另有 {len(es.problems)} 处没能走到："
                         f"{_why_none(es.problems)}"]

    rows: list[dict] = []
    for i, e in enumerate(es.entities):
        if not is_live(e, spec.liveness):
            continue
        row = {c.key: (i if c.synthetic else _cell(e, c)) for c in cols}
        for c in cols:
            if c.format == "enum":
                row[c.key] = _enum_cell(c, row[c.key])
        rows.append(row)

    return ResourceTable(
        spec.name, label, True, "",
        columns=[_col_public(c) for c in cols], rows=rows,
        show_when_any=list(spec.table.show_when_any),
        empty_text=spec.table.empty_text, notes=notes)


def from_entities(m: Manifest, res: ProbeResult, snap: Snapshot
                  ) -> list[ResourceTable]:
    """Render tables whose guarded source applies to this concrete ELF.

    Family manifests span structurally different kernels.  A guarded source
    whose predicate is false means "this table does not exist in this shape",
    not "the table exists but decoding failed".  Omit that table.  Once a
    source is selected, compilation/runtime failures still flow through
    ``table_of`` as unavailable and remain visible.
    """
    resolved = {r.name: r for r in res.entities}
    out: list[ResourceTable] = []
    for e in m.entities:
        if e.table is None:
            continue
        r = resolved.get(e.name)
        if e.sources and r is not None and not r.sources:
            continue
        out.append(table_of(e, res, snap))
    return out
