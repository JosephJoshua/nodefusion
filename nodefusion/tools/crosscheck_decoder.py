
from __future__ import annotations

import sys
from pathlib import Path

_PAIRS = (
    ("pid", "pid"),
    ("state_name", "state"),
    ("name", "name"),
    ("pagetable", "pgtbl"),
    ("sz", "sz"),
    ("priority", "priority"),
    ("stride", "stride"),
    ("pass_value", "pass"),
    ("chan", "chan"),
    ("killed", "killed"),
    ("xstate", "xstate"),
)

_ZERO_IS_NONE = {"pgtbl", "sz", "chan"}


def _unmapped_state(v) -> bool:
    if isinstance(v, str):
        return v.startswith("?")
    return False


def _norm(old, new, key: str):
    if key in _ZERO_IS_NONE:
        return (old or None), (new or None)
    if key == "name":
        return (old or ""), (new or "")
    return old, new


def check(run_dir: str, elf: str, *, manifests: str | None = None,
          limit: int | None = None) -> bool:
    from ..host import guest as G
    from ..host import layout as L
    from ..host import nftrace as nf
    from ..host import procview
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
        print(f"这是 {kind}。老解码器的 ProcInfo 是照 xv6 设计的，只有 xv6 那条"
              f"分支能当标准答案，**不拿它去比别的内核** —— 那样比出来的"
              f"不一致说明不了谁对。")
        return False

    lay_path = rd / "kernel_layout.json"
    if not lay_path.exists():
        print(f"没有 {lay_path} —— 老解码器要靠它拿偏移，缺了就没有标准答案。")
        return False

    tr = nf.load(str(rd / "trace.nfb"))
    base = int(tr.meta.get("nf.ram_base", "0x80000000"), 16)
    size = int(tr.meta.get("nf.ram_size", "0x8000000"), 16)
    ram = G.RamImage(base, size)

    old = G.GuestDecoder(Elf64(elf), L.load(lay_path), ram)
    if not old.procs_ok:
        print(f"老解码器自己就解不出进程表：{old.procs_reason}")
        return False

    m = ms[kind]
    new = SnapshotBuilder(dw, probe(m, dw), m, syms=SymbolIndex(Elf64(elf), dw))

    frames = tr.snapshots if limit is None else tr.snapshots[:limit]
    diffs: list[tuple] = []
    agree: dict[str, int] = {k: 0 for _, k in _PAIRS}
    agree["parent"] = 0
    agree["fds"] = 0
    checked = live_frames = bad_state = 0

    for i, s in enumerate(frames):
        ram.apply(s.pages)
        o = {p.slot: p for p in old._decode_procs()}
        n = new.build(ram).all("task")
        if not o:
            continue
        live_frames += 1
        for slot, po in o.items():
            if slot >= len(n):
                diffs.append((i, slot, "槽位", f"老有槽 {slot}",
                              f"新只走到 {len(n)} 个"))
                continue
            pn = n[slot]
            checked += 1
            bad_state += _unmapped_state(po.state_name)
            for oattr, nname in _PAIRS:
                a, b = _norm(getattr(po, oattr), pn.get(nname), nname)
                if a == b:
                    agree[nname] += 1
                else:
                    diffs.append((i, slot, nname, a, b))
            tgt = pn.link("parent")
            a, b = po.parent_pid, (tgt.get("pid") if tgt else None)
            if a == b:
                agree["parent"] += 1
            else:
                diffs.append((i, slot, "parent(边)", a, b))

            a, b = po.open_fds, procview.open_fd_indices(pn)
            if a == b:
                agree["fds"] += 1
            else:
                diffs.append((i, slot, "fds", a, b))

    print(f"运行 {rd.name}   内核 {kind}   ELF={elf}")
    print(f"  快照 {len(frames)} 帧，其中 {live_frames} 帧有活进程")
    print(f"  逐槽比对 {checked} 条进程记录 × {len(_PAIRS) + 2} 个字段"
          f"（{len(_PAIRS)} 个字段 + parent 边 + fds）")
    if not checked:
        print("  一条都没比到 —— 这不算通过。")
        return False
    for k, v in agree.items():
        print(f"    {k:<10} 一致 {v}/{checked}")

    if bad_state:
        print(f"\n  !! {bad_state} 条记录的 state 不在任何枚举变体里。")
        print("     xv6 的 state 只能是 UNUSED..ZOMBIE，BSS 清零，这个值不该出现。")
        print("     最常见的原因是 **ELF 跟这趟运行对不上**：两条路都从这个 ELF")
        print("     里取 proc 的地址，换个构建就一起搬走，然后一致地读出垃圾。")
        print("     核对 manifest.json 的 kernel_elf，确认内核没被重新编译过。")
        return False

    if not diffs:
        print("  全部一致 —— 新旧两套解码器在同一份内存上给出同一个答案。")
        print("  （只证明两边一致：偏移由 crosscheck_offsetof 证，"
              "地址没有第二个出口，见模块头。）")
        return True

    print(f"  !! 不一致 {len(diffs)} 处，前 15 条：")
    for d in diffs[:15]:
        print("       帧 %s 槽 %s  %s：老=%r  新=%r" % d)
    return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(0 if check(sys.argv[1], sys.argv[2]) else 1)
