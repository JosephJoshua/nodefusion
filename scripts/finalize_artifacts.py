"""Refresh generated reports, sidecars, and Rust caller labels.

This operates on generated HTML, leaving the archived trace and ELF untouched.
It verifies the previous HTML hash before changing the report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from nodefusion.host.bundle import encode
from nodefusion.host.render import ASSETS, _PAGE, report_javascript
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
            wanted = report_javascript()
            if current != wanted:
                page = (page[:script_start + len("<script>\n")] + wanted
                        + page[script_end:])
                changed += 1
    return page, changed


_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_BLOCK = re.compile(r'<script\s+type="application/nodefusion"[^>]*>.*?</script>',
                    re.DOTALL)


def refresh_shell(page: str) -> tuple[str, int]:
    """Rebuild a generated page without changing its title or encoded runs."""
    title = _TITLE.search(page)
    blocks = _BLOCK.findall(page)
    if not page.startswith("<!DOCTYPE html>") or not title or not blocks:
        return page, 0
    updated = (_PAGE.replace("__TITLE__", title.group(1))
               .replace("__CSS__", (ASSETS / "app.css").read_text(encoding="utf-8"))
               .replace("__JS__", report_javascript())
               .replace("__DATA__", "\n".join(blocks)))
    return updated, int(updated != page)


def finalize(evidence: Path) -> int:
    sidecar = json.loads(evidence.read_text(encoding="utf-8"))
    if sidecar.get("report", {}).get("schema") == "nodefusion.artifact-evidence/1":
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
    returns = data['meta'].get('function_returns')
    if returns and record.get('function_trace') and returns['raw'] != record['function_trace'].get('returns', 0):
        raise ValueError(f'raw return count changed: {html}')
    observations = sidecar.get('observations', {})
    if returns and 'report_function_returns' in observations:
        if observations['report_function_returns']['raw'] != returns['raw']:
            raise ValueError(f'raw observation return count changed: {html}')
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
    page, assets_changed = refresh_shell(page)
    if not (page.startswith("<!DOCTYPE html>") and _TITLE.search(page) and _BLOCK.search(page)):
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
    if returns and record.get('function_trace'):
        record['function_trace'].update(matched_returns=returns['matched'], nested_entries=returns['nested_entries'])
    if returns and 'report_function_returns' in observations:
        observations['report_function_returns'] = returns.copy()
    staged_evidence = evidence.with_name(f".{evidence.name}.tmp-{os.getpid()}")
    try:
        staged_evidence.write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        staged_evidence.replace(evidence)
    finally:
        staged_evidence.unlink(missing_ok=True)
    return changed


def refresh_report_without_sidecar(html: Path) -> bool:
    page = html.read_text(encoding="utf-8")
    updated, changed = refresh_shell(page)
    if not changed:
        return False
    if _BLOCK.findall(updated) != _BLOCK.findall(page):
        raise ValueError(f"embedded runs changed: {html}")
    staged = html.with_name(f".{html.name}.tmp-{os.getpid()}")
    try:
        staged.write_text(updated, encoding="utf-8")
        if _BLOCK.findall(staged.read_text(encoding="utf-8")) != _BLOCK.findall(page):
            raise ValueError(f"embedded runs changed after staging: {html}")
        staged.replace(html)
    finally:
        staged.unlink(missing_ok=True)
    return True


def finalize_comparison(evidence: Path) -> bool:
    record = json.loads(evidence.read_text(encoding="utf-8"))
    if record.get("format") != "nodefusion.comparison-evidence/1":
        raise ValueError(f"unsupported comparison sidecar: {evidence}")
    name = record["html"]
    if Path(name).name != name:
        raise ValueError(f"expected a sibling comparison report: {evidence}")
    html = evidence.with_name(name)
    if sha256(html) != record["html_sha256"]:
        raise ValueError(f"HTML hash differs from sidecar: {html}")
    page = html.read_text(encoding="utf-8")
    if len(_BLOCK.findall(page)) != len(record["runs"]):
        raise ValueError(f"comparison run count differs from sidecar: {html}")
    changed = refresh_report_without_sidecar(html)
    record["html_sha256"] = sha256(html)
    record["html_bytes"] = html.stat().st_size
    staged = evidence.with_name(f".{evidence.name}.tmp-{os.getpid()}")
    try:
        staged.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged.replace(evidence)
    finally:
        staged.unlink(missing_ok=True)
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
    for path in sorted(args.root.rglob("*.json")):
        if json.loads(path.read_text(encoding="utf-8")).get("format") == "nodefusion.comparison-evidence/1":
            print(f"{path}: comparison refreshed={finalize_comparison(path)}")
    for html in sorted(args.root.rglob("*.html")):
        if refresh_report_without_sidecar(html):
            print(f"{html}: report interface refreshed")


if __name__ == "__main__":
    main()
