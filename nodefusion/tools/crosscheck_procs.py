
from __future__ import annotations

import sys
from pathlib import Path

_FIELDS = (
    "pid", "name", "state", "state_name", "sz", "pagetable", "parent_slot",
    "parent_pid", "chan", "killed", "xstate", "kstack", "trapframe",
    "priority", "stride", "pass_value", "open_fds", "cwd",
    "user_pages", "cow_pages", "pagetable_pages", "vm_regions", "vm_error",
)

_ZERO_IS_NONE = frozenset({
    "pagetable", "sz", "chan", "kstack", "trapframe", "cwd"})

_DELIBERATE = {
    "state": "数值状态没有跨内核的通用含义（xv6 的 4 和 rCore 的 4 不是一回"
             "事），新路径带的是含义（state_name），不是那个数",
}

_ELF_PROBE_FRAMES = 40


def _elf_matches(ram, elf, snapshots) -> bool:
    for s in snapshots[:_ELF_PROBE_FRAMES]:
        ram.apply(s.pages)
        if ram.check_kernel_mapping(elf):
            return True
    return False


def check(run_dir: str, elf: str, *, manifests: str | None = None,
          limit: int | None = None) -> bool:
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

    tr = nf.load(str(rd / "trace.nfb"))
    ram = G.RamImage(int(tr.meta.get("nf.ram_base", "0x80000000"), 16),
                     int(tr.meta.get("nf.ram_size", "0x8000000"), 16))
    e64 = Elf64(elf)

    if not _elf_matches(ram, e64, tr.snapshots):
        print(f"运行 {rd.name}   内核 {kind}")
        print(f"  ELF 入口处的字节和物理内存对不上：{elf}")
        print("  两个成因，这里分不出是哪个：")
        print("    1) 这个内核不是直接映射的（那样符号地址本就不能当物理地址用）；")
        print("    2) 手上这份 ELF 不是录这趟用的那个构建。")
        print("  不比了 —— 两条路会一起读错同一个地方，然后一致地给出错的答案。")
        return False

    m = ms[kind]
    sb = SnapshotBuilder(dw, probe(m, dw), m, syms=SymbolIndex(e64, dw))
    lay = L.load(lay_path)
    old = G.GuestDecoder(e64, lay, ram)
    new = G.GuestDecoder(e64, lay, ram, entities=sb)

    same = dict.fromkeys(_FIELDS, 0)
    old_only = dict.fromkeys(_FIELDS, 0)
    new_only = dict.fromkeys(_FIELDS, 0)
    diffs: list[tuple] = []
    rowdiff: list[tuple] = []
    rows = 0

    frames = tr.snapshots if limit is None else tr.snapshots[:limit]
    for i, s in enumerate(frames):
        ram.apply(s.pages)
        po = old.decode(i, s.snap_seq).procs
        pn = new.decode(i, s.snap_seq).procs
        if not po and not pn:
            continue
        if len(po) != len(pn):
            rowdiff.append((i, len(po), len(pn)))
            continue
        for a, b in zip(po, pn):
            rows += 1
            for k in _FIELDS:
                x, y = getattr(a, k, None), getattr(b, k, None)
                if k in _ZERO_IS_NONE:
                    x, y = (x or None), (y or None)
                if x is None and y is None:
                    continue
                if y is None:
                    old_only[k] += 1
                elif x is None:
                    new_only[k] += 1
                elif x == y:
                    same[k] += 1
                else:
                    diffs.append((i, k, x, y))

    print(f"运行 {rd.name}   内核 {kind}   ELF={elf}")
    print(f"  ELF 入口字节与内存一致")
    print(f"  快照 {len(frames)} 帧，逐行比对 {rows} 条")

    if rowdiff:
        print(f"  !! {len(rowdiff)} 帧的进程条数对不上，前 5 帧：")
        for i, a, b in rowdiff[:5]:
            print(f"       帧 {i}: 老 {a} 条，新 {b} 条")
        return False

    if not rows:
        print("  一条都没比到 —— 这不算通过。")
        return False

    cmp_fields = [k for k in _FIELDS if same[k] or diffs or new_only[k]]
    print("\n  比到的字段：")
    for k in _FIELDS:
        if not (same[k] or new_only[k]):
            continue
        n_d = sum(1 for d in diffs if d[1] == k)
        seen = same[k] + n_d + new_only[k]
        skipped = rows - seen
        tail = f"（另 {skipped} 行两边都没有）" if skipped else ""
        flag = f"   不一致 {n_d}" if n_d else ""
        extra = f"   新的独有 {new_only[k]}" if new_only[k] else ""
        print(f"    {k:<18} 一致 {same[k]}/{seen}{flag}{extra}{tail}")

    dropped = [k for k in _FIELDS if old_only[k] and k in _DELIBERATE]
    gaps = [k for k in _FIELDS if old_only[k] and k not in _DELIBERATE]

    if dropped:
        print("\n  故意不搬（不是缺口）：")
        for k in dropped:
            print(f"    {k:<18} {_DELIBERATE[k]}")

    if gaps:
        print("\n  覆盖缺口 —— 老的解得出、新的没有（不算失败）：")
        for k in gaps:
            part = (f"（另有 {same[k]} 行两边都有且一致）" if same[k] else "")
            print(f"    {k:<18} 老的有值而新的为空 {old_only[k]}/{rows} 行{part}")
        print("    这些是删掉老路之前要补进 manifest 的；确认某个不该搬的话，")
        print("    连同理由加进 crosscheck_procs.py 的 _DELIBERATE。")
    else:
        print("\n  没有覆盖缺口：老路解得出的字段，manifest 这条路都解得出。")

    if diffs:
        print(f"\n  不一致 {len(diffs)} 处，前 20 处：")
        for i, k, a, b in diffs[:20]:
            print(f"    帧 {i:<4} {k:<18} 老={a!r:<28} 新={b!r}")
        return False

    print(f"\n  比到的 {len(cmp_fields)} 个字段全部一致。")
    print("  （只证两边一致，不证两边都对；也没有语义校验 —— 对 xv6 来说")
    print("   这比 crosscheck_procinfo 弱，不是替代品。见模块头。）")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    lim = int(argv[3]) if len(argv) > 3 else None
    return 0 if check(argv[1], argv[2], limit=lim) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
