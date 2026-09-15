
from __future__ import annotations

from ..rt import Memory, ReadCtx, Unavailable, Value

__all__ = [
    "Int", "USize", "ISize", "PageNum", "Bool", "Atomic", "Newtype", "Field",
    "Enum", "CStr", "Bitfield", "Unit",
    "u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64",
    "usize", "isize", "ppn", "bool_", "unit",
]

_SIZES = (1, 2, 4, 8)


def _read_uint(mem: Memory, addr: int, size: int) -> int | None:
    if size == 1:
        return mem.u8(addr)
    if size == 2:
        return mem.u16(addr)
    if size == 4:
        return mem.u32(addr)
    if size == 8:
        return mem.u64(addr)
    raise ValueError(f"不支持的整数宽度 {size}")


def _sign(v: int, size: int) -> int:
    bits = size * 8
    return v - (1 << bits) if v >> (bits - 1) else v


def _guard(addr: int) -> Unavailable | None:
    if addr < 0:
        return Unavailable(f"地址是负数（{addr}），上游的偏移算减了", addr)
    return None



class Int:

    def __init__(self, size: int, signed: bool = False) -> None:
        if size not in _SIZES:
            raise ValueError(f"整数宽度只能是 {_SIZES} 之一，给的是 {size!r}")
        self.size = size
        self.signed = signed

    @property
    def name(self) -> str:
        return f"{'i' if self.signed else 'u'}{self.size * 8}"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        v = _read_uint(mem, addr, self.size)
        if v is None:
            return Unavailable(
                f"读 {self.name} 越界：这 {self.size} 字节不在已映射的物理内存里",
                addr)
        return _sign(v, self.size) if self.signed else v

    def __repr__(self) -> str:
        return f"Int({self.name})"


class _PtrInt:

    signed = False

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        n = ctx.ptr_size
        if n not in (4, 8):
            return Unavailable(
                f"ctx.ptr_size = {n!r}，只支持 4 和 8 —— 探测阶段没填对", addr)
        v = _read_uint(mem, addr, n)
        if v is None:
            kind = "isize" if self.signed else "usize"
            return Unavailable(
                f"读 {kind} 越界：这 {n} 字节不在已映射的物理内存里", addr)
        return _sign(v, n) if self.signed else v

    def __repr__(self) -> str:
        return "isize" if self.signed else "usize"


class USize(_PtrInt):
    signed = False


class ISize(_PtrInt):
    signed = True


class PageNum(_PtrInt):

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        v = super().__call__(mem, addr, ctx)
        if not isinstance(v, int):
            return v
        if ctx.page_shift <= 0:
            return Unavailable(
                f"ctx.page_shift = {ctx.page_shift!r}，不合法 —— "
                f"探测阶段没填对", addr)
        return v << ctx.page_shift

    def __repr__(self) -> str:
        return "ppn"



class Bool:

    def __init__(self, strict: bool = True) -> None:
        self.strict = strict

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        v = mem.u8(addr)
        if v is None:
            return Unavailable("读 bool 越界：这 1 字节不在已映射的物理内存里",
                               addr)
        if v in (0, 1):
            return v == 1
        if self.strict:
            return Unavailable(
                f"bool 字节是 {v:#04x}，Rust 的 bool 只允许 0x00/0x01 —— "
                f"多半是字段偏移算错了或者快照撕裂，不是一个真值", addr)
        return True

    def __repr__(self) -> str:
        return f"Bool(strict={self.strict})"



class Atomic:

    def __init__(self, inner) -> None:
        self.inner = inner

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return self.inner(mem, addr, ctx)

    def __repr__(self) -> str:
        return f"Atomic({self.inner!r})"


class Newtype:

    def __init__(self, inner, type_name: str | None = None, *,
                 field: str = "__0") -> None:
        self.inner = inner
        self.type_name = type_name
        self.field = field

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        off = ctx.offset(self.type_name, self.field) if self.type_name else None
        return self.inner(mem, addr + (off or 0), ctx)

    def __repr__(self) -> str:
        return f"Newtype({self.inner!r}, {self.type_name!r})"


class Field:

    def __init__(self, inner, type_name: str | None, field: str,
                 off: int | None = None) -> None:
        self.inner = inner
        self.type_name = type_name
        self.field = field
        self.off = off

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        off = self.off
        if off is None:
            if not self.type_name:
                return Unavailable(
                    f"不知道 `{self.field}` 是哪个类型的字段 —— 这条链上没人给"
                    f"得出类型名，查不了偏移", addr)
            off = ctx.offset(self.type_name, self.field)
        if off is None:
            return Unavailable(
                f"{self.type_name} 的布局里没有 `{self.field}` 这个字段", addr)
        return self.inner(mem, addr + off, ctx)

    def __repr__(self) -> str:
        return f"Field({self.inner!r}, {self.type_name!r}, {self.field!r})"


class Variant:

    def __init__(self, inner, type_name: str | None, variant: str, *,
                 payload_off: int | None = None, discr: int | None = None,
                 tag_off: int | None = None, tag_size: int | None = None,
                 known: tuple[str, ...] = ()) -> None:
        self.inner = inner
        self.type_name = type_name
        self.variant = variant
        self.payload_off = payload_off
        self.discr = discr
        self.tag_off = tag_off
        self.tag_size = tag_size
        self.known = known

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        if self.payload_off is None:
            have = "、".join(self.known) or "（一个都没量到）"
            return Unavailable(
                f"不知道 {self.type_name or '这个枚举'} 的变体 "
                f"`{self.variant}` 载荷在哪儿。量到的变体有：{have}", addr)
        if self.tag_off is not None and self.discr is not None:
            if self.tag_size not in _SIZES:
                return Unavailable(
                    f"{self.type_name} 的判别值宽度是 {self.tag_size!r}，"
                    f"只认 {_SIZES}", addr)
            got = _read_uint(mem, addr + self.tag_off, self.tag_size)
            if got is None:
                return Unavailable(
                    f"读 {self.type_name} 的判别值越界（+{self.tag_off}，"
                    f"{self.tag_size} 字节）", addr)
            if got != self.discr:
                return None
        return self.inner(mem, addr + self.payload_off, ctx)

    def __repr__(self) -> str:
        return (f"Variant({self.inner!r}, {self.type_name!r}, "
                f"{self.variant!r}, +{self.payload_off})")



class Enum:

    def __init__(self, type_name: str, size: int = 4, *,
                 signed: bool = False) -> None:
        if size not in _SIZES:
            raise ValueError(f"枚举判别值宽度只能是 {_SIZES} 之一，给的是 {size!r}")
        self.type_name = type_name
        self.size = size
        self.signed = signed

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        raw = _read_uint(mem, addr, self.size)
        if raw is None:
            return Unavailable(
                f"读枚举 {self.type_name} 的判别值越界："
                f"这 {self.size} 字节不在已映射的物理内存里", addr)
        if self.signed:
            raw = _sign(raw, self.size)
        name = (ctx.enums.get(self.type_name) or {}).get(raw)
        return raw if name is None else name

    def __repr__(self) -> str:
        return f"Enum({self.type_name!r}, {self.size})"



class CStr:

    def __init__(self, maxlen: int, *, encoding: str = "utf-8",
                 strict: bool = True) -> None:
        if maxlen < 1:
            raise ValueError(f"maxlen 至少是 1，给的是 {maxlen!r}")
        self.maxlen = maxlen
        self.encoding = encoding
        self.strict = strict

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad

        raw = mem.blob(addr, self.maxlen)
        whole = raw is not None
        if raw is None:
            buf = bytearray()
            for i in range(self.maxlen):
                b = mem.u8(addr + i)
                if b is None:
                    break
                buf.append(b)
                if b == 0:
                    break
            if not buf:
                return Unavailable(
                    "读 cstr 越界：首字节就不在已映射的物理内存里", addr)
            raw = bytes(buf)

        end = raw.find(b"\x00")
        if end < 0:
            if whole:
                return Unavailable(
                    f"往后 {self.maxlen} 字节里没有结尾 NUL —— 这里不是 C "
                    f"字符串，或者 maxlen 给小了", addr)
            return Unavailable(
                f"只读到 {len(raw)} 字节就出了映射，还没见到结尾 NUL", addr)

        body = raw[:end]
        try:
            return body.decode(self.encoding,
                               "strict" if self.strict else "replace")
        except UnicodeDecodeError as e:
            return Unavailable(
                f"第 {e.start} 字节起不是合法 {self.encoding}"
                f"（{body[e.start:e.start + 4]!r}）—— 这段多半不是字符串", addr)

    def __repr__(self) -> str:
        return f"CStr({self.maxlen})"



class Bitfield:

    def __init__(self, offset: int, width: int, *, size: int = 8,
                 signed: bool = False) -> None:
        if size not in _SIZES:
            raise ValueError(f"位段底整数宽度只能是 {_SIZES} 之一，给的是 {size!r}")
        if offset < 0 or width < 1:
            raise ValueError(f"位段 offset 要 >=0、width 要 >=1，"
                             f"给的是 offset={offset!r} width={width!r}")
        if offset + width > size * 8:
            raise ValueError(
                f"位段 [{offset}, {offset + width}) 超出了 {size * 8} 位的整数")
        self.offset = offset
        self.width = width
        self.size = size
        self.signed = signed

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        bad = _guard(addr)
        if bad is not None:
            return bad
        raw = _read_uint(mem, addr, self.size)
        if raw is None:
            return Unavailable(
                f"读位段的底整数越界：这 {self.size} 字节不在已映射的物理内存里",
                addr)
        v = (raw >> self.offset) & ((1 << self.width) - 1)
        if self.signed and v >> (self.width - 1):
            v -= 1 << self.width
        return v

    def __repr__(self) -> str:
        return f"Bitfield({self.offset}, {self.width}, size={self.size})"


class Unit:

    size = 0

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return None

    def __repr__(self) -> str:
        return "Unit()"



u8 = Int(1)
u16 = Int(2)
u32 = Int(4)
u64 = Int(8)
i8 = Int(1, signed=True)
i16 = Int(2, signed=True)
i32 = Int(4, signed=True)
i64 = Int(8, signed=True)
usize = USize()
isize = ISize()
ppn = PageNum()
bool_ = Bool()
unit = Unit()
