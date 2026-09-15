
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.host import elfid                            # noqa: E402

RUN_UTC = "2026-08-29T07:00:00Z"


def _elf(tmp_path: Path, *, mtime: datetime) -> Path:
    p = tmp_path / "kernel"
    p.write_bytes(b"not really an elf")
    ts = mtime.timestamp()
    os.utime(p, (ts, ts))
    return p


def _at(offset_hours: float) -> datetime:
    return (datetime.fromisoformat(RUN_UTC.replace("Z", "+00:00"))
            + timedelta(hours=offset_hours))


def test_old_run_says_cannot_check_not_looks_fine(tmp_path):
    p = _elf(tmp_path, mtime=_at(-1))
    (line,) = elfid.compare(None, p, recorded_utc=RUN_UTC)
    assert "查不了" in line


def test_elf_rewritten_after_the_run_is_reported(tmp_path):
    p = _elf(tmp_path, mtime=_at(+8))
    (line,) = elfid.compare(None, p, recorded_utc=RUN_UTC)
    assert "查不了" in line and "晚于" in line


def test_the_mtime_hint_states_it_is_not_proof(tmp_path):
    p = _elf(tmp_path, mtime=_at(+8))
    (line,) = elfid.compare(None, p, recorded_utc=RUN_UTC)
    assert "不证明" in line


def test_elf_older_than_the_run_stays_quiet(tmp_path):
    p = _elf(tmp_path, mtime=_at(-1))
    (line,) = elfid.compare(None, p, recorded_utc=RUN_UTC)
    assert "晚于" not in line
    assert "查不了" in line


def test_no_recorded_time_means_no_hint(tmp_path):
    p = _elf(tmp_path, mtime=_at(+8))
    (line,) = elfid.compare(None, p, recorded_utc=None)
    assert "晚于" not in line


def test_unreadable_symbols_are_not_reported_as_unchanged(tmp_path):
    p = _elf(tmp_path, mtime=_at(+8))
    recorded = {"sha256": "a" * 64, "root_symbols": {"proc": "0x80233e80"}}
    (line,) = elfid.compare(recorded, p, recorded_utc=RUN_UTC)
    assert "比不了" in line
    assert "解码仍然成立" not in line, "读不出来的时候不许说解码成立"


def test_nothing_recorded_for_symbols_is_also_uncheckable(tmp_path):
    p = _elf(tmp_path, mtime=_at(-1))
    recorded = {"sha256": "a" * 64, "root_symbols_note": "一个都没找到"}
    (line,) = elfid.compare(recorded, p, recorded_utc=RUN_UTC)
    assert "比不了" in line


def test_identical_full_hash_needs_no_root_symbol_fallback(tmp_path):
    """Byte-identical ELFs already prove every symbol address is identical."""
    p = _elf(tmp_path, mtime=_at(-1))
    recorded = elfid.elf_identity(p)
    recorded.pop("root_symbols", None)
    recorded["root_symbols_note"] = "这个内核没有通用的根符号名"

    assert elfid.compare(recorded, p, recorded_utc=RUN_UTC) == []


def test_a_reconstructed_identity_says_so(tmp_path):
    p = _elf(tmp_path, mtime=_at(-1))
    recorded = {"sha256": "a" * 64, "root_symbols": {"proc": "0x1"},
                "reconstructed": "拿入口字节比出来的"}
    lines = elfid.compare(recorded, p, recorded_utc=RUN_UTC)
    assert any("事后补的" in x for x in lines), lines


def test_the_reconstructed_note_survives_a_clean_comparison(tmp_path):
    p = _elf(tmp_path, mtime=_at(-1))
    now = elfid.elf_identity(p)
    recorded = dict(now)
    recorded["reconstructed"] = "拿入口字节比出来的"
    lines = elfid.compare(recorded, p, recorded_utc=RUN_UTC)
    assert any("事后补的" in x for x in lines), (
        f"身份全对上的时候把这句吞了：{lines}")


def test_a_normally_recorded_identity_stays_quiet(tmp_path):
    p = _elf(tmp_path, mtime=_at(-1))
    now = elfid.elf_identity(p)
    lines = elfid.compare(dict(now), p, recorded_utc=RUN_UTC)
    assert not any("事后补的" in x for x in lines), lines


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
