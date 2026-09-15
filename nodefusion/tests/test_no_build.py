
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.host.kernels import KernelProfile  # noqa: E402
from nodefusion.host.record import RecordError, Recorder  # noqa: E402


@dataclass
class _Cfg:
    kernel_dir: Path
    no_build: bool = True
    lab_stage: object = None
    make_vars: dict = field(default_factory=dict)


def _Profile() -> KernelProfile:
    return KernelProfile(
        kind="fake", kernel_elf="kernel.elf", kernel_image="kernel.bin",
        build="make", detect_files=(), required_tools=(), machine_opts=(),
        interactive=False)


def _recorder(root: Path, elf: Path | None = None) -> Recorder:
    r = object.__new__(Recorder)
    r.cfg, r.sh, r.profile, r.warnings = _Cfg(root), None, _Profile(), []
    return r


def _tree(root: Path, *, elf=True, image=True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    e = root / "kernel.elf"
    if elf:
        e.write_bytes(b"\x7fELF" + b"\0" * 64)
    if image:
        (root / "kernel.bin").write_bytes(b"\0" * 16)
    return e


def test_it_records_without_building(tmp_path):
    r = _recorder(tmp_path, _tree(tmp_path))
    out = r.build_kernel()
    assert "跳过构建" in out


def test_it_says_out_loud_that_nothing_was_built(tmp_path):
    r = _recorder(tmp_path, _tree(tmp_path))
    r.build_kernel()
    assert len(r.warnings) == 1
    w = r.warnings[0]
    assert "--no-build" in w
    assert "kernel.elf" in w
    assert "UTC" in w
    assert "没人验证过" in w


def test_a_missing_elf_is_fatal(tmp_path):
    _tree(tmp_path, elf=False)
    r = _recorder(tmp_path, tmp_path / "kernel.elf")
    with pytest.raises(RecordError, match=r"--no-build 要求产物已经在了"):
        r.build_kernel()


def test_a_missing_image_is_fatal_too(tmp_path):
    r = _recorder(tmp_path, _tree(tmp_path, image=False))
    with pytest.raises(RecordError, match=r"kernel\.bin"):
        r.build_kernel()


def test_the_error_says_how_to_get_unstuck(tmp_path):
    _tree(tmp_path, elf=False, image=False)
    r = _recorder(tmp_path, tmp_path / "kernel.elf")
    with pytest.raises(RecordError) as e:
        r.build_kernel()
    assert "去掉 --no-build" in str(e.value)


def test_the_flag_reaches_the_config_from_the_command_line():
    from nodefusion.host import cli
    p = cli.build_parser() if hasattr(cli, "build_parser") else None
    if p is None:
        pytest.skip("cli 没有导出 parser")
    base = ["record", "--program", "x", "--kernel", "/nonexistent"]
    a = p.parse_args(base + ["--no-build"])
    assert a.no_build is True
    assert p.parse_args(base).no_build is False
