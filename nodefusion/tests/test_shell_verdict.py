
from __future__ import annotations

from dataclasses import replace

import pytest

from nodefusion.host import kernels as K
from nodefusion.host.record import Recorder, _exit_code
from nodefusion.model import manifest as M



_USER_PANIC = (
    "Rust user shell\n"
    ">> ch4_unmap\n"
    "Panicked at src/bin/ch4_unmap.rs:18, assertion `left == right` failed\n"
    "  left: 0\n right: -1\n"
    "Shell: Process 2 exited with code -1\n"
    ">> "
)

_CLEAN = (
    "Rust user shell\n"
    ">> ch6_file0\n"
    "file_test passed!\n"
    "Shell: Process 2 exited with code 0\n"
    ">> "
)

_KERNEL_PANIC = (
    "Rust user shell\n"
    ">> ch2b_bad_instructions\n"
    "[kernel] Panicked at src/syscall/mod.rs:82 Unsupported syscall_id: 9999\n"
)

_SHELL_DROWNED = (
    "Rust user shell\n"
    ">> " + "�" * 400 + "\n"
    "Panicked at src/lib.rs:30, Heap allocation error, "
    "layout = Layout { size: 8192, align: 1 (1 << 0) }\n"
)


@pytest.fixture
def rcore() -> K.KernelProfile:
    spec = M.load_dir(M.builtin_dir())["rcore"].profile
    p = K.KernelProfile.from_spec("rcore", spec)
    return replace(p, interactive=True, prompt=p.shell_prompt)


def verdict(profile: K.KernelProfile, console: str):
    r = Recorder.__new__(Recorder)
    r.profile = profile
    first = console.find(profile.prompt)
    mark = (first + len(profile.prompt)) if first >= 0 else 0
    return r._verdict(console, mark)



def test_user_program_panic_is_not_a_kernel_crash(rcore):
    outcome, code, amb = verdict(rcore, _USER_PANIC)
    assert outcome == "completed"
    assert code == -1, "退出码是这趟唯一说明程序失败了的东西，不能丢"
    assert amb is None


def test_the_same_console_always_gives_the_same_answer(rcore):
    final = verdict(rcore, _USER_PANIC)[0]
    assert final == "completed"
    for n in range(1, len(_USER_PANIC) + 1):
        v = verdict(rcore, _USER_PANIC[:n])
        if v is None:
            continue
        assert v[0] in (final, "guest_halted"), (
            f"看到前 {n} 个字符时判成 {v[0]}，看完整份却是 {final}")


def test_a_halt_before_the_exit_line_does_not_settle_it(rcore):
    cut = _USER_PANIC.index("Shell: Process")
    outcome, code, _ = verdict(rcore, _USER_PANIC[:cut])
    assert outcome == "guest_halted"
    assert code is None


def test_a_real_kernel_panic_is_still_a_panic(rcore):
    outcome, code, _ = verdict(rcore, _KERNEL_PANIC)
    assert outcome == "panic"
    assert code is None


def test_a_drowned_shell_is_not_reported_as_a_kernel_panic(rcore):
    outcome, _, _ = verdict(rcore, _SHELL_DROWNED)
    assert outcome == "guest_halted"


def test_a_clean_run_reports_exit_code_zero_not_none(rcore):
    outcome, code, _ = verdict(rcore, _CLEAN)
    assert outcome == "completed"
    assert code == 0 and code is not None



def test_without_an_exit_marker_the_ambiguity_is_recorded(rcore):
    mute = replace(rcore, exit_marker="")
    outcome, code, amb = verdict(mute, _USER_PANIC)
    assert outcome == "completed"
    assert code is None
    assert amb is not None, "没有退出行可依据时的歧义必须如实记下来"
    assert amb["halt_marker"] == "Panicked at"
    assert amb["halt_at"] < amb["prompt_at"]


def test_a_clean_run_is_not_flagged_ambiguous(rcore):
    mute = replace(rcore, exit_marker="")
    outcome, _, amb = verdict(mute, _CLEAN)
    assert outcome == "completed"
    assert amb is None



def test_halt_markers_fall_back_to_panic_markers(rcore):
    p = replace(rcore, panic_markers=("panic",), halt_markers=())
    assert p.halts() == ("panic",)
    assert replace(p, halt_markers=("oops",)).halts() == ("oops",)


def test_a_pattern_without_a_capture_group_yields_none_not_zero():
    import re
    assert _exit_code(re.search("exited", "exited")) is None
    assert _exit_code(re.search(r"code (\w+)", "code oops")) is None
    assert _exit_code(re.search(r"code (-?\d+)", "code -4")) == -4


def test_the_shipped_rcore_pattern_matches_the_real_line(rcore):
    import re
    hit = re.search(rcore.exit_marker, _USER_PANIC)
    assert hit is not None and _exit_code(hit) == -1
