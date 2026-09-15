
from __future__ import annotations

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec/event-stream.md"
NFTRACE_PY = ROOT / "host/nftrace.py"
ANALYZE_PY = ROOT / "host/analyze.py"


def _spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def _nftrace_block() -> str:
    text = _spec()
    i = text.index("**`NFTRACE`")
    j = text.index("```", text.index("```", i) + 3)
    return text[i:j]


def test_the_spec_no_longer_calls_the_payload_text():
    row = next(l for l in _spec().splitlines()
               if l.startswith("| 11 ") and "NFTRACE" in l)
    assert "UTF-8" not in row, f"类型 11 又被写成文本了：{row}"


def test_the_documented_payload_is_the_size_the_parser_reads():
    block = _nftrace_block()
    n = 0
    for m in re.finditer(r"uint64_t\s+(\w+)(?:\[(\d+)\])?\s*;", block):
        n += int(m.group(2) or 1)
    assert n, f"没从规范里解出任何字段，块是不是改了格式：\n{block}"

    src = NFTRACE_PY.read_text(encoding="utf-8")
    i = src.index("elif rtype == REC_NFTRACE:")
    fmt = re.search(r'unpack_from\("([^"]+)"', src[i:i + 400])
    assert fmt, "找不到 REC_NFTRACE 那一支的 struct 格式"
    assert struct.calcsize(fmt.group(1)) == n * 8, (
        f"规范说 {n} 个 u64（{n * 8} 字节），"
        f"代码按 {fmt.group(1)}（{struct.calcsize(fmt.group(1))} 字节）解")


def test_every_inner_record_type_in_the_code_is_in_the_spec_table():
    src = ANALYZE_PY.read_text(encoding="utf-8")
    consts = dict(re.findall(r"^\s+(NFT_[A-Z_]+)\s*=\s*(\d+)\s*$",
                             src, re.MULTILINE))
    consts.pop("NFT_MAX_LAG", None)
    assert consts, "一个 NFT_* 记录类型常量都没找到，这条测试该跟着改了"

    spec = _spec()
    for name, num in consts.items():
        row = next((l for l in spec.splitlines()
                    if l.startswith("|") and name in l), None)
        assert row, f"{name} 在规范里没有对应的一行"
        assert re.match(rf"^\|\s*{num}\s*\|", row), (
            f"{name} 代码里是 {num}，规范那行的编号对不上：{row}")


def test_the_spec_distinguishes_legacy_zero_recordings_from_the_new_producer():
    text = _spec()
    assert "都是\n0" in text or "都是 0" in text
    assert "NodeFusion 集成补丁" in text


def test_the_code_points_at_the_spec_not_at_a_file_we_do_not_have():
    for p in (NFTRACE_PY, ANALYZE_PY):
        text = p.read_text(encoding="utf-8")
        i = text.find("kernel/nftrace.h")
        if i == -1:
            continue
        near = text[max(0, i - 400):i + 400]
        assert "event-stream.md" in near, (
            f"{p.name} 只指向 kernel/nftrace.h，而仓库里没有这个文件")
