# uCore tutorial chapters 1–8

NodeFusion treats the eight historical uCore tutorial kernels as one family
manifest.  The manifest selects entity sources from DWARF rather than a
chapter flag:

| chapters | measured shape | observable additions |
| --- | --- | --- |
| 1 | console-only | trap/SBI/console timeline; process, VM, allocator, and FS tables are explicitly absent |
| 2 | batch loader + trapframe | application-loader and syscall timeline; no process table yet |
| 3 | fixed `proc[NPROC]` scheduler | process table and scheduler/context events |
| 4 | `proc[NPROC]` + VM + allocator | exact allocator counters and per-PTE `pagetable.map` hook |
| 5 | VM + queue + process lifecycle | exact allocator counters and process-fork semantic hook |
| 6 | filesystem/device stack | bcache, file, inode, disk, and process tables |
| 7 | filesystem/device + pipe | chapter-7 pipe events and all chapter-6 resources |
| 8 | nested `proc[NPROC].threads[NTHREAD]` | separate process/thread tables, fork-vs-thread semantic channel, and sync events |

The ch4–ch7 observation hooks use the same wire protocol as the ch8
integration. Apply `ucore-legacy-nodefusion.patch` to ch4,
`ucore-ch5-nodefusion.patch` to ch5, and
`ucore-ch6-ch7-nodefusion.patch` to ch6–ch7. The latter two also emit exact
process-fork records. The ch8 source patch additionally emits
`NFT_THREAD_CREATE`, because only ch8 has distinct kernel thread creation.
This keeps the integration honest: earlier chapters cannot report thread
creation without inventing a distinction their kernel does not have.

The strict audit derives chapter-local feature absence from the resolved ELF
symbols.  Thus a missing `proc.fork` in ch1–4 is N/A, while a present but
unwatched function remains a coverage failure.  Early boot snapshots taken
before allocator initialization are excluded from the allocator-counter
denominator; they remain complete physical-memory snapshots.

The checked-in coverage evidence records one run for every chapter.  The HTML
reports intentionally contain the concise standard provenance banner; no
chapter-specific multi-paragraph disclaimer is injected into the reports.

The shared user-space compatibility patch enables the explicit Zicsr ISA
extension required by current RISC-V assemblers, removes ch7's stale `ch7_`
test glob (that source tree contains only `ch7b_*` tests), and fixes the ch8
philosophers test filename. These are build/test-list compatibility changes,
kept separate from the kernel observation hooks.
