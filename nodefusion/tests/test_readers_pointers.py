import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.rt import DictMemory, ReadCtx, Unavailable, is_ok
from nodefusion.model.readers.pointers import (
    Arc, Lazy, LazyInit, LazyLock, Mutex, OptionArc, OptionWeak, Ptr,
    SpinLock, SpinRwLock, UnsafeCell, UpSafeCell, Weak,
)

BASE = 0x8000_0000
SLOT = BASE + 0x1000
INNER = BASE + 0x2000
UNMAPPED = 0x9000_0000
PAYLOAD = 0xDEAD_BEEF_0000_0001
GARBAGE = 0x4141_4141_4141_4141

MAXU64 = (1 << 64) - 1


def le(v: int, n: int = 8) -> bytes:
    return v.to_bytes(n, "little")


def u64(mem, addr, ctx):
    v = mem.u64(addr)
    return Unavailable("读不出 u64", addr) if v is None else v


def rcore_ctx() -> ReadCtx:
    return ReadCtx(layout={
        "Lazy<Arc<TaskControlBlock>>": {"__0": 0},
        "Lazy<UPSafeCell<Processor>>": {"__0": 0},
        "Once<Arc<TaskControlBlock>>": {"data": 0, "status": 8},
        "Once<UPSafeCell<Processor>>": {"data": 0, "status": 128},
        "UPSafeCell<Processor>": {"inner": 0},
        "RefCell<Processor>": {"borrow": 0, "value": 8},
        "ArcInner<TaskControlBlock>": {"strong": 0, "weak": 8, "data": 16},
    })


def arc_mem(ptr_to: int = INNER, *, data_off: int = 16) -> DictMemory:
    inner = bytearray(le(2) + le(1))          # strong=2, weak=1
    inner += b"\x00" * max(0, data_off - len(inner))
    inner[data_off:data_off + 8] = le(PAYLOAD)
    return DictMemory({SLOT: le(ptr_to), INNER: bytes(inner)})



def test_arc_chain_reaches_payload():
    mem, ctx = arc_mem(), ReadCtx()
    assert Arc(u64)(mem, SLOT, ctx) == PAYLOAD


def test_arc_uses_measured_arcinner_layout():
    ctx, mem = rcore_ctx(), arc_mem()
    r = Arc(u64, inner_type="ArcInner<TaskControlBlock>")
    assert r(mem, SLOT, ctx) == PAYLOAD
    assert "DWARF" in r.provenance(ctx)
    assert Arc(u64)(mem, SLOT, ctx) == PAYLOAD


def test_arc_without_inner_returns_payload_address():
    assert Arc()(arc_mem(), SLOT, ReadCtx()) == INNER + 16


def test_arc_prefers_dwarf_offset_over_assumption():
    ctx = ReadCtx(layout={"ArcInner<Aligned>": {"data": 24}})
    mem = arc_mem(data_off=24)
    assert Arc(u64, inner_type="ArcInner<Aligned>")(mem, SLOT, ctx) == PAYLOAD
    assert Arc(u64)(mem, SLOT, ctx) != PAYLOAD


def test_arc_provenance_names_the_fallback():
    assert "假设" in Arc().provenance(ReadCtx())
    ctx = rcore_ctx()
    assert "DWARF" in Arc(inner_type="ArcInner<TaskControlBlock>").provenance(ctx)



def test_null_pointer_is_absence_not_failure():
    mem, ctx = DictMemory({SLOT: le(0)}), ReadCtx()
    for r in (Arc(u64), Weak(u64), OptionArc(u64), OptionWeak(u64), Ptr(u64)):
        got = r(mem, SLOT, ctx)
        assert got is None, f"{type(r).__name__} 把空指针报成了 {got!r}"
        assert is_ok(got), "空指针必须算取到了，不能算取不到"


def test_option_arc_is_niche_optimised():
    mem, ctx = arc_mem(), ReadCtx()
    assert OptionArc(u64)(mem, SLOT, ctx) == Arc(u64)(mem, SLOT, ctx)
    assert OptionArc(u64)(mem, SLOT, ctx) == PAYLOAD



def test_weak_dangling_sentinel_is_absence():
    ctx = ReadCtx()
    for sentinel in (0x1, 0x4, 0x8, 0x10, MAXU64, MAXU64 - 7):
        mem = DictMemory({SLOT: le(sentinel)})
        got = Weak(u64)(mem, SLOT, ctx)
        assert got is None, f"哨兵 {sentinel:#x} 没被认出来，返回了 {got!r}"
        assert is_ok(got)


def test_arc_rejects_sentinel_that_weak_accepts():
    mem, ctx = DictMemory({SLOT: le(0x8)}), ReadCtx()
    assert Weak(u64)(mem, SLOT, ctx) is None
    got = Arc(u64)(mem, SLOT, ctx)
    assert isinstance(got, Unavailable)
    assert "0x8" in str(got)


def test_misaligned_pointer_is_failure_not_absence():
    mem, ctx = DictMemory({SLOT: le(BASE + 0x2003)}), ReadCtx()
    for r in (Arc(u64), Weak(u64)):
        got = r(mem, SLOT, ctx)
        assert isinstance(got, Unavailable), f"{type(r).__name__} 放过了未对齐指针"
        assert "对齐" in got.reason and got.addr == SLOT


def test_weak_threshold_is_tunable():
    mem, ctx = DictMemory({SLOT: le(0x8)}), ReadCtx()
    assert Weak(u64)(mem, SLOT, ctx) is None
    assert isinstance(Weak(u64, min_addr=0)(mem, SLOT, ctx), Unavailable)



def test_deref_out_of_range_is_unavailable():
    mem = DictMemory({SLOT: le(UNMAPPED)})
    got = Arc(u64, inner_type="ArcInner<TaskControlBlock>")(
        mem, SLOT, rcore_ctx())
    assert isinstance(got, Unavailable)
    assert got.addr == UNMAPPED + 16
    assert not is_ok(got)


def test_reading_the_pointer_itself_out_of_range_is_unavailable():
    got = Arc(u64)(DictMemory(), SLOT, ReadCtx())
    assert isinstance(got, Unavailable) and got.addr == SLOT
    assert "快照" in got.reason


def test_fallback_offset_is_named_in_the_failure():
    mem = DictMemory({SLOT: le(UNMAPPED)})
    got = Arc(u64)(mem, SLOT, ReadCtx())
    assert isinstance(got, Unavailable) and "假设" in got.reason


def test_unavailable_never_looks_like_a_value():
    got = Arc(u64)(DictMemory(), SLOT, ReadCtx())
    assert not got and "0x80001000" in str(got)



def lazyinit_ctx() -> ReadCtx:
    return ReadCtx(layout={"LazyInit<Axns>": {"data": 0, "inited": 8}})


def lazyinit_mem(inited: int) -> DictMemory:
    body = le(PAYLOAD if inited else GARBAGE) + bytes([inited]) + b"\x00" * 7
    return DictMemory({SLOT: body})


def test_lazyinit_uninitialised_is_unavailable():
    got = LazyInit(u64, type_name="LazyInit<Axns>")(
        lazyinit_mem(0), SLOT, lazyinit_ctx())
    assert isinstance(got, Unavailable), f"未初始化却返回了 {got!r}"
    assert got != GARBAGE and "未初始化" in got.reason
    assert got.addr == SLOT


def test_lazyinit_initialised_reads_payload():
    assert LazyInit(u64, type_name="LazyInit<Axns>")(
        lazyinit_mem(1), SLOT, lazyinit_ctx()) == PAYLOAD


def test_lazyinit_flag_may_sit_after_the_payload():
    r = LazyInit(u64, type_name="LazyInit<Axns>")
    assert "inited 在 +8" in r.provenance(lazyinit_ctx())


def test_lazyinit_without_layout_is_unavailable():
    got = LazyInit(u64)(lazyinit_mem(1), SLOT, ReadCtx())
    assert isinstance(got, Unavailable)
    assert "inited" in got.reason and got.addr == SLOT


def test_lazyinit_flag_out_of_range_is_unavailable():
    got = LazyInit(u64, type_name="LazyInit<Axns>")(
        DictMemory(), SLOT, lazyinit_ctx())
    assert isinstance(got, Unavailable) and got.addr == SLOT + 8



def once_mem(status: int) -> DictMemory:
    return DictMemory({SLOT: le(PAYLOAD if status == 2 else GARBAGE)
                       + bytes([status]) + b"\x00" * 7})


def lazy_reader() -> Lazy:
    return Lazy(u64, type_name="Lazy<Arc<TaskControlBlock>>",
                once_type="Once<Arc<TaskControlBlock>>")


def test_lazy_incomplete_states_are_unavailable():
    ctx, r = rcore_ctx(), lazy_reader()
    for st, word in ((0, "Incomplete"), (1, "Running"), (3, "Panicked")):
        got = r(once_mem(st), SLOT, ctx)
        assert isinstance(got, Unavailable), f"状态 {st} 却返回了 {got!r}"
        assert word in got.reason, f"状态 {st} 的原因里没说清是 {word}"


def test_lazy_complete_reads_payload():
    assert lazy_reader()(once_mem(2), SLOT, rcore_ctx()) == PAYLOAD


def test_lazy_reads_low_byte_of_wide_status():
    mem = DictMemory({SLOT: le(PAYLOAD) + le(2)})
    assert lazy_reader()(mem, SLOT, rcore_ctx()) == PAYLOAD


def test_lazy_without_status_offset_refuses_to_read():
    ctx = ReadCtx(layout={"Lazy<Arc<TaskControlBlock>>": {"__0": 0}})
    got = Lazy(u64, type_name="Lazy<Arc<TaskControlBlock>>")(
        once_mem(2), SLOT, ctx)
    assert isinstance(got, Unavailable)
    assert "status" in got.reason and got.addr == SLOT


def test_lazy_complete_value_from_enums_beats_the_default():
    ctx = rcore_ctx()
    ctx.enums["Status"] = {0: "Incomplete", 7: "Complete"}
    r = Lazy(u64, type_name="Lazy<Arc<TaskControlBlock>>",
             once_type="Once<Arc<TaskControlBlock>>", status_enum="Status")
    assert r(once_mem(2), SLOT, ctx) != PAYLOAD
    mem = DictMemory({SLOT: le(PAYLOAD) + bytes([7]) + b"\x00" * 7})
    assert r(mem, SLOT, ctx) == PAYLOAD
    got = r(once_mem(0), SLOT, ctx)
    assert isinstance(got, Unavailable), "Incomplete 被当成 Complete 了"



def test_measured_rcore_descents():
    ctx = rcore_ctx()

    initproc = Lazy(type_name="Lazy<Arc<TaskControlBlock>>",
                    once_type="Once<Arc<TaskControlBlock>>")
    assert initproc(once_mem(2), SLOT, ctx) - SLOT == 0

    processor = Lazy(UpSafeCell(type_name="UPSafeCell<Processor>",
                                cell_type="RefCell<Processor>"),
                     type_name="Lazy<UPSafeCell<Processor>>",
                     once_type="Once<UPSafeCell<Processor>>")
    mem = DictMemory({SLOT: b"\x00" * 128 + bytes([2]) + b"\x00" * 7})
    assert processor(mem, SLOT, ctx) - SLOT == 8


def test_full_initproc_chain_lazy_then_arc():
    ctx = rcore_ctx()
    mem = DictMemory({
        SLOT: le(INNER) + bytes([2]) + b"\x00" * 7,
        INNER: le(2) + le(1) + le(PAYLOAD),              # ArcInner
    })
    r = Lazy(Arc(u64, inner_type="ArcInner<TaskControlBlock>"),
             type_name="Lazy<Arc<TaskControlBlock>>",
             once_type="Once<Arc<TaskControlBlock>>")
    assert r(mem, SLOT, ctx) == PAYLOAD



def test_inline_wrappers_need_no_memory_access():
    empty = DictMemory()
    ctx = ReadCtx(layout={"SpinNoIrq<Vec>": {"data": 8},
                          "Mutex<String>": {"data": 8},
                          "UPSafeCell<Processor>": {"inner": 0},
                          "RefCell<Processor>": {"borrow": 0, "value": 8}})
    assert UnsafeCell()(empty, SLOT, ctx) == SLOT            # transparent，+0
    assert SpinLock(type_name="SpinNoIrq<Vec>")(empty, SLOT, ctx) == SLOT + 8
    assert Mutex(type_name="Mutex<String>")(empty, SLOT, ctx) == SLOT + 8
    assert UpSafeCell(type_name="UPSafeCell<Processor>",
                      cell_type="RefCell<Processor>")(
        empty, SLOT, ctx) == SLOT + 8
    for r in (Arc(), Weak(), Ptr()):
        assert isinstance(r(empty, SLOT, ctx), Unavailable)


def test_upsafecell_two_hop_chain_from_dwarf():
    ctx = rcore_ctx()
    r = UpSafeCell(u64, type_name="UPSafeCell<Processor>",
                   cell_type="RefCell<Processor>")
    mem = DictMemory({SLOT: le(MAXU64) + le(PAYLOAD)})
    assert r(mem, SLOT, ctx) == PAYLOAD
    assert "DWARF" in r.provenance(ctx)


def test_partial_chain_is_rejected_not_half_used():
    ctx = ReadCtx(layout={"UPSafeCell<T>": {"inner": 0}})
    r = UpSafeCell(u64, type_name="UPSafeCell<T>", cell_type="RefCell<T>")
    mem = DictMemory({SLOT: le(MAXU64) + le(PAYLOAD)})
    got = r(mem, SLOT, ctx)
    assert isinstance(got, Unavailable), f"用了半条链，返回了 {got!r}"
    assert got != MAXU64 and "查不到" in got.reason


def test_inline_without_layout_names_what_it_wanted():
    got = SpinLock(u64, type_name="SpinNoIrq<Vec>")(
        DictMemory(), SLOT, ReadCtx())
    assert isinstance(got, Unavailable)
    assert "SpinNoIrq<Vec>" in got.reason and "data" in got.reason
    assert got.addr == SLOT


def test_inline_without_type_name_says_so():
    got = Mutex(u64)(DictMemory(), SLOT, ReadCtx())
    assert isinstance(got, Unavailable) and "没给类型名" in got.reason


def test_spinlock_ignores_the_lock_word():
    ctx = ReadCtx(layout={"SpinNoIrq<Vec>": {"data": 8}})
    mem = DictMemory({SLOT: le(1) + le(PAYLOAD)})
    assert SpinLock(u64, type_name="SpinNoIrq<Vec>")(mem, SLOT, ctx) == PAYLOAD


def test_composition_arc_of_mutex():
    ctx = ReadCtx(layout={"ArcInner<Mutex<T>>": {"data": 16},
                          "Mutex<T>": {"data": 8}})
    mem = DictMemory({SLOT: le(INNER),
                      INNER: le(2) + le(1) + le(0) + le(PAYLOAD)})
    r = Arc(Mutex(u64, type_name="Mutex<T>"), inner_type="ArcInner<Mutex<T>>")
    assert r(mem, SLOT, ctx) == PAYLOAD


def test_unsafecell_is_the_only_constant_offset():
    assert UnsafeCell()(DictMemory(), SLOT, ReadCtx()) == SLOT
    assert "语言保证" in UnsafeCell().provenance(ReadCtx())


def test_ptr_returns_address_and_can_opt_out_of_null_absence():
    ctx = ReadCtx()
    assert Ptr()(DictMemory({SLOT: le(INNER)}), SLOT, ctx) == INNER
    mem = DictMemory({SLOT: le(0)})
    assert Ptr()(mem, SLOT, ctx) is None
    assert Ptr(null_is_absent=False)(mem, SLOT, ctx) == 0


# --------------------------------------------------------------------- main

def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    fails = []
    for name, fn in tests:
        try:
            fn()
            print(f"  OK   {name}")
        except AssertionError as e:
            fails.append((name, str(e) or "断言失败"))
            print(f"  FAIL {name}: {e}")
        except Exception as e:                              # noqa: BLE001
            fails.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERR  {name}: {type(e).__name__}: {e}")

    print(f"\n共 {len(tests)} 项，失败 {len(fails)}")
    if fails:
        for n, why in fails:
            print(f"   {n}: {why}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())



def test_spinrwlock_flat_shape_takes_the_data_field():
    ctx = ReadCtx(layout={"SpinRwLock<T>": {"state": 0, "data": 16}})
    r = SpinRwLock(type_name="SpinRwLock<T>")
    assert r(DictMemory(), SLOT, ctx) == SLOT + 16


def test_spinrwlock_newtype_shape_goes_through_the_base():
    ctx = ReadCtx(layout={"SpinRwLock<T>": {"__0": 0},
                          "BaseSpinRwLock<G, T>": {"state": 8, "data": 16}})
    r = SpinRwLock(type_name="SpinRwLock<T>", base_type="BaseSpinRwLock<G, T>")
    assert r(DictMemory(), SLOT, ctx) == SLOT + 16


def test_spinrwlock_lockdep_feature_shifts_data_and_is_followed():
    ctx = ReadCtx(layout={"SpinRwLock<T>": {"__0": 0},
                          "BaseSpinRwLock<G, T>": {"data": 24}})
    r = SpinRwLock(type_name="SpinRwLock<T>", base_type="BaseSpinRwLock<G, T>")
    assert r(DictMemory(), SLOT, ctx) == SLOT + 24


def test_spinrwlock_half_a_chain_is_refused():
    ctx = ReadCtx(layout={"SpinRwLock<T>": {"__0": 0}})
    r = SpinRwLock(type_name="SpinRwLock<T>", base_type="BaseSpinRwLock<G, T>")
    got = r(DictMemory(), SLOT, ctx)
    assert isinstance(got, Unavailable) and not is_ok(got)


def test_spinrwlock_is_inline_and_never_touches_memory():
    ctx = ReadCtx(layout={"SpinRwLock<T>": {"data": 8}})
    assert SpinRwLock(type_name="SpinRwLock<T>")(DictMemory(), SLOT, ctx) \
        == SLOT + 8



def test_lazylock_walks_value_then_the_oncelock_tuple_field():
    ctx = ReadCtx(layout={"LazyLock<T, F>": {"value": 0, "initializer": 24},
                          "OnceLock<T>": {"__0": 0}})
    r = LazyLock(type_name="LazyLock<T, F>", once_type="OnceLock<T>")
    assert r(DictMemory(), SLOT, ctx) == SLOT


def test_lazylock_lands_on_the_lazyinit_not_on_the_payload():
    ctx = ReadCtx(layout={"LazyLock<T, F>": {"value": 8},
                          "OnceLock<T>": {"__0": 0},
                          "LazyInit<T>": {"inited": 0, "data": 8}})
    at = LazyLock(type_name="LazyLock<T, F>", once_type="OnceLock<T>")(
        DictMemory(), SLOT, ctx)
    assert at == SLOT + 8
    mem = DictMemory().write(at, le(0, 8) + le(GARBAGE))
    got = LazyInit(type_name="LazyInit<T>")(mem, at, ctx)
    assert isinstance(got, Unavailable) and not is_ok(got)


def test_lazylock_accepts_the_bare_tuple_field_spelling():
    ctx = ReadCtx(layout={"LazyLock<T, F>": {"value": 0},
                          "OnceLock<T>": {"0": 16}})
    r = LazyLock(type_name="LazyLock<T, F>", once_type="OnceLock<T>")
    assert r(DictMemory(), SLOT, ctx) == SLOT + 16


def test_lazylock_without_once_type_is_refused_not_guessed_at_zero():
    ctx = ReadCtx(layout={"LazyLock<T, F>": {"value": 0}})
    got = LazyLock(type_name="LazyLock<T, F>")(DictMemory(), SLOT, ctx)
    assert isinstance(got, Unavailable) and not is_ok(got)


def test_lazylock_never_falls_through_to_the_initializer_field():
    ctx = ReadCtx(layout={"LazyLock<T, F>": {"initializer": 24},
                          "OnceLock<T>": {"__0": 0}})
    got = LazyLock(type_name="LazyLock<T, F>", once_type="OnceLock<T>")(
        DictMemory(), SLOT, ctx)
    assert isinstance(got, Unavailable) and not is_ok(got)
    assert "value" in got.reason
    assert "initializer" not in got.reason
