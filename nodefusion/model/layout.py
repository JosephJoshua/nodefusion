
from __future__ import annotations

from dataclasses import dataclass, field


class LayoutError(Exception):
    pass


@dataclass
class StructLayout:

    name: str
    size: int | None
    fields: dict[str, int] = field(default_factory=dict)
    path: str = ""
    field_types: dict[str, int] = field(default_factory=dict)
    variants: dict[str, tuple[int | None, int, int | None]] = field(
        default_factory=dict)
    variant_tag: tuple[int, int | None] | None = None

    def off(self, fname: str) -> int:
        if fname not in self.fields:
            raise LayoutError(
                f"结构体 {self.path or self.name} 里没有字段 {fname!r}。"
                f"已有字段：{', '.join(sorted(self.fields)) or '（无）'}")
        return self.fields[fname]

    def has(self, fname: str) -> bool:
        return fname in self.fields


@dataclass
class Variable:

    name: str
    path: str
    addr: int | None
    type_off: int | None = None
    decl_file: str | None = None


@dataclass
class Function:

    name: str
    path: str
    low_pc: int | None
    decl_file: str | None = None
    params: list[str | None] = field(default_factory=list)


@dataclass
class InlineSite:

    name: str
    path: str
    addr: int
    host: str | None = None
    decl_file: str | None = None
