#!/usr/bin/env python3

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from nodefusion.host import dwarf as old_dwarf          # noqa: E402
from nodefusion.host.nfelf import Elf64                 # noqa: E402
from nodefusion.model.dwarfsrc import DwarfSource       # noqa: E402


def compare(path: str) -> bool:
    print(f"=== {path}")

    t0 = time.time()
    old = old_dwarf.DwarfInfo(path, elf=Elf64(path))
    t_old = time.time() - t0

    t1 = time.time()
    new = DwarfSource(path)
    t_new = time.time() - t1

    print(f"  host/dwarf.py    {len(old.structs):>6} structs  {t_old:5.1f}s")
    print(f"  model/dwarfsrc   {len(new.structs):>6} structs  {t_new:5.1f}s"
          f"   +{len(new.variables)} vars  +{len(new.functions)} fns")

    only_old = set(old.structs) - set(new.structs)
    only_new = set(new.structs) - set(old.structs)
    both = set(old.structs) & set(new.structs)

    mismatched = []
    for p in sorted(both):
        a, b = old.structs[p], new.structs[p]
        if a.fields != b.fields or a.size != b.size:
            mismatched.append(p)

    print(f"  共有 {len(both)}，仅旧 {len(only_old)}，仅新 {len(only_new)}，"
          f"布局不一致 {len(mismatched)}")

    if not both:
        print("  !! 两边都没读到结构体：这个 ELF 没有可用的调试信息，"
              "本次对比不构成证据（编译时加 -g）")
        return False

    dangling = [f"{s.path}.{f}" for s in new.structs.values()
                for f, to in s.field_types.items() if not new.knows_type(to)]
    if dangling:
        print(f"  !! 悬空类型引用 {len(dangling)} 个（引用偏移算错了），"
              f"例：{'、'.join(dangling[:3])}")

    ok = not mismatched and not dangling
    for p in mismatched[:5]:
        a, b = old.structs[p], new.structs[p]
        print(f"    !! {p}")
        print(f"       size  old={a.size} new={b.size}")
        for k in sorted(set(a.fields) | set(b.fields)):
            x, y = a.fields.get(k), b.fields.get(k)
            if x != y:
                print(f"       {k:<24} old={x} new={y}")
    if len(mismatched) > 5:
        print(f"    ... 还有 {len(mismatched) - 5} 个")

    for label, s in (("仅旧有", only_old), ("仅新有", only_new)):
        if s:
            sample = "、".join(sorted(s)[:3])
            print(f"    ({label} {len(s)} 个，例：{sample}）")

    new.close()
    return ok


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    results = [compare(p) for p in argv]
    print()
    if all(results):
        print("全部一致")
        return 0
    print("有内核对不上，见上")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
