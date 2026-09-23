"""Refresh embedded report assets, sidecars, and Rust caller labels.

This operates on generated HTML, leaving the archived trace and ELF untouched.
It verifies the previous HTML hash before changing the report.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nodefusion.host.bundle import encode
from nodefusion.host.render import ASSETS
from nodefusion.model.symbols import demangle_v0
from scripts.regenerate_artifact import _DATA, sha256, smoke_report


def refresh_assets(page: str) -> tuple[str, int]:
    """Replace embedded CSS/JS while leaving the verified data block intact."""
    changed = 0
    style_start = page.find("<style>\n")
    if style_start >= 0:
        style_end = page.find("\n</style>", style_start)
        if style_end >= 0:
            current = page[style_start + len("<style>\n"):style_end]
            wanted = (ASSETS / "app.css").read_text(encoding="utf-8")
            if current != wanted:
                page = (page[:style_start + len("<style>\n")] + wanted
                        + page[style_end:])
                changed += 1

    script_start = page.rfind("<script>\n")
    if script_start >= 0:
        script_end = page.find("\n</script>", script_start)
        if script_end >= 0:
            current = page[script_start + len("<script>\n"):script_end]
            wanted = (ASSETS / "app.js").read_text(encoding="utf-8")
            if current != wanted:
                page = (page[:script_start + len("<script>\n")] + wanted
                        + page[script_end:])
                changed += 1
    return page, changed


def finalize(evidence: Path) -> int:
    sidecar = json.loads(evidence.read_text(encoding="utf-8"))
    if sidecar.get("format") == "nodefusion.video-evidence/1":
        record = sidecar["report"]
        html = evidence.with_name(sidecar["html"])
    elif sidecar.get("schema") == "nodefusion.artifact-evidence/1":
        record = sidecar
        if evidence.name == "coverage.json":
            matches = list(evidence.parent.glob("ucore-*.html"))
            if len(matches) != 1:
                raise ValueError(f"expected one chapter report: {evidence.parent}")
            html = matches[0]
        else:
            html = evidence.with_name(evidence.name.removesuffix(".evidence.json") + ".html")
    else:
        raise ValueError(f"unsupported report sidecar: {evidence}")
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
    page = html.read_text(encoding="utf-8")
    if changed:
        match = _DATA.search(page)
        page = page[:match.start(1)] + encode(data) + page[match.end(1):]
    page, assets_changed = refresh_assets(page)
    if changed or assets_changed:
        staged = html.with_name(f".{html.name}.tmp-{os.getpid()}")
        try:
            staged.write_text(page, encoding="utf-8")
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
            json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
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
    files += sorted(args.root.glob("ucoreos/ch*/coverage.json"))
    files += sorted(path for path in args.root.rglob("*.json")
                    if path.name not in {"coverage.json"} and
                    json.loads(path.read_text(encoding="utf-8")).get("report", {}).get(
                        "schema") == "nodefusion.artifact-evidence/1")
    if not files:
        parser.error("no regenerated evidence files found")
    for path in files:
        print(f"{path}: {finalize(path)} caller labels demangled")


if __name__ == "__main__":
    main()
