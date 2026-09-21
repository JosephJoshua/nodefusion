
from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping

MAGIC = b"NFTRACE\x01"

REC_META = 1
REC_SAMPLE = 2
REC_DISCON = 3
REC_WATCHPC = 4
REC_SNAPMARK = 5
REC_RAMPAGE = 6
REC_IDLE = 7
REC_VCPU = 8
REC_WARN = 9
REC_END = 10
REC_NFTRACE = 11

REC_NAMES = {
    REC_META: "meta", REC_SAMPLE: "sample", REC_DISCON: "discon",
    REC_WATCHPC: "watchpc", REC_SNAPMARK: "snapmark", REC_RAMPAGE: "rampage",
    REC_IDLE: "idle", REC_VCPU: "vcpu", REC_WARN: "warn", REC_END: "end",
    REC_NFTRACE: "nftrace",
}

# flags
F_NO_REGS = 1 << 0
F_NO_CSR = 1 << 1
F_TRUNCATED = 1 << 2
F_ZLIB = 1 << 3
F_INCOMPLETE = 1 << 4
F_NO_MCSR = 1 << 5

SUPPORTED_FORMAT_VERS = frozenset({1, 2})

_HDR = struct.Struct("<BBHIQ")          # type, cpu, len, flags, insn
_SAMPLE = struct.Struct("<QQQII")       # pc, satp, sstatus, priv, pad
_DISCON_V1 = struct.Struct("<IIQQQQQQQ8QQ")
_DISCON_MCSR = struct.Struct("<QQQ")    # mcause, mepc, mtval
_WATCHPC = struct.Struct("<IIQQ8QQQ")
_WATCH_ROW = struct.Struct("<QBI" + _WATCHPC.format[1:])
_SNAPMARK = struct.Struct("<QQIIII")
_RAMPAGE = struct.Struct("<II")
_END = struct.Struct("<QQQQQQII")

DISCON_INTERRUPT = 1
DISCON_EXCEPTION = 2
DISCON_HOSTCALL = 4

PRIV_U = 0
PRIV_S = 1
PRIV_M = 3


class TraceError(Exception):
    pass


@dataclass(slots=True)
class Sample:
    insn: int
    cpu: int
    flags: int
    pc: int
    satp: int
    sstatus: int
    priv: int


@dataclass(slots=True)
class Discon:
    insn: int
    cpu: int
    flags: int
    discon_type: int
    priv: int
    from_pc: int
    to_pc: int
    scause: int
    sepc: int
    stval: int
    satp: int
    sstatus: int
    a: tuple
    sp: int
    mcause: int | None = None
    mepc: int | None = None
    mtval: int | None = None


    @property
    def trapped_to_m(self) -> bool:
        return self.priv == PRIV_M

    @property
    def cause_available(self) -> bool:
        if self.trapped_to_m:
            return self.mcause is not None and not (self.flags & F_NO_MCSR)
        return not (self.flags & F_NO_CSR)

    @property
    def cause(self) -> int | None:
        if not self.cause_available:
            return None
        return self.mcause if self.trapped_to_m else self.scause

    @property
    def epc(self) -> int | None:
        if not self.cause_available:
            return None
        return self.mepc if self.trapped_to_m else self.sepc

    @property
    def tval(self) -> int | None:
        if not self.cause_available:
            return None
        return self.mtval if self.trapped_to_m else self.stval

    @property
    def is_interrupt_flag(self) -> bool:
        c = self.cause
        return bool(c >> 63) if c is not None else False

    @property
    def cause_code(self) -> int | None:
        c = self.cause
        return None if c is None else c & ((1 << 63) - 1)


@dataclass(slots=True)
class WatchHit:
    insn: int
    cpu: int
    flags: int
    watch_id: int
    priv: int
    pc: int
    satp: int
    a: tuple
    sp: int
    ra: int


class PackedWatchHits(Sequence[WatchHit]):
    """Fixed-width watch records without millions of live Python objects."""

    def __init__(self):
        self.data = bytearray()

    def append_record(self, insn: int, cpu: int, flags: int, payload: bytes) -> None:
        self.data.extend(struct.pack("<QBI", insn, cpu, flags))
        self.data.extend(payload)

    def __len__(self) -> int:
        return len(self.data) // _WATCH_ROW.size

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        v = _WATCH_ROW.unpack_from(self.data, index * _WATCH_ROW.size)
        return WatchHit(v[0], v[1], v[2], v[3], v[4], v[5], v[6],
                        tuple(v[7:15]), v[15], v[16])

    def __iter__(self) -> Iterator[WatchHit]:
        for i in range(len(self)):
            yield self[i]


@dataclass(slots=True)
class SnapMark:
    insn: int
    cpu: int
    flags: int
    snap_seq: int
    ram_base: int
    page_size: int
    pages_changed: int
    pages_total: int
    pages: Mapping[int, bytes] = field(default_factory=dict)


@dataclass(slots=True)
class TraceEnd:
    insn: int
    total_insns: int
    snapshots: int
    discons: int
    samples: int
    watch_hits: int
    ram_bytes: int
    truncated: bool
    watch_drops: int | None = None


@dataclass(slots=True)
class NfTraceRec:
    insn: int
    cpu: int
    type: int
    a: tuple


@dataclass(slots=True)
class Trace:
    path: Path
    meta: dict = field(default_factory=dict)
    samples: list = field(default_factory=list)
    discons: list = field(default_factory=list)
    watch_hits: list[WatchHit] | PackedWatchHits = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    idles: list = field(default_factory=list)      # (insn, cpu, kind)
    vcpu_events: list = field(default_factory=list)
    warnings: list = field(default_factory=list)   # (insn, text)
    nftrace: list = field(default_factory=list)
    end: TraceEnd | None = None
    truncated_at_eof: bool = False

    @property
    def total_insns(self) -> int:
        if self.end:
            return self.end.total_insns
        last = 0
        for seq in (self.samples, self.discons, self.watch_hits, self.snapshots):
            if seq:
                last = max(last, seq[-1].insn)
        return last


class IndexedPages(Mapping[int, bytes]):
    """Page locations in the trace, decoded one snapshot at a time."""

    def __init__(self, path: Path):
        self.path = path
        self.offsets: dict[int, tuple[int, int, int, int]] = {}

    def __len__(self) -> int:
        return len(self.offsets)

    def __iter__(self) -> Iterator[int]:
        return iter(self.offsets)

    def __getitem__(self, idx: int) -> bytes:
        with self.path.open("rb") as stream:
            return self._read(idx, self.offsets[idx], stream)

    @staticmethod
    def _read(idx: int, entry: tuple[int, int, int, int], stream) -> bytes:
        offset, size, flags, raw_len = entry
        stream.seek(offset)
        blob = stream.read(size)
        if len(blob) != size:
            raise TraceError(f"物理页 {idx} 的负载已截断")
        if flags & F_ZLIB:
            blob = zlib.decompress(blob)
        if len(blob) != raw_len:
            raise TraceError(
                f"物理页 {idx} 解压后长度 {len(blob)} != 声明的 {raw_len}")
        return blob

    def items(self) -> Iterator[tuple[int, bytes]]:
        with self.path.open("rb") as stream:
            for idx, entry in self.offsets.items():
                yield idx, self._read(idx, entry, stream)


def _read_header(stream, path: Path) -> None:
    raw = stream.read(16)
    if len(raw) < 16 or raw[:8] != MAGIC:
        raise TraceError(f"{path} 不是 NodeFusion 轨迹文件（magic 不对）")
    fmt_ver, hdr_size = struct.unpack_from("<II", raw, 8)
    if fmt_ver not in SUPPORTED_FORMAT_VERS:
        raise TraceError(
            f"轨迹格式版本 {fmt_ver} 不被支持（本解码器认 "
            f"{sorted(SUPPORTED_FORMAT_VERS)}）")
    if hdr_size != _HDR.size:
        raise TraceError(
            f"轨迹记录头长度 {hdr_size} 与解码器的 {_HDR.size} 不一致；"
            f"插件和 host 版本不匹配")


def load(path: str | Path, *, want_pages: bool = True,
         indexed_pages: bool = False, compact_watch_hits: bool = False) -> Trace:
    p = Path(path)
    tr = Trace(path=p)
    if compact_watch_hits:
        tr.watch_hits = PackedWatchHits()
    cur_snap: SnapMark | None = None
    def records() -> Iterator[tuple[int, int, int, int, int, int, bytes]]:
        with p.open("rb") as stream:
            _read_header(stream, p)
            n = p.stat().st_size
            while stream.tell() < n:
                header = stream.read(_HDR.size)
                if len(header) < _HDR.size:
                    tr.truncated_at_eof = True
                    break
                rtype, cpu, rlen, flags, insn = _HDR.unpack(header)
                body = stream.tell()
                if body + rlen > n:
                    tr.truncated_at_eof = True
                    break
                if rtype == REC_RAMPAGE and indexed_pages and want_pages:
                    payload = stream.read(min(_RAMPAGE.size, rlen))
                    stream.seek(body + rlen)
                elif rtype == REC_RAMPAGE and not want_pages:
                    payload = b""
                    stream.seek(body + rlen)
                else:
                    payload = stream.read(rlen)
                yield rtype, cpu, rlen, flags, insn, body, payload

    for rtype, cpu, rlen, flags, insn, body, payload in records():
        if rtype == REC_META:
            text = payload.decode("utf-8", "replace")
            if "=" in text:
                k, v = text.split("=", 1)
                tr.meta[k] = v
        elif rtype == REC_SAMPLE:
            pc, satp, sstatus, priv, _ = _SAMPLE.unpack_from(payload, 0)
            tr.samples.append(Sample(insn, cpu, flags, pc, satp, sstatus, priv))
        elif rtype == REC_DISCON:
            v = _DISCON_V1.unpack_from(payload, 0)
            mcause = mepc = mtval = None
            if len(payload) >= _DISCON_V1.size + _DISCON_MCSR.size:
                mcause, mepc, mtval = _DISCON_MCSR.unpack_from(
                    payload, _DISCON_V1.size)
            tr.discons.append(Discon(
                insn, cpu, flags, v[0], v[1], v[2], v[3], v[4], v[5], v[6],
                v[7], v[8], tuple(v[9:17]), v[17], mcause, mepc, mtval))
        elif rtype == REC_WATCHPC:
            if compact_watch_hits:
                if rlen < _WATCHPC.size:
                    _WATCHPC.unpack_from(payload)
                tr.watch_hits.append_record(
                    insn, cpu, flags, payload[:_WATCHPC.size])
            else:
                v = _WATCHPC.unpack_from(payload, 0)
                tr.watch_hits.append(WatchHit(
                    insn, cpu, flags, v[0], v[1], v[2], v[3],
                    tuple(v[4:12]), v[12], v[13]))
        elif rtype == REC_SNAPMARK:
            seq, base, ps, changed, total, _ = _SNAPMARK.unpack_from(payload, 0)
            cur_snap = SnapMark(insn, cpu, flags, seq, base, ps, changed, total)
            if indexed_pages and want_pages:
                cur_snap.pages = IndexedPages(p)
            tr.snapshots.append(cur_snap)
        elif rtype == REC_RAMPAGE:
            if want_pages and cur_snap is not None:
                idx, raw_len = _RAMPAGE.unpack_from(payload, 0)
                if indexed_pages:
                    cur_snap.pages.offsets[idx] = (
                        body + _RAMPAGE.size, rlen - _RAMPAGE.size,
                        flags, raw_len)
                else:
                    blob = payload[_RAMPAGE.size:]
                    if flags & F_ZLIB:
                        blob = zlib.decompress(blob)
                    if len(blob) != raw_len:
                        raise TraceError(
                            f"物理页 {idx} 解压后长度 {len(blob)} != 声明的 {raw_len}")
                    cur_snap.pages[idx] = blob
        elif rtype == REC_IDLE:
            kind, = struct.unpack_from("<I", payload, 0)
            tr.idles.append((insn, cpu, kind))
        elif rtype == REC_VCPU:
            up, = struct.unpack_from("<I", payload, 0)
            tr.vcpu_events.append((insn, cpu, up))
        elif rtype == REC_WARN:
            tr.warnings.append((insn, payload.decode("utf-8", "replace")))
        elif rtype == REC_NFTRACE:
            t, a0, a1, a2, a3 = struct.unpack_from("<5Q", payload, 0)
            tr.nftrace.append(NfTraceRec(insn, cpu, t, (a0, a1, a2, a3)))
        elif rtype == REC_END:
            v = _END.unpack_from(payload, 0)
            drops = (struct.unpack_from("<Q", payload, _END.size)[0]
                     if len(payload) >= _END.size + 8 else None)
            tr.end = TraceEnd(insn, v[0], v[1], v[2], v[3], v[4], v[5],
                              bool(v[6]), drops)

    return tr


def iter_records(path: str | Path) -> Iterator[tuple]:
    p = Path(path)
    with p.open("rb") as stream:
        _read_header(stream, p)
        n = p.stat().st_size
        while stream.tell() + _HDR.size <= n:
            rtype, cpu, rlen, flags, insn = _HDR.unpack(stream.read(_HDR.size))
            if stream.tell() + rlen > n:
                break
            yield (REC_NAMES.get(rtype, f"?{rtype}"), cpu, flags, insn, rlen)
            stream.seek(rlen, 1)
