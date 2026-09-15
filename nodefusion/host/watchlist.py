
from __future__ import annotations

from dataclasses import dataclass, field

from .nfelf import Elf64

DEFAULT_WATCH: list[tuple[str, str]] = [
    ("kalloc", "phys_page"), ("kfree", "phys_page"),
    ("uvmalloc", "vm"), ("uvmdealloc", "vm"), ("uvmcopy", "vm"),
    ("uvmunmap", "vm"), ("uvmfree", "vm"), ("mappages", "pagetable"),
    ("copyout", "vm"), ("copyin", "vm"),
    ("usertrap", "trap"), ("kerneltrap", "trap"), ("usertrapret", "trap"),
    ("devintr", "interrupt"), ("clockintr", "interrupt"),
    ("allocproc", "proc"), ("freeproc", "proc"),
    ("fork", "proc"), ("exit", "proc"), ("wait", "proc"), ("kill", "proc"),
    ("growproc", "proc"), ("forkret", "proc"), ("reparent", "proc"),
    ("procinit", "proc"), ("userinit", "proc"), ("spawn", "proc"),
    ("scheduler", "sched"), ("sched", "sched"), ("yield", "sched"),
    ("swtch", "sched"),
    ("sleep", "sync"), ("wakeup", "sync"),
    ("syscall", "syscall"), ("exec", "proc"),
    ("binit", "bcache"), ("bget", "bcache"), ("bread", "bcache"),
    ("bwrite", "bcache"), ("brelse", "bcache"),
    ("begin_op", "log"), ("end_op", "log"), ("log_write", "log"),
    ("commit", "log"), ("write_log", "log"), ("install_trans", "log"),
    ("recover_from_log", "log"),
    ("virtio_disk_rw", "disk"), ("virtio_disk_intr", "disk"),
    ("ialloc", "inode"), ("iget", "inode"), ("iput", "inode"),
    ("ilock", "inode"), ("iunlock", "inode"), ("iupdate", "inode"),
    ("bmap", "inode"), ("readi", "inode"), ("writei", "inode"),
    ("balloc", "disk"), ("bfree", "disk"), ("namei", "inode"),
    ("dirlookup", "inode"),
    ("filealloc", "file"), ("fileclose", "file"), ("fileread", "file"),
    ("filewrite", "file"), ("filedup", "file"),
    ("pipealloc", "pipe"), ("piperead", "pipe"), ("pipewrite", "pipe"),
    ("pipeclose", "pipe"),
]

ALIASES: dict[str, list[str]] = {
    "fork": ["fork", "kfork"],
    "exit": ["exit", "kexit"],
    "wait": ["wait", "kwait"],
    "kill": ["kill", "kkill"],
    "exec": ["exec", "kexec"],
    "spawn": ["spawn", "kspawn"],
    "usertrapret": ["usertrapret", "prepare_return"],
    "swtch": ["swtch"],
}

#: ---------------------------------------------------------------- rCore
RCORE_WATCH: list[tuple[str, str]] = [
    ("frame_allocator::frame_alloc", "phys_page"),
    ("frame_allocator::frame_dealloc", "phys_page"),
    ("StackFrameAllocator::alloc", "phys_page"),
    ("StackFrameAllocator::dealloc", "phys_page"),
    ("MemorySet::new_kernel", "vm"), ("MemorySet::from_elf", "vm"),
    ("MemorySet::push", "vm"), ("MemorySet::insert_framed_area", "vm"),
    ("MemorySet::append_to", "vm"), ("MemorySet::shrink_to", "vm"),
    ("MemorySet::from_existed_user", "vm"),
    ("MapArea::map", "vm"), ("MapArea::unmap", "vm"),
    ("PageTable::map", "pagetable"), ("PageTable::unmap", "pagetable"),
    ("PageTable::new", "pagetable"),
    ("page_table::translated_byte_buffer", "vm"),
    ("mm::init", "vm"), ("task::change_program_brk", "vm"),
    ("__rust_alloc_error_handler", "panic"),
    ("trap_handler", "trap"), ("trap_return", "trap"),
    ("trap_from_kernel", "trap"),
    ("syscall::syscall", "syscall"),
    ("process::sys_exit", "proc"), ("process::sys_yield", "sched"),
    ("process::sys_fork", "proc"), ("process::sys_exec", "proc"),
    ("process::sys_waitpid", "proc"), ("process::sys_getpid", "proc"),
    ("process::sys_sbrk", "vm"), ("process::sys_mmap", "vm"),
    ("process::sys_munmap", "vm"), ("process::sys_get_time", "syscall"),
    ("fs::sys_read", "file"), ("fs::sys_write", "file"),
    ("fs::sys_open", "file"), ("fs::sys_close", "file"),
    ("fs::sys_pipe", "pipe"), ("fs::sys_dup", "file"),
    ("process::sys_spawn", "proc"), ("process::sys_kill", "proc"),
    ("process::sys_set_priority", "sched"),
    ("thread::sys_thread_create", "proc"), ("thread::sys_waittid", "proc"),
    ("sync::sys_mutex_lock", "sync"), ("sync::sys_mutex_unlock", "sync"),
    ("sync::sys_semaphore_down", "sync"), ("sync::sys_semaphore_up", "sync"),
    ("sync::sys_condvar_wait", "sync"), ("sync::sys_condvar_signal", "sync"),
    ("sync::sys_sleep", "sync"),
    ("task::run_first_task", "proc"), ("task::run_next_task", "sched"),
    ("task::suspend_current_and_run_next", "sched"),
    ("task::exit_current_and_run_next", "proc"),
    ("task::add_initproc", "proc"),
    ("processor::run_tasks", "sched"), ("processor::schedule", "sched"),
    ("processor::take_current_task", "sched"),
    ("manager::add_task", "sched"), ("manager::fetch_task", "sched"),
    ("TaskControlBlock::fork", "proc"), ("TaskControlBlock::exec", "proc"),
    ("TaskControlBlock::new", "proc"),
    ("ProcessControlBlock::fork", "proc"), ("ProcessControlBlock::exec", "proc"),
    ("ProcessControlBlock::new", "proc"),
    ("__switch", "sched"),
    ("MutexBlocking::lock", "sync"), ("MutexBlocking::unlock", "sync"),
    ("Semaphore::up", "sync"), ("Semaphore::down", "sync"),
    ("Condvar::wait", "sync"), ("Condvar::signal", "sync"),
    ("UPSafeCell::exclusive_access", "sync"),
    ("inode::open_file", "file"), ("OSInode::read", "file"),
    ("OSInode::write", "file"),
    ("Inode::find", "inode"), ("Inode::create", "inode"),
    ("Inode::read_at", "inode"), ("Inode::write_at", "inode"),
    ("Inode::clear", "inode"), ("Inode::ls", "inode"),
    ("inode::list_apps", "file"), ("OSInode::read_all", "file"),
    ("DiskInode::increase_size", "inode"),
    ("DiskInode::clear_size", "inode"),
    ("EasyFileSystem::alloc_data", "disk"),
    ("EasyFileSystem::dealloc_data", "disk"),
    ("EasyFileSystem::open", "disk"),
    ("Bitmap::alloc", "disk"), ("Bitmap::dealloc", "disk"),
    ("BlockCacheManager::get_block_cache", "bcache"),
    ("block_cache::block_cache_sync_all", "bcache"),
    ("BlockCache::new", "bcache"), ("BlockCache::sync", "bcache"),
    ("VirtIOBlock::read_block", "disk"), ("VirtIOBlock::write_block", "disk"),
    ("pipe::make_pipe", "pipe"), ("Pipe::read", "pipe"), ("Pipe::write", "pipe"),
]

RCORE_SNAP_ON = {"rust_begin_unwind", "__rust_alloc_error_handler"}

RCORE_EVENT_SNAP_ON = {
    "TaskControlBlock::fork", "TaskControlBlock::exec",
    "ProcessControlBlock::fork", "ProcessControlBlock::exec",
    "task::exit_current_and_run_next",
    "MemorySet::from_existed_user", "MemorySet::from_elf",
    "process::sys_fork", "process::sys_exec", "process::sys_exit",
}

SNAP_ON = {"panic"}

EVENT_SNAP_ON = {"fork", "forkret", "uvmcopy", "exit", "exec"}

NFTRACE_COMMIT = "nftrace_commit_point"


def demangle(name: str) -> str:
    if not name.startswith("_ZN"):
        return name
    s, out, i = name[3:], [], 0
    while i < len(s):
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == i:
            break
        n = int(s[i:j])
        part = s[j:j + n]
        i = j + n
        if len(part) == 17 and part.startswith("h"):
            break
        out.append(part)
    return "::".join(out) if out else name


def _path_index(elf: Elf64) -> dict[str, list]:
    idx: dict[str, list] = {}
    for s in elf.functions():
        path = demangle(s.name)
        if path != s.name:
            idx.setdefault(path, []).append(s)
    return idx


def _bare(seg: str) -> str:
    for esc, ch in (("$LT$", "<"), ("$GT$", ">"), ("$u20$", " "),
                    ("$C$", ","), ("$RF$", "&"), ("$BP$", "*")):
        seg = seg.replace(esc, ch)

    #   _$LT$os..fs..inode..OSInode$u20$as$u20$os..fs..File$GT$::read
    #     -> _<os..fs..inode..OSInode as os..fs..File>::read
    lt, gt = seg.find("<"), seg.rfind(">")
    if lt >= 0 and gt > lt:
        inner = seg[lt + 1:gt]
        if " as " in inner:
            concrete = inner.split(" as ", 1)[0]
            return concrete.replace("..", "::").split("::")[-1]
    return seg[:lt] if lt > 0 else seg


def _match_suffix(idx: dict[str, list], wanted: str) -> list:
    want = [_bare(w) for w in wanted.split("::")]
    hits = []
    for path, syms in idx.items():
        parts = [_bare(p) for p in path.split("::")]
        if len(parts) >= len(want) and parts[-len(want):] == want:
            hits.extend(syms)
    return hits


@dataclass
class WatchEntry:
    index: int
    name: str
    symbol: str
    addr: int
    resource: str
    snap: bool
    throttle: bool = False
    args: int = 2
    rate: int = 0
    params: list = field(default_factory=list)
    kind: str = ""
    operation: str = ""
    classify: dict | None = None


@dataclass
class WatchList:
    entries: list[WatchEntry]
    missing: list[str]
    nftrace_index: int | None

    def to_file_text(self) -> str:
        lines = ["# NodeFusion watch 列表（自动生成）",
                 "# 格式：<入口地址> [@标记:...]<名字>，标记可以连着写",
                 "#   @snap:  命中即抓内存快照，不受限流（崩溃现场）",
                 "#   @esnap: 命中即抓内存快照，受 evsnapmin/evsnapmax 限流",
                 "#   @nft:   guest 语义提交点，命中时读 a0 指向的记录",
                 "#   @rN:    每 N 次命中才记一条事件；@snap/@nft 不受它影响"]
        for e in self.entries:
            tags: list[str] = []
            if e.name == NFTRACE_COMMIT:
                tags.append("@nft:")
            elif e.snap:
                tags.append("@esnap:" if e.throttle else "@snap:")
            if e.rate > 1 and not tags:
                tags.append(f"@r{e.rate}:")
            lines.append(f"0x{e.addr:x} {''.join(tags)}{e.name}")
        return "\n".join(lines) + "\n"

    def to_json(self) -> dict:
        return {
            "entries": [
                {"index": e.index, "name": e.name, "symbol": e.symbol,
                 "addr": e.addr, "resource": e.resource, "snap": e.snap,
                 "throttle": e.throttle, "args": e.args, "rate": e.rate,
                 **({"params": e.params} if e.params else {}),
                 **({"kind": e.kind} if e.kind else {}),
                 **({"operation": e.operation} if e.operation else {}),
                 **({"classify": e.classify} if e.classify else {})}
                for e in self.entries],
            "missing": self.missing,
            "nftrace_index": self.nftrace_index,
        }


_TABLES = {
    "xv6": (DEFAULT_WATCH, SNAP_ON, EVENT_SNAP_ON),
    "rcore": (RCORE_WATCH, RCORE_SNAP_ON, RCORE_EVENT_SNAP_ON),
}


def has_table(kind: str) -> bool:
    return kind in _TABLES


def table_kinds() -> list[str]:
    return sorted(_TABLES)


def _pick_branch(dw, spec):
    if not spec.alts:
        return spec
    from ..model.probe import eval_when
    for one in (spec, *spec.alts):
        ok, _ = eval_when(dw, one.when)
        if ok:
            return one
    raise ValueError(
        f"{spec.kind} 那串候选一条都不成立，而最后一条本该是无条件的兜底")


def build_from_manifest(elf: Elf64, dw, watches, *, watch_all: bool = False,
                        extra: list[tuple[str, str]] | None = None,
                        events: dict | None = None) -> WatchList:
    from ..model.watchsel import select

    syms = [s for s in elf.symbols
            if s.value and s.name and (s.is_func or s.sym_type == 0)]
    sel = select(dw, watches, symbols=syms)

    entries: list[WatchEntry] = []
    nftrace_index = None
    seen_addrs: set[int] = set()

    params_by_addr = {f.low_pc: f.params for f in dw.functions
                      if f.low_pc is not None and f.params}

    ev = events or {}
    ev_used: set[str] = set()

    for s in sel.picked:
        seen_addrs.add(s.addr)
        spec = ev.get(s.path) or ev.get(s.name)
        if spec is not None:
            ev_used.add(s.path if s.path in ev else s.name)
            spec = _pick_branch(dw, spec)
        entries.append(WatchEntry(
            len(entries), s.name, s.path, s.addr,
            (spec.resource if spec is not None and spec.resource
             else s.subsystem),
            s.snapshot in ("always", "event"),
            throttle=s.snapshot == "event",
            args=s.args, rate=s.throttle,
            params=(list(spec.args) if spec is not None and spec.args
                    else params_by_addr.get(s.addr, [])),
            kind=spec.kind if spec is not None else "",
            operation=spec.operation if spec is not None else "",
            classify=(dict(spec.classify)
                      if spec is not None and spec.classify else None)))

    for name, resource in [(NFTRACE_COMMIT, "nftrace"), *(extra or [])]:
        sym = elf.sym(name)
        if sym is None or not sym.value:
            sel.empty_rules.append(f"[{resource}] fn={name!r}")
            continue
        if sym.value in seen_addrs:
            continue
        seen_addrs.add(sym.value)
        if name == NFTRACE_COMMIT:
            nftrace_index = len(entries)
        entries.append(WatchEntry(
            len(entries), name, sym.name, sym.value, resource, False))

    if watch_all:
        for s in elf.functions():
            if s.value in seen_addrs:
                continue
            seen_addrs.add(s.value)
            entries.append(WatchEntry(
                len(entries), s.name, s.name, s.value, "kernel", False))

    for k in sorted(set(ev) - ev_used):
        sel.empty_rules.append(
            f"[event] {k!r} 没匹配上任何观察点（键要么是解修饰后的短名，"
            f"要么是全路径）")

    return WatchList(entries, sel.empty_rules, nftrace_index)


def build(elf: Elf64, *, kind: str, watch_all: bool = False,
          extra: list[tuple[str, str]] | None = None) -> WatchList:
    if kind not in _TABLES:
        raise ValueError(
            f"没有名为 {kind!r} 的 watch 名单，已知的有：{'/'.join(_TABLES)}。"
            f"加新内核要在 watchlist._TABLES 里登记，不能沿用别的内核的函数名。")
    table, snap_on, event_snap_on = _TABLES[kind]

    wanted: list[tuple[str, str]] = list(table)
    if extra:
        wanted += extra
    wanted.append((NFTRACE_COMMIT, "nftrace"))
    for n in sorted(snap_on):
        wanted.append((n, "panic"))

    if watch_all:
        known = {n for n, _ in wanted}
        for s in elf.functions():
            if s.name not in known:
                wanted.append((s.name, "kernel"))

    entries: list[WatchEntry] = []
    missing: list[str] = []
    seen: set[str] = set()
    nftrace_index = None

    path_idx = _path_index(elf)

    for name, resource in wanted:
        if name in seen:
            continue
        seen.add(name)

        syms = []
        for cand in ALIASES.get(name, [name]):
            s = elf.sym(cand)
            if s is not None and s.value and (s.is_func or s.sym_type == 0):
                syms = [s]
                break
        if not syms and path_idx and "::" in name:
            syms = _match_suffix(path_idx, name)
        if not syms:
            missing.append(name)
            continue

        seen_addrs: set[int] = set()
        for sym in sorted(syms, key=lambda s: s.value):
            if sym.value in seen_addrs:
                continue
            seen_addrs.add(sym.value)
            idx = len(entries)
            entries.append(WatchEntry(
                idx, name, sym.name, sym.value, resource,
                name in snap_on or name in event_snap_on,
                throttle=name in event_snap_on and name not in snap_on))
            if name == NFTRACE_COMMIT:
                nftrace_index = idx

    if wanted and not entries:
        raise ValueError(
            f"{kind!r} 这份名单里 {len(wanted)} 个名字在这个 ELF 里一个都没解出来。"
            "这通常意味着名单和内核对不上（比如拿 xv6 的名单去解 rCore），"
            "而不是这些函数都被内联了。"
            f"\n前几个解不出来的：{'、'.join(missing[:5])}")

    return WatchList(entries, missing, nftrace_index)
