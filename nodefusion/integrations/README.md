# Kernel integrations

These patches add observation points; they do not replace NodeFusion's external
QEMU observer. Apply them to the exact upstream revision named below, build a
debug-symbol kernel, then record normally. Runs made without a patch remain
supported and keep unavailable semantics explicitly marked unknown.

## StarryOS

`starry-nodefusion.patch` targets `tgoskits` commit `7c5bbd1`.

```sh
git apply --unidiff-zero --check /path/to/nodefusion/nodefusion/integrations/starry-nodefusion.patch
git apply --unidiff-zero /path/to/nodefusion/nodefusion/integrations/starry-nodefusion.patch
CARGO_PROFILE_RELEASE_DEBUG=2 cargo xtask starry build \
  --config os/StarryOS/configs/board/qemu-riscv64.toml
```

The QEMU RISC-V board enables `starryos/nodefusion-trace`. The patch exports the
stable `nftrace_commit_point` symbol and emits the wire records registered in
`spec/event-stream.md`:

- `NFT_KALLOC`: physical allocation result, requested page count, and exact
  post-operation allocator counters, including a zero-address failure result;
- `NFT_PROC_FORK`: successful process creation from the clone/clone3 common path;
- `NFT_THREAD_CREATE`: successful thread creation from that same path.
- `NFT_SCHED_SWITCH`: exact outgoing/incoming scheduler IDs plus Linux TIDs
  where those exist, emitted by the scheduler tracepoint before the switch.
- `NFT_KFREE`: physical start address, page count, and exact post-operation
  allocator counters.
- `NFT_ALLOCATOR_STATE`: exact allocator counters after byte-heap mutations
  that can change the backing-page state without going through a page API.

The allocation callback runs after allocator locks are released and does not
allocate. The process/thread records run only after clone has committed and the
task has been spawned. This makes them authoritative over the earlier
function-entry classifier; the analyzer suppresses that duplicate when the
post-success record exists.

Use the explicit board config shown above. `--arch riscv64` materializes a
generated config only when one is missing, so a stale generated file can omit
new board features even though the source board config is correct.

`starry-thread-probe.S` is a 744-byte, no-libc RISC-V reproduction for the
`CLONE_THREAD` branch. Build it with the command in its header and run it in the
guest. On the patched kernel it produces `NFT_THREAD_CREATE`; ordinary shell
children produce `NFT_PROC_FORK`. This checks the distinction with the real
Linux clone ABI rather than inferring it from a function name.

## rCore

`rcore-nodefusion.patch` targets the tutorial repository's `ch7` commit
`6eed34d`. It adds the per-region VM-unmap hook and an allocation-result
`nftrace` producer.

```sh
git apply --unidiff-zero --check /path/to/nodefusion/nodefusion/integrations/rcore-nodefusion.patch
git apply --unidiff-zero /path/to/nodefusion/nodefusion/integrations/rcore-nodefusion.patch
cd os && CARGO_PROFILE_RELEASE_DEBUG=2 make build
```

The hook is called once for every `MapArea` immediately before that logical
region is removed, including the `areas.clear()` process-exit path. It accepts
the start and end VPN and changes no VM state. This supplies the per-region
granularity that neither `MapArea::unmap` nor `recycle_data_pages` has in an
unpatched course kernel.

`frame_alloc` emits `NFT_KALLOC` only after releasing the allocator borrow and
constructing the zeroed `FrameTracker`. The record carries the physical address,
`num_pages = 1`, and exact post-operation free/allocated page counts; allocation
failure carries address zero. `frame_dealloc` emits the corresponding
post-operation `NFT_KFREE` record. The analyzer uses these records as complete
physical-memory events and suppresses earlier function-entry duplicates.

The two rCore `__switch` call paths also emit `NFT_SCHED_SWITCH`. They record
the exact task PID and use the registered no-task sentinel for the scheduler
context, so short-lived tasks do not depend on landing inside a periodic memory
snapshot for attribution.

The patch intentionally does not create `log.commit`. easy-fs has no journal,
transaction commit, recovery record, or equivalent crash-atomic operation;
mapping a cache flush to that vocabulary would manufacture a false comparison
with xv6. NodeFusion keeps this kernel feature absence explicit, evidence-backed,
and embedded in HTML/video metadata.

## uCore

`ucore-nodefusion.patch` targets `LearningOS/uCore-Tutorial-Code` ch8 commit
`7728a992c20ce43627fbc319ccb4f5765e807cba`. It adds the same stable NFTrace
wire boundary used by the other integrations, with post-operation allocation,
free, fork, and thread-creation records. The noinline
`nodefusion_pagetable_map` hook runs after each successful PTE write, while the
existing `mappages` and `uvmunmap` entries retain region-level map/unmap counts.

```sh
git apply --check /path/to/nodefusion/nodefusion/integrations/ucore-nodefusion.patch
git apply /path/to/nodefusion/nodefusion/integrations/ucore-nodefusion.patch
```

The full ch8 showcase used two separately reviewable compatibility fixes:

- `ucore-ch8-showcase.patch` assigns the spinning mutex after a waiter observes
  it unlocked; the upstream teaching branch otherwise allows multiple waiters
  into the critical section.
- `ucore-user-modern-toolchain.patch` targets `LearningOS/uCore-Tutorial-Test`
  commit `1733f460c596b013b1c509ad42afa428640783b0`. It enables the `zicsr` ISA
  extension required by current GCC and removes a stray `.c` suffix from the
  aggregate test list.

Apply those patches in the kernel and nested `user` repositories respectively,
then record through the `ucore.toml` profile. The profile uses QEMU's built-in
OpenSBI because the repository's historical RustSBI image does not boot with
QEMU 10.2.2. uCore ch8 has no journal or transaction layer, so `log.commit`
remains an evidence-backed N/A rather than a fabricated cache-write event.
