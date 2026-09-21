
from __future__ import annotations

import struct
from collections.abc import Mapping as PageMapping, Sequence
from dataclasses import dataclass, field

from .layout import KernelLayout
from .nfelf import Elf64

PGSIZE = 4096
PGSHIFT = 12
MASK64 = (1 << 64) - 1

EM_RISCV = 243

MACHINE_NAMES = {
    EM_RISCV: "riscv64", 62: "x86_64", 183: "aarch64", 258: "loongarch64",
}

PTE_V = 1 << 0
PTE_R = 1 << 1
PTE_W = 1 << 2
PTE_X = 1 << 3
PTE_U = 1 << 4
PTE_G = 1 << 5
PTE_A = 1 << 6
PTE_D = 1 << 7
PTE_COW = 1 << 8

PROC_STATES = ["UNUSED", "USED", "SLEEPING", "RUNNABLE", "RUNNING", "ZOMBIE"]

K_FREE = 0
K_KERNEL_IMAGE = 1
K_KERNEL_OTHER = 2
K_USER = 3
K_PAGETABLE = 4
K_TRAPFRAME = 5
K_KSTACK = 6
K_USER_SHARED = 7
K_UNKNOWN = 8

KIND_NAMES = {
    K_FREE: "free", K_KERNEL_IMAGE: "kernel-image", K_KERNEL_OTHER: "kernel-other",
    K_USER: "user", K_PAGETABLE: "pagetable", K_TRAPFRAME: "trapframe",
    K_KSTACK: "kstack", K_USER_SHARED: "user-shared", K_UNKNOWN: "unknown",
}


class GuestError(Exception):
    pass


@dataclass(frozen=True)
class KernelImageFit:

    found: bool
    offset: int = 0
    paddr: int | None = None
    ambiguous: bool = False
    reason: str = ""

    @property
    def direct(self) -> bool:
        return self.found and self.offset == 0 and not self.ambiguous


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class RamImage:

    def __init__(self, base: int, size: int):
        self.base = base
        self.size = size
        self.data = bytearray(size)
        self.seen = bytearray(size // PGSIZE)

    def apply(self, pages: PageMapping[int, bytes]) -> None:
        for idx, blob in pages.items():
            off = idx * PGSIZE
            if off + len(blob) > self.size:
                continue
            self.data[off:off + len(blob)] = blob
            self.seen[idx] = 1

    def page_seen(self, idx: int) -> bool:
        return 0 <= idx < len(self.seen) and self.seen[idx] == 1


    def _off(self, pa: int, n: int) -> int | None:
        off = pa - self.base
        if off < 0 or off + n > self.size:
            return None
        first, last = off // PGSIZE, (off + n - 1) // PGSIZE
        for idx in range(first, last + 1):
            if not self.page_seen(idx):
                return None
        return off

    def u8(self, pa: int) -> int | None:
        o = self._off(pa, 1)
        return None if o is None else self.data[o]

    def u16(self, pa: int) -> int | None:
        o = self._off(pa, 2)
        return None if o is None else struct.unpack_from("<H", self.data, o)[0]

    def u32(self, pa: int) -> int | None:
        o = self._off(pa, 4)
        return None if o is None else struct.unpack_from("<I", self.data, o)[0]

    def i32(self, pa: int) -> int | None:
        o = self._off(pa, 4)
        return None if o is None else struct.unpack_from("<i", self.data, o)[0]

    def u64(self, pa: int) -> int | None:
        o = self._off(pa, 8)
        return None if o is None else struct.unpack_from("<Q", self.data, o)[0]

    def blob(self, pa: int, n: int) -> bytes | None:
        o = self._off(pa, n)
        return None if o is None else bytes(self.data[o:o + n])

    def cstr(self, pa: int, maxlen: int) -> str | None:
        b = self.blob(pa, maxlen)
        if b is None:
            return None
        end = b.find(b"\x00")
        if end >= 0:
            b = b[:end]
        return b.decode("utf-8", "replace")

    def _entry_bytes(self, elf: Elf64, n: int = 64) -> bytes | None:
        entry = elf.e_entry
        for i in range(elf.e_phnum):
            off = elf.e_phoff + i * elf.e_phentsize
            p_type, _f, p_offset, p_vaddr, _pa, p_filesz, _m, _a = \
                struct.unpack_from("<IIQQQQQQ", elf.data, off)
            if p_type != 1 or p_filesz == 0:
                continue
            if p_vaddr <= entry < p_vaddr + p_filesz:
                d = entry - p_vaddr
                return bytes(elf.data[p_offset + d:p_offset + d + min(n, p_filesz - d)])
        return None

    def find_kernel_image(self, elf: Elf64) -> KernelImageFit:
        entry = elf.e_entry
        if not entry:
            return KernelImageFit(False, reason="ELF 没有入口地址（e_entry 为 0）")
        want = self._entry_bytes(elf)
        if not want:
            return KernelImageFit(
                False, reason="ELF 的程序头里没有哪个 PT_LOAD 段含入口地址，"
                              "没法知道入口处该是什么字节")

        if self.blob(entry, len(want)) == want:
            return KernelImageFit(True, offset=0, paddr=entry)

        in_page = entry & (PGSIZE - 1)
        hits: list[int] = []
        for idx in range(len(self.seen)):
            if not self.seen[idx]:
                continue
            pa = self.base + idx * PGSIZE + in_page
            if self.blob(pa, len(want)) == want:
                hits.append(pa)
                if len(hits) > 1:
                    break
        if not hits:
            return KernelImageFit(False, reason="物理内存里找不到这段字节")
        if len(hits) > 1:
            return KernelImageFit(True, paddr=hits[0], ambiguous=True,
                                  reason="不止一处匹配，无法断定内核装在哪儿")
        return KernelImageFit(True, offset=entry - hits[0], paddr=hits[0])

    def check_kernel_mapping(self, elf: Elf64) -> bool:
        return self.find_kernel_image(elf).direct


class KernelView:

    def __init__(self, ram: "RamImage", offset: "int | Sequence[int]") -> None:
        self.ram = ram
        offs = [offset] if isinstance(offset, int) else list(offset)
        self.offsets: list[int] = list(dict.fromkeys(o for o in offs if o))

    @property
    def offset(self) -> int:
        return self.offsets[0] if self.offsets else 0

    def _t(self, a: int) -> int:
        for off in self.offsets:
            p = a - off
            if 0 <= p - self.ram.base < self.ram.size:
                return p
        return a

    def u8(self, a: int) -> int | None:
        return self.ram.u8(self._t(a))

    def u16(self, a: int) -> int | None:
        return self.ram.u16(self._t(a))

    def u32(self, a: int) -> int | None:
        return self.ram.u32(self._t(a))

    def i32(self, a: int) -> int | None:
        return self.ram.i32(self._t(a))

    def u64(self, a: int) -> int | None:
        return self.ram.u64(self._t(a))

    def blob(self, a: int, n: int) -> bytes | None:
        return self.ram.blob(self._t(a), n)

    def cstr(self, a: int, maxlen: int) -> str | None:
        return self.ram.cstr(self._t(a), maxlen)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

@dataclass
class Mapping:
    va: int
    pa: int
    flags: int
    level: int

    @property
    def perm_str(self) -> str:
        s = ""
        for bit, ch in ((PTE_R, "r"), (PTE_W, "w"), (PTE_X, "x"), (PTE_U, "u")):
            s += ch if self.flags & bit else "-"
        if self.flags & PTE_COW:
            s += "C"
        return s


def _longest_run(leaves: Sequence[tuple[int, int]]) -> int:
    if not leaves:
        return 0
    best = run = 0
    end = None
    for va, size in sorted(leaves):
        run = size if end is None or va != end else run + size
        end = va + size
        best = max(best, run)
    return best


def walk_pagetable(ram: RamImage, root_pa: int, *, machine: int,
                   max_pages: int | None = None
                   ) -> tuple[list[Mapping], list[int], str | None]:
    if machine != EM_RISCV:
        who = MACHINE_NAMES.get(machine, f"e_machine={machine}")
        return [], [], (
            f"这个二进制是 {who}，而这里只实现了 RISC-V 的 Sv39 页表格式。"
            f"照 Sv39 去解会得到一堆看着像映射的东西，所以不解")
    if max_pages is None:
        max_pages = max(20000, (ram.size // PGSIZE) * 4)
    if not root_pa:
        return [], [], "页表根为 0"
    maps: list[Mapping] = []
    ptpages: list[int] = []
    err: str | None = None

    seen_nodes: set[tuple[int, int, int]] = set()

    def rec(pa: int, level: int, va_base: int):
        nonlocal err
        if len(maps) > max_pages:
            err = "映射数量超过上限，结果被截断"
            return
        if len(ptpages) > max_pages:
            err = "页表结点数量超过上限，结果被截断（页表可能有环或已损坏）"
            return
        key = (pa, level, va_base)
        if key in seen_nodes:
            return
        seen_nodes.add(key)
        if ram.blob(pa, PGSIZE) is None:
            err = f"页表页 0x{pa:x} 不在已观察的物理内存范围内"
            return
        if not ram.page_seen((pa - ram.base) >> PGSHIFT):
            err = f"页表页 0x{pa:x} 从未被快照覆盖"
            return
        ptpages.append(pa)
        for i in range(512):
            pte = ram.u64(pa + i * 8)
            if pte is None or not (pte & PTE_V):
                continue
            child = ((pte >> 10) & ((1 << 44) - 1)) << PGSHIFT
            va = va_base | (i << (PGSHIFT + 9 * level))
            if pte & (PTE_R | PTE_W | PTE_X):
                maps.append(Mapping(va, child, pte & 0x3FF, level))
            elif level > 0:
                rec(child, level - 1, va)

    rec(root_pa, 2, 0)
    return maps, ptpages, err


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

@dataclass
class ArrayLoc:
    base: int
    elem_off: int
    elem_size: int
    count: int
    ok: bool
    reason: str = ""


def locate_array(elf: Elf64, layout: KernelLayout, sym_name: str,
                 elem_size: int, count: int, *, extra_tail: int = 0) -> ArrayLoc:
    sym = elf.sym(sym_name)
    if sym is None or not sym.value:
        return ArrayLoc(0, 0, elem_size, 0, False, f"内核里没有符号 '{sym_name}'")

    lock_size = layout.sizes.get("spinlock", 24)
    elem_off = (lock_size + 7) & ~7
    need = elem_off + elem_size * count + extra_tail
    if sym.size and sym.size != need:
        return ArrayLoc(
            sym.value, elem_off, elem_size, count, False,
            f"符号 '{sym_name}' 实际大小 {sym.size} 与推算布局 "
            f"{elem_off}+{count}×{elem_size}+{extra_tail}={need} 不一致，"
            f"该内核可能改过这个结构；本资源标记为不可解释")
    return ArrayLoc(sym.value, elem_off, elem_size, count, True)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

@dataclass
class ProcInfo:
    slot: int
    pid: int | None
    name: str | None
    state: int | None
    state_name: str
    sz: int | None
    pagetable: int
    parent_slot: int | None
    parent_pid: int | None
    chan: int | None
    killed: int | None
    xstate: int | None
    kstack: int | None
    trapframe: int | None
    priority: int | None
    stride: int | None
    pass_value: int | None
    open_fds: list[int] | None
    cwd: int | None
    sched_ctx: int | None = None
    sched_ctxs: list[int] = field(default_factory=list)
    user_pages: int = 0
    cow_pages: int = 0
    pagetable_pages: int = 0
    vm_regions: list = field(default_factory=list)
    vm_error: str | None = None
    fields: dict | None = None


@dataclass
class ResourceTable:
    available: bool
    reason: str = ""
    rows: list = field(default_factory=list)


@dataclass
class SystemState:
    insn: int
    snap_seq: int
    ticks: int | None
    complete: bool
    incomplete_reason: str = ""

    procs: list[ProcInfo] = field(default_factory=list)
    sched_owners: dict[int, dict] = field(default_factory=dict)
    procs_available: bool = True
    procs_reason: str = ""
    cpus: list[dict] = field(default_factory=list)

    phys_kind: bytearray = field(default_factory=bytearray)
    phys_pid: list = field(default_factory=list)
    phys_free: int = 0
    phys_used: int = 0
    phys_total: int = 0
    phys_available: bool = True
    phys_reason: str = ""
    phys_free_available: bool = True
    pagetable_root_source: str = ""
    pagetable_errors: list = field(default_factory=list)

    refcounts_available: bool = False
    shared_pages: int = 0

    resources: list = field(default_factory=list)
    resources_reason: str = ""


class GuestDecoder:

    def __init__(self, elf: Elf64, layout: KernelLayout, ram: RamImage,
                 *, entities=None):
        self.elf = elf
        self.layout = layout
        self.ram = ram
        self.entities = entities

        self._fit: KernelImageFit | None = None

        self._windows = []
        self._windows_why = "还没量过（要先有观测到的页表根）"
        self._roots = []

        self.nproc = layout.const("NPROC", 64)
        self.ncpu = layout.const("NCPU", 8)
        self.nofile = layout.const("NOFILE", 16)
        self.nfile = layout.const("NFILE", 100)
        self.ninode = layout.const("NINODE", 50)
        self.nbuf = layout.const("NBUF", 30)
        self.kernbase = layout.const("KERNBASE", 0x80000000)
        self.phystop = layout.const("PHYSTOP", 0x88000000)

        self.e_machine = elf.e_machine

        self.proc_base = elf.sym("proc").value if elf.sym("proc") else 0
        self.cpus_base = elf.sym("cpus").value if elf.sym("cpus") else 0
        self.ticks_addr = elf.sym("ticks").value if elf.sym("ticks") else 0
        self.end_addr, self.end_sym = self._find_kernel_end()

        self.is_rcore = layout.kind == "rcore"
        self.rcore_tm, self.rcore_tm_why = (
            self._find_rcore_taskmgr() if self.is_rcore else (0, ""))
        self.rcore_kind = layout.consts.get("RCORE_TASKS_KIND")
        self.rcore_initproc, self.rcore_initproc_why = (
            self._find_rcore_static("INITPROC")
            if self.is_rcore and self.rcore_kind in (2, 4) else (0, ""))
        self.rcore_processor, self.rcore_processor_why = (
            self._find_rcore_static("PROCESSOR")
            if self.is_rcore and self.rcore_kind in (2, 4) else (0, ""))
        self.rcore_appmgr, self.rcore_appmgr_why = (
            self._find_rcore_static("APP_MANAGER")
            if self.is_rcore and self.rcore_kind == 3 else (0, ""))
        if self._has_manifest_procs():
            self.procs_ok, self.procs_reason = self._check_manifest_procs()
        elif self.is_rcore:
            self.procs_ok, self.procs_reason = self._check_rcore_tasks()
        else:
            self.procs_ok, self.procs_reason = self._check_procs()

        self.kmem = locate_array(elf, layout, "kmem", 8, 1)
        self.ref = self._locate_ref()
        self.bcache_loc = locate_array(
            elf, layout, "bcache", layout.sizes.get("buf", 0), self.nbuf,
            extra_tail=layout.sizes.get("buf", 0))
        self.ftable_loc = locate_array(
            elf, layout, "ftable", layout.sizes.get("file", 0), self.nfile)
        self.itable_loc = locate_array(
            elf, layout, "itable", layout.sizes.get("inode", 0), self.ninode)

    _KERNEL_END_SYMS = ("end", "ekernel")

    def _find_kernel_end(self) -> tuple[int, str]:
        for n in self._KERNEL_END_SYMS:
            s = self.elf.sym(n)
            if s is not None and s.value:
                return s.value, n
        return 0, ""

    def _find_rcore_static(self, ident: str) -> tuple[int, str]:
        cands = [s for s in self.elf.symbols
                 if s.value and s.is_object
                 and ident in s.name and "LAZY" in s.name]
        if not cands:
            return 0, (f"内核里没有 {ident} 的 lazy_static 静态量符号"
                       f"（这一章可能本来就没有它；也可能是内核被 strip 了）")
        uniq = {s.value for s in cands}
        if len(uniq) > 1:
            return 0, (f"找到 {len(uniq)} 个疑似 {ident} 的静态量符号，"
                       f"无法确定用哪个，任务表标为不可用")
        return cands[0].value, ""

    def _find_rcore_taskmgr(self) -> tuple[int, str]:
        return self._find_rcore_static("TASK_MANAGER")

    def _check_rcore_tasks(self) -> tuple[bool, str]:
        L = self.layout
        kind = self.rcore_kind
        chain = L.note("task-chain") or ""

        def fail(msg: str) -> tuple[bool, str]:
            return False, msg + (f"（{chain}）" if chain else "")

        if kind is None:
            return fail("这一章没有判定出任务表形态"
                        "（ch1 本来就没有任务概念）。")

        if kind == 3:
            return fail("这一章是批处理内核，没有进程/任务列表可以重建。")

        if kind in (0, 1):
            if not self.rcore_tm:
                return False, self.rcore_tm_why
            need = ["rcore.taskmgr_from_lazy", "task.task_status"]
            if kind == 1:
                need += ["rcore.tasks_ptr", "rcore.tasks_len"]
            else:
                need += ["rcore.tasks", "rcore.num_app"]
            lack = [n for n in need if not L.has(n)]
            if lack:
                return fail(f"任务表的偏移没解全，缺：{'、'.join(lack)}。")
            if "task" not in L.sizes:
                return False, "拿不到 TaskControlBlock 的大小，没法按下标切分任务数组"
            return True, ""

        if kind == 2:
            if not self.rcore_initproc:
                return fail(f"{self.rcore_initproc_why} —— 没有树根就无法枚举进程。")
            need = ["rcore.initproc_from_lazy", "rcore.arc_data", "rcore.tcb_inner",
                    "rcore.tcb_status", "rcore.children_ptr", "rcore.children_len"]
            lack = [n for n in need if not L.has(n)]
            if lack:
                return fail(f"进程树的偏移没解全，缺：{'、'.join(lack)}。")
            return True, ""

        if kind == 4:
            if not self.rcore_initproc:
                return fail(f"{self.rcore_initproc_why} —— 没有树根就无法枚举进程。")
            need = ["rcore.initproc_from_lazy", "rcore.arc_pcb_data",
                    "rcore.pcb_inner", "rcore.pcb_children_ptr",
                    "rcore.pcb_children_len"]
            lack = [n for n in need if not L.has(n)]
            if lack:
                return fail(f"进程树的偏移没解全，缺：{'、'.join(lack)}。")
            return True, ""

        return fail(f"不认识的任务表形态 KIND={kind}。")

    @property
    def image_fit(self) -> KernelImageFit:
        if self._fit is None or not self._fit.found:
            self._fit = self.ram.find_kernel_image(self.elf)
        return self._fit

    _windows: Sequence[int] = ()
    _windows_why: str = "还没量过（要先有观测到的页表根）"
    _roots: Sequence[int] = ()

    _WINDOW_MIN_BYTES = 2 * 1024 * 1024

    _WINDOW_MIN_RUN_BYTES = 64 * 1024

    def _derive_windows(self, roots: Sequence[int]) -> tuple[list[int], str]:
        roots = [r for r in roots if r]
        if not roots:
            return [], "没有观测到页表根，量不出线性窗口"
        if self.e_machine != EM_RISCV:
            who = MACHINE_NAMES.get(self.e_machine, f"e_machine={self.e_machine}")
            return [], f"这个二进制是 {who}，只会走 RISC-V 的 Sv39 页表，没法量线性窗口"
        cover: dict[int, int] = {}
        leaves: dict[int, list[tuple[int, int]]] = {}
        walked = 0
        for root in dict.fromkeys(roots):
            maps, _pt, _err = walk_pagetable(self.ram, root, machine=self.e_machine)
            if not maps:
                continue
            walked += 1
            for m in maps:
                if not (m.va & (1 << 38)):
                    continue
                va = m.va | (MASK64 << 39) & MASK64
                size = 4096 << (9 * m.level)
                off = (va - m.pa) & MASK64
                cover[off] = cover.get(off, 0) + size
                leaves.setdefault(off, []).append((va, size))
            break
        if not walked:
            return [], "没有能走通的页表根，量不出线性窗口"
        keep = sorted(
            (o for o in cover
             if cover[o] >= self._WINDOW_MIN_BYTES
             or _longest_run(leaves[o]) >= self._WINDOW_MIN_RUN_BYTES),
            key=lambda o: -cover[o])
        if not keep:
            return [], (f"页表里没有覆盖超过 {self._WINDOW_MIN_BYTES // 1048576} MiB "
                        f"、也没有连续超过 {self._WINDOW_MIN_RUN_BYTES // 1024} KiB "
                        f"的线性窗口（共 {len(cover)} 个不同的 va-pa 差）")
        return keep, ""

    def note_observed_roots(self, roots: Sequence[int] | None) -> None:
        if roots:
            self._roots = list(roots)

    @property
    def kmem_view(self):
        fit = self.image_fit
        offs: list[int] = [fit.offset] if fit.found and fit.offset else []

        if not self._windows:
            self._windows, self._windows_why = self._derive_windows(self._roots)
        offs += list(self._windows)

        return KernelView(self.ram, offs) if offs else self.ram

    def _proc_entity(self):
        entities = self.entities
        return (None if entities is None else
                entities.entity_for("process", fallback="task"))

    def _has_manifest_procs(self) -> bool:
        return self._proc_entity() is not None

    def _check_manifest_procs(self) -> tuple[bool, str]:
        spec = self._proc_entity()
        if self.entities.compiled(spec.name):
            return True, ""
        why = self.entities.why_not(spec.name)
        return False, (
            f"manifest 声明的进程实体 {spec.name!r} 枚举计划没编出来"
            + (f"：{why}" if why else "。"))

    def _check_procs(self) -> tuple[bool, str]:
        if not self.proc_base:
            note = self.layout.note("proc-table")
            return False, note or (
                "内核 ELF 里没有 proc 符号，找不到进程表基址。"
                "进程表可能不是固定地址的静态数组（比如在堆上的动态容器），"
                "这种情况下外部观测无法安全定位。")
        need = ("proc.state", "proc.pid", "proc.pagetable")
        lack = [f for f in need if not self.layout.has(f)]
        if "proc" not in self.layout.sizes or lack:
            return False, (
                f"有 proc 符号，但内核布局里缺 {'sizeof(proc)' if 'proc' not in self.layout.sizes else ''}"
                f"{'、'.join(lack)}，无法按槽位切分进程表。"
                + (f"（{self.layout.note('struct-layout')}）"
                   if self.layout.note("struct-layout") else ""))
        return True, ""

    def _locate_ref(self) -> ArrayLoc:
        sym = self.elf.sym("ref")
        if sym is None or not sym.value:
            return ArrayLoc(0, 0, 4, 0, False, "内核里没有 ref 符号（该阶段可能没有 COW）")
        lock_size = self.layout.sizes.get("spinlock", 24)
        off = (lock_size + 7) & ~7
        n = (sym.size - off) // 4 if sym.size else 0
        if n <= 0:
            return ArrayLoc(sym.value, off, 4, 0, False, "ref 数组长度推算失败")
        abs_pages = self.phystop // PGSIZE
        rel_pages = (self.phystop - self.kernbase) // PGSIZE
        loc = ArrayLoc(sym.value, off, 4, n, True)
        if n >= abs_pages:
            loc.reason = "absolute-ppn"
        elif n >= rel_pages:
            loc.reason = "kernbase-relative"
        else:
            loc.ok = False
            loc.reason = f"ref 数组只有 {n} 项，覆盖不了物理内存，标记为不可用"
        return loc


    def decode(self, insn: int, snap_seq: int, *,
               observed_roots: list[int] | None = None) -> SystemState:
        ram = self.ram
        self.note_observed_roots(observed_roots)
        st = SystemState(insn=insn, snap_seq=snap_seq, ticks=None, complete=True)

        st.ticks = ram.u32(self.ticks_addr) if self.ticks_addr else None
        st.procs_available = self.procs_ok
        st.procs_reason = self.procs_reason

        tabled = [e for e in getattr(getattr(self.entities, "m", None),
                                     "entities", []) if e.table is not None]
        snap = (self.entities.build(self.kmem_view)
                if self.entities is not None and (self.procs_ok or tabled)
                else None)

        if not self.procs_ok:
            st.procs = []
        elif snap is not None:
            st.procs = self._procs_from_entities(st, snap)
            st.sched_owners = self._sched_owners(snap)
        elif self.is_rcore:
            st.procs = ({2: self._decode_rcore_tree,
                         4: self._decode_rcore_proc_tree}
                        .get(self.rcore_kind, self._decode_rcore_flat))(st)
        else:
            st.procs = self._decode_procs()
        st.cpus = self._decode_cpus(st.procs)
        self._decode_physical(st, observed_roots or [])

        if tabled and snap is not None:
            from . import resources as _R
            st.resources = _R.from_entities(self.entities.m, self.entities.res,
                                            snap)
        elif self.entities is None:
            st.resources_reason = ("没有走 manifest 那条路，资源表只能由 manifest "
                                   "声明 —— 不是说这个内核没有资源表，是我们没去看。")
        elif not tabled:
            st.resources_reason = "这个内核的 manifest 没有声明 [entity.table]。"
        else:
            st.resources_reason = "这一帧没能建出实体快照。"
        return st

    def _sched_owners(self, snap: "Snapshot") -> dict[int, dict]:
        kinds = [e.name for e in self.entities.m.entities
                 if any(f.role == "sched_context"
                        for f in list(e.fields) + list(e.relations))]
        out: dict[int, dict] = {}
        for k in kinds:
            for e in snap.all(k):
                c = e.role("sched_context")
                if isinstance(c, int) and not isinstance(c, bool):
                    out.setdefault(c, {"kind": k, "id": e.role("id"),
                                       "name": e.role("name")})
        return out

    def _procs_from_entities(self, st: "SystemState",
                             snap: "Snapshot") -> list["ProcInfo"]:
        from ..model.snapshot import is_live
        from . import procview

        spec = self._proc_entity()
        if spec is None:
            st.procs_available = False
            st.procs_reason = (
                "manifest 里没有哪个实体标了 role = \"process\"，也没有叫 "
                "task 的实体 —— 不知道该把哪一类当进程列出来")
            return []
        es = snap.sets.get(spec.name)
        ents = [] if es is None else es.entities
        # Only failures in the selected process entity qualify the process
        # table.  A broken resource table (for example blockcache) is reported
        # by the resource view; it must not turn a successfully decoded process
        # tree into "processes unavailable".
        why = ([] if es is None else
               ([es.unavailable] if es.unavailable else [])
               + [p.reason for p in es.problems])
        if why:
            st.procs_reason = "；".join(why)
            if not ents:
                st.procs_available = False
        if es is not None and es.truncated:
            st.procs_reason = "；".join(
                [*why, "到达上限被截断，列出来的是**至少**这些，不是全部"])
        alive = spec.liveness
        slot_of = {e.addr: i for i, e in enumerate(ents)}

        out: list[ProcInfo] = []
        for i, e in enumerate(ents):
            if not is_live(e, alive):
                continue
            r = procview.row(e, slot=i)
            parent = e.link("parent")
            out.append(ProcInfo(
                slot=i,
                pid=r["pid"],
                name=r["name"],
                state=None,
                state_name=r["state_name"],
                sz=r["sz"],
                pagetable=r["pagetable"],
                parent_slot=None if parent is None else slot_of.get(parent.addr),
                parent_pid=r["parent_pid"],
                chan=r["chan"], killed=r["killed"], xstate=r["xstate"],
                kstack=r["kstack"], trapframe=r["trapframe"],
                priority=r["priority"], stride=r["stride"],
                pass_value=r["pass"],
                open_fds=r["fds"],
                cwd=r["cwd"],
                sched_ctx=r["sched_ctx"],
                sched_ctxs=r["sched_ctxs"],
                fields=procview.fields_view(e),
            ))
        return out

    @staticmethod
    def satp_root(satp: int) -> int | None:
        if not satp or (satp >> 60) != 8:
            return None
        return (satp & ((1 << 44) - 1)) << PGSHIFT


    _RCORE_MAX_TASKS = 4096

    _RCORE_MAX_NODES = 4096

    def _rcore_states(self) -> dict[int, str]:
        return {v: k.split(".")[-1] for k, v in self.layout.consts.items()
                if k.startswith("enum.TaskStatus.")}

    def _arc_vec(self, base: int, ptr_key: str, len_key: str) -> list[int]:
        L, ram = self.layout, self.ram
        if not (L.has(ptr_key) and L.has(len_key)):
            return []
        n = ram.u64(base + L.off(len_key))
        p = ram.u64(base + L.off(ptr_key))
        if not n or not p or n > self._RCORE_MAX_NODES:
            return []
        out = []
        for i in range(int(n)):
            v = ram.u64(p + i * 8)
            if v:
                out.append(v)
        return out

    def _walk_rcore_tree(self, root_ptr: int, children_ptr_key: str,
                         children_len_key: str, arc_data_key: str
                         ) -> list[tuple[int, int | None]]:
        L = self.layout
        ad = L.off(arc_data_key)
        seen: set[int] = set()
        order: list[tuple[int, int | None]] = []
        queue: list[tuple[int, int | None]] = [(root_ptr, None)]
        while queue and len(order) < self._RCORE_MAX_NODES:
            arc, parent = queue.pop(0)
            if arc in seen:
                continue
            seen.add(arc)
            node = arc + ad
            order.append((node, parent))
            for ch in self._arc_vec(node, children_ptr_key, children_len_key):
                if ch not in seen:
                    queue.append((ch, arc))
        return order


    def _decode_rcore_tree(self, st: SystemState) -> list[ProcInfo]:
        L, ram = self.layout, self.ram
        root_arc = ram.u64(self.rcore_initproc + L.off("rcore.initproc_from_lazy"))
        if not root_arc:
            st.procs_available = False
            st.procs_reason = (
                "INITPROC 里的 Arc 指针读不到或为空 —— 它是 lazy_static，"
                "第一次用到时才建，这一时刻可能还没初始化")
            return []

        cur = None
        if self.rcore_processor and L.has("rcore.processor_current"):
            c = ram.u64(self.rcore_processor + L.off("rcore.processor_current"))
            cur = c or None

        states = self._rcore_states()
        nodes = self._walk_rcore_tree(root_arc, "rcore.children_ptr",
                                      "rcore.children_len", "rcore.arc_data")
        idx = {n: i for i, (n, _) in enumerate(nodes)}
        ad = L.off("rcore.arc_data")
        out: list[ProcInfo] = []
        for i, (node, parent_arc) in enumerate(nodes):
            state = ram.u8(node + L.off("rcore.tcb_status"))
            if state is None:
                continue
            ppn = (ram.u64(node + L.off("rcore.tcb_root_ppn"))
                   if L.has("rcore.tcb_root_ppn") else None)
            tcx = (ram.u64(node + L.off("rcore.tcb_trap_cx_ppn"))
                   if L.has("rcore.tcb_trap_cx_ppn") else None)
            pnode = (parent_arc + ad) if parent_arc else None
            out.append(ProcInfo(
                slot=i, pid=i, name="",
                state=state, state_name=states.get(state, f"?{state}"),
                sz=None,
                pagetable=(ppn << PGSHIFT) if ppn else 0,
                parent_slot=idx.get(pnode) if pnode else None,
                parent_pid=idx.get(pnode) if pnode else None,
                chan=None, killed=None,
                xstate=(ram.u32(node + L.off("rcore.tcb_exit_code"))
                        if L.has("rcore.tcb_exit_code") else None),
                kstack=None,
                trapframe=(tcx << PGSHIFT) if tcx else None,
                priority=None, stride=None, pass_value=None,
                open_fds=None, cwd=None,
            ))

        why = ["任务是从 INITPROC 顺 children 走进程树枚举的，不是读就绪队列"
               "（就绪队列里只有 Ready 的，会漏掉正在跑的和已退出未回收的）",
               "编号是遍历序号，不是内核里的 pid —— pid 存在 PidHandle 里，"
               "本次没有解析"]
        if cur is not None:
            ci = idx.get(cur + ad)
            why.append(f"当前运行的是遍历序号 {ci}" if ci is not None
                       else "当前运行的那个任务不在从 INITPROC 走到的树里"
                            "（可能是快照落在切换中途）")
        elif self.rcore_processor:
            why.append("PROCESSOR.current 是空的：此刻没有任务在跑（或还没调度）")
        st.procs_reason = "；".join(why)
        return out

    def _decode_rcore_proc_tree(self, st: SystemState) -> list[ProcInfo]:
        L, ram = self.layout, self.ram
        root_arc = ram.u64(self.rcore_initproc + L.off("rcore.initproc_from_lazy"))
        if not root_arc:
            st.procs_available = False
            st.procs_reason = (
                "INITPROC 里的 Arc 指针读不到或为空 —— 它是 lazy_static，"
                "第一次用到时才建，这一时刻可能还没初始化")
            return []

        nodes = self._walk_rcore_tree(root_arc, "rcore.pcb_children_ptr",
                                      "rcore.pcb_children_len", "rcore.arc_pcb_data")
        idx = {n: i for i, (n, _) in enumerate(nodes)}
        ad = L.off("rcore.arc_pcb_data")
        out: list[ProcInfo] = []
        n_threads = 0
        for i, (node, parent_arc) in enumerate(nodes):
            ppn = (ram.u64(node + L.off("rcore.pcb_root_ppn"))
                   if L.has("rcore.pcb_root_ppn") else None)
            zombie = (ram.u8(node + L.off("rcore.pcb_is_zombie"))
                      if L.has("rcore.pcb_is_zombie") else None)
            threads = self._arc_vec(node, "rcore.pcb_tasks_ptr", "rcore.pcb_tasks_len")
            n_threads += len(threads)
            pnode = (parent_arc + ad) if parent_arc else None
            out.append(ProcInfo(
                slot=i, pid=i, name="",
                state=None,
                state_name=("zombie" if zombie else "alive") if zombie is not None
                           else "?",
                sz=None,
                pagetable=(ppn << PGSHIFT) if ppn else 0,
                parent_slot=idx.get(pnode) if pnode else None,
                parent_pid=idx.get(pnode) if pnode else None,
                chan=None, killed=None,
                xstate=(ram.u32(node + L.off("rcore.pcb_exit_code"))
                        if L.has("rcore.pcb_exit_code") else None),
                kstack=None, trapframe=None,
                priority=None, stride=None, pass_value=None,
                open_fds=None, cwd=None,
            ))

        why = ["这一章列的是**进程**（ProcessControlBlock），从 INITPROC 顺 "
               "children 走出来",
               f"这些进程下面一共挂着 {n_threads} 个线程；线程不单独列出，"
               f"否则同一个地址空间会被重复计数",
               "状态只有 is_zombie（进程没有 TaskStatus 字段），"
               "所以这里显示 alive/zombie 而不是 Ready/Running",
               "编号是遍历序号，不是内核里的 pid"]
        st.procs_reason = "；".join(why)
        return out

    def _decode_rcore_flat(self, st: SystemState) -> list[ProcInfo]:
        L, ram = self.layout, self.ram
        tm = self.rcore_tm + L.off("rcore.taskmgr_from_lazy")
        tsz = L.size("task")

        inline = L.consts.get("RCORE_TASKS_KIND", 1) == 0
        n_key = "rcore.num_app" if inline else "rcore.tasks_len"
        n = ram.u64(tm + L.off(n_key))
        if n is None:
            st.procs_available = False
            st.procs_reason = (
                f"任务数组的长度字段 {n_key}（物理地址 0x{tm + L.off(n_key):x}）"
                f"不在本次快照里，任务表无法重建")
            return []
        cap = L.consts.get("RCORE_TASKS_CAP")
        if inline and cap is not None and n > cap:
            st.procs_available = False
            st.procs_reason = (
                f"读到的 num_app={n} 超过数组容量 {cap}，两者对不上，"
                f"这一时刻的任务表标为不可用")
            return []
        if n > self._RCORE_MAX_TASKS:
            st.procs_available = False
            st.procs_reason = (
                f"读到的任务数 {n} 明显不合理（上限 {self._RCORE_MAX_TASKS}）。"
                f"快照可能正好落在 Vec 扩容中途，读到的长度和指针对不上，"
                f"这一时刻的任务表标为不可用。")
            return []

        if inline:
            arr = tm + L.off("rcore.tasks")
        else:
            ptr = ram.u64(tm + L.off("rcore.tasks_ptr"))
            if not ptr:
                st.procs_available = False
                st.procs_reason = (
                    "任务数组的堆指针读不到或为空 —— 任务表可能还没初始化"
                    "（TASK_MANAGER 是 lazy_static，第一次用到时才建）")
                return []
            arr = ptr

        root_off = L.off("rcore.task_root_ppn") if L.has("rcore.task_root_ppn") else None
        cur_idx = (ram.u64(tm + L.off("rcore.current_task"))
                   if L.has("rcore.current_task") else None)
        states = {v: k.split(".")[-1] for k, v in L.consts.items()
                  if k.startswith("enum.TaskStatus.")}

        out: list[ProcInfo] = []
        for i in range(int(n)):
            base = arr + i * tsz
            state = ram.u8(base + L.off("task.task_status"))
            if state is None:
                continue
            root = None
            if root_off is not None:
                ppn = ram.u64(base + root_off)
                root = (ppn << PGSHIFT) if ppn else None
            out.append(ProcInfo(
                slot=i, pid=i,
                name="",
                state=state,
                state_name=states.get(state, f"?{state}"),
                sz=(ram.u64(base + L.off("task.base_size"))
                    if L.has("task.base_size") else None),
                pagetable=root or 0,
                parent_slot=None, parent_pid=None,
                chan=None, killed=None, xstate=None,
                kstack=None,
                trapframe=(ram.u64(base + L.off("task.trap_cx_ppn")) << PGSHIFT
                           if L.has("task.trap_cx_ppn")
                           and ram.u64(base + L.off("task.trap_cx_ppn")) else None),
                priority=None, stride=None, pass_value=None,
                open_fds=None, cwd=None,
            ))

        why = ["rCore 没有 pid，这里的编号是任务在 TaskManager.tasks 里的下标"
               "（等于 app id）"]
        if cur_idx is not None:
            why.append(f"当前运行的是下标 {cur_idx}")
        if not L.has("rcore.task_root_ppn"):
            why.append("拿不到任务页表根，物理页归属无法按任务区分")
        st.procs_reason = "；".join(why)
        return out

    def _decode_procs(self) -> list[ProcInfo]:
        L = self.layout
        sz = L.size("proc")
        out: list[ProcInfo] = []
        addr_to_slot = {self.proc_base + i * sz: i for i in range(self.nproc)}

        for i in range(self.nproc):
            base = self.proc_base + i * sz
            state = self.ram.i32(base + L.off("proc.state"))
            if state is None:
                continue
            pid = self.ram.i32(base + L.off("proc.pid")) or 0
            if state == 0 and pid == 0:
                continue

            parent = self.ram.u64(base + L.off("proc.parent")) or 0
            parent_slot = addr_to_slot.get(parent)
            parent_pid = None
            if parent_slot is not None:
                parent_pid = self.ram.i32(
                    self.proc_base + parent_slot * sz + L.off("proc.pid"))

            fds = []
            ofile_off = L.off("proc.ofile")
            for f in range(self.nofile):
                v = self.ram.u64(base + ofile_off + f * 8)
                if v:
                    fds.append(f)

            def opt(field_name):
                return (self.ram.i32(base + L.off(field_name))
                        if L.has(field_name) else None)

            out.append(ProcInfo(
                slot=i, pid=pid, name=self.ram.cstr(base + L.off("proc.name"), 16) or "",
                state=state,
                state_name=PROC_STATES[state] if 0 <= state < len(PROC_STATES) else f"?{state}",
                sz=self.ram.u64(base + L.off("proc.sz")) or 0,
                pagetable=self.ram.u64(base + L.off("proc.pagetable")) or 0,
                parent_slot=parent_slot, parent_pid=parent_pid,
                chan=self.ram.u64(base + L.off("proc.chan")) or 0,
                killed=self.ram.i32(base + L.off("proc.killed")) or 0,
                xstate=self.ram.i32(base + L.off("proc.xstate")) or 0,
                kstack=self.ram.u64(base + L.off("proc.kstack")) or 0,
                trapframe=self.ram.u64(base + L.off("proc.trapframe")) or 0,
                priority=opt("proc.priority"), stride=opt("proc.stride"),
                pass_value=opt("proc.pass"),
                open_fds=fds,
                cwd=self.ram.u64(base + L.off("proc.cwd")) or 0,
                sched_ctx=(base + L.off("proc.context")
                           if L.has("proc.context") else None),
            ))
        return out

    def _decode_cpus(self, procs: list[ProcInfo]) -> list[dict]:
        if not self.cpus_base or "cpu" not in self.layout.sizes:
            return []
        L = self.layout
        sz = L.size("cpu")
        by_addr: dict[int, ProcInfo] = {}
        if (self.procs_ok and self.proc_base
                and "proc" in L.sizes and L.has("cpu.proc")):
            psz = L.size("proc")
            by_addr = {self.proc_base + p.slot * psz: p for p in procs}
        out = []
        for c in range(self.ncpu):
            base = self.cpus_base + c * sz
            pptr = self.ram.u64(base + L.off("cpu.proc"))
            if pptr is None:
                continue
            p = by_addr.get(pptr)
            out.append({
                "cpu": c,
                "proc_addr": pptr,
                "pid": p.pid if p else None,
                "name": p.name if p else None,
                "noff": self.ram.i32(base + L.off("cpu.noff")),
                "intena": self.ram.i32(base + L.off("cpu.intena")),
            })
        return out


    def _decode_physical(self, st: SystemState, observed_roots: list[int]) -> None:
        ram = self.ram
        npages = ram.size // PGSIZE
        kind = bytearray([K_UNKNOWN]) * npages
        pid_of = [0] * npages
        st.phys_total = npages

        def idx_of(pa: int) -> int | None:
            if pa < ram.base or pa >= ram.base + ram.size:
                return None
            return (pa - ram.base) >> PGSHIFT

        if self.end_addr:
            for i in range(0, min(npages, idx_of(self.end_addr) or 0) + 1):
                kind[i] = K_KERNEL_IMAGE

        if self.kmem.ok:
            head = ram.u64(self.kmem.base + self.kmem.elem_off)
            free_count, guard = 0, 0
            seen: set[int] = set()
            node = head or 0
            while node and guard < npages + 16:
                guard += 1
                i = idx_of(node)
                if i is None or node in seen:
                    st.phys_reason = "空闲链表走到了非法地址或出现环，遍历中止"
                    st.phys_free_available = False
                    break
                seen.add(node)
                kind[i] = K_FREE
                pid_of[i] = 0
                free_count += 1
                nxt = ram.u64(node)
                if nxt is None:
                    st.phys_reason = "空闲链表中断（该页未被快照覆盖）"
                    st.phys_free_available = False
                    break
                node = nxt
            st.phys_free = free_count
        else:
            st.phys_free_available = False
            st.phys_reason = self.kmem.reason

        mapped_by: dict[int, set[int]] = {}
        if self.procs_ok:
            st.pagetable_root_source = "proc-table"
            roots: list[tuple[int, ProcInfo | None]] = [
                (p.pagetable, p) for p in st.procs if p.pagetable]
        else:
            st.pagetable_root_source = "observed-satp" if observed_roots else ""
            roots = [(r, None) for r in dict.fromkeys(observed_roots) if r]

        if roots and self.e_machine != EM_RISCV:
            who = MACHINE_NAMES.get(self.e_machine, f"e_machine={self.e_machine}")
            st.pagetable_root_source = ""
            st.pagetable_errors.append(
                f"这个二进制是 {who}，NodeFusion 只会走 RISC-V 的 Sv39 页表，"
                f"因此这一时刻的 {len(roots)} 个页表根一个都没有遍历")
            roots = []

        for root, p in roots:
            maps, ptpages, err = walk_pagetable(ram, root,
                                                machine=self.e_machine)
            if p is not None:
                p.vm_error = err
            elif err:
                st.pagetable_errors.append(f"页表根 0x{root:x}：{err}")
            regions = []
            pid = p.pid if p is not None else 0
            for m in maps:
                i = idx_of(m.pa)
                if i is None:
                    continue
                if m.flags & PTE_U:
                    mapped_by.setdefault(i, set()).add(pid)
                    if kind[i] not in (K_TRAPFRAME,):
                        kind[i] = K_USER
                        pid_of[i] = pid
                    if p is not None:
                        p.user_pages += 1
                        if m.flags & PTE_COW:
                            p.cow_pages += 1
                elif p is not None:
                    if kind[i] == K_UNKNOWN:
                        kind[i] = K_TRAPFRAME
                        pid_of[i] = pid
                regions.append([m.va, m.pa, m.flags])
            for pa in ptpages:
                i = idx_of(pa)
                if i is not None and kind[i] in (K_UNKNOWN, K_KERNEL_OTHER):
                    kind[i] = K_PAGETABLE
                    pid_of[i] = pid
                    if p is not None:
                        p.pagetable_pages += 1
            if p is not None:
                if p.kstack:
                    i = idx_of(p.kstack)
                    if i is not None and kind[i] == K_UNKNOWN:
                        kind[i] = K_KSTACK
                        pid_of[i] = pid
                p.vm_regions = regions

        if self.procs_ok:
            shared = 0
            for i, owners in mapped_by.items():
                if len(owners) > 1:
                    kind[i] = K_USER_SHARED
                    shared += 1
            st.shared_pages = shared

        if st.phys_free_available:
            for i in range(npages):
                if kind[i] == K_UNKNOWN:
                    kind[i] = K_KERNEL_OTHER
            st.phys_used = npages - st.phys_free
        else:
            st.phys_free = 0
            st.phys_used = 0
            if not st.phys_reason:
                st.phys_reason = "拿不到空闲链表，空闲/占用页数无法确定"

        st.phys_available = bool(self.end_addr or roots)
        if not st.phys_available and not st.phys_reason:
            st.phys_reason = ("既没有内核末尾符号，也没有可用的页表根，"
                              "物理页归属无法重建")

        if st.pagetable_errors:
            note = f"有 {len(st.pagetable_errors)} 棵页表未走完，归属可能偏少"
            st.phys_reason = f"{st.phys_reason}；{note}" if st.phys_reason else note

        st.phys_kind = kind
        st.phys_pid = pid_of
        st.refcounts_available = self.ref.ok

    def refcount_of(self, pa: int) -> int | None:
        if not self.ref.ok:
            return None
        if self.ref.reason == "kernbase-relative":
            idx = (pa - self.kernbase) // PGSIZE
        else:
            idx = pa // PGSIZE
        if idx < 0 or idx >= self.ref.count:
            return None
        return self.ram.i32(self.ref.base + self.ref.elem_off + idx * 4)


    def _decode_bcache(self) -> ResourceTable:
        loc, L = self.bcache_loc, self.layout
        if not loc.ok:
            return ResourceTable(False, loc.reason)
        rows = []
        for i in range(loc.count):
            b = loc.base + loc.elem_off + i * loc.elem_size
            rows.append({
                "slot": i,
                "valid": self.ram.i32(b + L.off("buf.valid")),
                "disk": self.ram.i32(b + L.off("buf.disk")),
                "dev": self.ram.u32(b + L.off("buf.dev")),
                "blockno": self.ram.u32(b + L.off("buf.blockno")),
                "refcnt": self.ram.u32(b + L.off("buf.refcnt")),
            })
        return ResourceTable(True, "", rows)

    def _decode_ftable(self) -> ResourceTable:
        loc, L = self.ftable_loc, self.layout
        if not loc.ok:
            return ResourceTable(False, loc.reason)
        kinds = {0: "NONE", 1: "PIPE", 2: "INODE", 3: "DEVICE"}
        rows = []
        for i in range(loc.count):
            b = loc.base + loc.elem_off + i * loc.elem_size
            t = self.ram.i32(b + L.off("file.type"))
            ref = self.ram.i32(b + L.off("file.ref"))
            if not ref:
                continue
            rows.append({
                "slot": i, "type": kinds.get(t, f"?{t}"), "ref": ref,
                "readable": self.ram.u8(b + L.off("file.readable")),
                "writable": self.ram.u8(b + L.off("file.writable")),
                "inode": self.ram.u64(b + L.off("file.ip")),
                "off": self.ram.u32(b + L.off("file.off")),
            })
        return ResourceTable(True, "", rows)

    def _decode_itable(self) -> ResourceTable:
        loc, L = self.itable_loc, self.layout
        if not loc.ok:
            return ResourceTable(False, loc.reason)
        rows = []
        for i in range(loc.count):
            b = loc.base + loc.elem_off + i * loc.elem_size
            ref = self.ram.i32(b + L.off("inode.ref"))
            if not ref:
                continue
            rows.append({
                "slot": i, "ref": ref,
                "dev": self.ram.u32(b + L.off("inode.dev")),
                "inum": self.ram.u32(b + L.off("inode.inum")),
                "valid": self.ram.i32(b + L.off("inode.valid")),
                "type": self.ram.u16(b + L.off("inode.type")),
                "size": self.ram.u32(b + L.off("inode.size")),
                "nlink": self.ram.u16(b + L.off("inode.nlink")),
            })
        return ResourceTable(True, "", rows)
