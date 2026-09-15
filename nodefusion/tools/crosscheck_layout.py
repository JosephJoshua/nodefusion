
from __future__ import annotations

import json
import sys

from ..model.dwarfsrc import DwarfSource


def _rust_path(notes: dict, obj: str) -> str | None:
    return notes.get(f"{obj}._rust_path")


def check(layout_json: str, elf: str) -> bool:
    d = json.load(open(layout_json, encoding="utf-8"))
    offsets: dict = d.get("offsets", {})
    notes: dict = d.get("notes", {})
    dw = DwarfSource(elf)

    same = 0
    diff: list[str] = []
    unresolved: list[str] = []
    skipped: list[str] = []

    for key, want in sorted(offsets.items()):
        if "." not in key:
            skipped.append(key)
            continue
        obj, fieldpath = key.split(".", 1)
        rp = _rust_path(notes, obj)
        if rp is None:
            skipped.append(key)
            continue
        st = dw.find(rp)
        if st is None:
            unresolved.append(f"{key}（找不到类型 {rp}）")
            continue
        got = st.fields.get(fieldpath)
        if got is None:
            unresolved.append(f"{key}（{rp} 里没有字段 {fieldpath}）")
            continue
        if got == want:
            same += 1
        else:
            diff.append(f"{key}: 旧={want} 新={got}")

    print(f"内核形态 kind={d.get('kind')}  ELF={elf}")
    print(f"  一致 {same} 项")
    if diff:
        print(f"  !! 不一致 {len(diff)} 项 —— 这是真问题：")
        for x in diff:
            print(f"       {x}")
    if unresolved:
        print(f"  查不到 {len(unresolved)} 项（可能是这份 ELF 不是这一章）：")
        for x in unresolved[:8]:
            print(f"       {x}")
    if skipped:
        print(f"  跳过 {len(skipped)} 项（旧代码自拼的名字，没有类型可查）："
              f"{'、'.join(skipped[:6])}")
    return not diff


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(0 if check(sys.argv[1], sys.argv[2]) else 1)
