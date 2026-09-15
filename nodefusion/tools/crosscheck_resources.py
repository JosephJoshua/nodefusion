
from __future__ import annotations

import sys
from pathlib import Path

_TABLES = (
    ("bcache", "_decode_bcache"),
    ("ftable", "_decode_ftable"),
    ("itable", "_decode_itable"),
)


def check(run_dir: str, elf: str, *, manifests: str | None = None,
          limit: int | None = None) -> bool:
    from ..host import guest as G
    from ..host import layout as L
    from ..host import nftrace as nf
    from ..host import resources as R
    from ..host.nfelf import Elf64
    from ..model.dwarfsrc import DwarfSource
    from ..model.manifest import load_dir
    from ..model.probe import detect, probe
    from ..model.snapshot import SnapshotBuilder
    from ..model.symbols import SymbolIndex

    rd = Path(run_dir)
    ms = load_dir(manifests)
    dw = DwarfSource(elf)
    kind, why = detect(ms, dw)
    if kind is None:
        print(f"认不出这是哪个内核：{'；'.join(why)}")
        return False
    if kind != "xv6":
        print(f"这是 {kind}。老的资源表解码器是照 xv6 的 buf/file/inode 写的，"
              f"只有 xv6 能当标准答案，不拿它去比别的内核。")
        return False

    lay_path = rd / "kernel_layout.json"
    if not lay_path.exists():
        print(f"没有 {lay_path} —— 老解码器要靠它拿偏移，缺了就没有标准答案。")
        return False

    m = ms[kind]
    tabled = {e.name: e for e in m.entities if e.table is not None}
    if not tabled:
        print(f"{m.path} 里没有任何实体写了 [entity.table] —— 没东西可比。"
              f"这不算通过。")
        return False

    tr = nf.load(str(rd / "trace.nfb"))
    base = int(tr.meta.get("nf.ram_base", "0x80000000"), 16)
    size = int(tr.meta.get("nf.ram_size", "0x8000000"), 16)
    ram = G.RamImage(base, size)

    e, lay = Elf64(elf), L.load(lay_path)
    if tr.snapshots:
        ram.apply(tr.snapshots[0].pages)
        if not ram.check_kernel_mapping(e):
            print(f"{elf} 跟这份 trace 对不上（入口处的字节和内存里的不一样）。"
                  f"配错 ELF 的时候两边照样读得出数，而且自洽 —— 不比。")
            return False
    old = G.GuestDecoder(e, lay, ram)
    res = probe(m, dw)
    sb = SnapshotBuilder(dw, res, m, syms=SymbolIndex(e, dw))

    frames = tr.snapshots if limit is None else tr.snapshots[:limit]
    diffs: list[tuple] = []
    cells = {n: 0 for n, _ in _TABLES}
    rows_seen = {n: 0 for n, _ in _TABLES}
    avail_agree = {n: 0 for n, _ in _TABLES}

    for i, s in enumerate(frames):
        ram.apply(s.pages)
        made = {t.name: t for t in R.from_entities(m, res, sb.build(ram))}
        for name, meth in _TABLES:
            n = made.get(name)
            if n is None:
                diffs.append((i, name, "-", "老的有这张表", "manifest 没声明"))
                continue
            o = getattr(old, meth)()

            if bool(o.available) != bool(n.available):
                diffs.append((i, name, "available", o.available, n.available))
                continue
            avail_agree[name] += 1
            if not o.available:
                continue

            if len(o.rows) != len(n.rows):
                diffs.append((i, name, "行数", len(o.rows), len(n.rows)))
                continue
            for ro, rn in zip(o.rows, n.rows):
                rows_seen[name] += 1
                for k in sorted(set(ro) | set(rn)):
                    a, b = ro.get(k, "<老的没有这列>"), rn.get(k, "<新的没有这列>")
                    if a == b:
                        cells[name] += 1
                    else:
                        diffs.append((i, name, k, a, b))

    print(f"运行 {rd.name}   内核 {kind}   ELF={elf}")
    print(f"  快照 {len(frames)} 帧")
    total_rows = sum(rows_seen.values())
    for name, _ in _TABLES:
        print(f"    {name:<8} 可用性一致 {avail_agree[name]}/{len(frames)}"
              f"   行 {rows_seen[name]}   逐格一致 {cells[name]}")
    if not total_rows:
        print("  一行都没比到 —— 这不算通过。")
        return False

    if diffs:
        print(f"\n  不一致 {len(diffs)} 处，前 20 处：")
        for i, name, k, a, b in diffs[:20]:
            print(f"    帧 {i:<4} {name:<8} {k:<12} 老={a!r:<24} 新={b!r}")
        return False

    print("  全部一致 —— manifest 里的实体和写死的那三段给出同一个答案。")
    print("  （只证明两边一致：偏移由 crosscheck_offsetof 证，ELF 配对由 "
          "elfid 管，见模块头。）")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    lim = int(argv[3]) if len(argv) > 3 else None
    return 0 if check(argv[1], argv[2], limit=lim) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
