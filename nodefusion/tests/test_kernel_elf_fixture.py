
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import kernels as K
from nodefusion.tests import kernelelf as ke


@pytest.fixture()
def archive(tmp_path, monkeypatch):
    arc = tmp_path / "kernels"
    arc.mkdir()
    monkeypatch.setattr(K, "ARCHIVE", arc)
    monkeypatch.setattr(K, "BUILDS", arc / "builds")
    return arc


def test_the_archive_wins_over_the_build_path(archive, tmp_path, monkeypatch):
    live = tmp_path / "os"
    live.write_bytes(b"live build")
    arc = archive / "rcore-11111111.elf"
    arc.write_bytes(b"archived build")
    monkeypatch.setitem(ke.LIVE, "rcore", live)

    assert ke.kernel_elf("rcore") == arc


def test_the_build_path_is_the_fallback(archive, tmp_path, monkeypatch):
    live = tmp_path / "os"
    live.write_bytes(b"live build")
    monkeypatch.setitem(ke.LIVE, "rcore", live)

    assert ke.kernel_elf("rcore") == live


def test_neither_gives_none_not_an_exception(archive, tmp_path, monkeypatch):
    monkeypatch.setitem(ke.LIVE, "rcore", tmp_path / "nope")
    assert ke.kernel_elf("rcore") is None


def test_an_ambiguous_archive_does_not_guess(archive, tmp_path, monkeypatch):
    (archive / "rcore-11111111.elf").write_bytes(b"a")
    (archive / "rcore-22222222.elf").write_bytes(b"b")
    live = tmp_path / "os"
    live.write_bytes(b"live")
    monkeypatch.setitem(ke.LIVE, "rcore", live)

    assert ke.kernel_elf("rcore") == live


def test_builds_subdir_does_not_become_the_representative(archive, tmp_path,
                                                          monkeypatch):
    arc = archive / "rcore-11111111.elf"
    arc.write_bytes(b"representative")
    (archive / "builds").mkdir()
    for i in range(3):
        (archive / "builds" / f"rcore-2222222{i}.elf").write_bytes(bytes([i]))
    monkeypatch.setitem(ke.LIVE, "rcore", tmp_path / "nope")

    assert ke.kernel_elf("rcore") == arc



_TESTS = Path(__file__).resolve().parent


def test_no_test_hardcodes_the_kernel_build_path():
    needle = "riscv64gc-unknown-none-elf/release/" + "os" + '"'
    offenders = []
    for f in sorted(_TESTS.glob("test_*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if needle in line:
                offenders.append(f"{f.name}:{i}: {line.strip()}")

    assert not offenders, (
        "这些地方写死了构建产物的路径，改用 kernelelf.elf_or_skip：\n  "
        + "\n  ".join(offenders))
