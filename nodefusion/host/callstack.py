"""Conservative observed-frame chains from function entries and RISC-V returns."""

from __future__ import annotations

import heapq

from ..model.symbols import demangle, demangle_v0
from . import nftrace


def observed_stacks(events, returns, elf, retained_ids=None):
    """Return entry-id -> frames and match counts, never guessing across gaps.

    Only adjacent observed frames with a resolved caller, compatible SP/satp,
    and an actual return target are joined. Traps and scheduler switches break
    the chain; a different function or address space starts a new root.
    """
    paths = {}
    active = {}
    matched = 0
    nested = 0
    caller_cache = {}
    if not returns:
        return paths, {"raw": 0, "matched": 0, "nested_entries": 0}
    entries = ((e.insn, 0, e.cpu, e) for e in events
               if e.function_entry or e.kind == "sched.switch" or
               e.kind.startswith(("trap.", "interrupt.", "firmware.")))
    exits = ((r.insn, 1, r.cpu, r) for r in returns)
    for _, kind, cpu, obj in heapq.merge(entries, exits,
                                        key=lambda row: (row[0], row[1])):
        if kind == 1:
            frames = active.get(cpu)
            if (frames and not obj.flags & nftrace.F_NO_REGS and
                    not obj.flags & nftrace.F_NO_CSR and
                    frames[-1].return_address == obj.target and
                    frames[-1].address_space == obj.satp and
                    frames[-1].stack_pointer == obj.sp):
                frames.pop()
                matched += 1
            continue
        if not obj.function_entry:
            active.pop(cpu, None)
            continue
        if (obj.return_address is None or obj.stack_pointer is None or
                obj.address_space is None):
            active.pop(cpu, None)
            continue
        frames = active.setdefault(cpu, [])
        parent = frames[-1] if frames else None
        if obj.return_address not in caller_cache:
            raw = elf.resolve_pc(obj.return_address)[0] if elf else None
            caller_cache[obj.return_address] = (
                demangle(raw) or demangle_v0(raw) or raw) if raw else None
        caller = caller_cache[obj.return_address]
        if (parent is None or parent.entry_name != caller or
                parent.address_space != obj.address_space or
                obj.stack_pointer > parent.stack_pointer):
            frames.clear()
        if len(frames) >= 64:
            frames.clear()
        frames.append(obj)
        if retained_ids is None or id(obj) in retained_ids:
            paths[id(obj)] = tuple(f.entry_name or f.func or f.kind for f in frames[-16:])
        if len(frames) > 1:
            nested += 1
    return paths, {"raw": len(returns), "matched": matched,
                   "nested_entries": nested}
