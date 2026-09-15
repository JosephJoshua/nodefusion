
from __future__ import annotations

from pathlib import Path

import pytest

LIVE = {
    "rcore": Path("/Users/jsph273/Desktop/Code/tsinghua/rCore-Tutorial-Code-2025S"
                  "/os/target/riscv64gc-unknown-none-elf/release/os"),
}


def kernel_elf(kind: str) -> Path | None:
    from nodefusion.host import kernels as K
    try:
        p = K.archived_elf(kind)
    except K.ProfileError:
        p = None
    if p is not None and p.is_file():
        return p
    live = LIVE.get(kind)
    return live if live is not None and live.is_file() else None


def needs(kind: str):
    return pytest.mark.skipif(
        kernel_elf(kind) is None,
        reason=(f"要一份 {kind} 的内核 ELF：nodefusion/kernels/{kind}-*.elf"
                f"（录任意一趟会自动归档一份），或者构建产物 "
                f"{LIVE.get(kind, '(没登记构建路径)')}"))


def elf_or_skip(kind: str) -> Path:
    p = kernel_elf(kind)
    if p is None:
        pytest.skip(needs(kind).kwargs["reason"])
    return p
