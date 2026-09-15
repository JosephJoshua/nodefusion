
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.corpus

from nodefusion.host import analyze as A
from nodefusion.host.analyze import Analysis
from nodefusion.model.manifest import load_dir
from nodefusion.model.roles import ROLES

REPO = Path(__file__).resolve().parents[2]
MANI = REPO / "nodefusion" / "manifests"
RUNS = Path(__file__).resolve().parents[1] / "runs"
MDIR = MANI

XV6, ARCEOS = "lab3-cowtest-mac", "arceos-ctxsnap500"

A_UNREACHED = 0xffffffc08026d958
A_GC = 0xffffffc08026dab8             # id 3，gc
A_CHILD = 0xffffffc08026deb8


from conftest import shapes as _shapes  # noqa: E402


def _switches(name: str) -> list:
    return _shapes(name).switches



def test_the_role_is_in_the_closed_set():
    assert "sched_context" in ROLES


def test_every_kernel_with_a_switch_event_declares_the_field():
    for name, m in sorted(load_dir(str(MDIR)).items()):
        has_switch = any(
            (v.kind if hasattr(v, "kind") else v) == A.SWITCH_EVENT
            for v in m.events.values())
        if not has_switch:
            continue
        owners = [f"{e.name}.{f.name}" for e in m.entities
                  for f in e.fields if f.role == "sched_context"]
        assert owners, (
            f"{name}：有 {A.SWITCH_EVENT} 事件，却没有任何实体的字段标 "
            f"sched_context")


def test_every_switch_event_names_both_of_its_arguments():
    for name, m in sorted(load_dir(str(MDIR)).items()):
        for fn, spec in m.events.items():
            if (spec.kind if hasattr(spec, "kind") else spec) != A.SWITCH_EVENT:
                continue
            args = list(getattr(spec, "args", None) or [])
            assert A.OUTGOING_CTX_ARG in args, f"{name}:{fn} 缺 {A.OUTGOING_CTX_ARG}"
            assert A.INCOMING_CTX_ARG in args, f"{name}:{fn} 缺 {A.INCOMING_CTX_ARG}"


def test_the_three_kernels_call_this_field_three_different_names():
    manifests = load_dir(str(MDIR))
    got = {}
    for k in ("xv6", "arceos"):
        ent = manifests[k].entity_for("process", fallback="task")
        got[k] = [f.name for f in ent.fields if f.role == "sched_context"]
    got["rcore"] = [
        f"{ent.name}.{f.name}"
        for ent in manifests["rcore"].entities
        for f in ent.fields if f.role == "sched_context"
    ]
    assert got == {"xv6": ["context"], "arceos": ["ctx"],
                   "rcore": ["thread.task_cx", "task.task_cx"]}



def test_xv6_still_resolves_every_switch():
    sw = _switches(XV6)
    assert sw, "一次切换都没有，这条测试没验证到东西"
    bad = [e for e in sw if e.unknown]
    assert not bad, f"{len(bad)}/{len(sw)} 次切换归不了因：{bad[:2]}"


def test_xv6_names_the_scheduler_because_its_enumeration_is_exhaustive():
    assert _shapes(XV6).tasks_exhaustive is True
    assert any(e.detail.get("to_proc") == A.SCHEDULER for e in _switches(XV6))
    assert any(e.detail.get("from_proc") == A.SCHEDULER for e in _switches(XV6))


def test_both_ends_come_from_the_arguments_not_from_memory_of_the_last_switch():
    sw = _switches(XV6)
    first = sw[0]
    assert first.detail.get("from_proc") is not None, first.detail
    assert A.OUTGOING_CTX_ARG in first.detail, first.detail



def test_arceos_switches_are_attributed_at_all():
    sw = _switches(ARCEOS)
    assert len(sw) == 3, [e.insn for e in sw]
    named = [e for e in sw if e.detail.get("to_proc") is not None
             or e.detail.get("from_proc") is not None]
    assert len(named) == 3, "有切换事件两端都没归上"


def test_arceos_resolves_the_two_tasks_it_can_actually_enumerate():
    sw = _switches(ARCEOS)
    by_new = {e.detail.get(A.INCOMING_CTX_ARG): e.detail for e in sw}
    assert by_new[A_GC]["to_pid"] == 3 and by_new[A_GC]["to_proc"] == "gc"
    assert by_new[A_CHILD]["to_pid"] == 4
    assert by_new[A_CHILD]["to_proc"] == "", by_new[A_CHILD]


def test_arceos_refuses_to_call_the_unreachable_task_the_scheduler():
    assert _shapes(ARCEOS).tasks_exhaustive is False
    hits = [e.detail for e in _switches(ARCEOS)
            if e.detail.get(A.INCOMING_CTX_ARG) == A_UNREACHED
            or e.detail.get(A.OUTGOING_CTX_ARG) == A_UNREACHED]
    assert hits, f"没找到 {A_UNREACHED:#x} 那两条"
    for d in hits:
        end = "to" if d.get(A.INCOMING_CTX_ARG) == A_UNREACHED else "from"
        assert d.get(f"{end}_proc") != A.SCHEDULER, d
        assert f"{end}_unknown" in d, d
        assert "不猜" in d[f"{end}_unknown"]


def test_the_reason_says_which_address_could_not_be_placed():
    d = next(e.detail for e in _switches(ARCEOS)
             if "to_unknown" in e.detail)
    assert f"{A_UNREACHED:#x}" in d["to_unknown"]


def test_an_unplaced_end_is_listed_as_unknown_not_left_silent():
    sw = [e for e in _switches(ARCEOS) if "to_unknown" in e.detail]
    assert sw and all("to_pid" in e.unknown for e in sw)


def test_no_slot_is_invented_for_a_task_that_was_never_enumerated():
    for e in _switches(ARCEOS):
        for end in ("from", "to"):
            if f"{end}_unknown" in e.detail:
                assert e.detail.get(f"{end}_slot") is None, e.detail



def test_the_map_is_keyed_by_enumerated_addresses_not_by_a_stride_formula():
    addrs = sorted({c for c in _shapes(ARCEOS).sched_ctxs if c})
    assert len(addrs) >= 3, addrs
    gaps = {b - a_ for a_, b in zip(addrs, addrs[1:])}
    assert len(gaps) > 1, f"间距居然是齐的（{gaps}），这条测试的前提没了"


def test_a_task_found_by_enumeration_keeps_its_slot():
    sw = _switches(ARCEOS)
    d = next(e.detail for e in sw
             if e.detail.get(A.INCOMING_CTX_ARG) == A_CHILD)
    assert isinstance(d.get("to_slot"), int), d



def test_argument_names_can_come_from_the_manifest_after_recording():
    import json
    d = RUNS / ARCEOS
    if not (d / "watchlist.json").is_file():
        pytest.skip(f"这台机器上没有 {ARCEOS}")
    entry = next(e for e in json.loads((d / "watchlist.json").read_text())["entries"]
                 if e.get("kind") == A.SWITCH_EVENT)
    assert not entry.get("params"), "这趟录的时候已经有名字了，这条没在验后补"
    assert entry["args"] == 2, entry

    sw = _switches(ARCEOS)
    assert all(A.INCOMING_CTX_ARG in e.detail for e in sw)


def test_the_lookup_prefers_the_full_symbol_over_the_short_name():
    entry = {"symbol": "axcpu::riscv::context::context_switch",
             "name": "context_switch", "kind": A.SWITCH_EVENT, "args": 2}
    events = load_dir(str(MDIR))["arceos"].events
    _, _, argnames = A.event_shape("context_switch", entry,
                                   kernel_kind="arceos", events=events)
    assert argnames == [A.OUTGOING_CTX_ARG, A.INCOMING_CTX_ARG]


def test_a_recorded_name_wins_over_the_manifest():
    entry = {"symbol": "axcpu::riscv::context::context_switch",
             "name": "context_switch", "kind": A.SWITCH_EVENT,
             "args": 2, "params": ["当年这么叫", "另一个"]}
    events = load_dir(str(MDIR))["arceos"].events
    _, _, argnames = A.event_shape("context_switch", entry,
                                   kernel_kind="arceos", events=events)
    assert argnames == ["当年这么叫", "另一个"]



def test_a_metric_backed_by_real_events_is_not_reported_as_unobservable():
    n = len(_switches(ARCEOS))
    assert n == 3
    assert _shapes(ARCEOS).metrics["context_switches"] == n


def test_a_watched_function_that_never_fired_still_counts_as_zero_not_unknown():
    s = _shapes(XV6)
    m = s.metrics
    fired = set(s.kind_counts)
    zeros = [k for k, v in m.items()
             if v == 0 and k in Analysis._METRIC_KINDS]
    assert not any(k in fired for k in zeros), (zeros, fired & set(zeros))
    assert m["context_switches"] > 0, "xv6 这趟没有切换，这条测试选错样本了"


def test_rcore_declares_its_enumeration_incomplete_and_we_read_that():
    assert _shapes("rcore-ch6-fs").tasks_exhaustive is False

    mdir = Path(__file__).resolve().parents[1] / "manifests"
    task = load_dir(str(mdir))["rcore"].entity_for("process", fallback="task")
    declared = {s.completeness for s in task.sources}
    assert "reachable_only" in declared, declared
    assert "unknown" not in declared, f"有 source 没声明 completeness：{declared}"


def test_never_declaring_completeness_is_not_the_same_as_declaring_it_partial():
    from nodefusion.model.manifest import _COMPLETENESS

    assert _COMPLETENESS["unknown"] is None
    assert _COMPLETENESS["total"] is True
    for word in ("partial", "reachable_only", "ready_only", "none"):
        assert _COMPLETENESS[word] is False, word


def test_an_unrecognised_completeness_word_is_refused_at_load():
    import tempfile

    from nodefusion.model.manifest import ManifestError, load

    src = Path(__file__).resolve().parents[2] / "nodefusion/manifests/rcore.toml"
    text = src.read_text()
    assert 'completeness = "reachable_only"' in text, "rcore.toml 改了，样本要换"
    typo = text.replace('completeness = "reachable_only"',
                        'completeness = "reachabel_only"', 1)

    tmp = Path(tempfile.mkdtemp()) / "typo.toml"
    tmp.write_text(typo)
    with pytest.raises(ManifestError, match="completeness"):
        load(tmp)

    ok = Path(tempfile.mkdtemp()) / "ok.toml"
    ok.write_text(text)
    load(ok)
