
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import sys
from pathlib import Path

from . import bundle as bundle_mod
from . import kernels as kernels_mod
from . import render as render_mod
from ..model.manifest import ManifestError
from .analyze import analyze
from .record import NO_PROGRAM, RunConfig, record
from .shell import pick_shell, plugin_filename

REPO = Path(__file__).resolve().parents[2]
DEFAULT_RUNS = REPO / "nodefusion" / "runs"

# JSONL is a reusable interchange artifact, but it duplicates every decoded
# event.  Keep producing ordinary streams automatically while requiring an
# explicit request for very large ones.  The binary trace remains authoritative.
AUTO_EVENT_STREAM_MAX_BYTES = 256 * 1024 * 1024
EVENT_STREAM_DISK_RESERVE_BYTES = 512 * 1024 * 1024


def _path(s: str) -> Path:
    if platform.system() == "Windows" and s.startswith("/mnt/"):
        from .wslenv import to_win_path
        return to_win_path(s).resolve()
    return Path(s).resolve()


def _kv(pairs: list[str]) -> dict[str, str]:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"构建参数要写成 KEY=VALUE，收到的是 {p!r}")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def cmd_record(args) -> int:
    snap_insns = args.snap_insns
    boot_snapshots = args.boot_snapshots
    snap_start = args.snap_start
    if args.profile == "boot":
        if snap_start is None:
            snap_start = 0
        if snap_insns is None:
            snap_insns = 5_000_000
    elif args.profile == "uniform":
        if snap_start is None:
            snap_start = 0
    elif args.profile == "program":
        if boot_snapshots is None:
            boot_snapshots = 20

    program = args.program or NO_PROGRAM
    default_name = (program.replace(" ", "_").replace("/", "_")
                    if args.program else _path(args.kernel).name)

    cfg = RunConfig(
        kernel_dir=_path(args.kernel),
        program=program,
        kernel_kind=args.kernel_kind,
        name=args.name or default_name,
        out_root=_path(args.runs),
        cpus=args.cpus,
        lab_stage=args.lab_stage,
        make_vars=_kv(args.make_var),
        timeout=args.timeout,
        boot_timeout=args.boot_timeout,
        sample_insns=args.sample_insns,
        snap_insns=snap_insns,
        target_snapshots=args.snapshots,
        boot_snap_insns=args.boot_snap_insns,
        boot_snapshots=boot_snapshots,
        snap_start=snap_start,
        max_ram_bytes=args.max_ram_bytes,
        stdin_after=[(s.rsplit("=", 1)[0], s.rsplit("=", 1)[1].replace("\\n", "\n"))
                     for s in (args.stdin_after or []) if "=" in s],
        stdin_timeout=args.stdin_timeout,
        icount_shift=args.icount_shift,
        watch_all=args.watch_all,
        watch_subsystems=tuple(args.watch_subsystem),
        watch_from_table=args.watch_from_table,
        no_build=args.no_build,
    )
    if args.watch_from_manifest:
        print("[NodeFusion] 注意：--watch-from-manifest 已经是默认行为，"
              "这个选项不再有作用，可以去掉。")
    print(f"[NodeFusion] 录制 {cfg.name}：程序 ={cfg.program!r} 内核={cfg.kernel_dir.name}")
    r = record(cfg)
    print(f"[NodeFusion] 结局：{r.outcome}")
    why = r.manifest.get("trace_incomplete_reason")
    if why:
        print(f"[NodeFusion] 警告：这次录制没有正常收尾，轨迹很可能缺一段。{why}",
              file=sys.stderr)
    print(f"[NodeFusion] 轨迹：{r.trace_path} ({r.trace_path.stat().st_size/1e6:.1f} MB)")
    print(f"[NodeFusion] 运行目录：{r.run_dir}")
    for w in r.manifest.get("record_warnings") or []:
        print(f"[NodeFusion] 注意：{w}")
    if r.manifest["watchlist_missing"]:
        print(f"[NodeFusion] 这个内核里不存在的被观察函数："
              f"{', '.join(r.manifest['watchlist_missing'])}")
    if not args.no_render:
        return cmd_render(argparse.Namespace(
            run=[r.run_dir.name], runs=str(cfg.out_root), out=None, title=None,
            event_stream=getattr(args, "event_stream", "auto")))
    return 0


def _load(run_names: list[str], runs_root: Path, *, announce: bool = True):
    out = []
    for n in run_names:
        d = _path(n) if n.startswith('/mnt/') else Path(n)
        if not d.exists():
            d = runs_root / n
        if not (d / "manifest.json").exists():
            raise SystemExit(f"找不到运行记录：{d}（缺 manifest.json）")
        if announce:
            print(f"[NodeFusion] 分析 {d.name} …")
        a = analyze(d)
        if announce:
            print(f"           状态快照 {len(a.states)} 个，事件 {len(a.events)} 条")
        out.append(a)
    return out


def _write_event_stream(a, mode: str) -> None:
    """Write one optional JSONL artifact without risking an ENOSPC surprise."""
    p = a.run_dir / "events.jsonl"
    if mode == "never":
        print(f"[NodeFusion] 事件流：已按要求跳过（{p}）")
        return

    estimated = a.estimate_event_stream_bytes()
    free = shutil.disk_usage(p.parent).free
    if mode == "auto" and estimated > AUTO_EVENT_STREAM_MAX_BYTES:
        print("[NodeFusion] 事件流：自动跳过；预计 "
              f"{estimated/1e6:.1f} MB，超过自动导出上限 "
              f"{AUTO_EVENT_STREAM_MAX_BYTES/1e6:.1f} MB。"
              "需要完整 JSONL 时重跑 --event-stream always。")
        return
    if estimated + EVENT_STREAM_DISK_RESERVE_BYTES > free:
        message = ("事件流预计需要 "
                   f"{estimated/1e6:.1f} MB，但当前只有 {free/1e6:.1f} MB 可用；"
                   f"还必须保留 {EVENT_STREAM_DISK_RESERVE_BYTES/1e6:.1f} MB 安全余量")
        if mode == "auto":
            print(f"[NodeFusion] 事件流：自动跳过；{message}。"
                  "可释放空间后重跑 --event-stream always。")
            return
        raise SystemExit(f"拒绝写 events.jsonl：{message}")

    a.write_event_stream(p)
    print(f"[NodeFusion] 事件流：{p} ({p.stat().st_size/1e6:.1f} MB)")


def cmd_render(args) -> int:
    runs_root = _path(args.runs)
    analyses = _load(args.run, runs_root)

    if args.out:
        out = _path(args.out)
    elif len(analyses) == 1:
        out = analyses[0].run_dir / f"{analyses[0].manifest['run_name']}.html"
    else:
        names = "-vs-".join(a.manifest["run_name"] for a in analyses)
        out = runs_root / f"compare-{names}.html"

    p = render_mod.render(analyses, out, title=args.title)
    print(f"[NodeFusion] HTML：{p} ({p.stat().st_size/1e6:.1f} MB)")
    # HTML is the primary output of this command.  Write the potentially much
    # larger interchange stream only after a valid report is safely in place.
    mode = getattr(args, "event_stream", "auto")
    for a in analyses:
        _write_event_stream(a, mode)
    return 0


def cmd_audit(args) -> int:
    """Exit nonzero unless every requested run has complete applicable coverage."""
    analyses = _load(args.run, _path(args.runs), announce=not args.json)
    runs = []
    for a in analyses:
        result = bundle_mod.coverage(a)
        runs.append({"run": a.manifest.get("run_name") or a.run_dir.name,
                     "coverage": result})
    report = {
        "schema": "nodefusion.coverage-audit/1",
        "complete": all(r["coverage"]["status"] == "complete" for r in runs),
        "runs": runs,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for item in runs:
            cov = item["coverage"]
            metrics = cov["metrics"]
            print(f"[NodeFusion] {item['run']}：{cov['status']} "
                  f"{cov['percent']:.2f}%（指标 {metrics['covered']}/"
                  f"{metrics['applicable']}，blockers={len(cov['blockers'])}）")
            for blocker in cov["blockers"]:
                print("  - " + json.dumps(blocker, ensure_ascii=False, sort_keys=True))
    return 0 if report["complete"] else 1


def cmd_video(args) -> int:
    from . import video as video_mod
    from .cdp import CdpError

    runs_root = _path(args.runs)
    if args.html:
        html = _path(args.html)
    elif args.run:
        d = runs_root / args.run
        if not d.is_dir():
            d = _path(args.run)
        cand = sorted(d.glob("*.html"))
        if not cand:
            raise SystemExit(f"{d} 里没有报告 HTML，先跑一次 render")
        html = cand[0]
    else:
        raise SystemExit("要么给 --run，要么给 --html")

    out = _path(args.out) if args.out else html.with_suffix(".mp4")

    jobs: list[tuple[Path, object, str | None]] = [(out, None, None)]
    if args.section:
        try:
            info = video_mod.probe_info(html)
        except (video_mod.VideoError, CdpError) as e:
            print(f"[NodeFusion] 读不出这次运行有哪些子系统：{e}", file=sys.stderr)
            return 1
        have = video_mod.subsystems(info)
        if args.section == ["all"]:
            want = [s for s in have if s != video_mod.UNCLASSIFIED]
            if video_mod.UNCLASSIFIED in have:
                n = sum(1 for k in info.get("kinds") or []
                        if k.startswith(video_mod.UNCLASSIFIED + "."))
                print(f"[NodeFusion] 跳过 {video_mod.UNCLASSIFIED}（{n} 种还没给语义的"
                      f"函数事件）。要看就显式 --section {video_mod.UNCLASSIFIED}。")
        else:
            want = args.section
        missing = [s for s in want if s not in have]
        if missing:
            print(f"[NodeFusion] 这次运行里没有这些子系统："
                  f"{'、'.join(missing)}；有的是：{'、'.join(have)}", file=sys.stderr)
            return 1
        if args.out and len(want) > 1:
            print(f"[NodeFusion] 出多段时 -o 不生效，文件名按子系统取。",
                  file=sys.stderr)
        stem = out.with_suffix("").name
        jobs = [(out if (args.out and len(want) == 1)
                 else out.parent / f"{stem}-{s}.mp4",
                 (lambda s: lambda i, f: video_mod.build_subsystem_storyboard(i, f, s))(s), s)
                for s in want]
        print(f"[NodeFusion] 子系统：{'、'.join(want)}（共 {len(jobs)} 段）")

    made = []
    for dst, board, scope in jobs:
        try:
            made.append(video_mod.make_video(
                html, dst, fps=args.fps, width=args.width, height=args.height,
                keep_frames=args.keep_frames, storyboard=board,
                evidence_scope=scope))
        except (video_mod.VideoError, CdpError) as e:
            print(f"[NodeFusion] 导出视频失败：{e}", file=sys.stderr)
            for r in made:
                print(f"[NodeFusion] （已出：{r['mp4']}）", file=sys.stderr)
            return 1

    for dest in args.copy_to or []:
        dd = _path(dest)
        dd.mkdir(parents=True, exist_ok=True)
        for r in made:
            for key in ("mp4", "sidecar"):
                target = dd / Path(r[key]).name
                shutil.copy2(r[key], target)
                print(f"[NodeFusion] 已复制到 {target}")

    for r in made:
        print(f"[NodeFusion] MP4：{r['mp4']}　"
              f"{r['seconds']:.1f}s　{r['bytes']/1e6:.2f} MB")
    return 0


def _check_host_gcc() -> str | None:
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("gcc"):
        return "没有 gcc —— xv6 的 mkfs 是宿主工具，要宿主编译器"
    src = ("struct s { char n[8] __attribute__((nonstring)); };\n"
           "int main(void){ return sizeof(struct s); }\n")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.c"
        f.write_text(src, encoding="utf-8")
        p = subprocess.run(["gcc", "-Werror", "-Wall", "-o", str(Path(d) / "t"),
                            str(f)], capture_output=True, text=True)
    if p.returncode == 0:
        return None
    first = next((ln for ln in (p.stderr or "").splitlines() if "error" in ln),
                 "(编译器没给出可读的错误行)")
    return f"编不过 xv6 的宿主工具：{first.strip()}"


def cmd_doctor(args) -> int:
    sh = pick_shell(getattr(args, "distro", None))
    desc = sh.describe()
    info = sh.check_env(required=(), optional=(
        "qemu-system-riscv64", "riscv64-unknown-elf-gcc", "cargo", "ffmpeg"))
    print(f"[NodeFusion] 录制环境（{desc.get('kind')}"
          + (f" / {desc.get('platform')} {desc.get('machine')}"
             if desc.get("platform") else f" / {desc.get('distro')}") + "）：")
    for k, v in info.items():
        print(f"  {k:26} {v or '(缺)'}")
    print(f"  插件产物名 → {plugin_filename()}")
    if not info.get("qemu-system-riscv64"):
        print("  → 没有 qemu-system-riscv64，无法录制。")
    if not info.get("riscv64-unknown-elf-gcc"):
        print("  → 没有 riscv64 交叉 gcc：xv6 编不了；rCore 用 cargo，不受影响。")
    if desc.get("kind") == "local":
        bad = _check_host_gcc()
        print(f"  宿主 gcc（编 mkfs 用） → {bad or 'OK'}")
        if bad:
            print("  → xv6 的 Makefile 里 mkfs 那条写死了 `gcc -Werror`，没有变量"
                  "可以覆盖，所以 make 会停在这儿、根本编不到内核。")
            print("     不改内核树的做法：装一个真 GCC，再把它以 `gcc` 的名字"
                  "放到 PATH 前面，例如")
            print("       brew install gcc")
            print("       mkdir -p ~/.nf-bin && ln -sf $(brew --prefix)/bin/gcc-14"
                  " ~/.nf-bin/gcc")
            print("       PATH=~/.nf-bin:$PATH nodefusion record ...")
    ver = info.get("QEMUVER", "")
    if not re.search(r"version (1[0-9]|[2-9][0-9])\.", ver):
        print("  提示：当前 QEMU 版本较旧时，插件读寄存器/读 guest 内存的能力可能受限，"
              "详见 NodeFusion_环境准备说明.md 的降级方案一节。")
    return 0


def _recordable_kinds() -> list[str]:
    try:
        return kernels_mod.recordable()
    except Exception:
        return []


def _add_event_stream_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--event-stream", choices=("auto", "always", "never"), default="auto",
        help="events.jsonl 导出策略：auto 对大文件或低磁盘空间自动跳过（默认），"
             "always 强制导出，never 不导出")
    parser.add_argument(
        "--no-event-stream", dest="event_stream", action="store_const", const="never",
        help="--event-stream never 的简写")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="nodefusion", description="NodeFusion：面向任意 xv6 程序的运行观测与可视化")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="录制一次运行")
    r.add_argument("--program", help="要在 guest shell 里运行的命令，例如 cowtest。"
                                     "无 shell 的内核（rCore）留空")
    r.add_argument("--name", help="运行名（默认取程序名 / 内核目录名）")
    r.add_argument("--kernel", required=True, help="被观察内核的工程目录")
    r.add_argument("--kernel-kind", default=None, metavar="种类",
                   help="内核种类。默认按目录里的特征文件自动识别"
                        + (f"（能录的：{'/'.join(_recordable_kinds())}）"
                           if _recordable_kinds() else ""))
    r.add_argument("--runs", default=str(DEFAULT_RUNS), help="运行记录存放目录")
    r.add_argument("--cpus", type=int, default=1)
    r.add_argument("--lab-stage", type=int, default=None)
    r.add_argument("--make-var", action="append", default=[],
                   help="额外的 make 变量，形如 NF_FORK_COPY_MODE=COW，可重复")
    r.add_argument("--timeout", type=float, default=300.0)
    r.add_argument("--boot-timeout", type=float, default=90.0)
    r.add_argument("--sample-insns", type=int, default=200_000,
                   help="周期采样间隔；设为 0 可关闭周期采样")
    r.add_argument("--snap-insns", type=int, default=None,
                   help="内存快照间隔（指令数）。不给就先跑一次校准，自动选")
    r.add_argument("--snapshots", type=int, default=120, help="程序段目标快照帧数")
    r.add_argument("--boot-snap-insns", type=int, default=None,
                   help="启动段快照间隔（指令数）。不给则自动")
    r.add_argument("--boot-snapshots", type=int, default=None,
                   help="启动段目标快照帧数。想看开机过程就把它调大")
    r.add_argument("--snap-start", type=int, default=None,
                   help="从这个指令号起改用程序段间隔；给 0 表示全程用同一间隔")
    r.add_argument("--max-ram-bytes", type=int, default=1024 * 1024 * 1024,
                   help="内存快照总字节上限。到顶后插件停止落页、继续记事件（默认 1 GiB）。"
                        "录不会自己停下来的 workload 时调小它")
    r.add_argument("--profile", choices=["program", "boot", "uniform"], default=None,
                   help="快照策略预设：program=默认（启动稀疏、程序段密集）；"
                        "boot=看开机过程（全程密集）；uniform=全程均匀")
    r.add_argument("--icount-shift", type=int, default=3)
    r.add_argument("--watch-all", action="store_true",
                   help="盯住内核里全部函数（轨迹会显著变大）")
    r.add_argument("--watch-from-table", action="store_true",
                   help="观察点退回按内核写死的名单选。默认走 manifest 规则，"
                        "规则是名单的超集（xv6 141 对 72、rCore 92 对 59）。"
                        "只有 xv6 和 rcore 有名单，别的内核给了会报错")
    r.add_argument("--watch-from-manifest", action="store_true",
                   help=argparse.SUPPRESS)
    r.add_argument("--watch-subsystem", action="append", default=[],
                   metavar="子系统",
                   help="只武装这个子系统的 [[watch]] 规则，可重复。"
                        "子系统名来自 manifest（如 task / syscall / trap），"
                        "写错会当场报错并列出这份 manifest 声明了哪些。"
                        "录墙钟长的 workload 时用来压观察点密度："
                        "StarryOS 全开是 1825 个点，rCore ch7 才 92 个")
    r.add_argument("--no-build", action="store_true",
                   help="不编译，直接用现成的内核产物。会拆掉'先删再编再检查'"
                        "这道保险（构建脚本末尾的 | tail 会吞掉 make 的退出码），"
                        "所以录到的可能是任何时候留下的二进制。"
                        "只在必须跟已有轨迹保持同一个 build 时用")
    r.add_argument("--stdin-after", action="append", default=[], metavar="标记=文本",
                   help="等控制台出现<标记>后往 guest 送<文本>。"
                        "给那种 setup 完成后等外部信号才开跑的程序用，"
                        "例如 --stdin-after 'phase=armed=G'。可重复；"
                        "文本里的 \\n 会被当成回车")
    r.add_argument("--stdin-timeout", type=float, default=120.0)
    r.add_argument("--no-render", action="store_true")
    _add_event_stream_option(r)
    r.set_defaults(func=cmd_record)

    d = sub.add_parser("render", help="把运行记录渲染成自包含 HTML")
    d.add_argument("--run", action="append", required=True, help="运行名或目录，可重复")
    d.add_argument("--runs", default=str(DEFAULT_RUNS))
    d.add_argument("-o", "--out")
    d.add_argument("--title")
    _add_event_stream_option(d)
    d.set_defaults(func=cmd_render)

    c = sub.add_parser("compare", help="把两次运行渲染成对比报告")
    c.add_argument("--run", action="append", required=True)
    c.add_argument("--runs", default=str(DEFAULT_RUNS))
    c.add_argument("-o", "--out")
    c.add_argument("--title")
    _add_event_stream_option(c)
    c.set_defaults(func=cmd_render)

    a = sub.add_parser("audit", help="严格检查运行记录的适用项覆盖率；不完整时退出非零")
    a.add_argument("--run", action="append", required=True, help="运行名或目录，可重复")
    a.add_argument("--runs", default=str(DEFAULT_RUNS))
    a.add_argument("--json", action="store_true", help="只向 stdout 输出机器可读 JSON")
    a.set_defaults(func=cmd_audit)

    v = sub.add_parser("video", help="把报告 HTML 导出成 MP4（PPT 用）")
    v.add_argument("--run", help="运行名，用它目录里的报告")
    v.add_argument("--html", help="直接指定报告 HTML（对比报告用这个）")
    v.add_argument("--runs", default=str(DEFAULT_RUNS))
    v.add_argument("-o", "--out")
    v.add_argument("--fps", type=int, default=24)
    v.add_argument("--width", type=int, default=1600)
    v.add_argument("--height", type=int, default=900)
    v.add_argument("--section", action="append", metavar="子系统",
                   help="按子系统各出一段（vm / phys / sched / syscall / trap …），"
                        "可重复；写 all 表示这次运行里出现过的全部。"
                        "子系统名来自事件类型的第一段，不是写死的表。")
    v.add_argument("--keep-frames", action="store_true", help="保留中间 PNG 帧")
    v.add_argument("--copy-to", action="append",
                   help="导出后额外复制到的目录（比如 PPT 工程的 public/），可重复")
    v.set_defaults(func=cmd_video)

    doc = sub.add_parser("doctor", help="检查录制侧环境")
    doc.set_defaults(func=cmd_doctor)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (kernels_mod.ProfileError, ManifestError) as e:
        print(f"[NodeFusion] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
