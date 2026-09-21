from pathlib import Path
from types import SimpleNamespace

from nodefusion.host.record import Recorder, RunConfig


def _command(cpus):
    recorder = Recorder.__new__(Recorder)
    recorder.cfg = RunConfig(Path("/kernel"), "program", "test", Path("/runs"),
                             cpus=cpus)
    recorder.sh = SimpleNamespace(path=str)
    recorder.plugin_so = Path("/plugin/libnf.so")
    recorder.profile = SimpleNamespace(
        ram_bytes=lambda: (128 * 1048576, ""),
        event_snapshot_min_insns=0,
        machine_args=lambda kernel_dir: ["-M virt"])
    recorder.warnings = []
    return recorder._qemu_cmd(Path("/runs/trace.nfb"), None, 1000, 12345)


def test_single_vcpu_keeps_deterministic_icount():
    assert "-icount shift=3" in _command(1)


def test_smp_omits_incompatible_icount():
    command = _command(2)
    assert "-smp 2" in command
    assert "-icount" not in command
