import struct
import zlib

import pytest

from nodefusion.host import nftrace as nf


def _record(kind, payload, *, flags=0, insn=42):
    return nf._HDR.pack(kind, 0, len(payload), flags, insn) + payload


def _trace(*records):
    return nf.MAGIC + struct.pack("<II", 2, nf._HDR.size) + b"".join(records)


def test_indexed_pages_match_eager_decoding(tmp_path):
    page = b"x" * 4096
    mark = nf._SNAPMARK.pack(0, 0x80000000, 4096, 2, 2, 0)
    raw = _trace(
        _record(nf.REC_SNAPMARK, mark),
        _record(nf.REC_RAMPAGE, nf._RAMPAGE.pack(0, 4096) + zlib.compress(page),
                flags=nf.F_ZLIB),
        _record(nf.REC_RAMPAGE, nf._RAMPAGE.pack(1, 4096) + page),
        _record(nf.REC_END, nf._END.pack(42, 1, 0, 0, 0, 0, 0, 0)))
    path = tmp_path / "trace.nfb"
    path.write_bytes(raw)

    eager = nf.load(path)
    indexed = nf.load(path, indexed_pages=True)
    assert dict(indexed.snapshots[0].pages.items()) == eager.snapshots[0].pages
    assert indexed.snapshots[0].pages[0] == page
    assert list(nf.iter_records(path)) == [
        ("snapmark", 0, 0, 42, len(mark)),
        ("rampage", 0, nf.F_ZLIB, 42, 8 + len(zlib.compress(page))),
        ("rampage", 0, 0, 42, 8 + len(page)),
        ("end", 0, 0, 42, nf._END.size),
    ]
    assert nf.load(path, want_pages=False, indexed_pages=True).snapshots[0].pages == {}


@pytest.mark.parametrize("trailing", [b"x", nf._HDR.pack(nf.REC_META, 0, 5, 0, 0) + b"a"])
def test_partial_record_marks_trace_incomplete(tmp_path, trailing):
    path = tmp_path / "partial.nfb"
    path.write_bytes(_trace(_record(nf.REC_META, b"key=value"), trailing))
    trace = nf.load(path, indexed_pages=True)
    assert trace.meta == {"key": "value"}
    assert trace.truncated_at_eof


def test_indexed_page_rejects_invalid_length_when_consumed(tmp_path):
    path = tmp_path / "invalid.nfb"
    path.write_bytes(_trace(
        _record(nf.REC_SNAPMARK, nf._SNAPMARK.pack(0, 0, 4096, 1, 1, 0)),
        _record(nf.REC_RAMPAGE, nf._RAMPAGE.pack(0, 4096) + b"short")))
    trace = nf.load(path, indexed_pages=True)
    with pytest.raises(nf.TraceError, match="长度"):
        list(trace.snapshots[0].pages.items())


def test_packed_watch_hits_preserve_iteration_indexing_and_order(tmp_path):
    payload = nf._WATCHPC.pack(7, 1, 0x1234, 0x80000, *range(8), 99, 100)
    path = tmp_path / "watch.nfb"
    path.write_bytes(_trace(_record(nf.REC_WATCHPC, payload, insn=5),
                            _record(nf.REC_WATCHPC, payload, insn=9)))
    eager = nf.load(path).watch_hits
    packed = nf.load(path, compact_watch_hits=True).watch_hits
    assert isinstance(packed, nf.PackedWatchHits)
    assert list(packed) == eager
    assert packed[-1] == eager[-1]
    assert packed[:1] == eager[:1]
