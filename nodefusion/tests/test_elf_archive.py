
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodefusion.host import kernels as K
from nodefusion.host.analyze import resolve_kernel_elf


CONTENT_A = b"\x7fELF-build-A" + b"A" * 100
CONTENT_B = b"\x7fELF-build-B" + b"B" * 100


@pytest.fixture()
def archive(tmp_path, monkeypatch):
    arc = tmp_path / "kernels"
    arc.mkdir()
    monkeypatch.setattr(K, "ARCHIVE", arc)
    monkeypatch.setattr(K, "BUILDS", arc / "builds")
    return arc


def _sha(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()



def test_renamed_file_is_still_found(archive):
    p = archive / "somebody-renamed-this.elf"
    p.write_bytes(CONTENT_A)
    got = K.archived_elf_for_identity({"sha256": _sha(CONTENT_A)}, "rcore")
    assert got == p


def test_name_matches_but_content_does_not_is_not_found(archive):
    want = _sha(CONTENT_A)
    (archive / f"rcore-{want[:8]}.elf").write_bytes(CONTENT_B)
    assert K.archived_elf_for_identity({"sha256": want}, "rcore") is None


def test_no_sha_means_no_guess(archive):
    (archive / "rcore-12345678.elf").write_bytes(CONTENT_A)
    assert K.archived_elf_for_identity(None, "rcore") is None
    assert K.archived_elf_for_identity({}, "rcore") is None
    assert K.archived_elf_for_identity({"size_bytes": 100}, "rcore") is None


def test_finds_build_in_subdir(archive):
    (archive / "builds").mkdir()
    p = archive / "builds" / "rcore-deadbeef.elf"
    p.write_bytes(CONTENT_B)
    assert K.archived_elf_for_identity({"sha256": _sha(CONTENT_B)}) == p



def test_first_build_goes_top_level_then_others_go_to_builds(archive):
    src_a, src_b = archive / "src_a", archive / "src_b"
    src_a.write_bytes(CONTENT_A)
    src_b.write_bytes(CONTENT_B)

    first = K.archive_build(src_a, "rcore")
    assert first is not None and first.parent == archive

    second = K.archive_build(src_b, "rcore")
    assert second is not None and second.parent == archive / "builds"

    assert len(list(archive.glob("rcore-*.elf"))) == 1


def test_archiving_twice_is_a_no_op(archive):
    src = archive / "src"
    src.write_bytes(CONTENT_A)
    first = K.archive_build(src, "rcore")
    again = K.archive_build(src, "rcore")
    assert first == again
    assert len(list(archive.rglob("*.elf"))) == 1


def test_archive_failure_returns_none_not_raise(archive):
    assert K.archive_build(archive / "does-not-exist", "rcore") is None



def test_archived_elf_ignores_builds_subdir(archive):
    (archive / "rcore-11111111.elf").write_bytes(CONTENT_A)
    (archive / "builds").mkdir()
    (archive / "builds" / "rcore-22222222.elf").write_bytes(CONTENT_B)
    assert K.archived_elf("rcore") == archive / "rcore-11111111.elf"


def test_archived_elf_still_refuses_two_at_top_level(archive):
    (archive / "rcore-11111111.elf").write_bytes(CONTENT_A)
    (archive / "rcore-22222222.elf").write_bytes(CONTENT_B)
    with pytest.raises(K.ProfileError) as e:
        K.archived_elf("rcore")
    assert "rcore-11111111.elf" in str(e.value)
    assert "rcore-22222222.elf" in str(e.value)



def _manifest(elf: Path, content: bytes | None) -> dict:
    m = {"kernel_elf": str(elf), "kernel_kind": "rcore"}
    if content is not None:
        m["kernel_elf_identity"] = {"sha256": _sha(content)}
    return m


def test_live_path_matching_identity_is_used_silently(archive, tmp_path):
    live = tmp_path / "os"
    live.write_bytes(CONTENT_A)
    path, note = resolve_kernel_elf(_manifest(live, CONTENT_A))
    assert path == live
    assert note is None


def test_overwritten_live_path_falls_back_to_archive_and_says_so(archive, tmp_path):
    live = tmp_path / "os"
    live.write_bytes(CONTENT_B)
    arc = archive / "rcore-old.elf"
    arc.write_bytes(CONTENT_A)

    path, note = resolve_kernel_elf(_manifest(live, CONTENT_A))
    assert path == arc
    assert note and "rcore-old.elf" in note
    assert "覆盖" in note


def test_missing_live_path_falls_back_to_archive(archive, tmp_path):
    live = tmp_path / "gone"
    arc = archive / "rcore-old.elf"
    arc.write_bytes(CONTENT_A)

    path, note = resolve_kernel_elf(_manifest(live, CONTENT_A))
    assert path == arc
    assert note and "没有这个文件" in note


def test_no_archive_copy_still_returns_live_path(archive, tmp_path):
    live = tmp_path / "os"
    live.write_bytes(CONTENT_B)
    path, note = resolve_kernel_elf(_manifest(live, CONTENT_A))
    assert path == live
    assert note is None


def test_old_run_without_identity_uses_live_path(archive, tmp_path):
    live = tmp_path / "os"
    live.write_bytes(CONTENT_B)
    (archive / "rcore-aaaaaaaa.elf").write_bytes(CONTENT_A)

    path, note = resolve_kernel_elf(_manifest(live, None))
    assert path == live
    assert note is None



_ROOT = Path(__file__).resolve().parents[2]


def test_every_locally_analyzable_run_resolves_to_something_readable():
    runs = sorted((_ROOT / "nodefusion" / "runs").glob("*/manifest.json"))
    if not runs:
        pytest.skip("这台机器上没有录制结果")

    unreadable = []
    for m in runs:
        if not (m.parent / "trace.nfb").is_file():
            continue
        man = json.loads(m.read_text(encoding="utf-8"))
        if "kernel_elf" not in man:
            continue
        path, _ = resolve_kernel_elf(man)
        if not Path(path).is_file():
            unreadable.append(f"{m.parent.name} -> {path}")

    assert not unreadable, "这些 run 指向的 ELF 不存在：\n  " + "\n  ".join(unreadable)
