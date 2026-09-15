
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodefusion.host.kernels import KernelProfile
from nodefusion.host.record import ArtifactGuard, RecordError, Recorder


def _mk(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_a_deleted_file_comes_back(tmp_path):
    fs = _mk(tmp_path / "fs.img", "原始镜像")
    with ArtifactGuard([fs]) as g:
        fs.unlink()
        assert not fs.exists()
        assert g.restore() == [fs]
    assert fs.read_text(encoding="utf-8") == "原始镜像"


def test_an_overwritten_file_comes_back(tmp_path):
    kern = _mk(tmp_path / "kernel", "好内核")
    with ArtifactGuard([kern]) as g:
        kern.write_text("写了一半的坏内核", encoding="utf-8")
        g.restore()
    assert kern.read_text(encoding="utf-8") == "好内核"


def test_a_file_that_did_not_exist_is_not_conjured(tmp_path):
    missing = tmp_path / "fs.img"
    with ArtifactGuard([missing]) as g:
        assert not g.had(missing)
        assert g.restore() == []
    assert not missing.exists()


def test_had_distinguishes_the_two_kinds_of_absent(tmp_path):
    present = _mk(tmp_path / "fs.img", "x")
    absent = tmp_path / "other.img"
    with ArtifactGuard([present, absent]) as g:
        assert g.had(present) and not g.had(absent)


def test_the_backup_directory_does_not_outlive_the_block(tmp_path):
    fs = _mk(tmp_path / "fs.img", "x")
    with ArtifactGuard([fs]) as g:
        held = g._dir
        assert held and held.is_dir()
    assert not held.exists()


def test_same_name_in_different_directories_do_not_collide(tmp_path):
    a = _mk(tmp_path / "a" / "kernel", "A")
    b = _mk(tmp_path / "b" / "kernel", "B")
    with ArtifactGuard([a, b]) as g:
        a.unlink(); b.unlink()
        g.restore()
    assert a.read_text(encoding="utf-8") == "A"
    assert b.read_text(encoding="utf-8") == "B"


def test_the_same_path_twice_is_backed_up_once(tmp_path):
    k = _mk(tmp_path / "kernel", "K")
    with ArtifactGuard([k, k]) as g:
        assert len(g._saved) == 1
        k.unlink()
        assert g.restore() == [k]
    assert k.read_text(encoding="utf-8") == "K"


def test_directories_are_ignored(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    with ArtifactGuard([d]) as g:
        assert not g.had(d)
        assert g.restore() == []
    assert d.is_dir()


def test_restore_reports_only_what_actually_came_back(tmp_path):
    fs = _mk(tmp_path / "sub" / "fs.img", "x")
    with ArtifactGuard([fs]) as g:
        shutil.rmtree(tmp_path / "sub")
        back = g.restore()
    assert back == [fs] and fs.exists()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

@dataclass
class _FakeResult:
    returncode: int
    stdout: str = ""


class _FakeShell:

    def __init__(self, root, clean_deletes=(), builds=(), rc=0):
        self.root, self.clean_deletes = root, list(clean_deletes)
        self.builds, self.rc = list(builds), rc

    def path(self, p):
        return str(p)

    def run(self, script, *, check=True, **kw):
        for rel in self.clean_deletes:                    # make clean
            (self.root / rel).unlink(missing_ok=True)
        for rel in self.builds:
            f = self.root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("新产物", encoding="utf-8")
        return _FakeResult(self.rc, "假构建输出")


def _FakeProfile(**kw) -> KernelProfile:
    return KernelProfile(**{
        "kind": "fake", "kernel_elf": "kernel/kernel",
        "kernel_image": "kernel/kernel", "build": "make {mv}",
        "detect_files": (), "required_tools": (), "machine_opts": (),
        "interactive": False, "protect": ("fs.img",), **kw})


@dataclass
class _FakeCfg:
    kernel_dir: Path
    lab_stage: object = None
    make_vars: dict = field(default_factory=dict)
    no_build: bool = False


def _recorder(root, shell, profile=None):
    r = object.__new__(Recorder)
    r.cfg, r.sh, r.profile, r.warnings = _FakeCfg(root), shell, profile or _FakeProfile(), []
    return r


def _xv6_tree(root):
    _mk(root / "kernel" / "kernel", "旧内核")
    _mk(root / "fs.img", "旧镜像")
    return root


def test_a_failed_build_leaves_fs_img_where_it_found_it(tmp_path):
    root = _xv6_tree(tmp_path)
    sh = _FakeShell(root, clean_deletes=["kernel/kernel", "fs.img"],
                    builds=["kernel/kernel"], rc=2)
    with pytest.raises(RecordError) as e:
        _recorder(root, sh).build_kernel()
    assert "构建把它删掉了又没建回来" in str(e.value)
    assert (root / "fs.img").read_text(encoding="utf-8") == "旧镜像"


def test_it_says_the_tree_was_put_back(tmp_path):
    root = _xv6_tree(tmp_path)
    sh = _FakeShell(root, clean_deletes=["kernel/kernel", "fs.img"], rc=2)
    with pytest.raises(RecordError) as e:
        _recorder(root, sh).build_kernel()
    assert "已放回原处" in str(e.value) and "fs.img" in str(e.value)
    assert (root / "kernel" / "kernel").read_text(encoding="utf-8") == "旧内核"


def test_a_missing_fs_image_that_was_never_there_is_not_an_error(tmp_path):
    root = tmp_path
    _mk(root / "kernel" / "kernel", "旧内核")
    sh = _FakeShell(root, clean_deletes=["kernel/kernel"],
                    builds=["kernel/kernel"], rc=0)
    _recorder(root, sh).build_kernel()
    assert not (root / "fs.img").exists()


def test_a_successful_build_keeps_the_new_artifacts(tmp_path):
    root = _xv6_tree(tmp_path)
    sh = _FakeShell(root, clean_deletes=["kernel/kernel", "fs.img"],
                    builds=["kernel/kernel", "fs.img"], rc=0)
    _recorder(root, sh).build_kernel()
    assert (root / "kernel" / "kernel").read_text(encoding="utf-8") == "新产物"
    assert (root / "fs.img").read_text(encoding="utf-8") == "新产物"


def test_a_destroyed_fs_image_is_fatal_not_a_warning(tmp_path):
    root = _xv6_tree(tmp_path)
    sh = _FakeShell(root, clean_deletes=["kernel/kernel", "fs.img"],
                    builds=["kernel/kernel"], rc=0)
    rec = _recorder(root, sh)
    with pytest.raises(RecordError):
        rec.build_kernel()
    assert (root / "fs.img").exists()



#           inode.alloc = 0
#           inode.alloc = 1


def _calib_recorder(root, tmp_path, on_drive):
    r = _recorder(root, None)
    r.run_dir = tmp_path / "run"
    r.run_dir.mkdir(parents=True, exist_ok=True)
    r._drive = on_drive
    return r


def test_calibration_puts_the_disk_image_back(tmp_path):
    root = tmp_path / "tree"
    _mk(root / "fs.img", "干净镜像")

    def drive(*a, **kw):
        (root / "fs.img").write_text("被 guest 改过", encoding="utf-8")
        return ("completed", "", None)

    r = _calib_recorder(root, tmp_path, drive)
    with pytest.raises(RecordError):
        r._calibrate(None, {"entries": []})

    assert (root / "fs.img").read_text(encoding="utf-8") == "干净镜像", (
        "校准跑改过的盘没放回去 —— 追踪跑会从一个不同的初态启动，"
        "'两次跑的指令序列一致'这个前提就不成立了")


def test_the_disk_is_put_back_even_when_calibration_fails(tmp_path):
    root = tmp_path / "tree"
    _mk(root / "fs.img", "干净镜像")

    def drive(*a, **kw):
        (root / "fs.img").write_text("超时前写了一半", encoding="utf-8")
        return ("timeout", "", None)

    r = _calib_recorder(root, tmp_path, drive)
    with pytest.raises(RecordError):
        r._calibrate(None, {"entries": []})

    assert (root / "fs.img").read_text(encoding="utf-8") == "干净镜像"


def test_calibration_finds_manifest_proc_exec_kind(tmp_path, monkeypatch):
    """Manifest watches name the function; ``kind`` is the stable contract."""
    root = tmp_path / "tree"
    _mk(root / "fs.img", "干净镜像")

    def drive(trace_path, *a, **kw):
        trace_path.write_bytes(b"fake trace")
        return ("completed", "", None)

    r = _calib_recorder(root, tmp_path, drive)
    fake = SimpleNamespace(
        total_insns=900,
        watch_hits=[SimpleNamespace(watch_id=11, insn=123),
                    SimpleNamespace(watch_id=11, insn=789)],
    )
    monkeypatch.setattr("nodefusion.host.nftrace.load", lambda *a, **kw: fake)

    total, start = r._calibrate(None, {
        "entries": [{"index": 11, "name": "load_user_app", "kind": "proc.exec"}],
    })

    assert (total, start) == (900, 789)





def test_the_shell_heap_panic_note_is_written_when_it_happened(tmp_path):
    r = _recorder(tmp_path, None)
    r._note_shell_heap_panic(
        "file_test passed!\n>> \nPanicked at src/lib.rs, Heap allocation error\n")
    assert len(r.warnings) == 1 and "Heap allocation error" in r.warnings[0]


def test_no_note_when_the_console_never_panicked(tmp_path):
    r = _recorder(tmp_path, None)
    r._note_shell_heap_panic("file_test passed!\n>> \n")
    assert r.warnings == [], (
        "控制台里没有这条 panic 却写了注解 —— 读 manifest 的人会去控制台里"
        "找它，找不到，然后怀疑拿错了 run")
