"""Measure the QEMU recorder or trace decoder without report rendering.

Run from the repository root:
    python -m scripts.benchmark_trace decode nodefusion/runs/NAME/trace.nfb --indexed --compact
    python -m scripts.benchmark_trace qemu --kernel /path/to/image --plugin nodefusion/plugin/libnf.dylib --seconds 3

QEMU runs are time-bounded and shut down through QMP. Compare instruction
counts and snapshot counts alongside RSS: elapsed time alone includes shutdown.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _rss_bytes(usage) -> int:
    return usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)


def _qmp_quit(path: Path) -> None:
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(str(path))
        with sock.makefile("rwb", buffering=0) as io:
            io.readline()
            io.write(b'{"execute":"qmp_capabilities"}\r\n')
            io.readline()
            io.write(b'{"execute":"quit"}\r\n')


def record(args) -> dict:
    if args.trace_out and args.trace_out.exists():
        raise FileExistsError(args.trace_out)
    with tempfile.TemporaryDirectory(prefix="nf-bench-") as work:
        trace = Path(work) / "trace.nfb"
        qmp = Path(work) / "qmp.sock"
        plugin = f"{args.plugin},out={trace},sample={args.sample},snap={args.snap},ramsize={args.ram},maxram={args.maxram}"
        if args.watchlist:
            plugin += f",watch={args.watchlist}"
        cmd = [args.qemu, "-M", "virt", "-bios", "default",
               "-kernel", str(args.kernel), "-m", f"{args.ram // 1048576}M",
               "-smp", str(args.cpus), "-nographic",
               "-qmp", f"unix:{qmp},server=on,wait=off", "-plugin", plugin]
        if not args.no_icount:
            cmd.extend(["-icount", "shift=3"])
        start = time.perf_counter()
        with tempfile.TemporaryFile() as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=log)
            usage = None
            try:
                deadline = start + args.seconds
                while time.perf_counter() < deadline:
                    pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                    if pid:
                        proc.returncode = os.waitstatus_to_exitcode(status)
                        break
                    time.sleep(min(0.05, max(0, deadline - time.perf_counter())))
                if proc.returncode is None:
                    try:
                        _qmp_quit(qmp)
                    except OSError:
                        proc.terminate()
            finally:
                if proc.returncode is None:
                    deadline = time.perf_counter() + 10
                    while time.perf_counter() < deadline:
                        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                        if pid:
                            proc.returncode = os.waitstatus_to_exitcode(status)
                            break
                        time.sleep(0.05)
                    if proc.returncode is None:
                        proc.terminate()
                        _, status, usage = os.wait4(proc.pid, 0)
                        proc.returncode = os.waitstatus_to_exitcode(status)
                log.seek(0)
                stderr = log.read().decode("utf-8", "replace")
        from nodefusion.host import nftrace
        decoded = None
        trace_error = None
        if trace.exists():
            try:
                decoded = nftrace.load(trace, want_pages=False)
            except nftrace.TraceError as exc:
                trace_error = str(exc)
        if args.trace_out and trace.exists():
            shutil.copyfile(trace, args.trace_out)
        return {
            "mode": "qemu", "wall_seconds": round(time.perf_counter() - start, 3),
            "peak_rss_bytes": _rss_bytes(usage) if usage else None,
            "trace_bytes": trace.stat().st_size if trace.exists() else 0,
            "exit_code": proc.returncode,
            "total_insns": decoded.total_insns if decoded else None,
            "samples": len(decoded.samples) if decoded else None,
            "snapshots": len(decoded.snapshots) if decoded else None,
            "watch_hits": len(decoded.watch_hits) if decoded else None,
            "snapshot_ram_bytes": decoded.end.ram_bytes if decoded and decoded.end else None,
            "snapshot_reads": int(decoded.meta.get("nf.snapshot_reads", 0)) if decoded else None,
            "snapshot_fallbacks": int(decoded.meta.get("nf.snapshot_fallbacks", 0)) if decoded else None,
            "snapshot_us": int(decoded.meta.get("nf.snapshot_us", 0)) if decoded else None,
            "complete": bool(decoded and decoded.end),
            "trace_error": trace_error,
            "plugin_tail": stderr.strip().splitlines()[-2:],
        }


def decode(args) -> dict:
    from nodefusion.host import nftrace
    start = time.perf_counter()
    trace = nftrace.load(args.trace, indexed_pages=args.indexed,
                         compact_watch_hits=args.compact)
    if args.indexed:
        for snapshot in trace.snapshots:
            for _idx, _page in snapshot.pages.items():
                pass
    return {
        "mode": "decode", "indexed": args.indexed, "compact": args.compact,
        "wall_seconds": round(time.perf_counter() - start, 3),
        "peak_rss_bytes": _rss_bytes(resource.getrusage(resource.RUSAGE_SELF)),
        "trace_bytes": args.trace.stat().st_size,
        "total_insns": trace.total_insns,
        "samples": len(trace.samples), "snapshots": len(trace.snapshots),
        "watch_hits": len(trace.watch_hits),
        "pages": sum(len(s.pages) for s in trace.snapshots),
        "complete": bool(trace.end),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("decode")
    d.add_argument("trace", type=Path)
    d.add_argument("--indexed", action="store_true")
    d.add_argument("--compact", action="store_true")
    q = sub.add_parser("qemu")
    q.add_argument("--kernel", type=Path, required=True)
    q.add_argument("--plugin", type=Path, required=True)
    q.add_argument("--watchlist", type=Path)
    q.add_argument("--qemu", default="qemu-system-riscv64")
    q.add_argument("--seconds", type=float, default=3)
    q.add_argument("--ram", type=int, default=128 * 1048576)
    q.add_argument("--maxram", type=int, default=64 * 1048576)
    q.add_argument("--sample", type=int, default=200000)
    q.add_argument("--snap", type=int, default=5000000)
    q.add_argument("--cpus", type=int, default=1)
    q.add_argument("--no-icount", action="store_true")
    q.add_argument("--trace-out", type=Path,
                   help="保留轨迹用于逐页比对；目标文件必须不存在")
    args = parser.parse_args()
    print(json.dumps(decode(args) if args.mode == "decode" else record(args),
                     indent=2))


if __name__ == "__main__":
    main()
