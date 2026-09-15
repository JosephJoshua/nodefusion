#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.host import dwarf as dwarf_mod  # noqa: E402
from nodefusion.host import layout as layout_mod  # noqa: E402
from nodefusion.host.nfelf import Elf64  # noqa: E402

RCORE = Path("/Users/jsph273/Desktop/Code/tsinghua/rCore-Tutorial-Code-2025S")
KERNEL_ELF = "os/target/riscv64gc-unknown-none-elf/release/os"

CHAPTERS = ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8"]

STRUCTS = [
    "TaskManager", "TaskManagerInner", "TaskControlBlock", "TaskControlBlockInner",
    "ProcessControlBlock", "ProcessControlBlockInner", "Processor",
    "TaskContext", "TrapContext", "AppManager",
    "PidHandle", "KernelStack", "RecycleAllocator",
    "MemorySet", "PageTable", "MapArea", "FrameTracker",
    "PhysPageNum", "VirtPageNum", "PhysAddr", "VirtAddr",
    "OSInode", "OSInodeInner", "Inode", "EasyFileSystem", "Stdin", "Stdout",
    "DiskInode", "BlockCacheManager", "BlockCache",
    "Pipe", "PipeRingBuffer", "SignalFlags", "SignalActions",
    "MutexBlocking", "MutexSpin", "Semaphore", "Condvar",
]

ENUMS = ["TaskStatus", "MapType", "MapPermission", "ProcessStatus"]

GLOBALS = [
    "TASK_MANAGER", "PROCESSOR", "INITPROC", "PID2TCB", "PID2PCB",
    "APP_MANAGER", "KERNEL_SPACE", "FRAME_ALLOCATOR", "PID_ALLOCATOR",
    "ROOT_INODE", "BLOCK_DEVICE", "BLOCK_CACHE_MANAGER",
]


def run(argv: list[str], cwd: Path, check: bool = True) -> tuple[int, str]:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        raise RuntimeError(f"命令失败（{p.returncode}）：{argv}\n{out[-2000:]}")
    return p.returncode, out


_BUILD_CMD = ("set -o pipefail; "
              "cd os && CARGO_NET_GIT_FETCH_WITH_CLI=true "
              "CARGO_PROFILE_RELEASE_DEBUG=2 CARGO_PROFILE_RELEASE_STRIP=none "
              "make build 2>&1 | tail -30")


def run_build(cwd: Path) -> tuple[int, str]:
    p = subprocess.run(_BUILD_CMD, shell=True, cwd=cwd,
                       capture_output=True, text=True,
                       executable="/bin/bash")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


@dataclass
class ChapterReport:
    chapter: str
    built: bool
    build_error: str = ""
    text_size: int | None = None
    structs: dict = None
    enums: dict = None
    globals_: dict = None
    src_files: int = 0
    layout: dict = None

    def to_json(self) -> dict:
        return {
            "chapter": self.chapter, "built": self.built,
            "build_error": self.build_error, "text_size": self.text_size,
            "src_files": self.src_files,
            "structs": self.structs or {}, "enums": self.enums or {},
            "globals": self.globals_ or {},
            "layout": self.layout or {},
        }


def survey_one(ch: str, *, rebuild: bool = True) -> ChapterReport:
    rep = ChapterReport(chapter=ch, built=False)

    run(["git", "checkout", "-q", ch], RCORE)
    _, out = run(["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "os/src"], RCORE)
    rep.src_files = len([l for l in out.splitlines() if l.strip()])

    if rebuild:
        elf = RCORE / KERNEL_ELF
        elf.unlink(missing_ok=True)

        code, out = run_build(RCORE)

        if not elf.exists():
            rep.build_error = (f"make 退出码 {code}，且内核产物不存在 —— "
                               f"这一章的数据完全不可用\n" + out[-1500:])
            return rep
        if code != 0:
            rep.build_error = (
                f"make 退出码 {code}，但内核 ELF 已生成（内核目标排在 fs-img 之前）。"
                f"结构体勘察结果有效；失败的是内核之外的部分，"
                f"该章**无法录制**（缺 fs.img）。\n" + out[-1500:])

    elf_path = RCORE / KERNEL_ELF
    if not elf_path.exists():
        rep.build_error = f"找不到 {elf_path}"
        return rep

    e = Elf64(elf_path)
    for s in e._sections:
        if s.get("name") == ".text":
            rep.text_size = s["size"]

    di = dwarf_mod.DwarfInfo(elf_path, elf=e)
    rep.built = True

    rep.structs = {}
    for name in STRUCTS:
        lay = di.find(name)
        if lay is None:
            if name in di.conflicts:
                rep.structs[name] = {"conflict": di.conflicts[name]}
            continue
        rep.structs[name] = {
            "size": lay.size,
            "path": lay.path,
            "fields": dict(sorted(lay.fields.items(), key=lambda kv: kv[1])),
            "field_types": {f: (di.type_of(lay, f) or "?") for f in lay.fields},
        }

    rep.enums = {}
    for name in ENUMS:
        for path, vals in di.enums.items():
            if path == name or path.endswith("::" + name):
                if vals:
                    rep.enums[path] = vals

    rep.globals_ = {}
    for g in GLOBALS:
        hits = [{"sym": s.name, "addr": s.value, "size": s.size}
                for s in e.symbols if g in s.name]
        rep.globals_[g] = hits or None

    try:
        lay = layout_mod.probe_rcore(RCORE, elf_path)
        rep.layout = {
            "kind": lay.consts.get("RCORE_TASKS_KIND"),
            "cap": lay.consts.get("RCORE_TASKS_CAP"),
            "offsets": {k: v for k, v in sorted(lay.offsets.items())
                        if k.startswith("rcore.")},
            "notes": {k: v for k, v in sorted(lay.notes.items())
                      if "task" in k and not k.endswith("_rust_path")},
        }
    except Exception as ex:                                  # noqa: BLE001
        rep.layout = {"error": f"{type(ex).__name__}: {ex}"[:800]}

    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只勘察这些章，逗号分隔")
    ap.add_argument("--no-build", action="store_true", help="不重编，用现有 ELF")
    ap.add_argument("--out", default="nodefusion/tools/chapter_survey.json")
    args = ap.parse_args()

    chapters = [c.strip() for c in args.only.split(",") if c.strip()] or CHAPTERS
    unknown = [c for c in chapters if c not in CHAPTERS]
    if unknown:
        print(f"不认识的章节：{unknown}，已知的是 {CHAPTERS}", file=sys.stderr)
        return 2

    _, orig = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], RCORE)
    orig = orig.strip()
    print(f"原分支 {orig}，跑完会切回去", file=sys.stderr)

    reports = []
    try:
        for ch in chapters:
            print(f"[{ch}] 勘察中…", file=sys.stderr, flush=True)
            try:
                rep = survey_one(ch, rebuild=not args.no_build)
            except Exception as ex:                      # noqa: BLE001
                rep = ChapterReport(chapter=ch, built=False, build_error=str(ex)[:1500])
            reports.append(rep)
            if rep.built and not rep.build_error:
                tag = "ok"
            elif rep.built:
                tag = "内核 ok / 构建有失败（详见 build_error）"
            else:
                first = rep.build_error.splitlines()[0][:90] if rep.build_error else "?"
                tag = f"失败: {first}"
            n_s = len(rep.structs or {})
            lz = rep.layout or {}
            kind = (f"KIND={lz['kind']}" if lz.get("kind") is not None
                    else ("布局判定报错" if lz.get("error") else "KIND=?"))
            n_note = len(lz.get("notes") or {})
            print(f"[{ch}] {tag}  结构体 {n_s} 个  .text={rep.text_size}  "
                  f"{kind}  偏移 {len(lz.get('offsets') or {})} 个  待说明 {n_note} 处",
                  file=sys.stderr, flush=True)
    finally:
        run(["git", "checkout", "-q", orig], RCORE, check=False)
        print(f"已切回 {orig}", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.to_json() for r in reports],
                              ensure_ascii=False, indent=1))
    print(f"结果写到 {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
