
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                # noqa: E402

from nodefusion.model import manifest as M                   # noqa: E402
from nodefusion.model.plan import _STEP_ARGS, _STEPS        # noqa: E402
from nodefusion.model.readers.registry import (              # noqa: E402
    known_names, outer_name)

DRAFTS = Path(__file__).resolve().parents[1] / "manifests"


_ARGS_THAT_NAME_READERS = ("key",)

#:     `pub type StrongMap<K, V> = alloc::collections::btree_map::BTreeMap<K, V>;`
EXPECTED_MISSING: dict[str, set[str]] = {}


def _manifests() -> list[Path]:
    return sorted(DRAFTS.glob("*.toml"))


def _shells(step: dict) -> list[str]:
    out = list(step.get("unwrap") or [])
    out += list(step.get("via") or [])
    walk = step.get("walk")
    if isinstance(walk, dict):
        out += list(walk.get("via") or [])
    return [s for s in out if isinstance(s, str)]


_FIELD_NAME_ARG = re.compile(r"\b(field|variant|astype)\s*<\s*[^,<>]+,")


def _reader_heads(spec) -> list[str]:
    out = []
    for part in re.split(r"[<>,]", _FIELD_NAME_ARG.sub(r"\1<", spec.reader or "")):
        part = part.strip()
        if part:
            out.append(outer_name(part).lower())
    return out


class _FakeSpec:

    def __init__(self, reader: str) -> None:
        self.reader = reader


def _names_used(m: M.Manifest) -> tuple[set[str], set[str]]:
    words: set[str] = set()
    steps: set[str] = set()
    for e in m.entities:
        for grp in (e.fields, e.relations):
            for f in grp:
                words.update(_reader_heads(f))
        srcs = list(e.sources)
        for s in e.sources:
            for n in s.nested:
                srcs.append(M.SourceSpec(kind="", completeness="",
                                         steps=list(n.get("steps") or [])))
        for s in srcs:
            for st in s.steps:
                steps.update(k for k in st if k not in _STEP_ARGS)
                words.update(outer_name(x).lower() for x in _shells(st))
                for a in _ARGS_THAT_NAME_READERS:
                    v = st.get(a)
                    if isinstance(v, str) and v.strip():
                        words.update(_reader_heads(_FakeSpec(v)))
    return words, steps


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.name)
def test_every_draft_manifest_loads(path):
    m = M.load(path)
    assert m.entities, f"{path.name} 里一个实体都没有"


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.name)
def test_step_names_are_all_known(path):
    _, steps = _names_used(M.load(path))
    unknown = steps - set(_STEPS)
    assert not unknown, (
        f"{path.name} 用了引擎不认识的步骤 {sorted(unknown)}；"
        f"认识的有 {sorted(_STEPS)}")


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.name)
def test_reader_and_shell_names_match_the_known_todo_list(path):
    words, _ = _names_used(M.load(path))
    missing = {w for w in words if w not in set(known_names())}
    expected = EXPECTED_MISSING.get(path.name, set())

    surprises = missing - expected
    assert not surprises, (
        f"{path.name} 用了没记录过的名字 {sorted(surprises)}。多半是手误 —— "
        f"真要新加一个 reader，先实现它，或者把它写进 EXPECTED_MISSING 并"
        f"在对应 manifest 注释中说明为什么现在做不了")

    done = expected - missing
    assert not done, (
        f"{sorted(done)} 已经实现了，但还挂在 {path.name} 的待办里。"
        f"把它从 EXPECTED_MISSING 划掉 —— 过期的待办清单比没有更糟")


def test_the_two_verified_kernels_need_nothing_that_is_missing():
    for name in ("xv6.toml", "rcore.toml"):
        assert name not in EXPECTED_MISSING, f"{name} 不该有待办"
        words, _ = _names_used(M.load(DRAFTS / name))
        unknown = {w for w in words if w not in set(known_names())}
        assert not unknown, f"{name} 用了认不出来的名字 {sorted(unknown)}"
