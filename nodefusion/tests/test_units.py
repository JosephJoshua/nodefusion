import platform
import sys
from pathlib import Path

sys.path.insert(0, '.')

import pytest

from nodefusion.host import kernels as K


# --------------------------------------------------------------- rCore classify

def test_rcore_normal_exit_counts_as_completed_not_panic():
    real = ("[kernel] Hello\nTest write C OK!\n"
            "[kernel] Panicked at src/task/mod.rs:153 All applications completed!\n")
    assert K.by_kind('rcore').classify(real) == 'completed'


def test_rcore_real_panic_is_a_panic():
    assert K.by_kind('rcore').classify(
        "[kernel] Hello\n[kernel] Panicked at src/mm/heap.rs:20 out of memory\n"
    ) == 'panic'


@pytest.mark.parametrize("console, why", [
    ("[kernel] Hello\n", "有 boot 标记但没结束标记"),
    ("", "控制台整个是空的"),
    ("[kernel] everything fine\n", "正常文本里没有 panic 子串"),
])
def test_rcore_without_an_end_marker_is_qemu_exited(console, why):
    assert K.by_kind('rcore').classify(console) == 'qemu_exited', why


@pytest.mark.parametrize("console, booted", [
    ("[kernel] x", True),
    ("OpenSBI only", False),
])
def test_rcore_booted_needs_the_kernel_marker(console, booted):
    assert K.by_kind('rcore').booted(console) is booted


# ----------------------------------------------------------------- xv6 classify

def test_xv6_panic():
    assert K.by_kind('xv6').classify("hart 1 starting\npanic: acquire\n") == 'panic'


def test_xv6_without_markers_is_qemu_exited():
    assert K.by_kind('xv6').classify("$ ") == 'qemu_exited'


def test_xv6_booted_is_true_when_no_ready_markers_are_declared():
    assert K.by_kind('xv6').booted("$ ") is True



def test_by_kind_rejects_an_unknown_kernel():
    with pytest.raises(K.ProfileError):
        K.by_kind('linux')


def test_detect_raises_instead_of_guessing():
    with pytest.raises(K.ProfileError):
        K.detect(Path('/tmp'))


# ------------------------------------------------------------------ shell.path

def test_shell_does_not_rewrite_an_absolute_path():
    from nodefusion.host.shell import pick_shell
    assert pick_shell().path('/tmp/a b/c.txt') == '/tmp/a b/c.txt'


def test_plugin_filename_follows_the_platform():
    from nodefusion.host.shell import plugin_filename
    want = 'libnf.dylib' if platform.system() == 'Darwin' else 'libnf.so'
    assert plugin_filename() == want


def test_the_shell_module_still_exports_what_callers_import():
    from nodefusion.host.shell import LocalShell, default_qemu_prefix
    assert callable(default_qemu_prefix)
    assert isinstance(LocalShell, type)


# -------------------------------------------------------------------- cli._path

@pytest.mark.parametrize("given", ['/Users/x/y', '/Users/a b/c'])
def test_cli_path_keeps_absolute_paths_including_spaces(given):
    from nodefusion.host.cli import _path
    assert str(_path(given)) == given
