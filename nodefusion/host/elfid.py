
from __future__ import annotations


_ROOT_SYMBOLS = ("proc", "cpus",                       # xv6
                 "TASK_MANAGER", "PID2PCB", "PROCESSOR")  # rCore


def elf_identity(path) -> dict:
    import hashlib
    from pathlib import Path as _P

    p = _P(path)
    out: dict = {}
    try:
        out["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        out["size_bytes"] = p.stat().st_size
    except OSError as e:
        out["unavailable"] = f"读不了 {p}：{e}"
        return out

    try:
        from .nfelf import Elf64
        syms = Elf64(str(p)).symbols
        by_name = {s.name: s for s in syms} if isinstance(syms, list) else syms
        def _addr(s):
            return getattr(s, "value", getattr(s, "addr", None)) if s else None

        roots = {}
        for n in _ROOT_SYMBOLS:
            a = _addr(by_name.get(n))
            if a is not None:
                roots[n] = f"{a:#x}"
                continue
            # `_ZN75_$LT$os..task..manager..TASK_MANAGER$u20$as$u20$...LAZY...E`。
            if not n.isupper():
                continue
            hits = sorted(k for k in by_name if n in k)
            if len(hits) == 1 and _addr(by_name[hits[0]]) is not None:
                roots[n] = {"symbol": hits[0],
                            "addr": f"{_addr(by_name[hits[0]]):#x}"}
            elif len(hits) > 1:
                roots[n] = {"ambiguous": len(hits), "candidates": hits[:4]}
        if roots:
            out["root_symbols"] = roots
        else:
            out["root_symbols_note"] = (
                f"{p.name} 里一个都没找到：{'/'.join(_ROOT_SYMBOLS)}")
    except Exception as e:                       # noqa: BLE001
        out["root_symbols_note"] = f"读符号表失败：{type(e).__name__}: {e}"
    return out

def _touched_after(elf_path, recorded_utc: str | None) -> str | None:
    if not recorded_utc:
        return None
    from datetime import datetime, timezone
    from pathlib import Path as _P
    try:
        mt = datetime.fromtimestamp(_P(elf_path).stat().st_mtime, timezone.utc)
        rec = datetime.fromisoformat(recorded_utc.replace("Z", "+00:00"))
        if rec.tzinfo is None:
            rec = rec.replace(tzinfo=timezone.utc)
    except (OSError, ValueError):
        return None
    if mt <= rec:
        return None
    return (f"而且这份 ELF 的修改时间（{mt:%Y-%m-%d %H:%M} UTC）晚于本次录制的"
            f"开始时间（{rec:%Y-%m-%d %H:%M} UTC）—— 录完之后它被重新写过。"
            f"这**不证明**内容变了（重编出同样的二进制，mtime 一样会变），"
            f"但在查不了的前提下，这是唯一现成的线索，值得先确认再看结论。")


def compare(recorded: dict | None, elf_path, *,
            recorded_utc: str | None = None) -> list[str]:
    if not recorded:
        msg = ("manifest 里没有 kernel_elf_identity（老的 run 目录）："
               "**查不了**这份 ELF 是不是录制时那份。不是没问题，是不知道。")
        extra = _touched_after(elf_path, recorded_utc)
        return [msg + ("" if extra is None else " " + extra)]

    out: list[str] = []
    if recorded.get("reconstructed"):
        out.append(f"这份 kernel_elf_identity 是事后补的：{recorded['reconstructed']}")

    now = elf_identity(elf_path)
    if "unavailable" in now:
        return out + [f"读不了当前 ELF：{now['unavailable']}"]

    if (recorded.get("sha256")
            and recorded.get("sha256") == now.get("sha256")):
        return out

    was, isnow = recorded.get("root_symbols") or {}, now.get("root_symbols") or {}

    common = set(was) & set(isnow)
    if not common:
        why = ("录制时没记下根符号" if not was else
               now.get("root_symbols_note")
               or f"现在这份 ELF 里没找到：{'/'.join(sorted(was))}")
        return out + [f"**根符号比不了**：{why}。"
                f"哈希"
                f"{'不同' if recorded.get('sha256') != now.get('sha256') else '相同'}"
                f"，但决定解码对不对的是根符号的地址，而它没能比上 —— "
                f"这是查不了，不是没问题。"]

    moved = {k: (v, isnow[k]) for k, v in was.items()
             if k in isnow and isnow[k] != v}
    if moved:
        for k, (a, b) in sorted(moved.items()):
            a = a if isinstance(a, str) else a.get("addr", a)
            b = b if isinstance(b, str) else b.get("addr", b)
            out.append(f"**{k} 的地址变了**：录制时 {a}，现在 {b}。"
                       f"这份 ELF 不是录这趟用的那个 —— 照它解会整表错位，"
                       f"而且两条解码路会一起错、互相印证，看不出来。")
        return out

    if recorded.get("sha256") and recorded["sha256"] != now.get("sha256"):
        out.append("内核 ELF 重新编译过（哈希不同），但根符号地址没变 —— "
                   "进程表还在原地，解码仍然成立。")
    return out
