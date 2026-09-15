
from __future__ import annotations

import ast
import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .shell import Shell


class LayoutError(Exception):
    pass


_FIELDS: list[tuple[str, str, str | None]] = [
    ("proc", "struct proc", None),
    ("proc.state", "struct proc", "state"),
    ("proc.chan", "struct proc", "chan"),
    ("proc.killed", "struct proc", "killed"),
    ("proc.xstate", "struct proc", "xstate"),
    ("proc.pid", "struct proc", "pid"),
    ("proc.parent", "struct proc", "parent"),
    ("proc.kstack", "struct proc", "kstack"),
    ("proc.sz", "struct proc", "sz"),
    ("proc.pagetable", "struct proc", "pagetable"),
    ("proc.trapframe", "struct proc", "trapframe"),
    ("proc.context", "struct proc", "context"),
    ("proc.ofile", "struct proc", "ofile"),
    ("proc.cwd", "struct proc", "cwd"),
    ("proc.name", "struct proc", "name"),
    ("proc.priority", "struct proc", "priority"),
    ("proc.stride", "struct proc", "stride"),
    ("proc.pass", "struct proc", "pass"),
    ("cpu", "struct cpu", None),
    ("cpu.proc", "struct cpu", "proc"),
    ("cpu.noff", "struct cpu", "noff"),
    ("cpu.intena", "struct cpu", "intena"),
    ("context", "struct context", None),
    ("context.ra", "struct context", "ra"),
    ("context.sp", "struct context", "sp"),
    ("spinlock", "struct spinlock", None),
    ("spinlock.locked", "struct spinlock", "locked"),
    ("spinlock.name", "struct spinlock", "name"),
    ("spinlock.cpu", "struct spinlock", "cpu"),
    ("file", "struct file", None),
    ("file.type", "struct file", "type"),
    ("file.ref", "struct file", "ref"),
    ("file.readable", "struct file", "readable"),
    ("file.writable", "struct file", "writable"),
    ("file.pipe", "struct file", "pipe"),
    ("file.ip", "struct file", "ip"),
    ("file.off", "struct file", "off"),
    ("inode", "struct inode", None),
    ("inode.dev", "struct inode", "dev"),
    ("inode.inum", "struct inode", "inum"),
    ("inode.ref", "struct inode", "ref"),
    ("inode.valid", "struct inode", "valid"),
    ("inode.type", "struct inode", "type"),
    ("inode.size", "struct inode", "size"),
    ("inode.nlink", "struct inode", "nlink"),
    ("buf", "struct buf", None),
    ("buf.valid", "struct buf", "valid"),
    ("buf.disk", "struct buf", "disk"),
    ("buf.dev", "struct buf", "dev"),
    ("buf.blockno", "struct buf", "blockno"),
    ("buf.refcnt", "struct buf", "refcnt"),
    ("buf.data", "struct buf", "data"),
]

_CONSTS = [
    "NPROC", "NCPU", "NOFILE", "NFILE", "NINODE", "NBUF", "NDEV",
    "MAXOPBLOCKS", "LOGBLOCKS", "FSSIZE", "MAXPATH", "LAB_STAGE",
    "PGSIZE", "KERNBASE", "PHYSTOP", "MAXVA", "TRAMPOLINE", "TRAPFRAME",
]

_PROBE_TEMPLATE = r"""
/* NodeFusion 布局探针 —— 由 host/layout.py 自动生成，不要手改 */
#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/memlayout.h"
#include "kernel/riscv.h"
#include "kernel/spinlock.h"
#include "kernel/proc.h"
#include "kernel/fs.h"
#include "kernel/sleeplock.h"
#include "kernel/file.h"
#include "kernel/buf.h"

/* 值由生成方直接算好传进来，宏不再拼接 offsetof 的参数 —— 拼接会得到
   __builtin_offsetof (struct proc) (state) 这种非法写法。 */
#define NF_OFF(n, v)   asm volatile("\n.ascii \"NFOFF " n " %0\"" :: "i"((long)(v)))
#define NF_SZ(n, v)    asm volatile("\n.ascii \"NFSZ " n " %0\"" :: "i"((long)(v)))
#define NF_CONST(n, v) asm volatile("\n.ascii \"NFCONST " n " %0\"" :: "i"((long)(v)))

void nf_layout_probe(void)
{
/*NF_BODY*/
}
"""


@dataclass
class KernelLayout:
    sizes: dict[str, int] = field(default_factory=dict)
    offsets: dict[str, int] = field(default_factory=dict)
    consts: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    source: str = ""
    notes: dict[str, str] = field(default_factory=dict)
    kind: str = ""

    def off(self, name: str) -> int:
        if name not in self.offsets:
            raise LayoutError(
                f"内核布局里没有 '{name}'。这个内核可能删改了对应结构体；"
                f"相关资源必须显式标为不可解释，不能猜。")
        return self.offsets[name]

    def has(self, name: str) -> bool:
        return name in self.offsets or name in self.sizes

    def size(self, name: str) -> int:
        if name not in self.sizes:
            raise LayoutError(f"内核布局里没有 '{name}' 的 sizeof")
        return self.sizes[name]

    def const(self, name: str, default: int | None = None) -> int:
        if name in self.consts:
            return self.consts[name]
        if default is not None:
            return default
        raise LayoutError(f"内核常量 '{name}' 未探测到")

    def note(self, name: str) -> str | None:
        return self.notes.get(name)

    def to_json(self) -> dict:
        return {
            "sizes": self.sizes, "offsets": self.offsets,
            "consts": self.consts, "missing": self.missing,
            "source": self.source, "notes": self.notes, "kind": self.kind,
        }

    @staticmethod
    def from_json(d: dict) -> "KernelLayout":
        return KernelLayout(
            sizes=dict(d.get("sizes", {})), offsets=dict(d.get("offsets", {})),
            consts=dict(d.get("consts", {})), missing=list(d.get("missing", [])),
            source=d.get("source", ""), notes=dict(d.get("notes", {})),
            kind=d.get("kind", ""))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

_RUST_INT_MAX = {
    "usize": (1 << 64) - 1, "u64": (1 << 64) - 1, "u32": (1 << 32) - 1,
    "u16": (1 << 16) - 1, "u8": 0xFF,
    "isize": (1 << 63) - 1, "i64": (1 << 63) - 1, "i32": (1 << 31) - 1,
}
_RUST_CONST_RE = re.compile(
    r"(?:pub\s+)?const\s+(\w+)\s*:\s*[\w:<>]+\s*=\s*([^;]+);")
_RUST_SUFFIX_RE = re.compile(
    r"\b((?:0[xXbBoO])?[0-9a-fA-F]+)(?:[ui](?:8|16|32|64|128|size))\b")
_RUST_MAX_RE = re.compile(r"\b([ui](?:8|16|32|64|128|size))::MAX\b")
_RUST_DIGITS_RE = re.compile(r"\b(0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*)")

_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.LShift: lambda a, b: a << b,
    ast.RShift: lambda a, b: a >> b,
    ast.BitOr: lambda a, b: a | b,
    ast.BitAnd: lambda a, b: a & b,
    ast.BitXor: lambda a, b: a ^ b,
}


def _rust_expr_to_py(expr: str) -> str:
    expr = _RUST_MAX_RE.sub(
        lambda m: str(_RUST_INT_MAX[m.group(1)])
        if m.group(1) in _RUST_INT_MAX else m.group(0), expr)
    expr = _RUST_DIGITS_RE.sub(lambda m: m.group(0).replace("_", ""), expr)
    expr = _RUST_SUFFIX_RE.sub(r"\1", expr)
    return expr.strip()


def _eval_rust_const(expr: str, env: dict[str, int]) -> int | None:
    try:
        tree = ast.parse(_rust_expr_to_py(expr), mode="eval")
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value if isinstance(n.value, int) else None
        if isinstance(n, ast.Name):
            return env.get(n.id)
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            if v is None:
                return None
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return v
            if isinstance(n.op, ast.Invert):
                return ~v
            return None
        if isinstance(n, ast.BinOp):
            fn = _ALLOWED_BINOPS.get(type(n.op))
            a, b = ev(n.left), ev(n.right)
            if fn is None or a is None or b is None:
                return None
            if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
                return None
            return fn(a, b)
        return None

    v = ev(tree)
    return None if v is None else v & ((1 << 64) - 1)


def read_rust_consts(path: Path) -> tuple[dict[str, int], dict[str, str]]:
    vals: dict[str, int] = {}
    bad: dict[str, str] = {}
    if not path.exists():
        return vals, bad
    text = path.read_text(errors="replace")
    for m in _RUST_CONST_RE.finditer(text):
        name, expr = m.group(1), m.group(2).strip()
        v = _eval_rust_const(expr, vals)
        if v is None:
            bad[name] = f"常量表达式无法安全求值：{expr}"
        else:
            vals[name] = v
    return vals, bad


_RCORE_CONST_ALIASES = {
    "PAGE_SIZE": "PGSIZE",
    "MEMORY_END": "PHYSTOP",
    "TRAP_CONTEXT_BASE": "TRAPFRAME",
}

_QEMU_VIRT_DRAM_BASE = 0x8000_0000


_RCORE_STRUCTS: dict[str, str] = {
    "task": "TaskControlBlock",
    "task_manager": "TaskManager",
    "task_manager_inner": "TaskManagerInner",
    "task_context": "TaskContext",
    "trap_context": "TrapContext",
    "memory_set": "MemorySet",
    "page_table": "PageTable",
    "map_area": "MapArea",
    "phys_page_num": "PhysPageNum",
    "virt_page_num": "VirtPageNum",
    "app_manager": "AppManager",
    "frame_tracker": "FrameTracker",
}


def probe_rcore(kernel_dir: Path, elf_path: Path | None = None) -> KernelLayout:
    kernel_dir = Path(kernel_dir)
    lay = KernelLayout(source=str(kernel_dir), kind="rcore")

    src = kernel_dir / "os" / "src"
    vals: dict[str, int] = {}
    bad: dict[str, str] = {}
    used: list[str] = []
    for cand in (src / "config.rs", src / "batch.rs"):
        if not cand.exists():
            continue
        v, b = read_rust_consts(cand)
        if v:
            used.append(cand.name)
        for k, x in v.items():
            vals.setdefault(k, x)
        for k, why in b.items():
            bad.setdefault(k, why)
    if not vals:
        lay.notes["consts"] = (
            f"{src} 下没有 config.rs 也没有 batch.rs（或里面没有可读的常量）—— "
            f"rCore 早期章节（ch1、ch2）本来就没有这些常量。"
            f"因此本次不提供任何源码常量；结构体偏移仍从 DWARF 读，不受影响。")
    else:
        lay.notes["consts"] = f"常量取自 {'、'.join(used)}"
    for name, v in vals.items():
        lay.consts[_RCORE_CONST_ALIASES.get(name, name)] = v
    for name, why in bad.items():
        lay.notes[_RCORE_CONST_ALIASES.get(name, name)] = why

    ld = kernel_dir / "os" / "src" / "linker.ld"
    if ld.exists():
        m = re.search(r"BASE_ADDRESS\s*=\s*(0[xX][0-9a-fA-F]+|\d+)\s*;",
                      ld.read_text(errors="replace"))
        if m:
            lay.consts["KERNEL_BASE"] = int(m.group(1), 0)
            lay.notes["KERNEL_BASE"] = f"取自 {ld.name} 的 BASE_ADDRESS"

    lay.consts["KERNBASE"] = _QEMU_VIRT_DRAM_BASE
    lay.notes["KERNBASE"] = (
        "来自 QEMU -machine virt 的主内存基址，不是从 rCore 源码读的。"
        "换机器型号（或换成真机）必须一并改。")

    _probe_rcore_dwarf(lay, elf_path)
    return lay


def _probe_rcore_dwarf(lay: KernelLayout, elf_path: Path | None) -> None:
    if elf_path is None or not Path(elf_path).exists():
        lay.missing = sorted(_RCORE_STRUCTS)
        lay.notes["struct-layout"] = (
            f"没有拿到内核 ELF（{elf_path}），无法读取 DWARF，"
            f"结构体偏移全部不可用。")
        return

    from .dwarf import DwarfError, DwarfInfo

    try:
        dw = DwarfInfo(elf_path)
    except DwarfError as e:
        lay.missing = sorted(_RCORE_STRUCTS)
        lay.notes["struct-layout"] = (
            f"读不到调试信息，结构体偏移全部不可用：{e}\n"
            f"rCore 需要带调试信息编译（CARGO_PROFILE_RELEASE_DEBUG=2 "
            f"CARGO_PROFILE_RELEASE_STRIP=none）才能取到字段偏移。")
        return

    missing: list[str] = []
    for canon, short in sorted(_RCORE_STRUCTS.items()):
        s = dw.find(short)
        if s is None:
            missing.append(canon)
            why = dw.conflicts.get(short)
            lay.notes[canon] = (
                f"调试信息里有多个同名但布局不同的 {short}，无法确定用哪个：{why}"
                if why else
                f"这个内核里没有 {short}（各章内核结构不同，可能本章就没有这个东西）")
            continue
        if s.size is not None:
            lay.sizes[canon] = s.size
        for fname, off in s.fields.items():
            lay.offsets[f"{canon}.{fname}"] = off
        lay.notes[f"{canon}._rust_path"] = s.path

    for path, members in dw.enums.items():
        if not members:
            continue
        short = path.rsplit("::", 1)[-1]
        for mname, val in members.items():
            key = f"enum.{short}.{mname}"
            if key in lay.consts and lay.consts[key] != val:
                lay.notes[f"enum.{short}"] = (
                    f"{short} 在调试信息里有多套不同的判别值，已标为不可信")
                continue
            lay.consts[key] = val

    _resolve_task_chain(lay, dw)

    lay.missing = missing
    lay.notes["struct-layout"] = (
        "结构体偏移读自内核 ELF 的 DWARF（.debug_info），也就是编译器实际选定的"
        "布局。#[repr(Rust)] 允许按大小重排字段，实测确有重排，因此不能照源码"
        "顺序推算。学生改了结构体，这里会自动跟着变。")
    if dw.conflicts:
        lay.notes["struct-layout-conflicts"] = (
            "以下类型在调试信息里有多套不同布局，已标为不可用而不是任选一套："
            + "；".join(sorted(dw.conflicts)[:20]))


def _descend(dw, start, target: str, *, max_hops: int = 8
             ) -> tuple[int | None, object, list[str]]:
    off = 0
    cur = start
    trail = [start.name]
    for _ in range(max_hops):
        if cur.name == target:
            return off, cur, trail
        fname = None
        for cand in ("value", "data", "__0"):
            if cur.has(cand):
                fname = cand
                break
        if fname is None and len(cur.fields) == 1:
            fname = next(iter(cur.fields))
        if fname is None:
            return None, cur, trail
        nxt = dw.struct_of_field(cur, fname)
        if nxt is None:
            return None, cur, trail
        off += cur.off(fname)
        cur = nxt
        trail.append(cur.name)
    return (off, cur, trail) if cur.name == target else (None, cur, trail)


def _find_lazy(dw, inner_frag: str, *, direct: bool = False
               ) -> tuple[object | None, str]:
    if direct:
        cands = [s for s in dw.structs.values()
                 if s.name.startswith("Lazy<" + inner_frag)]
        how = f"值类型以 {inner_frag} 开头"
    else:
        cands = [s for s in dw.structs.values()
                 if s.name.startswith("Lazy<") and inner_frag in s.path]
        how = f"包着 {inner_frag}"
    if not cands:
        return None, f"找不到{how}的 Lazy<...> 类型"
    uniq = {(s.path, s.size) for s in cands}
    if len(uniq) > 1:
        detail = "；".join(f"{p[:70]}(size={sz})" for p, sz in sorted(uniq))
        return None, (f"{how}的 Lazy<...> 有 {len(uniq)} 个不同的，"
                      f"无法确定用哪个：{detail}")
    return cands[0], ""


def _descend_to_prefix(dw, start, prefix: str, *, max_hops: int = 8):
    off = 0
    cur = start
    trail = [start.name]
    for _ in range(max_hops):
        if cur.name.startswith(prefix):
            return off, cur, trail
        fname = None
        for cand in ("value", "data", "__0"):
            if cur.has(cand):
                fname = cand
                break
        if fname is None and len(cur.fields) == 1:
            fname = next(iter(cur.fields))
        if fname is None:
            return None, cur, trail
        nxt = dw.struct_of_field(cur, fname)
        if nxt is None:
            return None, cur, trail
        off += cur.off(fname)
        cur = nxt
        trail.append(cur.name)
    return (off, cur, trail) if cur.name.startswith(prefix) else (None, cur, trail)


def _arc_data_off(dw, ty_suffix: str) -> int | None:
    ai = next((s for s in dw.structs.values()
               if s.name.startswith("ArcInner<")
               and s.path.endswith(ty_suffix + ">")), None)
    return ai.off("data") if ai is not None and ai.has("data") else None


def _vec_offsets(lay: KernelLayout, dw, owner, fname: str, base: int,
                 prefix: str) -> bool:
    if not owner.has(fname):
        return False
    v = dw.struct_of_field(owner, fname)
    raw = dw.struct_of_field(v, "buf") if v is not None else None
    if v is None or raw is None or not v.has("len") \
            or not raw.has("ptr") or not raw.has("cap"):
        return False
    at = base + owner.off(fname)
    lay.offsets[f"{prefix}_len"] = at + v.off("len")
    lay.offsets[f"{prefix}_ptr"] = at + v.off("buf") + raw.off("ptr")
    lay.offsets[f"{prefix}_cap"] = at + v.off("buf") + raw.off("cap")
    return True


def _root_ppn_off(dw, owner, base: int) -> int | None:
    if not owner.has("memory_set"):
        return None
    ms = dw.struct_of_field(owner, "memory_set")
    pt = dw.struct_of_field(ms, "page_table") if ms is not None else None
    if pt is None or not pt.has("root_ppn"):
        return None
    return base + owner.off("memory_set") + ms.off("page_table") + pt.off("root_ppn")


def _resolve_initproc(lay: KernelLayout, dw, root_ty: str) -> None:
    lz, why = _find_lazy(dw, root_ty, direct=True)
    if lz is None:
        lay.notes["task-tree-initproc"] = (
            f"定位不到 INITPROC 的静态量类型（{why}），无法确定进程树的根，"
            f"因此无法枚举全部任务")
        return
    off, _, tr = _descend_to_prefix(dw, lz, "Arc<")
    if off is None:
        lay.notes["task-tree-initproc"] = (
            f"从 {lz.path} 走不到里面的 Arc（{'->'.join(tr)}）")
        return
    lay.offsets["rcore.initproc_from_lazy"] = off


def _resolve_processor(lay: KernelLayout, dw) -> None:
    proc = dw.find("Processor")
    if proc is None or not proc.has("current"):
        lay.notes["task-tree-processor"] = (
            "没有 Processor 或它没有 current 字段，取不到当前正在跑的任务")
        return
    plz, why = _find_lazy(dw, "processor::Processor")
    if plz is None:
        lay.notes["task-tree-processor"] = f"定位不到 PROCESSOR 的静态量类型（{why}）"
        return
    poff, _, trail = _descend(dw, plz, "Processor")
    if poff is None:
        lay.notes["task-tree-processor"] = (
            f"从 {plz.path} 走不到 Processor（{'->'.join(trail)}）")
        return
    lay.offsets["rcore.processor_from_lazy"] = poff
    lay.offsets["rcore.processor_current"] = poff + proc.off("current")


def _resolve_rcore_proc_tree(lay: KernelLayout, dw) -> None:
    pcb = dw.find("ProcessControlBlock")
    tcb = dw.find("TaskControlBlock")
    if pcb is None or tcb is None:
        lay.notes["task-tree"] = "ch8 形态需要 ProcessControlBlock 和 TaskControlBlock，缺其一"
        return

    for suffix, key in (("ProcessControlBlock", "rcore.arc_pcb_data"),
                        ("TaskControlBlock", "rcore.arc_tcb_data")):
        off = _arc_data_off(dw, suffix)
        if off is None:
            lay.notes["task-tree"] = f"找不到 ArcInner<{suffix}> 的布局"
            return
        lay.offsets[key] = off

    if not pcb.has("inner"):
        lay.notes["task-tree"] = "ProcessControlBlock 里没有 inner 字段"
        return
    wrap = dw.struct_of_field(pcb, "inner")
    poff, pin, ptrail = _descend(dw, wrap, "ProcessControlBlockInner") \
        if wrap is not None else (None, None, ["?"])
    if poff is None or pin is None:
        lay.notes["task-tree"] = (
            f"从 ProcessControlBlock.inner 走不到 ProcessControlBlockInner"
            f"（{'->'.join(ptrail)}）")
        return
    pbase = pcb.off("inner") + poff
    lay.offsets["rcore.pcb_inner"] = pbase

    if not _vec_offsets(lay, dw, pin, "children", pbase, "rcore.pcb_children"):
        lay.notes["task-tree-children"] = (
            "ProcessControlBlockInner.children 的 Vec 布局解不出来，无法枚举全部进程")
    if not _vec_offsets(lay, dw, pin, "tasks", pbase, "rcore.pcb_tasks"):
        lay.notes["task-tree-threads"] = (
            "ProcessControlBlockInner.tasks 的 Vec 布局解不出来，"
            "能看到进程但看不到每个进程里的线程")

    rp = _root_ppn_off(dw, pin, pbase)
    if rp is not None:
        lay.offsets["rcore.pcb_root_ppn"] = rp
    else:
        lay.notes["task-tree-rootppn"] = (
            "取不到 ProcessControlBlockInner 的页表根，地址空间无法对应到进程")
    for f, key in (("exit_code", "rcore.pcb_exit_code"),
                   ("is_zombie", "rcore.pcb_is_zombie")):
        if pin.has(f):
            lay.offsets[key] = pbase + pin.off(f)
            ty = dw.type_of(pin, f)
            if ty:
                lay.notes[f"{key}.type"] = ty

    if tcb.has("inner"):
        twrap = dw.struct_of_field(tcb, "inner")
        toff, tin, ttrail = _descend(dw, twrap, "TaskControlBlockInner") \
            if twrap is not None else (None, None, ["?"])
        if toff is None or tin is None:
            lay.notes["task-tree-thread"] = (
                f"从 TaskControlBlock.inner 走不到 TaskControlBlockInner"
                f"（{'->'.join(ttrail)}）")
        else:
            tbase = tcb.off("inner") + toff
            lay.offsets["rcore.tcb_inner"] = tbase
            for f, key in (("task_status", "rcore.tcb_status"),
                           ("exit_code", "rcore.tcb_exit_code"),
                           ("trap_cx_ppn", "rcore.tcb_trap_cx_ppn")):
                if tin.has(f):
                    lay.offsets[key] = tbase + tin.off(f)
                    ty = dw.type_of(tin, f)
                    if ty:
                        lay.notes[f"{key}.type"] = ty
    else:
        lay.notes["task-tree-thread"] = "TaskControlBlock 里没有 inner 字段"

    _resolve_initproc(lay, dw, "alloc::sync::Arc<os::task::process::ProcessControlBlock")
    _resolve_processor(lay, dw)

    lay.consts["RCORE_TASKS_KIND"] = 4
    lay.notes["task-chain"] = (
        "这一章进程和线程是分开的两层：进程树从 INITPROC 顺 "
        "ProcessControlBlockInner.children 走，每个进程的线程在它的 tasks 里"
        "（Vec<Option<Arc<TaskControlBlock>>>，空位是 None）。"
        "地址空间属于进程，PROCESSOR.current 里放的是当前**线程**。")


def _resolve_rcore_tree(lay: KernelLayout, dw) -> None:
    tcb = dw.find("TaskControlBlock")
    if tcb is None:
        lay.notes["task-tree"] = "没有 TaskControlBlock，无法走进程树"
        return

    ad = _arc_data_off(dw, "TaskControlBlock")
    if ad is None:
        lay.notes["task-tree"] = "找不到 ArcInner<TaskControlBlock> 的布局"
        return
    lay.offsets["rcore.arc_data"] = ad

    # TaskControlBlock -> (UPSafeCell/RefCell/UnsafeCell...) -> TaskControlBlockInner
    if not tcb.has("inner"):
        lay.notes["task-tree"] = "TaskControlBlock 里没有 inner 字段"
        return
    inner_wrap = dw.struct_of_field(tcb, "inner")
    if inner_wrap is None:
        lay.notes["task-tree"] = "TaskControlBlock.inner 的类型解不出来"
        return
    ioff, tin, itrail = _descend(dw, inner_wrap, "TaskControlBlockInner")
    if ioff is None or tin is None:
        lay.notes["task-tree"] = (
            f"从 TaskControlBlock.inner 走不到 TaskControlBlockInner"
            f"（{'->'.join(itrail)}）")
        return
    inner_off = tcb.off("inner") + ioff
    lay.offsets["rcore.tcb_inner"] = inner_off

    for fname, key in (("task_status", "rcore.tcb_status"),
                       ("exit_code", "rcore.tcb_exit_code")):
        if tin.has(fname):
            lay.offsets[key] = inner_off + tin.off(fname)
            ty = dw.type_of(tin, fname)
            if ty:
                lay.notes[f"{key}.type"] = ty

    if not _vec_offsets(lay, dw, tin, "children", inner_off, "rcore.children"):
        lay.notes["task-tree-children"] = (
            "TaskControlBlockInner.children 的 Vec 布局解不出来（或根本没有这个字段），"
            "只能看到就绪队列和当前任务，无法枚举全部任务")

    rp = _root_ppn_off(dw, tin, inner_off)
    if rp is not None:
        lay.offsets["rcore.tcb_root_ppn"] = rp
    else:
        lay.notes["task-tree-rootppn"] = (
            "取不到 TaskControlBlockInner 的页表根，地址空间无法对应到任务")
    if tin.has("trap_cx_ppn"):
        lay.offsets["rcore.tcb_trap_cx_ppn"] = inner_off + tin.off("trap_cx_ppn")

    _resolve_initproc(lay, dw, "alloc::sync::Arc<os::task::task::TaskControlBlock")
    _resolve_processor(lay, dw)

    lay.consts["RCORE_TASKS_KIND"] = 2
    lay.notes["task-chain"] = (
        "这一章没有扁平的任务表：TaskManager 里只有就绪队列，"
        "当前任务在 PROCESSOR 里，已退出未回收的挂在父任务 children 上。"
        "完整枚举靠从 INITPROC 走进程树。")


def _resolve_task_chain(lay: KernelLayout, dw) -> None:
    tm = dw.find("TaskManager")
    if tm is None:
        am = dw.find("AppManager")
        if am is not None:
            alz, awhy = _find_lazy(dw, "AppManager")
            if alz is None:
                lay.notes["task-chain-appmgr"] = (
                    f"定位不到 APP_MANAGER 的静态量类型（{awhy}）")
            else:
                aoff, _, atr = _descend(dw, alz, "AppManager")
                if aoff is None:
                    lay.notes["task-chain-appmgr"] = (
                        f"从 {alz.path} 走不到 AppManager（{'->'.join(atr)}）")
                else:
                    lay.offsets["rcore.appmgr_from_lazy"] = aoff
            for f, key in (("num_app", "rcore.appmgr_num_app"),
                           ("current_app", "rcore.appmgr_current"),
                           ("app_start", "rcore.appmgr_app_start")):
                if am.has(f):
                    lay.offsets[key] = am.off(f)
            n = dw.array_of_field(am, "app_start")
            if n and n[1] is not None:
                lay.consts["RCORE_APP_START_LEN"] = n[1]
            lay.consts["RCORE_TASKS_KIND"] = 3
            lay.notes["task-chain"] = (
                "这一章是批处理内核：没有任务表，只有 AppManager 记录应用总数和"
                "当前跑到第几个。没有进程概念，因此不存在进程列表。")
            return
        lay.notes["task-chain"] = (
            "这个内核里既没有 TaskManager 也没有 AppManager"
            "（ch1 本来就没有任务/批处理的概念）。")
        return

    if tm.has("ready_queue") and not tm.has("inner"):
        if dw.find("ProcessControlBlock") is not None:
            _resolve_rcore_proc_tree(lay, dw)
        else:
            _resolve_rcore_tree(lay, dw)
        return

    lazy = next((s for s in dw.structs.values()
                 if s.name.startswith("Lazy<") and "TaskManager" in s.path), None)
    if lazy is not None:
        loff, _, ltrail = _descend(dw, lazy, "TaskManager")
        if loff is None:
            lay.notes["task-chain-lazy"] = (
                f"从 lazy_static 的静态量走不到 TaskManager（{'->'.join(ltrail)}）")
        else:
            lay.offsets["rcore.taskmgr_from_lazy"] = loff
    else:
        lay.notes["task-chain-lazy"] = (
            "没找到 Lazy<TaskManager>，无法确定静态量里 TaskManager 的位置")

    tcb = dw.find("TaskControlBlock")
    if tcb is not None and tcb.has("memory_set"):
        ms = dw.struct_of_field(tcb, "memory_set")
        if ms is not None and ms.has("page_table"):
            pt = dw.struct_of_field(ms, "page_table")
            if pt is not None and pt.has("root_ppn"):
                lay.offsets["rcore.task_root_ppn"] = (
                    tcb.off("memory_set") + ms.off("page_table")
                    + pt.off("root_ppn"))
            else:
                lay.notes["task-root"] = "PageTable 里没有 root_ppn 字段"
        else:
            lay.notes["task-root"] = "MemorySet 里没有 page_table 字段"

    off = 0
    cur = tm
    trail = ["TaskManager"]
    for fname in ("inner",):                    # TaskManager.inner
        if not cur.has(fname):
            lay.notes["task-chain"] = f"{'->'.join(trail)} 里没有字段 {fname}"
            return
        off += cur.off(fname)
        nxt = dw.struct_of_field(cur, fname)
        if nxt is None:
            lay.notes["task-chain"] = (
                f"{'->'.join(trail)}.{fname} 的类型在调试信息里解不出来")
            return
        cur, _ = nxt, trail.append(nxt.name)

    guard = 0
    while cur.name != "TaskManagerInner" and guard < 8:
        guard += 1
        fname = "value" if cur.has("value") else (
            next(iter(cur.fields)) if len(cur.fields) == 1 else None)
        if fname is None:
            lay.notes["task-chain"] = (
                f"走到 {'->'.join(trail)} 时不知道该跟哪个字段继续"
                f"（字段：{', '.join(sorted(cur.fields)) or '无'}）")
            return
        off += cur.off(fname)
        nxt = dw.struct_of_field(cur, fname)
        if nxt is None:
            lay.notes["task-chain"] = (
                f"{'->'.join(trail)}.{fname} 的类型在调试信息里解不出来")
            return
        cur = nxt
        trail.append(cur.name)

    if cur.name != "TaskManagerInner":
        lay.notes["task-chain"] = f"从 TaskManager 走不到 TaskManagerInner（{'->'.join(trail)}）"
        return

    inner_off = off
    lay.offsets["rcore.taskmgr_inner"] = inner_off
    if cur.has("current_task"):
        lay.offsets["rcore.current_task"] = inner_off + cur.off("current_task")
    if tm.has("num_app"):
        lay.offsets["rcore.num_app"] = tm.off("num_app")

    if not cur.has("tasks"):
        lay.notes["task-chain"] = "TaskManagerInner 里没有 tasks 字段"
        return
    tasks_off = inner_off + cur.off("tasks")
    lay.offsets["rcore.tasks"] = tasks_off

    tasks_ty = dw.type_of(cur, "tasks") or ""
    vec = dw.struct_of_field(cur, "tasks")
    if tasks_ty.startswith("Vec<") and vec is not None:
        raw = dw.struct_of_field(vec, "buf")
        if raw is None or not vec.has("len"):
            lay.notes["task-chain"] = "Vec 的内部布局在调试信息里解不出来"
            return
        if not (raw.has("ptr") and raw.has("cap")):
            lay.notes["task-chain"] = (
                f"RawVec 里没有 ptr/cap（字段：{', '.join(sorted(raw.fields))}）")
            return
        lay.offsets["rcore.tasks_len"] = tasks_off + vec.off("len")
        lay.offsets["rcore.tasks_ptr"] = tasks_off + vec.off("buf") + raw.off("ptr")
        lay.offsets["rcore.tasks_cap"] = tasks_off + vec.off("buf") + raw.off("cap")
        lay.notes["task-chain"] = (
            f"任务表是堆上的 Vec：{'->'.join(trail)}.tasks。"
            f"元素在堆上，需要顺 ptr 再读一跳。")
        lay.consts["RCORE_TASKS_KIND"] = 1
    else:
        lay.notes["task-chain"] = (
            f"任务表是内联的定长数组（类型 {tasks_ty or '未知'}），"
            f"元素直接排在 TaskManagerInner.tasks 处，不用再跟指针。")
        lay.consts["RCORE_TASKS_KIND"] = 0
        n = dw.size_of_type(cur, "tasks")
        if n is not None:
            lay.consts["RCORE_TASKS_BYTES"] = n
        arr = dw.array_of_field(cur, "tasks")
        if arr and arr[1] is not None:
            lay.consts["RCORE_TASKS_CAP"] = arr[1]
        else:
            lay.notes["task-chain-count"] = (
                "定长任务数组的元素个数在调试信息里读不到，"
                "只能靠 num_app 限制实际条数")


def detect_kernel(kernel_dir: Path) -> str:
    d = Path(kernel_dir)
    if (d / "kernel" / "proc.h").exists() and (d / "kernel" / "param.h").exists():
        return "xv6"
    if all((d / p).exists() for p in
           ("os/src/main.rs", "os/src/sbi.rs", "os/src/linker.ld")):
        return "rcore"
    return ""


@functools.lru_cache(maxsize=1)
def _manifest_names() -> tuple[str, ...]:
    try:
        from ..model.manifest import builtin_dir, load_dir
        return tuple(sorted(load_dir(builtin_dir())))
    except Exception:                                     # noqa: BLE001
        return ()


def _layout_from_manifest(kernel_dir: Path, kind: str) -> KernelLayout:
    return KernelLayout(
        source=str(kernel_dir), kind=kind,
        notes={"_manifest_layout":
               f"{kind} 的结构体偏移不在这份文件里，也没有探测失败。"
               f"它们由 manifest（nodefusion/manifests/{kind}.toml）加内核 ELF 的 "
               f"DWARF 在分析阶段解出来，见 model/probe.py。这一步的 asm-offsets "
               f"探针只适用于 C 内核（要编 include 内核头文件的代码），"
               f"对这个内核不成立，所以没有跑。"})


def _render_probe(fields, consts) -> str:
    lines = []
    for name, struct_name, field_name in fields:
        if field_name is None:
            lines.append(f'    NF_SZ("{name}", sizeof({struct_name}));')
        else:
            lines.append(
                f'    NF_OFF("{name}", '
                f'__builtin_offsetof({struct_name}, {field_name}));')
    for c in consts:
        lines.append(f'#ifdef {c}')
        lines.append(f'    NF_CONST("{c}", {c});')
        lines.append(f'#endif')
    return _PROBE_TEMPLATE.replace("/*NF_BODY*/", "\n".join(lines))


def probe(kernel_dir: Path, sh: Shell, *, make_vars: str = "",
          work_dir: Path | None = None,
          override: Path | None = None,
          kind: str = "",
          elf_path: Path | None = None) -> KernelLayout:
    kernel_dir = Path(kernel_dir)

    if override is not None:
        lay = load(Path(override))
        lay.notes["_override"] = (
            f"这份布局直接来自 {override}，不是从被观察内核探测出来的。"
            f"内核改了结构体，这里不会自动跟着变。")
        return lay

    detected = kind or detect_kernel(kernel_dir)
    if detected == "rcore":
        return probe_rcore(kernel_dir, elf_path)

    if detected != "xv6":
        known = _manifest_names()
        if detected in known:
            return _layout_from_manifest(kernel_dir, detected)
        raise LayoutError(
            f"认不出 {kernel_dir} 是哪种内核，不能替它选布局探测方式。\n"
            "  * xv6：靠 kernel/proc.h + kernel/param.h 认出来，走 asm-offsets 探针；\n"
            "  * rCore：靠 os/src/{main.rs,sbi.rs,linker.ld} 认出来，从 DWARF 读；\n"
            f"  * 有 manifest 的（{'/'.join(known)}）：偏移在分析阶段从 DWARF 解，\n"
            "    这一步不探 —— 但得先认出是哪一种，见各 manifest 的 detect_files；\n"
            "  * 其余：写一份 manifest（见 nodefusion/manifests/），\n"
            "    或者用 --layout-override 直接给一份现成的布局 JSON。\n"
            "以前这里会默认按 xv6 探，然后报一个'找不到 kernel/types.h'——"
            "那句话把人引到了错的方向。")

    work = work_dir or (kernel_dir.parent / "nodefusion" / "runs" / "_layout")
    work.mkdir(parents=True, exist_ok=True)

    def compile_probe(fields, consts) -> tuple[bool, str]:
        src = work / "nf_layout_probe.c"
        asm = work / "nf_layout_probe.s"
        src.write_text(_render_probe(fields, consts), encoding="utf-8")
        cmd = (
            f'cd "{sh.path(kernel_dir)}" && '
            f'riscv64-unknown-elf-gcc -march=rv64gc -mcmodel=medany -ffreestanding '
            f'-nostdlib -fno-builtin -I. {make_vars} '
            f'-S -o "{sh.path(asm)}" "{sh.path(src)}" 2>&1'
        )
        r = sh.run(cmd, check=False)
        if r.returncode != 0:
            return False, r.stdout + r.stderr
        return True, asm.read_text(encoding="utf-8", errors="replace")

    ok, out = compile_probe(_FIELDS, _CONSTS)
    missing: list[str] = []
    if not ok:
        good = []
        for f in _FIELDS:
            ok1, _ = compile_probe([f], [])
            if ok1:
                good.append(f)
            else:
                missing.append(f[0])
        ok, out = compile_probe(good, _CONSTS)
        if not ok:
            raise LayoutError(
                "内核布局探针编译失败，且逐字段重试后仍然失败。"
                "请确认 kernel/ 目录下的头文件能被交叉编译器找到。\n" + out[:3000])

    layout = KernelLayout(missing=missing, source=str(kernel_dir), kind="xv6")
    for kind, name, val in re.findall(
            r"NF(OFF|SZ|CONST) ([A-Za-z0-9_.]+) (-?\d+)", out):
        v = int(val)
        if kind == "OFF":
            layout.offsets[name] = v
        elif kind == "SZ":
            layout.sizes[name] = v
        else:
            layout.consts[name] = v

    if "proc" not in layout.sizes or "proc.pid" not in layout.offsets:
        raise LayoutError(
            "探针跑通了但没拿到 struct proc 的布局，这不正常。"
            "生成的汇编片段：\n" + out[:2000])
    return layout


def save(layout: KernelLayout, path: Path) -> None:
    path.write_text(json.dumps(layout.to_json(), indent=2, ensure_ascii=False),
                    encoding="utf-8")


def load(path: Path) -> KernelLayout:
    return KernelLayout.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
