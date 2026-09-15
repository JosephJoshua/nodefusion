
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from nodefusion.host import analyze as A
from nodefusion.model.manifest import ManifestError, load, load_dir
from nodefusion.model.snapshot import _completeness

REPO = Path(__file__).resolve().parents[2]
MANI = REPO / "nodefusion" / "manifests"
RUNS = Path(__file__).resolve().parents[1] / "runs"
MDIR = MANI


class _Src:

    def __init__(self, completeness: str, reason: str | None = None) -> None:
        self.completeness, self.reason = completeness, reason


# ------------------------------------------------------------------ manifest

def test_the_default_is_first_so_nothing_changes_by_accident():
    for f in sorted(MDIR.glob("*.toml")):
        raw = tomllib.loads(f.read_text(encoding="utf-8"))
        declared = {e.get("name") for e in raw.get("entity", [])
                    if "source_combine" in e}
        for e in load(f).entities:
            if e.name in declared:
                continue
            assert e.source_combine == "first", f"{f.name}:{e.name}"


def test_every_declared_combine_is_a_word_the_code_knows():
    known = {"first", "union"}
    seen = 0
    for f in sorted(MDIR.glob("*.toml")):
        raw = tomllib.loads(f.read_text(encoding="utf-8"))
        for e in raw.get("entity", []):
            if "source_combine" in e:
                seen += 1
                assert e["source_combine"] in known, (
                    f"{f.name}:{e.get('name')} 写了 "
                    f"{e['source_combine']!r}，认得的只有 {sorted(known)}")
    assert seen, "一个都没有的话这条测试什么也没验证"


def test_starry_thread_declares_union():
    ent = [e for e in load(MDIR / "starry.toml").entities
           if e.name == "thread"][0]
    assert ent.source_combine == "union"
    assert len(ent.sources) == 3


def test_arceos_task_declares_union():
    ent = [e for e in load(MDIR / "arceos.toml").entities if e.name == "task"][0]
    assert ent.source_combine == "union"
    # Three complementary roles, with measured FIFO/CFS declarations for the
    # ready role.
    assert len(ent.sources) == 4


def test_rcore_task_stays_first_because_its_sources_are_alternatives():
    ms = load_dir(str(MDIR))
    if "rcore" not in ms:
        pytest.skip("没有 rcore 的 manifest")
    ent = [e for e in ms["rcore"].entities if e.name == "task"]
    if not ent:
        pytest.skip("rcore 的 manifest 里没有 task")
    assert ent[0].source_combine == "first"
    assert len(ent[0].sources) > 1, "只有一条的话这条测试什么也没验证"


def test_an_unknown_combine_refuses_to_load(tmp_path):
    p = tmp_path / "k.toml"
    p.write_text(
        '[kernel]\nname = "k"\n\n'
        '[[entity]]\nname = "task"\ntype = "T"\nsource_combine = "unoin"\n')
    with pytest.raises(ManifestError) as e:
        load(p)
    assert "source_combine" in str(e.value) and "unoin" in str(e.value)



def test_one_source_keeps_its_own_completeness():
    got = _completeness([_Src("total", "全都在这张表里")])
    assert got["completeness"] == "total"
    assert got["completeness_reason"] == "全都在这张表里"


def test_partials_do_not_add_up_to_total():
    got = _completeness([_Src("partial", "甲"), _Src("partial", "乙"),
                         _Src("partial", "丙")])
    assert got["completeness"] == "partial"


def test_one_total_source_makes_the_union_total():
    got = _completeness([_Src("partial", "只有就绪队列"), _Src("total")])
    assert got["completeness"] == "total"


def test_every_reason_survives_the_merge():
    got = _completeness([_Src("partial", "甲缺 X"), _Src("partial", "乙缺 Y")])
    assert "甲缺 X" in got["completeness_reason"]
    assert "乙缺 Y" in got["completeness_reason"]


def test_no_sources_is_unknown_not_total():
    assert _completeness([])["completeness"] == "unknown"


def test_the_reasons_stay_separable_even_though_each_contains_semicolons():
    got = _completeness([_Src("partial", "甲；甲的下半句"),
                         _Src("partial", "乙；乙的下半句")])["completeness_reason"]
    assert "（1）甲" in got and "（2）乙" in got



def test_the_probe_report_names_every_source_not_just_the_first():
    from nodefusion.model.dwarfsrc import DwarfSource
    from nodefusion.model.probe import probe

    elf = Path("/Users/jsph273/Desktop/Code/tsinghua/tg-arceos-tutorial"
               "/app-childtask/target/riscv64gc-unknown-none-elf/release"
               "/arceos-childtask")
    if not elf.is_file():
        pytest.skip("这台机器上没有 ArceOS 的构建")
    j = probe(load(MDIR / "arceos.toml"), DwarfSource(str(elf))).to_json()
    t = [e for e in j["entities"] if e["name"] == "task"][0]
    assert t["source_kind"].count("+") == 2, t["source_kind"]
    assert t["completeness"] == "partial"
    assert "合了 3 条来源" in (t["completeness_reason"] or "")


def test_the_probe_trace_says_it_took_the_union():
    from nodefusion.model.dwarfsrc import DwarfSource
    from nodefusion.model.probe import probe

    elf = Path("/Users/jsph273/Desktop/Code/tsinghua/tg-arceos-tutorial"
               "/app-childtask/target/riscv64gc-unknown-none-elf/release"
               "/arceos-childtask")
    if not elf.is_file():
        pytest.skip("这台机器上没有 ArceOS 的构建")
    j = probe(load(MDIR / "arceos.toml"), DwarfSource(str(elf))).to_json()
    t = [e for e in j["entities"] if e["name"] == "task"][0]
    assert any("取并集" in line for line in t["source_trace"]), t["source_trace"]


@pytest.mark.parametrize(
    ("elf_name", "scheduler", "container"),
    [
        ("arceos-55f7257f.elf", "FifoScheduler", "list"),
        ("builds/arceos-f24c92ae.elf", "CFScheduler", "btreemap"),
    ],
)
def test_arceos_selects_and_compiles_the_concrete_scheduler_queue(
        elf_name, scheduler, container):
    """FIFO and CFS store ready tasks in different container shapes.

    Both archived ELFs are real recordings.  A source merely being present in
    TOML is insufficient: it must be selected by that ELF and compile through
    the container to TaskInner without leaving a failed sibling source behind.
    """
    from nodefusion.host.nfelf import Elf64
    from nodefusion.model.dwarfsrc import DwarfSource
    from nodefusion.model.probe import probe
    from nodefusion.model.snapshot import SnapshotBuilder
    from nodefusion.model.symbols import SymbolIndex

    elf = REPO / "nodefusion" / "kernels" / elf_name
    if not elf.is_file():
        pytest.skip(f"这台机器上没有 ArceOS ELF：{elf}")
    manifest = load(MDIR / "arceos.toml")
    dw = DwarfSource(str(elf))
    result = probe(manifest, dw)
    builder = SnapshotBuilder(
        dw, result, manifest, syms=SymbolIndex(Elf64(str(elf)), dw))

    assert builder.compiled("task"), builder.why_not("task")
    assert builder.why_not("task") == "", builder.why_not("task")
    plans = builder._plans["task"]
    # idle + the one matching ready queue + exited; the other scheduler shapes
    # must be rejected by `when`, not selected and allowed to fail compilation.
    assert len(plans) == 3
    ready = [p for p in plans if any(
        op.kind == "iter" and op.args.get("container") == container
        for op in p.ops)]
    assert len(ready) == 1
    trace = "\n".join(ready[0].trace)
    assert scheduler in trace
    assert trace.rstrip().endswith("descend_to axtask::task::TaskInner = +0")



def _run(name: str):
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    return A.analyze(d)


@pytest.mark.corpus
def test_the_union_finds_tasks_the_first_source_alone_would_miss():
    a = _run("arceos-childtask-evsnap")
    names = {(p if isinstance(p, dict) else vars(p)).get("name")
             for s in a.states for p in s.procs}
    assert "idle" in names, names
    assert "gc" in names, f"就绪队列那条没跑：{names}"
    assert len(names) >= 3, names


@pytest.mark.corpus
def test_cfs_btree_source_recovers_real_ready_tasks_and_fields():
    """The CFS declaration must execute against recorded memory, not just DWARF."""
    a = _run("arceos-lazymapping")
    rows = [p if isinstance(p, dict) else vars(p)
            for state in a.states for p in state.procs]
    ready = [p for p in rows if p.get("name") in {"main", "gc"}]

    assert {p.get("name") for p in ready} == {"main", "gc"}
    assert all(p.get("state_name") == "Ready" for p in ready)
    for proc in ready:
        fields = proc.get("fields") or {}
        assert {"id", "name", "state", "cpu", "exit", "ctx"} <= fields.keys()
        assert all(fields[name]["state"] == "present"
                   for name in ("id", "name", "state", "cpu", "exit", "ctx"))


@pytest.mark.corpus
def test_the_three_sets_are_disjoint_so_nothing_is_double_counted():
    a = _run("arceos-childtask-evsnap")
    assert sum(len(s.procs) for s in a.states) == 6


@pytest.mark.corpus
def test_the_same_task_is_never_listed_twice_in_one_frame():
    a = _run("arceos-childtask-evsnap")
    seen = 0
    for s in a.states:
        pids = [(p if isinstance(p, dict) else vars(p)).get("pid")
                for p in s.procs]
        real = [x for x in pids if x is not None]
        assert len(real) == len(pids), f"有任务连 pid 都没解出来：{s.insn} {pids}"
        seen += len(real)
        assert len(real) == len(set(real)), (s.insn, real)
    assert seen, "一个任务都没查到，这条测试又空转了"


@pytest.mark.corpus
@pytest.mark.parametrize("name", ["lab3-cowtest-mac", "rcore-ch6-fs"])
def test_kernels_that_did_not_opt_in_decode_exactly_as_before(name):
    a = _run(name)
    assert sum(len(s.procs) for s in a.states) > 0
