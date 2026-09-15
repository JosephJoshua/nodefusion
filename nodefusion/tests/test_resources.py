
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                # noqa: E402

from nodefusion.host import resources as R                   # noqa: E402
from nodefusion.model.manifest import (                      # noqa: E402
    ColumnSpec, EntitySpec, Manifest, TableSpec)
from nodefusion.model.probe import (                         # noqa: E402
    ABSENT, PRESENT, UNDECODABLE, ProbeResult, ResolvedEntity, ResolvedField)
from nodefusion.model.rt import Unavailable                  # noqa: E402
from nodefusion.model.snapshot import (                      # noqa: E402
    Entity, EntitySet, Field, Snapshot)

BASE = 0x8000_0000


def _spec(*, columns=None, liveness=None, show_when_any=(), empty="",
          fields=("ref",)) -> EntitySpec:
    cols = columns if columns is not None else [
        ColumnSpec("slot", "槽位", synthetic=True),
        ColumnSpec("ref", "引用数")]
    return EntitySpec(
        name="t", type="e", label="表", liveness=liveness,
        table=TableSpec(columns=cols, show_when_any=list(show_when_any),
                        empty_text=empty))


def _probe(present=("ref",), *, absent=(), undecodable=(), optional=()
           ) -> ProbeResult:
    fs = [ResolvedField(name=n, path=n, reader="i32", state=PRESENT)
          for n in present]
    fs += [ResolvedField(name=n, path=n, reader="i32", state=ABSENT,
                         reason=f"这个内核里没有 e.{n}",
                         optional=(n in optional)) for n in absent]
    fs += [ResolvedField(name=n, path=n, reader="i32", state=UNDECODABLE,
                         reason=f"字段 {n!r} 的 reader 造不出来",
                         optional=(n in optional)) for n in undecodable]
    return ProbeResult(kernel="k", arch="riscv64",
                       entities=[ResolvedEntity(name="t", type="e",
                                                struct_path="e", fields=fs)])


def _snap(values: list[dict], *, unavailable=None) -> Snapshot:
    ents = []
    for i, vals in enumerate(values):
        e = Entity(kind="t", addr=BASE + i * 16)
        for k, v in vals.items():
            e.fields[k] = (Field(name=k, state=UNDECODABLE, reason="读不到")
                           if v is None else
                           Field(name=k, state=PRESENT, value=v))
        ents.append(e)
    es = EntitySet(kind="t", entities=ents, completeness="total")
    es.unavailable = unavailable
    return Snapshot(sets={"t": es})


def _table(spec=None, res=None, snap=None):
    return R.table_of(spec or _spec(), res or _probe(),
                      snap if snap is not None else _snap([{"ref": 1}]))



def test_a_set_that_never_got_built_is_not_an_empty_table():
    t = _table(snap=_snap([], unavailable="内核里没有符号 'tbl'"))
    assert not t.available and "tbl" in t.reason and not t.rows


def test_a_missing_snapshot_is_reported_not_defaulted():
    t = _table(snap=Snapshot(sets={}))
    assert not t.available and "t" in t.reason


def test_unavailable_tables_carry_no_rows_and_no_columns():
    t = _table(snap=_snap([], unavailable="走不到"))
    assert not t.available and t.rows == [] and t.columns == []


def test_walk_problems_with_no_entities_is_a_refusal_not_an_empty_table():
    snap = _snap([], unavailable=None)
    snap.sets["t"].problems = [Unavailable("Once 的状态是 Incomplete")]
    t = _table(snap=snap)
    assert not t.available
    assert "Incomplete" in t.reason
    assert t.rows == []


def test_rows_that_did_come_back_survive_but_stop_claiming_completeness():
    snap = _snap([{"ref": 1}, {"ref": 2}])
    snap.sets["t"].problems = [Unavailable("第 3 格读不出来")]
    t = _table(snap=snap)
    assert t.available and len(t.rows) == 2
    assert any("第 3 格读不出来" in n for n in t.notes)


def test_the_same_reason_sixteen_times_collapses_but_the_count_does_not():
    snap = _snap([{"ref": 1}])
    snap.sets["t"].problems = [Unavailable("同一层壳解不开") for _ in range(16)]
    t = _table(snap=snap)
    note = "".join(t.notes)
    assert note.count("同一层壳解不开") == 1
    assert "16" in note



def test_missing_required_column_fails_the_whole_table():
    t = _table(res=_probe(present=(), absent=("ref",)))
    assert not t.available and "引用数" in t.reason and "ref" in t.reason


def test_a_field_the_reader_could_not_be_built_for_also_fails_the_table():
    t = _table(res=_probe(present=(), undecodable=("ref",)))
    assert not t.available and "reader" in t.reason


def test_missing_optional_column_drops_the_column_and_says_so():
    spec = _spec(columns=[ColumnSpec("slot", "槽位", synthetic=True),
                          ColumnSpec("ref", "引用数"),
                          ColumnSpec("extra", "附加", optional=True)])
    t = R.table_of(spec, _probe(present=("ref",), absent=("extra",)),
                   _snap([{"ref": 1}]))
    assert t.available, t.reason
    assert "extra" not in t.rows[0], "缺的列不该出现在行里"
    assert t.notes and "附加" in t.notes[0], (
        "默默少一列会被当成这个内核就没这项")


def test_a_field_declared_optional_makes_its_column_optional_too():
    spec = _spec(columns=[ColumnSpec("ref", "引用数"),
                          ColumnSpec("extra", "附加")])
    t = R.table_of(spec, _probe(present=("ref",), absent=("extra",),
                                optional=("extra",)), _snap([{"ref": 1}]))
    assert t.available, t.reason
    assert t.notes and "附加" in t.notes[0]


def test_column_order_is_the_manifest_order():
    spec = _spec(columns=[ColumnSpec("ref", "引用数"),
                          ColumnSpec("slot", "槽位", synthetic=True)])
    t = R.table_of(spec, _probe(), _snap([{"ref": 1}]))
    assert [c["key"] for c in t.columns] == ["ref", "slot"]



def test_liveness_drops_rows_at_decode_time():
    spec = _spec(liveness={"skip_when": {"field": "ref", "equals": 0}})
    t = R.table_of(spec, _probe(),
                   _snap([{"ref": 1}, {"ref": 0}, {"ref": 3}]))
    assert [x["slot"] for x in t.rows] == [0, 2], "ref==0 的表项不该出现"


def test_slot_is_the_enumeration_index_not_the_row_number():
    spec = _spec(liveness={"skip_when": {"field": "ref", "equals": 0}})
    t = R.table_of(spec, _probe(), _snap([{"ref": 0}, {"ref": 2}, {"ref": 3}]))
    assert [x["slot"] for x in t.rows] == [1, 2]


def test_no_liveness_means_every_slot_is_a_row():
    t = _table(snap=_snap([{"ref": 0}, {"ref": 0}]))
    assert len(t.rows) == 2


def test_a_cell_we_could_not_read_is_none_not_zero():
    t = _table(snap=_snap([{"ref": None}]))
    assert t.available and t.rows[0]["ref"] is None



def test_enum_maps_by_index_and_marks_the_unknown():
    spec = _spec(columns=[ColumnSpec(
        "type", "类型", format="enum",
        values=["NONE", "PIPE", "INODE", "DEVICE"])])
    t = R.table_of(spec, _probe(present=("type",)),
                   _snap([{"type": 2}, {"type": 9}, {"type": 0}]))
    assert [x["type"] for x in t.rows] == ["INODE", "?9", "NONE"], (
        "认不出的数值要原样带出来，不能留空 —— 留空会被读成没读到")


def test_show_when_any_and_empty_text_reach_the_ui():
    spec = _spec(show_when_any=["ref"], empty="当前没有打开的文件。")
    t = R.table_of(spec, _probe(), _snap([]))
    assert t.available and t.rows == []
    assert t.show_when_any == ["ref"]
    assert t.empty_text == "当前没有打开的文件。", (
        "空表时说什么是内核语义，不是通用的「暂无数据」")


def test_from_entities_only_makes_tables_for_entities_that_asked_for_one():
    m = Manifest(name="k", entities=[
        EntitySpec(name="task", type="proc"),
        _spec()])
    got = R.from_entities(m, _probe(), _snap([{"ref": 1}]))
    assert [t.name for t in got] == ["t"]


def test_from_entities_omits_a_guarded_table_that_does_not_apply():
    """A false shape predicate is structural absence, not a decode failure."""
    from nodefusion.model.manifest import SourceSpec
    from nodefusion.model.probe import ResolvedEntity

    spec = _spec()
    spec.sources = [SourceSpec(kind="table", completeness="total",
                               when={"type_exists": "OnlyInLaterChapter"})]
    m = Manifest(name="k", entities=[spec])
    res = _probe()
    res.entities = [ResolvedEntity(name=spec.name, type=spec.type, sources=[])]
    assert R.from_entities(m, res, _snap([])) == []



_BASE_TOML = """
[kernel]
name = "k"

[[entity]]
name = "t"
type = "e"
%s

[entity.fields]
ref = { path = "ref", reader = "i32" }

[entity.table]
%s

  [[entity.table.column]]
  key = "%s"
%s
"""


def _load(tmp_path, ent_extra="", table_extra="", col_key="ref", col_extra=""):
    from nodefusion.model import manifest as M
    p = tmp_path / "k.toml"
    p.write_text(_BASE_TOML % (ent_extra, table_extra, col_key, col_extra),
                 encoding="utf-8")
    return M.load(p)


def test_a_clean_manifest_still_loads(tmp_path):
    m = _load(tmp_path)
    assert [c.key for c in m.entities[0].table.columns] == ["ref"]


def test_typo_in_a_table_key_is_an_error_not_a_silent_drop(tmp_path):
    from nodefusion.model.manifest import ManifestError
    with pytest.raises(ManifestError) as ei:
        _load(tmp_path, table_extra='show_when_an = ["ref"]')
    msg = str(ei.value)
    assert "show_when_an" in msg and "show_when_any" in msg


def test_typo_in_a_column_key_is_an_error(tmp_path):
    from nodefusion.model.manifest import ManifestError
    with pytest.raises(ManifestError) as ei:
        _load(tmp_path, col_extra='  lable = "引用数"')
    assert "lable" in str(ei.value) and "label" in str(ei.value)


def test_a_column_naming_no_declared_field_is_an_error(tmp_path):
    from nodefusion.model.manifest import ManifestError
    with pytest.raises(ManifestError) as ei:
        _load(tmp_path, col_key="reff")
    msg = str(ei.value)
    assert "reff" in msg and "ref" in msg


def test_read_options_cannot_be_restated_on_a_column(tmp_path):
    from nodefusion.model.manifest import ManifestError
    with pytest.raises(ManifestError) as ei:
        _load(tmp_path, col_extra='  reader = "u64"')
    assert "reader" in str(ei.value)


def test_a_not_yet_supported_entity_key_is_refused_rather_than_ignored(
        tmp_path):
    from nodefusion.model.manifest import ManifestError
    with pytest.raises(ManifestError) as ei:
        _load(tmp_path, ent_extra='via = ["Lazy", "Mutex"]')
    assert "via" in str(ei.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
