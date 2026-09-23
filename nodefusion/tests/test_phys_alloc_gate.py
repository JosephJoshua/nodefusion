
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from nodefusion.host import analyze as A
from nodefusion.host.nftrace import NfTraceRec

RUNS = Path(__file__).resolve().parents[1] / "runs"

XV6 = "lab3-cowtest-mac"


def _run(name: str):
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    return A.analyze(d)


def _allocs(a):
    return [e for e in a.events if e.kind == A.PHYS_ALLOC_EVENT]



def test_the_gate_is_not_spelled_as_a_kernel_name():
    src = Path(A.__file__).read_text()
    line = [l for l in src.splitlines()
            if "_nft_kalloc_after(w.cpu" in l]
    assert line, "找不到取物理页那一行，这条测试该跟着改了"
    idx = src.splitlines().index(line[0])
    gate = next(l for l in reversed(src.splitlines()[:idx])
                if l.lstrip().startswith("if "))
    assert "PHYS_ALLOC_EVENT" in gate, f"判据不是事件种类：{gate.strip()}"
    assert "kalloc" not in gate, f"判据里还写着函数名：{gate.strip()}"


def test_the_kind_is_what_the_manifest_actually_says():
    from nodefusion.model.manifest import load_dir

    mdir = Path(__file__).resolve().parents[1] / "manifests"
    declared = set()
    for m in load_dir(str(mdir)).values():
        for spec in m.events.values():
            declared.add(spec.kind if hasattr(spec, "kind") else spec)
    assert A.PHYS_ALLOC_EVENT in declared, (
        f"没有任何 manifest 声明 {A.PHYS_ALLOC_EVENT}，这个常量是死的")



@pytest.mark.corpus
def test_xv6_still_produces_its_allocation_events():
    n = len(_allocs(_run(XV6)))
    assert n == 38588, f"phys.alloc 事件数变了：{n}"


@pytest.mark.corpus
def test_every_allocation_says_it_does_not_know_which_page():
    ev = _allocs(_run(XV6))
    assert ev, "一条 phys.alloc 都没有，这条测试没验证到东西"
    filled = [e for e in ev if "allocated_pa" in e.detail]
    assert not filled, f"{len(filled)} 条凭空填了物理页：{filled[:1]}"
    assert all("allocated_pa" in e.unknown for e in ev)


@pytest.mark.corpus
def test_the_run_really_has_no_semantic_channel():
    a = _run(XV6)
    assert len(a.trace.nftrace) == 0, (
        f"这趟有 {len(a.trace.nftrace)} 条 nftrace 了 —— "
        "上一条测试的前提没了，去把它改成验证'填得对'")


@pytest.mark.corpus
def test_a_kernel_without_the_declaration_simply_has_no_such_events():
    for name in ("rcore-ch6-fs", "arceos-ctxsnap500"):
        a = _run(name)
        assert _allocs(a) == []
        assert not any("allocated_pa" in e.unknown for e in a.events)


def test_clone_semantic_records_become_registered_events():
    a = object.__new__(A.Analysis)
    for nft_type, expected in ((A.Analysis.NFT_PROC_FORK, "proc.fork"),
                               (A.Analysis.NFT_THREAD_CREATE, "thread.create")):
        rec = NfTraceRec(insn=123, cpu=0, type=nft_type, a=(7, 8, 0, 0))
        event = a._nftrace_event(rec, -1, {})
        assert event.kind == expected
        assert event.detail == {
            "parent_tid": 7, "child_tid": 8, "source": "nftrace"}


def test_kalloc_semantic_record_is_the_complete_allocation_event():
    a = object.__new__(A.Analysis)
    rec = NfTraceRec(insn=123, cpu=0, type=A.Analysis.NFT_KALLOC,
                     a=(0x8123_4000, 4, 123, 45))
    event = a._nftrace_event(rec, -1, {})
    assert event.kind == "phys.alloc"
    assert event.resource == "physical_memory"
    assert event.detail == {
        "allocated_pa": 0x8123_4000, "num_pages": 4,
        "free_pages": 123, "allocator_used_pages": 45,
        "source": "nftrace"}
    assert event.unknown == []


def test_legacy_kalloc_record_does_not_invent_a_page_count():
    a = object.__new__(A.Analysis)
    rec = NfTraceRec(insn=123, cpu=0, type=A.Analysis.NFT_KALLOC,
                     a=(0x8123_4000, 0, 0, 0))
    event = a._nftrace_event(rec, -1, {})
    assert "num_pages" not in event.detail
    assert event.unknown == ["num_pages"]


def test_sched_semantic_record_fills_both_endpoints_without_snapshots():
    a = object.__new__(A.Analysis)
    rec = NfTraceRec(insn=123, cpu=0, type=A.Analysis.NFT_SCHED_SWITCH,
                     a=(41, 42, A.Analysis.NFT_NO_TASK, 7))
    event = a._nftrace_event(rec, -1, {})
    assert event.kind == "sched.switch"
    assert event.unknown == []
    assert event.detail["from_task_id"] == 41
    assert event.detail["from_pid"] is None
    assert event.detail["from_proc"] == "kernel-task#41"
    assert event.detail["to_task_id"] == 42
    assert event.detail["to_pid"] == 7


def test_kfree_semantic_record_has_physical_range():
    a = object.__new__(A.Analysis)
    rec = NfTraceRec(insn=123, cpu=0, type=A.Analysis.NFT_KFREE,
                     a=(0x8123_4000, 8, 131, 37))
    event = a._nftrace_event(rec, -1, {})
    assert event.kind == "phys.free"
    assert event.detail == {
        "freed_pa": 0x8123_4000, "num_pages": 8,
        "free_pages": 131, "allocator_used_pages": 37,
        "source": "nftrace"}
    assert event.unknown == []


def test_allocator_state_record_is_not_duplicated_as_an_action_event():
    a = object.__new__(A.Analysis)
    a.states = []
    rec = NfTraceRec(insn=123, cpu=0, type=A.Analysis.NFT_ALLOCATOR_STATE,
                     a=(321, 54, 0, 0))
    a._attribute = lambda *_: (7, "init")
    assert a._nftrace_event(rec, -1, {}) is None


def test_latest_allocator_state_fills_absolute_snapshot_counters():
    a = object.__new__(A.Analysis)
    a.nft_allocator_states = [(10, 100, 20), (30, 90, 30)]
    a.nft_allocator_state_insns = [10, 30]
    a.decoder = NS(kmem=NS(reason="内核里没有符号 'kmem'"))
    st = NS(insn=25, phys_total=128, phys_free=0, phys_used=0,
            phys_free_available=False,
            phys_reason="内核里没有符号 'kmem'；页表根 0x1 未走完")

    a._apply_allocator_state(st)

    assert st.phys_free_available is True
    assert st.phys_free == 100
    assert st.phys_used == 28
    assert st.phys_reason == "页表根 0x1 未走完"


def test_clone_completion_channel_is_selected_per_event_kind():
    a = object.__new__(A.Analysis)
    a.nft_clone_types = {A.Analysis.NFT_PROC_FORK}
    assert a._nft_clone_channel("proc.fork") is True
    assert a._nft_clone_channel("thread.create") is False


def test_successful_clone_channel_replaces_all_entry_attempts():
    a = object.__new__(A.Analysis)
    a.nft_clone_types = {A.Analysis.NFT_PROC_FORK}
    a.nft_records = {(0, A.Analysis.NFT_PROC_FORK): [
        NfTraceRec(insn=200, cpu=0, type=A.Analysis.NFT_PROC_FORK,
                   a=(7, 8, 0, 0))]}
    a.watch_by_id = {0: {"name": "fork", "symbol": "fork",
                         "kind": "proc.fork"}}
    a.kernel_kind = "ucore"
    a.kevents = {}
    hit = NS(watch_id=0, cpu=0, insn=100, a=(0,) * 8)
    # The entry could have failed; pairing it with a later success by a
    # five-million-instruction window would be unsound.
    assert a._watch_event(hit, 0, {}) is None
    assert a._nftrace_event(a.nft_records[(0, A.Analysis.NFT_PROC_FORK)][0],
                            0, {}).kind == "proc.fork"


def test_declared_clone_channel_suppresses_failed_only_entry_attempts():
    a = object.__new__(A.Analysis)
    a.clone_completion_channel = "nftrace"
    a.nft_clone_types = set()
    a.nft_records = {}
    assert a._nft_clone_channel("proc.fork") is True
    assert a._nft_clone_channel("thread.create") is True


def test_entry_only_kernel_keeps_clone_attempts_without_semantic_records():
    a = object.__new__(A.Analysis)
    a.clone_completion_channel = "entry"
    a.nft_clone_types = set()
    assert a._nft_clone_channel("proc.fork") is False
