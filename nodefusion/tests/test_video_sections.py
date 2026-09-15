
from __future__ import annotations

import json

import pytest

from nodefusion.host import video as V


def _info(*kinds: str) -> dict:
    return {"kinds": list(kinds)}



def test_subsystems_come_from_the_kind_namespace():
    assert V.subsystems(_info("vm.copy", "vm.map", "phys.free", "sched.switch")) \
        == ["phys", "sched", "vm"]


def test_a_kind_without_a_dot_is_not_a_subsystem():
    assert V.subsystems(_info("panic", "vm.copy")) == ["vm"]


def test_evidence_fields_are_derived_for_the_requested_scope():
    info = {
        "observed_fields": {
            "process": ["pid", "state"],
            "resources": ["thread.id", "thread.name"],
            "events": {"disk": ["block", "operation"], "sched": ["to_ctx"]},
        },
    }
    assert V.evidence_fields(info, "disk") == [
        "block", "operation", "thread.id", "thread.name"]
    assert V.evidence_fields(info, "sched") == ["to_ctx", "pid", "state"]
    assert V.evidence_fields(info, "thread") == [
        "pid", "state", "thread.id", "thread.name"]


def test_evidence_fields_are_bounded_but_report_omissions():
    info = {"observed_fields": {"events": {"vm": [f"f{i}" for i in range(20)]}}}
    got = V.evidence_fields(info, "vm", limit=3)
    assert got == ["f0", "f1", "f2", "+17 more"]


def test_evidence_fields_name_the_generic_event_columns_when_no_schema_exists():
    assert V.evidence_fields({}, None) == [
        "event.kind", "event.count", "event.timestamp"]


def test_the_unclassified_fallback_still_shows_up_in_the_list():
    assert V.UNCLASSIFIED in V.subsystems(_info("func.kalloc", "vm.copy"))



def test_a_subsystem_board_only_stops_on_its_own_kinds():
    board = V.build_subsystem_storyboard(
        _info("vm.copy", "vm.map", "phys.free", "sched.switch"), 24, "vm")
    stops = [s.meta["kind"] for s in board if "kind" in s.meta]
    assert stops == ["vm.copy", "vm.map"]


def test_it_opens_on_the_view_that_shows_that_subsystem():
    def tab_of(prefix, *kinds):
        b = V.build_subsystem_storyboard(_info(*kinds), 24, prefix)
        return b[1].setup
    assert "'phys'" in tab_of("phys", "phys.free")
    assert "'vm'" in tab_of("pagetable", "pagetable.map")
    assert "'procs'" in tab_of("sched", "sched.switch")


def test_an_unmapped_subsystem_falls_back_to_the_event_list():
    b = V.build_subsystem_storyboard(_info("syscall.write"), 24, "syscall")
    assert "'events'" in b[1].setup


def test_asking_for_a_subsystem_that_is_not_there_says_what_is():
    with pytest.raises(V.VideoError) as e:
        V.build_subsystem_storyboard(_info("vm.copy", "phys.free"), 24, "fs")
    assert "phys" in str(e.value) and "vm" in str(e.value)


def test_a_long_subsystem_does_not_become_an_endless_video():
    many = _info(*[f"syscall.s{i}" for i in range(30)])
    stops = [s for s in V.build_subsystem_storyboard(many, 24, "syscall")
             if "kind" in s.meta]
    assert len(stops) == 12


def test_every_shot_asks_for_at_least_one_frame():
    b = V.build_subsystem_storyboard(_info("vm.copy"), 1, "vm")
    assert b, "分镜是空的，下面那句 all() 就成了空转"
    assert all(s.frames >= 1 for s in b)



def test_the_section_flag_can_repeat():
    from nodefusion.host import cli
    a = cli.build_parser().parse_args(
        ["video", "--run", "r", "--section", "vm", "--section", "phys"])
    assert a.section == ["vm", "phys"]


def test_without_the_flag_nothing_changes():
    from nodefusion.host import cli
    assert cli.build_parser().parse_args(["video", "--run", "r"]).section is None


def test_make_video_can_take_a_storyboard():
    import inspect
    assert "storyboard" in inspect.signature(V.make_video).parameters
    assert "evidence_scope" in inspect.signature(V.make_video).parameters


def test_evidence_sidecar_is_portable_and_keeps_the_video_digest(tmp_path):
    result = {
        "html": "/private/run/demo.html",
        "mp4": "/private/run/demo.mp4",
        "mp4_sha256": "a" * 64,
        "info": {"runs": ["demo"]},
    }
    out = V.write_evidence_sidecar(result, tmp_path / "demo.json")
    payload = json.loads(out.read_text())

    assert payload["format"] == "nodefusion.video-evidence/1"
    assert payload["html"] == "demo.html"
    assert payload["mp4"] == "demo.mp4"
    assert payload["mp4_sha256"] == "a" * 64
    assert "/private/" not in out.read_text()



def test_no_storyboard_means_the_default_one():
    b = V.resolve_storyboard(None, _info("vm.copy"), 24)
    assert b and b[0].label == "概览"


def test_a_factory_gets_the_run_info():
    seen = {}

    def factory(info, fps):
        seen.update(info=info, fps=fps)
        return [V.Shot("x", 1)]

    out = V.resolve_storyboard(factory, _info("vm.copy"), 24)
    assert seen["fps"] == 24 and seen["info"]["kinds"] == ["vm.copy"]
    assert [s.label for s in out] == ["x"]


def test_a_ready_made_list_is_used_as_is():
    shots = [V.Shot("只有这一镜", 3)]
    assert V.resolve_storyboard(shots, _info("vm.copy"), 24) == shots
