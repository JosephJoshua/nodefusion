
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.readers import containers as C     # noqa: E402
from nodefusion.model.rt import ReadCtx                  # noqa: E402
from nodefusion.tests.test_readers_containers import (   # noqa: E402
    DictMemory, read_u32, u32, u64)

LINKS_OFF = 256
E1, E2, E3 = 0x1000, 0x1300, 0x1600
HEAD = 0x900


def _ready_queue(*addrs):
    mem = DictMemory().write(HEAD, u64(addrs[0] if addrs else 0))
    for i, at in enumerate(addrs):
        nxt = addrs[(i + 1) % len(addrs)]
        mem.write(at, u32(i + 1))
        mem.write(at + LINKS_OFF, u64(nxt))
    return mem


def _reader():
    return C.list(0, LINKS_OFF, read_u32, terminator=C.CircularHeaded())


def test_walks_the_whole_ring_and_stops_at_the_head():
    got = _reader()(_ready_queue(E1, E2, E3), HEAD, ReadCtx())
    assert got == [1, 2, 3], got
    assert C.incomplete_of(got) is None, "绕回第一个是正常结束，不是环"


def test_a_single_element_ring_yields_exactly_one():
    got = _reader()(_ready_queue(E1), HEAD, ReadCtx())
    assert got == [1], got


def test_an_empty_queue_is_empty_not_an_error():
    mem = DictMemory().write(HEAD, u64(0))
    got = _reader()(mem, HEAD, ReadCtx())
    assert got == [], got
    assert C.incomplete_of(got) is None, "空队列不是故障"


def test_null_terminated_would_have_falsely_cried_cycle():
    got = C.list(0, LINKS_OFF, read_u32)(
        _ready_queue(E1, E2, E3), HEAD, ReadCtx())
    assert isinstance(C.incomplete_of(got), C.Cycle), (
        f"预期错误规则会误报成环，实际拿到 {got}")


def test_a_genuinely_broken_ring_is_still_reported():
    mem = _ready_queue(E1, E2, E3)
    mem.write(E3 + LINKS_OFF, u64(E2))
    got = _reader()(mem, HEAD, ReadCtx())
    c = C.incomplete_of(got)
    assert isinstance(c, C.Cycle), got
    assert c.addr == E2, f"环该在 {E2:#x} 闭合：{got}"


def test_truncation_still_applies():
    got = _reader()(_ready_queue(E1, E2, E3), HEAD, ReadCtx(max_items=2))
    assert isinstance(C.incomplete_of(got), C.Truncated), got
