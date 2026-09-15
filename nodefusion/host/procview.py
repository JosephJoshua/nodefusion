
from __future__ import annotations

from typing import Any

from ..model.snapshot import Entity

_BY_ROLE = {
    "pid": "id",
    "name": "name",
    "state_name": "state",
    "pagetable": "address_space_root",
    "priority": "priority",
    "xstate": "exit_code",
    "trapframe": "trap_context",
    "sched_ctx": "sched_context",
}

_BY_NAME = ("sz", "chan", "killed", "stride", "pass", "kstack", "cwd")


def render_state(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    return f"?{value & 0xFFFFFFFF:#x}"


def open_fd_indices(entity: Entity, field: str = "ofile") -> list[int] | None:
    table = entity.get(field)
    if table is None:
        return None
    return [i for i, slot in enumerate(table) if slot]


def parent_id(entity: Entity, field: str = "parent") -> Any:
    p = entity.link(field)
    return p.role("id") if p is not None else None


def sched_contexts(entity: Entity) -> list[int]:
    out: list[int] = []
    own = entity.role("sched_context")
    if isinstance(own, int) and not isinstance(own, bool):
        out.append(own)
    for subs in entity.links.values():
        for sub in subs:
            if sub.kind == entity.kind:
                continue
            v = sub.role("sched_context")
            if isinstance(v, int) and not isinstance(v, bool) and v not in out:
                out.append(v)
    return out


def row(entity: Entity, *, slot: int) -> dict[str, Any]:
    out: dict[str, Any] = {"slot": slot, "addr": entity.addr}

    for key, role in _BY_ROLE.items():
        out[key] = entity.role(role)
    for key in _BY_NAME:
        out[key] = entity.get(key)

    out["state_name"] = render_state(out["state_name"])
    out["parent_pid"] = parent_id(entity)
    out["fds"] = open_fd_indices(entity)
    out["sched_ctxs"] = sched_contexts(entity)
    return out


def fields_view(entity: Entity) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "state": f.state,
            "value": f.value,
            "role": f.role,
            "reason": f.reason,
            "reader": f.reader,
        }
        for name, f in entity.fields.items()
    }
