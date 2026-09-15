
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.rt import DictMemory, ReadCtx, Unavailable, is_ok
from nodefusion.model.readers.scalars import (
    Atomic, Bitfield, Bool, CStr, Enum, Int, Newtype,
    bool_, i32, i64, isize, ppn, u8, u16, u32, u64, usize,
)


BASE = 0x1000
_buf = bytearray(0x40)
_buf[0x00] = 0xAB                                              # u8
_buf[0x01] = 0x01
_buf[0x02] = 0x00
_buf[0x03] = 0x5A
_buf[0x04:0x06] = (0xBEEF).to_bytes(2, "little")               # u16
_buf[0x08:0x0C] = (0xDEADBEEF).to_bytes(4, "little")           # u32 / i32
_buf[0x10:0x18] = (0x1122334455667788).to_bytes(8, "little")
_buf[0x18:0x1D] = b"init\x00"                                  # cstr
_buf[0x20:0x24] = (2).to_bytes(4, "little")
_buf[0x24:0x28] = (99).to_bytes(4, "little")
_buf[0x30:0x38] = (42).to_bytes(8, "little")
_buf[0x38:0x40] = b"ABCDEFGH"

PID_OUTER = BASE + 0x28
NO_NUL = BASE + 0x38
GONE = 0x9000

MEM = DictMemory({
    BASE: bytes(_buf),
    0x2000: b"ok\x00",
    0x3000: (0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"),
})

CTX = ReadCtx(
    layout={"Pid": {"__0": 8}},
    enums={"TaskStatus": {0: "Ready", 1: "Running", 2: "Zombie"}},
    ptr_size=8,
)
CTX32 = ReadCtx(layout=CTX.layout, enums=CTX.enums, ptr_size=4)


def _unavail(v, where=""):
    assert isinstance(v, Unavailable), f"{where}：期望 Unavailable，得到 {v!r}"
    assert not is_ok(v), f"{where}：is_ok 应该是 False"
    assert not v, f"{where}：Unavailable 应该是假值"
    assert v.reason and len(v.reason) > 8, f"{where}：原因太短，人看不懂：{v.reason!r}"
    return v



def test_int_normal():
    assert u8(MEM, BASE + 0x00, CTX) == 0xAB
    assert u16(MEM, BASE + 0x04, CTX) == 0xBEEF
    assert u32(MEM, BASE + 0x08, CTX) == 0xDEADBEEF
    assert u64(MEM, BASE + 0x10, CTX) == 0x1122334455667788


def test_int_signed():
    assert i32(MEM, BASE + 0x08, CTX) == -559038737
    assert i64(MEM, BASE + 0x10, CTX) == 0x1122334455667788
    assert i64(MEM, 0x3000, CTX) == -1
    assert u64(MEM, 0x3000, CTX) == 0xFFFFFFFFFFFFFFFF


def test_int_out_of_range_is_unavailable():
    for r, name in ((u8, "u8"), (u16, "u16"), (u32, "u32"), (u64, "u64")):
        v = _unavail(r(MEM, GONE, CTX), name)
        assert v.addr == GONE, f"{name}：Unavailable 得带上出事地址"
        assert v != 0 and v is not False


def test_int_partial_overlap_is_unavailable():
    _unavail(u64(MEM, BASE + 0x3C, CTX), "跨出映射末尾的 u64")


def test_negative_address_says_so():
    v = _unavail(u32(MEM, -8, CTX), "负地址")
    assert "负数" in v.reason, "负地址要单独说明，别混进'越界'里误导排查方向"


def test_bad_width_raises_at_construction():
    for bad in (0, 3, 5, 16):
        try:
            Int(bad)
            assert False, f"Int({bad}) 应该 raise"
        except ValueError:
            pass


# --------------------------------------------------------- usize / isize

def test_usize_follows_ptr_size():
    assert usize(MEM, BASE + 0x10, CTX) == 0x1122334455667788     # ptr_size=8
    assert usize(MEM, BASE + 0x08, CTX32) == 0xDEADBEEF           # ptr_size=4
    assert isize(MEM, BASE + 0x08, CTX32) == -559038737
    assert isize(MEM, 0x3000, CTX) == -1


def test_usize_rejects_nonsense_ptr_size():
    v = _unavail(usize(MEM, BASE + 0x10, ReadCtx(ptr_size=7)), "ptr_size=7")
    assert "ptr_size" in v.reason


def test_usize_out_of_range():
    _unavail(usize(MEM, GONE, CTX), "usize 越界")
    _unavail(isize(MEM, GONE, CTX), "isize 越界")



def test_bool_normal():
    assert bool_(MEM, BASE + 0x01, CTX) is True
    assert bool_(MEM, BASE + 0x02, CTX) is False


def test_bool_rejects_illegal_byte_by_default():
    v = _unavail(bool_(MEM, BASE + 0x03, CTX), "非法 bool 字节")
    assert "0x5a" in v.reason.lower()


def test_bool_lenient_mode_is_opt_in():
    assert Bool(strict=False)(MEM, BASE + 0x03, CTX) is True


def test_bool_out_of_range():
    _unavail(bool_(MEM, GONE, CTX), "bool 越界")



def test_atomic_is_transparent():
    assert Atomic(u32)(MEM, BASE + 0x08, CTX) == u32(MEM, BASE + 0x08, CTX)
    assert Atomic(bool_)(MEM, BASE + 0x01, CTX) is True
    assert Atomic(usize)(MEM, BASE + 0x10, CTX) == 0x1122334455667788


def test_atomic_propagates_unavailable():
    _unavail(Atomic(u64)(MEM, GONE, CTX), "atomic 越界")


# ----------------------------------------------------------------- newtype

def test_newtype_uses_dwarf_offset():
    assert Newtype(usize, "Pid")(MEM, PID_OUTER, CTX) == 42
    assert Newtype(u32, "Pid")(MEM, PID_OUTER, CTX) == 42


def test_newtype_falls_back_to_zero_offset():
    assert Newtype(usize)(MEM, PID_OUTER + 8, CTX) == 42
    assert Newtype(usize, "NotInLayout")(MEM, PID_OUTER + 8, CTX) == 42


def test_newtype_offset_actually_shifts():
    assert Newtype(u8, "Pid")(MEM, BASE + 0x08 - 8, CTX) == 0xEF


def test_newtype_out_of_range():
    _unavail(Newtype(usize, "Pid")(MEM, GONE, CTX), "newtype 越界")



def test_enum_known_discriminant():
    assert Enum("TaskStatus", 4)(MEM, BASE + 0x20, CTX) == "Zombie"


def test_enum_unknown_discriminant_returns_raw_int():
    v = Enum("TaskStatus", 4)(MEM, BASE + 0x24, CTX)
    assert is_ok(v), "表里查不到不等于读失败"
    assert isinstance(v, int) and not isinstance(v, str)
    assert v == 99


def test_enum_missing_table_returns_raw_int():
    v = Enum("NoSuchEnum", 4)(MEM, BASE + 0x20, CTX)
    assert is_ok(v) and v == 2


def test_enum_out_of_range_is_unavailable():
    _unavail(Enum("TaskStatus", 4)(MEM, GONE, CTX), "枚举越界")


def test_enum_bad_width_raises():
    try:
        Enum("TaskStatus", 3)
        assert False, "宽度 3 应该 raise"
    except ValueError:
        pass



def test_cstr_normal():
    assert CStr(16)(MEM, BASE + 0x18, CTX) == "init"


def test_cstr_near_end_of_mapping_still_reads():
    assert CStr(32)(MEM, 0x2000, CTX) == "ok"


def test_cstr_unterminated_is_unavailable_not_truncated():
    v = _unavail(CStr(8)(MEM, NO_NUL, CTX), "maxlen 内无 NUL")
    assert "NUL" in v.reason
    assert v != "ABCDEFGH"


def test_cstr_runs_off_mapping_says_which_case():
    v = _unavail(CStr(16)(MEM, NO_NUL, CTX), "扫到映射外")
    assert "出了映射" in v.reason


def test_cstr_out_of_range():
    v = _unavail(CStr(16)(MEM, GONE, CTX), "cstr 越界")
    assert v.addr == GONE


def test_cstr_bad_maxlen_raises():
    try:
        CStr(0)
        assert False, "maxlen=0 应该 raise"
    except ValueError:
        pass



def test_bitfield_extracts_range():
    assert Bitfield(0, 8, size=8)(MEM, BASE + 0x10, CTX) == 0x88
    assert Bitfield(8, 8, size=8)(MEM, BASE + 0x10, CTX) == 0x77
    assert Bitfield(56, 8, size=8)(MEM, BASE + 0x10, CTX) == 0x11
    assert Bitfield(0, 1, size=8)(MEM, BASE + 0x10, CTX) == 0
    assert Bitfield(3, 1, size=8)(MEM, BASE + 0x10, CTX) == 1


def test_bitfield_on_narrower_integer():
    assert Bitfield(4, 4, size=4)(MEM, BASE + 0x08, CTX) == 0xE


def test_bitfield_signed():
    assert Bitfield(0, 4, size=8)(MEM, BASE + 0x10, CTX) == 8
    assert Bitfield(0, 4, size=8, signed=True)(MEM, BASE + 0x10, CTX) == -8


def test_bitfield_out_of_range():
    _unavail(Bitfield(0, 8, size=8)(MEM, GONE, CTX), "位段越界")


def test_bitfield_bad_spec_raises_at_construction():
    for args, kw in (((60, 8), {"size": 8}),
                     ((0, 0), {}),
                     ((-1, 4), {}),
                     ((0, 4), {"size": 3})):
        try:
            Bitfield(*args, **kw)
            assert False, f"Bitfield{args} {kw} 应该 raise"
        except ValueError:
            pass



def test_no_reader_ever_returns_a_plausible_default_on_failure():
    readers = [u8, u16, u32, u64, i32, i64, usize, isize, bool_,
               Atomic(u32), Newtype(usize, "Pid"), Newtype(u32),
               Enum("TaskStatus", 4), CStr(16), Bitfield(0, 4, size=8)]
    for r in readers:
        v = r(MEM, GONE, CTX)
        assert isinstance(v, Unavailable), f"{r!r} 在越界地址上回了 {v!r}"
        assert v.addr is not None, f"{r!r} 的 Unavailable 没带地址"
        assert str(v).startswith("取不到"), f"{r!r} 的 Unavailable 文案不对"



def test_ppn_is_a_page_number_not_an_address():
    assert ppn(MEM, BASE + 0x30, CTX) == 42 << 12


def test_ppn_shift_comes_from_ctx_not_hardcoded_twelve():
    ctx = ReadCtx(layout=CTX.layout, enums=CTX.enums, page_shift=16)
    assert ppn(MEM, BASE + 0x30, ctx) == 42 << 16


def test_ppn_out_of_range_stays_unavailable():
    _unavail(ppn(MEM, GONE, CTX), "ppn 越界")


def test_ppn_rejects_a_nonsense_shift():
    ctx = ReadCtx(layout=CTX.layout, enums=CTX.enums, page_shift=0)
    _unavail(ppn(MEM, BASE + 0x30, ctx), "page_shift=0")


def main() -> int:
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)]
    fails = []
    for name, fn in tests:
        try:
            fn()
            print(f"  OK   {name}")
        except AssertionError as e:
            fails.append((name, str(e) or "断言失败"))
            print(f"  FAIL {name}: {e}")
        except Exception as e:
            fails.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERR  {name}: {type(e).__name__}: {e}")
    print(f"\n共 {len(tests)} 项，通过 {len(tests) - len(fails)}，失败 {len(fails)}")
    if fails:
        for name, why in fails:
            print(f"   - {name}: {why}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
