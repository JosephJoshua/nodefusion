
from __future__ import annotations

import json
import hashlib
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .cdp import Browser, CdpError


class VideoError(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_evidence_sidecar(result: dict, out_path: Path) -> Path:
    """Write a portable, self-verifying description beside an exported MP4."""
    payload = {
        "format": "nodefusion.video-evidence/1",
        **result,
        "html": Path(result["html"]).name,
        "mp4": Path(result["mp4"]).name,
    }
    payload.pop("sidecar", None)
    out_path = Path(out_path)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return out_path



EVENT_INTEREST = [
    "kernel.panic",
    "proc.exec",
    "proc.fork",
    "vm.copy",
    "trap.page_fault",
    "syscall.enter",
    "sched.switch",
    "phys.alloc",
    "sync.sleep",
    "sync.wakeup",
    "disk.io",
    "log.commit",
    "proc.exit",
    "thread.create",
    "thread.exit",
]

SWEEP_TABS = [
    ("phys", 9.0, "物理内存逐页归属"),
    ("procs", 5.0, "进程与调度"),
    ("vm", 5.0, "虚拟内存与页表"),
]


SUBSYSTEM_TAB = {
    "phys": "phys",
    "vm": "vm", "pagetable": "vm",
    "proc": "procs", "sched": "procs", "task": "procs", "thread": "procs",
}


@dataclass
class Shot:
    label: str
    frames: int
    setup: str = ""
    per_frame: str = ""
    meta: dict = field(default_factory=dict)


def build_storyboard(info: dict, fps: int) -> list[Shot]:
    def F(sec: float) -> int:
        return max(1, int(round(sec * fps)))

    shots: list[Shot] = []
    kinds = set(info.get("kinds") or [])
    compare = bool(info.get("compare"))

    if compare:
        shots.append(Shot("对比总览", F(3.0), "nfExport.tab('compare');",
                          "nfExport.seekBusiest();"))
        shots.append(Shot("对比·随时间演进", F(12.0), "nfExport.tab('compare');",
                          "nfExport.seekProgFrac(t);"))
        shots.append(Shot("对比·指标", F(4.0), "nfExport.tab('metrics');",
                          "nfExport.seekProgFrac(1);"))
        return shots

    shots.append(Shot("概览", F(3.5), "nfExport.tab('overview');",
                      "nfExport.seekBusiest();"))

    for tab, sec, label in SWEEP_TABS:
        shots.append(Shot(f"{label}（{tab}）", F(sec),
                          f"nfExport.tab('{tab}');",
                          "nfExport.seekProgFrac(t);"))

    picks = [k for k in EVENT_INTEREST if k in kinds]
    for kind in picks[:8]:
        shots.append(Shot(f"事件：{kind}", F(2.2),
                          f"nfExport.tab('events');"
                          f"window.__nfPick=nfExport.findEvents({json.dumps(kind)},1)[0];"
                          f"if(window.__nfPick) nfExport.gotoEvent(window.__nfPick.i);",
                          "", {"kind": kind}))

    shots.append(Shot("指标", F(4.0), "nfExport.tab('metrics');",
                      "nfExport.seekProgFrac(1);"))
    if "kernel.panic" in kinds or info.get("outcome") not in ("completed", None):
        shots.append(Shot("控制台", F(3.5), "nfExport.tab('console');", ""))
    return shots


def probe_info(html: Path, log=print) -> dict:
    html = Path(html)
    if not html.is_file():
        raise VideoError(f"找不到报告：{html}")
    with Browser(width=800, height=600, scale=1.0) as br:
        br.navigate(html.resolve().as_uri())
        log(f"  探查 {html.name}…")
        br.wait_for("!!(window.nfExport && window.nfExport.ready())", limit=300.0)
        return br.eval("window.nfExport.info()")


UNCLASSIFIED = "func"


def subsystems(info: dict) -> list[str]:
    return sorted({k.split(".")[0] for k in (info.get("kinds") or []) if "." in k})


def evidence_fields(info: dict, scope: str | None, *, limit: int = 12) -> list[str]:
    """Fields to name in a video's evidence strip, derived from its bundle."""
    inventory = info.get("observed_fields") or {}
    fields = list((inventory.get("events") or {}).get(scope, [])) if scope else []
    if scope in (None, "proc", "task", "thread", "sched"):
        fields.extend(inventory.get("process") or [])
    if scope in (None, "bcache", "disk", "log", "fs", "thread"):
        fields.extend(inventory.get("resources") or [])
    # Preserve stable source order while removing overlaps between groups.
    unique = list(dict.fromkeys(str(x) for x in fields if x))
    if not unique:
        return ["event.kind", "event.count", "event.timestamp"]
    if len(unique) <= limit:
        return unique
    return unique[:limit] + [f"+{len(unique) - limit} more"]


def _install_evidence_overlay(br: Browser, info: dict, scope: str | None) -> None:
    """Put immutable provenance in normal flow on every exported frame."""
    run = ", ".join(info.get("runs") or []) or "unknown"
    sha = info.get("kernel_elf_sha256") or "unknown"
    fields = evidence_fields(info, scope)
    lines = [
        f"Run: {run} | ELF: {sha[:12]} | Scope: {scope or 'all'}",
        "Fields: " + ", ".join(fields),
    ]
    script = """(()=>{
      let d=document.getElementById('nf-video-evidence');
      if(!d){
        d=document.createElement('div');d.id='nf-video-evidence';
        const h=document.querySelector('header');
        h && h.parentNode ? h.parentNode.insertBefore(d,h.nextSibling) : document.body.prepend(d);
      }
      d.textContent=%s;
      Object.assign(d.style,{margin:'0 12px 8px',padding:'7px 10px',background:'rgba(8,12,18,.94)',
        color:'#e6edf3',border:'1px solid #52606d',borderRadius:'4px',
        font:'11px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace',
        whiteSpace:'pre-wrap',pointerEvents:'none'});
    })()""" % json.dumps("\n".join(lines))
    br.eval(script)


def build_subsystem_storyboard(info: dict, fps: int, prefix: str) -> list[Shot]:
    def F(sec: float) -> int:
        return max(1, int(round(sec * fps)))

    kinds = [k for k in (info.get("kinds") or []) if k.split(".")[0] == prefix]
    if not kinds:
        raise VideoError(
            f"这次运行里没有 {prefix!r} 这个子系统的事件。有的是："
            + "、".join(subsystems(info)))

    tab = SUBSYSTEM_TAB.get(prefix, "events")
    shots = [Shot(f"{prefix}：概览", F(2.5), "nfExport.tab('overview');",
                  "nfExport.seekBusiest();"),
             Shot(f"{prefix}：随时间演进", F(6.0),
                  f"nfExport.tab('{tab}');", "nfExport.seekProgFrac(t);")]
    for kind in kinds[:12]:
        shots.append(Shot(f"事件：{kind}", F(2.2),
                          f"nfExport.tab('events');"
                          f"window.__nfPick=nfExport.findEvents({json.dumps(kind)},1)[0];"
                          f"if(window.__nfPick) nfExport.gotoEvent(window.__nfPick.i);",
                          "", {"kind": kind}))
    shots.append(Shot("指标", F(3.0), "nfExport.tab('metrics');",
                      "nfExport.seekProgFrac(1);"))
    return shots


def resolve_storyboard(storyboard, info: dict, fps: int) -> list[Shot]:
    if storyboard is None:
        return build_storyboard(info, fps)
    if callable(storyboard):
        return storyboard(info, fps)
    return list(storyboard)



def render_frames(html: Path, out_dir: Path, *, fps: int, width: int, height: int,
                  storyboard=None, evidence_scope: str | None = None,
                  log=print) -> tuple[list[Path], dict]:
    if not html.is_file():
        raise VideoError(f"找不到报告：{html}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.png"):
        old.unlink()

    frames: list[Path] = []
    with Browser(width=width, height=height, scale=1.0) as br:
        br.navigate(html.resolve().as_uri())
        log(f"  打开 {html.name}（{html.stat().st_size / 1e6:.1f} MB），等待数据解压…")
        try:
            br.wait_for("!!(window.nfExport && window.nfExport.ready())", limit=300.0)
        except CdpError as e:
            try:
                note = br.eval("(document.getElementById('loading')||{}).textContent") or ""
                has = br.eval("typeof window.nfExport")
            except CdpError:
                note, has = "(取不到)", "(取不到)"
            raise VideoError(
                f"{e}\n  页面提示：{note.strip()[:300]}\n"
                f"  window.nfExport = {has}"
                + ("\n  → 前端脚本没执行完，多半是 app.js 有语法错误。"
                   if has == "undefined" else "")) from e
        info = br.eval("window.nfExport.info()")
        _install_evidence_overlay(br, info, evidence_scope)
        log(f"  运行 {info['runs']}　程序 {info['program']}　"
            f"快照 {info['states']}　事件 {info['events']}")

        shots = resolve_storyboard(storyboard, info, fps)
        total = sum(s.frames for s in shots)
        log(f"  分镜 {len(shots)} 段，共 {total} 帧 @ {fps}fps ≈ {total / fps:.1f}s")

        n_done = 0
        t0 = time.time()
        for shot in shots:
            if shot.setup:
                br.eval(f"(()=>{{{shot.setup}}})()")
            for i in range(shot.frames):
                n = shot.frames
                t = i / (n - 1) if n > 1 else 1.0
                body = shot.per_frame or ""
                js = (
                    "(async()=>{"
                    f"const i={i},n={n},t={t!r};"
                    f"{body}"
                    "await window.nfExport.settle();return 1;})()"
                )
                br.eval(js, await_promise=True)
                png = br.screenshot()
                p = out_dir / f"f_{len(frames):05d}.png"
                p.write_bytes(png)
                frames.append(p)
                n_done += 1
            log(f"    · {shot.label}：{shot.frames} 帧　"
                f"（{n_done}/{total}，{time.time() - t0:.0f}s）")

    if not frames:
        raise VideoError("一帧都没渲染出来")
    return frames, info



def _native_ffmpeg() -> str | None:
    env = os.environ.get("NF_FFMPEG")
    if env and Path(env).is_file():
        return env
    return shutil.which("ffmpeg")


def encode(frames_dir: Path, out_mp4: Path, fps: int, log=print) -> Path:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if out_mp4.exists():
        out_mp4.unlink()

    args = [
        "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(fps),
        "-i", "f_%05d.png",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]

    exe = _native_ffmpeg()
    if exe:
        log(f"  编码（本机 ffmpeg）→ {out_mp4.name}")
        r = subprocess.run([exe] + args + [str(out_mp4)], cwd=frames_dir,
                           stdin=subprocess.DEVNULL, capture_output=True)
        if r.returncode != 0:
            raise VideoError("ffmpeg 编码失败：\n" + r.stderr.decode("utf-8", "replace")[:2000])
    elif platform.system() == "Windows":
        log(f"  编码（WSL ffmpeg）→ {out_mp4.name}")
        from .wslenv import Wsl, WslError
        wsl = Wsl()
        chk = wsl.run("command -v ffmpeg || true", check=False)
        if not chk.stdout.strip():
            raise VideoError(
                "Windows 和 WSL 里都找不到 ffmpeg，无法生成 MP4。\n"
                "  WSL 里装一下即可：wsl -d Ubuntu-24.04 -u root apt-get install -y ffmpeg\n"
                "  或把 Windows 版 ffmpeg.exe 放进 PATH / 用 NF_FFMPEG 指过去。\n"
                "  （playwright 自带的 ffmpeg 只能编 VP8/webm，PowerPoint 不认，故不使用）")
        quoted = " ".join(f"'{a}'" for a in args)
        script = (f"cd '{wsl.path(frames_dir)}' && "
                  f"ffmpeg {quoted} '{wsl.path(out_mp4)}'")
        try:
            wsl.run(script, timeout=1800)
        except WslError as e:
            raise VideoError(str(e)) from e
    else:
        raise VideoError(
            "找不到 ffmpeg，无法生成 MP4。\n"
            "  macOS：brew install ffmpeg\n"
            "  Linux：apt-get install -y ffmpeg\n"
            "  或用 NF_FFMPEG 指向可执行文件。\n"
            "  （playwright 自带的 ffmpeg 只能编 VP8/webm，PowerPoint 不认，故不使用）")

    if not out_mp4.is_file() or out_mp4.stat().st_size == 0:
        raise VideoError(f"编码后没有产出有效文件：{out_mp4}")
    return out_mp4



def make_video(html: Path, out_mp4: Path, *, fps: int = 24, width: int = 1600,
               height: int = 900, keep_frames: bool = False, storyboard=None,
               evidence_scope: str | None = None, log=print) -> dict:
    html = Path(html)
    out_mp4 = Path(out_mp4)
    frames_dir = out_mp4.parent / ("_frames_" + out_mp4.stem)

    log(f"[video] {html}")
    attempts = 2
    for k in range(1, attempts + 1):
        try:
            frames, info = render_frames(html, frames_dir, fps=fps, width=width,
                                         height=height, storyboard=storyboard,
                                         evidence_scope=evidence_scope,
                                         log=log)
            break
        except CdpError as e:
            if k == attempts:
                raise VideoError(f"渲染帧失败（重试 {attempts} 次）：{e}") from e
            log(f"  [重试 {k}/{attempts - 1}] 浏览器侧出错，重开一次：{e}")
    encode(frames_dir, out_mp4, fps, log=log)
    size = out_mp4.stat().st_size

    if not keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    result = {
        "html": str(html), "mp4": str(out_mp4), "frames": len(frames),
        "fps": fps, "seconds": len(frames) / fps, "bytes": size,
        "mp4_sha256": _sha256(out_mp4),
        "width": width, "height": height,
        "evidence_scope": evidence_scope or "all",
        "evidence_fields": evidence_fields(info, evidence_scope),
        "info": info,
    }
    sidecar = out_mp4.with_suffix(".json")
    write_evidence_sidecar(result, sidecar)
    result["sidecar"] = str(sidecar)
    log(f"[video] 完成：{out_mp4}　{size / 1e6:.2f} MB　"
        f"{len(frames)} 帧 / {fps}fps = {len(frames) / fps:.1f}s　{width}x{height}")
    log(f"[video] 凭据：{sidecar}")
    return result
