"""Conservative observed-frame chains from function entries and RISC-V returns."""

from __future__ import annotations

import heapq

from ..model.symbols import display_name
from . import nftrace


def observed_stacks(events, returns, elf, retained_ids=None, *, raw_names=False, frame_pcs=None):
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
    label_cache = {}
    def label(name):
        if name not in label_cache:
            label_cache[name] = display_name(name)
        return label_cache[name]
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
            caller_cache[obj.return_address] = raw
        caller = caller_cache[obj.return_address]
        # Raw symbols distinguish Rust instantiations with the same display
        # name. Older producers may already supply a decoded entry name.
        caller_matches = (parent is not None and caller is not None and
                          (parent.entry_name == caller or parent.entry_name == label(caller)))
        if (not caller_matches or
                parent.address_space != obj.address_space or
                obj.stack_pointer > parent.stack_pointer):
            frames.clear()
        if len(frames) >= 64:
            frames.clear()
        frames.append(obj)
        if retained_ids is None or id(obj) in retained_ids:
            paths[id(obj)] = tuple((f.entry_name or f.func or f.kind) if raw_names
                                  else label(f.entry_name or f.func or f.kind) for f in frames)
            if frame_pcs is not None:
                # Parent frames show their suspended call site, not their entry.
                visible = frames
                frame_pcs[id(obj)] = tuple(
                    max(0, visible[k + 1].return_address - 1) if k + 1 < len(visible)
                    else (f.pc or 0) for k, f in enumerate(visible))
        if len(frames) > 1:
            nested += 1
    return paths, {"raw": len(returns), "matched": matched,
                   "nested_entries": nested}
