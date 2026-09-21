"""Refresh verified report sidecars and normalize Rust caller labels.

This operates on generated HTML, leaving the archived trace and ELF untouched.
It verifies the previous HTML hash before changing the report.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nodefusion.host.bundle import encode
from nodefusion.model.symbols import demangle_v0
from scripts.regenerate_artifact import _DATA, sha256, smoke_report


def finalize(evidence: Path) -> int:
    record = json.loads(evidence.read_text(encoding="utf-8"))
    html = evidence.with_name(evidence.name.removesuffix(".evidence.json") + ".html")
    if sha256(html) != record["html_sha256"]:
        raise ValueError(f"HTML hash differs from sidecar: {html}")
    data = smoke_report(html)
    changed = 0
    funcs = data["dict"]["funcs"]
    for i, name in enumerate(funcs):
        if name.startswith("_R"):
            readable = demangle_v0(name, impls=True, generics=True)
            if readable and readable != name:
                funcs[i] = readable
                changed += 1
    if changed:
        page = html.read_text(encoding="utf-8")
        match = _DATA.search(page)
        staged = html.with_name(f".{html.name}.tmp-{os.getpid()}")
        try:
            staged.write_text(page[:match.start(1)] + encode(data) +
                              page[match.end(1):], encoding="utf-8")
            if (smoke_report(staged)["meta"]["event_selection"] !=
                    data["meta"]["event_selection"]):
                raise ValueError("event selection changed during label normalization")
            staged.replace(html)
        finally:
            staged.unlink(missing_ok=True)
    record["html_sha256"] = sha256(html)
    record["html_bytes"] = html.stat().st_size
    record["event_selection"] = data["meta"]["event_selection"]
    staged_evidence = evidence.with_name(f".{evidence.name}.tmp-{os.getpid()}")
    try:
        staged_evidence.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        staged_evidence.replace(evidence)
    finally:
        staged_evidence.unlink(missing_ok=True)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    files = sorted(args.root.rglob("*.evidence.json"))
    if not files:
        parser.error("no regenerated evidence files found")
    for path in files:
        print(f"{path}: {finalize(path)} caller labels demangled")


if __name__ == "__main__":
    main()
