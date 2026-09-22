"""Render and verify one archived run without changing its source directory.

Example:
    python -m scripts.regenerate_artifact --run nodefusion/runs/rcore-ch7 \
        --out /tmp/regen/rcore/ch7/report.html --strict
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import zlib
from pathlib import Path

from nodefusion.host.analyze import analyze
from nodefusion.host.render import render


_DATA = re.compile(r'<script type="application/nodefusion"[^>]*>([^<]+)</script>')
_SOURCE_FILES = ("trace.nfb", "manifest.json", "watchlist.json",
                 "kernel_layout.json")


def evidence_destination(out: Path) -> Path:
    video_path = out.with_suffix(".json")
    if video_path.is_file():
        video = json.loads(video_path.read_text(encoding="utf-8"))
        if (video.get("format") == "nodefusion.video-evidence/1"
                and video.get("html") == out.name):
            return video_path
    chapter_path = out.parent / "coverage.json"
    if chapter_path.is_file():
        chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
        if (chapter.get("schema") == "nodefusion.artifact-evidence/1"
                and chapter.get("run") == out.stem):
            return chapter_path
    return out.with_suffix(".evidence.json")


def _sidecar_value(path: Path, report: dict) -> dict:
    if not path.exists():
        return report
    old = json.loads(path.read_text(encoding="utf-8"))
    previous = old.get("report", old)
    if (previous.get("coverage", {}).get("status") == "complete" and
            report["coverage"]["status"] != "complete"):
        raise ValueError("refusing to replace a complete report with incomplete coverage")
    if old.get("format") == "nodefusion.video-evidence/1":
        if (old.get("html") != path.with_suffix(".html").name
                or (old.get("info") or {}).get("runs") != [report["run"]]
                or old["info"].get("kernel_elf_sha256") != report["kernel_elf_sha256"]):
            raise ValueError("video belongs to a different run or kernel")
        previous_report = old.get("report")
        if previous_report and (previous_report["source_sha256"]["trace.nfb"] !=
                         report["source_sha256"]["trace.nfb"]):
            raise ValueError("video belongs to a different trace; record a new video")
        mp4 = path.with_name(old["mp4"])
        if mp4.stat().st_size != old["bytes"] or sha256(mp4) != old["mp4_sha256"]:
            raise ValueError("video checksum mismatch")
        old["report"] = report
        return old
    if old.get("schema") == "nodefusion.artifact-evidence/1":
        if path.name == "coverage.json" and old["run"] != report["run"]:
            raise ValueError("chapter evidence belongs to a different run")
        if (old.get("source_sha256", {}).get("trace.nfb") ==
                report["source_sha256"]["trace.nfb"] and
                old.get("kernel_elf_sha256") == report["kernel_elf_sha256"] and
                "archive_bytes" in old):
            report["archive_bytes"] = old["archive_bytes"]
        return report
    raise ValueError(f"unsupported report destination: {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def smoke_report(path: Path) -> dict:
    page = path.read_text(encoding="utf-8")
    matches = _DATA.findall(page)
    if len(matches) != 1 or 'id="panel-functions"' not in page:
        raise ValueError("report lacks a single bundle or the function panel")
    data = json.loads(zlib.decompress(base64.b64decode(matches[0])))
    events = data["events"]
    counts = data["meta"]["function_entries"]
    if (len(events["entry"]) != len(events["insn"])
            or len(events["caller"]) != len(events["insn"])
            or len(events["entry_name"]) != len(events["insn"])
            or sum(events["entry"]) != counts["retained"]
            or counts["retained"] > counts["raw"]):
        raise ValueError("function-entry counts differ from the report data")
    returns = data["meta"].get("function_returns")
    if returns and (returns["matched"] > returns["raw"] or
                    returns["nested_entries"] > counts["raw"] or
                    ("stack" in events and len(events["stack"]) != len(events["insn"]))):
        raise ValueError("function-return data differs from the report events")
    if data["meta"]["event_selection"]["retained"] != len(events["insn"]):
        raise ValueError("event-selection count differs from the report data")
    limit = data["meta"]["event_selection"].get("target_limit")
    if limit is not None and len(events["insn"]) > limit:
        raise ValueError("interactive event count exceeds the browser budget")
    return data


def regenerate(run: Path, out: Path, evidence: Path, *, replace: bool = False,
               strict: bool = False) -> dict:
    if not replace and (out.exists() or evidence.exists()):
        raise FileExistsError("output already exists; pass --replace to regenerate")
    analysis = analyze(run)
    want = (analysis.manifest.get("kernel_elf_identity") or {}).get("sha256")
    actual = sha256(analysis.kernel_elf_path)
    if want and want != actual:
        raise ValueError(f"archived ELF SHA-256 mismatch: {actual} != {want}")
    for name in _SOURCE_FILES:
        if not (run / name).is_file():
            raise FileNotFoundError(run / name)

    out.parent.mkdir(parents=True, exist_ok=True)
    staged = out.with_name(f".{out.name}.tmp-{os.getpid()}")
    try:
        render([analysis], staged)
        data = smoke_report(staged)
        coverage = data["meta"]["capability"]["coverage"]
        if strict and coverage["status"] != "complete":
            raise ValueError(f"strict coverage incomplete: {coverage['blockers']}")
        report = {
            "schema": "nodefusion.artifact-evidence/1",
            "run": analysis.manifest.get("run_name") or run.name,
            "kernel_kind": analysis.kernel_kind,
            "source_sha256": {name: sha256(run / name) for name in _SOURCE_FILES},
            "kernel_elf_sha256": actual,
            "html_sha256": sha256(staged),
            "html_bytes": staged.stat().st_size,
            "function_trace": {
                "kind": ("return-matched observed frames" if
                         data["meta"].get("function_returns", {}).get("raw") else
                         "function-entry sequence (no return events)"),
                **data["meta"]["function_entries"],
                "returns": data["meta"].get("function_returns", {}).get("raw", 0),
                "matched_returns": data["meta"].get("function_returns", {}).get("matched", 0),
                "nested_entries": data["meta"].get("function_returns", {}).get("nested_entries", 0),
            },
            "event_selection": data["meta"]["event_selection"],
            "coverage": coverage,
        }
        evidence.parent.mkdir(parents=True, exist_ok=True)
        value = _sidecar_value(evidence, report)
        temp = evidence.with_name(f".{evidence.name}.tmp-{os.getpid()}")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        staged.replace(out)
        temp.replace(evidence)
    finally:
        staged.unlink(missing_ok=True)
        if "temp" in locals():
            temp.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="exit nonzero if strict applicable coverage is incomplete")
    args = parser.parse_args()
    evidence = args.evidence or evidence_destination(args.out)
    report = regenerate(args.run, args.out, evidence, replace=args.replace,
                        strict=args.strict)
    coverage = report["coverage"]
    print(f"{report['run']}: {coverage['percent']:.2f}% "
          f"({len(coverage['blockers'])} blockers), "
          f"function entries {report['function_trace']['retained']}/"
          f"{report['function_trace']['raw']}, HTML {report['html_bytes']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
