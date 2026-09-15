
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import analyze as A

RUNS = Path(__file__).resolve().parents[1] / "runs"
XV6, RCORE, ARCEOS = "lab3-cowtest-mac", "rcore-ch6-fs", "arceos-ctxsnap500"


def _run(name: str):
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    return A.analyze(d)



def test_the_table_holds_kinds_not_function_names():
    from nodefusion.model.manifest import load_dir

    mdir = Path(__file__).resolve().parents[1] / "manifests"
    declared = {getattr(spec, "kind", spec)
                for m in load_dir(str(mdir)).values()
                for spec in m.events.values()}
    unknown = {k: v for k, v in A.Analysis._METRIC_KINDS.items()
               if v not in declared}
    assert not unknown, f"这些类别没有任何 manifest 声明过：{unknown}"


def test_the_old_xv6_name_table_is_gone():
    assert not hasattr(A.Analysis, "_WATCH_DEPS")


def test_cache_misses_count_only_device_reads():
    a = object.__new__(A.Analysis)
    a.events = [
        A.Event(1, 0, "disk.io", "disk", detail={"operation": "read"}),
        A.Event(2, 0, "disk.io", "disk", detail={"operation": "write"}),
        A.Event(3, 0, "disk.io", "disk", detail={"operation": "write"}),
    ]
    assert a._disk_reads(3) == 1


def test_shared_xv6_disk_entry_uses_the_recorded_write_argument():
    a = object.__new__(A.Analysis)
    a.events = [
        A.Event(1, 0, "disk.io", "disk", detail={"write": 0}),
        A.Event(2, 0, "disk.io", "disk", detail={"write": 1}),
    ]
    assert a._disk_reads(2) == 1


def test_unknown_disk_direction_blocks_the_derived_metric():
    a = object.__new__(A.Analysis)
    a.events = [A.Event(1, 0, "disk.io", "disk")]
    assert a._disk_reads(1) is None


def test_old_watchlist_can_take_direction_from_the_current_exact_symbol():
    from nodefusion.model.manifest import EventSpec

    entry = {"name": "read_block", "symbol": "driver::Disk::read_block"}
    events = {
        "driver::Disk::read_block": EventSpec(
            kind="disk.io", operation="read"),
        "other::Disk::read_block": EventSpec(
            kind="disk.io", operation="write"),
    }
    assert A.event_operation("read_block", entry, events) == "read"



@pytest.mark.corpus
def test_the_alias_trap_one_instruction_two_real_names():
    a = _run(XV6)
    assert "fork" in a.watched_names, "这趟没挂 fork，样本选错了"
    assert a.kevents is not None
    assert "kfork" in a.kevents, "manifest 不再写 kfork 了，这条测试要重想"
    assert "fork" not in a.kevents, "manifest 现在两个都写了，陷阱没了"

    inv = {}
    for name, spec in a.kevents.items():
        inv.setdefault(getattr(spec, "kind", spec), []).append(name)
    assert not any(n in a.watched_names for n in inv.get("proc.fork", ())), (
        "反查表这回能查到了 —— 陷阱不成立，这条测试该删")

    assert "proc.fork" in a._watched_kinds()
    assert a.metrics()["forks"] == 4



@pytest.mark.corpus
def test_the_xv6_numbers_are_unchanged():
    m = _run(XV6).metrics()
    assert {k: m[k] for k in A.Analysis._METRIC_KINDS} == {
        "context_switches": 932, "kalloc": 38588, "kfree": 108815,
        "disk_io": 42, "bcache_reads": 395, "log_commits": 9,
        "forks": 4, "execs": 3,
        "vm_maps": 76583, "vm_unmaps": 18,
        "page_table_maps": None,
    }


@pytest.mark.corpus
def test_evidence_still_outranks_the_table_on_arceos():
    m = _run(ARCEOS).metrics()
    assert m["context_switches"] == 3
    assert "sched.switch" not in (m["unobservable_reason"] or "")



@pytest.mark.corpus
def test_every_function_named_in_the_reason_is_this_kernels_own():
    for run in (RCORE, ARCEOS):
        a = _run(run)
        why = a.metrics()["unobservable_reason"] or ""
        assert why, f"{run} 十个指标不全都有值，却没给理由"
        assert a.kevents is not None, f"{run} 认不出内核了，这条测试选错样本"

        named: list[str] = []
        kinds: list[str] = []
        for seg in why.split("；"):
            if "没挂上观测点：" in seg:
                named = seg.split("没挂上观测点：", 1)[1].split("。")[0].split("、")
            elif "没有任何函数映射过来" in seg:
                kinds = seg.split("分不出来）：", 1)[1].split("。")[0].split("、")

        assert named or kinds, f"{run} 的理由一句都没解开，解析器该跟着改了\n{why}"

        alien = [n for n in named if n not in a.kevents]
        assert not alien, f"{run} 点了名，但这些不是它自己的函数：{alien}\n{why}"
        bad = [k for k in kinds if k not in A.Analysis._METRIC_KINDS.values()]
        assert not bad, f"{run} 列了不属于这些指标的类别：{bad}"

        m_now = a.metrics()
        blind_kinds = {k for name, k in A.Analysis._METRIC_KINDS.items()
                       if m_now.get(name) is None}
        for n in named:
            assert n not in a.watched_names, (
                f"{run} 说 {n!r} 没挂上观测点，但它就在 watched_names 里\n{why}")
            k = getattr(a.kevents[n], "kind", a.kevents[n])
            assert k in blind_kinds, (
                f"{run} 点了 {n!r}（类别 {k}），可这个类别对应的指标算得出来，"
                f"点它没有意义\n{why}")

        if run == RCORE:
            assert named, f"{run} 该有点名的函数才对\n{why}"
            m = a.metrics()
            declared = {getattr(s, "kind", s) for s in (a.kevents or {}).values()}
            absent = set(m.get("absent_declared") or {})
            expect = {k for name, k in A.Analysis._METRIC_KINDS.items()
                      if m.get(name) is None and k not in declared and k not in absent}
            assert set(kinds) == expect, (sorted(kinds), sorted(expect), why)


@pytest.mark.corpus
def test_the_unmistakably_xv6_names_never_appear():
    xv6_only = ("swtch", "kalloc", "kfree", "virtio_disk_rw",
                "bread", "mappages", "uvmunmap")
    for run in (RCORE, ARCEOS):
        why = _run(run).metrics()["unobservable_reason"] or ""
        leaked = [n for n in xv6_only if n in why]
        assert not leaked, f"{run} 的理由里混进了 xv6 的函数名：{leaked}\n{why}"


@pytest.mark.corpus
def test_old_recording_reports_the_new_unmap_hook_as_missing_from_its_elf():
    """A pre-integration recording cannot retroactively contain the new hook.

    `rcore-ch6-fs` predates the NodeFusion integration.  The current manifest
    now maps `vm.unmap` to the exact per-region hook, but that old ELF cannot
    contain a symbol introduced later.  It must therefore be described as a
    mapped function unavailable in this ELF—not as a permanent granularity gap.
    `frame_dealloc` remains the independent "present but not armed" example.
    """
    why = _run(RCORE).metrics()["unobservable_reason"]

    segs = why.split("；")
    unwatched = [s for s in segs if "没挂上观测点" in s]
    unavailable = [s for s in segs if "对应函数不在本次 ELF" in s]
    assert len(unwatched) == 1, f"「没挂上」那一段应该正好一段：{segs}"
    assert len(unavailable) == 1, f"旧 ELF 缺新 hook 的段应该正好一段：{segs}"

    assert "frame_dealloc" in unwatched[0], (
        f"frame_dealloc 该在「没挂上」那一段里\n{why}")
    assert "vm.unmap" in unavailable[0], (
        f"vm.unmap 该在「本次 ELF 没有新 hook」那一段里\n{why}")
    assert "没有粒度对得上的函数可挂" not in why


@pytest.mark.corpus
def test_an_unrecognised_kernel_says_it_cannot_tell():
    a = _run(RCORE)
    a.kevents = None
    m = {k: None for k in A.Analysis._METRIC_KINDS}
    why = a._unobservable_reason(m)
    assert "无从知道" in why, why
    assert "没有声明" not in why, f"认不出内核却断言人家没声明：{why}"


@pytest.mark.corpus
def test_later_chapter_functions_are_not_reported_as_missed_watchpoints():
    """A family manifest is broader than any one chapter's concrete ELF."""
    a = _run("rcore-ch1-bare")
    why = a.metrics()["unobservable_reason"] or ""
    assert "对应函数不在本次 ELF" in why, why
    assert "最多只能有 6 项" in why, why
    assert "没挂上观测点" not in why, (
        "ch1 没有后续章节的任务/内存/文件系统函数，不能把结构缺席说成漏挂点："
        + why)


@pytest.mark.corpus
def test_the_only_thing_xv6_cannot_measure_is_the_other_granularity():
    m = _run(XV6).metrics()
    why = m["unobservable_reason"] or ""
    assert why, (
        "xv6 的 unobservable_reason 又是 None 了。要么 page_table_maps 有值了"
        "（那说明区域级的又被映回单 PTE 那个词上，#70 白改），"
        "要么那条指标被删了")
    assert "pagetable.map" in why, why
    others = [k for k in A.Analysis._METRIC_KINDS.values()
              if k != "pagetable.map" and k in why]
    assert not others, f"xv6 又有别的指标算不出来了：{others}\n{why}"
    assert m["vm_maps"] == 76583, (
        f"vm_maps = {m['vm_maps']}，期望 76583 —— #70 只该改名字，不该改数")
