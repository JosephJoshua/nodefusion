
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class Memory(Protocol):

    def u8(self, pa: int) -> int | None: ...
    def u16(self, pa: int) -> int | None: ...
    def u32(self, pa: int) -> int | None: ...
    def i32(self, pa: int) -> int | None: ...
    def u64(self, pa: int) -> int | None: ...
    def blob(self, pa: int, n: int) -> bytes | None: ...
    def cstr(self, pa: int, maxlen: int) -> str | None: ...


class DictMemory:

    def __init__(self, chunks: dict[int, bytes] | None = None) -> None:
        self.chunks: dict[int, bytes] = dict(chunks or {})

    def write(self, pa: int, data: bytes) -> "DictMemory":
        self.chunks[pa] = data
        return self

    def _slice(self, pa: int, n: int) -> bytes | None:
        for base, buf in self.chunks.items():
            if base <= pa and pa + n <= base + len(buf):
                return buf[pa - base:pa - base + n]
        return None

    def u8(self, pa: int) -> int | None:
        b = self._slice(pa, 1)
        return None if b is None else b[0]

    def u16(self, pa: int) -> int | None:
        b = self._slice(pa, 2)
        return None if b is None else int.from_bytes(b, "little")

    def u32(self, pa: int) -> int | None:
        b = self._slice(pa, 4)
        return None if b is None else int.from_bytes(b, "little")

    def i32(self, pa: int) -> int | None:
        b = self._slice(pa, 4)
        return None if b is None else int.from_bytes(b, "little", signed=True)

    def u64(self, pa: int) -> int | None:
        b = self._slice(pa, 8)
        return None if b is None else int.from_bytes(b, "little")

    def blob(self, pa: int, n: int) -> bytes | None:
        return self._slice(pa, n)

    def cstr(self, pa: int, maxlen: int) -> str | None:
        b = self._slice(pa, maxlen)
        if b is None:
            return None
        i = b.find(b"\x00")
        return b[:i if i >= 0 else len(b)].decode("utf-8", "replace")



@dataclass(frozen=True)
class Unavailable:

    reason: str
    addr: int | None = None

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        at = f"（@{self.addr:#x}）" if self.addr is not None else ""
        return f"取不到{at}：{self.reason}"


Value = int | str | bool | bytes | list | dict | None | Unavailable


def is_ok(v: Value) -> bool:
    return not isinstance(v, Unavailable)


@dataclass
class ReadCtx:

    layout: dict[str, dict[str, int]] = field(default_factory=dict)
    enums: dict[str, dict[int, str]] = field(default_factory=dict)
    field_types: dict[str, dict[str, str]] = field(default_factory=dict)
    ptr_size: int = 8
    page_shift: int = 12
    max_items: int = 4096

    def offset(self, type_name: str, field_name: str) -> int | None:
        return (self.layout.get(type_name) or {}).get(field_name)

    def field_type(self, type_name: str, field_name: str) -> str | None:
        return (self.field_types.get(type_name) or {}).get(field_name)


class Reader(Protocol):

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value: ...
