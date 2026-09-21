from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from nodefusion.model.manifest import (
    _DETECT_KEYS,
    _ENTITY_COLUMN_KEYS,
    _ENTITY_KEYS,
    _FIELD_KEYS,
    _KERNEL_KEYS,
    _PROFILE_KEYS,
    _SOURCE_KEYS,
    _TABLE_KEYS,
    _WATCH_KEYS,
    _WATCH_MATCH_KEYS,
)
from nodefusion.model.plan import _STEPS
from nodefusion.model.readers.registry import known_names


ROOT = Path(__file__).resolve().parents[2]
DOCS = (
    ROOT / "docs" / "manifests" / "AUTHORING.md",
    ROOT / "docs" / "manifests" / "REFERENCE.md",
)


@pytest.mark.parametrize("path", DOCS, ids=lambda path: path.name)
def test_manifest_documentation_toml_examples_parse(path: Path):
    blocks = re.findall(r"```toml\n(.*?)```", path.read_text(encoding="utf-8"), re.S)
    assert blocks, f"{path} 没有 TOML 示例"
    for index, block in enumerate(blocks, 1):
        try:
            tomllib.loads(block)
        except tomllib.TOMLDecodeError as error:
            pytest.fail(f"{path.name} 的第 {index} 个 TOML 示例无法解析：{error}")


def test_reference_mentions_every_manifest_key_and_source_step():
    text = DOCS[1].read_text(encoding="utf-8")
    groups = (
        _KERNEL_KEYS,
        _DETECT_KEYS,
        _ENTITY_KEYS,
        _SOURCE_KEYS,
        _FIELD_KEYS,
        _TABLE_KEYS,
        _ENTITY_COLUMN_KEYS,
        _WATCH_KEYS,
        _WATCH_MATCH_KEYS,
        _PROFILE_KEYS,
        _STEPS,
    )
    missing = sorted(
        name for group in groups for name in group
        if f"`{name}`" not in text and f" {name} " not in text
    )
    assert not missing, f"REFERENCE.md 没有提到这些 manifest 名称：{missing}"


def test_reference_mentions_every_registered_reader():
    text = DOCS[1].read_text(encoding="utf-8")
    missing = [name for name in known_names() if name not in text]
    assert not missing, f"REFERENCE.md 没有提到这些 reader：{missing}"


def test_authoring_guide_contains_the_full_validation_path():
    text = DOCS[0].read_text(encoding="utf-8")
    required = (
        "crosscheck_dwarf",
        "crosscheck_watchsel",
        "git apply --check",
        "--run-corpus",
        "NF_CORPUS_MAX_TRACE_MIB=0",
        "--event-stream always",
        "audit",
        "coverage.json",
        "trace.nfb",
        "manifest.json",
        "HTML",
        "SHA-256",
    )
    missing = [term for term in required if term not in text]
    assert not missing, f"AUTHORING.md 缺少这些验证步骤：{missing}"
