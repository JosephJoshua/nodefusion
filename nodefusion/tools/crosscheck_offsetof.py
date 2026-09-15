
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..model.dwarfsrc import DwarfSource
from ..model.manifest import load_dir
from ..model.probe import detect, probe
from ..model.resolve import PRESENT

_INCLUDES = (
    "kernel/types.h", "kernel/param.h", "kernel/memlayout.h", "kernel/riscv.h",
    "kernel/spinlock.h", "kernel/proc.h", "kernel/fs.h", "kernel/sleeplock.h",
    "kernel/file.h", "kernel/buf.h",
)

_CFLAGS = (
    "-march=rv64gc", "-mcmodel=medany", "-ffreestanding", "-fno-common",
    "-nostdlib", "-fno-builtin", "-Wno-main", "-fno-stack-protector",
    "-fno-pie", "-no-pie",
)

_CC_CANDIDATES = ("riscv64-unknown-elf-gcc", "riscv64-elf-gcc",
                  "riscv64-linux-gnu-gcc")


def _find_cc() -> str | None:
    for c in _CC_CANDIDATES:
        if shutil.which(c):
            return c
    return None


def _lab_stage(kernel_dir: Path) -> int:
    mk = kernel_dir / "Makefile"
    if mk.exists():
        for line in mk.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("LAB_STAGE") and "?=" in s:
                try:
                    return int(s.split("?=", 1)[1].strip())
                except ValueError:
                    break
    return 5


def _designator(f) -> str:
    return ".".join(f.hops) if f.hops else f.path


def check(kernel_dir: str, elf: str, *, manifests: str | None = None,
          keep: bool = False) -> bool:
    kd = Path(kernel_dir)
    ms = load_dir(manifests)
    dw = DwarfSource(elf)
    kind, why = detect(ms, dw)
    if kind is None:
        print(f"认不出这是哪个内核：{'；'.join(why)}")
        return False

    m = ms[kind]
    lang = (getattr(m, "language", None) or "").lower()
    if lang and lang != "c":
        print(f"{kind} 是 {lang} 写的，没有 offsetof —— 这条路只适用于 C 内核。"
              f"请改用 crosscheck_layout.py。")
        return False

    cc = _find_cc()
    if cc is None:
        print(f"找不到 riscv64 交叉编译器（找过：{'、'.join(_CC_CANDIDATES)}）。"
              f"没有编译器就没法拿 offsetof 当标准答案，**不降级成只信 DWARF** —— "
              f"那样等于没检查。")
        return False

    res = probe(m, dw)
    stage = _lab_stage(kd)

    lines = ["/* NodeFusion offsetof 对拉探针 —— 自动生成 */"]
    lines += [f'#include "{h}"' for h in _INCLUDES]
    lines.append("")

    checked: list[str] = []
    skipped: list[str] = []
    for e in res.entities:
        if not e.ok or not e.type:
            continue
        cty = e.type if e.type.startswith("struct ") else f"struct {e.type}"
        if e.size is not None:
            lines.append(
                f'_Static_assert(sizeof({cty}) == {e.size}, '
                f'"sizeof({e.type}) != {e.size} (DWARF)");')
            checked.append(f"sizeof({e.type})={e.size}")
        for f in e.fields:
            if f.state != PRESENT or f.offset is None:
                skipped.append(f"{e.name}.{f.name}（{f.state}）")
                continue
            d = _designator(f)
            lines.append(
                f'_Static_assert(__builtin_offsetof({cty}, {d}) == {f.offset}, '
                f'"offsetof({e.type}, {d}) != {f.offset} (DWARF)");')
            checked.append(f"{e.name}.{f.name}@{f.offset}")

    if not checked:
        print("一条都没解出来，没什么可核对的。")
        return False

    src = "\n".join(lines) + "\n"
    tmp = Path(tempfile.mkdtemp(prefix="nf-offsetof-"))
    cfile = tmp / "probe.c"
    cfile.write_text(src, encoding="utf-8")

    cmd = [cc, *_CFLAGS, f"-DLAB_STAGE={stage}", f"-I{kd}",
           "-c", "-o", str(tmp / "probe.o"), str(cfile)]
    p = subprocess.run(cmd, capture_output=True, text=True)

    print(f"内核 {kind}  ELF={elf}")
    print(f"  编译器 {cc}   LAB_STAGE={stage}（取自 {kd/'Makefile'}）")
    print(f"  断言 {len(checked)} 条：{'、'.join(checked[:6])}"
          f"{' …' if len(checked) > 6 else ''}")
    if skipped:
        print(f"  没断言 {len(skipped)} 条（DWARF 里就没解出来，不是不一致）："
              f"{'、'.join(skipped[:5])}")

    if p.returncode == 0:
        print("  全部一致 —— offsetof 和 DWARF 给出同一套偏移。")
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
        return True

    print("  !! 有对不上的，编译器原话：")
    shown = 0
    for line in (p.stderr or "").splitlines():
        low = line.lower()
        if "static assertion" in low or "static_assert" in low or "error:" in low:
            print(f"       {line.strip()}")
            shown += 1
    if not shown:
        print("       （不是断言失败，是编译本身没过。原始输出：）")
        for line in (p.stderr or "").splitlines()[:12]:
            print(f"       {line.strip()}")
    print(f"  探针留在 {cfile}")
    return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(0 if check(sys.argv[1], sys.argv[2]) else 1)
