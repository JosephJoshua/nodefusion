"""Offline source and symbol metadata for recorded instruction addresses."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import zlib
from pathlib import Path, PureWindowsPath

from ..model.symbols import display_name, display_dwarf_name


def llvm_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/opt/homebrew/opt/llvm/bin", "/usr/local/opt/llvm/bin"):
        path = Path(prefix) / name
        if path.is_file():
            return str(path)
    return None


def full_names(symbols: list[str]) -> list[str]:
    tool = llvm_tool("llvm-cxxfilt")
    if tool and symbols:
        try:
            result = subprocess.run([tool, "--no-strip-underscore"],
                                    input="\n".join(symbols) + "\n", text=True,
                                    capture_output=True, check=True, timeout=60)
            names = result.stdout.splitlines()
            if len(names) == len(symbols):
                return [re.sub(r"::h[0-9a-f]{16}$", "", name) if raw.startswith(("_ZN", "_R")) and name != raw
                        else name if name != raw else display_name(raw)
                        for raw, name in zip(symbols, names)]
        except (OSError, subprocess.SubprocessError):
            pass
    return [display_name(raw) for raw in symbols]


def resolve_file(filename: str, roots: list[Path], maps: list[tuple[str, str]]) -> Path | None:
    if not roots:
        return None
    candidate = Path(filename)
    for old, new in maps:
        try:
            if PureWindowsPath(filename).drive:
                relative = PureWindowsPath(filename).relative_to(PureWindowsPath(old))
                candidate = Path(new).joinpath(*relative.parts)
            else:
                candidate = Path(new) / candidate.relative_to(old)
            break
        except ValueError:
            continue
    choices = [candidate] if candidate.is_absolute() else [r / candidate for r in roots]
    for choice in choices:
        resolved = choice.resolve()
        if any(resolved.is_relative_to(root) for root in roots) and resolved.is_file():
            return resolved
    return None


def load_snapshot(manifest: dict, run_dir: Path) -> dict | None:
    record = manifest.get('source_snapshot')
    if not record:
        return None
    root = Path(run_dir).resolve()
    path = (root / record['path']).resolve()
    if path.parent != root:
        raise ValueError('source snapshot must be inside the run directory')
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != record['sha256']:
        raise ValueError('source snapshot hash mismatch')
    return json.loads(zlib.decompress(payload))


def capture_snapshot(elf: Path, destination: Path, roots, maps=()) -> dict:
    """Archive DWARF-referenced source before starting the guest."""
    from ..model.dwarfsrc import DwarfSource, ELFFile
    roots = [Path(root).resolve() for root in roots]
    files = {}
    omitted = {}
    used = 0
    with Path(elf).open("rb") as handle:
        binary = ELFFile(handle)
        if binary.has_dwarf_info():
            dw = binary.get_dwarf_info()
            for cu in dw.iter_CUs():
                directory = cu.get_top_DIE().attributes.get("DW_AT_comp_dir")
                comp_dir = directory.value.decode("utf-8", "replace") if directory and isinstance(directory.value, bytes) else ""
                for filename in DwarfSource._file_table(dw, cu):
                    if filename and not Path(filename).is_absolute() and comp_dir:
                        filename = str(Path(comp_dir) / filename)
                    if not filename or filename in files:
                        continue
                    path = resolve_file(filename, roots, maps)
                    if path is None:
                        continue
                    size = path.stat().st_size
                    if size > 4 * 1024 * 1024 or used + size > 32 * 1024 * 1024:
                        omitted[filename] = "size_limit"
                        continue
                    try:
                        content = path.read_bytes()
                        text = content.decode("utf-8")
                    except (OSError, UnicodeError):
                        omitted[filename] = "read_error"
                        continue
                    used += len(content)
                    files[filename] = {"path": next(path.relative_to(r).as_posix() for r in roots if path.is_relative_to(r)),
                                       "text": text, "sha256": hashlib.sha256(content).hexdigest()}
                cu._dielist.clear()
                cu._diemap.clear()
                dw._linetable_cache.clear()
    payload = zlib.compress(json.dumps({"files": files, "omitted": omitted}, ensure_ascii=False).encode(), 9)
    destination.write_bytes(payload)
    return {"path": destination.name, "sha256": hashlib.sha256(payload).hexdigest(),
            "files": len(files), "bytes": used, "omitted": len(omitted), "captured": "before_qemu"}


def build_source(elf: Path | None, addresses, *, roots=(), maps=(), snapshot=None) -> dict:
    """Read only explicitly allowed roots; bundle each UTF-8 file once."""
    out = {"files": [], "locations": {}, "status": "no_debug_info",
           "snapshot": "render", "limits": {"file_bytes": 4 * 1024 * 1024,
                                                "total_bytes": 32 * 1024 * 1024}}
    tool = llvm_tool("llvm-symbolizer")
    if not tool:
        out["status"] = "symbolizer_missing"
        return out
    if elf is None or not Path(elf).is_file():
        return out
    roots = [Path(root).resolve() for root in roots]
    archived_files = {}
    if snapshot:
        archived_files = snapshot.get("files", {})
        out["snapshot"] = "record"
    unique = sorted({int(pc) for pc in addresses if pc})
    files = {}
    resolved_paths = {}
    omitted = {}
    used = 0
    for start in range(0, len(unique), 4096):
        chunk = unique[start:start + 4096]
        try:
            result = subprocess.run(
                [tool, "--obj=" + str(elf), "--output-style=JSON", "--inlines", "--demangle"],
                input="\n".join(hex(pc) for pc in chunk) + "\n", text=True,
                capture_output=True, check=True, timeout=120)
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            if len(rows) != len(chunk):
                raise ValueError("symbolizer response count")
        except (OSError, ValueError, subprocess.SubprocessError):
            out["status"] = "symbolizer_failed"
            return out
        for pc, row in zip(chunk, rows):
            frames = []
            for symbol in row.get("Symbol", []):
                filename = symbol.get("FileName", "")
                line = symbol.get("Line", 0)
                if not filename or not line:
                    continue
                file_id = None
                file_status = (snapshot or {}).get("omitted", {}).get(filename, "not_provided")
                archived = archived_files.get(filename)
                if not archived and filename not in resolved_paths:
                    resolved_paths[filename] = resolve_file(filename, roots, maps)
                path = resolved_paths.get(filename) if not archived else None
                if archived:
                    if filename not in files:
                        files[filename] = len(out["files"])
                        out["files"].append(archived)
                    file_id = files[filename]
                elif path:
                    key = str(path)
                    if key not in files:
                        size = path.stat().st_size
                        if size > out["limits"]["file_bytes"] or used + size > out["limits"]["total_bytes"]:
                            files[key] = None
                            omitted[key] = "size_limit"
                        else:
                            try:
                                content = path.read_bytes()
                                text = content.decode("utf-8")
                            except (OSError, UnicodeError):
                                files[key] = None
                                omitted[key] = "read_error"
                            else:
                                used += len(content)
                                files[key] = len(out["files"])
                                relative = next(path.relative_to(r).as_posix() for r in roots
                                                if path.is_relative_to(r))
                                out["files"].append({"path": relative, "text": text,
                                                     "sha256": hashlib.sha256(content).hexdigest()})
                    file_id = files[key]
                    file_status = omitted.get(key, file_status)
                function = symbol.get("FunctionName", "")
                if filename.endswith(".rs"):
                    function = display_dwarf_name(function)
                frames.append({"file": file_id, "path": filename, "line": line,
                               "file_status": "embedded" if file_id is not None else file_status,
                               "column": symbol.get("Column", 0),
                               "function": function})
            if frames:
                out["locations"][hex(pc)] = frames
    out["status"] = "ready" if out["locations"] else "no_debug_info"
    return out
