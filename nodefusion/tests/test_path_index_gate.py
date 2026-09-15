
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import watchlist as W
from nodefusion.host.kernels import archived_elf


def _archived(kind: str) -> Path:
    return archived_elf(kind) or Path(f"/nonexistent/{kind}.elf")

ELVES = {k: _archived(k) for k in ("xv6", "rcore", "arceos")}


def _elf(which: str):
    p = ELVES[which]
    if not p.is_file():
        pytest.skip(f"要 {which} 的内核 ELF（{p}），是 build 产物，没有就跳过")
    from nodefusion.host.nfelf import Elf64
    return Elf64(str(p))



def test_the_gate_is_not_spelled_as_a_kernel_name():
    src = (Path(W.__file__)).read_text()
    line = [l for l in src.splitlines()
            if "_path_index(elf)" in l and "def " not in l]
    assert line, "找不到建索引那一行，这条测试该跟着改了"
    for l in line:
        assert 'kind ==' not in l, f"判据又写回内核名了：{l.strip()}"


def test_an_unmangled_kernel_gets_an_empty_index():
    assert _path_index_len("xv6") == 0


def test_a_legacy_mangled_kernel_still_gets_its_index():
    assert _path_index_len("rcore") > 100


def _path_index_len(which: str) -> int:
    return len(W._path_index(_elf(which)))



def test_dropping_unmangled_names_loses_nothing():
    elf = _elf("rcore")

    old: dict[str, list] = {}
    for s in elf.functions():
        old.setdefault(W.demangle(s.name), []).append(s)
    new = W._path_index(elf)
    assert len(old) > len(new), "旧写法没多收东西，这条测试没验证到差别"

    for path in set(old) - set(new):
        assert W.demangle(path) == path, f"{path} 是解开过的，不该被丢掉"

    for path in set(old) - set(new):
        assert elf.sym(path) is not None, f"{path} 精确查名也找不着，真丢了"


def test_the_watchlist_is_unchanged_on_both_supported_kernels():
    got = {}
    for kind in ("xv6", "rcore"):
        wl = W.build(_elf(kind), kind=kind)
        got[kind] = (len(wl.entries), len(wl.missing))
    assert got["xv6"] == (72, 1), got["xv6"]
    assert got["rcore"] == (59, 46), got["rcore"]



def test_a_bare_name_is_never_matched_by_suffix():
    with pytest.raises(ValueError, match="一个都没解出来"):
        W.build(_elf("rcore"), kind="xv6")


def test_the_two_tables_disagree_about_whether_names_are_paths():
    def paths(kind):
        table = W._TABLES[kind][0]
        return sum("::" in n for n, _ in table), len(table)

    n_xv6, tot_xv6 = paths("xv6")
    n_rc, tot_rc = paths("rcore")
    assert n_xv6 == 0, f"xv6 表里出现了 {n_xv6} 个路径名"
    assert n_rc > tot_rc // 2, f"rCore 表里只有 {n_rc}/{tot_rc} 个是路径名"


def test_the_gate_asks_both_questions_at_the_point_of_use():
    src = Path(W.__file__).read_text()
    use = [l for l in src.splitlines()
           if "not syms and path_idx" in l and l.lstrip().startswith("if ")]
    assert len(use) == 1, use
    assert '"::" in name' in use[0], f"少了名字那一半：{use[0].strip()}"



def test_the_two_rust_kernels_do_not_share_a_mangling_scheme():
    def scheme(which):
        ns = [s.name for s in _elf(which).functions()]
        return ("legacy" if sum(n.startswith("_ZN") for n in ns) > len(ns) // 2
                else "v0" if sum(n.startswith("_R") for n in ns) > len(ns) // 2
                else "plain")

    assert scheme("rcore") == "legacy"
    assert scheme("arceos") == "v0"
    assert scheme("xv6") == "plain"


def test_this_modules_demangler_only_claims_legacy():
    from nodefusion.model.symbols import demangle as full

    v0 = "_RNvNtCs8MUOdSUZJDZ_6axtask9run_queue7poll_gc"
    assert W.demangle(v0) == v0, "host 的 demangle 声称解开了 v0，它并不能"
    assert full(v0) == "axtask::run_queue::poll_gc"
