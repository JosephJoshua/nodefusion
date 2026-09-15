
from __future__ import annotations

import base64
import json
import zlib
from collections import Counter
from pathlib import Path

from . import guest as guest_mod
from .analyze import Analysis

MAX_EVENTS = 150_000

MIN_SPARE_EVENTS = 25_000

DIAGNOSTIC_PREFIXES = ("func.",)


def _is_semantic(kind: str) -> bool:
    """Whether ``kind`` is part of the normalized event vocabulary.

    ``func.*`` deliberately means "a watchpoint fired but nobody has assigned
    portable semantics to it yet".  It is useful diagnostic evidence and must
    remain sampled, but it is the only event family that may be omitted from an
    interactive bundle.  A hand-maintained allowlist cannot stay complete as
    manifests add normalized namespaces.
    """
    return not any(kind.startswith(prefix) for prefix in DIAGNOSTIC_PREFIXES)


def _rle(kinds: bytearray, pids: list) -> list:
    out = []
    if not kinds:
        return out
    ck, cp, n = kinds[0], pids[0], 1
    for i in range(1, len(kinds)):
        k, p = kinds[i], pids[i]
        if k == ck and p == cp:
            n += 1
        else:
            out.append([ck, cp, n])
            ck, cp, n = k, p, 1
    out.append([ck, cp, n])
    return out


class Interner:

    def __init__(self):
        self.items: list[str] = []
        self.index: dict[str, int] = {}

    def __call__(self, s: str | None) -> int:
        if s is None:
            s = ""
        i = self.index.get(s)
        if i is None:
            i = len(self.items)
            self.items.append(s)
            self.index[s] = i
        return i


def _event_selection(events: list, *, materialize: bool) -> tuple[list, dict]:
    """Apply interactive sampling with bounded auxiliary memory.

    Multi-million-event runs used to allocate an additional tuple for every
    raw event before selecting the small diagnostic sample.  Two linear passes
    preserve exactly the same systematic sample while storing only retained
    events.  Coverage audits can avoid materializing even those.
    """
    raw_kinds = Counter(e.kind for e in events)
    priority_raw = sum(_is_semantic(e.kind) for e in events)
    if len(events) <= MAX_EVENTS:
        return (events if materialize else []), {
            "applied": False,
            "policy": "semantic-full/func-systematic-v2",
            "raw": len(events), "retained": len(events), "dropped": 0,
            "target_limit": MAX_EVENTS, "minimum_spare": MIN_SPARE_EVENTS,
            "always_keep": "all normalized events (everything except func.*)",
            "priority_raw": priority_raw,
            "spare_raw": len(events) - priority_raw,
            "spare_budget": 0, "stride": 1,
            "retained_kinds": dict(sorted(raw_kinds.items())),
            "dropped_kinds": {},
        }

    room = max(MAX_EVENTS - priority_raw, MIN_SPARE_EVENTS)
    spare_raw = len(events) - priority_raw
    step = max(1, spare_raw // room) if room > 0 and spare_raw else 1
    chosen: list = []
    retained_kinds: Counter = Counter()
    dropped_kinds: dict[str, int] = {}
    spare_seen = 0
    spare_kept = 0
    for e in events:
        retain = _is_semantic(e.kind)
        if not retain:
            retain = room > 0 and spare_kept < room and spare_seen % step == 0
            spare_seen += 1
            if retain:
                spare_kept += 1
        if retain:
            retained_kinds[e.kind] += 1
            if materialize:
                chosen.append(e)
        else:
            dropped_kinds[e.kind] = dropped_kinds.get(e.kind, 0) + 1

    retained = sum(retained_kinds.values())
    dropped = len(events) - retained

    return chosen, {
        "applied": True,
        "policy": "semantic-full/func-systematic-v2",
        "raw": len(events), "retained": retained, "dropped": dropped,
        "target_limit": MAX_EVENTS, "minimum_spare": MIN_SPARE_EVENTS,
        "always_keep": "all normalized events (everything except func.*)",
        "priority_raw": priority_raw, "spare_raw": spare_raw,
        "spare_budget": room, "stride": step if room > 0 and spare_raw else None,
        "retained_kinds": dict(sorted(retained_kinds.items())),
        "dropped_kinds": dict(sorted(dropped_kinds.items())),
    }


def _select_events(events: list) -> tuple[list, dict]:
    return _event_selection(events, materialize=True)


def _observed_fields(states: list[dict], events: list) -> dict:
    """Inventory fields that are actually present in this concrete report.

    This is evidence metadata, not a kernel schema.  It is derived from the
    decoded rows and event payloads so videos can identify what they display
    without maintaining another per-kernel field list in the exporter.
    """
    process: set[str] = set()
    resources: set[str] = set()
    event: dict[str, set[str]] = {}

    for state in states:
        for proc in state.get("procs", []):
            for name, field in (proc.get("fields") or {}).items():
                if isinstance(field, dict) and field.get("state") == "present":
                    process.add(name)
        for resource in state.get("resources", []):
            name = resource.get("name") or "resource"
            for column in resource.get("columns", []):
                key = column.get("key")
                if key:
                    resources.add(f"{name}.{key}")

    for item in events:
        prefix = item.kind.split(".", 1)[0]
        detail = item.detail if isinstance(item.detail, dict) else {}
        event.setdefault(prefix, set()).update(detail.keys())

    return {
        "process": sorted(process),
        "resources": sorted(resources),
        "events": {k: sorted(v) for k, v in sorted(event.items())},
    }


def _coverage(a: Analysis, metrics: dict, states: list[dict], selection: dict) -> dict:
    """Strict, machine-readable applicable-coverage audit for one bundle.

    This intentionally asks more than the old "N scalar metrics have values"
    sentence.  A run is complete only when applicable metrics are exact, every
    normalized event carries all fields its decoder promised, post-start
    snapshots decode, manifest fields decode, and the interactive export loses
    no normalized event.  A manifest declaration with ``why = feature`` is N/A;
    a granularity declaration remains a gap.
    """
    absent = metrics.get("absent_declared") or {}
    feature_absent = {kind for kind, spec in absent.items()
                      if spec.get("why") == "feature"}
    scalar = [k for k, v in metrics.items()
              if k not in {"by_kind", "unobservable_reason", "absent_declared",
                           "armed_silent", "sampling"}
              and isinstance(v, (int, float, type(None)))
              and not isinstance(v, bool)]

    metric_kind = dict(Analysis._METRIC_KINDS)
    not_applicable = {
        name for name, kind in metric_kind.items() if kind in feature_absent
    }
    for name, deps in Analysis._DERIVED_FROM.items():
        if any(dep in feature_absent for dep in deps):
            not_applicable.add(name)
    # Some historical kernels genuinely have no process table, allocator, or
    # resource cache yet.  Their snapshots still carry complete physical pages,
    # but the corresponding semantic channel is not applicable.  Derive these
    # three snapshot-channel exemptions from the same manifest-backed feature
    # absence used for scalar metrics, instead of turning an intentionally empty
    # chapter into a strict-coverage failure.
    snapshot_na = set()
    if {"proc.initproc", "proc.alloc"} <= feature_absent:
        snapshot_na.add("processes")
    if {"bcache.init", "inode.alloc"} <= feature_absent:
        snapshot_na.add("resources")
    if {"phys.alloc", "phys.free"} <= feature_absent:
        snapshot_na.add("physical_counters")
    applicable = [name for name in scalar if name not in not_applicable]
    missing_metrics = [name for name in applicable if metrics.get(name) is None]
    sampled_metrics = sorted(
        name for name in applicable
        if (metrics.get("sampling") or {}).get("metrics", {}).get(name))

    semantic_events = [e for e in a.events if _is_semantic(e.kind)]
    unknown_events = [e for e in semantic_events if e.unknown]
    unknown_fields = Counter(
        field for e in unknown_events for field in (e.unknown or []))

    start = int(a.manifest.get("program_start_insn") or 0)
    relevant_states = [s for s in states if int(s.get("insn") or 0) >= start]
    if not relevant_states:
        relevant_states = states
    # Allocator counters are only defined after the kernel's allocator
    # initialization commit.  Early boot snapshots are still valid physical
    # memory images, but asking them for a free/used total would manufacture a
    # failure before the producer existed.  Start that channel's denominator
    # at the first authoritative allocator record.
    allocator_start = min(
        (int(r[0]) for r in getattr(a, "nft_allocator_states", [])),
        default=0)
    bad_phys_counters = sum(
        not s.get("phys_free_ok", False) for s in relevant_states
        if int(s.get("insn") or 0) >= allocator_start)
    bad_snapshots = {
        "incomplete": sum(not s.get("complete", False) for s in relevant_states),
        "physical_memory": sum(not s.get("phys_ok", False) for s in relevant_states),
        "physical_counters": 0 if "physical_counters" in snapshot_na else bad_phys_counters,
        "processes": 0 if "processes" in snapshot_na else sum(
            not s.get("procs_ok", False) for s in relevant_states),
        "resources": sum(
            1 for s in relevant_states for table in s.get("resources", [])
            if not table.get("ok", False)),
    }
    if "resources" in snapshot_na:
        bad_snapshots["resources"] = 0
    field_states = Counter()
    for state in relevant_states:
        for proc in state.get("procs", []):
            for field in (proc.get("fields") or {}).values():
                if isinstance(field, dict):
                    field_states[str(field.get("state") or "unknown")] += 1
    # `absent` is a manifest-backed fact about this kernel/chapter, not a
    # decoder failure.  It is the field-level equivalent of an N/A metric.
    bad_field_cells = sum(
        count for state, count in field_states.items()
        if state not in {"present", "empty", "absent"})

    dropped_semantic = sum(
        count for kind, count in (selection.get("dropped_kinds") or {}).items()
        if _is_semantic(kind))
    watch_source = str(a.manifest.get("watch_source") or "")
    full_watch_scope = bool(watch_source) and "[" not in watch_source
    trace_ok = not a.trace.truncated_at_eof
    plugin_ok = not (a.trace.end and a.trace.end.truncated)

    blockers = []
    if missing_metrics:
        blockers.append({"check": "metrics", "items": missing_metrics})
    if sampled_metrics:
        blockers.append({"check": "exact_metrics", "items": sampled_metrics})
    if unknown_events:
        blockers.append({"check": "semantic_event_fields",
                         "count": len(unknown_events),
                         "fields": dict(sorted(unknown_fields.items()))})
    bad_snap_total = sum(bad_snapshots.values())
    if bad_snap_total:
        blockers.append({"check": "snapshots", "items": bad_snapshots})
    if bad_field_cells:
        blockers.append({"check": "manifest_fields", "count": bad_field_cells,
                         "states": dict(sorted(field_states.items()))})
    if dropped_semantic:
        blockers.append({"check": "interactive_semantic_events",
                         "count": dropped_semantic})
    if not full_watch_scope:
        blockers.append({"check": "watch_scope", "value": watch_source or None})
    if not trace_ok or not plugin_ok:
        blockers.append({"check": "trace_integrity",
                         "trace_complete": trace_ok, "snapshots_complete": plugin_ok})

    # Atomic denominator: each applicable metric, normalized event, snapshot
    # channel, manifest field cell, export-retained normalized event, scope and
    # two integrity checks.  The status is authoritative; percent is a compact
    # display value and reaches 100 only when no blocker exists.
    pre_allocator_states = sum(
        int(s.get("insn") or 0) < allocator_start for s in relevant_states
    ) if allocator_start else 0
    snapshot_units = len(relevant_states) * (4 - len(snapshot_na)) - (
        pre_allocator_states if "physical_counters" not in snapshot_na else 0
    ) + sum(
        0 if "resources" in snapshot_na else len(s.get("resources", []))
        for s in relevant_states)
    field_units = sum(field_states.values())
    total = (len(applicable) + len(semantic_events) + snapshot_units + field_units
             + len(semantic_events) + 3)
    failed = (len(missing_metrics) + len(sampled_metrics) + len(unknown_events)
              + bad_snap_total + bad_field_cells + dropped_semantic
              + (0 if full_watch_scope else 1) + (0 if trace_ok else 1)
              + (0 if plugin_ok else 1))
    passed = max(0, total - failed)
    complete = not blockers
    percent = 100.0 if complete else round(100.0 * passed / max(1, total), 2)
    return {
        "status": "complete" if complete else "incomplete",
        "percent": percent,
        "passed": passed,
        "total": total,
        "metrics": {"covered": len(applicable) - len(missing_metrics),
                    "applicable": len(applicable),
                    "not_applicable": sorted(not_applicable),
                    "missing": missing_metrics, "sampled": sampled_metrics},
        "semantic_events": {"raw": len(semantic_events),
                            "unknown": len(unknown_events),
                            "unknown_fields": dict(sorted(unknown_fields.items())),
                            "dropped_from_interactive": dropped_semantic},
        "snapshots": {"checked": len(relevant_states), **bad_snapshots},
        "snapshot_not_applicable": sorted(snapshot_na),
        "manifest_fields": {"cells": field_units,
                            "states": dict(sorted(field_states.items())),
                            "not_applicable": field_states.get("absent", 0),
                            "unresolved": bad_field_cells},
        "full_watch_scope": full_watch_scope,
        "blockers": blockers,
    }


def coverage(a: Analysis) -> dict:
    """Return the strict coverage audit without constructing a full bundle.

    The report builder needs full physical-memory rows and retained event
    columns.  A CI gate needs neither, and constructing them roughly doubled
    peak memory on the largest traces.  This compact projection contains every
    field consumed by ``_coverage`` and uses the same selection policy in
    non-materializing mode.
    """
    states = [{
        "insn": st.insn,
        "complete": st.complete,
        "phys_ok": st.phys_available,
        "phys_free_ok": st.phys_free_available,
        "procs_ok": st.procs_available,
        "procs": [({"fields": p.fields} if p.fields is not None else {})
                  for p in st.procs],
        "resources": [{"ok": r.available} for r in st.resources],
    } for st in a.states]
    _, selection = _event_selection(a.events, materialize=False)
    return _coverage(a, a.metrics(), states, selection)


def build(a: Analysis) -> dict:
    fn = Interner()
    kind_i = Interner()
    res_i = Interner()
    name_i = Interner()

    events, drop_info = _select_events(a.events)
    metrics = a.metrics()

    ev = {
        "insn": [], "cpu": [], "kind": [], "res": [], "pid": [],
        "pc": [], "func": [], "tick": [], "detail": [], "unknown": [],
    }
    for e in events:
        ev["insn"].append(e.insn)
        ev["cpu"].append(e.cpu)
        ev["kind"].append(kind_i(e.kind))
        ev["res"].append(res_i(e.resource))
        ev["pid"].append(e.pid if e.pid is not None else -1)
        ev["pc"].append(e.pc or 0)
        ev["func"].append(fn(e.func))
        ev["tick"].append(e.tick if e.tick is not None else -1)
        ev["detail"].append(e.detail or None)
        ev["unknown"].append(e.unknown or None)

    states = []
    for st in a.states:
        procs = []
        for p in st.procs:
            procs.append({
                "slot": p.slot, "pid": p.pid, "name": name_i(p.name),
                "state": p.state, "state_name": p.state_name,
                "sz": p.sz, "pagetable": p.pagetable,
                "parent_pid": p.parent_pid, "chan": p.chan,
                "killed": p.killed, "xstate": p.xstate,
                "priority": p.priority, "stride": p.stride, "pass": p.pass_value,
                "user_pages": p.user_pages, "cow_pages": p.cow_pages,
                "pt_pages": p.pagetable_pages,
                "fds": p.open_fds,
                "vm": p.vm_regions,
                "vm_error": p.vm_error,
                **({"fields": p.fields} if p.fields is not None else {}),
            })
        states.append({
            "insn": st.insn, "tick": st.ticks, "seq": st.snap_seq,
            "complete": st.complete, "reason": st.incomplete_reason,
            "free": st.phys_free if st.phys_free_available else None,
            "used": st.phys_used if st.phys_free_available else None,
            "total": st.phys_total,
            "shared": st.shared_pages if st.procs_available else None,
            "phys": _rle(st.phys_kind, st.phys_pid),
            "phys_ok": st.phys_available, "phys_reason": st.phys_reason,
            "phys_free_ok": st.phys_free_available,
            "pt_root_src": st.pagetable_root_source,
            "pt_errors": st.pagetable_errors,
            "procs": procs,
            "procs_ok": st.procs_available, "procs_reason": st.procs_reason,
            "cpus": [{"cpu": c["cpu"], "pid": c["pid"],
                      "name": name_i(c["name"] or ""),
                      "noff": c.get("noff"), "intena": c.get("intena")}
                     for c in st.cpus],
        })

        states[-1]["resources"] = [
            {"name": r.name, "label": r.label, "ok": r.available,
             "reason": r.reason, "columns": r.columns, "rows": r.rows,
             "show_when_any": r.show_when_any, "empty": r.empty_text,
             "notes": r.notes}
            for r in st.resources]
        if st.resources_reason:
            states[-1]["resources_reason"] = st.resources_reason

    man = a.manifest
    tr = a.trace

    coverage = _coverage(a, metrics, states, drop_info)
    capability = {
        "external_observer": True,
        "plugin_api": tr.meta.get("nodefusion.plugin_api"),
        "instruction_timeline": True,
        "memory_snapshots": len(a.states) > 0,
        "guest_semantics": len(a.trace.nftrace) > 0,
        "guest_semantics_note":
            f"内核提供了 nftrace 语义通道，已读到 {len(a.trace.nftrace):,} 条内核上报，"
            "kalloc 返回的物理页等外部看不到的信息由内核直接给出。"
            if a.trace.nftrace else
            "内核里没有 nftrace 语义通道，所有事件均来自虚拟机外部观测。"
            "因此 kalloc 返回的物理页、内核内部的判断依据等信息标记为未知。"
            "（用 make NF_TRACE=1 重新编译内核即可补上这部分语义。）",
        "nftrace_records": len(a.trace.nftrace),
        # Kernel facts explicitly signed in the manifest.  These travel with
        # the report/video evidence so an unavailable metric cannot be mistaken
        # for a recorder failure or a measured zero.
        "absent_declared": metrics.get("absent_declared") or {},
        "missing_watch_functions": a.watchlist.get("missing", []),
        "missing_layout_fields": a.layout.missing,
        "trace_truncated_at_eof": tr.truncated_at_eof,
        "plugin_truncated": bool(tr.end.truncated) if tr.end else False,
        "snapshot_gap_insns": man.get("snap_insns"),
        "coverage": coverage,
    }

    identity = man.get("kernel_elf_identity") or {}
    archived = man.get("kernel_elf_archived") or man.get("kernel_elf")

    return {
        "format": "nodefusion.bundle/2",
        "meta": {
            "run": man.get("run_name"),
            "program": man.get("program"),
            "outcome": man.get("outcome"),
            "kernel_kind": man.get("kernel_kind"),
            "kernel_dir": man.get("kernel_dir"),
            "kernel_elf": Path(archived).name if archived else None,
            "kernel_elf_sha256": identity.get("sha256"),
            "observed_fields": _observed_fields(states, events),
            "lab_stage": man.get("lab_stage"),
            "make_vars": man.get("make_vars"),
            "cpus": a.ncpu,
            "icount_shift": man.get("icount_shift"),
            "total_insns": tr.total_insns,
            "sample_insns": man.get("sample_insns"),
            "snap_insns": man.get("snap_insns"),
            "boot_snap_insns": man.get("boot_snap_insns"),
            "program_start_insn": man.get("program_start_insn") or 0,
            "started_utc": man.get("started_utc"),
            "wall_seconds": man.get("wall_seconds"),
            "qemu": tr.meta.get("qemu.version") or tr.meta.get("qemu.target"),
            "ram_base": int(tr.meta.get("nf.ram_base", "0x80000000"), 0),
            "page_size": int(tr.meta.get("nf.page_size", "4096"), 0),
            "notes": a.notes,
            "warnings": [{"insn": i, "text": t} for i, t in tr.warnings],
            "console": a.console[-20000:],
            "event_selection": drop_info,
            "capability": capability,
            "kind_names": {k: v for k, v in guest_mod.KIND_NAMES.items()},
        },
        "metrics": metrics,
        "dict": {"kinds": kind_i.items, "res": res_i.items,
                 "funcs": fn.items, "names": name_i.items},
        "events": ev,
        "states": states,
        "samples": _samples(a),
    }


def _samples(a: Analysis) -> dict:
    fn = Interner()
    out = {"insn": [], "cpu": [], "pc": [], "priv": [], "func": []}
    step = max(1, len(a.trace.samples) // 20000)
    for s in a.trace.samples[::step]:
        name, _ = a.elf.resolve_pc(s.pc)
        out["insn"].append(s.insn)
        out["cpu"].append(s.cpu)
        out["pc"].append(s.pc)
        out["priv"].append(s.priv)
        out["func"].append(fn(name))
    out["funcs"] = fn.items
    return out


_JS_EXACT_MAX = 2**53 - 1


def _js_safe(o):
    if isinstance(o, bool):
        return o
    if isinstance(o, int):
        return o if abs(o) <= _JS_EXACT_MAX else f"0x{o & 0xFFFFFFFFFFFFFFFF:x}"
    if isinstance(o, dict):
        return {k: _js_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_js_safe(v) for v in o]
    return o


def encode(bundle: dict) -> str:
    raw = json.dumps(_js_safe(bundle), ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    comp = zlib.compress(raw, 9)
    return base64.b64encode(comp).decode("ascii")


def write_json(bundle: dict, path: Path) -> None:
    path.write_text(json.dumps(_js_safe(bundle), ensure_ascii=False), encoding="utf-8")
