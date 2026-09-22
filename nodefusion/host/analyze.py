
from __future__ import annotations

import bisect
import heapq
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import guest as guest_mod
from . import nftrace as trace_mod
from . import watchlist as watchlist_mod
from .layout import KernelLayout
from .nfelf import Elf64

CAUSE_ECALL_U = 8
CAUSE_ECALL_S = 9
CAUSE_PF_INSN = 12
CAUSE_PF_LOAD = 13
CAUSE_PF_STORE = 15

EXCEPTION_NAMES = {
    0: "指令地址未对齐", 1: "取指访问异常", 2: "非法指令", 3: "断点",
    4: "取数地址未对齐", 5: "取数访问异常", 6: "存数地址未对齐",
    7: "存数访问异常", 8: "用户态 ecall（系统调用）", 9: "S 态 ecall（SBI 调用）",
    11: "M 态 ecall", 12: "取指缺页", 13: "取数缺页", 15: "存数缺页",
}
INTERRUPT_NAMES = {
    1: "S 态软件中断", 5: "S 态时钟中断", 9: "S 态外部中断（设备）",
}
MINTERRUPT_NAMES = {
    3: "M 态软件中断", 7: "M 态时钟中断", 11: "M 态外部中断（设备）",
}

SBI_EXT_NAMES = {
    0x00: "legacy:set_timer",       0x01: "legacy:console_putchar",
    0x02: "legacy:console_getchar", 0x03: "legacy:clear_ipi",
    0x04: "legacy:send_ipi",        0x05: "legacy:remote_fence_i",
    0x06: "legacy:remote_sfence_vma",
    0x07: "legacy:remote_sfence_vma_asid",
    0x08: "legacy:shutdown",
    0x10: "BASE", 0x54494D45: "TIME", 0x735049: "sPI", 0x52464E43: "RFNC",
    0x48534D: "HSM", 0x53525354: "SRST", 0x504D55: "PMU",
    0x4442434E: "DBCN", 0x53555350: "SUSP", 0x43505543: "CPPC",
    0x4E41434C: "NACL", 0x535441: "STA",
}


def sbi_ext_name(eid: int) -> str:
    if eid in SBI_EXT_NAMES:
        return SBI_EXT_NAMES[eid]
    if 0 < eid <= 0xFFFFFFFF:
        b = eid.to_bytes(4, "big").lstrip(b"\x00")
        if b and all(0x20 <= c < 0x7F for c in b):
            return f"'{b.decode()}'"
    return f"{eid:#x}"

def load_syscall_names(kernel_dir: Path, spec) -> dict[int, str]:
    import re
    if spec is None:
        return {}
    rx, root = re.compile(spec.pattern), Path(kernel_dir)
    out: dict[int, str] = {}
    for pat in spec.files:
        for p in sorted(root.glob(pat)):
            if not p.is_file():
                continue
            for m in rx.finditer(p.read_text(errors="replace")):
                out[int(m.group("num"))] = m.group("name").lower()
    return out


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Event:
    insn: int
    cpu: int
    kind: str
    resource: str
    pid: int | None = None
    proc: str | None = None
    pc: int | None = None
    func: str | None = None
    tick: int | None = None
    detail: dict = field(default_factory=dict)
    unknown: list = field(default_factory=list)
    function_entry: bool = False
    entry_name: str | None = None
    return_address: int | None = None
    stack_pointer: int | None = None
    address_space: int | None = None

    def to_json(self) -> dict:
        d = {"insn": self.insn, "cpu": self.cpu, "kind": self.kind,
             "resource": self.resource}
        if self.pid is not None:
            d["pid"] = self.pid
        if self.proc:
            d["proc"] = self.proc
        if self.pc is not None:
            d["pc"] = self.pc
        if self.func:
            d["func"] = self.func
        if self.tick is not None:
            d["tick"] = self.tick
        if self.detail:
            d["detail"] = self.detail
        if self.unknown:
            d["unknown"] = self.unknown
        return d


_PROC_EVENT_KINDS = ("proc", "sched")


LEGACY_ARGNAMES: dict[str, list[str]] = {
    "balloc":         ["dev"],
    "bfree":          ["dev", "b"],
    "bget":           ["dev", "blockno"],
    "bmap":           ["ip", "bn"],
    "bread":          ["dev", "blockno"],
    "brelse":         ["buf"],
    "bwrite":         ["buf"],
    "copyin":         ["pagetable", "dst", "srcva", "len"],
    "copyout":        ["pagetable", "dstva", "src", "len"],
    "dirlookup":      ["dp", "name", "poff"],
    "exec":           ["path", "argv"],
    "exit":           ["status"],
    "fileclose":      ["f"],
    "filedup":        ["f"],
    "fileread":       ["f", "addr", "n"],
    "filewrite":      ["f", "addr", "n"],
    "freeproc":       ["proc"],
    "freewalk":       ["pagetable"],
    "growproc":       ["n"],
    "ialloc":         ["dev", "type"],
    "iget":           ["dev", "inum"],
    "ilock":          ["ip"],
    "install_trans":  ["recovering"],
    "iput":           ["ip"],
    "iunlock":        ["ip"],
    "iupdate":        ["ip"],
    "kfree":          ["pa"],
    "kill":           ["pid"],
    "log_write":      ["buf"],
    "mappages":       ["pagetable", "va", "size", "pa", "perm"],
    "namei":          ["path"],
    "panic":          ["msg"],
    "pipeclose":      ["pi", "writable"],
    "piperead":       ["pi", "addr", "n"],
    "pipewrite":      ["pi", "addr", "n"],
    "readi":          ["ip", "user_dst", "dst", "off", "n"],
    "sleep":          ["chan", "lock"],
    "swtch":          ["old_ctx", "new_ctx"],
    "uvmalloc":       ["pagetable", "oldsz", "newsz"],
    "uvmcopy":        ["old", "new", "sz"],
    "uvmdealloc":     ["pagetable", "oldsz", "newsz"],
    "uvmfree":        ["pagetable", "sz"],
    "uvmunmap":       ["pagetable", "va", "npages", "do_free"],
    "virtio_disk_rw": ["buf", "write"],
    "wait":           ["addr"],
    "wakeup":         ["chan"],
    "writei":         ["ip", "user_src", "src", "off", "n"],
}


def _func_events_from_manifest() -> dict[str, tuple[str, str, list[str]]]:
    from ..model.manifest import load_dir
    out: dict[str, tuple[str, str, list[str]]] = {}
    try:
        m = load_dir()[HARDCODED_KERNEL]
    except Exception:                                 # noqa: BLE001
        return out
    def argnames(sym: str) -> list[str]:
        alias = FUNC_EVENT_ALIASES.get(sym)
        return list(LEGACY_ARGNAMES.get(sym)
                    or (LEGACY_ARGNAMES.get(alias, []) if alias else []))

    for sym, spec in m.events.items():
        one = spec.alts[-1] if spec.alts else spec
        out[sym] = (one.kind, one.resource or "", argnames(sym))
    for sym, name in FUNC_EVENT_ALIASES.items():
        if sym in out:
            kind, res, args = out[sym]
            out[name] = (kind, res, list(args))
    return out

FUNC_EVENT_ALIASES: dict[str, str] = {
    "kfork": "fork", "kexit": "exit", "kwait": "wait",
    "kkill": "kill", "kspawn": "spawn", "kexec": "exec",
    "prepare_return": "usertrapret",
}

HARDCODED_KERNEL = "xv6"

_NOT_A_METRIC = frozenset({
    "by_kind",
    "unobservable_reason",
    "absent_declared",
    "armed_silent",
    "sampling",
})


FUNC_EVENTS: dict[str, tuple[str, str, list[str]]] = _func_events_from_manifest()

SWITCH_EVENT = "sched.switch"

OUTGOING_CTX_ARG = "old_ctx"
INCOMING_CTX_ARG = "new_ctx"

SCHEDULER = "调度器"

PHYS_ALLOC_EVENT = "phys.alloc"


def _current_event_spec(name: str, entry: dict, events: dict | None):
    """Find the current manifest entry for an archived watchpoint."""
    if not events:
        return None
    return events.get(entry.get("symbol") or "") or events.get(name)


def event_classifier(name: str, entry: dict,
                     events: dict | None = None) -> tuple[dict | None, list]:
    """Return a persisted classifier, or the current manifest rule for old runs.

    Old Starry recordings predate the classifier field but still contain all
    eight argument registers.  The current manifest may therefore add the
    interpretation without inventing any new measurement.  Its explicit args
    list is authoritative here because it includes ABI-hidden slots that DWARF
    source parameters omit.
    """
    classifier = entry.get("classify")
    if classifier:
        return classifier, list(entry.get("params") or [])
    spec = _current_event_spec(name, entry, events)
    classifier = getattr(spec, "classify", None)
    if classifier:
        return classifier, list(getattr(spec, "args", None) or [])
    return None, []


def classify_event_kind(default_kind: str, name: str, entry: dict,
                        values, events: dict | None = None) -> tuple[str, str | None]:
    """Apply a manifest bit-test classifier to captured a0..a7 values.

    The default kind is used when the tested bit is clear.  If the rule cannot
    be evaluated, fall back to a plain function event and explicitly mark the
    semantic kind unknown; silently choosing the default would turn an
    unclassified thread creation into a fake process fork.
    """
    classifier, params = event_classifier(name, entry, events)
    if not classifier:
        return default_kind, None
    try:
        arg = classifier["arg"]
        idx = params.index(arg)
        mask = int(classifier["mask"])
        set_kind = str(classifier["set"])
        if idx >= len(values):
            raise IndexError(idx)
        value = int(values[idx])
    except (KeyError, ValueError, TypeError, IndexError):
        return f"func.{name}", "event_kind"
    return (set_kind if value & mask else default_kind), None


def possible_event_kinds(kind: str, name: str, entry: dict,
                         events: dict | None = None) -> set[str]:
    """All semantic kinds a watchpoint classifier can produce."""
    classifier, _ = event_classifier(name, entry, events)
    if not classifier:
        return {kind}
    set_kind = classifier.get("set")
    return {kind, str(set_kind)} if set_kind else {kind}


def event_shape(name: str, entry: dict, *,
                kernel_kind: str | None,
                events: dict | None = None) -> tuple[str, str, list]:
    resource = entry.get("resource", "kernel")
    current_spec = _current_event_spec(name, entry, events)
    if entry.get("kind"):
        kind, argnames = entry["kind"], []
    elif getattr(current_spec, "classify", None):
        # A classifier is safe to backfill into an old recording: the trace
        # already captured the raw registers, and failure to locate the tested
        # register falls back to func.* rather than guessing the default kind.
        kind = current_spec.kind
        resource = current_spec.resource or resource
        argnames = list(current_spec.args)
    elif kernel_kind == HARDCODED_KERNEL:
        kind, table_res, argnames = FUNC_EVENTS.get(
            name, (f"func.{name}", "", []))
        resource = table_res or resource
    else:
        kind, argnames = f"func.{name}", []
    if not argnames:
        argnames = list(entry.get("params") or [])
    if not argnames and events:
        spec = current_spec
        argnames = list(getattr(spec, "args", None) or [])
    return kind, resource, argnames


def event_operation(name: str, entry: dict, events: dict | None = None) -> str:
    operation = str(entry.get("operation") or "")
    if operation or not events:
        return operation
    spec = events.get(entry.get("symbol") or "") or events.get(name)
    return str(getattr(spec, "operation", "") or "")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def resolve_kernel_elf(manifest: dict) -> tuple[Path, str | None]:
    from . import kernels as _kernels

    live = Path(manifest["kernel_elf"])
    ident = manifest.get("kernel_elf_identity") or {}
    want = ident.get("sha256")
    if not want:
        return live, None

    if live.is_file() and _kernels._sha256(live) == want:
        return live, None

    found = _kernels.archived_elf_for_identity(ident,
                                               manifest.get("kernel_kind"))
    if found is None:
        return live, None

    why = ("路径上没有这个文件了" if not live.is_file()
           else "路径上那份的哈希跟录制时记的对不上（被后来的构建覆盖了）")
    return found, (
        f"解这趟用的是归档里的 `{found.name}`，不是 manifest 里那条路径"
        f"（`{live}`）：{why}。归档那份的 sha256 跟 `kernel_elf_identity` "
        f"逐位相同，所以符号地址是录制当时那一套。")


class Analysis:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.manifest = json.loads(
            (self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.watchlist = json.loads(
            (self.run_dir / "watchlist.json").read_text(encoding="utf-8"))
        self.kernel_kind = self.manifest.get("kernel_kind")
        self.kevents: dict | None = None
        self._event_names_present: set[str] | None = None
        from . import layout as layout_mod
        self.layout: KernelLayout = layout_mod.load(self.run_dir / "kernel_layout.json")
        self.kernel_elf_path, _elf_note = resolve_kernel_elf(self.manifest)
        self.elf = Elf64(str(self.kernel_elf_path))
        self.kernel_dir = Path(self.manifest["kernel_dir"])
        self.syscalls: dict[int, str] = {}
        if self.kernel_kind:
            try:
                from ..model.manifest import load_dir
                _man = load_dir().get(self.kernel_kind)
                if _man is not None:
                    self.syscalls = load_syscall_names(
                        self.kernel_dir, _man.syscalls)
            except Exception as e:                        # noqa: BLE001
                self.notes.append(f"读不到 {self.kernel_kind} 的系统调用号表"
                                  f"（{e}），系统调用只显示号码。")

        self.trace = trace_mod.load(self.run_dir / "trace.nfb",
                                    indexed_pages=True, compact_watch_hits=True)
        self.console = (self.run_dir / "console.log").read_text(
            encoding="utf-8", errors="replace") if (self.run_dir / "console.log").exists() else ""

        self.watch_by_id = {e["index"]: e for e in self.watchlist["entries"]}
        self.watched_names: set[str] = {
            e["name"] for e in self.watchlist["entries"] if e.get("name")}
        self.watched_symbols: set[str] = {
            e["symbol"] for e in self.watchlist["entries"] if e.get("symbol")}

        self.nft_index: dict[tuple[int, int], tuple[list[int], list[int]]] = {}
        self.nft_records: dict[tuple[int, int], list] = {}
        _tmp: dict[tuple[int, int], list] = {}
        for r in self.trace.nftrace:
            _tmp.setdefault((r.cpu, r.type), []).append(r)
        for key, recs in _tmp.items():
            recs.sort(key=lambda x: x.insn)
            self.nft_records[key] = recs
            self.nft_index[key] = ([x.insn for x in recs], [x.a[0] for x in recs])

        # Exact allocator counters carried by the semantic channel.  Types 1
        # and 5 put (free, allocated) in a2/a3; type 6 is a counter-only
        # record and puts them in a0/a1.  All-zero type-1/5 tails are legacy
        # records, not a claim that the allocator has no pages.
        self.nft_allocator_states: list[tuple[int, int, int]] = []
        for r in self.trace.nftrace:
            if r.type in (self.NFT_KALLOC, self.NFT_KFREE):
                free, allocated = int(r.a[2]), int(r.a[3])
                if free == 0 and allocated == 0:
                    continue
            elif r.type == self.NFT_ALLOCATOR_STATE:
                free, allocated = int(r.a[0]), int(r.a[1])
            else:
                continue
            self.nft_allocator_states.append((r.insn, free, allocated))
        self.nft_allocator_states.sort(key=lambda x: x[0])
        self.nft_allocator_state_insns = [x[0] for x in self.nft_allocator_states]

        base = int(self.trace.meta.get("nf.ram_base", "0x80000000"), 16)
        size = int(self.trace.meta.get("nf.ram_size", "0x8000000"), 16)
        self.ram = guest_mod.RamImage(base, size)

        self.states: list[guest_mod.SystemState] = []
        self.events: list[Event] = []
        self.notes: list[str] = []

        if _elf_note:
            self.notes.append(_elf_note)

        from . import elfid
        for line in elfid.compare(self.manifest.get("kernel_elf_identity"),
                                  self.kernel_elf_path,
                                  recorded_utc=self.manifest.get("started_utc")):
            self.notes.append(line)

        if self.manifest.get("trace_complete") is False:
            self.notes.append(
                "**这份轨迹没有正常收尾**，末尾很可能缺一段：录制时插件没走完"
                "收尾流程，轨迹里没有结束记录。也就是说下面看到的最后一帧不一定"
                "是这次运行真正的最后一帧，"
                f"末尾的空白未必是内核真的什么都没做。原因："
                f"{self.manifest.get('trace_incomplete_reason') or '录制时没记下来'}")

        self.decoder = guest_mod.GuestDecoder(self.elf, self.layout, self.ram,
                                              entities=self._entities())
        smp = int(self.trace.meta.get("qemu.smp", "1"))
        self.decoder.ncpu = min(self.decoder.ncpu, max(1, smp))
        self.ncpu = self.decoder.ncpu

        if not self.decoder.procs_ok:
            self.notes.append(
                "进程表解不出来，上下文切换事件无法归属到具体进程"
                + (f"：{self.decoder.procs_reason}"
                   if self.decoder.procs_reason else "，而且没有给出原因。"))
        self.tasks_exhaustive = self._tasks_exhaustive()


    def _entities(self):
        try:
            from ..model.dwarfsrc import DwarfSource
            from ..model.manifest import load_dir
            from ..model.probe import detect, probe
            from ..model.snapshot import SnapshotBuilder
            from ..model.symbols import SymbolIndex
        except ImportError as e:                      # noqa: BLE001
            self.notes.append(f"实体解码器加载不了（{e}），退回分内核解码。")
            return None

        from ..model.manifest import builtin_dir
        mdir = builtin_dir()
        if not mdir.is_dir():
            self.notes.append(f"没有 manifest 目录 {mdir}，退回分内核解码。")
            return None
        try:
            ms = load_dir(str(mdir))
            dw = DwarfSource(str(self.kernel_elf_path))
            kind, why = detect(ms, dw)
            if kind is None:
                self.notes.append(
                    "manifest 认不出这个内核，退回分内核解码：" + "；".join(why))
                return None
            m = ms[kind]
            from .watchlist import _pick_branch
            self.kevents = {k: _pick_branch(dw, v) for k, v in m.events.items()}
            from ..model.watchsel import candidates
            syms = [s for s in self.elf.symbols
                    if s.value and s.name and (s.is_func or s.sym_type == 0)]
            present: set[str] = set()
            for c in candidates(dw, syms):
                if c.path:
                    present.add(c.path)
                present.update(n for n in c.names if n)
            self._event_names_present = present
            builder = SnapshotBuilder(dw, probe(m, dw), m,
                                      syms=SymbolIndex(self.elf, dw))
            self._manifest_dw = dw
            return builder
        except Exception as e:                        # noqa: BLE001
            self.notes.append(
                f"按 manifest 建实体解码器失败（{type(e).__name__}: {e}），"
                f"退回分内核解码。")
            return None


    def _satp_roots_per_snapshot(self) -> list[list[int]]:
        satp_at: list[tuple[int, int]] = [(d.insn, d.satp) for d in self.trace.discons]
        satp_at += [(s.insn, s.satp) for s in self.trace.samples]
        satp_at.sort(key=lambda x: x[0])

        out: list[list[int]] = []
        j = 0
        for snap in self.trace.snapshots:
            roots: list[int] = []
            while j < len(satp_at) and satp_at[j][0] <= snap.insn:
                r = guest_mod.GuestDecoder.satp_root(satp_at[j][1])
                if r is not None:
                    roots.append(r)
                j += 1
            out.append(list(dict.fromkeys(roots)))
        return out

    def rebuild_states(self) -> None:
        if not self.trace.snapshots:
            self.notes.append(
                "这次运行没有任何物理内存快照，无法重建系统状态；"
                "时间轴与事件仍然可用（它们来自虚拟机外部的指令级观测）。")
            return
        roots_by_snap: list[list[int]] = self._satp_roots_per_snapshot()
        if not self.decoder.procs_ok:
            n = len({r for rs in roots_by_snap for r in rs})
            self.notes.append(
                f"进程表不可用，页表根改用外部观测到的 satp（共 {n} 个不同的根）。"
                f"页表结构与物理页归属仍是真实观测，但无法归属到具体进程。")

        for i, snap in enumerate(self.trace.snapshots):
            self.ram.apply(snap.pages)
            st = self.decoder.decode(
                snap.insn, snap.snap_seq,
                observed_roots=roots_by_snap[i] if roots_by_snap else None)
            self._apply_allocator_state(st)
            if snap.flags & trace_mod.F_INCOMPLETE:
                st.complete = False
                st.incomplete_reason = "该次快照有物理页读取失败"
            self.states.append(st)

        if self.states:
            self._note_kernel_image_fit()

    def _apply_allocator_state(self, st: guest_mod.SystemState) -> None:
        """Fill absolute free/used counts from the latest guest measurement."""
        if not self.nft_allocator_states:
            return
        i = bisect.bisect_right(self.nft_allocator_state_insns, st.insn) - 1
        if i < 0:
            return
        _, free, _allocator_used = self.nft_allocator_states[i]
        # The UI's used count covers all non-free RAM, including the kernel
        # image and pages outside the allocator's managed arena.  The producer's
        # allocated count remains useful event evidence, but total-free is the
        # compatible system-wide value here.
        st.phys_free = free
        st.phys_used = max(0, st.phys_total - free)
        st.phys_free_available = True

        # Remove only the old missing-free-list explanation.  Ownership or
        # page-table caveats remain relevant and must not be hidden merely
        # because the scalar counters are now exact.
        missing_freelist = getattr(self.decoder.kmem, "reason", "")
        if missing_freelist and st.phys_reason:
            st.phys_reason = "；".join(
                part for part in st.phys_reason.split("；")
                if part != missing_freelist)

    def _note_kernel_image_fit(self) -> None:
        fit = self.ram.find_kernel_image(self.elf)

        if fit.direct:
            return

        if not fit.found:
            self.notes.append(
                f"这份内核 ELF 不是录制这趟轨迹时用的那个构建：ELF 入口处的 64 "
                f"字节在整个物理内存里一处都找不到（{fit.reason}）。"
                f"高半区内核会在别的物理地址上找到，所以不是映射方式的问题。"
                f"请核对 kernel_elf 指向的文件有没有被后来的构建覆盖。"
                f"基于符号地址的状态重建结果都不可信，已在界面上标注。")
            return

        if fit.ambiguous:
            self.notes.append(
                f"内核镜像在物理内存里匹配到不止一处，无法断定它装在哪儿"
                f"（{fit.reason}），因此说不出符号地址该怎么换算。"
                f"基于符号地址的状态重建结果都不可信，已在界面上标注。")
            return

        self.notes.append(
            f"这个内核不是直接映射的：镜像装在物理地址 {fit.paddr:#x}，而符号的"
            f"虚地址从 {self.elf.e_entry:#x} 起，虚实之差 {fit.offset:#x}。"
            f"入口处的字节在那里逐字节对上了，所以这份 ELF 就是录这趟用的构建。"
            f"manifest 那条路读内核静态变量时会按这个差换算，读到的是对的地方；"
            f"页表遍历和物理页归属不走这一层 —— 它们手里的 PPN 和外部读到的 "
            f"satp 本来就是物理地址，换算只会把对的地址弄错。")


    def _pid_by_slot_at(self, state_idx: int, slot: int) -> tuple[int | None, str | None]:
        n = len(self.states)
        if n == 0:
            return None, None
        start = max(0, min(state_idx, n - 1))
        for i in list(range(start, n)) + list(range(start - 1, -1, -1)):
            for p in self.states[i].procs:
                if p.slot == slot:
                    return p.pid, p.name
        return None, None

    def _tasks_exhaustive(self) -> bool | None:
        ents = self.decoder.entities
        if ents is None:
            return True if self.kernel_kind == HARDCODED_KERNEL else None
        spec = ents.entity_for("process", fallback="task")
        if spec is None:
            return None
        res = next((e for e in ents.res.entities if e.name == spec.name), None)
        if res is None or not res.sources:
            return None
        from ..model.manifest import _COMPLETENESS
        from ..model.snapshot import _completeness
        got = _completeness(res.sources)["completeness"]
        return _COMPLETENESS.get(got)

    def _task_by_ctx(self, state_idx: int, ctx: int):
        n = len(self.states)
        if not ctx or n == 0:
            return None
        start = max(0, min(state_idx, n - 1))
        for i in list(range(start, n)) + list(range(start - 1, -1, -1)):
            for p in self.states[i].procs:
                if p.sched_ctx == ctx or ctx in (p.sched_ctxs or ()):
                    return p
        return None

    def _sched_owner(self, state_idx: int, ctx: int) -> dict | None:
        n = len(self.states)
        if not ctx or n == 0:
            return None
        start = max(0, min(state_idx, n - 1))
        for i in list(range(start, n)) + list(range(start - 1, -1, -1)):
            got = getattr(self.states[i], "sched_owners", None)
            if got:
                own = got.get(ctx)
                if own is not None:
                    return own
        return None

    def _attribute_switch(self, detail: dict, unknown: list, si: int,
                          cpu: int, cur_slot: dict) -> None:
        for end, arg in (("from", OUTGOING_CTX_ARG), ("to", INCOMING_CTX_ARG)):
            ctx = detail.get(arg)
            if ctx is None:
                unknown.append(f"{end}_pid")
                detail[f"{end}_unknown"] = (
                    f"这个内核的 manifest 没把切换函数的参数命名为 {arg!r}，"
                    f"不知道哪个参数是上下文地址")
                continue

            p = self._task_by_ctx(si, ctx)
            own = self._sched_owner(si, ctx)
            if p is not None:
                detail[f"{end}_pid"] = p.pid
                detail[f"{end}_proc"] = (
                    p.name if p.name is not None else (own or {}).get("name"))
                detail[f"{end}_slot"] = p.slot
            elif own is not None:
                detail[f"{end}_pid"] = None
                detail[f"{end}_proc"] = own.get("name") or (
                    f"{own.get('kind')}#{own.get('id')}")
                detail[f"{end}_slot"] = None
                detail[f"{end}_task_kind"] = own.get("kind")
                if own.get("id") is not None:
                    detail[f"{end}_task_id"] = own["id"]
            elif self.tasks_exhaustive:
                detail[f"{end}_pid"] = None
                detail[f"{end}_proc"] = SCHEDULER
                detail[f"{end}_slot"] = None
            else:
                unknown.append(f"{end}_pid")
                why = ("这个内核的任务枚举本身就不全"
                       if self.tasks_exhaustive is False else
                       "这个内核没有声明它的任务枚举全不全，我们无从判断")
                detail[f"{end}_unknown"] = (
                    f"上下文 {ctx:#x} 不属于任何一个枚举得到的任务。{why}，"
                    f"所以这既可能是调度器，也可能是一个我们够不着的任务 —— "
                    f"两者分不开，不猜。")

        cur_slot[cpu] = detail.get("to_slot")

    def build_events(self) -> None:
        tr = self.trace
        snap_insns = [s.insn for s in self.states]

        def state_index_for(insn: int) -> int:
            lo, hi, best = 0, len(snap_insns) - 1, -1
            while lo <= hi:
                mid = (lo + hi) // 2
                if snap_insns[mid] <= insn:
                    best, lo = mid, mid + 1
                else:
                    hi = mid - 1
            return best

        def tick_at(insn: int) -> int | None:
            i = state_index_for(insn)
            return self.states[i].ticks if i >= 0 else None

        cur_slot: dict[int, int | None] = {c: None for c in range(self.ncpu)}

        merged = heapq.merge(
            ((d.insn, 0, "discon", d) for d in tr.discons),
            ((w.insn, 1, "watch", w) for w in tr.watch_hits),
            ((r.insn, 2, "nftrace", r) for r in tr.nftrace),
            key=lambda t: (t[0], t[1]))

        for insn, _, kind, obj in merged:
            si = state_index_for(insn)
            if kind == "watch":
                ev = self._watch_event(obj, si, cur_slot)
            elif kind == "nftrace":
                ev = self._nftrace_event(obj, si, cur_slot)
            else:
                ev = self._discon_event(obj, si, cur_slot)
            if ev is not None:
                ev.tick = tick_at(insn)
                self.events.append(ev)

        self._note_recording_tail()

    def _note_recording_tail(self) -> None:
        if not self.states or not self.events:
            return
        if any(s.procs for s in self.states):
            return
        last = max(s.insn for s in self.states)
        after = [e for e in self.events if (e.insn or 0) > last]
        if not after:
            return

        tail, whole = Counter(e.kind for e in after), Counter(
            e.kind for e in self.events)
        only = {k: n for k, n in tail.items()
                if whole[k] == n and k.split(".")[0] in _PROC_EVENT_KINDS}
        if not only:
            return

        which = "、".join(f"{k}×{n}" for k, n in
                          sorted(only.items(), key=lambda kv: -kv[1]))
        self.notes.append(
            f"这趟一个进程都没解出来，但这不等于内核里没有：最后一帧内存停在第 "
            f"{last:,} 条指令，而轨迹一直记到第 "
            f"{max(e.insn or 0 for e in after):,} 条。讲进程的事件（{which}）"
            f"整趟只出现在这段里 —— 也就是说，任务是在最后一帧之后才出现的，"
            f"这份轨迹里没有能读到它们的内存。要看清这段，得让录制在这儿也抓"
            f"一帧：按指令数periodic抓的话，短促的阶段本来就容易整个漏掉。")

    NFT_KALLOC = 1
    NFT_PROC_FORK = 2
    NFT_THREAD_CREATE = 3
    NFT_SCHED_SWITCH = 4
    NFT_KFREE = 5
    NFT_ALLOCATOR_STATE = 6
    NFT_NO_TASK = (1 << 64) - 1

    NFT_MAX_LAG = 5_000_000

    def _nft_kalloc_after(self, cpu: int, insn: int) -> int | None:
        idx = self.nft_index.get((cpu, self.NFT_KALLOC))
        if not idx:
            return None
        insns, pas = idx
        i = bisect.bisect_right(insns, insn)
        if i >= len(insns):
            return None
        if insns[i] - insn > self.NFT_MAX_LAG:
            return None
        return pas[i]

    def _nft_clone_after(self, cpu: int, insn: int, kind: str) -> bool:
        """Whether an authoritative clone-result record follows this entry."""
        nft_type = {"proc.fork": self.NFT_PROC_FORK,
                    "thread.create": self.NFT_THREAD_CREATE}.get(kind)
        if nft_type is None:
            return False
        recs = self.nft_records.get((cpu, nft_type), [])
        if not recs:
            return False
        points = [r.insn for r in recs]
        i = bisect.bisect_right(points, insn)
        return i < len(points) and points[i] - insn <= self.NFT_MAX_LAG

    def _nftrace_event(self, r: trace_mod.NfTraceRec, si: int,
                       cur_slot: dict) -> Event | None:
        """Turn authoritative guest semantic records into common events."""
        if r.type == self.NFT_KALLOC:
            pid, proc = self._attribute(r.cpu, si, cur_slot)
            detail = {"allocated_pa": r.a[0], "source": "nftrace"}
            unknown = []
            # Producers added the requested page count in a1 together with the
            # standalone-event contract.  A zero remains readable for legacy
            # records, but it is not silently reinterpreted as one page.
            if r.a[1]:
                detail["num_pages"] = r.a[1]
            else:
                unknown.append("num_pages")
            if r.a[0] == 0:
                detail["note"] = "物理页分配失败"
            if r.a[2] or r.a[3]:
                detail["free_pages"] = r.a[2]
                detail["allocator_used_pages"] = r.a[3]
            return Event(
                insn=r.insn, cpu=r.cpu, kind=PHYS_ALLOC_EVENT,
                resource="physical_memory", pid=pid, proc=proc, pc=None,
                func=watchlist_mod.NFTRACE_COMMIT,
                detail=detail, unknown=unknown)

        if r.type == self.NFT_KFREE:
            pid, proc = self._attribute(r.cpu, si, cur_slot)
            return Event(
                insn=r.insn, cpu=r.cpu, kind="phys.free",
                resource="physical_memory", pid=pid, proc=proc, pc=None,
                func=watchlist_mod.NFTRACE_COMMIT,
                detail={"freed_pa": r.a[0], "num_pages": r.a[1],
                        "free_pages": r.a[2],
                        "allocator_used_pages": r.a[3],
                        "source": "nftrace"}, unknown=[])

        if r.type == self.NFT_ALLOCATOR_STATE:
            # This is a high-frequency state sample, not an operating-system
            # action.  It feeds snapshot free/used counters through
            # `_apply_allocator_state`; duplicating every sample in the event
            # timeline would turn allocator bookkeeping into millions of fake
            # user-facing events.
            return None

        if r.type == self.NFT_SCHED_SWITCH:
            pid, proc = self._attribute(r.cpu, si, cur_slot)
            detail = {"source": "nftrace"}
            for end, task_id, visible_id in (
                    ("from", r.a[0], r.a[2]), ("to", r.a[1], r.a[3])):
                detail[f"{end}_task_id"] = task_id
                if visible_id == self.NFT_NO_TASK:
                    detail[f"{end}_pid"] = None
                    detail[f"{end}_proc"] = f"kernel-task#{task_id}"
                else:
                    detail[f"{end}_pid"] = visible_id
                    detail[f"{end}_proc"] = f"task#{visible_id}"
            return Event(
                insn=r.insn, cpu=r.cpu, kind=SWITCH_EVENT,
                resource="scheduler", pid=pid, proc=proc, pc=None,
                func=watchlist_mod.NFTRACE_COMMIT,
                detail=detail, unknown=[])

        shape = {
            self.NFT_PROC_FORK: ("proc.fork", "process"),
            self.NFT_THREAD_CREATE: ("thread.create", "thread"),
        }.get(r.type)
        # Unknown future record types remain readable at the wire layer but
        # need a registered semantic mapping before they become events.
        if shape is None:
            return None
        kind, resource = shape
        pid, proc = self._attribute(r.cpu, si, cur_slot)
        return Event(
            insn=r.insn, cpu=r.cpu, kind=kind, resource=resource,
            pid=pid, proc=proc, pc=None,
            func=watchlist_mod.NFTRACE_COMMIT,
            detail={"parent_tid": r.a[0], "child_tid": r.a[1],
                    "source": "nftrace"}, unknown=[])

    def _attribute(self, cpu: int, si: int, cur_slot: dict) -> tuple[int | None, str | None]:
        slot = cur_slot.get(cpu)
        if slot is None:
            return None, None
        return self._pid_by_slot_at(si, slot)

    def _watch_event(self, w: trace_mod.WatchHit, si: int,
                     cur_slot: dict) -> Event | None:
        entry = self.watch_by_id.get(w.watch_id)
        if entry is None:
            return None
        name = entry["name"]

        if name == watchlist_mod.NFTRACE_COMMIT:
            return None
        kind, resource, argnames = event_shape(
            name, entry, kernel_kind=self.kernel_kind, events=self.kevents)

        kind, classification_unknown = classify_event_kind(
            kind, name, entry, w.a, self.kevents)

        # A patched Starry kernel reports the successful result from the
        # common clone/clone3 path.  Prefer that post-success record and omit
        # the earlier classified call event; otherwise one fork would appear
        # twice.  Legacy traces have no such record and keep the entry-based
        # classifier above.
        classifier, _ = event_classifier(name, entry, self.kevents)
        if classifier and self._nft_clone_after(w.cpu, w.insn, kind):
            return None
        if kind == SWITCH_EVENT and self.nft_records.get(
                (w.cpu, self.NFT_SCHED_SWITCH)):
            return None
        if kind == "phys.free" and self.nft_records.get(
                (w.cpu, self.NFT_KFREE)):
            return None

        detail: dict = {}
        for i, an in enumerate(argnames):
            if an is not None and i < len(w.a):
                detail[an] = w.a[i]
        operation = event_operation(name, entry, self.kevents)
        if operation:
            detail["operation"] = operation
        unknown: list = []
        if classification_unknown:
            unknown.append(classification_unknown)
        else:
            classifier, classifier_args = event_classifier(
                name, entry, self.kevents)
            if classifier:
                idx = classifier_args.index(classifier["arg"])
                detail["kind_source"] = (
                    f"{classifier['arg']} & 0x{int(classifier['mask']):x}")
                detail["kind_test_value"] = w.a[idx]

        xv6 = self.kernel_kind == HARDCODED_KERNEL

        if kind == SWITCH_EVENT:
            self._attribute_switch(detail, unknown, si, w.cpu, cur_slot)

        if kind == PHYS_ALLOC_EVENT:
            # The post-result KALLOC record is the complete event: it carries
            # the real physical address and requested page count.  Suppress
            # this earlier function-entry hit so counts are not doubled.
            if self._nft_kalloc_after(w.cpu, w.insn) is not None:
                return None
            # Unpatched kernels still retain the entry event, but must state
            # that a return value cannot be observed at function entry.
            unknown.append("allocated_pa")

        if xv6 and name == "panic":
            msg = self.ram.cstr(w.a[0], 96) if w.a and w.a[0] else None
            if msg:
                detail["msg"] = msg

        pid, proc = self._attribute(w.cpu, si, cur_slot)
        func, _ = self.elf.resolve_pc(w.pc)
        return Event(insn=w.insn, cpu=w.cpu, kind=kind, resource=resource,
                     pid=pid, proc=proc, pc=w.pc, func=func or entry["symbol"],
                     detail=detail, unknown=unknown, function_entry=True,
                     entry_name=entry["symbol"], return_address=w.ra or None,
                     stack_pointer=w.sp if not w.flags & trace_mod.F_NO_REGS else None,
                     address_space=w.satp if not w.flags & trace_mod.F_NO_CSR else None)

    def _discon_event(self, d: trace_mod.Discon, si: int,
                      cur_slot: dict) -> Event | None:
        pid, proc = self._attribute(d.cpu, si, cur_slot)
        epc = d.epc
        func, _ = self.elf.resolve_pc(epc if epc is not None else d.from_pc)
        detail = {"from_pc": d.from_pc, "to_pc": d.to_pc, "priv": d.priv}
        unknown = []

        if d.flags & trace_mod.F_NO_CSR:
            unknown.append("scsr")
        else:
            detail.update(scause=d.scause, sepc=d.sepc, stval=d.stval)
        if d.mcause is not None and not (d.flags & trace_mod.F_NO_MCSR):
            detail.update(mcause=d.mcause, mepc=d.mepc, mtval=d.mtval)

        code = d.cause_code
        if code is None:
            unknown.append("cause")
            detail["cause_name"] = "未知（本次陷入的权威 cause 寄存器不可读）"
            return Event(d.insn, d.cpu, "trap.unknown", "trap", pid, proc,
                         epc, func, detail=detail, unknown=unknown)
        detail["cause_code"] = code

        if d.trapped_to_m:
            if d.is_interrupt_flag:
                detail["cause_name"] = MINTERRUPT_NAMES.get(code, f"M 态中断 {code}")
                return Event(d.insn, d.cpu, "firmware.interrupt", "firmware",
                             pid, proc, epc, func, detail=detail, unknown=unknown)

            detail["cause_name"] = EXCEPTION_NAMES.get(code, f"异常 {code}")
            if code == CAUSE_ECALL_S:
                eid, fid = d.a[7], d.a[6]
                detail["sbi_eid"] = eid
                detail["sbi_fid"] = fid
                detail["sbi_ext"] = sbi_ext_name(eid)
                detail["args"] = list(d.a[:6])
                return Event(d.insn, d.cpu, "sbi.call", "firmware", pid, proc,
                             epc, func, detail=detail, unknown=unknown)

            return Event(d.insn, d.cpu, "firmware.trap", "firmware", pid, proc,
                         epc, func, detail=detail, unknown=unknown)

        if d.is_interrupt_flag:
            kind = {5: "interrupt.timer", 9: "interrupt.external",
                    1: "interrupt.software"}.get(code, "interrupt.other")
            detail["cause_name"] = INTERRUPT_NAMES.get(code, f"中断 {code}")
            return Event(d.insn, d.cpu, kind, "interrupt", pid, proc,
                         epc, func, detail=detail, unknown=unknown)

        detail["cause_name"] = EXCEPTION_NAMES.get(code, f"异常 {code}")

        if code == CAUSE_ECALL_U:
            num = d.a[7]
            detail["syscall_num"] = num
            detail["syscall"] = self.syscalls.get(num, f"sys_{num}")
            detail["args"] = list(d.a[:6])
            return Event(d.insn, d.cpu, "syscall.enter", "syscall", pid, proc,
                         epc, func, detail=detail, unknown=unknown)

        if code in (CAUSE_PF_INSN, CAUSE_PF_LOAD, CAUSE_PF_STORE):
            detail["fault_va"] = d.tval
            detail["fault_kind"] = {12: "instruction", 13: "load",
                                    15: "store"}[code]
            return Event(d.insn, d.cpu, "trap.page_fault", "vm", pid, proc,
                         epc, func, detail=detail, unknown=unknown)

        return Event(d.insn, d.cpu, "trap.exception", "trap", pid, proc,
                     epc, func, detail=detail, unknown=unknown)


    _METRIC_KINDS: dict[str, str] = {
        "context_switches": "sched.switch",
        "kalloc": "phys.alloc",
        "kfree": "phys.free",
        "disk_io": "disk.io",
        "bcache_reads": "bcache.read",
        "log_commits": "log.commit",
        "forks": "proc.fork",
        "execs": "proc.exec",
        "vm_maps": "vm.map",
        "vm_unmaps": "vm.unmap",
        "page_table_maps": "pagetable.map",
    }

    _DERIVED_FROM: dict[str, tuple[str, ...]] = {
        "bcache_hits": ("bcache.read", "disk.io"),
        "bcache_hit_rate": ("bcache.read", "disk.io"),
    }

    def _watched_kinds(self) -> set[str]:
        out: set[str] = set()
        for e in self.watchlist["entries"]:
            name = e.get("name")
            if not name:
                continue
            kind, _, _ = event_shape(name, e, kernel_kind=self.kernel_kind,
                                     events=self.kevents)
            out.update(possible_event_kinds(
                kind, name, e, self.kevents))
        return out

    def _sampled_kinds(self) -> dict[str, list[int]]:
        rates: dict[str, set[int]] = {}
        for e in self.watchlist["entries"]:
            name = e.get("name")
            if not name:
                continue
            kind, _, _ = event_shape(name, e, kernel_kind=self.kernel_kind,
                                     events=self.kevents)
            for possible in possible_event_kinds(kind, name, e, self.kevents):
                rates.setdefault(possible, set()).add(int(e.get("rate") or 0))
        return {k: sorted(v) for k, v in rates.items() if any(r > 1 for r in v)}

    def _disk_reads(self, disk_io: int | None) -> int | None:
        if disk_io is None:
            return None
        if disk_io == 0:
            return 0
        reads = 0
        seen = 0
        for event in self.events:
            if event.kind != "disk.io":
                continue
            seen += 1
            operation = event.detail.get("operation")
            if operation == "read":
                reads += 1
            elif operation == "write":
                continue
            elif "write" in event.detail:
                if not event.detail["write"]:
                    reads += 1
            else:
                return None
        return reads if seen == disk_io else None

    def metrics(self) -> dict:
        counts: dict[str, int] = {}
        for e in self.events:
            counts[e.kind] = counts.get(e.kind, 0) + 1
        wkinds = self._watched_kinds()

        def watched(kind: str):
            if kind in counts:
                return counts[kind]
            return 0 if kind in wkinds else None

        breads = watched("bcache.read")
        disk_io = watched("disk.io")
        disk_reads = self._disk_reads(disk_io)
        if breads is None or disk_reads is None:
            cache_hits = None
            hit_rate = None
        else:
            cache_hits = max(0, breads - disk_reads)
            hit_rate = (cache_hits / breads) if breads else None

        m = {
            "total_insns": self.trace.total_insns,
            "syscalls": counts.get("syscall.enter", 0),
            "page_faults": counts.get("trap.page_fault", 0),
            "exceptions": counts.get("trap.exception", 0),
            "timer_interrupts": counts.get("interrupt.timer", 0),
            "external_interrupts": counts.get("interrupt.external", 0),
            "bcache_reads": breads,
            "bcache_hits": cache_hits,
            "bcache_hit_rate": hit_rate,
            "by_kind": counts,
        }
        for metric, kind in self._METRIC_KINDS.items():
            m[metric] = watched(kind)

        _sampled = self._sampled_kinds()
        # A KALLOC semantic record is emitted for every successful or failed
        # allocation after the allocator has produced its result.  Once that
        # authoritative channel is present, a throttled diagnostic entry rule
        # cannot make the resulting phys.alloc metric sampled.
        if any(r.type == self.NFT_KALLOC for r in self.trace.nftrace):
            _sampled.pop(PHYS_ALLOC_EVENT, None)
        if any(r.type == self.NFT_KFREE for r in self.trace.nftrace):
            _sampled.pop("phys.free", None)
        end = getattr(self.trace, "end", None)
        m["sampling"] = {
            "kinds": {k: v for k, v in _sampled.items() if k in counts},
            "metrics": {
                name: _sampled[kind]
                for name, kind in self._METRIC_KINDS.items() if kind in _sampled
            },
            "drops": None if end is None else end.watch_drops,
        }

        for metric, deps in self._DERIVED_FROM.items():
            if any(d in _sampled for d in deps):
                m[metric] = None

        m["unobservable_reason"] = self._unobservable_reason(m)
        m["absent_declared"] = {
            k: {"why": s.why, "evidence": s.evidence}
            for k, s in sorted(self._absent_kinds().items())
        }
        m["armed_silent"] = sorted(wkinds - set(counts))
        return m

    def _absent_kinds(self) -> dict:
        cached = getattr(self, "_absent_cache", None)
        if cached is not None:
            return cached
        out: dict = {}
        derive_from_symbols = False
        if self.kernel_kind:
            try:
                from ..model.manifest import load_dir
                man = load_dir().get(self.kernel_kind)
                if man is not None:
                    from ..model.resolve import eval_when
                    dw = getattr(self, "_manifest_dw", None)
                    out = {kind: spec for kind, spec in man.absent.items()
                           if not spec.when or (dw is not None and
                                                eval_when(dw, spec.when)[0])}
                    derive_from_symbols = bool(
                        man.derive_feature_absence_from_symbols)
            except Exception as e:                        # noqa: BLE001
                self.notes.append(
                    f"读 {self.kernel_kind} 的 [absent] 失败"
                    f"（{type(e).__name__}: {e}），"
                    f"已声明的缺席这趟会按「manifest 没映射」报。")
        # A chapter-evolving family may opt into deriving build-local feature
        # absence from the resolved ELF.  Keep this generic and manifest-led:
        # no host-side kernel name or chapter number belongs here.  Never make
        # the claim when DWARF/symbol resolution failed, and never flatten a
        # present-but-unwatched function into N/A.
        if derive_from_symbols and self.kevents is not None \
                and self._event_names_present is not None:
            from ..model.manifest import AbsentSpec
            by_kind: dict[str, list[str]] = {}
            for fn, spec in self.kevents.items():
                by_kind.setdefault(getattr(spec, "kind", ""), []).append(fn)
            for kind, fns in by_kind.items():
                if kind and kind not in out and not any(
                        fn in self._event_names_present for fn in fns):
                    out[kind] = AbsentSpec(
                        kind=kind, why="feature",
                        evidence=("Build-specific ELF/DWARF symbol audit: none "
                                  "of the manifest's implementation symbols for "
                                  f"{kind} are present in this build."))
        self._absent_cache = out
        return out

    def _unobservable_reason(self, m: dict) -> str | None:
        blind = sorted(k for me, k in self._METRIC_KINDS.items()
                       if m.get(me) is None)
        sampled = (m.get("sampling") or {}).get("kinds") or {}
        sampled_deps = sorted({d for me, deps in self._DERIVED_FROM.items()
                               if m.get(me) is None
                               for d in deps if d in sampled})
        if not blind and not sampled_deps:
            return None

        if self.kevents is None:
            return ("这些事件类别测不到，但说不出是为什么："
                    + "、".join(blind)
                    + "。没能按 manifest 认出这个内核，无从知道它有没有对应的"
                      "函数。相关计数标为未知，而不是 0。")

        inv: dict[str, list[str]] = {}
        for name, spec in self.kevents.items():
            inv.setdefault(getattr(spec, "kind", spec), []).append(name)

        unwatched: set[str] = set()
        unavailable: set[str] = set()
        undeclared: set[str] = set()
        for kind in blind:
            mapped = list(inv.get(kind, ()))
            if not mapped:
                undeclared.add(kind)
                continue
            present = self._event_names_present
            if present is None:
                unavailable.add(kind)
                continue
            names = [n for n in mapped
                     if n in present and n not in self.watched_symbols
                     and n not in self.watched_names]
            if names:
                unwatched.update(names)
            elif not any(n in present for n in mapped):
                unavailable.add(kind)

        absent = self._absent_kinds()
        declared = sorted(k for k in undeclared if k in absent)
        unknown = sorted(k for k in undeclared if k not in absent)

        parts = []
        if unwatched:
            parts.append("这些函数在本次 ELF 里有、这趟却没挂上观测点："
                         + "、".join(sorted(unwatched)))
        if unavailable:
            parts.append(
                "这些类别在系列 manifest 中有函数映射，但对应函数不在本次 "
                "ELF 里（常见于较早章节尚未引入该结构或功能）："
                + "、".join(sorted(unavailable)))
        for why, phrase in (
            ("feature",
             "这些事本内核没有，manifest 里声明过并附了依据"),
            ("granularity",
             "这些事本内核会做，但没有粒度对得上的函数可挂，manifest 里"
             "声明过并附了依据"),
        ):
            hit = [k for k in declared if getattr(absent[k], "why", "") == why]
            if hit:
                parts.append(f"{phrase}：" + "、".join(hit))
        if unknown:
            parts.append("这些事件类别，本内核的 manifest 里没有任何函数映射"
                         "过来（也可能是它给同一件事起了别的名字，从这里分不"
                         "出来）：" + "、".join(unknown))
        if sampled_deps:
            parts.append("这些类别这趟是抽样记的，拿它们做被减数的外部推导量"
                         "因此算不出来（换一趟不限流的录制就有）："
                         + "、".join(sampled_deps))
        if not parts:
            return None
        unreachable = undeclared | unavailable
        return "；".join(self._coverage_clauses(m, unreachable) + parts) \
            + "。相关计数标为未知，而不是 0。"

    def _coverage_clauses(self, m: dict, undeclared: set[str]) -> list[str]:
        scalar = [k for k in m if k not in _NOT_A_METRIC]
        total = len(scalar)
        observed = sum(1 for k in scalar if m[k] is not None)
        unreachable = sum(1 for k in self._METRIC_KINDS.values()
                          if k in undeclared)
        unreachable += sum(1 for deps in self._DERIVED_FROM.values()
                           if any(k in undeclared for k in deps))
        head = f"本趟 {total} 项指标里 {observed} 项有数"
        if not unreachable:
            return [head]
        return [head,
                f"按这份 manifest，其中 {unreachable} 项没有函数可映，"
                f"这份 manifest 下最多只能有 {total - unreachable} 项"]


    def _event_stream_meta(self) -> dict:
        return {
            "type": "meta", "schema": "nodefusion.event-stream/1",
            "run": self.manifest.get("run_name"),
            "program": self.manifest.get("program"),
            "outcome": self.manifest.get("outcome"),
            "kernel": str(self.kernel_elf_path),
            "lab_stage": self.manifest.get("lab_stage"),
            "total_insns": self.trace.total_insns,
            "icount_shift": self.manifest.get("icount_shift"),
            "cpus": self.ncpu,
            "snapshots": len(self.states),
            "plugin_meta": self.trace.meta,
            "notes": self.notes,
        }

    def estimate_event_stream_bytes(self, sample_size: int = 1024) -> int:
        """Estimate JSONL size without first materializing millions of strings.

        The CLI uses this only as a conservative disk-safety gate.  Small event
        streams are measured exactly; large ones sample evenly across the run
        and add a 25 percent margin so an unusual tail cannot fill the disk.
        """
        meta = json.dumps(self._event_stream_meta(), ensure_ascii=False)
        if not self.events:
            return len((meta + "\n").encode("utf-8"))

        n = len(self.events)
        count = min(max(1, sample_size), n)
        if count == n:
            indices = range(n)
        elif count == 1:
            indices = (0,)
        else:
            indices = (i * (n - 1) // (count - 1) for i in range(count))
        sampled = sum(len((json.dumps(self.events[i].to_json(), ensure_ascii=False)
                           + "\n").encode("utf-8")) for i in indices)
        estimate = len((meta + "\n").encode("utf-8")) + sampled * n // count
        return estimate if count == n else estimate * 5 // 4

    def write_event_stream(self, path: Path) -> None:
        """Atomically write the reusable JSONL event stream.

        A full disk used to leave a plausible-looking truncated ``events.jsonl``
        behind.  The sibling temporary file is removed on every failure and is
        only renamed into place after the final write has succeeded.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(self._event_stream_meta(), ensure_ascii=False) + "\n")
                for e in self.events:
                    f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def analyze(run_dir: Path) -> Analysis:
    a = Analysis(run_dir)
    a.rebuild_states()
    a.build_events()
    return a
