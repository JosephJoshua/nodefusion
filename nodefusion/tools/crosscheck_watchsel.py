
from __future__ import annotations

import sys
from pathlib import Path

from ..host.nfelf import Elf64
from ..host import watchlist as WL
from ..model import manifest as M
from ..model.dwarfsrc import DwarfSource
from ..model.watchsel import select


def check(elf_path: str, manifest_path: str, kind: str = "") -> bool:
    kind = kind or Path(manifest_path).stem
    mf = M.load(Path(manifest_path))
    dw = DwarfSource(elf_path)
    elf = Elf64(elf_path)

    syms = [s for s in elf.symbols
            if s.value and s.name and (s.is_func or s.sym_type == 0)]
    sel = select(dw, mf.watches, symbols=syms)
    by_addr_new = {s.addr: s for s in sel.picked}

    print(f"ELF={elf_path}")
    print(f"manifest={manifest_path}  kind={kind}")
    print()

    if kind in WL._TABLES:
        wl = WL.build(elf, kind=kind)
        table_len = len(WL._TABLES[kind][0])
        by_addr_old = {e.addr: e for e in wl.entries}
        print(f"写死名单：{table_len} 个名字 -> 解出 {len(wl.entries)} 个观察点，"
              f"{len(wl.missing)} 个名字在这份 ELF 里找不到")
        if wl.missing:
            print(f"  找不到的（名单过期的症状）：{'、'.join(wl.missing[:8])}"
                  f"{' …' if len(wl.missing) > 8 else ''}")
    else:
        by_addr_old = {}
        print(f"写死名单：没有 {kind!r} 这一份（_TABLES 里未登记）")

    print(f"manifest 规则：{len(mf.watches)} 条 -> 选出 {len(sel.picked)} 个观察点")
    if sel.empty_rules:
        print(f"  !! {len(sel.empty_rules)} 条规则一个都没匹配上"
              f"（多半是名字写错了）：")
        for r in sel.empty_rules:
            print(f"       {r}")
    if sel.no_address:
        tot = sum(sel.no_address.values())
        print(f"  匹配上但没有地址（被内联/只有声明）{tot} 个："
              f"{'、'.join(f'{k}={v}' for k, v in sorted(sel.no_address.items()))}")

    if not by_addr_old:
        return not sel.empty_rules

    both = by_addr_old.keys() & by_addr_new.keys()
    only_old = by_addr_old.keys() - by_addr_new.keys()
    only_new = by_addr_new.keys() - by_addr_old.keys()

    print()
    print(f"两边都选中 {len(both)} 个")

    if only_old:
        print(f"只有写死名单选中 {len(only_old)} 个 —— manifest 少声明了这些地方：")
        rows = sorted((by_addr_old[a].name, by_addr_old[a].resource)
                      for a in only_old)
        for nm, res in rows[:20]:
            print(f"       {nm}  [{res}]")
        if len(rows) > 20:
            print(f"       …还有 {len(rows) - 20} 个")

    snap_diff = []
    for a in sorted(both):
        old, new = by_addr_old[a], by_addr_new[a]
        want_snap = new.snapshot in ("always", "event")
        want_thr = new.snapshot == "event"
        if old.snap != want_snap or old.throttle != want_thr:
            snap_diff.append(
                f"{old.name}: 旧 snap={old.snap} throttle={old.throttle}，"
                f"新 snapshot={new.snapshot!r}")
    if snap_diff:
        print(f"!! 快照标记不一致 {len(snap_diff)} 个：")
        for x in snap_diff:
            print(f"       {x}")
    else:
        print("快照标记：两边一致")

    rate_diff = [f"{by_addr_old[a].name}: 名单不抽稀，规则 throttle="
                 f"{by_addr_new[a].throttle}"
                 for a in sorted(both) if by_addr_new[a].throttle]
    if rate_diff:
        print(f"!! 名单里的点被规则抽稀了 {len(rate_diff)} 个：")
        for x in rate_diff:
            print(f"       {x}")
    else:
        print("事件节流：名单里的点一个都没被抽稀")

    if only_new:
        print(f"只有 manifest 规则选中 {len(only_new)} 个 —— 名单过期，"
              f"或者规则比名单宽：")
        rows = sorted((by_addr_new[a].name, by_addr_new[a].subsystem)
                      for a in only_new)
        for nm, sub in rows[:20]:
            print(f"       {nm}  [{sub}]")
        if len(rows) > 20:
            print(f"       …还有 {len(rows) - 20} 个")

    return not sel.empty_rules


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        raise SystemExit(2)
    ok = check(sys.argv[1], sys.argv[2],
               sys.argv[3] if len(sys.argv) == 4 else "")
    raise SystemExit(0 if ok else 1)
