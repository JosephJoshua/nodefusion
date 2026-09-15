
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


class ShellError(Exception):
    pass


def default_qemu_prefix() -> str:
    if platform.system() == "Darwin":
        return os.environ.get("NF_QEMU_PREFIX", "/opt/homebrew")
    return os.environ.get("NF_QEMU_PREFIX", "/opt/qemu-nf")


def plugin_filename() -> str:
    return "libnf.dylib" if platform.system() == "Darwin" else "libnf.so"


class Shell:

    def path(self, p: str | Path) -> str:
        raise NotImplementedError

    def run(self, script: str, *, check: bool = True,
            timeout: float | None = None) -> subprocess.CompletedProcess:
        raise NotImplementedError

    def popen(self, script: str) -> subprocess.Popen:
        raise NotImplementedError

    def describe(self) -> dict:
        raise NotImplementedError


    def check_env(self, required: tuple[str, ...] = ("qemu-system-riscv64",),
                  optional: tuple[str, ...] = ()) -> dict:
        names = tuple(required) + tuple(optional)
        lines = "; ".join(
            f'echo "{n}=$(command -v {n} 2>/dev/null)"' for n in names)
        r = self.run(lines + '; echo "QEMUVER=$(qemu-system-riscv64 --version '
                             '2>/dev/null | head -1)"', check=False)
        info: dict[str, str] = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k] = v.strip()
        missing = [n for n in required if not info.get(n)]
        if missing:
            raise ShellError(
                f"{self.describe().get('kind', '执行环境')} 里找不到："
                f"{', '.join(missing)}。装好之后再录。")
        return info


class LocalShell(Shell):

    def __init__(self, scratch: Path | None = None):
        self.bash = shutil.which("bash")
        if not self.bash:
            raise ShellError("找不到 bash")
        self.scratch = Path(scratch) if scratch else (
            Path(__file__).resolve().parents[1] / "runs" / "_tmp")
        self._seq = 0

    def path(self, p: str | Path) -> str:
        return str(p)

    def _write_script(self, script: str) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        self._seq += 1
        p = self.scratch / f"nf_cmd_{os.getpid()}_{self._seq}.sh"
        body = (
            "#!/bin/bash\n"
            "# NodeFusion 自动生成的临时脚本\n"
            f"export NF_QEMU_PREFIX=${{NF_QEMU_PREFIX:-{default_qemu_prefix()}}}\n"
            "export PATH=$NF_QEMU_PREFIX/bin:$PATH\n"
            + script + "\n"
        )
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        return p

    def run(self, script: str, *, check: bool = True,
            timeout: float | None = None) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [self.bash, str(self._write_script(script))],
            stdin=subprocess.DEVNULL,
            capture_output=True, timeout=timeout)
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        result = subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
        if check and proc.returncode != 0:
            raise ShellError(
                f"命令失败（退出码 {proc.returncode}）：\n"
                f"  命令：{script}\n"
                f"  stdout：{out.strip()[:2000]}\n"
                f"  stderr：{err.strip()[:2000]}")
        return result

    def popen(self, script: str) -> subprocess.Popen:
        return subprocess.Popen(
            [self.bash, str(self._write_script(script))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)

    def describe(self) -> dict:
        return {"kind": "local", "platform": platform.system(),
                "machine": platform.machine(),
                "qemu_prefix": default_qemu_prefix()}


def pick_shell(distro: str | None = None) -> Shell:
    if distro is not None or platform.system() == "Windows":
        from .wslenv import Wsl
        return Wsl(distro) if distro else Wsl()
    return LocalShell()
