
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

from .shell import Shell, ShellError

DEFAULT_DISTRO = os.environ.get("NF_WSL_DISTRO", "Ubuntu-24.04")


class WslError(ShellError):
    pass


def find_wsl() -> str:
    exe = shutil.which("wsl") or shutil.which("wsl.exe")
    if not exe:
        raise WslError(
            "找不到 wsl.exe。NodeFusion 的录制侧需要 WSL2；"
            "环境搭建见 NodeFusion_环境准备说明.md")
    return exe


def to_wsl_path(p: str | Path) -> str:
    s = str(p)
    if s.startswith("/"):
        return s
    win = PureWindowsPath(s)
    drive = win.drive.rstrip(":").lower()
    if not drive:
        raise WslError(f"无法换算路径 {p}：既不是绝对 Windows 路径也不是 POSIX 路径")
    rest = "/".join(win.parts[1:])
    return f"/mnt/{drive}/{rest}"


def to_win_path(p: str) -> Path:
    m = re.match(r"^/mnt/([a-z])/(.*)$", p)
    if not m:
        raise WslError(f"{p} 不是 /mnt/<盘符> 形式，无法换算回 Windows 路径")
    return Path(f"{m.group(1).upper()}:\\" + m.group(2).replace("/", "\\"))


class Wsl(Shell):

    DEFAULT_SCRATCH = Path(__file__).resolve().parents[1] / "runs" / "_tmp"

    def __init__(self, distro: str = DEFAULT_DISTRO, scratch: Path | None = None):
        self.distro = distro
        self.exe = find_wsl()
        self.scratch = Path(scratch) if scratch else self.DEFAULT_SCRATCH
        self._seq = 0

    def path(self, p: str | Path) -> str:
        return to_wsl_path(p)

    def describe(self) -> dict:
        return {"kind": "wsl", "distro": self.distro}

    def _write_script(self, script: str) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        self._seq += 1
        p = self.scratch / f"nf_cmd_{os.getpid()}_{self._seq}.sh"
        body = (
            "#!/bin/bash\n"
            "# NodeFusion 自动生成的临时脚本\n"
            "export NF_QEMU_PREFIX=${NF_QEMU_PREFIX:-/opt/qemu-nf}\n"
            "export PATH=$NF_QEMU_PREFIX/bin:$PATH\n"
            + script + "\n"
        )
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        return p

    def _argv(self, script: str, user: str | None = None) -> list[str]:
        path = self._write_script(script)
        argv = [self.exe, "-d", self.distro]
        if user:
            argv += ["-u", user]
        argv += ["--", "bash", to_wsl_path(path)]
        return argv

    def run(self, script: str, *, check: bool = True, user: str | None = None,
            timeout: float | None = None) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            self._argv(script, user),
            stdin=subprocess.DEVNULL,
            capture_output=True, timeout=timeout)
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        result = subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
        if check and proc.returncode != 0:
            raise WslError(
                f"WSL 命令失败（退出码 {proc.returncode}）：\n"
                f"  命令：{script}\n"
                f"  stdout：{out.strip()[:2000]}\n"
                f"  stderr：{err.strip()[:2000]}")
        return result

    def popen(self, script: str) -> subprocess.Popen:
        return subprocess.Popen(
            self._argv(script),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
