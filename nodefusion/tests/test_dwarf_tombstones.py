
from __future__ import annotations

import pytest

from nodefusion.tests.kernelelf import elf_or_skip


def _dw(kind: str):
    from nodefusion.model.dwarfsrc import DwarfSource
    return DwarfSource(str(elf_or_skip(kind)))


def _watchlist(kind: str):
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.watchlist import build_from_manifest
    from nodefusion.model import manifest as M
    p = str(elf_or_skip(kind))
    m = M.load_dir(M.builtin_dir())[kind]
    return build_from_manifest(Elf64(p), _dw(kind), m.watches, events=m.events)



@pytest.mark.parametrize("kind", ["rcore", "xv6", "arceos"])
def test_no_watchpoint_is_armed_at_a_tombstone_address(kind):
    bad = [(e.kind, e.name) for e in _watchlist(kind).entries if not e.addr]
    assert not bad, f"{kind} 选出了零地址观察点：{bad}"



def test_the_rust_kernel_actually_has_tombstones_to_filter():
    dw = _dw("rcore")
    assert dw.functions_tombstoned > 0, (
        "这份构建一个墓碑都没有，那条零地址断言就是空转的；"
        "先确认 DwarfSource 真的读到了 subprogram")


def test_a_c_kernel_has_none_so_the_filter_is_not_firing_blindly():
    assert _dw("xv6").functions_tombstoned == 0



def test_a_tombstoned_function_is_kept_without_an_address():
    dw = _dw("rcore")
    none_pc = [f for f in dw.functions if f.low_pc is None]
    assert len(none_pc) == dw.functions_tombstoned, (
        f"计数器说挡了 {dw.functions_tombstoned} 个，"
        f"但 functions 里只有 {len(none_pc)} 个没地址的")
    for f in none_pc[:5]:
        assert f.name and f.path, "置空地址的时候把身份也弄丢了"


def test_every_addressed_function_lands_in_an_executable_section():
    dw = _dw("rcore")
    assert dw._exec_ranges, "可执行节范围读空了，过滤会被短路掉"
    bad = [(hex(f.low_pc), f.path) for f in dw.functions
           if f.low_pc is not None and not dw._in_exec(f.low_pc)]
    assert not bad, f"这些地址不在可执行节里却留下了：{bad[:5]}"
