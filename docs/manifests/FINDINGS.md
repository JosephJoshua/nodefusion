# What writing eight manifests changed

**Date:** 2026-08-30, revised 2026-08-31
**Status:** started as a paper exercise; much of it has since been executed.
Two kernels now have binaries here — rCore and, as of 2026-08-31, ArceOS — and
the sections drawn from them say so. The five remaining kernels are still
paper. Each section states which it is; treat anything unmarked as read, not
measured.

Read the ArceOS section before trusting the paper ones. It found that claims
taken from **struct definitions** all held, while claims needing the **symbol
table** were wrong every time — including a crate path (`ax_task`, real:
`axtask`) and a global that had never existed. That split is the best
available guess at which of the remaining paper claims will survive.

The point was to find where the vocabulary breaks *before* building an engine
around it. It broke in twelve places. All twelve are cheap to fix on paper and
would have been expensive to fix in code.

## The vocabulary I proposed vs what was actually needed

Proposed in the design doc:

```
steps:   static, field, unwrap, index, iter, walk, percpu
readers: vec<arc>, btreemap, hashbrown, bitfield, weak, lazy_static, up_safe_cell
```

### Steps that were missing

| step | forced by | why |
|---|---|---|
| `descend_to` | ArceOS | Enter an unknown wrapper by *naming the type you want*. `AxTask` is `FifoTask`/`RRTask`/`CFSTask` by feature. Verified: `FifoTask<TaskInner>` has `inner` at +0. This is type-directed navigation made concrete, and it is a step, not a reader. |
| `deref` | reL4 | `ksCurThread` is a raw `usize`. Turning an address into a typed struct is its own operation. |
| `from` | Starry, AxVisor | Cross-entity reference: `from = "process.threads"`. Without it, every child entity re-walks from the root. |

`unwrap` also had to take a **list** — `["LazyLock", "SpinRwLock"]`, not one
wrapper. Real chains are 2–4 deep. `walk` needed two shapes: `children` (tree)
and `list` (intrusive, with an explicit `terminator`, for reL4). `iter` needed
`array` / `vec` / `btreemap` variants.

### Structure that was missing entirely

These are not steps. Assuming a manifest was a flat list of steps was the
biggest error.

1. **Several sources per entity.** ArceOS needs `TASK_REGISTRY` (complete, but
   no notion of *running*) *and* per-CPU `RUN_QUEUE.current` (running only).
   reL4 needs ready-queues *and* `ksCurThread`. One traversal is never enough.

2. **`completeness` as a first-class value**, not a footnote. Observed values:
   `total`, `partial`, `reachable_only`, `ready_only`, `total_in_root_ns`,
   `none`. reL4 can enumerate Ready threads only — seL4 keeps TCBs in untyped
   memory it does not track. Alien can only reach tasks still linked under
   `INIT_PROCESS`. **These are properties of the kernel, not failures of
   NodeFusion, and the UI must not present them as the latter.**

3. **`when` predicates on sources.** This is the one that pays for the whole
   redesign — see below.

4. **Several entities with relations.** Starry's `Process` **has no `state`
   field**; state is per-thread inside `tg: ThreadGroup`. AxVisor needs
   `vm` + `vcpu`. A single "task" entity cannot express either.

5. **`liveness.skip_when`.** xv6 marks free slots `UNUSED` rather than removing
   them. Without this the UI shows 64 processes forever.

6. **`optional_fields` separate from `fields`.** Absent-by-construction is a
   normal outcome, not an error. Verified on ArceOS: `need_resched` absent
   (`preempt` off), `on_cpu` present (`smp` on).

7. **`verified = false` per field.** reL4's `tcb_t` lives in an unfetched git
   dependency. Recording the guess *and* its unverified status beats either
   omitting it or asserting it.

8. **`[[bitfield]]` with `checkable = false`.** See "the one real break".

9. **`address_space` with `stage = 2`.** AxVisor needs GPA→HVA declared so the
   renderer does not silently mix two address spaces that use the same
   integers. The translation itself needed **no new step** — `memory_regions`
   is a `Vec` of plain structs the existing readers already handle. Two-stage
   memory was easier than expected.

10. **`role = "address_space_root"` on a field.** This is how `satp` stops being
    a named field and becomes an arch-tagged slot.

11. **`family` inheritance.** Starry and AxVisor are built on ArceOS and still
    carry `ax_task::task::TaskInner`. Declaring `family = "arceos"` lets them
    reuse its entity definitions instead of copying them.

12. **Subsystem matching differs by language.** Rust matches on module path,
    C on `DW_AT_decl_file`. Both derive; neither enumerates.

## The payoff: rCore chapter branching disappears

Today: five hand-written resolvers dispatched on an integer
`RCORE_TASKS_KIND`, and `guest.py` branching on it across ~95 sites.

The realisation from writing `rcore.toml`: **`layout.py` already detects the
shape by probing DWARF** (`layout.py:734/813/864/994/1000`). Detection was
never the hard part. The downstream branching was.

So all five shapes become **ordered alternatives with `when` predicates**, and
the engine takes the first that resolves:

| shape | chapter | discriminator |
|---|---|---|
| tree + thread table | ch8 | `type_exists = "ProcessControlBlock"` |
| process tree | ch5–ch7 | `field_exists TaskControlBlockInner.children` |
| heap `Vec` | — | `field_type tasks starts_with "Vec<"` |
| inline array | ch3–ch4 | `field_exists TaskManagerInner.tasks` |
| batch | ch2 | `type_exists = "AppManager"` |

No chapter flag anywhere. The `Vec`-vs-array discriminator is exactly the test
`layout.py:977` already performs.

## Readers actually required

Far past `vec<arc>`. Grouped by what they decode:

- **containers** — `array`, `vec`, `btreemap`, intrusive list
- **pointers** — `arc`, `weak`, `option<weak>`, `ptr`
- **locks/cells** — `spinlock`, `mutex`, `upsafecell`, `unsafecell`
- **lazies** — `lazylock`, `lazy`, `lazyinit`
- **scalars** — `atomic<T>`, `newtype<T>`, `enum`, `cstr`, `string`, `bitfield`

The design rule holds: each of these is an **encoding**, so it belongs in
NodeFusion. Every manifest above is pure *arrangement*. No manifest needed a
reader that another manifest didn't also need — which is the evidence that the
split is in the right place.

### Which of them are still missing

Measured, not estimated — `nodefusion/tests/test_manifest_vocabulary.py`
compares every name these manifests use against the registry, and pins the
gaps so a typo can't hide among them:

| missing | blocks | note |
|---|---|---|
| *(none)* | — | the table is empty as of 2026-09-07 — see `strongmap` below |

The table being empty is a result, not an oversight: `EXPECTED_MISSING` in
that test is now `{}`, and the test still fails in both directions — an
unrecorded name is a surprise, and a name still listed as missing that the
registry *can* build is a stale to-do.

xv6 and rCore need nothing that is missing — which is what lets them be the
two verified kernels. `alien`, `arceos`, `axvisor` and `starry` now also name
nothing that the registry cannot build.

### Why four of them could be written with no build

The earlier note here said all five had to wait for a binary, on the grounds
that "a reader is a claim about layout". That was too strong, and it was the
thing blocking the cheapest work in the list.

A reader names **fields**; offsets come from `ctx.offset(type, field)`, which
is DWARF at run time. So a wrong field name fails *loudly* — `Unavailable`,
naming the type and field it wanted. It cannot quietly produce a plausible
offset. That is what makes name-based readers safe to write in advance, and
why `Mutex` already shipped three candidate chains.

- **`string`** — measured against rCore's real DWARF, not recalled:
  `String{vec}` → `Vec<u8,Global>{buf, len}` → `RawVec<u8,Global>{cap, ptr}`.
  Note `cap` at +0 and `ptr` at +8: the compiler's order, the reverse of the
  source order, and exactly why nothing here is hardcoded. `alloc` is the same
  crate in all four kernels, so this one shape serves all of them.
- **`lazylock`, `spinrwlock`** — field names read from ArceOS *source*
  (`components/ax-lazyinit`, and the two different `SpinRwLock` definitions in
  `axsync` and `axtask`). Reading a definition off disk is a measurement.

`btreemap` was the fourth, and it took a different route — see below.

`strongmap` was the fifth and last, and it closed on 2026-09-07 **without a
reader being written** — measuring it showed none was needed. The standing
objection was that `StrongMap` comes from the `weak_map` crate, absent from
this checkout, so the map underneath could be a `BTreeMap` or a `HashMap` with
nothing on disk to say which; guessing wrong would not raise, it would read
hash buckets as B-tree nodes and return numbers. Both ends were then measured:

- **source** — `_nfverify/tgoskits`'s Cargo.lock pins weak-map 0.1.2, and that
  version in the cargo registry reads
  `pub type StrongMap<K, V> = alloc::collections::btree_map::BTreeMap<K, V>;`
  — a *type alias*, not a wrapping struct.
- **binary** — the DWARF type recorded in `starry.toml` is
  `SpinLock<BTreeMap<TgidNumber, Arc<Process>>>`. The alias is transparent in
  DWARF, so there is no extra shell to peel.

So starry's relation is spelled with names that already existed:
`spinlock<btreemap<newtype<u32>, arc>>` — the same shape as rcore/alien's
`vec<arc>`. The `containers.strongmap` class still exists with its own tests;
no manifest needs it wired into the registry.

Two shapes turned out to matter enough to record:

- `SpinRwLock` is **one name for two structs**. `axsync` has it flat
  (`{state, metadata, data}`); `axtask` has it as a newtype over
  `BaseSpinRwLock`, which the `lockdep` feature can grow a field in the middle
  of. The two candidate chains disambiguate themselves: the flat one has three
  fields, so the "sole field type" lookup declines to guess, which leaves the
  newtype chain unusable and the flat chain the only one standing.
- `LazyLock` walks `value → __0` and deliberately **stops on the `LazyInit`**
  rather than reaching through to its payload. Reaching through would save a
  manifest layer and skip the `inited` flag — and uninitialised `MaybeUninit`
  bytes always read back looking like data. So `arceos.toml` now names the
  layer: `unwrap = ["LazyLock", "LazyInit", "SpinRwLock"]`.

### `btreemap`: measured, then falsified on purpose

This one is not a name-based reader, so it needed a different argument. The
reader body already existed; what was missing was a `BTreeNodeLayout` and a
decision about what `iter` over a map even yields.

**Measured.** `resolve.btree_opts` reads the whole node layout out of DWARF —
`NodeRef{node, height}`, `LeafNode{len, keys, vals}`, the K/V strides from each
array's element `DW_AT_byte_size`, and `InternalNode.edges` found by rewriting
`LeafNode<` to `InternalNode<` in the type name. Reaching `NodeRef` at all
requires **name surgery**: `BTreeMap.root` is an `Option<NodeRef<…>>`, and an
`Option` enum has an *empty* DWARF member table, so the only way in is to strip
the `Option<…>` off the type name and look the inner type up again.

**Exercised on real memory.** rCore's `MapArea.data_frames` is a real
`BTreeMap<VirtPageNum, FrameTracker>`. Across `rcore-ch6-fs`: **108 maps, 218
key/value pairs, zero failures**, and every one passed the reader's own
`length` cross-check. That check is what makes the number mean something —
`BTreeMap` stores `length` separately from the tree, so walking the tree and
counting gives a genuinely independent second number. A `Vec` has nothing
comparable; its `len` *is* its `len`.

**Then deliberately broken**, because "108 passed" is worthless if the check is
inert. Perturbing each measured field one at a time:

| perturbation | caught? | what happened |
|---|---|---|
| `len` offset −2 | **yes** | `len=25708 > 11`, reported on 90 maps |
| `NodeRef` fields swapped | **yes** | "root is None but length=3" |
| `keys` +8 | **no** | 90 of 108 maps decoded *differently*, silently |
| `vals` −8 | **no** | every value address off by 8, silently |
| `key_size` doubled | **no** | 54 of 108 changed, silently |

So the `length` cross-check catches **structural** errors and misses
**content** errors. Keys went from `[0, 1, 2]` to `[1, 2, 1034]` with nothing
reported. That is the whole justification for making the layout
**all-or-nothing**: `btree_opts` returns `{}` unless every field was measured,
and the registry sets `node=None` unless every key is present. A half-measured
layout walks out real keys paired with fake values and looks fine.

`edges` is the one field allowed to be absent — without it the reader refuses
any node with `height > 0` rather than pretending that subtree is empty.

**What is still unexercised:** every root in this data has `height == 0`. All
108 maps are a single leaf, so the internal-node descent has *never run on real
memory* — dropping `edges` entirely produced byte-identical output. The
multi-level path is covered only by the synthetic tests in
`test_readers_containers.py`.

**The traversal contract.** `iter` wants addresses; `btreemap` yields
`[key, value]` pairs. The old `exec._container` line was

```python
if isinstance(item, int) and self._plausible(item):
```

which drops a pair on the floor and records **nothing** — the screen would show
an empty table for a full map. Now pairs unwrap to the value address, and the
key goes into the step label, so `btreemap[7]` rather than `btreemap[0]`
(AxVisor's `VMId` and ArceOS's task id are the whole point of writing
`key = "u64"` in the manifest). Anything that is neither an address nor an
empty slot is now reported instead of dropped. Instrumenting the old branch
across all eight runs showed it was hit **zero** times, so this is provably
inert for xv6 and rCore — confirmed by all eight renders being byte-identical
before and after.

`via` still cannot build a `btreemap`: it is a single outside-in chain and a map
needs two element readers. The refusal now says that, instead of claiming
`btreemap` is not a container — which would send someone off to implement
something that already exists.

**A latent typo the vocabulary test could not see.** `key` is a reader name,
and `axvisor.toml` had `key = "VMId"` — a *type* name. Nothing caught it,
because `test_manifest_vocabulary.py` only checked `reader =` fields and the
shell chains in `unwrap`/`via`; step *arguments* were skipped wholesale. It now
also checks argument values that name readers, and the first thing it found was
this one. `axvm-types/src/lib.rs:59` says `pub type VMId = usize` — a plain
alias, not a newtype, so the reader is `usize`. Read off disk, not guessed.

**What the cursor becomes.** The quietest of the three gaps was that `plan.py`
had no idea what an `iter` over a map leaves you holding. It left the cursor at
`None`, so the very next `{ field = … }` fell back to runtime resolution — and
at runtime there is an address but no type, so the whole source yields zero
entities and looks exactly like "this kernel doesn't have that table". Both
`arceos.toml` and `axvisor.toml` do `iter = "btreemap"` followed by more steps,
so this would have hit on the first real build of either.

The value's DIE is found by walking `LeafNode.vals` and asking for the array's
element type — *not* by splitting the second generic argument out of
`BTreeMap<K, V, A>`. Those arguments are spelled fully-qualified while `find()`
takes short names, and that mismatch has already cost this project once
(`Once<Arc<TCB>, spin::relax::Spin>`).

That element is not the value. In rCore it is
`MaybeUninit<ManuallyDrop<FrameTracker>>` — **two** wrappers, and `MaybeUninit`
is a *union* whose `uninit` and `value` members both sit at offset 0, so the
usual "one field, so unwrap it" rule does not apply. Peeling uses a **named
allowlist** (`MaybeUninit`, `ManuallyDrop`) rather than "unwrap any single-field
struct", because `FrameTracker` is itself a single-field newtype `{ppn}` — the
general rule would peel straight through it and silently substitute
`PhysPageNum` as the entity type. Addresses would still be right; every field
would then be looked up on the wrong type. Wrapper names are finite and known;
payload names are not.

One thing this could *not* be checked against: a manifest source that reaches a
map through `unwrap = [..., "Arc"]` loses its compile-time cursor, because
unwrapping a shell by name yields only a name and `refcounted_payload_die` needs
a DIE. That is pre-existing and documented in `plan.py`; rCore's manifest never
needs it (it uses `walk`, and entity fields resolve against `entity.type`). It
does mean the plan-side branch is covered by `test_plan_iter_map.py` against a
hand-built DWARF rather than by rCore end-to-end — the reader and the layout
measurement are the parts that got real memory.

## Watches became policy in all seven

Every manifest expressed watches as `{ match, args, throttle }` rather than a
symbol list. `args` is per-watch because `a[8]` is 64 of 104 bytes in every
record — **62%** — and most watches want two arguments. Syscall watches were the
only ones wanting three.

xv6's `vm` watch is the clearest case: `walk`/`walkaddr` hit ~50k times per boot
and are over half the trace volume. The current code excludes them by name in a
hand-written note. Throttling is the right shape because the cost is a **runtime
property**, and it keeps the events instead of discarding the function.

## The one real break

**reL4 bitfields cannot satisfy the falsifiability rule.**
`plus_define_bitfield!` generates accessors that inline away. `cap_t` is
literally `{ words: [usize; 2] }` — DWARF sees two integers. Bit positions
cannot be checked against the binary.

Declared explicitly: `checkable = false` with a stated reason, and the strongest
available fallback marked for what it is —
`validate = { in_set = [...], strength = "smoke_test_only" }`. A smoke test is
not falsification and the manifest says so rather than implying otherwise.

## Still unresolved

- **`[[entity.source.nested]]`** (rCore ch8 threads) is ugly. It is doing an
  entity's job inside a source. Starry solved the same problem with a separate
  entity plus `from`. rCore ch8 should probably do the same; needs a second pass.
- **Starry's nested PID namespaces.** A task can appear in several namespaces
  under different numbers. `total_in_root_ns` defers this rather than solving it.
- **reL4 `tcb_t` is unverified.** Its git dependencies are not fetched in this
  checkout, so every field path in `rel4.toml` is a source-read guess.
- **`detect` may be ambiguous.** Starry and AxVisor both carry ArceOS types.
  Ordering, or more specific predicates, needed.
- **B-tree internal nodes have never been walked on real memory.** Every
  `BTreeMap` reachable in the rCore runs is a single leaf. ArceOS and AxVisor
  iterate maps that are likely deeper; the first real build of either is what
  will actually exercise that path. (Still true after the ArceOS build below:
  that build's maps are reachable in DWARF but not yet in a trace.)

## The ArceOS build: what a second kernel actually changed

**This section is measured, not read.** Built
`tg-arceos-tutorial/app-childtask` for riscv64 on 2026-08-31 — axtask
0.3.0-preview.1, rustc nightly-2025-12-12, DWARF v4, 161 CUs. First
independent toolchain the project has seen.

(Practical note: `--release` strips debug info completely. 481 KB with no
`.debug_*` at all. `CARGO_PROFILE_RELEASE_DEBUG=2` gives 6.5 MB with DWARF,
and needs no edit to the tutorial repo.)

### The split that predicts which claims survive

Every claim in `arceos.toml` that came from **struct definitions** was right.
Every claim that needed the **symbol table** was wrong. That line is sharp
enough to plan around.

Right: all five field paths, their types and readers; the `TaskState` variants
(`Running=1 Ready=2 Blocked=3 Exited=4`); all three `optional_fields` being
absent, which is correct rather than a miss — this build sets none of
`smp`/`preempt`/`task-ext`.

Wrong, systematically:

| claim | reality |
|---|---|
| `ax_task` / `ax_mm` / `ax_alloc` | `axtask` / `axmm` / `axalloc` — all three watch modules matched **zero** functions (real: 33 / 10 / 8) |
| `ax_task::api::TASK_REGISTRY` | does not exist; api.rs:37 is `pub type AxCpuMask` |
| `completeness = "total"` on it | ArceOS has **no** global task registry — no global of `BTreeMap` type exists in the build at all |

A source-reading pass cannot check a symbol name, and no amount of review
catches `ax_task` — it reads like a crate path. Nothing short of a build finds
these.

**That table is scoped to this binary, and reading it unscoped will break
`starry.toml`.** Checked afterwards, from both lockfiles:

| build | package | symbol path |
|---|---|---|
| `tg-arceos-tutorial/app-childtask` | `axtask` 0.3.0-preview.1 | `axtask::…` |
| `_nfverify/tgoskits` (Starry) | `ax-task` 0.6.11 | `ax_task::…` |

Cargo turns `-` into `_` in a crate path, so `ax-task` really is `ax_task` in a
symbol. The ArceOS ecosystem renamed its crates somewhere between 0.3 and
0.6/0.8 — `ax-alloc` is 0.8.16 and `ax-mm` is 0.6.0 in the same lockfile. So
`axtask` and `ax_task` are **both right**, each in its own binary, and
`starry.toml`'s three `ax_task::` references are correct as written. They were
suspected of being the same stale typo and are not.

The trap is the shape of the correction, not the correction. "`ax_task` is
wrong, real is `axtask`" was measured, is true, and is useless without the
binary it was measured on attached to it. A finding recorded as a fact about a
*name* travels to other manifests; the same finding recorded as a fact about a
*build* does not. This is the `__rustc` two-true-names case again, one level up:
there, two names for one function; here, two names for one crate, and the
tiebreaker is which binary is being decoded.

`builds_on = "arceos"` survives this intact, which is worth noting — Starry
shares ArceOS's *structure* (the `TaskInner` shape, the same field layout) while
disagreeing about every crate *name*. That is precisely the split the family
mechanism assumes, and the reason each kernel still needs its own manifest
rather than inheriting paths from its base.

### The B-tree layout is not portable, which is the point

`btreemap` was measured on rCore last session. Measuring it again here, on a
different rustc with different key/value types, gives a **different layout** —
the fields are reordered, not merely shifted:

| | rCore `<VirtPageNum, FrameTracker>` K=8 V=8 | ArceOS `<TimerKey, Waker>` K=24 V=16 |
|---|---|---|
| `parent` | **0** | **176** |
| `keys` | **8** | **184** |
| `vals` | **96** | **0** |
| `parent_idx` | 184 | 448 |
| `len` | 186 | 450 |
| node size | 192 | 456 |

`B = 6` in both (11 keys, 12 edges) — that is the const generic, and it is the
only thing that stayed put.

This is the strongest evidence so far that measuring beats hardcoding. Anyone
who wrote down rCore's `keys:8, vals:96` — the obvious thing to do after
reading one kernel — would read ArceOS's timer wheel as garbage. Per the
negative-control table above, `keys` being wrong is in the category the
`length` cross-check **does not catch**.

The plan-side path is now exercised for real too: compiling
`{ iter = "btreemap" }` against this DWARF fills all nine `btree_*` arguments
with the ArceOS values and leaves the cursor on `Waker`, the value type. That
was synthetic-only before.

### Three engine bugs the build found

1. **`_static_addr` fabricated addresses.** It read every byte after
   `DW_OP_addr` as part of the address, despite a docstring promising the
   opposite. Three ArceOS percpu variables are emitted as
   `DW_OP_addr <n>; DW_OP_plus_uconst <k>`, and came back as
   `0x28230000000000000000` where the truth was `0x28`. Nothing downstream
   would have caught it — an address is just an integer. Fixed; xv6 and rCore
   use plain `DW_OP_addr` throughout, so all 8 runs render byte-identical.

2. **`percpu` steps had no type.** The step forwarded a name and nothing else,
   so every step after one was "type unknown" and `descend_to` — which can
   only be resolved at compile time — always failed. Invisible on xv6 and
   rCore, which reach tasks through globals; fatal on ArceOS, where per-CPU is
   the *only* route. Also now resolves the `NAME` / `__PERCPU_NAME` pair that
   `percpu::def_percpu` emits.

3. **`unwrap` dropped the DIE whenever the name peeled.** For
   `LazyInit<Arc<FifoTask<TaskInner>>>` that breaks in two steps: `LazyInit`
   peels by name and drops the DIE, then `Arc` *cannot* peel by name (two
   generic args) and needs the DIE it no longer has. The failure surfaced
   later, as `descend_to` reporting "type unknown" — a break reported nowhere
   near where it happened.

With those, the ArceOS idle-task source compiles end to end:
`percpu → LazyInit → Arc → descend_to TaskInner (+0) → id (+24)`.

### One toolchain change, three broken readers

Rust split `RawVec` since rCore's build:

```
OLD  RawVec<T>     { ptr: Unique<T>, cap, alloc }
NEW  RawVec<T, A>  { inner: RawVecInner<A>, _marker: PhantomData<T> }
     RawVecInner<A>{ cap: UsizeNoHighBit @0, ptr: Unique<u8> @8, alloc @16 }
```

`vec`, `vecdeque` and `string` all check for `ptr`+`cap` directly on `RawVec`,
so all three refuse to build on this toolchain. They refuse *loudly*, which is
the correct failure — but they refuse, and that is why ArceOS cannot read a
task **name** today.

Two distinct problems hide in there, and conflating them would cause a silent
error rather than a loud one. Where `ptr`/`cap` live is a relocation, fixable
by measuring. What the element type *is* is not: `ptr` is now `Unique<u8>`,
genuinely type-erased, so chasing the pointer can no longer recover `T` on any
build with this shape. Tracked as its own task.

### What ArceOS still cannot reach, and why each is different

- **Ready tasks** — `FifoScheduler{ready_queue: List<Arc<FifoTask<T>>>}` is an
  intrusive linked list; there is no `list` reader. The walk down to it is
  verified (`field scheduler` → +8).
- **Exited tasks** and the **`name`** field — split `RawVec`, above.
- **Current task** — `axhal::percpu::CURRENT_TASK_PTR` is typed `usize`. The
  type is erased *in the source*, not by the debug info, so no amount of DWARF
  work recovers it. This one needs the manifest to assert a type, which is a
  mechanism the vocabulary does not have.

Worth separating: the first two are missing readers, the third is a missing
*vocabulary* feature. Only the third would change the schema.

### A side note on `{ iter = "list" }`

It compiles. `plan.py` does not check container names against the reader
registry, so an unimplemented container produces a plan that fails at exec —
and "compiled, zero nodes" looks exactly like an empty table. Compile-time
rejection is probably right; noted with the `list` task.

## Machine-checked inventory

All seven parse with stdlib `tomllib` (Python 3.11+), so the format costs no
dependency.

```
alien     entities=1 sources=1 watches=2 bitfields=0
arceos    entities=1 sources=2 watches=3 bitfields=0
axvisor   entities=2 sources=2 watches=2 bitfields=0
rcore     entities=1 sources=5 watches=4 bitfields=0
rel4      entities=1 sources=2 watches=2 bitfields=1
starry    entities=2 sources=2 watches=2 bitfields=0
xv6       entities=1 sources=1 watches=3 bitfields=0

steps used:   unwrap 15, static 12, field 11, iter 9, walk 4,
              descend_to 3, from 2, percpu 1, deref 1
completeness: total 7, reachable_only 3, partial 2, none 1,
              ready_only 1, total_in_root_ns 1
readers:      29 distinct
```

Two things fall out:

- **`index` was proposed and never used.** Every indexed access turned out to be
  `iter` over an array or a `field` lookup. Drop it.
- **29 readers against 7 proposed.** The step vocabulary was roughly right and
  needed 3 additions; the reader vocabulary was off by 4×. This is the expected
  direction — readers are the open-ended half — but it means the reader
  interface must be trivial to add to, and reader count is a bad proxy for
  progress.

## TOML inline tables cannot span lines

Five of the seven files failed to parse on the first attempt, all with the same
error. TOML forbids newlines inside `{ ... }`, so a nested predicate like

```toml
when = { field_type = { type = "TaskManagerInner", field = "tasks", starts_with = "Vec<" } }
```

must sit on one line. Every such line is now 90–110 characters.

Tolerable at this nesting depth, and not worth changing format over. But if
predicates grow another level, switch those specific constructs to
`[[entity.source.when]]` table syntax rather than fighting the line length.
Worth knowing before the schema is fixed.

## What was NOT needed

Worth recording, so it does not get re-invented:

- No expression language. `when` predicates are three fixed forms
  (`type_exists`, `field_exists`, `field_type … starts_with`) and that covered
  all five rCore shapes.
- No new step for two-stage memory.
- No arch-specific steps. Architecture affects the *readers* (PTE format) and
  the address-space root register, not the traversal vocabulary.

## The list reader: a parameter that cannot be measured

**Measured**, ArceOS build of 2026-08-31, on 2026-09-01.

The ready queue was the last engine gap in `arceos.toml`. Writing it turned up
one genuinely new category and three bugs of a kind this document keeps
finding.

### Termination is a convention, not a layout

Three intrusive-list shapes exist, and **all three are the same bytes**: one
pointer slot per element, holding either 0 or an address. Nothing in DWARF
distinguishes them.

  * `NullTerminated` — head in an external slot, chain stops at 0.
  * `Circular` — the head address *is* a sentinel link; stop on return to it.
  * `CircularHeaded` — head in an external slot, but the ring closes back on
    the **first element**, not on the head.

ArceOS is the third, which existed in neither. Ground truth came from the crate,
not from the shape: `linked_list_r4l-0.3.0/src/raw_list.rs:312` stops when
`next == head`, and `push_back_internal` makes an empty-list insert
self-referential (`next = prev = new_ptr`).

The asymmetry is what forced the design. Reading a circular-headed ring as
null-terminated does not fail — it wraps past the end, returns to the first
element, trips cycle detection, and reports *"this list is corrupt"*. That is a
**false accusation against a healthy kernel**, which is worse than a refusal: a
refusal sends a student to the tool, an accusation sends them to debug code that
was never broken. So `terminator` has no default. `list` refuses to build
without it, and says why.

This is the first parameter in the vocabulary that is knowledge NodeFusion
cannot in principle recover. The line still holds — the manifest states
*arrangement* (which field is the link, which is `next`, how the chain ends),
NodeFusion measures *encoding* (every offset) — but arrangement now includes a
convention, not just names.

### `Option<NonNull<T>>` has no member table

The element type hides in `RawList.head: Option<NonNull<FifoTask<T>>>`. Under
niche optimisation that is 8 bytes, and rustc emits it as an **enum with no
members** — there is no field to follow. Name-peeling is the only route, the
same one `BTreeMap.root: Option<NodeRef>` already needed.

Peeling stops at the first unrecognised wrapper rather than running to the
innermost type. "Peel until nothing is left" would turn `Option<u32>` into a
perfectly good "element type" and walk a list of integers.

### Three bugs, one shape

All three were silent-wrong, not loud-wrong:

  * **`(None, 0)` is not a failure.** `_walk_fields` returned a zero offset when
    the walk failed, and the caller tested the offset. A failed walk therefore
    emitted `list_next_off = 0` — a half-offset that reads inside the same
    object, never faults, and yields plausible garbage. The function's own
    docstring said it must not do this. Failure now returns `None`.
  * **`provides = [...]` was never read by anything.** It sat in `arceos.toml`
    across two revisions looking like schema. `[[entity.source]]` had no
    unknown-key check — the one place in the manifest loader that didn't. Same
    for step arguments, whose allow-list lived only inside a test, where the
    engine could not enforce it. Both now reject unknown keys. The information
    moved to `reason`, which the UI actually shows.
  * **584/576 was never true.** The size and link offset recorded for `FifoTask`
    in notes, in `arceos.toml`'s header, and in a test docstring were wrong; the
    build says 280 and 256. Nothing consumed those numbers — every offset is
    measured — so nothing broke. But it is the `ax_task` / `axtask` mistake
    again in a new place: **prose about a binary drifts, and only the binary is
    checked.** Numbers now come from `list_opts`, and the docstring says so.

### Zero-sized fields are not payloads

`BaseSpinLock<G, T>{_phantom: PhantomData<G>, data: UnsafeCell<T>}` broke the
unwrap chain: two generic arguments (so the name cannot be peeled — taking the
first would yield `NoOp`) and two fields (so "sole field" did not apply). The
cursor lost its type and every later step reported "type unknown".

`PhantomData` is zero-sized, so it cannot be what a shell wraps — reading it
yields no bytes. Selecting the sole field that *occupies bytes* is elimination,
not choice, and it is measured (`DW_AT_byte_size`). This is the same lesson as
the split `RawVec`: when the name cannot disambiguate, the field table can.

## Watch selection: DWARF alone cannot see the code

Every kernel had its own hand-written watch table in `host/watchlist.py`
(`DEFAULT_WATCH`, 71 xv6 names; `RCORE_WATCH`, 103 rCore names), registered in
`_TABLES`. Adding a kernel meant editing code. Meanwhile all seven manifests
already carried `[[watch]]` rules — and nothing read them.

Replacing names with rules turned up four things, each with the same symptom:
**a subsystem that looks like it never ran.** That is indistinguishable from a
kernel that genuinely never called it, which is why none of these were noticed
before they were measured.

### The symbol table and DWARF each hold half the facts — again

`symbols.py` opens with this discovery for *variables*: rCore's `lazy_static!`
values have no `DW_TAG_variable`, so DWARF knows types but not these names,
while the symbol table knows names and addresses but not types.

Functions have the same split, in the same build. `MemorySet::from_elf` has
exactly one DWARF entry, a `DW_AT_declaration` stub with no address:

    name='from_elf' low_pc=None attrs=[linkage_name, name, decl_file,
                                       decl_line, type, declaration]

and it is plainly there in the symbol table:

    _ZN2os2mm10memory_set9MemorySet8from_elf17h0e4bf92a766ebb69E  0x802045bc

That ELF has **10150 `DW_TAG_subprogram` DIEs and only 1198 with `low_pc`**
(none use `DW_AT_ranges` — the rest are inlined-out abstract roots and
declarations). Selecting from DWARF alone lost every `Type::method` in `os::mm`
and `easy_fs` — 33 functions the old table found.

Watchpoints need addresses, so the symbol table has to be the primary source;
DWARF supplies `DW_AT_decl_file`, which is the only attribution a C kernel has
(`kalloc` carries no module in its name). They merge on **address** — the one
key both derive from the same binary. Merging on names would invent
disagreements, since one side says `from_elf` and the other says
`_ZN2os2mm...E`.

### One address, several true names

  * **Trait impls.** `OSInode::read` demangles to
    `<os::fs::inode::OSInode as os::fs::File>::read`. The leading `<` defeats
    every prefix match, so `module = "os::fs"` misses a function inside
    `os::fs`. Attribution follows the *self type*, not the trait: `OSInode`
    belongs to `os::fs` whether it implements `File` or `easy_fs`'s
    `BlockDevice`. Normalising once, at candidate-build time, keeps matching,
    naming and display in agreement.
  * **`#[no_mangle]`.** DWARF records the source name (`panic` in
    `lang_items.rs`), the symbol table records the ABI name
    (`rust_begin_unwind`). Both are true for that address.
  * **ICF.** The linker folds identical machine code, so
    `__rust_alloc_error_handler` and `handle_alloc_error` share one address.
    Whichever symbol is seen last wins the path, and rules written against the
    other name stop matching — for reasons that depend on symbol table order.

So a candidate carries aliases, and they are recorded in *both* merge
directions. Keeping only the winner was wrong twice over.

### Mapping symbols are not functions

`__switch` is written in assembly and is `STT_NOTYPE`, not `STT_FUNC`, so the
symbol filter has to admit NOTYPE — which also admits `$x.0`, the RISC-V
mapping symbol marking "this range is code". One sits at the same address as
`__rust_alloc_error_handler` and stole its path; worse, `$x.N` occurs hundreds
of times, so the names collided and real functions were discarded as duplicates.
They are excluded by name, because by type they are indistinguishable from the
assembly entry points that must be kept.

### Colliding names must be qualified, not dropped

`Inode::find` and any other `find` share a bare name. The first version dropped
the later one, so which function went unobserved depended on traversal order.
Names are a display problem; they must not be paid for with coverage. Collisions
now walk up the path (`Inode::find`) — which is how the hand-written tables spell
them anyway.

Note the neighbouring case that *is* a genuine merge: several symbols folded by
ICF onto one address are one function, and address dedup already handles it.
Identical paths at *different* addresses are separate monomorphisations with
separate machine code, and `watchlist.build()` has always attached all of them
— "attaching one would miss the other two's calls, and missing them is
invisible."

### Result: rules are a superset, on both kernels

    rCore   table 103 names -> 59 watchpoints;  rules 8 -> 92.  All 59 covered.
    xv6     table  71 names -> 72 watchpoints;  rules 11 -> 143. All 72 covered.

Snapshot flags match one for one, which needed `snapshot = "always" | "event"`
in the manifest: `SNAP_ON` and `EVENT_SNAP_ON` were two more per-kernel sets in
code. Order matters and is documented in the manifests — a broad rule placed
first claims the function with `snapshot = "none"`, leaving a full watch list
that captures no fork, exec or panic state at all.

`tools/crosscheck_watchsel.py` compares the two selectors on a real ELF and
reports both directions plus snapshot flags. Divergence is the finding, not a
bug to paper over: every gap it exposed was a **missing manifest declaration**
(rCore never declared `os::trap` or `os::drivers`; xv6 declared 3 files out of
~8), and all of them were closed in the manifests without touching code.

### Two corrections to earlier notes here

  * `RCORE_WATCH` resolves **59 of 103** names against the real ELF, not 3. The
    first count matched bare DWARF names and ignored `_match_suffix`, which
    resolves demangled path tails — the check was wrong, not the table.
  * All seven recorded rCore runs show `entries=0 missing=73`, and 73 is the
    *xv6* list length. They were recorded before `_TABLES` existed, when `kind`
    fell back to xv6. The `ValueError` guard in `build()` already prevents this;
    the runs are history, not a live defect. But it does mean `RCORE_WATCH` was
    never exercised by any recording — it was verified here for the first time.

## A superset by address is not a superset by event

The crosscheck said the rules were a strict superset of the hand table: every
address present, every snapshot flag identical, xv6 143 against 72 and rCore 92
against 59. All of that was true and none of it was sufficient.

`throttle` had been written on the broad rules — 128 on all of `kernel/vm.c`,
16 on `fs.c`/`bio.c`/`log.c` and `virtio_disk.c`, 64 on `os::mm`, 16 on
`os::fs`/`easy_fs`. Under those rules **34 xv6 and 28 rCore functions that the
table watched unthrottled came back thinned**, including:

    copyout  copyin  mappages  uvmalloc  uvmunmap  bread  namei
    PageTable::map  MemorySet::push  Inode::read_at  VirtIOBlock::read_block

which is a fair description of what the COW, filesystem and memory chapters are
*about*.

The reason this survived review is worth stating plainly. Every one of those
functions is still selected, still flagged for snapshots, still in
`watchlist.json`. Diff the two watchpoint lists and they agree. The loss only
appears downstream, in a report, as the lab's own operation happening eight
times — and "happened 8 times" and "happened 1024 times, 1016 of them dropped"
render identically.

The mistake was putting a runtime property on a source-layout key. How often a
function is called is a property of **that function**. `kernel/vm.c` holds both
`walk`, which fires around 50k times a boot and says nothing, and `copyout`,
which is the observation. A rule keyed on the file cannot tell them apart, and
picking a throttle for the file means picking wrong for one of them.

So throttles now sit on named rules ahead of the broad ones — `walk`/`walkaddr`,
`find_pte`/`find_pte_create`/`translate`, `get_block_cache` and friends — and
every file- and module-scoped rule is throttle 0. `crosscheck_watchsel` gained
the rate axis, and a test asserts no table watchpoint comes back throttled.

### What the delta actually consists of

Measured, not estimated. Booting the teacher xv6 to an idle shell under the
plugin, no workload, ~8.6 billion instructions, memory snapshots off:

| | watchpoints | hits | thinned | trace |
|---|---|---|---|---|
| table | 72 | 37,004 | 0 | 6.61 MB |
| rules, first attempt | 143 | 773,339 | 179,149,624 | 95.4 MB |
| rules, after `skip` | 141 | 70,509 | 50,831 | 10.65 MB |

Normalised for the small difference in instruction counts, the shipped rules
cost **1.6x the table for roughly double the coverage**.

The first attempt is the interesting row. Two functions produce 99.9% of every
watchpoint hit in the run:

    cpuid   351,176 recorded x256 = 89,901,056
    mycpu   351,173 recorded x256 = 89,900,288
    kfree    32,184 recorded          32,184     <- the next busiest

`mycpu` and `cpuid` are what `push_off`/`pop_off` call, so every `acquire()` and
every `release()` in the kernel goes through both. What they return is a hart
number and a pointer into a fixed-size array. There is no workload here at all —
this is the shell sitting at a prompt.

Throttling does not rescue that. At 1-in-256 the pair still contributes 702k
events against 37k for the entire hand table, and every one of those events is
a hart number. So `[[watch]]` grew a `skip = true`, and the two are excluded
outright.

`skip` and `throttle` answer different questions and should not be collapsed:
throttle means *useful but too dense*, skip means *not useful*. Thinning noise
leaves noise.

#### Correcting the earlier estimate on this page

An earlier revision of this section ranked the extras by static call sites and
concluded that `myproc` (41) led, with `argint` (17) and `mycpu` (12) behind.
The measurement says otherwise: `myproc` does not appear in the top fourteen at
all, and `mycpu`/`cpuid` — 12 and 9 static call sites — are essentially the
entire cost.

Static call sites count *places that can call*, and every one of them counts the
same. `mycpu` has twelve callers, but two of them are the lock primitives, which
run in every loop in the kernel. Frequency is not a property of the call graph's
shape.

The static numbers were labelled at the time as an upper bound on distinct call
paths rather than a rate, which was accurate, but they were still used to pick
which functions to throttle. That part was guesswork, and it picked wrong.

### A second workload: cowtest

The idle shell has no fork traffic, which is exactly where the extras were
expected to be most expensive. Repeating the measurement under `cowtest` — the
lab's own copy-on-write test, driven to its `cowtest passed` line and stopped
there on both runs:

| | watchpoints | instructions | hits | thinned | trace | per 10⁹ insns |
|---|---|---|---|---|---|---|
| table | 72 | 13.66 G | 348,062 | 0 | 51.99 MB | 3.81 MB |
| rules | 141 | 13.48 G | 614,095 | 435,394 | 83.87 MB | 6.22 MB |

**1.63x the bytes, 1.79x the hits**, against 1.6x on the idle shell. The ratio
is stable across two workloads that share almost nothing, which is a better
result than either number alone: the extras are not concentrated in one kind of
work.

What the extra bytes buy, ranked by hits among watchpoints the table did not
have:

    kref_dec_internal  108,815      page refcount drop
    kref_init_cnt       38,588      refcount init
    kref_inc            38,250      refcount bump
    vmfault             38,243      the COW fault handler
    ismapped            38,243
    walk                 2,180  x128
    myproc                 466  x256

`vmfault` is the function the lab exists to write, and the hand table did not
watch it. Neither did it watch any part of the page refcount lifecycle, so on a
cowtest recording the table can show that pages were freed but not that a
refcount reached zero — the two are the same event only when the assignment is
already correct. This is the delta paying for itself on the workload it was
most likely to fail on.

### Why the default has not moved

`--watch-from-manifest` is opt-in. Both kernels are now measured:

| kernel | workload | watchpoints | cost |
|---|---|---|---|
| xv6 | idle shell | 72 → 141 | 1.6x |
| xv6 | cowtest | 72 → 141 | 1.63x |
| rCore | boot | 59 → 92 | 1.01x |

An earlier revision of this section said rCore could not be measured without
rebuilding, because `build_kernel()` unlinks the ELF and runs `make clean`
before every run. That is true of the recorder but not of the measurement: the
existing build artifacts can be driven directly, which is how every row above
was produced.

Nothing measured argues against flipping the default. The remaining reason to
leave it is that the rules have twice been wrong in the same way on first
contact with a kernel — `mycpu`/`cpuid` on xv6, `current_trap_cx`/
`current_user_token` on rCore — and both times a boot-length measurement found
it in minutes. Every kernel in the target list still wants that one run before
its rules are trusted by default, and five of the seven have not had it.

That is an argument for measuring the rest, not for keeping the flag forever.

### rCore, measured — and the same accessor problem again

rCore never needed a rebuild after all. Every archived rCore run is
`program='(boot-to-exit)'`: no user program is fed, the kernel runs to its own
end. So the measurement is a boot, against the prebuilt `os.bin` and a *copy* of
`fs.img`, touching neither.

Both runs stop at the same guest instruction — 80 million, just past the
76,425,906 that `rcore-ch6-fs` recorded — so the totals compare with no
normalisation at all:

| | watchpoints | instructions | hits | thinned | trace |
|---|---|---|---|---|---|
| table | 59 | 80,000,013 | 602,553 | 0 | 93.20 MB |
| rules, first attempt | 94 | 80,000,006 | 955,660 | 2,373 | 135.51 MB |
| rules, after `skip` | 92 | 80,000,001 | 612,822 | 2,373 | 94.43 MB |

**1.01x for 56% more coverage.** The first attempt cost 1.45x, and two functions
were 97% of the difference:

    current_trap_cx     226,884      = 2 x the run's 118,235 traps
    current_user_token  117,580      = 1 x

Both live in `os::task` and were swept up by `module = "os::task"`.
`current_user_token` reads `satp`; `current_trap_cx` returns a pointer into the
current task. Neither describes a state change — the trap path calls them once
on the way in and once on the way out.

This is xv6's `mycpu`/`cpuid` a second time, in a different language, found by
the same method and fixed by the same rule. That is the useful part: `skip` was
added for one kernel and turned out to be needed by the next one measured, which
suggests the failure is structural rather than a quirk of xv6. Broad rules match
by *where code lives*, and every kernel keeps its hot accessors next to the
subsystem they serve.

What the remaining 1% buys, in full — 10,455 hits across the whole run:

    Stdin::readable  4,103   Stdout::write     2,054   read              2,049
    virt_to_phys     1,536   DiskInode::read_at  500   get_block_cache      96
    name                36   VirtIOBlk::read_block 32  get_block_id         32
    __rust_realloc        5   kstack_alloc          2   kernel_token          2

Console and block-device paths the table had no watchpoint on.

#### Bounding a run by instruction count

Stopping both runs at the same instruction needed a new plugin option,
`maxinsn=N`, because neither obvious alternative works.

Wall-clock does not: the run with more watchpoints is slower, so equal seconds
means unequal instructions, and the two are no longer measuring the same
execution.

Console output does not either, and this cost the most time to find. QEMU's
console is buffered whether it goes to redirected stdout *or* to
`-serial file:`, so the `Panicked at` line that ends an rCore boot does not
reach the file until the process exits. A loop polling for it never sees it.
Two runs were lost that way, at 2.0 and 3.5 billion instructions and 3.6 GB of
trace, almost all of it the post-panic `0xFF` storm rather than the kernel.

The instruction count is the plugin's own, so it has neither problem. On
reaching the bound the plugin finalises normally — END record, statistics — and
`nf_write_rec` then short-circuits on `nf.out == NULL`, which also stops every
other callback path without each having to check.

### Two things learned about rebuilding, while avoiding it

Both came out of preparing the cowtest runs, and both outlive that errand.

**A teacher-xv6 rebuild is address-stable.** Rebuilding the kernel from a clean
copy of the tree produced a different file (`e8fdc64b…` against `c6b612c6…`)
whose 322 symbols sit at byte-identical addresses; the difference is DWARF build
paths. The fear that recording again would strand archived traces does not
apply to this kernel. It is not a general licence — it says nothing about rCore,
where the build already deviates from the default in ways this file records
elsewhere — but for xv6 it is measured rather than assumed.

**The teacher tree cannot be fully rebuilt on this host.** `mkfs/mkfs.c`
includes `kernel/fs.h`, which declares

    char name[DIRSIZ] __attribute__((nonstring));

and the Makefile builds `mkfs` with `gcc -Werror`, where `gcc` is Apple clang 16
and rejects the attribute. The kernel itself builds fine — that goes through
`riscv64-unknown-elf-gcc`. Only the filesystem image is unbuildable.

That matters more than it looks, because `build_kernel()` runs `make clean`
first, and `make clean` deletes `fs.img`. On macOS the recorder therefore
destroys an artifact it cannot regenerate, and the failure lands *after* the
deletion. This was hit once here; the file was restored from a backup taken
beforehand and verified by hash. There is no recovery path without one.

### ArceOS: the third kernel, and the table path does not exist for it

The two measurements above compare a hand table against manifest rules. ArceOS
has no hand table to compare against. `watchlist._TABLES` has exactly two
entries, `xv6` and `rcore`; asking `build()` for anything else raises

    ValueError: 没有名为 'arceos' 的 watch 名单，已知的有：xv6/rcore

So for five of the seven target kernels, `--watch-from-manifest` is not an
optimisation over the table — it is the only way to select watchpoints at all.
That reframes the flag. The question is no longer "is the manifest path good
enough to become the default"; for most of the target list there is nothing
else, and the flag is the difference between recording and not recording.

Measured statically against the real build (`app-childtask`, riscv64, 6.5 MB,
1027 DWARF functions all with `low_pc`), selection went from 13 watchpoints to
20 after three defects were fixed. No run was made, so **there is no cost ratio
for this row** — the xv6 and rCore numbers come from paired traces and this one
would be fabricated. What follows is a static result and nothing more.

**The rules were wrong on first contact for the third time in a row.** xv6 was
`mycpu`/`cpuid`; rCore was `current_trap_cx`/`current_user_token`; ArceOS is
three separate holes:

| defect | what was missing | why the rules could not see it |
|---|---|---|
| no panic watchpoint | `rust_begin_unwind` | the manifest had three rules, all subsystem modules |
| no trap coverage | `riscv_trap_handler`, `handle_page_fault`, `init_trap` | they are in `axcpu`, not `axhal` |
| `fmt` selected | — | `module = "axmm"` matched a Debug impl |

The `fmt` case is the accessor problem again in a new costume. A `module` rule
matches on *where code lives*, and every crate keeps its `impl Debug` beside the
type it prints, so no location rule can exclude it. `skip` handles it, the same
axis that handles the per-trap accessors in rcore.toml. Four more `fmt` sit in
axcpu, axalloc and axtask and would have been swept in as those modules gained
rules — the fix was worth more than the one watchpoint it reclaimed.

### The demangler only read half the Rust kernels

The two Rust kernels in the tree split cleanly by symbol mangling scheme:

| kernel | legacy `_ZN` | v0 `_R` | demangled |
|---|---|---|---|
| rCore | 328 | 0 | 328 |
| ArceOS | 0 | 400 | **0** |

`demangle` understood only the legacy scheme, so on ArceOS the symbol-table half
of the DWARF/symbol merge contributed nothing. Its own docstring said "目前这几个
内核都还是旧版修饰", which stopped being true when the target list grew rather
than when any code changed.

The damage was narrower than that sounds, because DWARF happens to cover
1027/1027 ArceOS functions with a `low_pc`, so only 11 candidates fell back to a
raw `_R` path. But those 11 are precisely the functions DWARF cannot describe —
hand-written assembly — and one of them is `axcpu::riscv::context::
context_switch`, the pivot of every task switch. Ten of the other eleven are
generic monomorphisations from `alloc::collections::btree` that nobody would
watch. The useful fraction of a small number was most of the value.

**The oracle was inside the binary.** 246 addresses in the ArceOS ELF carry both
a DWARF path and a v0 symbol, which is a labelled corpus for free. The parser
accepts 63 of them and declines 183, and every acceptance matches DWARF
verbatim. It decodes only plain paths and bails on generics, backrefs, impl
paths and punycode — declining is the design, because a raw symbol name is
visibly undecoded whereas a plausible-looking wrong path would silently file a
function under the wrong subsystem.

Six of the 63 disagreed at first and were not parse errors. v0 files
`#[rustc_std_internal_symbol]` functions under a synthetic crate `__rustc`:

    DWARF   axalloc::default_impl::_::__rust_alloc
    symbol  __rustc::__rust_alloc

Both names are true, but only the DWARF one says which crate the code lives in.
`candidates()` preferred the symbol path on the general rule that it is more
specific — which held for legacy mangling and fails here, because `__rustc` is
not a crate anyone wrote. Left alone it would have moved four watchpoints into a
fake crate and made `module = "axalloc"` stop matching functions that are
plainly in axalloc. Synthetic paths are now kept as aliases only.

One rule needed no change at all: `fn = ["yield*"]` had always been correct, and
`axtask::api::yield_now` appeared the moment the demangler could read its name.
A rule that looks wrong and a rule that cannot be evaluated look identical from
the outside — both report an empty subsystem.

### Assembler local labels were becoming watchpoint names

`_is_mapping_symbol` filtered `$x`-style mapping symbols. It did not filter
`.L`-style assembler local labels, and on the ArceOS build `.L0 ` won the
address that `__rust_alloc_error_handler` also occupies, demoting the real name
to an alias. The panic rule's first selection was therefore a watchpoint named
`.L0`.

Its docstring had anticipated exactly this collision, and named this exact
function as the example — but only for `$`. The symptom differs from the
mapping-symbol one and is quieter. A mapping symbol makes the watchpoint
*disappear*, because `$x.N` recurs hundreds of times and the name collision
logic discards the duplicate. A local label leaves the watchpoint in place with
the correct address and only the name wrong, so nothing downstream ever
complains and the trace simply contains a point that cannot be identified.

### ArceOS, run: the rules are right, and they see 17% of the boot

Static selection proves an address resolves. It cannot prove the function is
ever reached, and a watchpoint that never fires looks exactly like one whose
address is wrong. So the 20 selected points were run against a real boot of
`app-childtask` — QEMU command taken from the tutorial's own xtask, the flat
`.bin` from objcopy because the ELF's `p_paddr` is the virtual
`0xffffffc080200000` and QEMU cannot load it.

Boot to shutdown is 67,517,561 instructions. 13 hits recorded, 49 more dropped
by throttling. The selection is sound:

| instruction | watchpoint |
|---|---|
| 10,769,216 | `init_trap` |
| 10,904,112 | `global_init` |
| 11,015,041 | `init_memory_management` |
| 11,019,267 | `new_kernel_aspace` |
| 11,021,248 | `map` |
| 11,025,195 | `__rust_alloc` |
| 67,418,695 | `__rust_dealloc` |
| 67,497,711 | `spawn_task` |
| 67,498,926 / 67,499,614 / 67,510,025 | `context_switch` ×3 |
| 67,505,429 / 67,511,354 | `exit` ×2 |

`spawn_task`, `context_switch` and `exit` all fire, which is the answer to the
question the run was for. Ten points never fired, and none of them is an error:
`panic`, `handle_alloc_error` and `__rust_alloc_error_handler` want a crash that
did not happen; `yield_now` wants a workload that yields rather than joins;
`unmap` wants something to be unmapped. Absent because the workload did not do
it is a different thing from absent because the address is wrong, and one run
separates them.

**The real result is the hole in the middle.** Between 11,025,195 and
67,418,695 there is not one watch hit — 56.4M instructions, 83% of the boot,
with 82% of all samples in it. That window is the `axmm` page-table build, the
451 ms gap visible in the console between `Initialize virtual memory
management` and `Initialize platform devices`. Resolving the sampled PCs:

| share | where |
|---|---|
| 39.8% | `page_table_multiarch::bits64::PageTable64Cursor::map` |
| 24.7% | `axplat_riscv64_qemu_virt::mem::phys_to_virt` |
| 14.3% | `page_table_entry::arch::riscv::new_page` |
| 11.1% | `PageTable64Cursor::map_region` |
| 7.9% | `page_table_entry::arch::riscv::is_huge` |

Not one of those is in `axtask`, `axmm`, `axalloc` or `axcpu`. They are in
`page_table_multiarch`, `page_table_entry`, `axplat_riscv64_qemu_virt` and
`bitmap_allocator` — dependency crates. `axmm::backend::{impl#0}::map` is
watched and fires, but it immediately delegates, and everything it delegates to
is outside every rule in the manifest.

This is structural rather than an oversight in this one file. ArceOS is a
unikernel assembled from many small crates, so rules written from the kernel's
own crate names systematically miss the crates it hands the work to. xv6 has no
equivalent — it has no dependencies — and rCore's `easy_fs` is already named in
its manifest. The vocabulary can express the fix, `module =
"page_table_multiarch"` being a legal rule today, but whether to add it is a
cost question and not obviously yes: the second entry in that table,
`phys_to_virt` at a quarter of the boot, is an accessor of exactly the kind
xv6's `mycpu` and rCore's `current_trap_cx` turned out to be, and the answer
there was `skip`, not `watch`.

There is also a reach limit. The two hottest entries are generic
monomorphisations whose symbols the conservative v0 parser declines, so their
paths are still raw `_R` strings and no `module` rule can match them however it
is written. Naming `page_table_multiarch` would catch `new_page` and `is_huge`
and miss `map` and `map_region`, which are 51% of the window.

#### A safety bound changed the answer

The first run was capped at 50M instructions to protect a disk with 5.5 GB
free. It ended with 6 hits, all in the init window, and `spawn_task`,
`context_switch` and `exit` apparently dead — which reads as three broken
watchpoints in the scheduler. The cap had landed inside the 56M page-table gap,
and everything interesting happens after it. The console log was complete
through `Multi-task OK!` and shutdown, which made the truncation invisible: the
guest output looked like a finished run because QEMU kept executing after the
plugin stopped recording.

Raising the bound to 400M cost nothing — the trace grew from 16 KB to 22 KB,
because trace size follows event count, not instruction count. The bound was
protecting against a risk that did not exist on this workload while silently
producing a wrong conclusion. `maxinsn` is worth keeping, but a run that ends
*at* the bound has to be read as truncated until shown otherwise, the same way
`truncated_at_eof` is read.

### Alien: a crate name that was never in the source, and a prefix that cannot match

Alien is the fourth target kernel, and the first one checked against source
rather than a binary. There is no build — `_nfverify/Alien` is a source tree —
so nothing below is measured. What source *can* settle is names, because in
Rust a symbol path starts at the crate name and the crate name is the package
name in `Cargo.toml`. That is not a heuristic; it is how the path is formed.

Three things in `alien.toml` were wrong, and all three were name inventions
rather than modelling mistakes. The shapes were right.

**`alien_kernel` does not exist.** `detect` and the task watch rule were both
rooted at `alien_kernel::`. Grepping the whole tree for that string returns
nothing — not a struct, not a module, not a `Cargo.toml` line. The package is
`kernel`, and `[lib] crate-type = ["staticlib"]` does not rename it. Every match
anchored at `alien_kernel::` was unreachable. Corrected to `kernel::`.

This is the failure the file's own header had already described, in the note
about Starry: *短名加照源码猜的 crate 名，detect 一条都没命中，于是底座 ArceOS
独中，给出一个理直气壮的错答案*. The warning was written about a different
manifest and was sitting three lines above the same bug.

**`module_prefix = "subsystems::"` cannot match anything.** Alien's 16
subsystems are `subsystems/*` workspace members, so each is a separate crate:
`mem`, `vfs`, `ksync`, and so on. A crate name is the *root* of its symbol
paths. `mem::alloc_frame` — never `subsystems::mem::alloc_frame`. The directory
name appears nowhere in any symbol.

The instructive part is the comment that sat above the rule:

> Alien's 16 subsystems/ directories map 1:1 to crate names, so subsystem
> membership is derived from the module path, not enumerated here.

The premise is correct and is exactly what refutes the rule. If each directory
*is* a crate, then there is no shared prefix to strip, because the crate names
are siblings at the root. "Map 1:1 to crate names" and "share the prefix
`subsystems::`" cannot both be true. The comment did the observation and then
drew the opposite conclusion from it — which is why it read as justification.

`module` already takes a list and already reports which entry matched, so
`module = [16 crate names]` with `subsystem = "*"` gets what the prefix was
reaching for, and the names come from the workspace glob rather than from the
directory listing being mistaken for a path.

Two consequences worth recording. `module_prefix` now has **zero users** across
all seven manifests; it still works and is still tested, but nothing depends on
it, and its docstring cited Alien as its motivating case — that example was
fictional and has been replaced. And the general form of the mistake is worth a
name: *a directory is not a module*. It happens to be one in C, where
`file = "kernel/proc.c"` is the only attribution available, and that is
presumably where the intuition came from.

**Twelve of thirteen kernel modules were unwatched.** `kernel/src/lib.rs`
declares `ebpf fs gui ipc kprobe ksym mm net per_cpu perf system task time
trap`. Only `task` had a rule. This is the ArceOS 17%-coverage shape again, but
visible before a run instead of after one: `trap`, `mm` and `fs` are watched by
every other manifest in this directory, so their absence here was an omission
rather than a decision. Added, with throttles copied from the comparable
ArceOS/rCore rules and labelled in the file as unmeasured.

**What source verification cannot reach.** `type` moved from the short name
`Task` to `kernel::task::task::Task`, derived from `mod task` in `lib.rs`, `mod
task` in `task/mod.rs`, and `pub struct Task` in `task/task.rs` — the module
structure determines the path uniquely, and `arceos.toml`'s
`axtask::task::TaskInner` proves qualified types resolve on a real build.
`static = "INIT_PROCESS"` stays short. Statics resolve through
`syms.resolve()` against the symbol table, not the type table, and the mangled
form of a `Lazy<Arc<Task>>` static is a property of the build, not of the
source. Guessing it would reproduce exactly the mistake this section is about.
So half the header's 待办 is now closed and half is explicitly still open.

### Starry had no working watchpoints at all, for the reason Alien did

Checking `starry.toml` straight after Alien, because the failure shape looked
reusable. It was. Both watch rules named crates that do not exist:

```toml
match = { module = "starry_core::task" }   # starry_core: not a crate
match = { module = "starry_api" }          # starry_api:  not a crate
```

`_nfverify/tgoskits`'s lockfile compiles `starry-kernel`, `starry-signal`,
`starry-vm`, `starry-fatfs`, `starryos`. Neither `starry_core` nor `starry_api`
appears anywhere in the StarryOS source tree or the lock. Both rules matched
zero functions, and since `builds_on` does not inherit watches (it only breaks
detection ties), **Starry selected no watchpoints whatsoever.** Not a thin set —
an empty one.

What makes this worth writing down is that the file already knew. Its header,
from a real DWARF check:

> 注意 crate 叫 starry_kernel，不是 starry_core […] 早先按源码猜的
> starry_core::task::process::Process 在二进制里根本不存在

The measurement was done, the conclusion was recorded in prose at the top of
the file, and it was applied to `detect` and `entity.type` — the section that
was being examined at the time. The watch block, thirty lines further down and
carrying the identical wrong crate name, was not touched. Alien failed the same
way: `alien_kernel` corrected nowhere, `Task` short in one place and qualified
in another, `subsystems::` left standing under a comment that refuted it.

So the pattern, stated once so it can be checked for: **a verification pass
corrects the section it is looking at, not every use of the fact it
established.** A crate name appears in `detect`, in `entity.type`, in
`entity.fields`' enum paths, and in every `watch` rule. Confirming it in one
place proves it everywhere and fixes it nowhere. Worth a lint: no `module`,
`type`, or `any_type` may name a crate root that no other entry in the same file
names.

The rules now read `starry_kernel::{task,syscall,trap,mm,file,pseudofs,ipc}`,
from `kernel/src/root.rs` — `lib.rs` is ten lines ending in
`include!("root.rs")`, so grepping `lib.rs` for `mod` finds nothing and the
module list looks empty. Plus the four base crates Starry actually vendors
(`ax_task`, `ax_cpu`, `ax_mm`, `ax_alloc`), and a panic rule, which is
fn-matched and therefore the one rule that ports across kernels unchanged. Two
rules became eleven.

None of it is measured — `tgoskits/target/` exists but is empty, so there is no
Starry binary to check against right now. Names come from the lockfile and the
module tree, which settle names and nothing else; throttles are copied from the
comparable ArceOS rules and are guesses. Two predictions are written into the
file so a first run can falsify them: `starry_kernel::sync` is the
`fmt`/`ksync`-shaped accessor risk, and coverage is likely as bad as ArceOS's
17% because Starry's dependency surface is larger, not smaller.

### A generic type had no spelling that a manifest could use

`axvisor.toml` named its two entity types with bare short names, `AxVM` and
`AxVCpu`, while its `detect` used the qualified `axvm::vm::AxVM` — the same fact
written two ways in one file, which is the shape the previous two sections are
about. Qualifying them turned up something worse than an inconsistency.

`AxVCpu` is generic: `pub struct AxVCpu<A: VmArchVcpuOps>`. Measuring what DWARF
does with that, on the rCore build:

```
path = core::ptr::non_null::NonNull<alloc::…::LeafNode<VirtPageNum, FrameTracker>>
name = NonNull<alloc::…::LeafNode<VirtPageNum, FrameTracker>>
```

Both carry the full monomorphised argument list. 839 of that build's 1343 types
have a `<` in the name — 62%. `find()` looked in two places, the exact-path table
and the short-name index, and a generic type is in neither under any name a
person would write: the short-name key is `AxVCpu<…>`, not `AxVCpu`, and the
exact-path key is `axvm::vcpu::AxVCpu<…>`, not `axvm::vcpu::AxVCpu`.

So **both** ways of naming it failed, and the failure was a `None` — which the
caller reports as the type not being in the binary. A generic entity is
indistinguishable from an absent one. The only string that would have worked is
the full monomorphisation, which is a property of one build: change the arch and
`AxVCpu<RISCVVCpu>` becomes `AxVCpu<VmxVCpu>`. That is exactly the sort of thing
a manifest must not hard-code, so "write it out in full" is not a fix.

`find()` now falls back to a third index keyed on the name with the arguments
stripped at the first `<`, under the rule the function already had: if the
instantiations disagree on layout, refuse and record the conflict rather than
pick. Measured on rCore — `BTreeMap` resolves (every instantiation is 24 bytes),
`NonNull` refuses and names the colliding instantiations, and both entity types
in `rcore.toml` resolve to the sizes recorded earlier in this file
(`TaskControlBlock` 288, `BlockCache` 544), so nothing moved.

Two smaller things fell out. `rsplit("::")` is wrong on a generic path — the
arguments contain `::` too, so `axvm::vcpu::AxVCpu<axvm::arch::RISCVVCpu>` splits
to `RISCVVCpu>`. That bug appeared in the first draft of the test helper, which
is a fair warning about where else it might be. And AxVisor's crate really is
`axvm`, no hyphen, confirmed in the tgoskits lockfile — so the `ax-task` →
`ax_task` renaming did not sweep the whole ecosystem, and each crate name still
has to be checked one at a time.

### The same defect in four of seven manifests, and one dead rule

Having found it in `alien.toml`, checking the rest. The bare-module bug is in
four of the seven:

| manifest | written | real | why |
|---|---|---|---|
| alien | `alien_kernel::task` | `kernel::task` | crate name invented; appears nowhere in the tree |
| alien | `module_prefix = "subsystems::"` | `module = [16 crates]` | directory name, never in a symbol |
| starry | `starry_core::task`, `starry_api` | `starry_kernel::{task,syscall}` | crates that do not exist |
| rel4 | `task_manager`, `cspace` | `rel4_kernel::{task_manager,cspace}` | modules named without their crate root |
| axvisor | `AxVM`, `AxVCpu` | `axvm::vm::AxVM`, `axvm::vcpu::AxVCpu` | short names, one of them generic |

Four independent authorings, one mistake: **writing the name you would use
inside the source file rather than the name the linker emits.** Inside
`rel4_kernel`, `task_manager::foo` is what you type; the symbol is
`rel4_kernel::task_manager::foo`. Inside `axvm`, the type is `AxVM`; the symbol
is `axvm::vm::AxVM`. The manifest sits outside every crate, so it never gets the
short form, and there is no context in which the short form is right.

None of it is visible without a build. Every one of these rules parses, validates
and selects zero — which is indistinguishable from a subsystem that did not run.

**A dead rule, from ordering rather than naming.** `axvisor.toml` had:

```toml
[[watch]] subsystem = "axvm"    match = { module = "axvm" }
[[watch]] subsystem = "vmexit"  match = { module = "axvm::vcpu", fn = ["*exit*"] }
```

Selection is first-come-first-served (`if fn.addr in seen_addr: continue`), and
`module = "axvm"` matches `axvm::vcpu::*` as a prefix. The broad rule claimed
every vmexit function before the narrow one was consulted, so `vmexit` could
never appear — and an absent subsystem reads as "no vmexits happened this run",
which for a hypervisor is a plausible-looking lie. Narrow rules go first, the
same reason `fmt`'s `skip` is first in `arceos.toml`.

**Reordering was necessary but not sufficient, and nobody checked.** Measured
2026-09-08 against `axvisor-9ebc9765.elf`: with the order already corrected, the
rule *still* selected zero, and `Selection.empty_rules` had been saying so —
`[vmexit] module='axvm::vcpu'，fn=['*exit*', '*vmexit*']`. The second cause is
naming, not ordering: `axvm::vcpu` contains no function whose name has `exit`
in it. Its five members are `map_host_backend_error`,
`map_interrupt_backend_error`, `map_vcpu_backend_error` and two
`__PERCPU_CURRENT_VCPU_*` stubs. Across the whole ELF only two symbols match
`vmexit`, both in `riscv_vcpu` and `cpu_local`. The exit path is
`axvm::architecture::exit` (`handle_hypercall`, `try_handle_mmio_read`).
Repointed there: `vmexit` now selects 2, `axvm` drops 250 → 248, and the total
holds at 323 — moved, not double-armed. The lesson is the one this file keeps
re-learning in other forms: after fixing a rule that produced nothing, **go look
at whether it now produces something**. Both failures render identically, and
the ordering fix made the diagnosis feel closed.

Both defects are mechanically checkable and neither needs a binary:

  * a `module`/`type`/`any_type` naming a crate root that no other entry in the
    same manifest names is almost certainly wrong;
  * a rule whose match is a strict narrowing of an earlier rule's is dead.

Worth writing as a lint. It would have caught five of the six problems in this
section, at parse time, with no kernel present.

**Coverage, incidentally.** Fixing the names made it obvious how thin these were:
alien 2→5 rules, starry 2→11, rel4 2→7, axvisor 2→5. All unmeasured — names come
from lockfiles and module trees, which settle names and nothing else, and every
throttle is copied from a comparable rcore/arceos rule. ArceOS is the warning
here: its rules were right and still saw 17% of the boot.

### The lint, and what it found in the manifest that was already verified

Both defects from the previous section are now checked at parse time by
`manifest.lint()`, which returns warnings rather than raising — these are
suspicions, and a hard failure would block loading a manifest that is merely
unusual.

The dead-rule check only treats a **pure module rule** (no `fn`, no `file`) as a
shadower. Such a rule matches every function in its modules, so anything narrower
after it is dead no matter what it says. A shadower with its own `fn` filter
would need glob-vs-glob reasoning to judge, so it is skipped: under-report rather
than mis-report.

Crate-root consistency is deliberately **not** checked. It was tried and does not
work. `alien.toml` used the invented `alien_kernel` in every entry, so the file
was internally consistent and no internal check could see it. A "minority crate
root is suspicious" heuristic false-positives on `arceos.toml`, where `axcpu`,
`axmm` and `axalloc` each appear exactly once and are all correct. That class of
error is only decidable against a binary.

Running it over the seven shipped manifests turned up one more, in the file with
the strongest provenance:

```
[rcore] 类型 'TaskControlBlock' 写的是短名，同一份文件里另一处写的是全名
        'os::task::task::TaskControlBlock'
```

`rcore.toml` is the manifest that has been checked against a real build more
than any other, and it had the same short-vs-qualified split as `axvisor.toml`.
It resolves today — there is exactly one `TaskControlBlock` in that binary — so
nothing was broken and nothing would have shown up in a run. It was one
same-named type away from failing, and the failure mode would have been `find()`
returning None with a conflicts entry, i.e. the kernel appearing not to contain
its own task struct.

Both rcore types are now qualified, and the second one is more interesting than
the first: `BlockCache` is `easy_fs::block_cache::BlockCache`, not `os::…`. The
short name concealed that the type comes from a **different crate** than the one
the rest of the manifest talks about. Qualifying names is not only about
collision safety; it is the only form in which a manifest states where something
lives.

A regression test asserts every shipped manifest lints clean, because this whole
class of error is invisible on a machine without the matching kernel: the rules
parse, they validate, and they select nothing.

### Re-running the crosscheck, and a rule that is idle rather than wrong

`find()` gained a third index this session, and it is on the path every decode
takes, so both kernels were crosschecked again. Nothing moved:

| kernel | table | rules | in both | snapshot flags | thinned |
|---|---|---|---|---|---|
| xv6 | 72 | 141 | 72 | consistent | none |
| rCore | 59 | 92 | 59 | consistent | none |

Same numbers as recorded earlier. The rules remain a strict superset on both.

The rCore run reports one rule matching nothing, which the tool labels *多半是
名字写错了*:

```
[mm] fn = ["find_pte_create", "find_pte", "translate"]
```

It is not a typo. All three are absent from this binary's symbol table **and**
its DWARF — `find_pte` and `find_pte_create` are inlined away completely in the
release build, and of `translate` only `translated_byte_buffer`,
`translated_str` and `translated_refmut<T>` survive under different names. The
rule is correct and would match on a debug build or another chapter; here there
is nothing left to match.

That distinction is the whole point of the project's absent/empty/undecodable
rule, applied to a rule rather than to a value. Three states share one symptom:

  * the name is wrong (starry's `starry_api`),
  * the name is right and the function was inlined (this one),
  * the name is right, the function exists, and the workload never called it
    (ArceOS's ten never-fired points).

All three appear as "this subsystem produced no events". Only the second and
third are correct behaviour, and the crosscheck cannot tell them apart — it can
only see that the ELF has no such symbol, which is equally true of a typo. So
the rule stays, with the reason written next to it: deleting it would also delete
the record that these functions get inlined, which is the more useful fact.

Worth noting what this implies for the throttle design. Rule 8 throttles the
page-table walk at 64; rule 10 (`module = "os::mm"`, throttle 0) takes the rest
of the module. Because selection is first-come-first-served and rule 8 matches
nothing here, the surviving `translated_*` functions fall through to rule 10 and
are *not* thinned — which is exactly what the comment above rule 8 asks for. The
arrangement produces the intended result through a rule that never fires.

### Flipping the default, and the one thing selection alone could not show

Watch selection now defaults to the manifest rules. `--watch-from-table` opts
back into the hardcoded list, and errors rather than substituting when the named
kernel has no table.

The static evidence was already in hand — rules are a strict superset on both
kernels, snapshot flags agree, nothing gets thinned. What was missing was a
recording. Recording cowtest at lab-stage 5 under the new default and diffing
against the table-recorded reference gave:

| | table | rules |
|---|---|---|
| watchpoints | 72 | 141 |
| events | 385 372 | 651 455 |
| trace | 60.7 MB | 92.6 MB (1.53×) |
| wall | 13.63 s | 14.06 s (+3%) |

Nothing lost, nothing thinned, snapshot flags identical — and five event
categories gone:

```
trap.userret  38753 -> 0      func.prepare_return  0 -> 38753
proc.fork         4 -> 0      func.kfork           0 -> 4
proc.exit         3 -> 0      func.kexit           0 -> 3
proc.wait         4 -> 0      func.kwait           0 -> 4
proc.exec         3 -> 0      func.kexec           0 -> 3
```

Counts preserved exactly; only the names changed. Seven addresses in this kernel
carry two real symbols each — the course tree wraps several syscalls as
`kfork`/`kexit`/`kwait`/`kkill`/`kspawn`/`kexec` and calls `usertrapret`
`prepare_return`, while the MIT tree uses the bare spellings. `xv6.toml` lists
both deliberately; `analyze.py`'s `FUNC_EVENTS` knew only one.

Three things worth keeping from this.

**Selection was a superset on all three axes and still lost information.** The
axes we had been checking — picked, snapshot, throttle — are properties of
*which* points are watched. This is a property of *what a watched point is
called*, and the two selection paths disagree on it wherever a symbol has an
alias. Nothing in the superset check can see that; it compares addresses.

**The failure is the project's standard silent one, one level further down.**
Watchpoint count unchanged, flags unchanged, throttles unchanged, event count
*higher*. The report reads "this run never forked" for a run that forked four
times — identical in every visible respect to a kernel that genuinely never
forks. Same shape as a manifest naming a crate that does not exist, except the
manifest here was right and the analyzer was wrong.

**`FUNC_EVENTS` is the next hardcoded table.** Watch selection moved to the
manifests; the mapping from function name to event type and argument names did
not. It is xv6-only in practice — the reason `resource` survived the relabelling
is that the manifest carries `resource` per rule, while event type and argument
names have no manifest field and fall back to `func.<name>` with no columns. Six
of the seven target kernels therefore produce `func.*` for everything. Recorded
as a task rather than fixed here, because the design question (extend
`[[watch]]`, or add an `[[event]]` section) deserves deciding on its own.

The regression test pins the invariant, not the table: for every address both
paths select, the two paths must agree on what it means. A test that listed the
aliases would repeat whatever mistake the table made. Verified to catch all
seven when the aliases are removed.

## 一张按函数名索引的表，会去认领别的内核

上一节末尾写了一句"七个内核里有六个的事件全是 `func.*`"。那句话当时没有被证实
过 —— 而且拿现有的 run 也证实不了。翻了一遍七份 rCore bundle：它们的
`watchlist.json` **全是空的**，`watch_source` 这个字段那时还不存在。观察点一个
都没装，所以 `FUNC_EVENTS` 从头到尾没被走到过。

那它们的 84183 条事件从哪来的？跟 `discon` 记录一条对一条 —— 全部来自陷入解码
那条路（`analyze.py` 里 `sbi.call` / `firmware.trap` / `syscall.enter` /
`interrupt.timer` 那几个分支）。那条路自己拼 `kind` 和 `detail`，本来就是通用
的，跟这张表不沾边。**事件有两个来源，只有 `watchpc` 那条会走 `event_shape`。**
之前把两者当成一个，才会拿"rCore 事件 100% 有参数名"去推翻一个它根本没测到的
判断。

拿真 ELF 静态地选一遍点（不重编、不录制），才是能说话的证据：

| | |
|---|---|
| 规则在 rCore 上选中 | 92 个点 |
| 落到 `func.<名字>` | 88 个（96%） |
| DWARF 里有形参名 | 46 个（50%），其余 release 下被内联或去掉了 |
| 跟 xv6 手写表撞名 | 4 个 |

前三行说明那句话方向是对的，只是当时没有依据。第四行是这次真正挖出来的东西。

### 撞名的那四个

`FUNC_EVENTS` 的键是光秃秃的函数名。`exec`、`fork`、`panic`、`syscall` 没有哪个
内核独占，于是这张表会认领任何内核里的同名函数：

    exec  0x8020cee2  真身 os::task::task::TaskControlBlock::exec
                      方法：a0 是 &self，a1 是 elf_data
          手写表说    exec(path, argv)

报告里于是有一列 `path` 装着 TaskControlBlock 指针、一列 `argv` 装着 ELF 数据的
指针。**两个值都在、两个名字都错、看着都像真的** —— 跟"真的读到了路径"分不出
区别。`panic` 一样：DWARF 说形参叫 `info`（`&PanicInfo`），表把它盖成 `msg`
（xv6 那边是 `char*`）。

这个坑在把选点默认换成 manifest 规则**之前**是睡着的：rCore 一个点都不选，撞不
上。换了默认，它就醒了。也就是说，让它变成活的正是上一节那次改动 —— 同一次改动
先暴露了别名退化，又埋下了这一个，方向相反：那次是**该给的语义没给**，这次是
**不该给的语义硬给**。

修法是问一句是哪个内核（`bac437a`）。`event_shape` 的 `kernel_kind` **没有默认
值**，因为默认成 xv6 就等于把这个 bug 原样写回去，而且只在别的内核上才看得见。
非 xv6 一律退回 `func.<名字>` + subsystem + 它自己的 DWARF 形参名。

代价是 rCore 的 `kernel.panic` 变回 `func.panic`。这是**类别降级、正确性升级**：
给别的内核配上像样的类别是另一件事，不能靠蹭 xv6 的表假装已经有了。

测试钉的还是不变量而不是那四个名字（那份名单跟着 `rcore.toml` 变）：**不是 xv6
的内核，参数名只能等于它自己 DWARF 里的形参**。另加一条反向的：确认"撞名"这件
事今天仍然发生 —— 否则哪天 `rcore.toml` 不再选中 `exec`，上面那条会因为没东西
可测而通过，保护就悄悄没了。把作用域判断改回去验过：六条里挂四条，没挂的两条正
好是 xv6 不该受影响那条和这条防空跑的。

### 同一个毛病，下面还有一层

修完表之后又翻了一遍 `analyze.py`，找还有什么是"按函数名分派"的。有三处，全在
`_watch_event` 里，全是读 xv6 源码得来的：

| 函数名 | 这段代码依据的 xv6 事实 | 换个内核会怎样 |
|---|---|---|
| `swtch` | a1 是新上下文指针 | 没有内核这么拼，暂时撞不上 |
| `kalloc` | 返回值靠内核内的 nftrace 补 | 补不到就如实标 unknown，不猜 |
| `panic` | a0 是 `char *` | **rCore 也有 `panic`，规则也真选中了** |

第三行才是要命的。rCore 是 `panic(info: &PanicInfo)`，a0 指向一个结构体。
`ram.cstr(a0, 96)` 照样会从结构体的字节里读出一段到 NUL 为止的东西，填进
`detail["msg"]`。**读得出来、读得像话、而且是编的。**

跟表那次比，这一个更难发现：列名错了，起码还能拿 DWARF 对一下；而一段"panic 消
息"没有第二个来源可以校对 —— 报告里就写着内核 panic 说了什么，你只能信它。

`swtch` 和 `kalloc` 今天撞不上，也一并收了作用域。"目前没有别的内核叫这个名字"
不是任何人在维护的性质，指望它就是等下一次。

常量顺手改名 `FUNC_EVENTS_KERNEL` -> `HARDCODED_KERNEL`：它现在管的不止那张表。

测 `panic` 那条用替身直接跑 `_watch_event`，而且让 `cstr` **永远**返回一段像话的
字符串 —— 要钉的不是"解出来的字符串不对"，是**根本不该去解**。把守卫改回
`xv6 = True` 验过：这条挂、xv6 那条照样过。

xv6 侧重跑了一遍 `lab3-cowtest-mac` 确认没动到：59 种类别、385372 条事件一条不
差，`swtch` 照样解出 932 次切换，38588 条 `phys.alloc` 照样把 `allocated_pa` 如
实标成未知。

## 把"默认 xv6"当成一类去扫

修完上面两处之后顺着同一个形状扫了一遍：**凡是缺省值取了某个真内核的名字的地
方**。一共四处，全是同一个根因，也全都不长得像错。

| 地方 | 缺省/兜底 | 错的时候看起来像什么 |
|---|---|---|
| `FUNC_EVENTS` 查表 | 键只有函数名，不问内核 | 报告里多了一列 `path`，装着别的东西 |
| `_watch_event` 按名分派的解码 | 同上 | 报告里写着 panic 消息是「……」 |
| `watchlist.build(kind=)` | `= "xv6"` | 73 个 missing、0 个命中 |
| `layout.probe()` | 认不出 -> 走 xv6 探针 | 「找不到 kernel/types.h」 |

第三行是七份 rCore run 观察点全空的真正原因 —— 之前只知道"空"，不知道为什么。
它们的 `missing` 列表里写的是 `kalloc`、`uvmalloc`、`swtch`、`pipealloc`：**一整
份 xv6 的名字**。调用处没把 `kind` 传下去，缺省值把它们送进了 xv6 那份名单。

rCore 自己是有名单的（`table_kinds()` 返回 `['rcore','xv6']`），拿它去解同一个
ELF 解得出 59 个点。所以名单没问题、二进制没问题，丢的只是一个参数。

### 为什么四个都不响

共同点是**缺省值挑了一个真内核的名字**。`kind="xv6"` 是个合法值，`""` 被当成
xv6 也是合法状态，于是"走错了"和"走对了"在类型上没有区别，只能靠结果判断 ——
而结果恰好也是本项目最难判的那种：

  * 0 个观察点 ≈ 这个内核这次什么都没干；
  * 73 个 missing ≈ 这个 build 内联得比较狠；
  * 一列 `path` ≈ 真的读到了路径；
  * 「找不到 kernel/types.h」≈ 交叉编译环境没配好。

四条都能自圆其说，而且都会把人引向一个**存在但无关**的问题。

### 一致的修法

四处都改成同一种形状：**没有默认值，认不出就报错，报错里说下一步去哪**。

  * `event_shape(kernel_kind=)` 不给默认 —— 默认成 xv6 就是把 bug 写回去；
  * `build(kind=)` 不给默认 —— 少传一个参数不该悄悄变成"另一个内核"；
  * 一份名单**全军覆没**直接抛错 —— 少数 missing 照旧放行，两者要分开；
  * `probe()` 认不出就抛错，并列出三条真实出路（xv6 探针 / rCore DWARF /
    manifest 或 `--layout-override`）。

最后一条单独说一句：`detect_kernel` 里早就有一段注释记着同一个坑的另一个方向 ——
rCore 的 ch1/ch2 曾因为认的是 `config.rs`（ch3 才出现）而认不出来，症状同样是
"找不到 kernel/types.h"。当时修的是**认得准不准**，没动**认不出之后去哪**。所以
这个坑其实被人踩过一次、也写下来过，只是补在了上半截。

## 换默认之后，两个内核的静态对拉

`crosscheck_watchsel` 在两份真 ELF 上跑（按地址比，不按名字 —— 两边命名法不同）：

| | 写死名单 | manifest 规则 | 两边都选中 | 只有规则有 |
|---|---|---|---|---|
| xv6 | 71 个名字 -> 72 个点（1 个找不到） | 15 条 -> 141 个点 | 72 | 69 |
| rCore | 103 个名字 -> 59 个点（46 个找不到） | 12 条 -> 92 个点 | 59 | 33 |

两边都是：**"只有名单有"为 0**，快照标记一致，名单里的点一个都没被节流抽稀。也
就是规则那条路在这两个内核上是严格超集，没丢任何一个原来盯着的点。

rCore 这一行是头一回量 —— 它以前根本没选中过任何点（见上一节）。

需要说清楚的是这条对拉**能证明什么**：它只比地址。xv6 那次别名退化（`fork` /
`kfork`）就是地址完全一致、语义掉了，这条查不出来。rCore 这边不受那个影响，因为
`FUNC_EVENTS` 现在只对 xv6 生效，rCore 的函数名不再喂给任何语义表 —— 名字只用来
取 DWARF 形参，而形参是跟着地址走的。

还有一件事这条对拉**不能**证明：这 92 个点装得上、打得中、参数落在对的寄存器
里。那要真录一遍，而录制会重编 rCore —— 现有七份轨迹都是同一个 build 的，重编就
全都解不开了。所以停在这里，等一个决定（见任务 #46）。

`crosscheck_dwarf` 也一并跑了：xv6 27 个结构体、rCore 1343 个，新旧两套读出来的
布局零差异。

## 事件语义搬进 manifest：`[event]`

上一节把 `FUNC_EVENTS` 关进了 xv6 的门里，止住了串味。代价是**别的内核连自己的
语义都没处写** —— 一律 `func.<名字>`，没有开口。这一节把这份知识挪到各内核自己
的 manifest，门禁的代价就没了：键自带内核归属，`[event]` 对七个目标内核都开着。

### 一件顺手发现的事：resource 早就不是 manifest 说了算

`event_shape` 的文档里写着"**资源**来自 manifest 的 `[[watch]] subsystem`，早就
不写死了"。这句话对表里的 69 个函数**全都不成立** —— 那些点的资源被
`FUNC_EVENTS` 里的第二栏盖掉了，manifest 给的 subsystem 根本没用上。

不是小数：拿真 ELF 量，69 个里 41 个两边不一样。

| manifest 的 subsystem | 表里的 resource | 个数 |
|---|---|---|
| fs | inode | 11 |
| fs | log | 7 |
| fs | bcache | 5 |
| file | pipe | 4 |
| proc | sched | 3 |
| vm | pagetable | 3 |
| proc | vm | 2 |
| proc | sync | 2 |
| trap | interrupt | 2 |
| fs | disk | 2 |

看清楚方向：**表里的更细**。规则是按文件/模块划的，一条 `fs` 罩着 inode、log、
bcache、disk 四类，一条 `proc` 罩着 sched 和 sync。粒度差是这两种东西的常态，
不是谁写错了。而报告里 `res` 是个筛选器，直接采用 manifest 的 subsystem 会**少
一档能筛的** —— 这是真损失，所以 `[event]` 里给了 `resource` 一个位置，41 条照
原样收窄。

### 参数名：先量错了一次

第一遍对拉的结论是"手写的名字跟 DWARF 完全一致，一条 `args` 都不用写"。那是错
的，而且错法值得记下来：当时 `xv6.toml` 里已经写着 `args` 覆盖，`select_watchlist`
把它们套上去之后才交给我比 —— 我拿表跟表自己的副本比了一遍。

拿 `events={}` 重新解一次 DWARF，真实情况是 8 条要覆盖：

| 函数 | 手写 | DWARF | 判定 |
|---|---|---|---|
| brelse / bwrite / log_write | `buf` | `b` | 改可读性，覆盖 |
| virtio_disk_rw | `buf, write` | `b, write` | 改可读性，覆盖 |
| freeproc | `proc` | `p` | 改可读性，覆盖 |
| panic | `msg` | `s` | 改可读性，覆盖 |
| sleep | `chan, lock` | `chan, lk` | 改可读性，覆盖 |
| swtch | `old_ctx, new_ctx` | （空） | 汇编，没有形参，覆盖 |
| **uvmalloc** | `pagetable, oldsz, newsz` | `pagetable, oldsz, newsz, xperm` | **手写的过时了，用 DWARF** |

最后一行是这次唯一改变行为的地方。`vm.c:221` 写着
`uvmalloc(pagetable_t, uint64 oldsz, uint64 newsz, int xperm)` —— 手写的名单停在
第三个参数，于是报告里 `xperm` 那一列一直没有名字。手写的比 DWARF **短一截**是
个可判定的信号（是前缀且更短），照这个信号自动排除，剩下的才覆盖。

### 验了什么

* 141 个观察点逐条对拉，manifest 那条路和查表那条路给出的 kind / resource /
  args **完全一致**，只有 `uvmalloc` 多出上面那个参数名。
* 重新解 `lab3-cowtest-mac`，385372 行事件**逐字节一致**。这份 bundle 的
  `watchlist.json` 里没有 `kind` 这个键（它录在这个键存在之前），所以它必须走
  兼容分支 —— 一致本身就是那条分支好使的证据。
* 14 条新测试，逐条验过：把改动倒回去，该红的红。

## rCore 的 `[event]`：把"能搬"变成"搬了"

搬家做完之后，`[event]` 只存在于一份 manifest 里 —— "非 xv6 的内核也能有自己的
语义"还只是个说法。给 rCore 写一份，才算验过。

92 个点里 49 个有了 kind，照源码读出来的，不是照名字猜的：trap 那三个来自
`trap/mod.rs:58,115,141`，`proc.exit`/`proc.initproc` 来自 `task/mod.rs:62,120`，
地址空间那批来自 `memory_set.rs`。

**故意没写的**：easy-fs 那三十来个（`Bitmap::alloc`、`Inode::find`、
`DiskInode::read_at`……）。`func.<名字>` 对它们已经是如实的，硬编一套类别把那一
列填满，正好是本项目最该避免的那种"看着都像真的"。

### 键为什么一律写全路径

写 rCore 这份的时候撞上一件 xv6 上不存在的事：观察点的 `name` 是解修饰后的**最后
一段**，只在会撞名时才带限定。这个 ELF 里：

    read            -> os::fs::stdio::Stdin::read      （光着）
    OSInode::read   -> os::fs::inode::OSInode::read    （带限定）

谁光着谁带限定，**取决于这个二进制里还有什么别的符号**。换一章、多一个同名函数，
今天写的 `read` 键明天就可能不再匹配任何点。而失配是无声的：那个函数退回
`func.read`，跟压根没写过这条一模一样。

所以 `[event]` 的键也接受全路径，且全路径优先。C 内核不受影响 —— xv6 的名字本来
就是扁平且唯一的，那份 manifest 一个全路径都不用写。

同时补上一条报告：**一个点都没匹配上的 `[event]` 键**，跟"一条函数都没匹配上的
规则"记在同一处（`missing`）。两者说的是同一件事 —— 说好要看的东西没看到。xv6
和 rCore 现在都是 0 条。

### 共有词汇

跟 xv6 那份对齐之后，两个内核有 14 个**同名**的事件类型：

    kernel.panic  pagetable.map  phys.free  proc.exec  proc.exit  proc.fork
    sched.enter   sched.switch   sched.yield  syscall.dispatch  trap.userret
    vm.copy       vm.grow        vm.shrink

这是"跨内核比较"能成立的前提。不对齐的话，两份报告只是并排放着的两张无关的表。

### 这些 kind 没有动态验证过

rCore 的观察点**至今一次都没打中过** —— 仓库里七份轨迹都是拿写死的 xv6 名单录
的，那份名单在 rCore 上一个符号都解不出来。要验就得重录，而重录会重编内核，现有
七份轨迹就全都解不开了。这句话同时写在 `rcore.toml` 的 `[event]` 上方，紧挨着那
些 kind。等一个决定，见任务 #46。

## rCore 的观察点第一次打中了（#46 结）

一直悬着的那件事：rCore 的 92 个观察点**从来没有一次命中过**。仓库里七份轨迹全
是拿写死的 xv6 名单录的，那份名单在 rCore 上一个符号都解不出来（73 个 missing、
0 个 watchpc）。要验就得录，而录会重编内核 —— 七份轨迹的符号地址全变，就都解不
开了。

### 解法不是"接受损失"，是 `--no-build`

拿**现有的那份二进制**再录一次就行：轨迹保住了，而且新旧两份是同一个 build，可以
直接对着比。

代价是拆掉了一道保险。`build_kernel()` 编之前先删旧产物，原因是 `profile.build`
末尾都有 `| tail` —— 管道退出码是 tail 的，make 失败照样返回 0，所以"内核在"只有
建立在"旧的已删"之上才算证据。`--no-build` 跳过这一整段，于是它自己付账：产物不
齐直接报错并给出下一步，齐了就往 manifest 里写一条 warning，点名用的哪个文件、
它是什么时候的，`kernel_elf_identity` 照常写。一份 `--no-build` 录的 bundle 不该
跟正常录的长得一样。

### 结果

    观察点        92 个（老 run：72 个名字里 0 个解出来）
    watchpc       58923 条（老 run：0 条）
    事件          66076 条，57 种
    有语义的      85%（其余退回 func.<名字>）

前几名：`pagetable.map` 32318、`trap.enter` / `trap.userret` 各 3324、
`syscall.dispatch` 3320、`vm.translate_buffer` 3300、`phys.free` 37、
`sched.switch` 25。

### 凭什么说这些事件是真的

数量本身不算证据 —— 打中了但打错地方，也会出来一堆数。所以看能互相对上的：

* `trap.enter` 3324 == `trap.userret` 3324，**正好配平**。进出成对。
* `syscall.write` 1653 == `func.Stdout::write` 1653。同一件事的两个观察点。
* `syscall.read` 1647 + `syscall.write` 1653 = 3300 ≈ `syscall.dispatch` 3320。
* 参数名来自 **rCore 自己的 DWARF**，不是 xv6 的：`phys.free` 带的是 `ppn`
  （xv6 的 `kfree` 是 `pa`），`syscall.write` 是 `fd/buf/len`。
* 值也对得上：`fd = 1` 是标准输出；`ppn = 533128` 换算成物理地址是
  `0x82300000`，落在 `0x80000000`–`0x88000000` 这块 RAM 里。

`pagetable.map` / `sched.switch` 这些的参数是空的 —— 那是规则里没要 args，不是解
不出来。没要就没有，如实留空。

### 原有七份轨迹

逐一重新解过，**全部仍然可解**：

    ch1-bare 42 条事件 / ch2-batch 2146 / ch3-array 2134 / ch5-tree 98790
    ch6-fs 84183 / ch8-proc 104476 / proc 2648

`ch6-fs` 依旧有 15 帧解出进程（新的那份是 30 帧）。没有任何东西被重编。

---

## `FUNC_EVENTS` 不再是手抄件：从 `xv6.toml` 生成（2026-09-03）

上面那段"`FUNC_EVENTS` is the next hardcoded table"写的时候，它是 69 条手写的
`函数名 -> (类别, 资源, 参数名)`。`[event]` 那一节后来补上了，于是同一件事在
仓库里有了两份，只好再写测试把两份拴住（#75）。**拴两份拷贝是在管理重复。**

这次量过之后确认可以消掉。拿 lab3-cowtest-mac 的 72 个观察点逐条对拉：

| 那一栏 | 能不能从 manifest 出 | 量到的 |
| --- | --- | --- |
| 类别 | 能 | 72/72 一致，按 `symbol` 查 `[event]` |
| 资源 | 能 | 72/72 一致，manifest 给了用 manifest 的，没给用 bundle 记的 |
| 参数名 | **不能** | 见下 |

所以 `FUNC_EVENTS` 现在是 `_func_events_from_manifest()` 生成的。名字和形状
没变，外面四十来处引用一处没动。

### 参数名为什么不能一起搬

搬进去就成了 `[event] args`，而那个键在**录制时**会盖掉 DWARF
（`watchlist.py` 里 manifest 的 args 优先）。拿真 ELF 量过这 47 条：

    38 条 跟 DWARF 一字不差
     1 条 uvmalloc：手写的三个参数，DWARF 有四个（多一个 xperm）
     8 条 manifest 已经写了（7 条改可读性 + 汇编写的 swtch）

也就是说搬进去等于新增 38 条什么都不改的覆盖，外加一条把 DWARF 读到的四个参数
盖回三个。`EventSpec` 的文档里点名说过 uvmalloc 是"手写的那方过时了、不该
覆盖"——搬进去正好把那句话反过来做一遍。

留着的那张 `LEGACY_ARGNAMES` 服务的是**另一个消费者**：2026 年之前录的 bundle
的 `watchlist.json` 里没有 `params` 键（lab3 那 72 条一条都没有），而分析手边
没有内核 ELF，DWARF 当场读不到。manifest 的 args 是"录制时的覆盖"，这张表是
"分析老 bundle 时的兜底"，两个时刻、两批内容。过期条件写在它头上了：语料里
没有 pre-`params` 的 bundle 了就整张删掉。

### 生成那步不许碰 ELF

`_entities()` 要 `DwarfSource(manifest["kernel_elf"])` 才能填上 `self.kevents`，
而那个路径指向录制那台机器上的内核树。真让生成跟着走那条路，表现是**在录制的
机器上一切正常，别人拿到 bundle 就整片事件退成 `func.*`**。所以生成只读 TOML，
并且有一条测试把 `DwarfSource.__init__` 打成抛异常再跑一遍生成。

### 踩到的那一脚

第一版生成只按符号名（`kexec`）去 `LEGACY_ARGNAMES` 里找参数名，而那张表是从
旧的写死名单抄出来的、按点名用的名字（`exec`）建键 —— 于是
`exec`/`exit`/`kill`/`wait` 四条的参数名静悄悄没了。**测试全绿**，因为那四条
当时没有测试盯着。

发现是靠拿 `HEAD` 建了个 worktree，把 72 条 `event_shape` 的输出逐条对拉。
换句话说：改一张影响面广的表，能拿改动前的自己当基准就一定要拿 —— 比补测试
覆盖率快，而且它盯的是**全部输出**，不是你想得起来的那几条。

---

## 映射的两种粒度分开数（#70，2026-09-03）

#69 读三个内核的实现，量出来分界不是"谁跟谁像"，是**粒度**：

    xv6     mappages(pt, va, size, pa, perm)      for(;;){ walk(); *pte=…; a+=PGSIZE; }   区域
    arceos  Backend::map(start, size, flags, pt)  PageIter4K 逐页 cursor().map()          区域
    rcore   PageTable::map(vpn, ppn, flags)       find_pte_create(vpn); *pte = …          单页

而这条线原来横切了名字：xv6（区域）和 rCore（单页）共用 `pagetable.map`，
ArceOS（区域，跟 xv6 同档）反倒单用 `vm.map`。于是 `page_table_maps` 这个指标
在两种粒度上数数，**而且已经数出来一对**：lab3-cowtest-mac 报 76583（段），
rcore-watchtest 报 32318（PTE）。两个数各自都没数错，错的是顶着同一个名字并排
摆出来。

改法：`pagetable.map` 收窄成"写一个 PTE"，区域级归 `vm.map`。xv6 的
`mappages` / `uvmunmap` 从 `pagetable.*` 挪到 `vm.*`，于是 xv6 跟 ArceOS 站到
一起 —— 那正是量出来的分组。指标同步拆成 `vm_maps` / `page_table_maps`。

### 改基准输出的代价，量过的

卡在 pending 一整天的就是这个决定（xv6 是本项目的对照基准）。实际代价：

    lab3-cowtest-mac  76583 从 page_table_maps 搬到 vm_maps；page_table_maps 变 None
    rcore-watchtest   32318 留在 page_table_maps，没动
    arceos-*          vm_maps = 1  ← 新的

**一个数都没丢**，改的是它叫什么、跟谁可比。

### 顺带堵上的洞

ArceOS 一直有 `vm.map` 事件（来自 `axmm::backend::map`），可 `_METRIC_KINDS`
里只有 `pagetable.map`，于是"ArceOS 映射了页面"这件事在指标里一个数都没有 ——
报告读起来像个从不映射页面的内核。这不是新加的功能，是分界线画对之后的自然
结果：ArceOS 和 xv6 本来就是同一档。

### 顺带露出来的两件事

**一、`page_table_unmaps` 成了死指标。**xv6 的 `uvmunmap` 挪走之后，七份
manifest 没有一份再声明 `pagetable.unmap`，这条指标对谁都是 None。删了。
删的是**指标**不是**词**：`pagetable.unmap` 仍然登记在 `model/kinds.py` 里，
因为 `rcore.toml` 明写着自己缺这一条"不是漏写的"。留着死指标的代价不是零 ——
一个永远算不出数的指标会天天出现在 `unobservable_reason` 里，而那一栏本来是
用来指出真的没测到的东西的；掺进不可能有值的，读的人会开始忽略整栏。

**二、xv6 头一回上了 blind 名单。**它现在报"`pagetable.map` 算不出数"。这话
是对的：xv6 当然会写 PTE（mappages 循环里每页一个），但它没在那一层挂观察点。
所以这正好是本仓库反复说的那条 —— **"这张表算不出数"是关于观测的事实，
"这个内核没有这件事"是关于内核的断言，前者推不出后者** —— 这次主角换成了
对照基准自己。原来那两条断言"xv6 十个指标全都有值、理由栏是 None"的测试
因此红了，红得对，改成钉"少这一个，并且说清为什么"。

### 一条测试的写法教训

`test_every_function_named_in_the_reason_is_this_kernels_own` 里原来写着
`assert len(kinds) == 5`。指标表一动（加两个、删一个）它就红，而 6 这个数
本身什么也没说明。改成跟"这趟哪些指标是 None、且没有函数映射过来"对齐 ——
**写死的数字盯的是当时的形状，算出来的集合盯的才是那条不变式。**

---

## 打点相位：量过，决定不改（#71，2026-09-03）

事件打在**函数入口**（`NF_REC_WATCHPC = 命中被关注的函数入口`）。于是同一个
里程碑在不同内核上会落在里程碑的两侧：

    xv6     allocproc 入口      任务还没造出来
    rcore   new(elf) 入口       任务还没造出来
    arceos  spawn_task 入口     任务已经造好了（就是入参），还没进运行队列

先撤回 #71 原来提的改法（把 arceos 的 spawn_task 挪到 `sched.*` 表示入队）：
入口打点时 `add_task` 还没执行，挪过去一样不准，只是换个方向不准。

### 决定：容忍，不给事件加「入口/出口」维度

四条理由，都是量的：

**一、次数一比一。**每打一次都对应一个任务诞生。而次数正是所有下游真正在用
的东西 —— 相位差不影响它。

**二、没有任何视图跨内核比较单条事件的指令号。**读了 `renderCompare`：它比的
是计数和「某指令号处的状态」，差值表里全是 count 对 count，没有「A 的
proc.create 在 X、B 在 Y」这样一行。也就是说那个真正不可比的量，界面根本没
拿出来当可比的用。**不可比的东西没被摆成可比，就还不是缺陷。**

**三、唯一把相位写进 manifest 的地方是解决过的。**全量 grep 七份 manifest，
真正描述相位的只有 `arceos.toml:412` 一处，而它是拿相位当**快照节流值的
论证**用的 —— 「默认 2,000,000 比这个内核整个多任务阶段（13,643 条指令）还
宽，唯一那一帧落在 spawn 入口、子任务还没入队，解出来只有 idle，读起来就像
个没有任务的内核」。那个问题已经被那条设置本身解决了。这不是一处没露出来的
缺陷，是一段解决方案的理由。

**四、看到出口是录制器的改动，不是 manifest 的。**插件按入口 PC 触发；负载里
虽然带了 `ra`，但没有出口观察点这回事。而「返回值在入口看不到」那一类问题，
内核侧**已经有正解** —— `nftrace` 通道，内核在 return 前主动上报（`kalloc`
的 `allocated_pa` 就在等它）。而语料里三趟录制的 nftrace 记录数**都是 0**，
连那条已有的路都还没有任何数据走过。在没有数据验证第一条路的情况下先修第二
条路，方向是反的。

### 重新开的触发条件

写下来是因为「容忍」和「拖着」从外面看一模一样。任意一条成立就该重开：

* 某个视图开始跨内核并排单条事件的指令号；
* 某个指标的定义依赖「函数体跑完之后」的状态；
* 语料里出现第一份 nftrace 记录数非 0 的录制。

三条都是**可观察的**，不是「等有空再说」。测试逼着 `decided` 里必须出现
触发条件，否则红。

### 顺带更正一句自己写错的话

G 组原来记着「rCore 的 new(elf_data) 把装映像算进来了，xv6 要到 exec/userinit
才装」。读源码发现后半句对录这份轨迹的教师版 xv6 是错的：`uvmfirst` 和
`initcode` 在 `kernel/` 下**一个都不存在**，`userinit` 只做 allocproc + 置
initproc + cwd + RUNNABLE，一点映像都不装。正确说法是**映像只经由 `exec`
进来，一次都不例外**。

### 然后又错了一次，值得单记

改完上面那句，我把另一半写成「rCore 的 `new(elf_data)` 把装映像算进来了」——
**那是从机器上另一份 rCore checkout 读的签名**，而那份 checkout 的
`TaskControlBlock::new` 收的是 `(process, ustack_base, alloc_user_res)`，
压根没有 elf 参数。拿一份对不上的源码去解释一份录好的轨迹，正是本仓库栽过的
那一跤（lab3 那份轨迹录自教师版 xv6，拿学生版解会自洽地解错）。

改法：**不靠任何源码，靠轨迹自己。**`rcore.toml` 已经把
`MemorySet::from_elf` 映射成了 `vm.from_elf`，于是「装了几次映像」是可以
直接数的。rcore-watchtest 数出来：

    27229479  proc.create
    27229498  vm.from_elf   ← 入口之后 19 条指令
    28622537  proc.exec
    28622554  vm.from_elf   ← 入口之后 17 条指令

两次装载，一次在 create 体内一次在 exec 体内 —— 间隔只有十几条指令，那就是
函数序言的长度，不可能是别处调进来的。

于是这个数站得住了：

    lab3-cowtest-mac   装映像 3 次（数 proc.exec，靠源码保证只经由 exec）  execs = 3   相等
    rcore-watchtest    装映像 2 次（直接数 vm.from_elf）                   execs = 1   少一次

**注意两边的证据强度不一样**，测试里也分开写了：rCore 那个数是从轨迹里数的，
xv6 那个数依赖「这版内核没有 initcode」这条源码结论。后者哪天不成立，钉它的
那条测试会先红。

`execs` 在 rCore 上少算了建任务时顺手装的那一次。**眼下是潜在的不是活的**
—— `execs` 只在 metrics JSON 里，`app.js` 一处都没渲染（grep 过）。所以加了
一条会红的测试盯着：哪天有人在界面上加 `execs`，先读 G 组那段。

### 多了一张表：`RESOLVED_TOLERATED`

G 组塞进已有的两张表都会说假话。它那三个词指的是**同一个里程碑在 ±1 相位上
的观测**，所以 `RESOLVED_DISTINCT`（「不是同义词」）是假的；决定又是不改，
`RESOLVED_PENDING_CHANGE`（「该改，还没改」）同样是假的。

「量过了，决定容忍」是第三种结局，得有第三个名字 —— 跟本仓库反复强调的
`absent` / `empty` / `undecidable` 必须长得不一样是同一件事。

`RESOLVED_PENDING_CHANGE` 因此空了。**空表要留着**：下一组裁完发现该改而暂时
改不动的有地方放，不至于又退回 `UNRESOLVED` 假装还缺证据。

---

## 两个内核的"第一个用户进程"，一个说得出名字一个说不出（#81，2026-09-03）

做 #71 时顺带量到的：

    rcore   os::task::add_initproc  ->  proc.initproc     已声明
    xv6     userinit                ->  func.userinit     掉进兜底前缀

`func.` 这个前缀本身的意思就是「观察点响了，但没有任何地方说过它算哪一类
事件」。可这件事说得出来 —— 两个内核都在把第一个用户进程弄起来，而且
`proc.initproc` 这个词早就登记了、rCore 也早就在用。一个说得出一个说不出，
是漏了一行映射，不是两个内核真的不一样。

**注意 xv6 那边的观察点一直是挂着的**（`userinit` 在 watchlist 的 72 条里），
所以这不是"没观测到"，是"观测到了但没归类"。这两件事在报告里长得很像，区别
只有 `func.` 那个前缀 —— 也正因为长得像，它躺了很久没人发现。

### 映射之前先量相位

G 组的教训是：**名字像不代表打点的时刻一样**。arceos 的 `spawn_task` 名字看着
是"创建"，可打点那一刻任务已经造好了。所以这次先量，不看名字：

    lab3-cowtest-mac   1770240364  proc.initproc
                       1770240369  proc.alloc      ← 隔 5 条指令
    rcore-watchtest      26132671  proc.initproc
                         27229479  proc.create     ← 隔 1,096,808 条指令

两边**顺序一样**：打点时第一个用户进程都还没诞生。xv6 的 `allocproc` 就在
`userinit` 函数体里（隔 5 条指令，那是函数序言）；rCore 的 `INITPROC` 是
`lazy_static`，`clone()` 才强制构造，而那 110 万条指令花在从文件系统里读
initproc 的映像上。

**间隔差了五个数量级，相位却是齐的。**相位讲的是顺序，不是远近 —— 这一条
值得单记，因为很容易反过来想（"隔这么远肯定不是同一件事"）。

所以这条映射不欠 G 组那笔近似账：它跟 arceos 的 `spawn_task` 不是一类，
那个是在诞生**之后**打点。

### 顺带量了一下 `func.*` 到底有多常见

    arceos-childtask   0 种
    rcore-watchtest    22 种（Stdin::readable 3300 次、virt_to_phys 1545 次……）

rCore 那 22 种**不是同一类问题**，别顺手一起改。#81 之所以是漏，是因为
rCore 已经有了 `proc.initproc` 这个词而 xv6 没用上；而 `Stdin::readable`
这类根本没有哪个内核给过跨内核的名字。给它们造词等于替一个内核发明词汇，
正是登记表要挡的事。真要动，先答的是"rcore.toml 观察了 92 个符号却只给
70 个归了类，这是有意的吗" —— 有意就照 rcore.toml 写明自己缺
`pagetable.unmap` 的那种写法记一笔。

## rcore.toml 那 43 个空白：早就写明是有意的，缺的是证据（#82，2026-09-03）

上一节结尾把问题记成"这是有意的吗"。**先更正提问本身**：rcore.toml 第 347
行早就答了 ——

> 没列的不是漏了：easy-fs 那三十来个（`Bitmap::alloc`、`Inode::find`……）
> 记成 `func.<名字>` 已经如实，硬给它们编一套类别才是这里最不该做的事。

也就是说，#82 不是"未决"，是我立条目的时候没把 manifest 自己那段读完。同一
段还写了 `phys.alloc` / `pagetable.unmap` 为什么缺（被 rustc 内联了，符号表
里没有），可见这份 manifest 记缺席一向记得挺细。

先把数字也更正了。原话"只给 70 个归了类"是没量就写的，量下来是：

    92  个观察点
    49  个有 `[event]` 映射
    43  个没有  ← 其中 rcore-watchtest 那趟真的响过 22 种

43 个里 36 个挤在文件系统和块设备那一带（19 个 `easy_fs::*`、11 个
`os::fs::*`、6 个块驱动），剩下 5 个零散在 `os::mm::*`。这就是为什么它看着
像漏：`bcache.*`、`disk.*`、`inode.*`、`file.*` 这些词**登记表里全都有**，
xv6 那边都在用。

### 但是照名字映会得到一个读得通的错数

块设备那一层三个符号，rcore-watchtest 量出来：

    515  os::drivers::block::virtio_blk::VirtIOBlock::read_block
     97  easy_fs::block_cache::get_block_cache
     33  virtio_drivers::blk::VirtIOBlk<H>::read_block

按名字推该是 `read_block → disk.io`、`get_block_cache → bcache.get`，两个词
xv6 都现成。**可这三个数对不上那个模型**：缓存夹在中间才对，外层 515 却比
最里层的驱动 33 多了一个数量级。谁调谁、哪一层才算"一次真的磁盘 I/O"，光看
名字和计数说不出来。

而 xv6 的命中率是这么算的（规范 §3.5）：`命中 ≈ bread 次数 − 磁盘 I/O 次数`。
真把 `read_block` 映成 `disk.io`，rCore 就报 515 次磁盘 I/O —— 一个不会报错、
画得出图、也解释得出来的数，而驱动实际只读了 33 次。

**这才是那句"硬编类别是这里最不该做的事"的分量所在**：风险不是留白难看，是
补上的白读得通。#71 犯的错是拿对不上的源码解释轨迹；这一条同样是"证据不够
就别下判断"，只不过这次是名字冒充证据。

### 结论

`func.<名字>` 留着。要动这 43 个，前置条件写死一句：**得先有一份跟录制用的
那个二进制对得上的 easy-fs 源码**，把 `VirtIOBlock::read_block` /
`get_block_cache` / `VirtIOBlk<H>::read_block` 三层调用关系读清楚，能解释
515 / 97 / 33 这个形状。解释得了再映，映完那三个数就是校验答案的题面。

## C 组：名字先改了，"算一类还是两类"仍未决（2026-09-03）

C 组是 `trap.page_fault`（代码按 CSR 解出来的）跟 arceos.toml 映 
`handle_page_fault` 得到的那个词。原来后者叫 `trap.pagefault`，跟前者只差一个
下划线 —— **看着像打错字，其实是两层**。

### 名字这件事跟"并不并"无关，可以先办

kinds.py 早就写着"无论定哪边都得改名"。改名的代价这次量得出来是零：
`trap.pagefault` 在**全部 14 趟里一次都没响过**，改名动不了任何数字。
改成 `trap.page_fault_handler`：守下划线约定，说得出自己是哪一层，
两种结局都用得上（并了它消失，分了它就是对的名字）。

顺带更正 kinds.py 里一句旧话："128 个里唯一不守下划线约定的"。数下来这样的
有七个：`trap.usertrap`、`trap.kerneltrap`、`fs.dirlookup`、`vm.freewalk`、
`proc.growproc`、`proc.initproc`、`trap.pagefault`。前六个**该连写** —— 它们
照抄的是 xv6 里符号的拼法，拿名字回去 grep 源码搜得到。`trap.pagefault` 两头
都不沾：既不守约定，也不是任何符号的拼法（arceos 那函数叫 `handle_page_fault`，
本来就带下划线）。所以它该改，理由不是"唯一的例外"，是"谁的拼法都不是"。

### 改名把一件本来看不见的事翻出来了

`analyze.py` 解事件类别时，**优先用录制时写进 `watchlist.json` 的 `kind`**，
不是现在 manifest 里写的那个。所以改 manifest 只管以后录的 —— 已经录下来的
五趟 arceos 里，那个观察点仍然写着 `trap.pagefault`。

录下来的东西不回头改（跟"不许重建 rCore"是同一条纪律：改了那趟录制就不能拿来
对质了），于是语料的词汇**分叉**了。分叉本身没关系，**分叉没人声明**才要命。
所以加了 `kinds.RETIRED`（老名字 -> 改成谁、为什么）和一条测试：逐个 run 读
`watchlist.json`，凡是 `kind` 不在 `KINDS` 里的，必须在 `RETIRED` 里查得到。
谁再改名不登记，那条测试就红。

### 但"算一类还是两类"这次也没定，而且比原来以为的更难

原来 kinds.py 写着这组的 0 是"看负载的 0"：arceos 那几趟恰好没缺页而已，
换个会缺页的负载再录一趟就有了，**这个便宜**。量下来这话没根据。

量的是"代码自己解出来的事件在 arceos 上出没出现过"。analyze.py 不经 manifest
直接产出四个词，五趟 arceos 里**一个都没有**：

    arceos-childtask        syscall.enter 0  trap.page_fault 0  trap.exception 0  trap.unknown 0
    arceos-tracecomplete    （同上）
    对照 lab3-cowtest-mac   syscall.enter 174  trap.page_fault 38243
    对照 rcore-proc         syscall.enter 122  trap.page_fault 2

解码器本身是好的，只是在 arceos 上什么都没解出来。arceos 全趟合计才 33 条事件
（`firmware.trap` 19、`sched.switch` 3、`proc.exit` 2、三条 `*.init`），全是
观察点打的。**连 syscall.enter 都是 0 —— 这一点"恰好没缺页"解释不了。**

所以 F 组那招（看两个词是不是在同一次事件上严格交错）这里不光缺内层数据，
**外层在 arceos 上也从来没有过**。哪怕明天录到一趟 arceos 缺页，也未必立刻
就有两边数据可对。

**重新开的触发条件因此改得更弱、也更好查**：不必等"某趟 arceos 缺页"，只要
**某趟 arceos 产出任何一条代码解出来的事件**（哪怕 `syscall.enter`），就说明
那条路是通的。反过来，要是查明 ArceOS 作为 unikernel 根本不产生这类陷入记录，
那这组该从"未决"改判成"外层在这个内核上不存在"—— 那是另一种结论，不是同一个
问题的答案。

## A 组：并了。理由不是命名口味，是 ArceOS 崩溃时全程静默（2026-09-03）

A 组是同一个 Rust lang item 的两个拼法：

    xv6     panic（老 bundle 没 kind，走 FUNC_EVENTS）  -> kernel.panic
    rCore   os::lang_items::panic                      -> kernel.panic
    ArceOS  axruntime::lang_items::panic               -> panic.enter

原来挂着的理由是"得问写 manifest 的人是不是有意单开 `panic.*` 命名空间，
**量不出来**"。意图确实量不出来。但**后果量得出来**，而且后果足够定这件事。

### 数消费者

    kernel.panic   4 个        panic.enter   0 个
      app.js:321   时间轴标红
      app.js:1133  详情里显示 panic 消息
      video.py:44  关键帧（注释原话：崩了的话这是全片最该看的一帧）
      video.py:128 **判定这趟算不算崩了**，决定加不加控制台镜头

也就是说 ArceOS 真崩一次：时间轴不标、详情不显示、视频不取那一帧、而且
**这趟不会被当成崩了**。这不是命名口味的分歧，是崩溃处理在 ArceOS 上整个
不工作。这正是 kinds.py 开头那句"后果是安静的"说的东西 —— 只不过这次安静的
不是一个指标，是一整条故障路径。

### "有意单开命名空间"这个说法没有旁证

如果 arceos.toml 是有意用 `panic.*` 跟 `kernel.*` 作对比，那它总得在别处
用过 `kernel.*`。数了：**一次都没有**（`grep -c '= "kernel\.' arceos.toml`
得 0）。所以 `panic.` 不是选出来的对比，它就是这一族在那份 manifest 里的
落脚处。

并的代价是零：`panic.enter` 全语料 0 次。

留了一条重新开的路：真想把 panic 分阶段（进入 / 打印 / 停机），按 C 组改名
后的写法加 `kernel.panic_xxx` 这种**说得出自己是哪一阶段**的词。换个命名空间
把同一件事再写一遍不叫分阶段，那叫同义词。

### 顺带：第五张表

`RESOLVED_MERGED`。前四张说不出"并完了"这个结局 —— `RESOLVED_DISTINCT` 是
"不是同义词"（假的），`RESOLVED_TOLERATED` 是"是同义词但不改"（也假的，改了），
`RESOLVED_PENDING_CHANGE` 是"该改还没改"（同样假的）。跟当初为什么要单开
`RESOLVED_TOLERATED` 是一个理由：结局不一样就得有不一样的名字。

这张表的门槛比别的高一格，因为**并词是唯一会真的丢信息的动作**：每组必须写
`merged_into`（并进哪个词）、`retired`（哪些词退休了，且每个都要在 `RETIRED`
里查得到）、`decided`（凭什么敢并 + 重新开的触发条件）。

## B 组：从录制里读出来是**三层**，不是两层（2026-09-03）

原来记的是"rcore 把两个都映到 kernel.alloc_error，arceos 分成两类"。从五趟
arceos 和 rcore-watchtest 的 `watchlist.json` 里读（**不是从源码猜的**），
实际是一条三层的链，两份 manifest 各盯不同的两层：

    1  alloc::alloc::handle_alloc_error            arceos -> panic.alloc
    2  __rust_alloc_error_handler                  arceos -> panic.alloc_handler
                                                   rcore  -> kernel.alloc_error
    3  os::mm::heap_allocator::handle_alloc_error  rcore  -> kernel.alloc_error

第 1 层是 Rust 库入口，第 2 层是编译器生成的跳板，第 3 层是内核自己那个
`#[alloc_error_handler]`。arceos 盯 1+2，rcore 盯 2+3 —— **观测的不是同一对**。

### 有一半不用等裁决就是错的

rcore 那两条撞在同一个词上。两个不同符号共用一个名字，那个计数天然读不出来：
是调用关系就数两遍，不是调用关系就把两件事混成一件。无论哪种，
`kernel.alloc_error` 在 rCore 上的意思都是"这两个符号之一响了"，没法跟别的
内核比。

**2026-09-03 改掉了**（#84）。rcore.toml 现在是：

    __rust_alloc_error_handler                  -> panic.alloc_handler
    os::mm::heap_allocator::handle_alloc_error  -> kernel.alloc_error

第 2 层跟着 arceos 叫同一个词 —— 它俩是同一个编译器跳板，arceos 那边解修饰
多带一个 `__rustc::` 前缀，裸名一样（从两边录下来的 `watchlist.json` 对出来
的，不是照源码猜的）。`kernel.alloc_error` 收窄成只指 rCore 自己那个
`#[alloc_error_handler]`。

老名字**没有退休**，所以 `RETIRED` 里没有它 —— 变的是它指的东西窄了。已经录
下来的四趟 rCore 里两个符号仍写着 `kernel.alloc_error`（分析读的是录制当时那
份 watchlist），四趟全是 0 次，所以改名动不了任何数字。

**这一组仍然不算裁决完**：改的是"一个词指两个符号"这个硬错，下面那个粒度问题
原样留着。

### 粒度定了：比第 2 层（2026-09-04）

原来打算等一趟真 OOM 再说 —— 那是把一个**静态**问题当成了动态问题。"1→2→3
是不是调用链"写在 `.text` 里，反汇编就能读，不需要它跑起来。（触发条件写成
"等录到一次 OOM"，等于给一个查得到的事实设了个永远不会到的期限。）

反汇编的是两份**跟录制对得上**的二进制 —— rCore 那份的 sha256 跟
`rcore-fs-alloc/manifest.json` 里的 `kernel_elf_identity` 逐字节相同
（`57942a68…d9f2`），所以这不是 #71 那种拿对不上的源码解释录制。

**先更正上面那张表：rCore 是四个符号，不是三个。**漏掉的是 `__rg_oom` ——
它是 `l`（local）加 `.hidden`，选点规则选不中，所以从来没进过 watchlist，
而上面那张表正是从 watchlist 读出来的。**从选中的东西里推不出总共有什么。**

rCore（每条边都是直接跳转，没有间接调用、没有条件分支）：

    alloc::alloc::handle_alloc_error            0x80212728
      ── jalr ──▶ __rust_alloc_error_handler    0x8020e1f0   8 字节，纯跳板
      ── jr   ──▶ __rg_oom                      0x80209e18   尾跳，不建栈帧
      ── jalr ──▶ os::mm::heap_allocator::handle_alloc_error  0x80209dbe

ArceOS：

    alloc::alloc::handle_alloc_error            0xffffffc080212c16
      ── jalr ──▶ __rust_alloc_error_handler    0xffffffc0802005ca   同样 8 字节
      ── jr   ──▶ __rdl_alloc_error_handler     0xffffffc080212b6a
      ── jalr ──▶ core::panicking::panic_nounwind_fmt

于是两个问题一起有了答案。

**一、是调用链，而且是 1:1 的。**每条边都是无条件直接跳转，一次分配失败每层
各响一次。所以**光看计数，取哪一层都一样** —— 这一层的选择不是精度问题，是
含义问题。

**二、第 3 层不是"一层"，是个岔路口。**`__rg_oom` 只在 crate 定义了
`#[alloc_error_handler]` 时才生成；没定义就生成 `__rdl_alloc_error_handler`
那条默认路，直接 `panic_nounwind_fmt`，再不回内核代码。**一个 crate 只会有其中
一个，不会两个都有。**所以 rCore 的四层和 ArceOS 的三层不是同一条链上深浅不同
的两个位置，是分叉后的两条不同的路。

**裁决：跨内核比第 2 层 `__rust_alloc_error_handler`（`panic.alloc_handler`）。**
三条理由，第三条最重要：

  * 它在岔路**上游**，两边都有，含义相同；
  * 它是 Rust ABI 定死的那个接缝，8 字节跳板的形状两边一模一样；
  * 因此**任何 no_std + 全局分配器的 Rust 内核都必然有它** —— StarryOS、
    AxVisor、Alien 不用各写一条规则就能对上。这正是这个仓库要的：
    可比性来自结构，不来自逐内核的手工对齐。

第 1 层和第 4 层留着，但**它们不可比，而且原因不同**：第 1 层是"库发现失败了"
（语言运行时的视角），第 4 层是"这个内核自己的处置跑了"（内核策略的视角）。
第 4 层在 ArceOS 上不存在**不是没映射，是它没定义自己的处理函数** —— 而这件
事本身是条静态可读的结论：看 `.text` 里是 `__rg_oom` 还是
`__rdl_alloc_error_handler`，就知道这个内核有没有自己的 OOM 策略。

`__rg_oom` / `__rdl_alloc_error_handler` 两边都不映。映了只会多一个恒等于第 2
层的计数（1:1 已经证了），而它真正携带的信息是**静态的**，不该靠事件去读。

这一组到此裁决完。以后有哪趟真 OOM 了，四层计数应该全相等；**不相等就是这条
结论错了**，回来重读这一段。

---

## rCore 的 inode 那一层：映了四条，但**不映的三样**才是重点（2026-09-04）

块设备那一层 #82 之后就映了（`bcache.read`、`disk.io`）。再往上 easy-fs 还有
一整层 inode，一直记成 `func.<名字>`。这次把能对上的映了过来。

### 先量后映

`easy_fs` 的函数本来就都挂着观察点（`module = ["os::fs", "easy_fs"]` 那条
规则罩着），所以不用重录就能看见它们响了多少次。`rcore-filetest` 那趟：

```
853  easy_fs::layout::DiskInode::read_at
851  easy_fs::layout::DiskInode::get_block_id
756  easy_fs::vfs::Inode::read_at
 97  easy_fs::layout::DirEntry::name
  5  easy_fs::vfs::Inode::find
  5  easy_fs::vfs::Inode::find_inode_id
  1  easy_fs::vfs::Inode::write_at
  1  easy_fs::bitmap::Bitmap::alloc
  1  easy_fs::bitmap::Bitmap::dealloc
```

映了四条，每条都照 easy-fs 源码核过语义：`Inode::read_at` = xv6 `readi`、
`Inode::write_at` = `writei`、`DiskInode::get_block_id` = `bmap`（一样是把
文件内第几块换算成磁盘第几块，依次走 direct/indirect1/indirect2）、
`Inode::find_inode_id` = `dirlookup`。

重录一趟（`rcore-fs-inode`，`--no-build`）验的：新类别的计数跟映射前那几个
`func.*` 的计数**一个不差**——

```
inode.read      756   ==  Inode::read_at          756
inode.bmap      851   ==  DiskInode::get_block_id 851
inode.dirlookup   5   ==  find_inode_id             5
inode.write       1   ==  write_at                  1
```

同时两个老锚点没动：`bcache.read` 2572、`disk.io` 849，跟 `rcore-filetest`
一模一样。也就是说这次改动只换了标签，没有多数一次也没有少数一次。

这趟同时是第一趟 rCore 满格的 fs 录制：17/17（上限 17）。`rcore-filetest`
是 16/17，差的那项是 `frame_alloc` —— 它录于 #87 的内联规则之前。

### 不映的三样，各是一种不同的"看着该映"

**一、`Bitmap::alloc` / `dealloc`：一个符号兼两个角色。** `EasyFileSystem`
里并排放着 `inode_bitmap` 和 `data_bitmap` 两个 `Bitmap` 字段
（efs.rs:13/15），共用同一个 `Bitmap::alloc`，靠 `self.start_block_id` 在
运行时区分（bitmap.rs:29）。xv6 那边是分开的两个函数，对应两个词：
`balloc` → `disk.balloc`、`ialloc` → `inode.alloc`。

所以它既不是前者也不是后者。映成任何一个，那个计数从此都把另一件事也数进去，
而且**数出来的一切看着都正常** —— 不会有任何东西报错。这跟 B 组（#84）是同
一类毛病的反面：那边是两个符号撞一个词，这边是一个符号该拆成两个词。要映得
先能按 `self` 分流，那是另一件事。

**二、`DiskInode::read_at`：在 vfs 那层底下。** `Inode::read_at` 就是转给它的
（vfs.rs:159）。两条都映会把同一次读数两遍。xv6 没有这个分层——它的 `readi`
自己就把 bmap+bread 做了。853 对 756 这个差也印证了不是一层：多出来的是
`read_all` 那条路直接调下层，没经过 vfs。

**三、`log.commit`：easy-fs 根本没有日志。** 整个 `easy-fs/src` 里 grep 不到
log / journal / transaction 一个词。最像的是 `block_cache_sync_all()`
（`Inode::write_at` 末尾调一次），可它只是把缓存里的脏块逐个写回，没有日志块、
没有原子性、没有崩溃恢复；xv6 的 `commit` 是先写日志再安装，图的正是崩溃
原子性。映成同一个词，等于替 rCore 声称了一个它没有的保证。

### 一句原则的措辞被这次改动逼精确了

manifest 里原来那句是"硬给它们编一套类别才是这里最不该做的事"。这次有四个从
那个名单里搬走了，所以得说清楚它防的到底是什么：**防的是按名字猜，不是"永远
别映"。** 判据是照源码核语义 + 先把数量出来。差一个字，两件事。

### 留下的一个洞：manifest 说不出"这个内核确实没有"

`log.commit` 现在在理由栏里显示成"manifest 里没有任何函数映射过来（也可能是
它给同一件事起了别的名字，从这里分不出来）"。这句话**不错**，但比现在知道的
弱：easy-fs 没有日志是查过源码的，不是没映。

`[[entity.source]]` 早就有 `reason` 可以写"这一章确实没有任务表"，事件类别这
边没有对应的东西。差的是个 schema：让 manifest 能声明某个类别**按设计就没有**
并附上依据，理由栏据此换一种说法。这会碰到 `_OVERCLAIM` 那道护栏（它现在
一律禁止"这个内核没有"式的措辞，因为默认情况下确实推不出来），所以得一起想，
不适合顺手塞进这次改动。已单开一条。

### 上限那句自己错了一次：漏了外部推导量

写完 fs 那部分顺手核了一遍各内核的上限，ArceOS 报的是 9/11 —— "差 2 项"。
差的是 `bcache_hits` 和 `bcache_hit_rate`。

这两项**永远补不上**。它们不映任何函数，是别的指标的差
（`命中 ≈ bread − 磁盘 I/O`），而 `metrics()` 里明写着任一被减数是 None
就整个是 None。ArceOS 的 manifest 里 `bcache.read` 和 `disk.io` 一个都没映，
所以这两个差从一开始就注定是 None。

上限只扣了 `_METRIC_KINDS` 里那八项，没扣它们，于是 11。真实上限是 9，
ArceOS 其实**顶格**。

这正是上限这个东西要消灭的那种假缺口 —— 第一版自己犯了一次，而且犯在
上线的第二天。原因是 `_METRIC_KINDS` 那张表按"指标 -> 它映哪个类别"组织，
推导量在里面根本没有条目，照着它数就必然漏。补了一张 `_DERIVED_FROM`，
并加了条反向测试：表里声明的依赖只要有一个够不着，那个指标就必须是 None
—— 算式和依赖表是两处，得有人盯着它们对上。

改完各趟的读数：

```
lab3-cowtest-mac       18/18  满格
rcore-fs-inode         17/17  满格
rcore-forktest-inline  17/17  满格
arceos-ctxsnap500       9/9   满格   <- 原来报 9/11
rcore-ch6-fs            6/17  差 11（那趟一个观察点都没挂，manifest 之前录的）
```

### 语料分两拨，老的那拨不是"观察点少"（2026-09-04）

收尾时我写过一句 caveat：「只有 rcore-fs-alloc 数据完整，早先几趟 rCore 录制
挂的观察点更少」。量完发现这句话**两处都不对**。

十四趟 rCore 录制，按 `watchlist.json` 和 `kernel_elf_identity` 数：

```
run                      started       wp  missing  elf-id      watch_source
rcore-proc               2026-08-28     0    73     -           -
rcore-ch1-bare           2026-08-29     0    73     -           -
rcore-ch2-batch          2026-08-29     0    73     -           -
rcore-ch3-array          2026-08-29     0    73     -           -
rcore-ch5-tree           2026-08-29     0    73     -           -
rcore-ch6-fs             2026-08-29     0    73     -           -
rcore-ch8-proc           2026-08-29     0    73     -           -
rcore-watchtest          2026-09-01    92     2     57942a68b4  manifest:rcore
rcore-filetest           2026-09-03    92     2     57942a68b4  manifest:rcore
rcore-forktest           2026-09-03    92     2     57942a68b4  manifest:rcore
rcore-forktest-inline    2026-09-03   102     2     57942a68b4  manifest:rcore
rcore-fs-inode           2026-09-03   102     2     57942a68b4  manifest:rcore
rcore-fs-full            2026-09-03   104     2     57942a68b4  manifest:rcore
rcore-fs-alloc           2026-09-03   108     2     57942a68b4  manifest:rcore
```

**第一处错**：不是"少"，是 0。而且看 `missing` 里装的是什么就知道为什么 ——
老那拨的 73 条是 `kalloc` / `kfree` / `uvmalloc` / `uvmdealloc`，**xv6 的符号名**。
那七趟录在 manifest 这套东西之前，当时观察点名单是 xv6 写死的那份，拿它去
rCore 的 ELF 上解，73 条一条都解不上。所以它们不是"挂得少的 rCore 录制"，
是**换内核之前的产物**，跟现在这拨没有可比性。

**第二处错**：不是只有 rcore-fs-alloc 完整。当前这拨七趟同一份 ELF
（`57942a68b4`），`missing` 都是 2，覆盖率 16~17/19。fs-alloc 观察点最多
（108）只是因为它多点了 easy-fs 那两个内联分配器。

那两条 `missing` 也不是缺口，两条都是**故意的**：

* `[mm] fn=[find_pte_create, find_pte, translate]` —— 规则留着但匹配不上。
  这次直接查了 DWARF 复核（不是照抄注释）：三个名字的
  `DW_TAG_subprogram` 带 `low_pc` 的是 0 个，`DW_TAG_inlined_subroutine`
  展开点**也是 0 个**。也就是说这回"挂不上"是真的 —— 跟 `select_watchlist`
  那次和 `alloc_inode` 那次不一样，那两次都是"没人要"被我读成了"找不到"。
  规则留着是因为它匹配不上这件事本身就是信息：换 debug build 就会命中。
* `[nftrace] fn=nftrace_commit_point` —— 内核里得先有这个探针。rCore 没编，
  `test_watchsel.py:433` 钉着它必须留在 `missing` 里。

**老那拨能不能重录？** 不能，而且不该。ch1/ch2/ch3/ch5/ch8 要换五个分支重新
构建，而构建会覆盖 `os/target/.../os` —— 当前这七趟全靠那一份 ELF 解码，覆盖
了就全变成解不开的。ch6 这一支本来就在树上，而且已经有四趟当代录制
（fs-alloc / fs-full / fs-inode / filetest）盖住了。

留着它们有别的用处：`rcore-ch6-fs` 是唯一一趟进程表解得出来的 rCore 录制
（见 test_capability_notes），零观察点这个极端情形也顺便测了兜底路径。但
**不能拿它当观察性的见证**：它的"有函数没挂上"那一支必然亮，因为什么都没挂。
`test_the_four_reasons_are_still_told_apart` 原来就是这么写的，已经改成
`rcore-filetest`（92 个观察点，仍有没挂上的）。

## 校准跑把"第一次"吃掉了：整个 rcore 语料的系统性偏置

录制要跑两趟 QEMU：先一趟不抓快照的**校准跑**（量总指令数、定位程序起点），
再一趟带追踪的。两趟挂的是**同一个可写磁盘镜像**。于是任何"只在第一次发生"
的事件，都被校准跑消费掉了，追踪跑里结构性地看不见 —— 不是漏采，是那条分支
第二次根本不会走。

发现它花的功夫值得记一笔，因为**它长得跟真结论一模一样**。`inode.alloc`
一条都没有的时候，先查的是仪器：观察点在 0x8021ac78 armed，地址对；程序跑完
了，控制台上有 `file_test passed!`；解码器没坏，同一趟里另外八十多个 kind 都
有事件。仪器、程序、解码三样都正常，事件是 0 —— 按项目的规矩，这时候该写的
是"rCore 不分配 inode"。那会是一个关于**内核**的断言，实际来源是**工具跑了
两趟**。

真正定案的证据是两份控制台日志的启动清单：

```
calibration.console.log   启动清单没有 filea   <- 这趟把它建了
console.log               启动清单有   filea   <- 于是这趟走了另一条分支
```

对应 `os/src/fs/inode.rs` 里 `open_file` 的分支：

```rust
if flags.contains(OpenFlags::CREATE) {
    if let Some(inode) = ROOT_INODE.find(name) {
        inode.clear();                       // 文件已存在：清空，释放数据块
        ...
    } else {
        ROOT_INODE.create(name)              // 文件不存在：分配 inode
        ...
    }
}
```

`ch6b_filetest_simple` 只 `open(filea, CREATE|WRONLY)` 一次。文件在不在，决定
它走哪一臂 —— 而"在不在"由校准跑决定，不由内核决定。

**偏置是整个语料级的。** 单看任何一趟都正常，得把所有跑这个程序的录制排在一起
才看得出来（下表由 `events.jsonl` 现算，不是手写的）：

```
run                 clear 臂 (共4)  create 臂 (共2)
rcore-ch8-filetest            4              0
rcore-ch8-newfile             0              2
rcore-control                 4              0
rcore-filetest                3              0
rcore-fs-alloc                4              0
rcore-fs-full                 3              0
rcore-fs-inode                3              0
```

`rcore-ch8-newfile` 是修好之后录的，也是**整个语料里唯一**一趟 `func.create`
和 `inode.alloc` 有事件的录制。反过来说，另外六趟对 clear 臂的覆盖是这个 bug
的**产物**：修好之后，同一个程序对着构建出来的干净镜像跑，永远只走 create 臂。

所以那六趟没删。它们是真数据 —— 真内核对着一个非初始状态的镜像做的真事 ——
而且 `rcore-ch8-filetest` 是当代 ch8 那份 ELF 上唯一覆盖 clear 臂的录制。
它跟 `rcore-ch8-newfile` 是同一个程序、同一份 ELF、不相交的 kind 集合，是一对
before/after。**没有重命名**：manifest 里三处出现的名字有两处在录下来的 QEMU
命令行和插件自己的输出里，改了就是伪造一条从没执行过的命令。

修法是在校准跑外面包一层 `ArtifactGuard`，无条件放回（失败那趟照样可能已经
写过盘了）。备份清单用的是 `protected()` —— devices 加 protect —— 而不是去解析
QEMU 的 `-drive file=`：后者脆得多，而多备一个 QEMU 根本不写的文件只值一次拷贝。
`inode.alloc` 随即从 0 变成 1。

留下来的限制：clear 臂现在需要**主动**准备初始状态（预置一个带 filea 的
fs.img），`--stdin-after` 不行 —— 它在等提示符**之前**送输入，而第一趟程序退出
时的提示符会让等待循环立刻返回，第二次调用可能根本没被消费。

## "所有 kind 都响了吗"：67 个里 64 个，剩下三个是内核的性质

> 2026-09-05：这里的 **67/64 已经过时**，同步那两个词补上之后是 69/66，见文末
> 「ch8 的同步原语」。没响的仍然是同样那三个，所以下面的推理没变，只有分母变了。


数这个数本身踩了两次坑，都值得记，因为它们是同一个形状 —— **清点脚本漏掉
一类条目，结果看着完全正常。**

第一次多数了三个。按 `kind = ` 裸做 harvest 会把 `batch` / `tree` / `table`
算进来，那三个**不是事件类别**，是 `[entity.source]` 的形状名（ch2 没有任务表、
ch3 是数组、ch5+ 是树）。混进来会让"三个没响"看着像"六个没响"。

第二次少数了几个，而且是自找的：`[event]` 的值**不总是字符串**，
`"__switch" = { kind = "sched.switch", args = [...] }` 这种是字典。第一版脚本
对 `[event]` 只收字符串值，又把整个 `event` 键从递归里排除掉了 —— 于是所有
带参数的映射两头都没进去，一声不响。发现它是因为另一段代码在字典上做
`v in {...}` 崩了；不崩的话那个数会一直偏小，而 63/66 和 64/67 看起来一样合理。

清点脚本得跟着 manifest 的**每一种**写法走，这跟 #63 那次"词汇窄化无声降级"
是一回事。

事件类别 67 个，64 个有事件。没响的三个：

```
kernel.alloc_error     armed 26 趟 | 有事件 0 趟
panic.alloc_handler    armed 18 趟 | 有事件 0 趟
trap.kernel            armed 22 趟 | 有事件 0 趟
```

**三个都不是仪器问题**，两条独立证据：

一、同族的对照组响了。`kernel.panic` 挂了 25 趟、在 `rcore-panic` 和
`rcore-ch3-sched` 两趟里有事件。panic 这条路从布点到解码是通的，所以上面三个
0 说的是内核。这一步不能省：这个项目里"没观测到"和"没发生"长得一样，
`inode.alloc` 那次就是仪器全对、结论全错。

二、源码里它们是无条件 panic 的分支（ch8）：

```rust
// os/src/trap/mod.rs:143
pub fn trap_from_kernel() -> ! {
    panic!("a trap {:?} from kernel!", scause::read().cause());
}

// os/src/mm/heap_allocator.rs:9
#[alloc_error_handler]
pub fn handle_alloc_error(layout: core::alloc::Layout) -> ! {
    panic!("Heap allocation error, layout = {:?}", layout);
}
```

返回类型 `!` 就是证明：这两条路走进去就不回来。`trap_from_kernel` 只在内核态
自己吃了异常时被调，`handle_alloc_error`（以及跳板 `__rust_alloc_error_handler`）
只在内核堆分配失败时被调。而 `KERNEL_HEAP_SIZE = 0x200_0000`，**32 MB** ——
量了才知道，不是印象里的 3 MB；这些 workload 不会顺手把它耗光。

所以这三个 0 是**结构性的**：健康的内核跑不出来。它们跟 `[absent]` 里那两条
（`log.commit`、`vm.unmap`）又不一样 —— 那两条是能力不存在，这三条是能力存在、
路径只有出事才走。要它们响得**故意把内核弄坏**，那测的就不是这个内核了。

留着映射的理由是 0 在这里有意义：哪天某趟录制里 `trap.kernel` 冒出来一条，
那是一个货真价实的发现，而不是"这个词一直没人用"。


## ch8 的同步原语：映汇聚点，不映那六个方法（#104，2026-09-05）

ch8 是同步那一章，而 `rcore.toml` 里同步词汇是**零**。补的时候有两件事值得记，
一件是设计，一件是差点写出来的错结论。

### 为什么不映 `Mutex::lock` / `Semaphore::down` 那六个方法

事件在**函数入口**触发（WATCHPC）。那六个方法的函数体全都带分支，进了函数不
等于事情发生了：

```rust
// os/src/sync/semaphore.rs —— count 够就直接返回，根本不睡
fn down(&self) { ...; if inner.count < 0 { ...; block_current_and_run_next(); } }
// os/src/sync/condvar.rs —— 队列空就什么都不做
fn signal(&self) { if let Some(task) = inner.wait_queue.pop_front() { wakeup_task(task); } }
```

映它们，"阻塞"就变成"有人调用过 `down()`"。多报多少取决于争用程度，事后没法修。

改映两个汇聚点，函数体是无条件的，而且每个原语最后都从这儿走（`os/src` 下
grep，八个调用点）：

```
os::task::block_current_and_run_next -> sync.sleep
    condvar.rs:45  semaphore.rs:52  mutex.rs:88  syscall/sync.rs:21
os::task::manager::wakeup_task       -> sync.wakeup
    timer.rs:111   condvar.rs:34    semaphore.rs:39  mutex.rs:100
```

两个符号在 ch8 的录制里**早就 armed 了**（`kind=None`），所以这是一次纯 manifest
改动，不用重编内核 —— 那正是"内核知识只放 manifest"想要的样子。

### 差点把录制事故写成内核性质

先在叫 `rcore-ch8-sync` 那趟里查这两个符号：armed，**0 条事件**。一个同步章的
录制里没有任何阻塞，看着像个结论。

不是。看控制台：

```
Rust user shell
>> ���...���(boot-to-exit)
Error when executing!
Shell: Process 2 exited with code -4
```

被喂进 shell 的是字面量 `(boot-to-exit)`（`record.py` 里"没有程序"的占位符），
当成命令执行失败了。**那趟从头到尾没跑过任何同步程序**，零说的是录制，不是内核。
`record.py:661` 现在有 `program != NO_PROGRAM` 的守卫，那趟是守卫之前录的。

这跟 `inode.alloc` 那次是同一个形状：下结论说"内核没走这条路"之前，先确认
仪器对着的是不是那条路。那趟留在盘上不改名 —— 名字写在它自己的 `manifest.json`
和事件流的 meta 里，改目录名只会让两边对不上，而且它记录的 QEMU 命令行是真跑过的。

### 补录之后的数

`rcore-ch8-mpsc-sem`（信号量多生产者单消费者，控制台 `mpsc_sem passed!`）：

```
sync.sleep   205
sync.wakeup  205
```

**正好 1:1** —— 跟读源码得到的预期一致：`wakeup_task(task)` 手上没任务就不会被调
（四个调用点里三个在 `pop_front()` 成功之后，一个是到期定时器）。

但**跨内核不能直接比这个数**。xv6 的 `lab3-cowtest-mac`：`sync.sleep=50`、
`sync.wakeup=1154`，23 比 1。为什么是 23 倍说不了 —— 那趟记的 `xv6-riscv_teacher`
现在不在盘上，读不到它的 `wakeup()`。所以只记下事实：两边 `sync.wakeup` 同名，
分母不同，rCore 数的是"被唤醒的任务"，xv6 数的是别的什么，要比先把 xv6 那侧量清楚。

整体覆盖随之从 67/64 变成 **69 个事件类别、66 个响过**（31 趟 rcore 录制）。没响的
仍然是 `kernel.alloc_error`、`panic.alloc_handler`、`trap.kernel` 那三个结构性的。

### 顺带：原计划里"再录几个应用能多出十一个 kind"是假的

原来排的步骤有两条是"补应用换 kind"：录 `ch4b_sbrk` 之类"三个 kind"，重打 fs.img
塞 `chN_*` 练习应用"八个 kind"。两条的前提都不成立，量出来是这样：

一、**应用早就在镜像里了。** ch8 的 fs.img 有 89 个应用，包括
`ch4b_sbrk`、`ch4_mmap0..3`、`ch4_unmap`、`ch4_unmap2`、`ch6_file0..3`。
不用重打包。

二、**再多应用也变不出 kind 来。** 69 个映射里 66 个已经响过，剩三个是健康内核
跑不出来的（要它们响得故意把内核弄坏）。也就是说可达的 kind 已经全满，
"多录一个应用 = 多几个 kind"这个算式没有余量可用。

真正缺的从来不是应用，是**词**：同步那两个词补上之前，ch8 跑再多遍同步程序也
只会记成 `func.*`。这跟 #63「词汇窄化无声降级」是同一件事 —— 缺映射的症状不是
报错，是那件事看着像没发生过。

### 一份 ELF 当不了逐章 manifest 的裁判

加完映射跑全量，`test_no_manifest_ships_a_dead_event_key` 红了：那条测试拿一份
ELF 问"每个 `[event]` 键都匹配上了吗"，而它用的是 `rcore-ch6-fs` 那趟的内核 ——
ch6 里没有 mutex/semaphore，新加的两个键在那儿当然匹配不上。

**红得有道理，但删映射是错的答案。** 量一遍手边六份 rcore 构建的死键数（章号按
"哪几趟录制用了这份构建"读出来）：

```
ee56f4f0 (ch1)  71      ed5b4cab (ch5)  28
a2d992fd (ch2)  68      57942a68 (ch6)   2
ee39fba1 (ch3)  66      022dd65e (ch8)  13
```

ch1→ch6 一路降，是能力逐章长出来。ch8 回升到 13 是另一回事：fs 那批系统调用在
ch8 这个构建里被内联了。所以**没有哪一份是超集** —— ch6 认得 fs 系统调用不认得
同步，ch8 反过来。

一份 ELF 当裁判，就分不出"打错字"和"这一章还没这个能力"，而这两者的处理方式
正相反：前者改 manifest，后者一改就丢掉真语义。判据改成**交集**：所有构建里都
匹配不上，才算打错字。实测这个交集是 0（xv6、arceos 也是 0）。

原来那个洞照样堵着 —— 验过变异体：把键拼成 `blcok_current_and_run_next`，六份
构建里全都匹配不上，测试照红。内核种类改成从 manifests 目录读，加内核仍然是
"写一份 TOML，不改代码"。

## 三趟录制一直指着**错的内核**（#105，2026-09-05）

给五趟老 run 补 `kernel_elf_identity` 的时候撞出来的。补法是拿轨迹里的物理内存
跟归档的六份 rcore 构建逐一比 ELF 入口字节（`RamImage.find_kernel_image`），命中
的那份就是当初真正跑的那个。

结果不是"补上就完了"：

| run | manifest 原先指的 | 入口字节实际配上的 |
|---|---|---|
| rcore-ch3-array | 57942a68 (ch6) | **ee39fba1 (ch3)** |
| rcore-ch5-tree  | 57942a68 (ch6) | **ed5b4cab (ch5)** |
| rcore-ch6-fs    | 57942a68 (ch6) | 57942a68 ✓ |
| rcore-ch8-proc  | 57942a68 (ch6) | **022dd65e (ch8)** |
| rcore-proc      | 57942a68 (ch6) | 一份都配不上 |

四趟里三趟是错的。它们都默认落到了归档顶层那份"代表作"（ch6）上。

**为什么一直没人发现：错的 ELF 会自洽地解错。** 两条解码路都从同一份 ELF 取进程
表的地址，换一份构建就一起搬走、一致地读出垃圾 —— 逐格比对全绿，没有任何症状。
这跟 `elfid` 那条主线是同一个东西的两面：正因为没症状，身份检查必须在解码**之前**
做，而且必须区分"没查"和"查过了"。

`rcore-proc` 是第五种情况：六份构建全不匹配 —— 它当初跑的那个构建**没归档**。写成
`kernel_elf_identity_unavailable` 并注明理由。特意先确认了入口那一页确实 dump 出来
了，所以这是"构建丢了"，不是"快照缺页"；两者结论完全不同。**没随便挑一份顶上** ——
猜错了正好落进上一段那个无症状的坑里。

### 补出来的身份得自报家门

补出来的身份跟录制时记下的长得一模一样，证据强度却不同：当时记的是"我读的就是这个
文件"，事后补的是"入口字节只跟这一份对得上"。后者足够定身份，但它是**推断**。

`elfid.compare()` 因此多认一个 `reconstructed` 键，凡是补的就先说一句。写的时候第一
版把这句话挂在函数尾部的 `out` 上，于是它在两个提前 `return` 口上被静默丢掉 —— 其中
一个正是**比对全对**那条路，也就是读的人最放心、最不会追问的那一刻。测试是照着这个
丢法写的（`test_the_reconstructed_note_survives_a_clean_comparison`），第一次跑就红。

同一条规矩的第四态：**没记** / **比不了** / **读到了且一样** / **后来推的**，四件事，
四种说法。对照组是 `rcore-forktest`（录制时就记了身份）—— 它什么也不说。

## 十九趟 run 指着一条会被下次编译覆盖的路径（#106 前置，2026-09-05）

要录 ch4 就得换分支重编，而重编会覆盖 `os/target/riscv64gc-unknown-none-elf/release/os`。
先查了一遍谁还依赖那条路径：**31 趟 rcore run 里 19 趟**。分两种：

* 11 趟 `kernel_elf` 和 `kernel_elf_archived` 都指着它（压根没归档指针）；
* 8 趟 `kernel_elf_archived` 是对的，但 `kernel_elf` 仍留着那条易变路径。

第二种最阴：粗看"有归档"就放过去了 —— 我第一遍查的时候写的是 `archived or kernel_elf`，
正好把它们盖住。分析工具的 ELF 是命令行传的，人照 manifest 里的 `kernel_elf` 抄一条
过去，重编之后抄到的就是**另一个内核**，然后得到一个自洽的错答案（见上一节）。

19 趟全部改指归档副本。判据是**本 manifest 自己记的 `sha256` 与归档副本逐字节相同** ——
比 #105 那批强：那批是拿入口字节推的，这批是当初就记下的。所以只写 `kernel_elf_repointed`
说明换了路径，**不写** `reconstructed`：身份没变，变的是指针。

改完复验：没有任何 run 的两个字段还含 `/target/`，抽验 `rcore-getpid` 逐格比对 12 个
字段全一致。

## ch4 录上了（#106，2026-09-05）

`rcore-ch4-mmap`，boot-to-exit 跑完全部内建应用，36089 条事件 / 33 个 kind，
`trace_complete: true`。新构建 `543147ea` 已归档并带 identity，录完立刻把
`kernel_elf` 改指归档副本 —— 否则下一次编译就把它变成上一节那个坑。

**没有新 kind**，跟立任务时预计的一样：69 个映射里 66 个早就响过，剩三个结构性不可
达。这一趟补的是**章覆盖**，不是词汇。值得记的是 `trap.page_fault` 响了 2 次 —— ch4
正是地址空间那章，这个 kind 在这里才有戏。

控制台末尾那句 `[kernel] Panicked at src/task/mod.rs:153 All applications completed!`
不是失败：那是 ch4 正常的收尾路径（`outcome` 记的是 `completed`）。事件流里那条
`kind: null` 也不是事件，是流头部的 `type: meta` 那行。两条都核过，没按"看着像出事"
下结论。

### ch7 也录上了，但先被环境挡了一道

`ch7` pin 的工具链是 `nightly-2024-02-25`，本机没装；rustup 去下载，报
`failed to extract package: No space left on device`。盘满了：460Gi 里只剩 258Mi。
rCore + NodeFusion 加起来才 ~1.6G，425G 的占用绝大部分不是这个项目的。

清的是**定义上就是缓存**的那些（npm `_cacache`、go build cache、uv cache、cargo 的
`.crate` 压缩包、pip/Homebrew 下载缓存），加上 rCore 自己那两个 `target/` —— 后者动手前
先确认 ch4 的 ELF 已归档且逐字节一致。**没碰** `~/.rustup` 和 `~/.platformio`：那是装好的
工具链，不是缓存；也没碰 Lark/JetBrains/浏览器那些可能存着本地状态的目录。腾出 2.2Gi。

然后**按 pin 装 `nightly-2024-02-25`**，没有改 `rust-toolchain.toml` 去将就已装的工具链 ——
那样录出来的是"另一个工具链编的 ch7"，跟课程 pin 的不是同一份，写进 manifest 的
`build_toolchain_note` 也记了这一点。

`rcore-ch7-sig-pipe`，跑 `ch7b_usertest`（16 个测例，含 sig_simple / pipetest /
pipe_large_test，三个 ch7 测例都 exit 0；另有 ch4b_sbrk 退 -11、ch6b_cat 退 -1，是这套
应用自己的结果，没去动）。**298457 条事件 / 97 个 kind**，目前最富的一趟 rcore 录制。
`outcome` 记的是 `panic`，那是录制器已经识别并解释过的那条"程序正常退出之后 shell 撞上
OpenSBI 返回 -1"的老账，跟目标程序无关。

缺的观察点只剩 3 个：两个同步汇聚点（ch8 才有）和 `nftrace_commit_point`。

### ch7 的管道和信号有语义、没词汇

这一趟印证了立任务时的预计：**没有新的 mapped kind**。但它同时暴露出反面 ——
ch7 那两样新能力全部以 `func.*`（打了观察点、manifest 里没映射）的形式露头：

```
管道  func.sys_pipe 3   func.make_pipe 3   func.Pipe::{read,write,readable,writable} 各 3
信号  func.sys_sigaction 1  func.sys_kill 1  func.sys_sigreturn 1  func.current_add_signal 1
      func.handle_signals 21897   func.check_signals_error_of_current 21897
```

ch7 比 ch6 多的六个系统调用是 dup/pipe/kill/sigaction/sigprocmask/sigreturn，而
NodeFusion 现在**没有 `ipc.*` 也没有 `signal.*` 词汇**。

后两个的次数说明了为什么不能顺手映：`handle_signals` 响了 21897 次 —— 跟
`trap.enter`（21958）几乎一比一，因为它在每次陷入返回前都被无条件调用。事件在**函数入口**
就打（WATCHPC），所以把它映成"投递了一个信号"会把 21897 次*检查*报成 21897 次*投递*。
真正表示"有信号进队"的是 `current_add_signal`，1 次。这跟 ch8 那六个同步原语是同一个坑，
处理方式也该一样：映汇聚点、映无条件的那些，不映带分支的。

已另立任务，不在本次范围内 —— 本次是补章覆盖，不是补词汇。

## 八章的词汇补齐：87 个未映射观察点 -> 53（#107，2026-09-06）

上一条留的那个任务，这次做完了。做法是先逐个**读源码**判"入口处这一下到底证明了
什么"，再决定映还是不映；一条都不是按名字猜的。

87 里 34 个拿到了词，其余 53 个**逐条写明了为什么不给**，写在 `rcore.toml` 的
`[event]` 末尾，分四类：下层（映了就数两遍）、取值（不是事件）、对面没有这东西、
还没量所以还没定。第四类只有 6 条，全部列了"要量什么才能定"。

新登记 25 个类别：ch7 的六个系统调用（dup/pipe/kill/sigaction/sigprocmask/sigreturn）、
ch8 的同步与线程系统调用十四个、`signal.raise`、`thread.{create,alloc_res,free_res}`，
外加一直没人用的 `syscall.{trace,yield}`。管道**沿用 xv6 已有的 `pipe.*`**，没另造
`ipc.*` —— 两个内核的管道是同一个东西，不该有两套说法。

### `[event]` 现在能按结构分支

ch8 逼出来一个真问题：`os::task::task::TaskControlBlock::new` 在 ch1–7 造**进程**，
在 ch8 拆出 `ProcessControlBlock` 之后造**线程**。全路径一模一样，只有签名变了。
不加区分地映成 `proc.create`，ch8 里开四条线程就报四个进程 —— 不报错、不缺失，
只是把线程数说成进程数。

TOML 的键必须唯一，所以给 `[event]` 加了候选串，**第一条 `when` 成立的胜出**：

```toml
"os::task::task::TaskControlBlock::new" = [
  { kind = "thread.create", when = { type_exists = "os::task::process::ProcessControlBlock" } },
  { kind = "proc.create" },
]
```

判据是**结构**，不是章节号 —— 跟 `[[entity.source]]` 的 `when` 共用
`probe.eval_when`。manifest 里从来没有章节号，这里也没开这个头。实测拿三份真
ELF 判过：ch5/ch7 得 `proc.create`，ch8 得 `thread.create`。

解析时强制两条：最后一条必须无条件（全带条件的话，都不成立时会静静退回
`func.<名字>`，跟没写过一样）；不在末尾的不能无条件（它会无条件胜出，后面永远
轮不上）。候选串里**每一条**的 kind 都过注册表 —— 否则把没登记的词藏进第二条
就能绕过它。

### 顺带修掉一个一直是"碰巧绿"的断言

`test_rcore_counts_pte_maps_exactly_when_it_armed_that_watchpoint` 判"这趟挂没挂上
`PageTable::map`"，用的是 `"PageTable" in name`。而 `name` 是**显示名** —— 解修饰后
的最后一段，只在这个 ELF 里撞名时才带限定。老几趟里 `PageTable::new` 撞了名、显示成
`PageTable::new`，子串就命中了：**这条断言一直靠 `new` 成立，它想问的 `map` 从头到尾
显示成 `map`，一次都没被问到。**

ch4 那份 ELF 里 `new` 也不撞名，假绿才塌。`watchlist.py` 里早写着"显示名不稳、判据
要用全路径"，测试没照做。现在 `Analysis` 多了 `watched_symbols`（取稳定的 `symbol`
字段），判据换成它。

### 重录：先量哪几章值得重录

事件类别是**录制时**冻进 `watchlist.json` 的（`analyze.py` 读 `entry["kind"]`），
所以已录的 run 不会自动显示这批新词 —— 要在轨迹里露头就得重录。哪几章值得重录
不是拍脑袋定的：拿当前 manifest 对 8 份归档 ELF 各跑一遍 `build_from_manifest`，
数 `entries` 里命中新符号的条数。

| 归档构建 | 章 | 带几个新词 | 覆盖的 run |
|---|---|---|---|
| `022dd65e` | ch8 | **25/35** | 5 趟 |
| `e989faf1` | ch7 | **12/35** | 1 趟 |
| `ed5b4cab` | ch5 | 3/35 | 2 趟 |
| `543147ea` | ch4 | 3/35 | 1 趟 |
| `ee39fba1` | ch3 | 2/35 | 2 趟 |
| `57942a68` | ch6 | 1/35 | — |
| `a2d992fd` / `ee56f4f0` | ch2 / ch1 | 0/35 | 各 1 趟 |

ch7+ch8 的并集是 31/35。剩下 4 个（`sys_trace`、`sys_yield`、`run_first_task`、
`init_heap`）只在 ch3/ch4/ch5 里没被内联掉 —— 又一次印证"某个符号只在一章缺，
通常是代码生成的事，不是语义的事"。

### ch7 已重录：词汇落地了，`when` 也在真 ELF 上验过

`os/target` 里躺的正是 ch7 那份构建，所以 `--no-build` 就能重录，不用重编、不占
额外磁盘。`kernel_elf_identity.sha256` 对上了 `e989faf1…`，是同一份二进制。

12 个新观察点全部挂上，其中 `TaskControlBlock::new` 判成了 **`proc.create`** ——
ch7 没有 `ProcessControlBlock`，候选串的兜底分支胜出。此前这条只在假 DWARF 上
测过；现在真二进制也走通了。

| kind | 计数 |
|---|---|
| `syscall.pipe` / `pipe.alloc` / `pipe.read` / `pipe.write` | 3 / 3 / 3 / 3 |
| `syscall.kill` → `signal.raise` → `syscall.sigreturn` | 1 / 1 / 1 |
| `syscall.sigaction` | 1 |
| `proc.create` | 1 |
| `syscall.dup`、`syscall.sigprocmask` | **0** |
| `heap.alloc_zeroed` | 4964 |

两个 0 是**如实的 0**，不是解码坏了：同一张观察表上的兄弟系统调用都响了，所以
仪器是好的，只是 `ch7b_usertest` 压根没调这两个。这正是"下结论说 X 没发生之前，
先确认量它的那件仪器是好的"那条纪律 —— 判据是同表兄弟，不是"我觉得应该响"。

管道那四个数彼此对得上（一次 `sys_pipe` 造一根管道，读写各 3 次），信号那条链
也对得上（kill 一次 → 置位一次 → sigreturn 一次）。这种内部一致性比单个数字更
能说明词映对了。

### `heap.alloc_zeroed` 不能拿来比较不同趟

同一份二进制、同样的参数，连录两趟，语义计数**逐个相同**，只有
`heap.alloc_zeroed` 不一样：4964 vs 4961。

这个差不是噪声引起的误差，它有具体来源：这趟的 `record_warnings` 早就写明，目标
程序正常退出**之后**，shell 回到提示符继续读输入，而 OpenSBI 取不到字符返回 -1、
被当成 0xFF 灌进行缓冲区，把 8 KB 用户堆撑爆。也就是说 `heap.alloc_zeroed` 有一
截在数**退出之后的空转**，而空转多久取决于 QEMU 什么时候被收掉 —— 挂钟决定的。

所以：ch7 的 `heap.alloc_zeroed` 不是稳定量，拿它比不同趟会看到幻影差异。其余
语义计数是稳定的。

### `outcome` 是挂钟敏感的，这次翻了面

重录前这趟记的是 `outcome: panic`，重录后是 `completed`。二进制没变、icount 确定
性执行，所以变的只能在宿主侧；而 `record.py` 自 2026-09-05 以来一次没改过。

原因在驱动循环：它轮询 guest 控制台，每一圈**先**查 `done_markers`、**后**查
`panic_markers`。哪个标记在某次轮询时已经到了，就由哪个定性。这趟控制台最后确实
有一句 `Panicked at src/lib.rs:30, Heap allocation error` —— 就是上面那段说的、与
目标程序无关的堆爆。观察点从 116 涨到 128，插件每条指令多做一点事，guest→host
的时序跟着变，于是轮询落点变了。

按这趟自己的 warning，`completed` 才是对的判定（那次 panic 发生在目标程序正常
退出之后）。连录两趟都是 `completed`，在当前观察表下是稳的。

但**结论不该是"修好了"**：同一份二进制两次录制给出过两种结局，说明 `outcome`
的判定本身依赖挂钟，只是这次恰好从错的翻到了对的。已单开任务；这里只记事实。

### ch8 重录：`thread.create` 少报了 62%，被算术揪出来

ch8 要真编一次（`os/target` 里躺的是 ch7 的产物）。重编出来的 ELF 跟归档
**逐字节相同**（sha 仍是 `022dd65e`），所以这一章的 5 趟彼此仍然可比，归档也不用
加新条目 —— 顺带说明这份构建是可复现的。

25 个新词全部挂上。同一个 manifest 键 `os::task::task::TaskControlBlock::new`，
在 ch7 上判成 `proc.create`、在 ch8 上判成 `thread.create`，进程那三个词交给
`ProcessControlBlock::{new,exec,fork}` —— 按结构分支的设计在两个方向上都跑通了。

`rcore-ch8-mpsc-sem` 的数字互相印证：`syscall.semaphore_down` 和
`syscall.semaphore_up` **都是 1600**，严丝合缝的生产者-消费者配对。

**然后有一个数不对。** `syscall.thread_create` 响了 5 次，`thread.create` 只响了
3 次。而 `sys_thread_create`（thread.rs:23）里那句
`Arc::new(TaskControlBlock::new(...))` 是无条件的 —— 没有提前返回、没有分支 ——
所以 5 次系统调用必然造 5 个 TCB。3 不可能是对的。

3 是从哪来的：`proc.create` 1 + `proc.fork` 2 = 3，正好是 `process.rs` 那两个
调用点。查 DWARF 和符号表就实锤了：

    符号表  0x80217084  size=398   独立副本，被 process.rs 调
    内联点  0x802161b6  host=os::syscall::thread::sys_thread_create

观察点挂在独立副本上，`sys_thread_create` 里那次被内联了，5 次执行一次都没碰到
观察点。**线程数少报 62%（3/8），而且没有任何一处报错、没有任何一处对不上。**
解码器是好的，观察点也确实挂上了 —— 只是挂在了源码眼里"同一个函数"的两个地址
中的一个。这正是这套东西存在的理由：不是抓崩溃，是抓那种自洽的假数。

修法是现成的，而且不用重编：`[[watch]]` 早就有 `inlined = true`，这份 manifest
里已经为 `frame_alloc` 和 `alloc_inode` 用过两回。加第三条窄规则
（`module = "os::task::task", fn = ["new"]`）之后 `thread.create` = **8**，
分解得干干净净：5（来自 `sys_thread_create`）+ 3（来自 `process.rs`）。

按 `os::task::task` 而不是 `os::task`：实测后者会连 `TaskUserRes::new` 的两个
展开点一起收进来，那俩没有语义映射，只会变成 `func.new` 噪声。实测这条规则只在
ch8 上加 1 个点（129→130），ch7/ch6/ch5 一个都不多 —— 规则窄到只在需要它的构建上
生效，这是第三次重复同一条教训了（前两次见上面那两条 `inlined` 规则的注释）。

**这条规则一开始放错了位置**，`test_manifest_lint.py` 抓了出来：我把它挨着另外两条
`inlined` 规则放在文件靠后处，读起来成组、顺眼，但选点是先到先得，而更靠前的
`module = "os::task"` 已经把它整个罩住了。挪到那条前面之后 lint 转绿。

值得记的是**为什么 lint 抓得住而实测抓不住**：把它挪回去，`thread.create` 照样是
8 —— 因为罩着它的那条没写 `inlined = true`，压根不认领内联点，所以实际没抢走。
换句话说这条规则当时是"侥幸能用"。哪天有人给宽的那条加上 `inlined = true`
（完全合理的一步），窄的就静静失效，`thread.create` 掉回 3，跟这一节开头描述的
故障一模一样。lint 管的是**规则之间的关系**，实测只管当下这份 ELF 的结果 ——
这就是为什么两样都要。挪完之后四份 ELF 重量一遍确认没变：ch8 130（内联点仍判
`thread.create`）、ch7 128、ch6 108、ch5 58，两个 `TCB::new` 地址的
`args`/`rate` 也都一致。

### 哪些计数能跨趟比，哪些不能

重录暴露出一个必须说清楚的区别。事件在函数**入口**触发，所以计数回答的是
"内核被要求做这件事多少次"，而不是"这件事发生了多少次"。对自旋轮询来说，这两者
差得很远：

| 计数 | 稳不稳 | 为什么 |
|---|---|---|
| `thread.create`、`proc.fork`、`syscall.thread_create`、`semaphore_down/up` | 稳 | 一次逻辑事件一次调用 |
| `syscall.waittid` | **不稳**（106 vs 105） | 线程没退出时内核返回 -2，用户侧 `user/src/lib.rs:317` 是 `loop { match sys_waittid { -2 => yield_() } }` —— 数的是**轮询次数**，由调度决定 |
| `heap.alloc_zeroed` | **不稳**（4964 vs 4961） | 有一截在数目标程序退出之后 shell 的空转 |

两个不稳的都不是缺陷，是**这个数本来就该这么理解**。但拿它们比较不同趟会看到
幻影差异，所以在这里点名。

"稳"那一行还得排除掉限流的可能，否则说的就是限流后的数。查的时候差点被一个
同名字段坑了：`proc.fork` 打出来是 `throttle=True`，看着像被抽稀了。不是 ——
manifest 里的 `throttle` 是**事件限流率**，落到 `WatchEntry.rate`；而
`WatchEntry.throttle` 是另一回事，由 `snapshot == "event"` 推出来，管的是**附带的
快照**要不要被插件端限流。两个字段同名、隔一层、含义还相反，`watchlist.py` 自己
的注释管这叫"历史包袱"。实测这四个观察点的 `rate` 都是 0：

    0x80213ce2  proc.fork      esnap=True   rate=0
    0x802161b6  thread.create  esnap=False  rate=0
    0x80217084  thread.create  esnap=False  rate=0
    0x80212d90  proc.create    esnap=False  rate=0

也就是说 `proc.fork` 只有快照受限，计数一条不少，上表那一行成立。

顺带记一条空的：`syscall.mutex_*` 和 `syscall.condvar_*` 在 5 趟 ch8 里**全是 0**。
这不是没挂上（它们都在观察表里，同表的信号量系统调用响了 1600 次），是这套
workload 压根没有用互斥锁和条件变量的程序。要验证这几个词，得再录一趟跑
`ch8b_mut_*` / `ch8b_condsync_*` 的。

### 100 个词里 16 个从没响过；查下去查出两件不一样的事

上一节那条空的引出一个该系统地问一遍的问题：manifest 声明的词，有多少在**任何一趟**
录制里出现过？跨 33 趟 rCore 录制统计，100 个声明的词里 16 个一次都没响。

**先说量错了一次的地方，因为这一次的教训比结果本身有用。** 头一版是拿
`events.jsonl` 里的 `kind` 跟 `watchlist.json` 里的 `kind` 做差集算的，得到一张
漂亮的"挂上了但从没响"表，38 项。表是假的：`events.jsonl` 存的是**探针给的原始
名字**（`func.sys_semaphore_down`），语义词是 `analyze.py` 事后拿 watchlist 关联
出来的。两份产物**本来就不该一致**，做差集只会得到一堆假象。

戳破它的是一个我自己刚量过的数：表里说 `syscall.semaphore_down` 从没响过，可上一
节明明记着它响了 1600 次。**不是数据错了，是仪器用错了。** 换成 `Analysis` +
`build_events()` 重算，同一趟 `rcore-ch8-proc` 从"4 个词"变成"70 个词"。

改对之后，16 个词分成性质完全不同的两类。

#### 一类：workload 没跑到（8 个）

`syscall.mutex_*`、`syscall.condvar_*`、`syscall.sleep`、`syscall.gettid` 在 ch8
上都挂上了，只是这 5 趟没有用到它们的程序；`syscall.trace` 只在 ch4 存在（2025S
的 lab 加的），`syscall.sigprocmask` 只在 ch7 存在。补录一趟就有。

`trap.kernel`、`kernel.alloc_error`、`panic.alloc_handler` 是错误路径 —— 要内核
自己出问题才响。这三个"没响"是**好消息**，不该去凑。

#### 另一类：函数被内联了，词就消失了（3 个）

`heap.init`、`syscall.yield`、`syscall.dup` 是另一回事。查符号表和 DWARF：

    init_heap    ch5 符号表有 0x80209f60   ch6 起只剩内联点（host os::mm::init）
    sys_yield    ch3/4/5 符号表有          ch6 起只剩内联点（host os::syscall::syscall）
    sys_dup      ch7 符号表有 0x8020b2c2   ch8 只剩内联点（host os::syscall::syscall）

没有改名、没有删掉，就是**不再作为符号存在**。而且两个的宿主都是
`os::syscall::syscall` 那个分发函数 —— 章节往后走、分支越加越多，编译器把小的
分支一个个折进去。这不是三个孤立的个案，是个会一直复发的系统效应，所以没有一个个
手工修，而是问了一遍"这份构建里哪些 `sys_*` 只以内联点存在"。答案：ch3 有 2 个、
ch5 有 2 个、ch6 和 ch7 各 1 个、**ch8 有 11 个**。

#### 但这跟 `thread.create` 那件事性质相反，差点看错

11 个听着像个大盲区。不是 —— **系统调用有第二件仪器**。陷入边界上的
`syscall.enter` 直接从 trap frame 里读调用号，内联不掉它。实测
`rcore-ch8-filetest`：

    64   write     1359      124  yield      9
    63   read      1353      220  fork       2
    260  waitpid     10      221  exec       2
    93   exit         1       56  openat     2 / 57 close 2

正是那些"挂不上"的调用，一条不少。

所以两件事看着一样、其实相反：

| | 第二件仪器 | 内联的后果 |
|---|---|---|
| `TaskControlBlock::new` | 没有 | **真盲区**，线程数少报 62% |
| `sys_yield` / `sys_dup` 等 | `syscall.enter` | 事件不丢，**丢的是词** |

后者是词汇不自洽：查 `syscall.yield` 一条没有，查 `syscall.enter{syscall="yield"}`
有 9 条。加第四条 `inlined` 规则（`fn = ["sys_*", "syscall"]`，用通配符而不是把
系统调用抄一遍）之后对齐了，加点数 ch3 11→14、ch4 42→43、ch5 57→59、ch6 107→108、
ch7 127→128、ch8 129→140，全部落在已声明的词上。

**"声明的词从没响过"不等于"这件事没被观察到"** —— 也可能是另一件仪器用别的名字
记下来了。这是这一轮里第二次栽在"先确认量它的那件仪器是好的"上。

### 每份 Rust 内核都往 0x0 挂了一个观察点

顺着上面查 ch8 的时候，`syscall.enable_deadlock_detect` 冒出来一个对不上的地方：
它不在"从没响过"的名单里（5 趟里每趟响 2-3 次），可扫描说它在 ch8 只以内联点存在、
而且没挂上。两个都对不了。

把事件打出来，`pc` 是 **0x0**。对照一条正常的：

    proc.create   pc=0x80212d90  func=_ZN2os4task7process19ProcessControlBlock3new17h...
    thread.create pc=0x80217084  func=_ZN2os4task4task16TaskControlBlock3new17h...
    enable_...    pc=0x0         func=os::syscall::sync::sys_enable_deadlock_detect

`func` 的形态就是判据：真观察点带的是**符号表里的 mangled 名**，这一条带的是
**DWARF 的 demangled 路径**。它是从 DWARF 那条路进来的，而地址是个墓碑。

链接器 `--gc-sections` 回收掉一段代码之后（在 Rust 内核上，通常是因为那个函数被
内联到了每一处调用点、独立副本没人要了），`DW_TAG_subprogram` 那条记录还在，只是
`DW_AT_low_pc` 被写成 0。`_inline_site` 早就挡着 range 表那一侧的墓碑，注释里还
专门写了"挂上去就是往 0x0 挂"；`DW_AT_low_pc` 这一侧一直漏着。

量了一遍，规模比预想大得多 —— 这不是边角情况，是**常态**：

| ELF | subprogram | 其中 low_pc=0 |
|---|---|---|
| arceos-55f7257f | 1027 | 762 |
| rcore-022dd65e (ch8) | 899 | 657 |
| rcore-57942a68 (ch6) | 836 | 630 |
| xv6-c6b612c6 | 265 | **0** |

xv6 是 C，没有单态化、内联也没这么狠，一个都没有 —— 正好当对照组。

平时不出事，因为大多数墓碑函数没有 watch 规则匹配。一旦匹配上就挂到 0x0，而且
产物看着完全正常。每份 rCore 构建正好有一个，每章还不是同一个函数：

    ch4  heap.realloc                     __rust_realloc
    ch5  （无词）                          take_current_task
    ch6  （无词）                          kernel_token
    ch7  （无词）                          kernel_token
    ch8  syscall.enable_deadlock_detect   sys_enable_deadlock_detect

ch8 那个最糟，因为它带着一个已声明的词：报出来的 2-3 次不是那个函数，而那个函数
真正的函数体（内联点 0x80218380）一次都没被观察到。**同一个词既是假阳性又是
假阴性**，且每一项自洽。

修法是把 `_in_exec` 那个判断补到 subprogram 这条路径上。但**不是丢掉，是把
`low_pc` 置空** —— 丢掉的话"这个 build 里没有这个函数"和"有、但没有独立副本"就
长得一模一样了，而后者在优化编译的 Rust 内核上是常态。置空会让它落进 `watchsel`
里"匹配上了但没有 low_pc"那一类，那一类本来就按子系统报数。顺带修掉一个隐患：
`watchsel` 那边是 `by_addr.setdefault(fn.low_pc, c)`，六百多个墓碑全撞在 key 0 上，
谁先来谁赢。

改完之后三个内核都没有零地址观察点了，xv6 一个点都没动（141 个，墓碑 0 个），
每份 rCore 正好少一个。`thread.create` 的两个地址都还在。

`test_dwarf_tombstones.py` 钉住这条。里面有一条是专门防空转的：先断言这份构建
**确实有**墓碑要挡，否则"没有零地址"在空集合上永远成立 —— 把过滤整个删掉也照样
绿。实测把修复关掉，7 条里红 3 条，包括这条防空转的。

### `syscall.gettid` 录不到：不是这个词不存在，是这台机器上量不了

全仓 `user/src/bin` 里用 `gettid` 的只有两个程序，都是 ch8 的死锁测试：

    ch8_deadlock_sem1    ch8_deadlock_sem2

两个都跑不出结果，但原因不一样，得分开写：

**sem1 是真的挂死。** 它的设计前提是"内核检测到死锁、`semaphore_down` 返回
`-0xdead`"，末尾 `assert!(failed > 0)`。可本章内核的 `sys_enable_deadlock_detect`
是个空壳 —— 正是上一节里 ch8 那个被 `--gc-sections` 回收掉的墓碑函数。没有检测就
没有 `-0xdead`，三个线程真的互相等下去，`waittid` 永不返回。**上一节那个 DWARF
异常提前预告了这里的运行时行为**：一个什么都不做的函数会被内联掉（留下墓碑），
也同样检测不出死锁（挂死）。同一个事实的两个侧面。

**sem2 不该挂。** 它的资源序列是构造成无死锁的（tid1/tid3 拿到信号量后随即释放，
tid0/tid2 等的正是那两个），不依赖检测也能跑完。但实测 200 秒里控制台除了
`>> ch8_deadlock_sem2` 一个字都没吐出来 —— 没跑完，也没报错。它慢在
`sleep(1000)` 是 **guest 时间**，而 `-icount shift=3` 加 140 个观察点之下，guest
时间和挂钟时间差得很远。

**为什么不接着录。** 轨迹增长约 9.5 MB/s，200 秒就是 1.9 GB。试过把快照压到最少
（`--snapshots 2 --boot-snapshots 1`），大小几乎没变 —— 撑起体积的是采样流不是
快照。采样也调不稀：`--sample-insns 4000000` 之后校准直接失败
（"校准跑没有拿到任何指令计数"），因为校准的指令总数就是从采样流里数出来的。
这台机器上没有那么多空间，所以这个词记成**量不了**，不是"没响过"。

### 录制被外层杀掉之后，QEMU 会活着继续写一个已经删掉的文件

排查上面那件事的时候踩到的，值得单独记，因为症状完全指向别处。

外层 `timeout` 杀掉 `python -m nodefusion.host record`，QEMU 不一定跟着死。它会
继续按原参数往 `runs/<name>/trace.nfb` 写。此时就算把整个 run 目录 `rm -rf` 掉，
**空间也不会回来** —— Unix 上删掉一个仍被进程打开的文件，只是摘掉目录项，块要等
最后一个 fd 关闭才释放。表现就是 `rm -rf` 掉 1.2 GB 之后 `df` 纹丝不动。

它在下一次录制时报出来的样子是这个：

    calibration.qemu.log:
      qemu-system-riscv64: -device virtio-blk-device,...: Failed to get "write" lock
      Is another process using the image [user/.../fs.img]?

而 `record` 把这一步的失败翻译成了

    RecordError: 校准跑没有拿到任何指令计数，说明插件没有真正挂上。
                 请检查 QEMU 是否带 --enable-plugins。

**这句提示指错了方向**：插件挂上了（`calibration.qemu.log` 第一行就是"已挂载"），
挂不上的是磁盘镜像。照着提示去查 `--enable-plugins` 查不到任何东西。

排查动作是 `pgrep -f qemu-system-riscv64`；`kill -9` 之后空间才真的回来。

### "还有 N 个词没响过"——这个数一直把两种毛病混在一起数

之前记的是"8 个词没响过"。重新量了一遍（35 趟 rcore 录制，armed 取
`watchlist.json` 里的 kind，fired 取 `Analysis.build_events()` 解出来的 kind），
得到 5 个。**这 8→5 不是进展**，只有一个是真修好的，其余是口径变了。

拆开来是两类完全不同的东西，修法也完全不同：

**一、挂上去了，但一次没响（5 个）**

    kernel.alloc_error      挂 28 趟    错误路径，本来就该不响
    panic.alloc_handler     挂 24 趟    同上
    trap.kernel             挂 28 趟    同上
    syscall.gettid          挂  7 趟    量不了，见上一节
    syscall.sigprocmask     挂  1 趟    只有 ch7 有，得切分支重编

前三个不响才是对的 —— 它们响了说明内核出事了。真正欠着的只有后两个。

**二、声明了，但从来没挂上去过（当时 2 个，现在 1 个）**

    heap.init        <- os::mm::heap_allocator::init_heap    已修，见下
    syscall.trace    <- os::syscall::process::sys_trace      只有 ch4 有这个函数

这两个在 `rcore.toml` 的 `[event]` 里登记着，`model/kinds.py` 里也登记着，但
**35 趟录制里一趟都没被挂上**。所以它们压根进不了"armed - fired"这个差集 ——
不是变好了，是被口径漏掉了。

它们其实每趟都在报，就在 `manifest.json` 的 `watchlist_missing` 里：

    [event] 'os::mm::heap_allocator::init_heap' 没匹配上任何观察点
    [event] 'os::syscall::process::sys_trace' 没匹配上任何观察点

`[event]` 那张表只负责给**已经匹配上的**观察点改名，它自己不会去挂点。函数被
内联掉、或者本章根本没有这个函数，这一条就落空。

**为什么必须分开数。** 两类要的动作不一样：第一类缺的是**能触发它的程序**（换
个 workload 重录就行）；第二类缺的是**观察点本身**（得先在 `[[watch]]` 里补规
则，或者加 `inlined = true`，光重录一万遍也不会变）。混着数出来的那个 N，指不
向任何一个具体动作。

这一轮真正修好的是 `syscall.dup`：它一直挂着（4 趟），只是没有哪个 workload 走
过重定向。用 `--program "ch6_file0 > nfout.txt"` 录一趟就响了 —— `--program` 那
个串是**原样送进 shell** 的（`send(f"{c.program}\n")`），所以 `>` `<` `|` 都能
直接用，不用重编内核。那一趟 0.95 秒、31 MB，`syscall.dup` 1 次、`open` 3 次、
`close` 4 次，pc=0x8021741c 带的是符号表里的 mangled 名（即 `sys_dup` 内联进
`syscall()` 的那个点），不是墓碑。

`heap.init` 属于第二类，修法就不一样了：给 mm 那条 inlined 规则点名
`init_heap`（见 `rcore.toml`），7 份归档构建里 4 份挂上了。重录之后它在
`0x8021478c` 响了一次 —— **和先前从 DWARF 静态量出来的地址一模一样**，带的
`func` 是 `_ZN2os2mm4init17h…E`，也就是把它内联进去的那个宿主函数
`os::mm::init`。这正是内联点该有的样子（事件报的是宿主的符号名，不是被内联
函数自己的）。

复量一遍，口径没动：armed 99 → 100、fired 163 → 164、never fired 仍是 5 ——
`heap.init` 同时进了两个集合，所以它是从第二类里消失的，不是掉进第一类。第二
类现在只剩 `syscall.trace`，它要 ch4 的内核才谈得上挂。

## 一个词同时表示四件事：`panic_markers` 把工具的副作用栽给了内核（#109，2026-09-06）

原来记的现象是"同一份二进制两次录制给出过两种结局"。量下来，比那条更硬：
**同一批语料里就躺着两种结论，而且它们的证据一模一样。**

    run             outcome    ELF        退出码  panic@  提示符@  wall
    rcore-mmap      completed  57942a68     -1     3584    3712    0.89
    rcore-setprio   completed  57942a68     -1     3586    3717    0.86
    rcore-spawn     completed  57942a68     -1     3585    3678    0.88
    rcore-unmap     panic      57942a68     -1     3584    3712    2.11

同一份 ELF、同样的失败方式、标记位置逐字节相同，四趟里三趟记 completed、一趟
记 panic。那 1.2 秒的挂钟差正是两个分支的收尾等待之差（panic 睡 1.5 秒，
completed 睡 0.3 秒）—— 也就是说，结局不同不是因为发生的事不同，是因为**轮询
恰好落在哪一刻**。

### 真正的毛病不在轮询，在一个词被当四个词用

`rcore.toml` 里写的是 `panic_markers = ["Panicked at"]`。这一条同时匹配四种
完全不同的事（29 趟 rcore 语料，逐条看过）：

    [kernel] Panicked at src/task/mod.rs:135 All applications completed!   正常关机
    [kernel] Panicked at src/syscall/mod.rs:82 Unsupported syscall_id      真的内核崩了
    Panicked at src/bin/ch4_unmap.rs:18, assertion failed                  用户程序断言失败
    Panicked at src/lib.rs:30, Heap allocation error                       shell 被 0xFF 撑爆

后两种里**内核好好的**。第三种是被观测的程序没通过测试；第四种更糟 —— 那是
我们自己的 `stdin_preload` 造成的：没程序可送时 shell 读空缓冲区拿到 0xFF，
撑爆 8 KB 用户堆。把它记成 panic，等于把工具自己的副作用栽给被观测的内核。

分界线是现成的：rCore 的内核 panic 带 `[kernel] ` 前缀（`os/src/console.rs` 里
加的），用户态的没有。语料里 100% 对得上。

### 改了三件事

**一，`panic_markers` 收窄成 `["[kernel] Panicked at"]`**，只表示"内核崩了"。
`rcore-panic` 那趟（`Unsupported syscall_id: 9999`）是语料里唯一一次真的内核
崩溃，收窄之后它仍然判 panic。

**二，新增 `halt_markers`**，表示"guest 不会再有进展了"。这跟"内核崩了"是两个
问题：一个决定结局，一个决定**什么时候收手**。合在一个字段里，就只能拿"内核崩
没崩"去回答"还要不要接着等"。rCore 的 `halt_markers` 就是原来那条宽的
`Panicked at` —— 它本来就是干这个用的。留空则退回用 `panic_markers`，xv6 那边
行为不变。

**三，新增 `exit_marker`**，认 shell 自己报的退出行：

    exit_marker = 'Shell: Process \d+ exited with code (-?\d+)'

抄自 `user_shell.rs`。为什么它比提示符可靠：它是 shell **直说**的"程序退出了、
退出码多少"，而提示符只能拿来推断；而且它出现得更早 —— 28 趟实测无一例外，
比第二个提示符早 36~37 字节。**不是一个定值**：差的那 1 字节就是退出码本身
的长度（退出码 `0` 的 17 趟是 36，`-1`/`-2`/`-4` 的 11 趟是 37）。真正能拿来
当判据的不变量只有"这个间隔恒为正"。顺带把退出码取了出来。`completed` 说的是"跑完了"不是"跑成功
了"：`rcore-sbrk` 是 -2、`rcore-watchtest` 是 -4，以前退出码无处可看。

### 判定改成纯函数

`_verdict(console, mark)`：给定完整控制台文本，答案唯一。轮询循环只负责判断
"结束了没有"。这样同一份 `console.log` 离线重算能得到同一个结论，也能单测 ——
`_drive_shell` 在这之前是 `tests/README.md` 里明写着"没有覆盖"的。

有一处必须留着等待：用户程序自己 panic 之后，shell 报退出码要更晚 —— 四趟用户
panic 的实测间隔是 56~94 字节（`rcore-spawn` 56、`rcore-mmap` 91、
`rcore-setprio` 94）。轮询若正好落在这中间就会看到一个
halt 却看不到退出行。所以循环看到 `guest_halted` 时先等 1.5 秒（这段等待本来
就有，是给插件写崩溃快照用的）再拿完整文本重判一次。

### 拿新判定重算整个语料

35 趟里 32 趟结论不变，3 趟变：

    rcore-unmap    panic -> completed（退出码 -1）   跟它那三个同样的兄弟一致了
    rcore-ch5-tree panic -> guest_halted            boot-to-exit，内核根本没崩
    rcore-ch6-fs   panic -> guest_halted            同上

另有 25 趟第一次带上了退出码。

`guest_halted` 是新加的结局值。它说的是"内核没崩，但 guest 回不来了"——
跟 panic 分开，因为在 rCore 上这一类基本都是我们自己造成的。`video.py` 早就
按 `outcome not in ("completed", None)` 判异常，新值不会被误当成正常。

### 实机复核

在 ch8 的构建上重跑了那个引发分歧的程序：

    rcore-verdict-unmap  ch4_unmap  outcome=completed  exit_code=-1  wall=0.92

控制台形状跟当年的 `rcore-unmap` 一样（用户程序断言失败 -> shell 报 -1 ->
提示符），结局不再是 panic，0.92 秒也说明没再走 panic 分支那 1.5 秒的等待。

### 顺带扒出来一件事：`(boot-to-exit)` 是被当成命令送进去的

有 shell 的内核上跑 boot-to-exit，`_drive_shell` 会把字面量 `(boot-to-exit)`
当命令送给 shell：

    >> (boot-to-exit)
    Error when executing!
    Shell: Process 2 exited with code -4

以前这趟记 `completed`，看不出任何异常；现在退出码 -4 把它暴露出来了。这是
退出码该起的作用。**这不是这次改动引入的**，是原本就有、原本看不见。

---

## 那个"要量的比值"取不到，而取不到就是答案（#112，2026-09-06）

`rcore.toml` 里挂了很久一条待办：`add_task` 到底是不是 `sync.wakeup` 的下层？
写的判据是量两者的比值 —— 相等就说明它只是 wakeup 的实现细节，不该有词；大于
就说明 fork / spawn 那几条路也走它，那它是独立的一类。

这个比值**取不到**。不是数据不够，是它在结构上就不存在：

    ch7   有 manager::add_task           没有 wakeup_task（ch8 才引入）
    ch8   有 manager::wakeup_task        add_task 的符号在二进制里没了

两者从来不在同一趟里同时武装，比值无从谈起。ch8 的 add_task 在源码里好好的
（`os/src/task/manager.rs:66`），是被内联或 gc 掉了 —— 而 watchlist 的
`missing` 里也不会报它，因为规则是按模块选的，没有哪条**点名**要 add_task 然后
落空。"没在名单里"和"名单说找不到"是两件事，这里是前者。

### 该问的是另一个比值

不是"跟 wakeup 比"，是"跟**所有调它的东西**比"。ch7 的 add_task 有三个调用点，
`rcore-ch7-sig-pipe` 实测：

| 事件 | 次数 | 调用点 |
| --- | ---: | --- |
| `sched.yield` | 7373 | `task/mod.rs:53`（suspend_current_and_run_next） |
| `proc.fork` | 62 | `syscall/process.rs:48` |
| `proc.initproc` | 1 | `task/mod.rs:123` |
| **合计** | **7436** | |
| `func.add_task` | **7436** | |

逐条对上，不差一次。三个调用点每一个都已经有词了，所以 add_task 再给一个词，
是给同一批时刻起第四个名字，而且会让"一共几个事件"重复计数。**归第一类，不映。**

顺带把同批的另外几个也量了：

* `remove_from_pid2task`（ch7）62 次，`proc.exit` 也是 62 —— 严格 1:1，
  退出路径的下一层。不映。
* `take_current_task`（ch5）仍然定不了，但理由变了：不是"没重录"，是**只有一趟
  武装了它**，只响 2 次，跟 yield 11 / switch 25 / exit 1 都对不上。n=2 单趟，
  分解不出东西。
* `MapArea::unmap` 从待办里删掉了 —— 它早就在 `[absent]` 的 `vm.unmap` 那条裁
  完了，带着实测数。两处记同一件事，迟早不一致。

### 掉出来一件更要紧的：ch8 的 `proc.exit` 数的是线程

`remove_task` 和 `remove_from_pid2process` 不属于第一类。三趟实测它俩**永远一起
响、次数完全相同**（ch8-sync 1/1、ch8-mpsc-sem 1/1、ch8-usertest 65/65）——
同一刻的两个符号，所以最多该有一个词。但它们跟 `proc.exit` **不**相等：

    rcore-ch8-usertest    proc.exit 101    remove_* 65    thread.create 102

差在哪儿源码里写着：`remove_from_pid2process` 被 `if tid == 0` 罩着
（ch8 `os/src/task/mod.rs:99`），整个**进程**塌掉才走一次；而 `proc.exit` 绑的
`exit_current_and_run_next` 是每个**线程**退出都走。101 次线程退出里 65 次是
进程退出。

也就是说 ch8 里能把"进程退了"和"线程退了"分开的，全仓库只有这两个符号，而
`proc.exit` 这个名字正在把它们混掉。这是个独立的问题，单独记了一条 task ——
manifest 已经有现成的办法（`TaskControlBlock::new` 就是按
`type_exists = ProcessControlBlock` 分成 thread.create / proc.create 的），
exit 照抄即可，仍然不用引进章节号。

### 方法上的一句

原来的判据把"量比值"当成了唯一出路，于是这条待办卡了几轮 —— 而 `wakeup_task`
的函数体里第一行就写着 `add_task(task)`，调用图一看就知道两者是嵌套不是同义。
**问"是不是同一件事"该先看调用图，比值只是它的一个推论**；等比值的代价是，
当两个符号从不同时存在时，就永远等不到。

---

## `proc.exit` 在 ch8 数的是线程（#113，2026-09-06）

上一条量 `add_task` 时掉出来的。rCore ch8 把进程和线程拆开之后，
`os::task::exit_current_and_run_next` 变成**每条线程**退出走一次，可它顶着
`proc.exit` 这个名字。`rcore-ch8-usertest`：

    proc.exit                     101      每条线程退出一次
    func.remove_task               65
    func.remove_from_pid2process   65
    thread.create                 102

101 次里只有 65 次是整个进程塌掉。差别源码里写着：`remove_from_pid2process`
被 `if tid == 0` 罩着（ch8 `os/src/task/mod.rs:99`），主线程退出才走。

这不报错、不缺失，只是把线程数说成了进程数 —— 跟当初 `TaskControlBlock::new`
在 ch8 被映成 `proc.create` 是**同一个毛病**，那次是"开四条线程报四个进程"。

### 改法照抄先例

判据仍然是结构，不是章节号：

    "os::task::exit_current_and_run_next" = [
      { kind = "thread.exit", when = { type_exists = "os::task::process::ProcessControlBlock" } },
      { kind = "proc.exit" },
    ]
    "os::task::manager::remove_from_pid2process" = "proc.exit"

这样 `proc.exit` 在 ch1–8 和 xv6 里说的都是"一个进程没了"，跨内核才比得了；
ch8 多出来的那一层由 `thread.exit` 承担（同日在 `kinds.py` 登记）。

### 为什么不是 `remove_task`——数字相等不等于同一件事

`remove_task` 跟 `remove_from_pid2process` 在**三趟里次数完全相同**
（1/1、1/1、65/65）。照数字挑，两个都行。

但它是在一个循环里被调的：

    // ch8 os/src/task/mod.rs:134-143
    for task in process_inner.tasks.iter().filter(|t| t.is_some()) {
        remove_inactive_task(Arc::clone(&task));   // -> remove_task
        ...
    }

**一个进程有几条线程就走几次。**这几趟的进程都只有主线程，所以数字撞上了。
把"进程退出"绑到它上面，在这份语料里对，换一份多线程的 workload 就按线程数
翻倍，而且不会报错。

这是这一轮第二次遇到同一类陷阱：`add_task` 那条是"相等所以是同一件事"的反面
（7436 = 7373+62+1，相等**确实**说明它没有新信息），这条是"相等纯属巧合"。
两者的区别不在数字，在**调用图**：add_task 的三个调用点是全部，remove_task 的
调用点在循环里。数字只能提出假设，定不了案。

### 实机复核（没有重编）

`os/target/.../release/os` 里那份现成的 ch8 二进制，sha256 `022dd65e…`，跟
`rcore-ch8-proc` 录制时记下的 `kernel_elf_identity` **逐字节相同**。拿它把观察点
重选了一遍：

    thread.exit      os::task::exit_current_and_run_next
    proc.exit        os::task::manager::remove_from_pid2process
    (无)             os::task::manager::remove_task
    thread.create    os::task::task::TaskControlBlock::new
    sync.wakeup      os::task::manager::wakeup_task

ch1–7 走候选串的后一条，这条分支的正确性有现成证据：`TaskControlBlock::new` 用
同一个谓词，录好的 ch5 / ch7 watchlist 里是 `proc.create`，ch8 里是
`thread.create`。

### 顺带补了 video.py 的一个旧漏

`EVENT_INTEREST` 里一个 `thread.*` 都没有 —— `thread.create` **本来就漏**，
ch8 一直在产它，这份名单从来没收。改完之后 ch8 的线程退出会从 `proc.exit`
变成 `thread.exit`，不补进去就等于让它从视频里整个消失。按名单自己写的判据
（通用操作系统概念）把 `thread.create` / `thread.exit` 都收了，
`SUBSYSTEM_TAB` 里也把 `thread` 归到 `procs` 页。

## #111：能武装 ≠ 会响，以及三个词各自卡在哪

三条里有两条的前提是错的 —— 先量，再改。

* `syscall.trace` 不是"只有 ch4 有"。拿归档 ELF 静态重选一遍观察点，**ch3 和
  ch4 都有**真地址。
* `heap.init` 根本不用重录：`rcore-ch8-redirect` 里它一直在响。
* 只有 `syscall.sigprocmask` 真的非 ch7 不可。

这一步不需要 QEMU：ELF + DWARF + manifest 就能回答"这个符号在不在、有没有
kind"。"跑得到吗"才要开机。把静态那半截先做掉，省下的是整轮重编。

### 分支带的是没做完的实验骨架，而桩照样触发观察点

ch4 的 `sys_trace` / `sys_mmap` / `sys_munmap` 都是 `// YOUR JOB` 桩，函数体
只有一句 `-1`。可 WATCHPC 在**函数入口**开火，跟函数体返回什么无关 ——
"这个系统调用没实现"和"这个系统调用观察不到"是两件事，别混。

### 编进去哪些用户程序，是 make 变量说了算，不是分支

`os/Makefile`：`CHAPTER ?= $(当前分支名)`、`TEST ?= $(CHAPTER)`、`BASE ?= 1`；
`user/Makefile`：`TESTS := $(shell seq $(BASE) $(TEST))` —— `BASE=0` 只收
`ch{N}_*.rs`（正常测试，也就是要评分的那些），`BASE=1` 只收 `ch{N}b_*.rs`
（基础测试）。默认的 `BASE=1` 意味着 `ch4_trace1.rs` 这类**从来没被编进过
内核**，于是 `sys_trace` 一直在观察点表里、一次都没响。

`user/` 是 gitignore 的，但它躺在工作区里、装着所有章节的程序，**不随分支变**。

### `--make-var` 曾经被静默丢掉

`record.py` 做的是 `build.format(mv=mv)`，而 `str.format` 对模板里**没引用的**
关键字参数默默忽略。七份 manifest 里只有 `xv6.toml` 带 `{mv}`。所以给 rCore
传 `--make-var BASE=0` 的结果是：参数被收下、被写进 `manifest.json` 的
`make_vars`、然后丢掉 —— 存档里记着一个从未传给 make 的构建参数。这不是
"没生效"，是**存档在说谎**。

已在 `rcore.toml` 补上 `{mv}`，并在 `build_kernel()` 里加硬拦：给了构建参数
而模板没落点就直接报错。

（顺带：`BASE=0` 会把 `ch3_*` 也拉进来，而 ch3 的程序跑在 ch4 内核上时
`get_time` 返回 -1，`ch3_sleep1` 的等待循环永不结束 —— 第一次这么录，写出
1054.7 MB 轨迹后超时。要单章就给 `BASE=4`。）

### `syscall.trace`：录到了

`rcore-ch4-trace`，`--make-var BASE=4`，outcome `completed`，6.9 MB：

    {"insn": 26837092, "kind": "syscall.trace", "pc": 2149608172,
     "func": "_ZN2os7syscall7process9sys_trace17ha17956fea99a28f6E",
     "detail": {"_trace_request": 0, "_id": 48927, "_data": 0}}

### `syscall.sigprocmask`：量到了，但存不下

ch7 的 `sys_sigprocmask` 是**实现好的**，不是桩。全仓库只有一个调用点 ——
`user/src/bin/ch7b_sig_tests.rs:76`，在 8 个子测试里的第 5 个
`kernel_sig_test_ignore`。它确实响了：

    {"insn": 31179748, "kind": "syscall.sigprocmask", "pid": 3, "pc": 2149616590,
     "func": "_ZN2os7syscall7process15sys_sigprocmask17h218f25bb66dffd3fE",
     "detail": {"mask": 524288}}

`mask = 524288 = 1<<19 = SIGSTOP`，跟源码那行传的值对得上；同一趟里还有一条
配套的 `syscall.enter`（`syscall_num 135`、`args[0]=524288`）独立佐证。`func`
是 symtab 的 mangled 名、`pc` 非零 —— 真命中，不是 #110 那种墓碑。

**但这趟留不下来**，原因不是卡死。第 6 个子测试 `kernel_sig_test_stop_cont`
是按 guest 墙钟忙等：`user/src/lib.rs:263` 的 `sleep()` 写成

    while get_time() < start + period_ms { sys_yield(); }

父进程等 1000 ms、子进程等 500 ms，每一圈都是一次系统调用加一整轮调度，
而调度路径上挂满观察点。于是 **轨迹体积正比于 guest 墙钟时间 × 观察点密度，
跟做了多少有用的事无关**：129 个观察点下，25 秒写出 869 MB 轨迹、展开成
925 MB 的 `events.jsonl`（分析进程 RSS 5.2 GB），两次把磁盘写满，插件死在
"写轨迹负载失败：No space left on device"。

抽稀采样和快照都不解决它：插件里 `nf_emit_sample` 和 `nf_watch_hit` 是两条
**独立**的发射路径，涨的是后者。manifest 的 `throttle` 也不管 —— 它管的是
"事件要不要触发快照"（受 `evsnapmin` 约束），不是事件本身的频率。真正的
旋钮是"少武装几个观察点"，而那个目前没有开关。

### `--max-ram-bytes` 以前够不着

`RunConfig` 有 `max_ram_bytes`、`_qemu_cmd` 也把它当 `maxram=` 传给插件，唯独
CLI 没有对应开关，于是它永远是 1 GiB —— 跟 `{mv}` 同一类毛病：一条只差最后
一环的链路。已补上 `--max-ram-bytes`。它只封快照落页的总字节数，封不住事件
流，所以对上面那个问题只是减害，不是解药。

## 穿过指针之后再走一格：alien 的 `address_space_root` 现在跟另外两个内核同义

三个内核的 `address_space_root` 曾经不是一个语义：

    xv6   pagetable                                 reader=ptr   根页表地址
    rCore inner.memory_set.page_table.root_ppn.__0  reader=ppn   页号 -> 物理地址
    alien inner.address_space                       arc<mutex<struct>>  **结构体地址**

alien 读出来的 `0x8058a948` 是 `PageTable64` 结构体自己在堆上的地址 —— 连页对齐
都不是。它能唯一标识一个地址空间，所以看着"能用"，但拿它跟另外两个内核并排比就
是错的。

挡路的是两堵墙，都不在 alien 这边：

* 字段路径下潜**只穿内联壳、不解引用指针**，而 `TaskInner.address_space` 到
  `PageTable64` 中间隔着一个 `Arc`；
* `[entity.fields]` 只认 path/reader/role/links_to/enum/verified，没有
  `via`/`unwrap`（那是 `[[entity.source]]` 的词汇）。

绕过去的办法是**别动 path，动 reader**：reader 链本来就穿得过 `Arc`（`arc` 在
`_CROSS` 里），缺的只是穿过去之后再往里走一格的词汇。补了两处：

1. **`field<字段名, 内层>`**（`readers/scalars.py` 的 `Field`）。跟 `newtype`
   共用同一套问 `ctx.offset` 的机器，差别是**查不到偏移就报 Unavailable，绝不
   退回 0**。`newtype` 退回 0 有依据（单字段元组结构体的字段只能在 0）；具名
   字段没有这种保证 —— `root_paddr` 实测在 +24，退回 0 会读到它前面那个字段，
   读出来是个像模像样的数，没人看得出不对。

2. **`resolve.peel_die` 改成先按 reader 自己声明的载荷字段走**（新增
   `registry.inline_payload_fields`，直接读各个壳类的 `_chains`，不另抄一份）。
   原来它按"唯一一个占字节的字段"挑载荷 —— 那条规矩对锁**永远**不成立，锁天生
   就是锁字 + 载荷两个字段。于是
   `TicketMutex<PageTable64<…>, KernelLockAction>` 这层一律返回 None，
   `layer_chain` 从那层起全没名字：字符串剥不动（两个泛型实参，剥出来是哪个都
   是猜），测量也不给，里层就此没名字。实测日志：

       make('field<root_paddr, usize>'  type_name=None
            layer_chain=[{'name': None}, {'name': None}]

   顺带补了 `_peel_transparent_cell`：锁的载荷字段落在 `UnsafeCell<T>` 上，
   reader 停在那儿是对的（`repr(transparent)` 保证 +0，白跑一趟），但**名字**
   得再脱一层，否则下一层会拿 `UnsafeCell<PageTable64<…>>` 去查偏移表，查不到。
   按全限定名认 `UnsafeCell`/`ManuallyDrop`，不按形状认 —— 形状跟
   `PhysAddr(usize)` 这种真 newtype 一模一样，按形状穿会把想要的名字丢掉。

结果（alien-pwd 实测）：

    改之前  present  0x8058a948   页对齐 False
    改之后  present  0xa0565000   页对齐 True，页号 0xa0565

`peel_die` 是所有内核共用的，所以按老规矩测了对照组：`starry-fsprobe`（540 个
字段格）和 `rcore-ch6-fs`（180 个）逐字段哈希**改前改后一模一样**
（`9dc4b7bb8beed103` / `0d1112dd66e42dc6`）。也就是说这一改对现有内核是零影响，
只是把原来测不出来的那层补上了。

还**没**变的：字段路径本身仍然穿不过指针。这次是把活儿挪到 reader 链上去干，
不是把 path 教会解引用。哪天真要在 path 里跨指针，那还是另一件事。

## 全语料测试的地板：进程内缓存去不掉，磁盘缓存可以

`A.analyze(run)` 的成本**按 trace 字节数走，跟解出多少事件无关**（实测
starry-forkecho-ram512：66.7MB、9115 条事件、198 秒；rcore-ch8-usertest：
143.5MB、107 万条事件、32 秒）。有六份测试文件要对**全语料**提问，于是每跑一次
测试就是 52 趟 analyze。

第一步是把"一趟 analyze 抽出来的小形状"放进 `tests/conftest.py` 共享
（`Shapes`：metrics / kind_counts / switches / notes / … 全是几 KB；
`a.events`、`a.states` 这种整体一律不留 —— 连做三趟 RSS 就 4.7GB）。各文件自己
`@lru_cache` 只在模块内共享，实测四份文件一起跑时 `arceos-ctxsnap500` 被
analyze 了三次。放进 conftest 之后，一个 pytest 进程里每趟只 analyze 一次。

但 52 趟是**进程内的地板** —— 换一份文件单独跑、或者隔一会儿再跑，全部重来。
所以又加了一层**磁盘**缓存（`tests/.shape-cache/`，已 gitignore）：

    冷跑（清空缓存）  97 passed in 1634.24s (27:14)
    热跑              97 passed in   33.56s
    缓存占用          2.0MB / 52 个文件

**48.7 倍**，而代价是 2MB 磁盘。（这台机器只剩 10GiB、98% 满，所以写缓存时会把
同一趟的旧键删掉 —— 每改一次代码键就换一个，不删的话磁盘按改动次数线性涨。）

### 这个缓存能不能信，全在键上

键 = 录下来的东西 + 内核 ELF + **解码逻辑**。第三样最容易漏，漏了就致命：改完
`resolve.py` 再跑测试，读到的是改之前的结论，绿得毫无意义。今天改 `peel_die`
那一下差点撞上 —— 要是缓存不认代码，"对照组改前改后哈希一致"这个结论就成了
自证。所以 `_code_fingerprint()` 把 `model/` 和 `host/` 的每个 `.py`、加上所有
manifest 的 size+mtime_ns 都算进去。

按 mtime 而不读内容，是因为一次 stat 几百个文件是毫秒级的。代价是
`git checkout` 会让 mtime 变、缓存整体作废 —— 那是**偏保守**的方向：宁可白算
一遍，不能给旧答案。

内核 ELF 按 `manifest.json` 里录的 **sha256 内容哈希**认，不按路径：`kernel_elf`
常常指着 `target/`，下次编译就换成别的内核了（31 趟里 19 趟中过招）。

对照开关：`NF_SHAPE_CACHE=off pytest …`。怀疑缓存骗人时拿它跑一遍。

### 还没吃到这个好处的

还有九份文件仍然直接 `A.analyze`（`test_procs_gate` / `test_procs`…
`test_context_switch_snapshot` 等），因为它们要的是 `a.states` / `a.procs` 这类
**大**东西，不在 `Shapes` 里。往 `Shapes` 里加字段的规矩没变：**只加小的** ——
想加整体之前先算 53 趟乘上去是多少内存。

## starry 的 `address_space_root`：链子有了，也捅出四个通用毛病（#144，2026-09-09）

starry 是七个内核里仅剩两个没有 `address_space_root` 的之一。现在有了：
`starry-forkecho-ram512` 上 120 帧、165/172 解出、**全部页对齐**、40 个不同页表。

### 为什么这条链有 17 跳

`Process`（152 字节）身上**没有**任何通往地址空间的东西，`ThreadGroup` 里只有
一串 TidNumber。starry 把进程拆成两个堆对象 —— 拓扑那半（`Process`：pid /
parent / children / tg）和资源那半（`ProcessData`：aspace / cmdline / heap_top /
rlim）—— 而两者之间**指针只有一个方向**（`ProcessData.proc` 指回来）。从
`Process` 往外唯一走得通的是 `identity`：

    Process.identity            +0     Weak<PidIdentity>
    PidIdentity.state           +24    IrqMutex<PidIdentityState>
      IrqMutex.__0              +0     SpinLock<PidIdentityState>
      SpinLock.__0              +0     BaseSpinLock<RawState, ..>
      BaseSpinLock.data         +8     UnsafeCell<PidIdentityState>
    PidIdentityState.process_lifecycle +16   ProcessLifecycle（判别值 u32 @ +64）
      ProcessLifecycle::Live.__0 +0    Weak<ProcessData>
    ProcessData.aspace          +576   IrqMutex<Arc<Mutex<AddrSpace>>>
    Mutex.data                  +16    UnsafeCell<AddrSpace>
    AddrSpace + 24                     物理地址（pt.inner.root.paddr）

对账三条，互相独立：

  * 手算一遍（完全不过 reader），165/165 逐个相同，全部页对齐；
  * `ProcessData.proc`（+1120）回指的 `Process` 落在同一趟自己枚举出来的进程
    集合里 —— 170 次里 165 次成立，而按错的 `ArcInner.data`（+64）走则是
    169 次全不成立；
  * 剩下 7 次判别值读出 1000000000 = `None`，那是真的还没有 `ProcessData`。

### 捅出来的四个毛病，没一个是 starry 专属

**1. 内层类型名原来优先"字符串剥泛型实参"。** `registry.make` 里
`inner_type(type_name)` 干的是「`W<T>` 里面装的是 `T`」，而**转发型**的壳不是
这样：`Arc<T>` 装 `ArcInner<T>`、`IrqMutex<T>` 装 `SpinLock<T>`、`SpinLock<T>`
装 `BaseSpinLock<S, T>`。剥得动不等于剥得对 —— 剥出来的 `T` 是个真存在的类型
名，往下传不报错，只让内层拿着错类型去查偏移。`arc` 早就绕开了（另外量了
`arcinner`），别的一直没有。改成 `layer_chain` 量到的优先、字符串剥当兜底。

**2. `Field` 的偏移原来在运行期按类型名查，而类型名不唯一。** 枚举变体的载荷
在 DWARF 里是一个个独立的 `structure_type`，全限定名只带模块路径和变体名 ——
同一个模块里两个枚举各有一个 `Live`，名字一模一样，`dwarfsrc.structs` 按名字
去重只留得下一个。实测这份二进制里 `ProcessLifecycle::Live` 是 die 14098、
80 字节、`__0` 在 **+0**，另一个同名的是 16 字节、`__0` 在 **+8**。按名字查到
后者，指针就从错了 8 字节的地方读：172 次里 123 次读到 0（当"空"）、49 次读到
没对齐的值（当"读错位置"），**一次都不报错** —— 两种结局单看都合法。

这跟 `ArcInner.data` 是同一个道理：链条走的时候手里有精确的 DIE，把量到的数
带下去，就不用在运行期拿一个有歧义的名字再查一遍。现在 `layer_chain` 给
`field` 那一层填 `field_off`，`scalars.Field.off` 一给就压过名字那条路（没给
就还是按名字查 —— `unwrap` 那条路造 reader 时没有 layer_chain）。

**3. `astype<类型名, 内层>`：DWARF 擦掉类型的地方让 manifest 说。** starry 的
`TaskInner.task_ext` 是 `Option<AxTaskExt>`，而 `AxTaskExt` 是 `extern_trait`
宏生成的 trait object 壳，擦除之后只剩 `Repr{__0: *mut (), __1: *mut ()}` ——
谁也问不出被指的是什么。而 `starry_kernel::task::Thread`（392 字节、28 个字段）
在同一份 DWARF 里完完整整躺着：**偏移不缺，缺的只是名字**。这一格跟别的都不
一样 —— 别的每一格都是量的，这一格是**说**的，断错了不会响，所以只在 DWARF
确实擦掉类型的地方用，并且要在 manifest 里写清楚凭什么这么断言。名字本身仍然
过 DWARF（`dw.type_off()` 反查，撞名会拒绝）。

这条链最后没用上 `astype`（`Live.__0` 直接就是 `Weak<ProcessData>`），但
process↔thread 那条边（#137）要走 `task_ext`，正需要它。

**4. 三层壳。** `IrqMutex<T>` 是 `SpinLock<T>` 的 newtype，而 `spinlock` reader
最长的链只到 `__0 -> BaseSpinLock.data` 两跳。写 `newtype<spinlock<…>>`，别去
扩 `SpinLock._chains` —— 那是按形状取的规矩，不该为某个内核加特例。

### 回归

rcore-ch6-fs 18/18、lab3-cowtest-mac 383/383 页表照旧全部页对齐；全量快测
1039 passed / 4 skipped。

## starry 的 process↔thread 边：方向是内核定的，不是界面定的（#137，2026-09-09）

原来立的题目是"需要按 TID 查表的 join，现有词汇没有"。**这个前提是错的。**
指针一直在，只是**方向反着**：

    TaskInner.task_ext  +784   Option<AxTaskExt>（判别值 +0，Some.__0 +8）
    AxTaskExt.__0       +0     extern_trait::Repr{__0: *mut (), __1: *mut ()}
    Repr.__0            +0     *mut ()                     ← 类型被擦掉
    Thread.proc_data    +0     Arc<ProcessData>
    ProcessData.proc    +1120  Arc<Process>

线程指得到进程；反过来进程手里一个指向线程的指针都没有（`ThreadGroup.threads`
是 `BTreeSet<TidNumber>`，装号码不装指针）。而 `procview.sched_contexts` 要的
恰恰是**进程那一侧的出边** —— 进程/线程分开的内核，切换归因全靠它。

### `inverse`：在指针真存在的那一侧声明，让 engine 反着记一份

manifest 写在有指针的那边，加一个 `inverse = "threads"`；`snapshot._link` 连完
正向边之后，把同一条边挂到对面实体上。**不新读一个字节**，也不引入 TID join
（TID 会复用，join 出来的边不如指针硬）。

两个坑，都实测过：

* **判重必须按身份。** `Entity` 是普通 dataclass，`x in list` 会走 `__eq__` 比
  所有字段，包括 `links` —— 而 `links` 连完就成环。实测两个字段完全相同的线程
  `t1 == t2` 为真（比到共同的 `proc` 那格时 list 走了身份捷径），第二个线程会
  被当成重复吞掉；环真绕起来（两个各带一个线程的**不同**进程）则直接
  RecursionError。
* **`inverse` 没有 `links_to` 就没有"对面"**，会一声不吭地不生效。在 loader 里
  拦掉。顺手补了 lint：`links_to` 指向这份文件里没声明过的实体要报。今天这不会
  让边连不上（`snap.index` 是跨 kind 按地址查的），但它已经不再只是注释了。

### 证据

starry-forkecho-ram512：process 行 172，**164 行带上了 `sched_ctxs`**（分布
`{0: 8, 1: 164}`）。这个数只可能来自新边 —— `sched_context` 这个 role 在
starry.toml 里**只挂在 thread 上**，`Process` 自己没有，所以进程行的 ctx 没有
第二个来源，改之前必然是 0/172。

另两趟是 0/92 和 0/90：跟 #145 同一个根，128 MiB 窗口读不到堆，线程压根枚举
不出来。

### 顺带量出一个新洞（#147）

1084 条 switch 里 611 条两端都认不出，集中在 **13 个**反复出现的 ctx 上。先以为
这些任务没进注册表 —— **量了之后不是**：拿 `ctx - 376` 当 TaskInner 基址读，13
个全解得出来（`idle` / `main` / `gc` / `ktimers/0` / `blk-ctl/nvme` /
`net-protocol` …，id 1..13），而同一趟最后一帧枚举到的 thread id 正是 `[4..14]`。

也就是说其中十个**既在注册表里、也解得出来**，却还是归因不到。原因在
`analyze._task_by_ctx`：它只翻**进程行**，而进程行的 `sched_ctxs` 是顺着上面那
条反向边取的 —— 内核线程没有用户态 `Process`，于是永远不会出现在任何一行里。
枚举到了也白枚举。这不是 starry 专用。

## 归因该认的是「调度单位」，不是「进程行」（#147，2026-09-09）

上面那条边接好之后，starry-forkecho-ram512 的 1084 条 switch 里还有 **611 条
两端都认不出**，集中在 13 个反复出现的 ctx 上（650/472/195/113/110 次…）。

先以为这些任务没进 `TASK_REGISTRY`。**量了之后不是**：拿 `ctx - 376` 当
`TaskInner` 基址读，13 个全解得干干净净 —— id 1..13 依次是 `idle`、`main`、
`gc`、`ktimers/0`、`serial0-maint`、`blk-ctl/nvme`、`blk-hctx/0`、
`net-queue-cpu0`、`net-protocol`、`trace-pipe-notify`、`tty-reader`、
`dev-log-server`、`alarm_task`。而同一趟最后一帧枚举到的 thread id 正是
`[4..14]`，名字就是那一批。

**其中十个既在注册表里、也已经被枚举成 thread 实体了，却还是归因不到。**
根在 `analyze._task_by_ctx`：它只翻 `states[i].procs`，而进程行的 `sched_ctxs`
是顺着关系边取的 —— 内核线程没有用户态 `Process`，一行都没有，于是枚举到了
也白枚举。这不是 starry 专用：任何"调度单位不都挂在进程下面"的内核都一样。

改法：`SystemState` 多一张 `sched_owners`（ctx -> `{kind, id, name}`），按
`role = "sched_context"` 建 —— manifest 说哪个实体是调度单位就取哪个，代码里
没有内核名字。归因先查进程行（那儿有 pid 和槽号），查不到再查这张表；查到了
就写名字，**pid 和 slot 留 None**，因为它确实没有 pid，而槽号是进程表的枚举序。

### 顺带炸出一个"空串当名字"的老毛病

改完一量，名字分布里 `''` 出现了 **492** 次。根在 `_procs_from_entities` 的
`name=r["name"] or ""` —— 它把**没有名字这个字段**压成了空串。而空串在 ArceOS
上是个**真值**：`axtask::spawn()` 传的就是 `String::new()`，那个子任务的名字
确实是空的（test_switch_attribution 里就断言着 `to_proc == ""`）。两件事压成
一样，"这个内核的进程没有名字"和"这个任务叫空字符串"就再也分不开。

`ProcInfo.name` 改成 `str | None`，搬运的时候不再 `or ""`；归因那边判的是
`is None` 而不是真假值，所以 ArceOS 那个真空串不会被别人的名字顶掉。这 492 个
端点现在显示 `busybox` —— 线程自己的名字。

### 数字

starry-forkecho-ram512，1084 条 switch：

|                | 接边前 | 接边后（#137） | 认调度单位后（#147） |
|----------------|-------|---------------|--------------------|
| 两端都有名字    | —     | 19            | **684**            |
| 只认出一端      | —     | 454           | 382                |
| 两端都不知道    | —     | 611           | **18**             |
| 名字是 `''` 的端点 | —  | 492           | **0**              |

xv6 / rCore / ArceOS 上调度单位就是进程行自己，`p.name` 本来就有值，这两处
取到的都还是原来那个数 —— test_switch_attribution 23 条全过，包括 xv6 那两条
断言"调度器"的和 ArceOS 那条断言"够不着的任务不许叫调度器"的。

剩下的 18 条是 id 1/2/3（`idle` / `main` / `gc`），它们不在注册表里 ——
枚举出来的号是 4..14。

> 这里原先写着"符号是现成的，照 arceos.toml 那三条 `union` 补"。**那句是
> 错的**，2026-09-09 量过之后推翻：`{percpu = …}` 在 starry 上根本编不出来，
> 而真正拦路的是别的东西。见下一节。

## starry 的 per-CPU 区被"窗口至少 2 MiB"这条门槛整条丢掉（#148，2026-09-09）

### 先说三条路各自死在哪

想枚举 `idle`，看上去有三条路，实测三条都不通，而且死因各不相同：

1. **`{ percpu = "ax_task::run_queue::IDLE_TASK" }`** —— 编都编不出来：

       第 0 步 percpu：ELF 符号表里没有 _percpu_start、_percpu_end、
       _percpu_load_start、_percpu_load_end

   starry 用的是 **ax_percpu**，跟 arceos 的 `percpu` crate 不是一套。后者靠
   链接脚本圈出一段 per-CPU 区，边界就是那四个符号；ax_percpu 是**运行期**排
   布局的（`ax_percpu::layout::INSTALLED_LAYOUT`、`PerCpuArea::cpu_area`、
   `___priv::symbol_offset`）。`plan.py` 的 percpu 步只认前者。

2. **把 `___PERCPU_*` 的 D 段地址当 static 读** —— 读得到，但读出来是 0，
   **每一帧都是**。不是"没拍到"：`RamImage.blob` 对没观测过的页返回 `None`，
   这里返回的是货真价实的零字节。模板不是活数据所在。

3. **`{ static = "ax_task::run_queue::RUN_QUEUES" }`**（BSS 全局）—— 值是真的
   （`0xffffffe081002178`），但那个地址**翻译不了**。

### 真正的拦路石

把页表走一遍，按 va-pa 差分组，再看每组的叶子在 VA 上连不连得起来
（starry-forkecho-ram512）：

| va−pa 差 | 总量 | 叶子 | 连续段 | 最长一段 |
|---|---|---|---|---|
| `0xffffffc000000000` | 759.82 MiB | 68807 | 8 | 495.74 MiB |
| `0xfffffffeffe00000` | 14.00 MiB | 7 | 1 | 14.00 MiB |
| `0xffffffe000000000` | **0.25 MiB** | 65 | **1** | 0.25 MiB |

第三条就是 per-CPU 区（`0xffffffe081002000..0xffffffe081043000`），65 个 4 KiB
叶子**连成一整片**。`_derive_windows` 的 `_WINDOW_MIN_BYTES = 2 MiB` 把它整条
丢掉，于是 RUN_QUEUES 那个指针落在"没有窗口能翻译"的地址上。

门槛写在那儿的理由是对的（不设的话每个用户页都成一个"窗口"，`_t` 会把本该读
不到的地址硬减进内存 —— 那是造假）。**错的是它旁边那句注释**："比它小的成片
映射不存在"。per-CPU 区天生就是几百 KiB。

改法是换判据而不是调小门槛：**总字节数 ≥ 2 MiB，或者最长连续段 ≥ 64 KiB**。
连续性不是启发式，是线性映射的定义 —— 16 个连着的页共用同一个 va-pa 差，那
一段就**是**线性映射；而门槛要挡的用户页是**散**的，一页一个差，最长连续段就
是 4 KiB，照样进不来。

### 一个差点当真的错误

中途我手工加了个 `0xffffffe000000000` 窗口去试，读出来一个"活的 AxRunQueue"，
数字都对得上。等按**量出来的**窗口复核才知道那趟是巧合 —— 任何一个能减进
RAM 的偏移都会读到*某些*字节，而那些字节看上去和真数据一模一样。窗口必须是
页表里走出来的，手填的偏移只能用来提假设，不能用来下结论。

## uCore ch8：C 内核接入与严格覆盖（2026-09-15）

基线是 `LearningOS/uCore-Tutorial-Code` ch8
`7728a992c20ce43627fbc319ccb4f5765e807cba`。它同时有固定进程池、每进程固定线程
数组、bcache、系统文件表和 inode 表；这些都由 `ucore.toml` 的通用实体步骤枚举，
宿主端没有 `if ucore` 分支。`struct proc` 的 8 个字段、`struct thread` 的 8 个
字段和三张资源表的 17 个字段在实际 ELF 上全部可解。

这次补出一个通用的 C/DWARF 缺口：`filepool` 的地址只在 ELF 符号表，完整的
`struct file[2048]` 类型只在头文件产生的 `extern` DWARF 声明。两边以唯一的同名
全局量相接是事实连接，不是按字节数猜数组长度。`DwarfSource.var_decl()` 因而保留
这种类型声明，`SymbolIndex` 只有在声明类型唯一时才把它接到 ELF 地址；冲突仍拒绝。

函数入口拿不到的语义仍走同一套 NFTrace 协议：分配成功后的物理页、释放后的计数、
fork/thread-create 成功结果由内核上报；每次成功写 PTE 后调用无副作用的 noinline
观察点。区域级 `mappages`/`uvmunmap` 仍直接从原函数入口计数。ch8 没有 journal，
所以 `log.commit` 是带源码依据的 N/A，不拿 `bwrite` 冒充提交。

最终 `ch8b_usertest` 录制正常退出，原始轨迹 1,255,451,171 字节。严格门禁结果：
18/18 个适用指标、5,349,758 条语义事件零未知字段、84 张相关快照全部完整、1,968
个 manifest 字段格零未解、完整 watch scope、trace/plugin 完整，结论 100%。HTML
保留全部语义事件，只对 `func.*` 诊断命中做系统抽样；因此指标和覆盖门禁都仍按原始
事件计算。
