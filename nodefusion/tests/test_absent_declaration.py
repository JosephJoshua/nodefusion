
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import analyze as A
from nodefusion.model import kinds as K
from nodefusion.model import manifest as M

RUNS = Path(__file__).resolve().parents[1] / "runs"
MANIFESTS = Path(__file__).resolve().parents[1] / "manifests"

OK_EV = "easy-fs/src 整个 crate grep 不到 log / journal / transaction。"


def _load(tmp_path: Path, body: str) -> M.Manifest:
    p = tmp_path / "t.toml"
    p.write_text('[kernel]\nname = "t"\n\n' + body, encoding="utf-8")
    return M.load(p)


def _skip_if_missing(name: str) -> Path:
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")
    return d



def test_the_inline_table_form_loads(tmp_path):
    m = _load(tmp_path, f'[absent]\n"log.commit" = '
                        f'{{ why = "feature", evidence = "{OK_EV}" }}\n')
    assert set(m.absent) == {"log.commit"}
    assert m.absent["log.commit"].why == "feature"
    assert m.absent["log.commit"].evidence == OK_EV


def test_the_section_form_loads_the_same_thing(tmp_path):
    m = _load(tmp_path, f'[absent."vm.unmap"]\nwhy = "granularity"\n'
                        f'evidence = "{OK_EV}"\n')
    assert m.absent["vm.unmap"].why == "granularity"
    assert m.absent["vm.unmap"].kind == "vm.unmap"


def test_a_manifest_without_the_section_still_loads(tmp_path):
    assert _load(tmp_path, "").absent == {}


def test_both_why_values_are_accepted(tmp_path):
    m = _load(tmp_path, f'[absent]\n'
                        f'"log.commit" = {{ why = "feature", evidence = "{OK_EV}" }}\n'
                        f'"vm.unmap" = {{ why = "granularity", evidence = "{OK_EV}" }}\n')
    assert {s.why for s in m.absent.values()} == {"feature", "granularity"}



def test_an_unknown_why_is_rejected_and_the_message_lists_the_choices(tmp_path):
    with pytest.raises(M.ManifestError) as e:
        _load(tmp_path, f'[absent]\n"log.commit" = '
                        f'{{ why = "featrue", evidence = "{OK_EV}" }}\n')
    msg = str(e.value)
    assert "featrue" in msg
    assert "feature" in msg and "granularity" in msg, f"没告诉人能填什么：{msg}"


def test_a_placeholder_evidence_is_rejected(tmp_path):
    for junk in ("无", "N/A", "没有", "见代码"):
        with pytest.raises(M.ManifestError) as e:
            _load(tmp_path, f'[absent]\n"log.commit" = '
                            f'{{ why = "feature", evidence = "{junk}" }}\n')
        assert "evidence" in str(e.value), str(e.value)


def test_a_missing_evidence_is_rejected_too(tmp_path):
    with pytest.raises(M.ManifestError):
        _load(tmp_path, '[absent]\n"log.commit" = { why = "feature" }\n')


def test_declaring_a_kind_that_is_also_mapped_is_rejected(tmp_path):
    with pytest.raises(M.ManifestError) as e:
        _load(tmp_path, f'[event]\nlog_write = "log.commit"\n\n'
                        f'[absent]\n"log.commit" = '
                        f'{{ why = "feature", evidence = "{OK_EV}" }}\n')
    msg = str(e.value)
    assert "log.commit" in msg
    assert "log_write" in msg, f"该指出是谁映的，不然人得自己翻：{msg}"


def test_an_unknown_key_is_rejected(tmp_path):
    with pytest.raises(M.ManifestError):
        _load(tmp_path, f'[absent]\n"log.commit" = '
                        f'{{ why = "feature", evidenc = "{OK_EV}" }}\n')


def test_a_bare_string_is_not_a_declaration(tmp_path):
    with pytest.raises(M.ManifestError) as e:
        _load(tmp_path, '[absent]\n"log.commit" = "本内核没有日志层"\n')
    assert "表" in str(e.value)


def test_an_unregistered_kind_is_rejected(tmp_path):
    with pytest.raises(K.UnknownKindError) as e:
        _load(tmp_path, f'[absent]\n"log.komit" = '
                        f'{{ why = "feature", evidence = "{OK_EV}" }}\n')
    assert "log.commit" in str(e.value), (
        f"拼错时该把同命名空间里已登记的列出来：{e.value}")



def test_every_shipped_manifest_loads():
    assert M.load_dir(MANIFESTS)


def test_the_declaration_we_ship_is_the_real_rcore_feature_limit():
    mans = M.load_dir(MANIFESTS)
    declared = {k: sorted(m.absent) for k, m in mans.items() if m.absent}
    assert declared == {"rcore": ["log.commit"],
                        "ucore": ["log.commit"]}, declared
    a = mans["rcore"].absent
    assert a["log.commit"].why == "feature"


def test_the_shipped_evidence_points_at_something_checkable():
    checked = 0
    for kern, m in M.load_dir(MANIFESTS).items():
        for kind, spec in m.absent.items():
            ev = spec.evidence
            assert any(t in ev for t in ("::", ".rs", "/src", "()", "grep")), (
                f"{kern} 的 {kind} 依据里没有可查的抓手：{ev}")
            checked += 1
    assert checked, "一条声明都没查到 —— 多半是 absent 没加载进来"



def test_absent_kinds_needs_no_dwarf():
    class Bare:
        kernel_kind = "rcore"
        notes: list[str] = []
    got = A.Analysis._absent_kinds(Bare())
    assert sorted(got) == ["log.commit"]
    assert not Bare.notes, f"不该有告警：{Bare.notes}"


def test_an_unknown_kernel_kind_yields_an_empty_table_quietly():
    class Bare:
        kernel_kind = "nosuchkernel"
        notes: list[str] = []
    assert A.Analysis._absent_kinds(Bare()) == {}


@pytest.mark.corpus
def test_the_report_carries_the_evidence_but_the_sentence_does_not():
    m = A.analyze(_skip_if_missing("rcore-fs-alloc")).metrics()
    decl = m.get("absent_declared") or {}
    assert set(decl) == {"log.commit"}, decl
    why = m.get("unobservable_reason") or ""
    for kind, d in decl.items():
        assert d["evidence"], kind
        assert d["evidence"] not in why, (
            f"{kind} 的依据被塞进理由句里了，那句话的解析会坏：{why}")


@pytest.mark.corpus
def test_declaring_absence_does_not_raise_the_ceiling():
    m = A.analyze(_skip_if_missing("rcore-fs-alloc")).metrics()
    why = m.get("unobservable_reason") or ""
    import re
    total = int(re.search(r"本趟 (\d+) 项指标", why).group(1))
    ceiling = int(re.search(r"最多只能有 (\d+) 项", why).group(1))
    n_declared = len(m.get("absent_declared") or {})
    assert n_declared, "rCore 的声明没了，这条测不到东西"
    assert ceiling <= total - n_declared, (
        f"上限 {ceiling}，总数 {total}，声明过的 {n_declared} —— "
        f"声明过的那几项被从分母里放行了")
