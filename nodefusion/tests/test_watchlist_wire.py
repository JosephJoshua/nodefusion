
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nodefusion.host.watchlist import NFTRACE_COMMIT, WatchEntry, WatchList

_PLUGIN_C = Path(__file__).resolve().parent.parent / "plugin" / "nf_plugin.c"


def _wl(*entries: WatchEntry) -> list[str]:
    text = WatchList(entries=list(entries), missing=[],
                     nftrace_index=None).to_file_text()
    return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]


def _entry(name: str, addr: int, **kw) -> WatchEntry:
    kw.setdefault("index", 0)
    kw.setdefault("symbol", name)
    kw.setdefault("resource", "proc")
    kw.setdefault("snap", False)
    return WatchEntry(name=name, addr=addr, **kw)


def test_a_plain_watch_carries_no_tag():
    assert _wl(_entry("fork", 0x8000_1000)) == ["0x80001000 fork"]


def test_a_rate_becomes_an_at_r_tag():
    assert _wl(_entry("walk", 0x8000_2000, rate=128)) == ["0x80002000 @r128:walk"]


@pytest.mark.parametrize("rate", [0, 1])
def test_a_rate_of_zero_or_one_is_not_written(rate):
    assert _wl(_entry("fork", 0x8000_1000, rate=rate)) == ["0x80001000 fork"]


def test_a_snapshot_watch_never_advertises_a_rate():
    line, = _wl(_entry("panic", 0x8000_0e30, snap=True, rate=64))
    assert line == "0x80000e30 @snap:panic"

    line, = _wl(_entry(NFTRACE_COMMIT, 0x8000_9000, rate=64))
    assert line == f"0x80009000 @nft:{NFTRACE_COMMIT}"


def test_an_event_snapshot_keeps_its_own_tag():
    line, = _wl(_entry("kfork", 0x8000_2ee6, snap=True, throttle=True))
    assert line == "0x80002ee6 @esnap:kfork"


def test_a_rust_method_name_survives_the_tag_syntax():
    line, = _wl(_entry("MemorySet::push", 0x8020_1234, rate=64))
    assert line == "0x80201234 @r64:MemorySet::push"


def test_every_tag_the_writer_can_emit_is_understood_by_the_plugin():
    src = _PLUGIN_C.read_text(encoding="utf-8")
    known = set(re.findall(r'strcmp\(tag,\s*"(\w+)"\)', src))
    assert {"snap", "esnap", "nft"} <= known, known
    assert "tag[0] == 'r'" in src

    emitted = set()
    for e in (_entry("a", 1, snap=True),
              _entry("b", 2, snap=True, throttle=True),
              _entry(NFTRACE_COMMIT, 3),
              _entry("d", 4, rate=8)):
        for tag in re.findall(r"@(\w+?):", _wl(e)[0]):
            emitted.add(tag)
    for tag in emitted:
        assert tag in known or re.fullmatch(r"r\d+", tag), tag
