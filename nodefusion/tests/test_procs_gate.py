
from __future__ import annotations

import pytest

from nodefusion.host import guest as G


class _Spec:
    def __init__(self, name: str) -> None:
        self.name = name


class _M:

    def __init__(self, spec: _Spec | None) -> None:
        self._spec = spec
        self.entities: list = []

    def entity_for(self, role: str, fallback: str | None = None):
        return self._spec


class _Entities:

    def __init__(self, spec: _Spec | None, *, compiled: bool = True,
                 why: str = "") -> None:
        self.m = _M(spec)
        self._compiled, self._why = compiled, why

    def compiled(self, name: str) -> bool:
        return self._compiled

    def entity_for(self, role: str, fallback: str | None = None):
        return self.m.entity_for(role, fallback=fallback)

    def why_not(self, name: str) -> str:
        return self._why


def _dec(entities) -> G.GuestDecoder:
    d = object.__new__(G.GuestDecoder)
    d.entities = entities
    d.is_rcore = False
    return d



def test_a_manifest_with_a_process_entity_opens_the_gate():
    ok, why = _dec(_Entities(_Spec("task")))._check_manifest_procs()
    assert ok and why == ""


def test_the_gate_is_taken_when_the_manifest_declares_one():
    assert _dec(_Entities(_Spec("task")))._has_manifest_procs() is True


def test_role_process_wins_over_the_name():
    assert _dec(_Entities(_Spec("process")))._has_manifest_procs() is True



def test_no_process_entity_means_the_old_paths_still_decide():
    assert _dec(_Entities(None))._has_manifest_procs() is False


def test_a_decoder_without_entities_does_not_crash():
    assert _dec(None)._has_manifest_procs() is False



def test_a_plan_that_does_not_compile_is_refused():
    ok, _ = _dec(_Entities(_Spec("task"), compiled=False))._check_manifest_procs()
    assert ok is False


def test_the_reason_comes_from_the_model_layer():
    _, why = _dec(_Entities(_Spec("task"), compiled=False,
                            why="找不到静态符号 'IDLE_TASK'"))._check_manifest_procs()
    assert "IDLE_TASK" in why
    assert "proc 符号" not in why


def test_the_reason_names_the_entity_that_failed():
    _, why = _dec(_Entities(_Spec("task"), compiled=False))._check_manifest_procs()
    assert "task" in why


def test_a_missing_reason_still_produces_a_sentence():
    _, why = _dec(_Entities(_Spec("task"), compiled=False))._check_manifest_procs()
    assert why and why.strip().endswith(("。", "："))



def test_the_builder_answers_before_a_snapshot_is_built():
    from nodefusion.model.snapshot import SnapshotBuilder
    b = object.__new__(SnapshotBuilder)
    b._plans, b._why = {"task": object()}, {}
    assert b.compiled("task") is True
    assert b.why_not("task") == ""


def test_an_unknown_entity_is_not_compiled():
    from nodefusion.model.snapshot import SnapshotBuilder
    b = object.__new__(SnapshotBuilder)
    b._plans, b._why = {}, {}
    assert b.compiled("nope") is False


def test_the_builder_selects_the_process_shape_that_compiled():
    """Two role declarations can be structural alternatives, not ambiguity."""
    from nodefusion.model.manifest import EntitySpec, Manifest
    from nodefusion.model.snapshot import SnapshotBuilder

    b = object.__new__(SnapshotBuilder)
    b.m = Manifest(name="t", entities=[
        EntitySpec(name="process", type="P", role="process"),
        EntitySpec(name="task", type="T", role="process"),
    ])
    b._plans = {"process": [], "task": [object()]}
    assert b.entity_for("process").name == "task"


def test_the_builder_keeps_a_failed_candidate_for_diagnostics():
    from nodefusion.model.manifest import EntitySpec, Manifest
    from nodefusion.model.snapshot import SnapshotBuilder

    b = object.__new__(SnapshotBuilder)
    b.m = Manifest(name="t", entities=[
        EntitySpec(name="process", type="P", role="process"),
        EntitySpec(name="task", type="T", role="process"),
    ])
    b._plans = {"process": [], "task": []}
    assert b.entity_for("process").name == "process"



@pytest.mark.corpus
@pytest.mark.parametrize("name,want", [("rcore-ch6-fs", 18),
                                       ("rcore-watchtest", 60),
                                       ("lab3-cowtest-mac", 383)])
def test_the_runs_that_used_to_decode_still_decode(name, want):
    from pathlib import Path

    from nodefusion.host import analyze as A

    d = Path(__file__).resolve().parents[1] / "runs" / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    a = A.analyze(d)
    assert sum(len(s.procs) for s in a.states) == want
