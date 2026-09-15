
from __future__ import annotations

import pytest

from nodefusion.host import layout as L


def test_a_manifest_kernel_gets_an_empty_layout_not_an_error(tmp_path):
    lay = L.probe(tmp_path, sh=None, kind="arceos")
    assert lay.kind == "arceos"
    assert lay.offsets == {} and lay.sizes == {}


def test_the_empty_layout_says_why_it_is_empty(tmp_path):
    note = L.probe(tmp_path, sh=None, kind="arceos").notes["_manifest_layout"]
    assert "没有探测失败" in note
    assert "DWARF" in note and "model/probe.py" in note


def test_missing_offsets_are_not_silently_invented(tmp_path):
    lay = L.probe(tmp_path, sh=None, kind="arceos")
    with pytest.raises(L.LayoutError):
        lay.off("proc.pid")


def test_an_unknown_kind_still_raises(tmp_path):
    with pytest.raises(L.LayoutError) as e:
        L.probe(tmp_path, sh=None, kind="something-else")
    assert "认不出" in str(e.value)


def test_the_error_names_the_kernels_that_do_have_manifests(tmp_path):
    with pytest.raises(L.LayoutError) as e:
        L.probe(tmp_path, sh=None, kind="something-else")
    assert "arceos" in str(e.value)


def test_the_caller_supplied_kind_wins_over_sniffing(tmp_path):
    (tmp_path / "kernel").mkdir()
    (tmp_path / "kernel" / "proc.h").write_text("", encoding="utf-8")
    (tmp_path / "kernel" / "param.h").write_text("", encoding="utf-8")
    assert L.detect_kernel(tmp_path) == "xv6"
    assert L.probe(tmp_path, sh=None, kind="arceos").kind == "arceos"


def test_without_a_kind_it_still_sniffs(tmp_path):
    with pytest.raises(L.LayoutError):
        L.probe(tmp_path, sh=None)


def test_an_override_still_wins_over_everything(tmp_path):
    p = tmp_path / "lay.json"
    L.save(L.KernelLayout(offsets={"proc.pid": 8}, kind="xv6"), p)
    lay = L.probe(tmp_path, sh=None, kind="arceos", override=p)
    assert lay.off("proc.pid") == 8
    assert "_override" in lay.notes
