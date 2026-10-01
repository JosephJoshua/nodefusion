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


def test_raw_stack_identity_and_suspended_call_site():
    root = entry(1, 'root', 0x99, 100)
    root.pc = 0x100
    child = entry(2, 'child', 0x10, 80)
    child.pc = 0x200
    pcs = {}
    paths, _ = observed_stacks([root, child], [ret(3, 0x10, 80)], Elf(),
                              raw_names=True, frame_pcs=pcs)
    assert paths[id(child)] == ('root', 'child')
    assert pcs[id(child)] == (0xf, 0x200)


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


def test_rust_raw_symbols_match_and_display_as_function_names():
    raw_root = '_ZN2os4root17h1234567890abcdefE'
    raw_child = '_ZN2os5child17h1234567890abcdefE'
    root = entry(1, raw_root, 0x99, 100)
    child = entry(2, raw_child, 0x10, 80)
    elf = type('RustElf', (), {'resolve_pc': lambda self, pc: (raw_root, 0) if pc == 0x10 else (None, 0)})()
    paths, counts = observed_stacks([root, child], [ret(3, 0x10, 80)], elf)
    assert paths[id(child)] == ('os::root', 'os::child')
    assert counts['nested_entries'] == 1
    assert root.entry_name == raw_root
    assert child.entry_name == raw_child


def test_decoded_names_do_not_merge_distinct_raw_rust_symbols():
    raw_root = '_ZN2os4root17h1234567890abcdefE'
    other_root = '_ZN2os4root17hfedcba0987654321E'
    root = entry(1, raw_root, 0x99, 100)
    child = entry(2, 'child', 0x10, 80)
    elf = type('RustElf', (), {'resolve_pc': lambda self, pc: (other_root, 0) if pc == 0x10 else (None, 0)})()
    paths, counts = observed_stacks([root, child], [ret(3, 0x10, 80)], elf)
    assert paths[id(child)] == ('child',)
    assert counts['nested_entries'] == 0
