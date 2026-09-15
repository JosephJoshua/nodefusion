
from __future__ import annotations

import sys
from pathlib import Path

_KEYS = ("slot", "pid", "name", "state_name", "sz", "pagetable",
         "parent_pid", "parent_slot", "chan", "killed", "xstate",
         "priority", "stride", "pass_value", "open_fds")

_ZERO_IS_NONE = {"pagetable", "sz", "chan"}


def _unmapped_state(v) -> bool:
    return isinstance(v, str) and v.startswith("?")


def check(run_dir: str, elf: str, *, manifests: str | None = None):
    from ..host import guest as G
    from ..host import layout as L
    from ..host import nftrace as nf
    from ..host.nfelf import Elf64
    from ..model.dwarfsrc import DwarfSource
    from ..model.manifest import load_dir
    from ..model.probe import detect, probe
    from ..model.snapshot import SnapshotBuilder
    from ..model.symbols import SymbolIndex

    rd = Path(run_dir)
    lay_path = rd / "kernel_layout.json"
    if not lay_path.exists():
        print(f"没有 {lay_path} —— 老解码器要靠它拿偏移，缺了就没有标准答案。")
        return False

    ms = load_dir(manifests)
    dw = DwarfSource(elf)
    kind, why = detect(ms, dw)
    if kind is None:
        print(f"认不出这是哪个内核：{'；'.join(why)}")
        return False
    if kind != "xv6":
        print(f"这是 {kind}。老的 ProcInfo 是照 xv6 设计的，只有 xv6 那条分支"
              f"能当标准答案，不拿它去比别的内核。")
        return False

    tr = nf.load(str(rd / "trace.nfb"))
    base = int(tr.meta.get("nf.ram_base", "0x80000000"), 16)
    size = int(tr.meta.get("nf.ram_size", "0x8000000"), 16)
    ram = G.RamImage(base, size)

    m = ms[kind]
    sb = SnapshotBuilder(dw, probe(m, dw), m, syms=SymbolIndex(Elf64(elf), dw))
    lay, e64 = L.load(lay_path), Elf64(elf)
    old = G.GuestDecoder(e64, lay, ram)
    new = G.GuestDecoder(e64, lay, ram, entities=sb)

    agree = {k: 0 for k in _KEYS}
    diffs: list[tuple] = []
    bad_state = n = 0

    for i, s in enumerate(tr.snapshots):
        ram.apply(s.pages)
        po = old.decode(i, s.snap_seq).procs
        pn = new.decode(i, s.snap_seq).procs
        if not po:
            continue
        if len(po) != len(pn):
            diffs.append((i, "行数", len(po), len(pn)))
            continue
        for a, b in zip(po, pn):
            n += 1
            bad_state += _unmapped_state(a.state_name) or _unmapped_state(b.state_name)
            for k in _KEYS:
                x, y = getattr(a, k), getattr(b, k)
                if k in _ZERO_IS_NONE:
                    x, y = (x or None), (y or None)
                if x == y:
                    agree[k] += 1
                else:
                    diffs.append((i, k, x, y))

    print(f"运行 {rd.name}   内核 {kind}   ELF={elf}")
    print(f"  快照 {len(tr.snapshots)} 帧，逐行比对 {n} 条 ProcInfo "
          f"× {len(_KEYS)} 个字段")
    rows = [d for d in diffs if d[1] == "行数"]
    if rows:
        print(f"  !! {len(rows)} 帧的行数对不上（老 vs 新），前 5 帧：")
        for _, _, a, b in rows[:5]:
            print(f"       老 {a} 行，新 {b} 行")
        print("     新的那条按 manifest 的 [entity.liveness] 跳过空槽，"
              "老的只在 state==0 且 pid==0 时跳，")
        print("     所以老的多出来是**可能**的；但差得多的时候先怀疑 ELF 配错 ——")
        print("     基址错了会读出一片状态越界的槽，两条路的过滤强度不同就分道扬镳。")
        return False

    if not n:
        print("  一条都没比到 —— 这不算通过。")
        return False
    for k in _KEYS:
        print(f"    {k:<12} 一致 {agree[k]}/{n}")

    if bad_state:
        v = getattr(new.entities.m.entity("task"), "root_symbol", "proc")
        print(f"\n  !! {bad_state} 行的 state 不在任何枚举变体里。")
        print(f"     xv6 的 state 只能是 UNUSED..ZOMBIE，BSS 又是清零的，"
              f"所以这个值不该出现。")
        print(f"     最常见的原因是 **ELF 跟这趟运行对不上** —— 两条路都从"
              f"这个 ELF 里取 `{v}` 的地址，")
        print(f"     换个构建就一起读到别的地方去了，然后一致地读出垃圾。")
        print(f"     核对 manifest.json 里的 kernel_elf，确认内核没被重新编译过。")
        return False

    if diffs:
        print(f"  !! 不一致 {len(diffs)} 处，前 15 条：")
        for d in diffs[:15]:
            print("       帧 %s  %s：老=%r  新=%r" % d)
        return False

    print("  全部一致 —— 搬到 ProcInfo 这一步没走歪，行数也对得上。")
    print("  （只证明两边一致。ELF 配错的话两边会一起错，见模块头。）")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(0 if check(sys.argv[1], sys.argv[2]) else 1)
