
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

import pytest

from nodefusion.host import analyze as A
from nodefusion.model import kinds as K

from conftest import corpus_run_dirs as _corpus_run_dirs  # noqa: E402
from conftest import shapes as _shapes  # noqa: E402

RUNS = Path(__file__).resolve().parents[1] / "runs"

pytestmark = [
    pytest.mark.corpus,
    pytest.mark.skipif(
        not _corpus_run_dirs(RUNS),
        reason="这台机器上没有录制结果（nodefusion/runs/ 不进 git）"),
]

_TIMER_RUN = "lab3-cowtest-mac"
_TIMER_COUNT = 419


@lru_cache(maxsize=None)
def _kinds_of(name: str) -> tuple[str, ...]:
    return _shapes(name).kinds_seq


def _runs() -> list[str]:
    return [d.name for d in _corpus_run_dirs(RUNS)]


def test_the_timer_pair_fires_one_to_one_and_interleaves():
    if not (RUNS / _TIMER_RUN / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {_TIMER_RUN}")
    seq = [k for k in _kinds_of(_TIMER_RUN)
           if k in ("interrupt.timer", "interrupt.clock")]
    c = Counter(seq)
    assert c["interrupt.timer"] == c["interrupt.clock"] == _TIMER_COUNT, c

    pairs = list(zip(seq, seq[1:]))
    same = [i for i, (x, y) in enumerate(pairs) if x == y]
    assert not same, (
        f"有 {len(same)} 处相邻两条同类，不再是严格交错了 —— "
        f"「一次中断两个观察点」这个结论得重量。头几处在 {same[:5]}")


def test_the_timer_metric_counts_one_side_only():
    if not (RUNS / _TIMER_RUN / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {_TIMER_RUN}")
    m = _shapes(_TIMER_RUN).metrics
    assert m["timer_interrupts"] == _TIMER_COUNT, (
        f"timer_interrupts = {m['timer_interrupts']}，期望 {_TIMER_COUNT}。"
        f"要是 {_TIMER_COUNT * 2}，说明两个观察点被并起来数了")


def test_the_timer_pair_is_recorded_as_distinct_with_its_measurement():
    g = next((x for x in K.RESOLVED_DISTINCT
              if "interrupt.timer" in x["kinds"]), None)
    assert g, "F 组不在 RESOLVED_DISTINCT 里"
    assert g.get("measured"), f"F 组没带测量数据：{g}"
    run, a_, b_, how = g["measured"][0]
    assert run == _TIMER_RUN and a_ == b_ == _TIMER_COUNT, g["measured"]
    assert "交错" in how, how
    assert not any("interrupt.timer" in x["kinds"] for x in K.UNRESOLVED)


def test_undecidable_set_is_exactly_the_unresolved_kinds_with_no_evidence():
    runs = _runs()
    assert runs, "一趟 run 都没有，这条测试没验证到东西"
    fired: set[str] = set()
    for name in runs:
        fired |= set(_kinds_of(name))

    disputed = {k for g in K.UNRESOLVED for k in g["kinds"]}
    expected = disputed - fired

    now_visible = sorted(K.UNDECIDABLE_FROM_TRACES & fired)
    assert not now_visible, (
        f"这几个词现在有输出了：{now_visible}。把它们从 kinds.py 的 "
        f"UNDECIDABLE_FROM_TRACES 里去掉，然后照 F 组的办法把对应那组裁决掉")

    missing = sorted(expected - K.UNDECIDABLE_FROM_TRACES)
    assert not missing, (
        f"这几个词在争议名单上、又一次都没出现过，该收进 "
        f"UNDECIDABLE_FROM_TRACES：{missing}")

    assert K.UNDECIDABLE_FROM_TRACES == expected, (
        sorted(K.UNDECIDABLE_FROM_TRACES), sorted(expected))


def test_undecidable_set_only_names_registered_kinds():
    unknown = sorted(k for k in K.UNDECIDABLE_FROM_TRACES
                     if not K.is_registered(k))
    assert not unknown, unknown


_REGION_RUN, _REGION_FUNC, _REGION_MAPS = "lab3-cowtest-mac", "mappages", 76583
_PAGE_RUN, _PAGE_FUNC, _PAGE_MAPS = "rcore-watchtest", "PageTable", 32318
_PAGE_SYM = "os::mm::page_table::PageTable::map"


@lru_cache(maxsize=None)
def _page_table_maps(name: str) -> tuple[int | None, tuple[str, ...]]:
    sh = _shapes(name)
    funcs = sorted(sh.funcs_by_kind.get("pagetable.map", ()))
    return sh.metrics.get("page_table_maps"), tuple(funcs)


def test_the_two_map_granularities_no_longer_share_a_metric():
    for run in (_REGION_RUN, _PAGE_RUN):
        if not (RUNS / run / "trace.nfb").is_file():
            pytest.skip(f"这台机器上没有 {run}")

    region = _shapes(_REGION_RUN).metrics
    page = _shapes(_PAGE_RUN).metrics

    assert region.get("vm_maps") == _REGION_MAPS, region.get("vm_maps")
    assert region.get("page_table_maps") is None, (
        f"{_REGION_RUN} 又报出 page_table_maps 了：{region.get('page_table_maps')}。"
        f"xv6 没有单 PTE 那一档的观察点，有数说明 mappages 又被映回去了")

    assert page.get("page_table_maps") == _PAGE_MAPS, page.get("page_table_maps")
    assert page.get("vm_maps") is None, (
        f"{_PAGE_RUN} 报出了 vm_maps：{page.get('vm_maps')}")

    region_funcs = sorted(_shapes(_REGION_RUN).funcs_by_kind.get("vm.map", ()))
    page_funcs = sorted(_shapes(_PAGE_RUN).funcs_by_kind.get("pagetable.map", ()))
    assert any(_REGION_FUNC in f for f in region_funcs), region_funcs
    assert any(_PAGE_FUNC in f for f in page_funcs), page_funcs

    for k in ("vm.map", "pagetable.map"):
        assert K.is_registered(k), f"{k} 没登记"


def test_the_region_metric_now_counts_arceos_too():
    runs = [n for n in _runs() if n.startswith("arceos")]
    if not runs:
        pytest.skip("这台机器上没有 arceos 的 run")
    counted = {n: _shapes(n).metrics.get("vm_maps") for n in runs}
    assert any(v for v in counted.values()), (
        f"没有一趟 arceos 报出 vm_maps：{counted}。要么观察点没挂上，"
        f"要么 vm.map 又从指标表里掉了")


def test_rcore_counts_pte_maps_exactly_when_it_armed_that_watchpoint():
    armed_and_counted, counted, armed = [], [], []
    for name in _runs():
        if not name.startswith("rcore"):
            continue
        n, funcs = _page_table_maps(name)
        is_armed = _PAGE_SYM in _shapes(name).watched_symbols
        if n:
            counted.append(name)
            assert len(funcs) == 1, (
                f"{name} 的 pagetable.map 来自不止一个函数：{list(funcs)}。"
                f"两个粒度混进同一个指标，就是 #70 修掉的那个毛病")
            assert _PAGE_FUNC in funcs[0], (name, funcs)
        if is_armed:
            armed.append(name)
        if n and is_armed:
            armed_and_counted.append(name)

    assert sorted(counted) == sorted(armed), (
        f"有数的和挂上的对不上 —— 有数：{sorted(counted)}，挂上：{sorted(armed)}")
    assert armed_and_counted, "一趟 rcore 都没数出单 PTE，观察点是不是全掉了"



_IMAGE_LOADS = {
    "lab3-cowtest-mac":   (3,         3),
    "rcore-watchtest":    (2,         1),
}


def _image_loads(name: str) -> int:
    c = Counter(_kinds_of(name))
    return c["vm.from_elf"] or c["proc.exec"]


def test_execs_counts_image_loads_on_xv6_but_not_on_rcore():
    for name, (loads, execs) in _IMAGE_LOADS.items():
        if not (RUNS / name / "trace.nfb").is_file():
            pytest.skip(f"这台机器上没有 {name}")
        got = _image_loads(name)
        assert got == loads, f"{name} 装映像次数变了：{got} != {loads}"
        m = _shapes(name).metrics
        assert m.get("execs") == execs, (
            f"{name} 的 execs 变了：{m.get('execs')} != {execs}")


def test_rcore_loads_the_image_inside_the_create_body():
    name = "rcore-watchtest"
    if not (RUNS / name / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    ev = [(e.insn, e.kind) for e in A.analyze(RUNS / name).events
          if e.kind in ("vm.from_elf", "proc.create", "proc.exec")]
    seq = [k for _, k in ev]
    assert seq == ["proc.create", "vm.from_elf",
                   "proc.exec", "vm.from_elf"], seq
    for (i0, _), (i1, _) in ((ev[0], ev[1]), (ev[2], ev[3])):
        gap = i1 - i0
        assert 0 < gap < 200, (
            f"from_elf 离入口 {gap} 条指令 —— 太远了，可能不在同一个函数体里")


def test_execs_is_still_not_rendered_anywhere():
    js = (Path(__file__).resolve().parents[1] / "host/assets/app.js")
    if not js.is_file():
        pytest.skip("找不到 app.js")
    assert "execs" not in js.read_text(encoding="utf-8"), (
        "app.js 现在渲染 execs 了。先读 kinds.py 里 G 组的 consequence："
        "rCore 建任务时顺手装了一次映像，execs 没数它")



_INITPROC = {
    "lab3-cowtest-mac":  ("proc.alloc",    1_000),
    "rcore-watchtest":   ("proc.create",   2_000_000),
}


def test_both_kernels_name_the_first_user_process_the_same_way():
    for name in _INITPROC:
        if not (RUNS / name / "trace.nfb").is_file():
            pytest.skip(f"这台机器上没有 {name}")
        c = Counter(_kinds_of(name))
        assert c["proc.initproc"] == 1, (
            f"{name} 的 proc.initproc 有 {c['proc.initproc']} 条，应该正好 1")
        assert not any(k == "func.userinit" for k in _kinds_of(name)), (
            f"{name} 里又出现 func.userinit 了 —— xv6.toml 的映射掉了")


def test_the_two_initproc_watchpoints_are_in_phase():
    for name, (birth, limit) in _INITPROC.items():
        if not (RUNS / name / "trace.nfb").is_file():
            pytest.skip(f"这台机器上没有 {name}")
        ev = [(e.insn, e.kind) for e in A.analyze(RUNS / name).events
              if e.kind in ("proc.initproc", birth)]
        assert ev and ev[0][1] == "proc.initproc", (
            f"{name} 里 {birth} 出现在 proc.initproc 之前 —— 相位反了，"
            f"这个映射要重看：{ev[:3]}")
        after = [i for i, k in ev if k == birth]
        assert after, f"{name} 里 proc.initproc 之后没有 {birth}"
        gap = after[0] - ev[0][0]
        assert 0 < gap <= limit, (
            f"{name} 的 proc.initproc 到 {birth} 隔了 {gap} 条指令"
            f"（上限 {limit}）—— 中间夹了别的东西？")


_BLOCK_LAYERS = {
    "func.read_block":               515,   # os::drivers::block::virtio_blk::VirtIOBlock
    "func.get_block_cache":           97,   # easy_fs::block_cache
    "func.VirtIOBlk<H>::read_block":  33,
}


def test_the_rcore_block_layer_stays_unclassified_until_someone_explains_it():
    name = "rcore-watchtest"
    if not (RUNS / name / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    c = Counter(_kinds_of(name))
    for kind, want in _BLOCK_LAYERS.items():
        assert c[kind] == want, (
            f"{name} 的 {kind} 现在是 {c[kind]} 条，量的时候是 {want} 条。\n"
            f"如果是因为 rcore.toml 给它加了映射：先答 515/97/33 那个形状是"
            f"怎么回事，别让 disk.io 报出比驱动次数还多的磁盘 I/O。")
    assert c["disk.io"] == 0 and c["bcache.get"] == 0, (
        f"{name} 报出了 disk.io={c['disk.io']} / bcache.get={c['bcache.get']}。"
        f"映之前得先解释外层 515 比驱动 33 多一个数量级是怎么回事 —— "
        f"xv6 的命中率算法是 bread − disk_reads，映错方向会得到一个读得通的错数。")


def test_recorded_watchlists_only_name_words_the_registry_still_knows():
    seen: dict[str, list[str]] = {}
    for d in sorted(RUNS.iterdir()):
        wl = d / "watchlist.json"
        if not wl.is_file():
            continue
        import json
        for e in json.loads(wl.read_text(encoding="utf-8"))["entries"]:
            k = e.get("kind")
            if k:
                seen.setdefault(k, []).append(d.name)
    assert seen, "一个 run 的 watchlist 都没读到，这条测试就没在测东西"
    stray = {k: v for k, v in seen.items()
             if k not in K.KINDS and k not in K.RETIRED}
    assert not stray, (
        f"这些 kind 录在 watchlist 里，但 KINDS 和 RETIRED 里都没有：{stray}\n"
        f"改名了就去 kinds.RETIRED 记一笔（老名字 -> 改成谁、为什么）；"
        f"录制文件本身不要改，那是证据。")
    for old in K.RETIRED:
        assert old not in K.KINDS, (
            f"{old} 同时在 KINDS 和 RETIRED 里 —— 退休了就该从 KINDS 拿掉")


def test_the_old_page_fault_handler_name_left_no_stragglers():
    old, new = 0, 0
    for d in _corpus_run_dirs(RUNS):
        if not (d / "trace.nfb").is_file():
            continue
        c = Counter(_kinds_of(d.name))
        old += c["trap.pagefault"]
        new += c["trap.page_fault_handler"]
    assert old == 0, (
        f"老名字 `trap.pagefault` 还响了 {old} 次。它 2026-09-03 就改成 "
        f"`trap.page_fault_handler` 了（见 kinds.py 的 RETIRED）—— 有谁还在"
        f"报老名字，多半是某份 manifest 或者某段代码没跟着改。")
    assert new > 0, (
        "新名字 `trap.page_fault_handler` 全语料 0 次。上面那条老名字是 0 就"
        "不说明改名成功了，只说明这个观察点整个没响。去看 starry.toml 的 "
        "[event] 还在不在，以及录制时 watch 范围有没有覆盖到 task 那组。")
