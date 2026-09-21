
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.host import bundle as B                      # noqa: E402
from nodefusion.host.analyze import Event                     # noqa: E402
from nodefusion.host.guest import SystemState                # noqa: E402
from nodefusion.host.resources import ResourceTable          # noqa: E402

LEGACY = ("bcache", "ftable", "itable")


def _analysis(*states) -> NS:
    return NS(
        events=[], states=list(states), console=[], elf=None, ncpu=1,
        notes=[], metrics=lambda: {}, layout=NS(missing=[]), watchlist={},
        manifest={"run_name": "t"},
        trace=NS(meta={}, nftrace=[], warnings=[], total_insns=0,
                 truncated_at_eof=False, end=None, snapshots=[], samples=[]),
    )


def _state(resources=(), reason="") -> SystemState:
    st = SystemState(insn=0, snap_seq=0, ticks=None, complete=True)
    st.resources = list(resources)
    st.resources_reason = reason
    return st


def _table(name="bcache") -> ResourceTable:
    return ResourceTable(name, "缓冲区缓存", True, "",
                         columns=[{"key": "slot", "label": "槽位"}],
                         rows=[{"slot": 0}], show_when_any=["slot"],
                         empty_text="空")


def test_the_format_string_says_two():
    assert B.build(_analysis(_state()))["format"] == "nodefusion.bundle/2"


def test_semantic_function_entries_remain_visible_in_function_trace():
    a = _analysis(_state())
    a.elf = NS(resolve_pc=lambda addr: ("_ZN2os2vm3map17h1234567890abcdefE", 0))
    a.events = [
        Event(1, 0, "vm.map", "vm", func="map_region", function_entry=True,
              entry_name="os::vm::map_region", return_address=0x80001000),
        Event(2, 0, "trap.enter", "trap", func="trap_handler"),
    ]
    result = B.build(a)
    assert result["events"]["entry"] == [1, 0]
    assert result["dict"]["funcs"][result["events"]["entry_name"][0]] == \
        "os::vm::map_region"
    assert result["events"]["caller"][0] >= 0
    assert result["events"]["caller"][1] == -1
    assert result["meta"]["function_entries"] == {"raw": 1, "retained": 1}


def test_caller_names_demangle_rust_trait_impls():
    raw = ("_RNvXs5_NtNtNtNtCsaZSK9boPIKd_13starry_kernel2mm6aspace"
           "7backend3cowNtB5_10CowBackendNtB7_10BackendOps9clone_map")
    a = _analysis(_state())
    a.elf = NS(resolve_pc=lambda addr: (raw, 0))
    a.events = [Event(1, 0, "vm.map", "vm", function_entry=True,
                      entry_name="map_page", return_address=0x80001000)]
    result = B.build(a)
    caller_id = result["events"]["caller"][0]
    assert result["dict"]["funcs"][caller_id] == \
        "starry_kernel::mm::aspace::backend::cow::CowBackend::clone_map"


def test_resources_is_always_there_even_when_empty():
    b = B.build(_analysis(_state(reason="没声明")))
    assert b["states"][0]["resources"] == []


def test_the_three_hardcoded_keys_are_gone():
    b = B.build(_analysis(_state([_table()]), _state(reason="没声明")))
    for s in b["states"]:
        assert not [k for k in LEGACY if k in s]


def test_an_empty_table_list_carries_its_reason():
    b = B.build(_analysis(_state(reason="没有走 manifest 那条路")))
    assert b["states"][0]["resources_reason"] == "没有走 manifest 那条路"


def test_no_reason_key_when_there_are_tables():
    assert "resources_reason" not in B.build(
        _analysis(_state([_table()])))["states"][0]


def test_columns_and_order_ride_along_with_the_data():
    s = B.build(_analysis(_state([_table()])))["states"][0]
    assert s["resources"][0]["columns"] == [{"key": "slot", "label": "槽位"}]
    assert s["resources"][0]["show_when_any"] == ["slot"]


def test_an_unavailable_table_still_appears_with_its_reason():
    t = ResourceTable("ftable", "打开文件表", False, "这个内核里没有 file.ref")
    s = B.build(_analysis(_state([t])))["states"][0]
    assert s["resources"][0]["ok"] is False
    assert s["resources"][0]["reason"] == "这个内核里没有 file.ref"


def test_observed_fields_inventory_only_claims_concrete_present_data():
    states = [{
        "procs": [{"fields": {
            "pid": {"state": "present", "value": 7},
            "task_ext": {"state": "absent"},
            "malformed": None,
        }}],
        "resources": [{
            "name": "bcache",
            "columns": [{"key": "block"}, {"label": "missing key"}],
        }],
    }]
    events = [NS(kind="disk.io", detail={"block": 2, "write": True})]

    assert B._observed_fields(states, events) == {
        "process": ["pid"],
        "resources": ["bcache.block"],
        "events": {"disk": ["block", "write"]},
    }


def test_event_selection_metadata_accounts_for_every_raw_event(monkeypatch):
    monkeypatch.setattr(B, "MAX_EVENTS", 10)
    monkeypatch.setattr(B, "MIN_SPARE_EVENTS", 3)
    events = [NS(kind="syscall.enter", insn=i) for i in range(4)]
    events += [NS(kind="func.hot_path", insn=i + 4) for i in range(26)]

    selected, audit = B._select_events(events)

    assert audit["applied"] is True
    assert audit["raw"] == 30
    assert audit["retained"] == len(selected) == 10
    assert audit["dropped"] == 20
    assert audit["raw"] == audit["retained"] + audit["dropped"]
    assert audit["priority_raw"] == 4
    assert audit["spare_raw"] == 26
    assert audit["spare_budget"] == 6
    assert audit["stride"] == 4
    assert sum(audit["retained_kinds"].values()) == audit["retained"]
    assert sum(audit["dropped_kinds"].values()) == audit["dropped"]
    assert [e.insn for e in selected[:4]] == [0, 1, 2, 3]


def test_bounded_selector_preserves_order_and_systematic_sample(monkeypatch):
    monkeypatch.setattr(B, "MAX_EVENTS", 6)
    monkeypatch.setattr(B, "MIN_SPARE_EVENTS", 2)
    events = [NS(kind=("proc.fork" if i in {2, 7} else "func.hot"), insn=i)
              for i in range(12)]
    selected, audit = B._select_events(events)
    # Ten diagnostics, four spare slots => old spare[::2][:4], interleaved
    # with both semantic events in original timeline order.
    assert [event.insn for event in selected] == [0, 2, 3, 5, 7, 8]
    assert audit["stride"] == 2
    assert audit["retained"] == 6


def test_large_semantic_stream_stays_browser_bounded(monkeypatch):
    monkeypatch.setattr(B, "MAX_EVENTS", 10)
    monkeypatch.setattr(B, "MIN_SPARE_EVENTS", 3)
    events = [NS(kind="syscall.enter", insn=i) for i in range(80)]
    events += [NS(kind="proc.exit", insn=80)]
    events += [NS(kind="func.hot", insn=i) for i in range(81, 101)]
    selected, audit = B._select_events(events)
    assert len(selected) == audit["retained"] == 10
    assert any(e.kind == "syscall.enter" for e in selected)
    assert any(e.kind == "proc.exit" for e in selected)
    assert audit["semantic_retained"] == 7
    assert audit["dropped_kinds"]["syscall.enter"] == 74
    assert audit["raw"] == audit["retained"] + audit["dropped"]


def test_interactive_sampling_does_not_erase_raw_semantic_coverage(monkeypatch):
    monkeypatch.setattr(B, "MAX_EVENTS", 10)
    monkeypatch.setattr(B, "MIN_SPARE_EVENTS", 3)
    a = _analysis(_state())
    a.events = [Event(i, 0, "syscall.enter", "syscall") for i in range(40)]
    audit = B.build(a)["meta"]["capability"]["coverage"]
    assert audit["semantic_events"]["raw"] == 40
    assert audit["semantic_events"]["dropped_from_interactive"] == 30
    assert not any(b["check"] == "interactive_semantic_events"
                   for b in audit["blockers"])


def test_event_selection_without_sampling_is_still_auditable(monkeypatch):
    monkeypatch.setattr(B, "MAX_EVENTS", 10)
    events = [NS(kind="heap.alloc", insn=i) for i in range(3)]
    selected, audit = B._select_events(events)
    assert selected is events
    assert audit["applied"] is False
    assert (audit["raw"], audit["retained"], audit["dropped"]) == (3, 3, 0)
    assert audit["retained_kinds"] == {"heap.alloc": 3}


def test_compact_coverage_audit_matches_the_rendered_bundle():
    a = _analysis()
    assert B.coverage(a) == B.build(a)["meta"]["capability"]["coverage"]


def test_every_normalized_namespace_is_retained_when_budget_allows(monkeypatch):
    """Adding a new semantic namespace must not require editing an allowlist."""
    monkeypatch.setattr(B, "MAX_EVENTS", 7)
    monkeypatch.setattr(B, "MIN_SPARE_EVENTS", 1)
    semantic = [
        NS(kind="phys.alloc", insn=1), NS(kind="heap.alloc", insn=2),
        NS(kind="bcache.read", insn=3), NS(kind="vm.map", insn=4),
        NS(kind="future_namespace.fact", insn=5),
    ]
    diagnostic = [NS(kind="func.noise", insn=i) for i in range(6, 30)]
    selected, audit = B._select_events(semantic + diagnostic)
    assert all(event in selected for event in semantic)
    assert not [kind for kind in audit["dropped_kinds"]
                if not kind.startswith("func.")]


def test_declared_kernel_absence_rides_with_report_and_video_metadata():
    analysis = _analysis(_state())
    declared = {
        "log.commit": {
            "why": "feature",
            "evidence": "easy-fs/src has no journal or transaction commit layer",
        }
    }
    analysis.metrics = lambda: {"absent_declared": declared}
    bundle = B.build(analysis)
    assert bundle["meta"]["capability"]["absent_declared"] == declared


def test_missing_absolute_physical_counters_block_strict_coverage():
    st = _state()
    st.phys_available = True
    st.phys_free_available = False
    st.procs_available = True
    analysis = _analysis(st)
    analysis.manifest["watch_source"] = "manifest:test"

    coverage = B.build(analysis)["meta"]["capability"]["coverage"]

    assert coverage["snapshots"]["physical_memory"] == 0
    assert coverage["snapshots"]["physical_counters"] == 1
    assert any(blocker["check"] == "snapshots"
               for blocker in coverage["blockers"])


def test_missing_end_record_blocks_strict_coverage():
    analysis = _analysis(_state())
    analysis.manifest["watch_source"] = "manifest:test"
    result = B.coverage(analysis)
    assert any(blocker["check"] == "trace_integrity"
               for blocker in result["blockers"])



_RCORE = Path(__file__).resolve().parents[1] / "runs" / "rcore-ch6-fs"


@pytest.mark.corpus
def test_columns_are_an_outcome_not_a_schema():
    if not (_RCORE / "trace.nfb").is_file():
        import pytest
        pytest.skip(f"这台机器上没有 {_RCORE.name}")

    from nodefusion.host import analyze as A

    d = B.build(A.analyze(_RCORE))
    shapes: dict[str, set] = {}
    for st in d["states"]:
        for r in st.get("resources") or []:
            key = (r["ok"], tuple(c["key"] for c in r["columns"]))
            shapes.setdefault(r["name"], set()).add(key)

    assert shapes, "一张资源表都没有，这条测试没验证到东西"
    varying = {n: s for n, s in shapes.items() if len(s) > 1}
    assert varying, (
        "这趟里列名不再变了 —— 那 #33 的理由就没了，去把它重新想一遍，"
        f"别直接改这条断言。实测各表取值：{shapes}")

    for name, s in varying.items():
        assert {ok for ok, _ in s} == {False, True}, (name, s)
        assert all(bool(cols) == ok for ok, cols in s), (name, s)
