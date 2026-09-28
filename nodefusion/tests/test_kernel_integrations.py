"""Contracts shared by the shipped kernel integration patches and manifests."""

import subprocess
from pathlib import Path

import pytest

from nodefusion.host.analyze import Analysis
from nodefusion.model.manifest import load

ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS = ROOT / "integrations"


def test_integration_patches_are_well_formed_unified_diffs():
    for patch in INTEGRATIONS.glob("*.patch"):
        subprocess.run(
            ["git", "apply", "--numstat", str(patch)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_starry_patch_exports_the_wire_point_and_all_registered_types():
    text = (INTEGRATIONS / "starry-nodefusion.patch").read_text(encoding="utf-8")
    assert "nftrace_commit_point" in text
    for name, number in (("NFT_KALLOC", 1), ("NFT_PROC_FORK", 2),
                         ("NFT_THREAD_CREATE", 3), ("NFT_SCHED_SWITCH", 4),
                         ("NFT_KFREE", 5), ("NFT_ALLOCATOR_STATE", 6)):
        assert f"const {name}: u64 = {number};" in text
    assert "trace_page_alloc(0, num_pages, free_pages, used_pages)" in text, (
        "allocation failure must emit a zero result and requested page count")
    assert "trace_page_alloc(addr, num_pages, free_pages, used_pages)" in text
    assert "trace_page_free(pos, num_pages, free_pages, used_pages)" in text
    assert "trace_allocator_state(free_pages, used_pages)" in text
    assert "flags.contains(CloneFlags::THREAD)" in text


def test_starry_cache_results_are_recorded_per_request():
    patch = (INTEGRATIONS / "starry-cache-trace.patch").read_text()
    assert "const NFT_CACHE_READ: u64 = 7;" in patch
    assert "folio.slot(slot).is_uptodate()" in patch
    assert "if filled.is_err() { 2 } else { u64::from(hit) }" in patch
    assert "trace_cache_read(if result.is_ok() { 0 } else { 2 }" in patch
    assert '"ax-fs-ng/nodefusion-trace"' in patch


def test_starry_thread_probe_uses_a_real_linux_clone_thread_call():
    text = (INTEGRATIONS / "starry-thread-probe.S").read_text(encoding="utf-8")
    # CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND |
    # CLONE_THREAD | CLONE_SYSVSEM, followed by the RISC-V clone syscall.
    assert "li      a0, 0x50f00" in text
    assert "li      a7, 220" in text
    assert "child_stack_end" in text
    assert "li      a7, 93" in text


def test_rcore_patch_and_manifest_agree_on_the_per_region_hook():
    symbol = "os::mm::memory_set::nodefusion_vm_unmap_region"
    patch = (INTEGRATIONS / "rcore-nodefusion.patch").read_text(encoding="utf-8")
    assert "for area in self.areas.iter()" in patch
    assert "nodefusion_vm_unmap_region(" in patch

    manifest = load(ROOT / "manifests" / "rcore.toml")
    assert manifest.events[symbol].kind == "vm.unmap"
    assert manifest.events[symbol].args == ["start_vpn", "end_vpn"]
    assert manifest.absent["vm.unmap"].when == {
        "type_missing": "os::mm::memory_set::MemorySet"}


def test_rcore_patch_exports_exact_physical_allocation_results():
    patch = (INTEGRATIONS / "rcore-nodefusion.patch").read_text(encoding="utf-8")
    assert "nftrace_commit_point" in patch
    assert "const NFT_KALLOC: u64 = 1;" in patch
    assert "PhysAddr::from(f.ppn).0" in patch
    assert "a: [paddr as u64, 1, free_pages as u64, used_pages as u64]" in patch
    assert "const NFT_SCHED_SWITCH: u64 = 4;" in patch
    assert "const NFT_KFREE: u64 = 5;" in patch
    assert "nodefusion_trace_page_free" in patch
    assert "nodefusion_trace_sched_switch" in patch


def test_rcore_reference_region_removal_is_an_attempt_not_a_success_event():
    manifest = load(ROOT / 'manifests/rcore.toml')
    symbol = 'os::mm::memory_set::MemorySet::remove_framed_area'
    assert manifest.events[symbol].kind == 'vm.remove_area'
    assert manifest.events[symbol].args == ['self', 'start_vpn', 'end_vpn']
    dedicated = next(index for index, watch in enumerate(manifest.watches)
                     if watch.match.get('fn') == ['remove_framed_area'])
    inline = next(index for index, watch in enumerate(manifest.watches)
                  if watch.match.get('fn') == ['frame_alloc', 'frame_dealloc', 'unmap', 'init_heap'])
    assert dedicated < inline
    assert manifest.watches[dedicated].args == 3
    assert not manifest.watches[dedicated].inlined


def test_rcore_2026a_ch4_observation_patch_preserves_region_acceptance():
    patch = (INTEGRATIONS / 'rcore-2026a-ch4-observation.patch').read_text()
    assert patch.index('})?;') < patch.index('nodefusion_vm_unmap_region(start.0, end.0);')
    assert patch.index('nodefusion_vm_unmap_region(start.0, end.0);') < patch.index('let mut area = self.areas.remove(index);')
    assert 'const NFT_ALLOCATOR_STATE: u64 = 6;' in patch
    assert 'a: [free_pages as u64, used_pages as u64, 0, 0]' in patch
    assert 'nodefusion_trace_page(NFT_KALLOC, paddr, free_pages, used_pages)' in patch
    assert 'nodefusion_trace_page(NFT_KFREE, PhysAddr::from(ppn).0, free_pages, used_pages)' in patch
    assert 'GlobalAlloc::alloc(&self.0, layout)' in patch
    assert 'GlobalAlloc::dealloc(&self.0, ptr, layout)' in patch
    manifest = load(ROOT / 'manifests/rcore.toml')
    event = manifest.events['os::mm::page_table::PageTable::map']
    assert event.kind == 'pagetable.map' and event.args == ['self', 'vpn', 'ppn', 'flags']
    rule = next(watch for watch in manifest.watches
                if watch.match == {'module': 'os::mm::page_table::PageTable', 'fn': ['map']})
    assert rule.args == 4 and not rule.inlined


def test_rcore_chapter_patches_preserve_per_region_and_scheduler_identity():
    for chapter in (6, 8):
        patch = (INTEGRATIONS / f"rcore-ch{chapter}-nodefusion.patch").read_text(
            encoding="utf-8")
        assert "nodefusion_vm_unmap_region" in patch
        assert "self.areas.clear();" in patch
        assert "nftrace_commit_point" in patch
        assert "nodefusion_trace_page(NFT_KALLOC" in patch
        assert "nodefusion_trace_sched_switch" in patch
    ch8 = (INTEGRATIONS / "rcore-ch8-nodefusion.patch").read_text()
    assert "Arc::as_ptr(&task) as usize" in ch8
    assert "a: [from_task, to_task, from_pid, to_pid]" in ch8
    assert "block_current_and_run_next" in ch8


def test_2026a_ch8_observation_preserves_thread_and_process_identity():
    rust = (INTEGRATIONS / 'rcore-2026a-ch8-observation.patch').read_text()
    c = (INTEGRATIONS / 'ucore-2026a-ch8-observation.patch').read_text()
    assert 'emit(3, [parent as u64, child as u64, 0, 0]);' in rust
    assert 'emit(3, parent_tid, child_tid, 0, 0);' in c
    assert rust.index('(*new_task_trap_cx).x[10] = arg;') < rust.index('crate::nftrace::thread_create(parent_tid, new_task_tid);')
    assert c.index('add_task(t);') < c.index('nftrace_thread_create(curr_thread()->tid, tid);')
    assert 'crate::nftrace::process_fork(current_process.getpid(), new_pid);' in rust
    assert c.index('add_task(nt);') < c.index('nftrace_proc_fork(p->pid, np->pid);')
    assert 'next_pid = task.process.upgrade().unwrap().getpid();' in rust
    assert 'crate::nftrace::NO_TASK, next_pid' in rust
    assert 'processor::trace_to_idle(task_id, pid);' in rust
    assert 'nftrace_sched_switch((uint64)&idle, (uint64)t, (uint64)-1, t->process->pid);' in c
    assert 'nftrace_sched_switch((uint64)t, (uint64)&idle, t->process->pid, (uint64)-1);' in c
    assert 'pub fn schedule(switched_task_cx_ptr: *mut TaskContext)' not in '\n'.join(line for line in rust.splitlines() if line.startswith(('+', '-')))


def test_2026a_ch8_sync_patch_only_retains_function_entries():
    patch = (INTEGRATIONS / 'rcore-2026a-ch8-observation.patch').read_text()
    assert 'pub fn recycle_data_pages' not in patch, (
        'dropping data frames leaves zombie page-table entries intact')
    for path in ('mutex.rs', 'semaphore.rs', 'condvar.rs'):
        section = patch.split(f'diff --git a/os/src/sync/{path}', 1)[1].split('diff --git ', 1)[0]
        additions = [line[1:].strip() for line in section.splitlines()
                     if line.startswith('+') and not line.startswith('+++')]
        deletions = [line for line in section.splitlines()
                     if line.startswith('-') and not line.startswith('---')]
        assert additions and set(additions) == {'#[inline(never)]'}
        assert not deletions
    assert 'diff --git a/os/src/sync/deadlock.rs' not in patch
    c = (INTEGRATIONS / 'ucore-2026a-ch8-observation.patch').read_text()
    assert 'diff --git a/os/sync.c' not in c
    assert 'diff --git a/os/proc.h' not in c
    for name in ('current_add_signal', 'remove_from_pid2process'):
        assert f'+#[inline(never)]\n pub fn {name}' in patch


@pytest.mark.parametrize('chapter', [5, 6, 7])
def test_2026a_observation_preserves_allocator_and_switch_semantics(chapter):
    rust = (INTEGRATIONS / f'rcore-2026a-ch{chapter}-observation.patch').read_text()
    c = (INTEGRATIONS / f'ucore-2026a-ch{min(chapter, 6)}-observation.patch').read_text()
    for patch in (rust, c):
        assert 'nftrace_commit_point' in patch
        assert 'nodefusion_pagetable_map' in patch or '#[inline(never)]' in patch
    assert 'self.allocated -= 1;' in rust
    assert 'self.allocated += 1;' in rust
    assert 'if result.is_some()' in rust
    assert 'frame.as_ref().map_or(0, |frame| PhysAddr::from(frame.ppn).0)' in rust
    assert 'pub(crate) const NO_TASK: usize = usize::MAX;' in rust
    assert 'emit(4, [from_task as u64, to_task as u64, from_pid as u64, to_pid as u64])' in rust
    assert 'crate::nftrace::NO_TASK, next_pid' in rust
    assert 'crate::nftrace::sched_switch(task_id, idle, pid, crate::nftrace::NO_TASK)' in rust
    assert rust.index('add_task(new_task);') < rust.index('crate::nftrace::process_fork(current_task.getpid(), new_pid);')
    assert 'nf_used_pages--;' in c
    assert 'nf_used_pages++;' in c
    assert c.index('nf_used_pages--;') < c.index('nftrace_page_free((uint64)pa, nf_free_pages, nf_used_pages);')
    assert c.index('add_task(np);') < c.index('nftrace_proc_fork(p->pid, np->pid);')
    assert 'nftrace_sched_switch((uint64)&idle, (uint64)p, (uint64)-1, p->pid);' in c
    assert 'nftrace_sched_switch((uint64)p, (uint64)&idle, p->pid, (uint64)-1);' in c
    assert c.index('*pte = PA2PTE(pa) | perm | PTE_V;') < c.index('nodefusion_pagetable_map(a, pa, perm | PTE_V);')


@pytest.mark.parametrize('chapter', [6, 7])
def test_2026a_filesystem_observation_keeps_the_directory_algorithm(chapter):
    patch = (INTEGRATIONS / f'rcore-2026a-ch{chapter}-observation.patch').read_text()
    filesystem = patch.split('diff --git a/easy-fs/src/vfs.rs', 1)[1].split('diff --git ', 1)[0]
    added = [line[1:] for line in filesystem.splitlines() if line.startswith('+') and not line.startswith('+++')]
    removed = [line for line in filesystem.splitlines() if line.startswith('-') and not line.startswith('---')]
    assert added == ['    #[inline(never)]'] and not removed
    assert 'fn find_inode_id(&self, name: &str, disk_inode: &DiskInode)' in filesystem


def test_2026a_ch7_pipe_observation_only_retains_existing_helpers():
    patch = (INTEGRATIONS / 'rcore-2026a-ch7-observation.patch').read_text()
    pipe = patch.split('diff --git a/os/src/fs/pipe.rs', 1)[1].split('diff --git ', 1)[0]
    added = [line[1:] for line in pipe.splitlines() if line.startswith('+') and not line.startswith('+++')]
    removed = [line for line in pipe.splitlines() if line.startswith('-') and not line.startswith('---')]
    assert added == ['    #[inline(never)]'] * 5 and not removed
    for name in ('write_byte', 'read_byte', 'available_read', 'available_write', 'all_write_ends_closed'):
        assert 'pub fn ' + name + '(' in pipe
    task = patch.split('diff --git a/os/src/task/mod.rs', 1)[1].split('diff --git ', 1)[0]
    assert 'fn call_kernel_signal_handler(' in task
    assert 'fn call_user_signal_handler(' in task
    assert 'fn check_pending_signals(' in task
    assert not [line for line in task.splitlines() if line.startswith('-') and not line.startswith('---')]


def test_rcore_2026a_ch5_region_hooks_only_describe_explicit_pte_removal():
    patch = (INTEGRATIONS / 'rcore-2026a-ch5-observation.patch').read_text()
    assert 'if mapped_end > area.vpn_range.get_start()' in patch
    assert 'nodefusion_vm_unmap_region(area.vpn_range.get_start().0, mapped_end.0);' in patch
    assert 'if self.vpn_range.get_start() < self.vpn_range.get_end()' in patch
    assert 'nodefusion_vm_unmap_region(self.vpn_range.get_start().0, self.vpn_range.get_end().0);' in patch
    assert 'if new_end < self.vpn_range.get_end()' in patch
    assert 'nodefusion_vm_unmap_region(new_end.0, self.vpn_range.get_end().0);' in patch
    # Releasing data-frame ownership on exit leaves the zombie page table alive.
    # Do not invent explicit PTE-removal events for that separate operation.
    assert 'self.areas.clear();' not in patch


def test_rcore_ch8_keeps_applicable_vm_and_signal_watchpoints_callable():
    patch = (INTEGRATIONS / "rcore-page-table-observation-points.patch").read_text()
    assert patch.count("#[inline(never)]") == 6
    for name in ("PageTable", "find_pte_create", "find_pte(", "map(",
                 "translate(", "current_add_signal("):
        assert name in patch


def test_rcore_ch4_sched_probe_uses_task_ids_without_inventing_pids():
    patch = (INTEGRATIONS / "rcore-ch4-nodefusion.patch").read_text()
    assert "nodefusion_trace_sched_switch(Some(current), Some(next))" in patch
    assert "a: [from, to, NFT_NO_TASK, NFT_NO_TASK]" in patch
    assert "nodefusion_trace_page(NFT_KALLOC" in patch


def test_rcore_log_commit_remains_an_evidence_backed_feature_absence():
    manifest = load(ROOT / "manifests" / "rcore.toml")
    absent = manifest.absent["log.commit"]
    assert absent.why == "feature"
    assert "easy-fs/src" in absent.evidence
    assert "journal" in absent.evidence


def test_rcore_filesystem_absence_depends_on_the_resolved_build(monkeypatch):
    manifest = load(ROOT / "manifests" / "rcore.toml")
    monkeypatch.setattr("nodefusion.model.manifest.load_dir",
                        lambda: {"rcore": manifest})

    class Dwarf:
        def __init__(self, present):
            self.present = present

        def find(self, name):
            assert name in {
                "easy_fs::block_cache::BlockCacheManager",
                "os::task::task::TaskControlBlock",
                "os::task::processor::Processor",
                "os::mm::frame_allocator::StackFrameAllocator",
                "os::mm::memory_set::MemorySet"}
            return object() if name in self.present else None

    for present in (
        set(),
        {"os::mm::frame_allocator::StackFrameAllocator",
         "os::mm::memory_set::MemorySet"},
        {"os::task::processor::Processor",
         "os::mm::frame_allocator::StackFrameAllocator",
         "os::mm::memory_set::MemorySet"},
        {"easy_fs::block_cache::BlockCacheManager",
         "os::task::processor::Processor",
         "os::mm::frame_allocator::StackFrameAllocator",
         "os::mm::memory_set::MemorySet"},
    ):
        analysis = object.__new__(Analysis)
        analysis.kernel_kind = "rcore"
        analysis._manifest_dw = Dwarf(present)
        analysis.kevents = None
        analysis.notes = []
        absent = analysis._absent_kinds()
        for kind, typ in (
            ("bcache.read", "easy_fs::block_cache::BlockCacheManager"),
            ("disk.io", "easy_fs::block_cache::BlockCacheManager"),
            ("sched.switch", "os::task::task::TaskControlBlock"),
            ("proc.initproc", "os::task::task::TaskControlBlock"),
            ("proc.alloc", "os::task::task::TaskControlBlock"),
            ("proc.fork", "os::task::processor::Processor"),
            ("proc.exec", "os::task::processor::Processor"),
            ("vm.unmap", "os::mm::memory_set::MemorySet"),
            ("phys.alloc", "os::mm::frame_allocator::StackFrameAllocator"),
            ("phys.free", "os::mm::frame_allocator::StackFrameAllocator"),
            ("vm.map", "os::mm::memory_set::MemorySet"),
            ("pagetable.map", "os::mm::memory_set::MemorySet"),
        ):
            assert (kind in absent) == (typ not in present)
        assert "log.commit" in absent


def test_ucore_patch_and_manifest_supply_exact_semantics():
    patch = (INTEGRATIONS / "ucore-nodefusion.patch").read_text(encoding="utf-8")
    for name, number in (("NFT_KALLOC", 1), ("NFT_PROC_FORK", 2),
                         ("NFT_THREAD_CREATE", 3), ("NFT_SCHED_SWITCH", 4),
                         ("NFT_KFREE", 5), ("NFT_ALLOCATOR_STATE", 6)):
        assert f"{name} = {number}" in patch
    assert "nftrace_commit_point" in patch
    assert "nodefusion_pagetable_map(a, pa, perm | PTE_V)" in patch
    assert "nftrace_proc_fork(task_to_id(curr_thread()), task_to_id(nt))" in patch
    assert "nftrace_thread_create(task_to_id(curr_thread()), task_to_id(t))" in patch

    manifest = load(ROOT / "manifests" / "ucore.toml")
    assert manifest.events["nodefusion_pagetable_map"].kind == "pagetable.map"
    assert manifest.events["uvmunmap"].kind == "vm.unmap"
    assert manifest.events["fork"].kind == "proc.fork"
    assert manifest.absent["log.commit"].why == "feature"


def test_ucore_2026a_ch4_patch_observes_allocator_results_and_committed_ptes():
    patch = (INTEGRATIONS / 'ucore-2026a-ch4-observation.patch').read_text()
    paths = [line.split(' b/', 1)[1] for line in patch.splitlines() if line.startswith('diff --git ')]
    assert set(paths) == {'os/kalloc.c', 'os/vm.c', 'os/nftrace.c', 'os/nftrace.h'}
    assert 'NFT_KALLOC = 1' in patch and 'NFT_KFREE = 5' in patch and 'NFT_ALLOCATOR_STATE = 6' in patch
    assert 'nftrace_page_alloc((uint64)l, 1, nf_free_pages, nf_used_pages)' in patch
    assert 'nftrace_page_free((uint64)pa, 1, nf_free_pages, nf_used_pages)' in patch
    assert 'nftrace_allocator_state(nf_free_pages, nf_used_pages)' in patch
    assert patch.index('*pte = PA2PTE(pa) | perm | PTE_V;') < patch.index('nodefusion_pagetable_map(a, pa, perm | PTE_V);')
    assert 'const struct nftrace_record record = { type, { a0, a1, a2, a3 } }' in patch


def test_ucore_2026a_ch4_page_table_experiment_owns_and_reclaims_its_pages():
    patch = (INTEGRATIONS / 'ucore-2026a-ch4-pagetable-experiment.patch').read_text()
    assert patch.index('uvmunmap(table, va, 1, 0)') < patch.index('uvmunmap(table, va, 1, 1)')
    assert patch.index('uvmunmap(table, TRAMPOLINE, 1, 0)') < patch.index('freewalk(table)')
    assert 'walkaddr(table, va + 0x123) != (uint64)frame' in patch
    assert 'useraddr(table, va + 0x123) != (uint64)frame + 0x123' in patch
    assert 'frame[0x123] != 0x5a' in patch
    assert patch.index('kvm_init();') < patch.index('nodefusion_pagetable_experiment();', patch.index('kvm_init();'))


def test_ucore_showcase_fixes_remain_separate_from_observation_patch():
    observation = (INTEGRATIONS / "ucore-nodefusion.patch").read_text()
    kernel_fix = (INTEGRATIONS / "ucore-ch8-showcase.patch").read_text()
    user_fix = (INTEGRATIONS / "ucore-user-modern-toolchain.patch").read_text()
    assert "m->locked = 1" not in observation
    assert "m->locked = 1" in kernel_fix
    assert "rv64imac_zicsr" in user_fix
    assert "CH7_TESTS := $(CH7_BASE_TESTS)" in user_fix
    assert '"ch8b_mut_phi_din\\0"' in user_fix


def test_ucore_manifest_covers_all_eight_measured_shapes():
    manifest = load(ROOT / "manifests" / "ucore.toml")
    assert manifest.detect == {"all_symbol": ["digits", "SBI_SHUTDOWN"]}
    assert manifest.derive_feature_absence_from_symbols is True
    process = manifest.entity("process")
    assert process.liveness["skip_when"] == {
        "field": "state", "one_of": ["UNUSED", "P_UNUSED"]}
    fields = {field.name: field for field in process.fields}
    assert fields["context"].role == "sched_context"
    assert fields["trapframe"].role == "trap_context"
    assert all(fields[name].optional for name in ("context", "trapframe", "kstack"))
    parent = next(field for field in manifest.entity("process").relations
                  if field.name == "parent")
    assert parent.optional is True
    assert parent.links_to == "process"
    assert "CHAPTER=1" in manifest.profile.build
    assert "-f os/queue.c" in manifest.profile.build
    assert "-f nfs/fs.c" in manifest.profile.build
    assert "scripts/pack.py" in manifest.profile.build
    assert manifest.profile.devices[0].built_when == ("Makefile", "fs-copy.img:")
    doc = (ROOT.parent / "artifacts" / "ucoreos" / "README.md").read_text()
    for chapter in range(1, 9):
        assert f"| ch{chapter} |" in doc
    legacy = (INTEGRATIONS / "ucore-legacy-nodefusion.patch").read_text()
    for token in ("NFT_KALLOC", "NFT_KFREE", "NFT_ALLOCATOR_STATE",
                  "nodefusion_pagetable_map"):
        assert token in legacy
    for filename in ("ucore-ch5-nodefusion.patch",
                     "ucore-ch6-ch7-nodefusion.patch"):
        process = (INTEGRATIONS / filename).read_text()
        assert "nftrace_proc_fork((uint64)p->pid, (uint64)np->pid)" in process
