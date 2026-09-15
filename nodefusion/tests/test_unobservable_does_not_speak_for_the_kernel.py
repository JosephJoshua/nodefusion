
from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.corpus

from nodefusion.host import analyze as A

RUNS = Path(__file__).resolve().parents[1] / "runs"
XV6, RCORE, ARCEOS = "lab3-cowtest-mac", "rcore-ch6-fs", "arceos-ctxsnap500"


from conftest import shapes as _shapes  # noqa: E402



def test_arceos_really_does_map_pages_in_this_run():
    sh = _shapes(ARCEOS)
    assert sh.kind_counts["vm.map"], "ArceOS 这趟没有 vm.map 事件，这份测试的前提没了"

    src = [fn for fn, s in sh.kevents.items()
           if getattr(s, "kind", s) == "vm.map"]
    assert src, "没有函数映射到 vm.map"
    assert any("map" in fn for fn in src), f"产生 vm.map 的函数不像映射：{src}"


def test_the_metric_is_still_blind_and_that_part_is_honest():
    m = _shapes(ARCEOS).metrics
    assert m.get("page_table_maps") is None, (
        f"ArceOS 报出了 page_table_maps={m.get('page_table_maps')}。它没有单 PTE "
        f"那一档的观察点，有数说明有人把区域级的 vm.map 又映回去了")
    assert m.get("vm_maps"), (
        f"ArceOS 的 vm_maps 是 {m.get('vm_maps')} —— 它明明有 vm.map 事件"
        f"（上一条测试钉着），指标却收不到，#70 那个洞回来了")



_OVERCLAIM = (
    "本内核没有声明",
    "内核在这件事上没词汇",
    "这个内核没有",
    "内核里没有这件事",
)


def test_the_reason_does_not_claim_the_kernel_lacks_the_capability():
    why = _shapes(ARCEOS).metrics.get("unobservable_reason") or ""
    assert "pagetable.map" in why, f"前提变了，这条该重写：{why}"
    for bad in _OVERCLAIM:
        assert bad not in why, f"又替内核下断言了（{bad!r}）：{why}"


def test_the_reason_says_it_is_talking_about_the_manifest():
    why = _shapes(ARCEOS).metrics.get("unobservable_reason") or ""
    assert "manifest" in why, why


def test_the_reason_admits_the_other_name_possibility():
    why = _shapes(ARCEOS).metrics.get("unobservable_reason") or ""
    assert "别的名字" in why or "另一个名字" in why, why


def test_the_same_wording_on_rcore():
    why = _shapes(RCORE).metrics.get("unobservable_reason") or ""
    assert "vm.unmap" in why, why
    for bad in _OVERCLAIM:
        assert bad not in why, f"{bad!r} 出现在 rCore 的理由里：{why}"



_BRANCHES = {
    "unwatched":   "没挂上观测点",
    "unknown":     "没有任何函数映射过来",
    "feature":     "这些事本内核没有",
    "granularity": "没有粒度对得上的函数可挂",
}


def test_the_reason_branches_are_still_told_apart():
    rcore = _shapes("rcore-filetest").metrics.get("unobservable_reason") or ""
    for tag in ("unwatched", "feature"):
        assert _BRANCHES[tag] in rcore, f"rCore 少了 {tag} 那一支：{rcore}"
    assert "vm.unmap" in rcore and "对应函数不在本次 ELF" in rcore, rcore
    assert _BRANCHES["granularity"] not in rcore, rcore
    assert _BRANCHES["unknown"] not in rcore, (
        f"rCore 的两个类别都声明过了，不该再说「没有函数映射过来」：{rcore}")

    segs = [s for s in rcore.split("；") if "本趟" not in s and "最多只能有" not in s]
    assert len(segs) == 3, f"rCore 该有三段理由，实际 {len(segs)} 段：{segs}"
    for tag in ("unwatched", "feature"):
        hit = [s for s in segs if _BRANCHES[tag] in s]
        assert len(hit) == 1, f"{tag} 落在 {len(hit)} 段里：{segs}"

    arceos = _shapes(ARCEOS).metrics.get("unobservable_reason") or ""
    assert _BRANCHES["unknown"] in arceos, (
        f"ArceOS 十个类别没映也没声明，这一支不该消失：{arceos}")
    for tag in ("feature", "granularity"):
        assert _BRANCHES[tag] not in arceos, (
            f"ArceOS 的 manifest 里没有 [absent]，不该出现「声明过」的说法："
            f"{arceos}")


def test_a_declared_absence_is_not_also_reported_as_unmapped():
    _m = _shapes(RCORE).metrics
    why = _m.get("unobservable_reason") or ""
    declared = set(_m.get("absent_declared") or {})
    assert declared, "rCore 的 [absent] 空了，这条测不到东西"
    unknown_seg = [s for s in why.split("；") if _BRANCHES["unknown"] in s]
    for kind in declared:
        for seg in unknown_seg:
            assert kind not in seg, (
                f"{kind} 既声明过又被算进「没映射」：{seg}")


def test_xv6_explains_exactly_one_thing_and_explains_it_honestly():
    why = _shapes(XV6).metrics.get("unobservable_reason") or ""
    assert why, "xv6 的理由栏又是 None 了 —— page_table_maps 有值了？"
    assert "pagetable.map" in why, why
    for phrase in _OVERCLAIM:
        assert phrase not in why, (
            f"对 xv6 也说过头了：出现了「{phrase}」。它循环里每页写一个 PTE，"
            f"只是没在那一层挂观察点\n{why}")



def _coverage(why: str) -> tuple[int, int, int]:
    m = re.search(r"本趟 (\d+) 项指标里 (\d+) 项有数", why)
    assert m, f"理由栏开头没有那句分母：{why[:120]}"
    total, observed = int(m.group(1)), int(m.group(2))
    c = re.search(r"最多只能有 (\d+) 项", why)
    return total, observed, int(c.group(1)) if c else total


@pytest.mark.parametrize("run", [XV6, RCORE, ARCEOS])
def test_the_reason_opens_with_a_denominator_that_matches_the_data(run):
    m = _shapes(run).metrics
    why = m.get("unobservable_reason") or ""
    total, observed, ceiling = _coverage(why)

    scalar = {k: v for k, v in m.items()
              if v is None or isinstance(v, (int, float)) and not isinstance(v, bool)}
    assert total == len(scalar), (total, sorted(scalar))
    assert observed == sum(1 for v in scalar.values() if v is not None)
    assert observed <= ceiling <= total, (observed, ceiling, total)


def test_the_denominator_is_the_manifests_ceiling_not_the_kernels():
    for run in (XV6, RCORE, ARCEOS):
        why = _shapes(run).metrics.get("unobservable_reason") or ""
        if "最多只能有" not in why:
            continue
        assert "按这份 manifest" in why, (
            f"{run} 报了上限却没说这是 manifest 的上限：{why[:160]}")
        for bad in _OVERCLAIM:
            assert bad not in why, f"{run} 的分母句里说过头了（{bad!r}）：{why}"


def test_a_kernel_at_its_own_ceiling_reads_as_full_not_as_missing_two():
    for run in ("lab3-cowtest-mac", "rcore-forktest-inline"):
        d = RUNS / run
        if not (d / "trace.nfb").is_file():
            pytest.skip(f"这台机器上没有 {run}")
        _, observed, ceiling = _coverage(
            _shapes(run).metrics.get("unobservable_reason") or "")
        assert observed == ceiling, (
            f"{run}: 有数 {observed}、上限 {ceiling}。要么真多观测到了东西"
            f"（好事，把这条改了），要么掉了一项（该查是谁掉的）")


@pytest.mark.parametrize("run", [XV6, RCORE, ARCEOS])
def test_a_derived_metric_is_none_whenever_any_input_is_out_of_reach(run):
    sh = _shapes(run)
    m = sh.metrics
    inv = set()
    for name, spec in sh.kevents.items():
        inv.add(getattr(spec, "kind", spec))
    for metric, deps in A.Analysis._DERIVED_FROM.items():
        missing = [k for k in deps if k not in inv]
        if not missing:
            continue
        assert m.get(metric) is None, (
            f"{run}: {metric} 有值 {m.get(metric)!r}，可它依赖的 {missing} "
            f"这份 manifest 里没有函数映过来。要么算式变了、要么这张表过期了")


def test_the_ceiling_subtracts_derived_metrics_too():
    d = RUNS / ARCEOS
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {ARCEOS}")
    m = _shapes(ARCEOS).metrics
    _, observed, ceiling = _coverage(m.get("unobservable_reason") or "")
    assert m["bcache_hits"] is None and m["bcache_hit_rate"] is None, (
        "前提变了：ArceOS 现在能算块缓存命中了，这条测试得重写")
    assert observed == ceiling, (
        f"ArceOS 有数 {observed}、上限 {ceiling}。它挂满了观察点，差的那几项"
        f"都是 manifest 没映 —— 顶格才对")
