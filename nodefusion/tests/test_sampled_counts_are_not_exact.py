
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.corpus

from conftest import RUNS, shapes  # noqa: E402
from nodefusion.host.analyze import Analysis as _An

A_METRIC_KINDS = _An._METRIC_KINDS
A_DERIVED_FROM = _An._DERIVED_FROM

SAMPLES = ["starry-showcase", "rcore-fs-alloc", "lab3-cowtest-mac"]


def _sampling(run: str) -> dict:
    m = shapes(run).metrics
    assert "sampling" in m, f"{run}: metrics() 里没有 sampling 这一格"
    return m["sampling"]



@pytest.mark.parametrize("run", SAMPLES)
def test_sampling_diagnostics_stay_out_of_the_metric_denominator(run):
    m = shapes(run).metrics
    assert isinstance(m["sampling"], dict)
    for leaked in ("watch_drops", "sampled_kinds", "sampled_metrics"):
        assert leaked not in m, (
            f"{run}: `{leaked}` 露到 metrics() 顶层了。"
            f"标量会进覆盖率分母，dict 会被别处当指标遍历 —— 都放 sampling 里。")



@pytest.mark.parametrize("run", SAMPLES)
def test_sampled_kinds_only_lists_kinds_that_actually_fired(run):
    m = shapes(run).metrics
    kinds = set(_sampling(run)["kinds"])
    fired = set(m["by_kind"])
    silent = set(m["armed_silent"])
    assert kinds <= fired, (
        f"{run}: 这些类别标了抽样却没响过 {sorted(kinds - fired)[:5]}")
    assert not (kinds & silent), (
        f"{run}: 这些类别同时在「挂了没响」和「抽样过」里 {sorted(kinds & silent)[:5]}")


@pytest.mark.parametrize("run", SAMPLES)
def test_sampled_metric_names_are_real_metrics(run):
    m = shapes(run).metrics
    smet = _sampling(run)["metrics"]
    for name, rates in smet.items():
        assert name in A_METRIC_KINDS, (
            f"{run}: `{name}` 不在 _METRIC_KINDS 里，卡片上没有这一格")
        assert name in m, f"{run}: `{name}` 不是 metrics() 里的键"
        assert rates and all(isinstance(r, int) for r in rates)
        assert any(r > 1 for r in rates), (
            f"{run}: `{name}` 标成抽样了，可 rate 全是 {rates} —— 那是全量")



def test_starry_phys_alloc_is_a_sampled_57_not_an_exact_one():
    s = _sampling("starry-showcase")
    assert s["kinds"].get("phys.alloc") == [256], (
        f"phys.alloc 的抽样率变了：{s['kinds'].get('phys.alloc')}")
    assert s["metrics"].get("kalloc") == [256]
    n = shapes("starry-showcase").metrics["kalloc"]
    assert 0 < n < 256, (
        f"kalloc 记了 {n} 条。这条见证假定它远小于抽样率 —— 数变大了就该"
        f"重新量一遍，顺手把上面那个 57～14592 的区间改掉。")


def test_a_run_without_throttling_has_an_empty_sampling_block():
    for run in ("rcore-fs-alloc", "lab3-cowtest-mac"):
        s = _sampling(run)
        assert s["kinds"] == {} and s["metrics"] == {}, (
            f"{run} 挂上限流了？{sorted(s['kinds'])[:5]}")


def test_drops_is_none_when_the_trace_never_recorded_it():
    vals = {run: _sampling(run)["drops"] for run in SAMPLES}
    assert vals["starry-showcase"] and vals["starry-showcase"] > 0, (
        f"starry-showcase 挂了 @r64/@r256 却说没丢：{vals['starry-showcase']}")
    for run, v in vals.items():
        assert v is None or isinstance(v, int), f"{run}: drops = {v!r}"


def test_a_derived_metric_whose_input_is_sampled_is_unknown_not_zero():
    m = shapes("starry-showcase").metrics
    kinds = _sampling("starry-showcase")["kinds"]
    assert "bcache.read" in kinds and "disk.io" in kinds, (
        "这条见证假定这两类都被抽样了，前提变了就该重新量")
    assert m["bcache_hits"] is None, f"bcache_hits = {m['bcache_hits']!r}，该是 None"
    assert m["bcache_hit_rate"] is None, (
        f"bcache_hit_rate = {m['bcache_hit_rate']!r}，该是 None —— "
        f"0.0 是在说'一次没命中'，那是编的")


def test_sampling_blocked_metrics_do_not_lower_the_ceiling():
    m = shapes("starry-showcase").metrics
    why = m["unobservable_reason"]
    total = int(re.search(r"本趟 (\d+) 项指标", why).group(1))
    observed = int(re.search(r"(\d+) 项有数", why).group(1))
    # A fully mapped manifest has no need to print a reduced ceiling at all;
    # in that case its ceiling is the total.  Older manifests with genuine
    # unreachable kinds still carry the explicit sentence.
    ceiling_match = re.search(r"最多只能有 (\d+) 项", why)
    ceiling = int(ceiling_match.group(1)) if ceiling_match else total
    unreachable = total - ceiling

    blocked = [k for k, v in m.items()
               if v is None and k in A_DERIVED_FROM]
    declared = {getattr(spec, "kind", spec) for spec in shapes(
        "starry-showcase").kevents.values()}
    watched = shapes("starry-showcase").watched_kinds
    unwatched = [name for name, kind in A_METRIC_KINDS.items()
                 if m.get(name) is None and kind in declared and kind not in watched]
    assert observed + unreachable + len(unwatched) + len(blocked) == total, (
        f"对不上：有数 {observed} + 够不着 {unreachable} + 已映射但旧录制没挂 "
        f"{len(unwatched)} + 抽样挡住 {len(blocked)} != {total}。"
        "有 None 没人解释。")
    assert "抽样记的" in why, f"理由栏没提抽样：{why}"


def test_the_runs_this_file_pins_are_still_here():
    missing = [r for r in SAMPLES if not (RUNS / r / "trace.nfb").exists()]
    assert not missing, f"这几趟不见了，见证失效：{missing}"
