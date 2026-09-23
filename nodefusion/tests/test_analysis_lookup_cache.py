from types import SimpleNamespace as NS

from nodefusion.host.analyze import Analysis


def _proc(slot, pid, name, *contexts):
    return NS(slot=slot, pid=pid, name=name,
              sched_ctx=contexts[0] if contexts else None,
              sched_ctxs=list(contexts[1:]))


def test_event_attribution_lookups_are_cached_without_changing_order():
    a = object.__new__(Analysis)
    past = _proc(3, 10, "past", 0x1000)
    future = _proc(3, 20, "future", 0x2000, 0x2008)
    a.states = [
        NS(procs=[past], sched_owners={0x3000: {"name": "old"}}),
        NS(procs=[], sched_owners={}),
        NS(procs=[future], sched_owners={0x3000: {"name": "new"}}),
    ]

    # The historical policy searches the current and future snapshots before
    # falling back to the past. Memoization must retain that exact order.
    assert a._pid_by_slot_at(1, 3) == (20, "future")
    assert a._task_by_ctx(1, 0x2008) is future
    assert a._sched_owner(1, 0x3000) == {"name": "new"}

    assert a._pid_slot_cache[(1, 3)] == (20, "future")
    assert a._task_ctx_cache[(1, 0x2008)] is future
    assert a._sched_owner_cache[(1, 0x3000)] == {"name": "new"}


def test_missing_attribution_is_cached_too():
    a = object.__new__(Analysis)
    a.states = [NS(procs=[], sched_owners={})]
    assert a._pid_by_slot_at(0, 99) == (None, None)
    assert a._task_by_ctx(0, 0x9999) is None
    assert a._sched_owner(0, 0x9999) is None
    assert (0, 99) in a._pid_slot_cache
    assert (0, 0x9999) in a._task_ctx_cache
    assert (0, 0x9999) in a._sched_owner_cache
