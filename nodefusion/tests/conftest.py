
from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from nodefusion.host import analyze as A

RUNS = Path(__file__).resolve().parents[1] / "runs"

# Local recordings are ignored artifacts, so a new showcase can silently turn
# an ordinary test run into an hour-long, multi-gigabyte corpus scan.  Keep
# discovery bounded by default; exhaustive validation remains available by
# setting NF_CORPUS_MAX_TRACE_MIB=0 (normally on the archive server).
DEFAULT_CORPUS_MAX_TRACE_MIB = 256


def pytest_addoption(parser):
    parser.addoption(
        "--run-corpus", action="store_true", default=False,
        help="run exhaustive tests over ignored nodefusion/runs recordings")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "corpus: exhaustive checks over local ignored recordings")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-corpus"):
        return
    skip = pytest.mark.skip(reason="exhaustive local corpus test; pass --run-corpus")
    for item in items:
        if "corpus" in item.keywords:
            item.add_marker(skip)


def corpus_run_dirs(root: Path = RUNS) -> list[Path]:
    """Return trace-bearing corpus directories within the configured size cap."""
    if not root.is_dir():
        return []
    raw = os.environ.get("NF_CORPUS_MAX_TRACE_MIB",
                         str(DEFAULT_CORPUS_MAX_TRACE_MIB))
    try:
        max_mib = int(raw)
    except ValueError as exc:
        raise pytest.UsageError(
            f"NF_CORPUS_MAX_TRACE_MIB must be an integer, got {raw!r}") from exc
    limit = max_mib * 1024 * 1024 if max_mib > 0 else None
    out = []
    for d in sorted(root.iterdir()):
        trace = d / "trace.nfb"
        if d.is_dir() and trace.is_file() and (limit is None or trace.stat().st_size <= limit):
            out.append(d)
    return out

_CACHE_DIR = Path(__file__).resolve().parent / ".shape-cache"
_CACHE_OFF = os.environ.get("NF_SHAPE_CACHE") == "off"


@lru_cache(maxsize=1)
def _code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for sub in ("model", "host"):
        for p in sorted((root / sub).rglob("*.py")):
            st = p.stat()
            h.update(f"{p.relative_to(root)}|{st.st_size}|{st.st_mtime_ns}\n"
                     .encode())
    for p in sorted((root / "manifests").glob("*.toml")):
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def _run_key(d: Path) -> str:
    h = hashlib.sha256()
    h.update(_code_fingerprint().encode())
    for p in sorted(d.iterdir()):
        if p.is_file():
            st = p.stat()
            h.update(f"{p.name}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    try:
        ident = json.loads((d / "manifest.json").read_text()
                           ).get("kernel_elf_identity") or {}
    except (OSError, ValueError):
        ident = {}
    h.update(str(ident.get("sha256")).encode())
    return h.hexdigest()[:16]


class Shapes(NamedTuple):
    name: str
    metrics: dict
    kevents: dict
    kind_counts: Counter
    switches: list
    tasks_exhaustive: Any
    notes: list
    sched_ctxs: tuple
    watched_kinds: frozenset
    watched_symbols: frozenset
    funcs_by_kind: dict
    kinds_seq: tuple


@lru_cache(maxsize=None)
def shapes(name: str) -> Shapes:
    d = RUNS / name
    if not (d / "trace.nfb").is_file():
        pytest.skip(f"这台机器上没有 {name}")

    hit = _load_cached(name, d)
    if hit is not None:
        return hit
    sh = _compute(name, d)
    _store_cached(name, d, sh)
    return sh


def _load_cached(name: str, d: Path) -> Shapes | None:
    if _CACHE_OFF:
        return None
    f = _CACHE_DIR / f"{name}.{_run_key(d)}.pkl.gz"
    try:
        got = pickle.loads(gzip.decompress(f.read_bytes()))
    except (OSError, ValueError, EOFError, pickle.UnpicklingError,
            AttributeError, ImportError):
        return None
    return got if isinstance(got, Shapes) and got.name == name else None


def _store_cached(name: str, d: Path, sh: Shapes) -> None:
    if _CACHE_OFF:
        return
    key = _run_key(d)
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        for old in _CACHE_DIR.glob(f"{name}.*.pkl.gz"):
            if old.name != f"{name}.{key}.pkl.gz":
                old.unlink(missing_ok=True)
        tmp = _CACHE_DIR / f"{name}.{key}.pkl.gz.tmp{os.getpid()}"
        tmp.write_bytes(gzip.compress(pickle.dumps(sh, protocol=5), 1))
        tmp.replace(_CACHE_DIR / f"{name}.{key}.pkl.gz")
    except OSError:
        pass


def _compute(name: str, d: Path) -> Shapes:
    a = A.analyze(d)
    return Shapes(
        name=name,
        metrics=a.metrics(),
        kevents=dict(a.kevents or {}),
        kind_counts=Counter(e.kind for e in a.events),
        switches=[e for e in a.events if e.kind == A.SWITCH_EVENT],
        tasks_exhaustive=a.tasks_exhaustive,
        notes=list(a.notes),
        sched_ctxs=tuple(p.sched_ctx for s in a.states for p in s.procs),
        watched_kinds=frozenset(a._watched_kinds()),
        watched_symbols=frozenset(a.watched_symbols or ()),
        funcs_by_kind=_funcs_by_kind(a),
        kinds_seq=tuple(e.kind for e in a.events),
    )


def _funcs_by_kind(a) -> dict:
    out: dict[str, set] = {}
    for e in a.events:
        out.setdefault(e.kind, set()).add(e.func)
    return {k: frozenset(v) for k, v in out.items()}
