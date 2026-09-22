from nodefusion.host.analyze import Event
from nodefusion.host.callstack import observed_stacks
from nodefusion.host.nftrace import FunctionReturn


class Elf:
    def resolve_pc(self, pc):
        return {0x10: ("root", 0), 0x20: ("child", 0)}.get(pc, (None, None))


def entry(insn, name, ra, sp, *, cpu=0, satp=1):
    return Event(insn, cpu, "func." + name, "function", function_entry=True,
                 entry_name=name, return_address=ra, stack_pointer=sp,
                 address_space=satp)


def ret(insn, target, sp, *, cpu=0, satp=1):
    return FunctionReturn(insn, cpu, 0, 0x1000, target, sp, satp, 1)


def test_nested_chain_requires_observed_return():
    root = entry(1, "root", 0x99, 100)
    child = entry(2, "child", 0x10, 80)
    sibling = entry(4, "child", 0x10, 80)
    paths, counts = observed_stacks([root, child, sibling],
                                    [ret(3, 0x10, 80), ret(5, 0x10, 80),
                                     ret(6, 0x99, 100)], Elf())
    assert paths[id(root)] == ("root",)
    assert paths[id(child)] == ("root", "child")
    assert paths[id(sibling)] == ("root", "child")
    assert counts == {"raw": 3, "matched": 3, "nested_entries": 2}


def test_context_change_and_unmatched_return_do_not_create_chains():
    root = entry(1, "root", 0x99, 100)
    unrelated = entry(3, "child", 0x10, 80, satp=2)
    other_cpu = entry(5, "child", 0x10, 80, cpu=1)
    paths, counts = observed_stacks([root, unrelated, other_cpu],
                                    [ret(2, 0x10, 80), ret(4, 0x99, 100)], Elf())
    assert paths[id(unrelated)] == ("child",)
    assert paths[id(other_cpu)] == ("child",)
    assert counts["matched"] == 0


def test_legacy_trace_has_no_claimed_stack():
    paths, counts = observed_stacks([entry(1, "root", 0x99, 100)], [], Elf())
    assert paths == {}
    assert counts == {"raw": 0, "matched": 0, "nested_entries": 0}


def test_unretained_entries_still_shape_retained_stack():
    root = entry(1, "root", 0x99, 100)
    child = entry(2, "child", 0x10, 80)
    paths, counts = observed_stacks([root, child], [ret(3, 0x10, 80)],
                                    Elf(), retained_ids={id(child)})
    assert paths == {id(child): ("root", "child")}
    assert counts["matched"] == 1
