
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.dwarfsrc import DwarfSource  # noqa: E402

ADDR = 0x03
PLUS_UCONST = 0x23


class _Attr:
    def __init__(self, value):
        self.value = value


class _CU:
    def __init__(self, address_size: int = 8):
        self._a = {"address_size": address_size}

    def __getitem__(self, k):
        return self._a[k]


class _Die:

    def __init__(self, loc, address_size: int = 8):
        self.attributes = {} if loc is None else {"DW_AT_location": _Attr(loc)}
        self.cu = _CU(address_size)


def addr_of(loc, address_size: int = 8):
    return DwarfSource._static_addr(_Die(loc, address_size))


def op_addr(n: int, size: int = 8) -> bytes:
    return bytes([ADDR]) + n.to_bytes(size, "little")


def uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)



def test_plain_addr_reads_exactly_the_address_width():
    assert addr_of(op_addr(0xFFFF_FFC0_8022_0000)) == 0xFFFF_FFC0_8022_0000


def test_address_width_comes_from_the_cu_not_from_a_hardcoded_8():
    assert addr_of(bytes([ADDR]) + (0x8010_0000).to_bytes(4, "little"),
                   address_size=4) == 0x8010_0000



def test_addr_plus_uconst_is_computed_not_swallowed():
    cases = [
        (op_addr(0x00) + bytes([PLUS_UCONST, 0x28]), 0x28),
        (op_addr(0x00) + bytes([PLUS_UCONST, 0x40]), 0x40),
        (op_addr(0x68) + bytes([PLUS_UCONST, 0x08]), 0x70),
    ]
    for expr, want in cases:
        got = addr_of(expr)
        assert got == want, f"{expr.hex(' ')} -> {got:#x}，应该是 {want:#x}"


def test_the_old_swallowing_behaviour_is_gone():
    expr = op_addr(0x00) + bytes([PLUS_UCONST, 0x28])
    swallowed = int.from_bytes(expr[1:], "little")
    assert swallowed == 0x28230000000000000000
    assert addr_of(expr) != swallowed


def test_multi_byte_uconst_is_decoded_as_uleb128():
    assert addr_of(op_addr(0x1000) + bytes([PLUS_UCONST]) + uleb(300)) == 0x1000 + 300



def test_an_unknown_trailing_opcode_is_refused():
    assert addr_of(op_addr(0x8000_0000) + bytes([0x06])) is None


def test_a_truncated_uleb_is_refused():
    assert addr_of(op_addr(0x100) + bytes([PLUS_UCONST, 0x80, 0x80])) is None


def test_extra_bytes_after_the_uconst_are_refused():
    assert addr_of(op_addr(0x100) + bytes([PLUS_UCONST, 0x10, 0x06])) is None


def test_a_short_expression_is_refused():
    assert addr_of(bytes([ADDR, 0x60, 0x00])) is None


def test_a_register_location_is_refused():
    assert addr_of(bytes([0x50])) is None


def test_no_location_at_all_is_refused():
    assert addr_of(None) is None


def test_a_location_list_offset_is_refused():
    assert DwarfSource._static_addr(_Die(0x1234)) is None
