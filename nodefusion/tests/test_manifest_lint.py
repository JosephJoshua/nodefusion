
import pytest

from nodefusion.model import manifest as M
from nodefusion.model.manifest import (EntitySpec, Manifest, WatchSpec,
                                       _fields)


def _w(sub: str, match: dict) -> WatchSpec:
    return WatchSpec(subsystem=sub, match=match)


def _m(*, watches=(), entities=(), detect=None) -> Manifest:
    return Manifest(name="k", family="k", arches=["riscv64"],
                    detect=detect or {}, entities=list(entities),
                    watches=list(watches))



def test_a_broad_module_rule_kills_a_narrower_one_after_it():
    out = M.lint(_m(watches=[
        _w("axvm", {"module": "axvm"}),
        _w("vmexit", {"module": "axvm::vcpu", "fn": ["*exit*"]}),
    ]))
    assert len(out) == 1
    assert "vmexit" in out[0] and "轮不到" in out[0]


def test_the_same_two_rules_in_the_right_order_are_fine():
    assert M.lint(_m(watches=[
        _w("vmexit", {"module": "axvm::vcpu", "fn": ["*exit*"]}),
        _w("axvm", {"module": "axvm"}),
    ])) == []


def test_a_shadower_that_has_its_own_fn_filter_is_not_counted():
    assert M.lint(_m(watches=[
        _w("sched", {"module": "axcpu", "fn": ["context_switch"]}),
        _w("trap", {"module": "axcpu"}),
    ])) == []


def test_sibling_modules_do_not_shadow_each_other():
    assert M.lint(_m(watches=[
        _w("a", {"module": "mem"}),
        _w("b", {"module": "memory"}),
    ])) == []


def test_a_rule_is_dead_only_if_every_one_of_its_modules_is_covered():
    assert M.lint(_m(watches=[
        _w("a", {"module": "kernel::fs"}),
        _w("b", {"module": ["kernel::fs::inode", "kernel::net"]}),
    ])) == []



def test_a_bare_type_beside_a_qualified_one_is_flagged():
    out = M.lint(_m(
        detect={"any_type": ["axvm::vm::AxVM"]},
        entities=[EntitySpec(name="vm", type="AxVM")]))
    assert len(out) == 1 and "AxVM" in out[0]


def test_a_bare_type_with_no_qualified_twin_is_left_alone():
    assert M.lint(_m(entities=[EntitySpec(name="task", type="tcb_t")])) == []


def test_matching_only_on_the_last_segment_not_a_substring():
    assert M.lint(_m(
        detect={"any_type": ["os::task::task::TaskControlBlock"]},
        entities=[EntitySpec(name="t", type="Task")])) == []



def test_links_to_a_kind_that_was_never_declared_is_flagged():
    out = M.lint(_m(entities=[
        EntitySpec(name="thread", type="T", relations=_fields(
            {"process": {"path": "task_ext", "links_to": "proces"}},
            optional=False)),
        EntitySpec(name="process", type="P"),
    ]))
    assert len(out) == 1
    assert "proces" in out[0] and "process" in out[0]


def test_links_to_a_declared_kind_is_fine():
    assert M.lint(_m(entities=[
        EntitySpec(name="thread", type="T", relations=_fields(
            {"process": {"path": "task_ext", "links_to": "process"}},
            optional=False)),
        EntitySpec(name="process", type="P"),
    ])) == []



def test_every_shipped_manifest_is_clean():
    bad = []
    for name, man in M.load_dir(M.builtin_dir()).items():
        bad += M.lint(man)
    assert bad == [], "\n".join(bad)




import re
from pathlib import Path

_MANIFESTS = Path(__file__).resolve().parents[1] / "manifests"

_REF = re.compile(r"(原\s*)?UNRESOLVED\s*([A-Z])\s*组")


def test_manifest_comments_do_not_point_at_a_resolved_group():
    from nodefusion.model import kinds as K
    live = {g["group"].split()[0] for g in K.UNRESOLVED}
    stale = []
    for f in sorted(_MANIFESTS.glob("*.toml")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for was_former, letter in _REF.findall(line):
                if was_former or letter in live:
                    continue
                stale.append(f"{f.name}:{i}: {line.strip()}")
    assert not stale, (
        "这些注释指着 UNRESOLVED 里已经没有的组。裁决的结论在 kinds.py 的 "
        "RESOLVED_DISTINCT 里 —— 把注释改成指那儿，并且核对一下它顺带说的"
        "结论有没有被裁决推翻：\n  " + "\n  ".join(stale))
