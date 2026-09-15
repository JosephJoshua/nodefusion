
from __future__ import annotations

from nodefusion.host.record import Recorder

_LOCKED = """\
[nodefusion-plugin] 已挂载：out=/x/calibration.nfb sample=200000 snap=0 watches=140
qemu-system-riscv64: -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0: \
Failed to get "write" lock
Is another process using the image [user/target/riscv64gc-unknown-none-elf/release/fs.img]?
[nodefusion-plugin] 结束：指令 0，快照 0 次，采样 0 次，watch 命中 0 次
"""

_SOME_OTHER_FAILURE = """\
qemu-system-riscv64: 某个还没见过的毛病
"""


def _reason(tmp_path, text: str | None):
    p = tmp_path / "calibration.qemu.log"
    if text is not None:
        p.write_text(text)
    return Recorder._calibration_failure_reason(p)


def test_write_lock_is_named_instead_of_blamed_on_the_plugin(tmp_path):
    msg = _reason(tmp_path, _LOCKED)
    assert "写锁" in msg
    assert "pgrep -f qemu-system-riscv64" in msg, "得给一条能直接跑的排查命令"


def test_the_plugin_is_not_accused_when_the_log_says_it_loaded(tmp_path):
    msg = _reason(tmp_path, _LOCKED)
    assert "--enable-plugins" not in msg, (
        "stderr 里明明有'已挂载'，还让人去查 --enable-plugins")


def test_an_unrecognised_failure_shows_qemu_own_words(tmp_path):
    msg = _reason(tmp_path, _SOME_OTHER_FAILURE)
    assert "某个还没见过的毛病" in msg


def test_a_missing_log_does_not_raise(tmp_path):
    msg = _reason(tmp_path, None)
    assert "读不到" in msg
