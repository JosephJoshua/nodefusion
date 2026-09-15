"""Contracts shared by the shipped kernel integration patches and manifests."""

from pathlib import Path

from nodefusion.model.manifest import load

ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS = ROOT / "integrations"


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
    assert "vm.unmap" not in manifest.absent


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


def test_rcore_log_commit_remains_an_evidence_backed_feature_absence():
    manifest = load(ROOT / "manifests" / "rcore.toml")
    absent = manifest.absent["log.commit"]
    assert absent.why == "feature"
    assert "easy-fs/src" in absent.evidence
    assert "journal" in absent.evidence


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
    parent = next(field for field in manifest.entity("process").relations
                  if field.name == "parent")
    assert parent.optional is True
    assert parent.links_to == "process"
    assert "CHAPTER=1" in manifest.profile.build
    assert "-f os/queue.c" in manifest.profile.build
    assert "-f nfs/fs.c" in manifest.profile.build
    assert "scripts/pack.py" in manifest.profile.build
    assert manifest.profile.devices[0].built_when == ("Makefile", "fs-copy.img:")
    doc = (ROOT.parent / "docs" / "kernels" / "ucoreos" /
           "chapters.md").read_text()
    for chapter in range(1, 9):
        assert f"| {chapter} |" in doc
    legacy = (INTEGRATIONS / "ucore-legacy-nodefusion.patch").read_text()
    for token in ("NFT_KALLOC", "NFT_KFREE", "NFT_ALLOCATOR_STATE",
                  "nodefusion_pagetable_map"):
        assert token in legacy
    for filename in ("ucore-ch5-nodefusion.patch",
                     "ucore-ch6-ch7-nodefusion.patch"):
        process = (INTEGRATIONS / filename).read_text()
        assert "nftrace_proc_fork((uint64)p->pid, (uint64)np->pid)" in process
