
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import kernels
from . import layout as layout_mod
from . import watchlist as watchlist_mod
from . import elfid
from .nfelf import Elf64
from .shell import pick_shell, plugin_filename

END_MARKER = "__NF_RUN_END__"

PROMPT = "$ "

NO_PROGRAM = "(boot-to-exit)"


def _exit_code(hit: "re.Match") -> int | None:
    if not hit.groups():
        return None
    try:
        return int(hit.group(1))
    except (TypeError, ValueError):
        return None


class RecordError(Exception):
    pass


@dataclass
class RunConfig:
    kernel_dir: Path
    program: str
    name: str
    out_root: Path
    cpus: int = 1
    lab_stage: int | None = None
    make_vars: dict[str, str] = field(default_factory=dict)
    timeout: float = 180.0
    boot_timeout: float = 60.0
    sample_insns: int = 200_000
    snap_insns: int | None = None
    target_snapshots: int = 120
    boot_snap_insns: int | None = None
    boot_snapshots: int | None = None
    snap_start: int | None = None
    stdin_after: list[tuple[str, str]] = field(default_factory=list)
    stdin_timeout: float = 120.0
    max_ram_bytes: int = 1024 * 1024 * 1024
    max_snapshot_ram_bytes: int = 1024 * 1024 * 1024
    icount_shift: int = 3
    watch_all: bool = False
    watch_subsystems: tuple[str, ...] = ()
    watch_from_table: bool = False
    no_build: bool = False
    distro: str | None = None
    kernel_kind: str | None = None
    layout_override: Path | None = None


@dataclass
class RunResult:
    run_dir: Path
    outcome: str            # completed / panic / timeout / boot_failed / qemu_error
    console: str
    trace_path: Path
    manifest: dict


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class _ConsoleReader(threading.Thread):

    def __init__(self, stream, log_path: Path):
        super().__init__(daemon=True)
        self.stream = stream
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.log = open(log_path, "wb")
        self.eof = False

    def run(self):
        try:
            while True:
                chunk = self.stream.read(1)
                if not chunk:
                    break
                with self.lock:
                    self.buf += chunk
                self.log.write(chunk)
                self.log.flush()
        except Exception:
            pass
        finally:
            self.eof = True
            try:
                self.log.close()
            except Exception:
                pass

    def text(self) -> str:
        with self.lock:
            return self.buf.decode("utf-8", "replace")

    def wait_for(self, needle: str, timeout: float) -> bool:
        return self.wait_any((needle,), timeout) is not None

    def wait_any(self, needles, timeout: float):
        deadline = time.time() + timeout
        while True:
            text = self.text()
            for needle in needles:
                if needle in text:
                    return needle
            if self.eof:
                return None
            if time.time() >= deadline:
                return None
            time.sleep(0.05)


_PLUGIN_MOUNTED = "[nodefusion-plugin] 已挂载："
_PLUGIN_FINISHED = "[nodefusion-plugin] 结束："


def _trace_incomplete(qemu_err: str) -> str | None:
    if _PLUGIN_FINISHED in qemu_err:
        return None
    if _PLUGIN_MOUNTED not in qemu_err:
        return ("插件的挂载行都没出现，它很可能压根没加载起来。"
                f"QEMU stderr 末尾：{qemu_err.strip()[-500:]}")
    return (f"插件挂上了却没打出收尾行（{_PLUGIN_FINISHED.strip()}），"
            f"说明它没走到 nf_finish，轨迹缺结束记录。"
            f"QEMU stderr 末尾：{qemu_err.strip()[-500:]}")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _qmp_quit(port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.recv(4096)                                     # greeting
            s.sendall(b'{"execute":"qmp_capabilities"}\r\n')
            s.recv(4096)
            s.sendall(b'{"execute":"quit"}\r\n')
            try:
                s.recv(4096)
            except Exception:
                pass
        return True
    except Exception:
        return False


def select_watchlist(elf: Elf64, kernel_elf_path: Path, *, kind: str,
                     prefer_table: bool = False, watch_all: bool = False,
                     subsystems: tuple[str, ...] = ()
                     ) -> tuple[watchlist_mod.WatchList, str, list[str]]:
    if prefer_table:
        if subsystems:
            raise RecordError(
                "--watch-subsystem 只对 manifest 规则那条路有意义："
                "写死的名单是一串函数名，里面没有子系统可分。"
                "去掉 --watch-from-table，或者去掉 --watch-subsystem。")
        if not watchlist_mod.has_table(kind):
            raise RecordError(
                f"显式要求用写死名单，但没有名为 {kind!r} 的名单。"
                f"有名单的只有 {sorted(watchlist_mod.table_kinds())}；"
                "别的内核去掉 --watch-from-table 即可，规则那条路是默认。")
        return watchlist_mod.build(elf, kind=kind, watch_all=watch_all), "table", []

    from ..model.dwarfsrc import DwarfSource
    from ..model.manifest import builtin_dir, load_dir
    from ..model.probe import detect as detect_kernel

    dw = DwarfSource(str(kernel_elf_path))
    manifests = load_dir(builtin_dir())
    name, trace = detect_kernel(manifests, dw)
    if name is None:
        raise RecordError(
            "manifest 认不出这个内核，选不出观察点。逐条判定：\n  "
            + "\n  ".join(trace))
    from ..model.manifest import lint
    trace += [f"lint：{w}" for w in lint(manifests[name])]

    watches = manifests[name].watches
    source = f"manifest:{name}"
    if subsystems:
        declared = list(dict.fromkeys(w.subsystem for w in watches))
        unknown = [s for s in subsystems if s not in declared]
        if unknown:
            raise RecordError(
                f"{name} 没有名为 {'、'.join(repr(s) for s in unknown)} 的子系统。"
                f"这份 manifest 声明的是：{'、'.join(declared)}")
        kept = [w for w in watches if w.subsystem in subsystems]
        trace.append(
            f"按子系统收窄：{len(watches)} 条规则里留下 {len(kept)} 条"
            f"（{'、'.join(subsystems)}）")
        watches = kept
        source += "[" + "+".join(subsystems) + "]"

    wl = watchlist_mod.build_from_manifest(
        elf, dw, watches, watch_all=watch_all,
        events=manifests[name].events)
    return wl, source, trace


class ArtifactGuard:

    def __init__(self, paths):
        self._paths = [Path(p) for p in dict.fromkeys(paths)]
        self._dir: Path | None = None
        self._saved: dict[Path, Path] = {}

    def __enter__(self) -> ArtifactGuard:
        self._dir = Path(tempfile.mkdtemp(prefix="nf-artifacts-"))
        for i, p in enumerate(self._paths):
            if p.is_file():
                dst = self._dir / f"{i}-{p.name}"
                shutil.copy2(p, dst)
                self._saved[p] = dst
        return self

    def __exit__(self, *exc) -> None:
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def had(self, path: Path) -> bool:
        return Path(path) in self._saved

    def restore(self) -> list[Path]:
        back: list[Path] = []
        for orig, copy in self._saved.items():
            try:
                orig.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy, orig)
                back.append(orig)
            except OSError:
                pass
        return back


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class Recorder:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.sh = pick_shell(cfg.distro)
        self.profile = (kernels.by_kind(cfg.kernel_kind, cfg.kernel_dir)
                        if cfg.kernel_kind
                        else kernels.detect(cfg.kernel_dir))
        self.run_dir = cfg.out_root / cfg.name
        self.repo_root = Path(__file__).resolve().parents[2]
        self.plugin_so = (self.repo_root / "nodefusion" / "plugin"
                          / plugin_filename())
        self.warnings: list[str] = []
        self.program_exit_code: int | None = None
        self.outcome_ambiguous: dict | None = None
        for opt in self.profile.unsupported:
            val = getattr(cfg, opt, None)
            if val and val != NO_PROGRAM:
                self.warnings.append(
                    f"{self.profile.kind} 没有 shell，忽略选项 {opt}={val!r}："
                    f"内核自己按顺序跑完所有应用，没有地方喂命令。")


    def effective_lab_stage(self) -> int | None:
        if self.cfg.lab_stage is not None:
            return self.cfg.lab_stage
        mk = self.cfg.kernel_dir / "Makefile"
        if mk.exists():
            m = re.search(r"^\s*LAB_STAGE\s*\?=\s*(\d+)", mk.read_text(errors="replace"),
                          re.MULTILINE)
            if m:
                return int(m.group(1))
        return None

    def _make_var_string(self) -> str:
        parts = []
        if self.cfg.lab_stage is not None:
            parts.append(f"LAB_STAGE={self.cfg.lab_stage}")
        for k, v in self.cfg.make_vars.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)

    def build_plugin(self) -> None:
        plugin_dir = self.repo_root / "nodefusion" / "plugin"
        self.sh.run(f'cd "{self.sh.path(plugin_dir)}" && make -s')
        if not self.plugin_so.exists():
            raise RecordError(f"插件没有构建出来：{self.plugin_so}")

    @property
    def kernel_elf_path(self) -> Path:
        return self.cfg.kernel_dir / self.profile.kernel_elf

    def build_kernel(self) -> str:
        if self.cfg.no_build:
            missing = [p for p in (self.kernel_elf_path,
                                   self.cfg.kernel_dir / self.profile.kernel_image)
                       if not p.exists()]
            if missing:
                raise RecordError(
                    "--no-build 要求产物已经在了，但这些不在：\n  "
                    + "\n  ".join(str(p) for p in missing)
                    + "\n去掉 --no-build 编一次，或者确认 --kernel 指对了目录。")
            import datetime as _dt
            mt = _dt.datetime.fromtimestamp(
                self.kernel_elf_path.stat().st_mtime, _dt.timezone.utc)
            self.warnings.append(
                f"--no-build：这次没有编译，直接用了现成的 "
                f"{self.kernel_elf_path}（修改时间 "
                f"{mt.strftime('%Y-%m-%d %H:%M UTC')}）。"
                "也就是说**没人验证过这份二进制是当前源码编出来的**；"
                "它可能是任何时候留下的。ELF 指纹见 kernel_elf_identity。")
            return "(--no-build：跳过构建)"

        mv = self._make_var_string()
        if mv and "{mv}" not in self.profile.build:
            raise RecordError(
                f"给了构建参数（{mv}），但 {self.profile.kind} 的 manifest "
                f"里 `[profile] build` 没有 `{{mv}}` 落点，参数会被丢掉。\n"
                "要么在那条 build 命令里加上 `{mv}`，要么别传 --make-var"
                "／--lab-stage —— 不能让存档记着一个没真正生效的参数。")
        kd = self.sh.path(self.cfg.kernel_dir)
        image = self.cfg.kernel_dir / self.profile.kernel_image
        keep = self.profile.protected(self.cfg.kernel_dir)

        protect = [self.kernel_elf_path, image, *keep]

        with ArtifactGuard(protect) as guard:
            for stale in {self.kernel_elf_path, image}:
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass
                except OSError as ex:
                    raise RecordError(
                        f"删不掉上一次的产物 {stale}：{ex}。"
                        f"继续编下去可能会录到旧内核，这里直接停。") from ex

            r = self.sh.run('set -o pipefail; ' + f'cd "{kd}" && '
                            + self.profile.build.format(mv=mv), check=False)

            problems: list[str] = []
            if not self.kernel_elf_path.exists():
                problems.append(f"内核没有编译出来：{self.kernel_elf_path}")
            if not image.exists():
                problems.append(f"内核镜像没有生成：{image}")
            required = set(self.profile.required_after_build(self.cfg.kernel_dir))
            for f in keep:
                if f in required and guard.had(f) and not f.exists():
                    problems.append(
                        f"构建把它删掉了又没建回来：{f}\n"
                        f"    如果这是 xv6 的 fs.img，在 macOS 上通常是 mkfs 编不过"
                        f" —— kernel/fs.h 里的 __attribute__((nonstring)) 过不了 "
                        f"Apple clang 的 -Werror。内核本身没问题"
                        f"（走 riscv64-unknown-elf-gcc）。")

            if problems:
                back = guard.restore()
                note = ("\n构建前的产物已放回原处："
                        + "、".join(str(p) for p in back)) if back else \
                       "\n（构建前没有可恢复的产物）"
                raise RecordError("\n".join(problems) + note
                                  + f"\n\n构建输出末尾：\n{r.stdout[-2000:]}")

            if r.returncode != 0:
                self.warnings.append(
                    f"构建整体返回 {r.returncode}，但内核 ELF 和镜像都已生成；"
                    f"失败的是内核之外的目标（如 fs-img）。"
                    f"若该内核需要文件系统镜像，本次运行的行为可能与预期不同。"
                    f"构建输出末尾：{r.stdout.strip()[-600:]}")
            return r.stdout


    def _qemu_cmd(self, trace_path: Path, watch_path: Path | None,
                  snap_insns: int, qmp_port: int) -> str:
        c = self.cfg
        kd = self.sh.path(c.kernel_dir)
        plugin_args = [
            f"out={self.sh.path(trace_path)}",
            f"sample={c.sample_insns}",
            f"snap={snap_insns}",
            f"maxram={c.max_ram_bytes}",
            f"snapstart={getattr(self, '_snap_start', 0)}",
            f"bootsnap={getattr(self, '_boot_snap', 0)}",
        ]
        ram, why = self.profile.ram_bytes()
        if ram is not None:
            cap = c.max_snapshot_ram_bytes
            if cap and ram > cap:
                self.warnings.append(
                    f"这台机器声明了 {ram // 1048576} MiB 物理内存，但每帧只拍前 "
                    f"{cap // 1048576} MiB（max_snapshot_ram_bytes）。超出那段的"
                    f"地址读出来是「没观察到」，不是零 —— 若有结构落在那里，"
                    f"它会被如实标成读不到。要整块拍下就调大这个上限。")
                ram = cap
            plugin_args.append(f"ramsize={ram}")
        elif why:
            self.warnings.append(
                f"没能从 machine_opts 得出物理内存大小（{why}），"
                f"插件将按它自己的默认值拍快照；若这台机器的内存比默认值大，"
                f"超出的部分不会进快照，那段地址上的结构会读成"
                f"「没观察到」。")

        ev_min = getattr(self.profile, "event_snapshot_min_insns", 0)
        if ev_min:
            plugin_args.append(f"evsnapmin={ev_min}")
        if watch_path is not None:
            plugin_args.append(f"watch={self.sh.path(watch_path)}")
        plugin = f"{self.sh.path(self.plugin_so)}," + ",".join(plugin_args)

        opts = list(self.profile.machine_args(c.kernel_dir)) + [
            f"-smp {c.cpus}", "-nographic",
            f"-icount shift={c.icount_shift}",
            f"-qmp tcp:127.0.0.1:{qmp_port},server=on,wait=off",
            f"-plugin {plugin}",
        ]
        return (f'cd "{kd}" && exec qemu-system-riscv64 ' + " ".join(opts))

    def _drive(self, trace_path: Path, watch_path: Path | None,
               snap_insns: int, console_log: Path,
               stderr_log: Path) -> tuple[str, str, str]:
        c = self.cfg
        qmp_port = _free_port()
        cmd = self._qemu_cmd(trace_path, watch_path, snap_insns, qmp_port)
        self.qemu_cmd = cmd
        proc = self.sh.popen(cmd)
        reader = _ConsoleReader(proc.stdout, console_log)
        reader.start()
        err_reader = _ConsoleReader(proc.stderr, stderr_log)
        err_reader.start()

        outcome = "unknown"
        try:
            if not self.profile.interactive:
                outcome = self._drive_headless(proc, reader)
            else:
                outcome = self._drive_shell(proc, reader)
        finally:
            if proc.poll() is None:
                if not _qmp_quit(qmp_port):
                    proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            reader.join(timeout=5)
            err_reader.join(timeout=5)

        return outcome, reader.text(), err_reader.text()

    def _drive_headless(self, proc, reader) -> str:
        c = self.cfg
        p = self.profile
        deadline = time.time() + c.timeout
        boot_deadline = time.time() + c.boot_timeout
        booted = False

        while time.time() < deadline:
            if reader.eof or proc.poll() is not None:
                return p.classify(reader.text())
            txt = reader.text()
            if not booted:
                if p.booted(txt):
                    booted = True
                elif time.time() >= boot_deadline:
                    return "boot_failed"
            if any(m in txt for m in p.done_markers):
                for _ in range(50):
                    if reader.eof or proc.poll() is not None:
                        break
                    time.sleep(0.1)
                return "completed"
            if any(m in txt for m in p.panic_markers):
                time.sleep(1.5)
                return "panic"
            time.sleep(0.05)
        return "timeout"

    def _drive_shell(self, proc, reader) -> str:
        c = self.cfg
        p = self.profile
        prompt = p.prompt or PROMPT
        panic_mark = p.panic_markers[0] if p.panic_markers else "panic"

        def send(text: str) -> None:
            try:
                proc.stdin.write(text.encode())
                proc.stdin.flush()
            except Exception as exc:
                raise RecordError(f"往 guest 控制台写命令失败：{exc}")

        preloaded = False
        if p.stdin_preload and c.program and c.program != NO_PROGRAM:
            send(f"{p.stdin_pad}{c.program}\n")
            preloaded = True

        boot = reader.wait_any((prompt, panic_mark), c.boot_timeout)
        if boot == panic_mark:
            time.sleep(1.5)
            return "panic"
        if boot is None:
            return "boot_failed"

        if not preloaded:
            send(f"{c.program}\n")
            mark = len(reader.text())
        else:
            txt = reader.text()
            first = txt.find(prompt)
            mark = (first + len(prompt)) if first >= 0 else len(txt)

        for marker, text in (c.stdin_after or []):
            if not reader.wait_for(marker, c.stdin_timeout):
                raise RecordError(
                    f"等待 guest 输出标记 {marker!r} 超时（{c.stdin_timeout}s），"
                    f"无法送出后续输入 {text!r}。"
                    f"控制台最后几行：\n{reader.text()[-400:]}")
            send(text)

        deadline = time.time() + c.timeout
        while time.time() < deadline:
            verdict = self._verdict(reader.text(), mark)

            if verdict and verdict[0] == "guest_halted":
                time.sleep(1.5)
                verdict = self._verdict(reader.text(), mark) or verdict

            if verdict:
                outcome, self.program_exit_code, self.outcome_ambiguous = verdict
                if outcome == "panic":
                    time.sleep(1.5)
                elif outcome == "completed":
                    time.sleep(0.3)
                return outcome

            if reader.eof or proc.poll() is not None:
                return "qemu_exited"
            time.sleep(0.05)
        return "timeout"

    def _verdict(self, txt: str, mark: int
                 ) -> tuple[str, int | None, dict | None] | None:
        p = self.profile
        prompt = p.prompt or PROMPT

        if p.exit_marker:
            hit = re.search(p.exit_marker, txt[mark:])
            if hit:
                return ("completed", _exit_code(hit), None)

        if any(m in txt for m in p.done_markers):
            return ("completed", None, None)

        if any(m in txt for m in p.panic_markers):
            return ("panic", None, None)

        if prompt in txt[mark:]:
            halted = next((m for m in p.halts() if m in txt), None)
            if halted is not None:
                return ("completed", None, {
                    "why": "控制台里同时有完成提示符和 halt 标记，而这个内核的 "
                           "profile 没有 exit_marker，无从确认程序真的跑完了。",
                    "prompt_at": txt.index(prompt, mark),
                    "halt_at": txt.index(halted),
                    "halt_marker": halted,
                    "resolved_as": "completed",
                })
            return ("completed", None, None)

        if any(m in txt for m in p.halts()):
            return ("guest_halted", None, None)

        return None


    def _calibrate(self, watch_path: Path | None,
                   wl_json: dict) -> tuple[int, int]:
        tmp_trace = self.run_dir / "calibration.nfb"
        with ArtifactGuard(self.profile.protected(self.cfg.kernel_dir)) as disks:
            outcome, console, _ = self._drive(
                tmp_trace, watch_path, snap_insns=0,
                console_log=self.run_dir / "calibration.console.log",
                stderr_log=self.run_dir / "calibration.qemu.log")
            disks.restore()

        from . import nftrace as nftrace_mod
        total = 0
        prog_start = 0
        if tmp_trace.exists():
            tr = nftrace_mod.load(tmp_trace, want_pages=False)
            total = tr.total_insns
            # Manifest-selected watches keep the real function name (for
            # example ``load_user_app``) and carry the normalized event name
            # in ``kind``.  The old table watchlist happened to call the entry
            # simply ``exec``; keying calibration only on that legacy label
            # silently left program_start_insn at zero for StarryOS.
            exec_ids = {
                e["index"] for e in wl_json["entries"]
                if e.get("kind") == "proc.exec" or e.get("name") == "exec"
            }
            if exec_ids:
                for w in reversed(tr.watch_hits):
                    if w.watch_id in exec_ids:
                        prog_start = w.insn
                        break
            tmp_trace.unlink(missing_ok=True)
        if total <= 0:
            raise RecordError(
                "校准跑没有拿到任何指令计数。\n"
                + self._calibration_failure_reason(
                    self.run_dir / "calibration.qemu.log"))
        return total, prog_start

    _LOCK_MARKERS = ('Failed to get "write" lock',
                     "Is another process using the image")

    @staticmethod
    def _calibration_failure_reason(log_path: Path) -> str:
        try:
            text = log_path.read_text(errors="replace")
        except OSError:
            return "（连 calibration.qemu.log 都读不到，没法说原因）"
        tail = "\n".join(text.strip().splitlines()[-6:])
        if any(m in text for m in Recorder._LOCK_MARKERS):
            return (
                "QEMU 拿不到磁盘镜像的写锁——多半是上一次录制留下的 QEMU 还活着。\n"
                "外层 timeout 杀掉 record，QEMU 不一定跟着死；它会接着往原来那个\n"
                "trace.nfb 写，哪怕那个文件已经被删了。删掉仍被打开的文件不释放\n"
                "磁盘块，所以 rm 掉 run 目录之后 df 也不会变。\n"
                "查一下：pgrep -f qemu-system-riscv64\n"
                f"QEMU stderr 末尾：\n{tail}")
        return (
            "插件真没挂上的话，stderr 里不会有\"已挂载\"那一行；先看这段再决定要不要\n"
            "去查 --enable-plugins。\n"
            f"QEMU stderr 末尾：\n{tail}")



    _SHELL_HEAP_PANIC = "Heap allocation error"

    def _note_shell_heap_panic(self, console: str) -> None:
        if self._SHELL_HEAP_PANIC not in (console or ""):
            return
        self.warnings.append(
            "控制台末尾的 `Panicked at src/lib.rs, Heap allocation error` "
            "是目标程序**正常退出之后**才发生的，跟它无关：shell 回到提示符继续读输入，"
            "而 os/src/fs/stdio.rs 判空写的是 `if c == 0`（RustSBI 约定），"
            "我们用的 QEMU 自带 OpenSBI 取不到字符时返回 -1，于是 0xFF 被当成真字符"
            "灌进行缓冲区，撑爆 8 KB 用户堆。结局判定看的是提示符是否重新出现，"
            "不受这次 panic 影响；目标程序的退出码见控制台里 shell 打的那一行。")

    def run(self) -> RunResult:
        c = self.cfg
        self.run_dir.mkdir(parents=True, exist_ok=True)

        env_info = self.sh.check_env(required=self.profile.required_tools)
        env_info["shell"] = self.sh.describe()
        self.build_plugin()
        build_log = self.build_kernel()

        kernel_elf_path = self.kernel_elf_path
        elf = Elf64(kernel_elf_path)

        lab_stage = self.effective_lab_stage()
        kl = layout_mod.probe(c.kernel_dir, self.sh,
                              make_vars=(f"-DLAB_STAGE={lab_stage}"
                                         if lab_stage is not None else ""),
                              work_dir=self.run_dir / "_layout",
                              override=c.layout_override,
                              kind=self.profile.kind,
                              elf_path=kernel_elf_path)
        layout_mod.save(kl, self.run_dir / "kernel_layout.json")

        wl, watch_source, detect_trace = select_watchlist(
            elf, kernel_elf_path, kind=self.profile.kind,
            prefer_table=c.watch_from_table, watch_all=c.watch_all,
            subsystems=tuple(c.watch_subsystems))
        watch_path = self.run_dir / "watchlist.txt"
        watch_path.write_text(wl.to_file_text(), encoding="utf-8", newline="\n")
        (self.run_dir / "watchlist.json").write_text(
            json.dumps(wl.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")

        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
        calibrated_total = None
        prog_start = 0

        need_calib = (c.snap_insns is None
                      or c.snap_start is None
                      or (c.boot_snap_insns is None and c.boot_snapshots is not None))
        if need_calib:
            calibrated_total, prog_start = self._calibrate(watch_path, wl.to_json())

        if c.snap_insns is not None:
            snap_insns = c.snap_insns
        elif prog_start > 0 and calibrated_total and calibrated_total > prog_start:
            snap_insns = max(200_000,
                             (calibrated_total - prog_start) // max(1, c.target_snapshots))
        else:
            snap_insns = max(1_000_000,
                             (calibrated_total or 1_000_000_000) // max(1, c.target_snapshots))

        if c.boot_snap_insns is not None:
            boot_snap = c.boot_snap_insns
        elif c.boot_snapshots and prog_start > 0:
            boot_snap = max(50_000, prog_start // max(1, c.boot_snapshots))
        elif prog_start > 0:
            boot_snap = max(1_000_000, prog_start // 20)
        else:
            boot_snap = 0

        snap_start = c.snap_start if c.snap_start is not None else prog_start
        if snap_start == 0:
            boot_snap = 0

        trace_path = self.run_dir / "trace.nfb"
        self._snap_start = snap_start
        self._boot_snap = boot_snap
        started = datetime.now(timezone.utc)
        t0 = time.time()
        outcome, console, qemu_err = self._drive(
            trace_path, watch_path, snap_insns,
            console_log=self.run_dir / "console.log",
            stderr_log=self.run_dir / "qemu.log")
        wall = time.time() - t0
        self._note_shell_heap_panic(console)

        if not trace_path.exists():
            raise RecordError(
                f"没有产出轨迹文件 {trace_path}。QEMU stderr：\n{qemu_err[-3000:]}")

        trace_why = _trace_incomplete(qemu_err)

        elf_ident = elfid.elf_identity(kernel_elf_path)
        archived = kernels.archive_build(kernel_elf_path, self.profile.kind,
                                         elf_ident)

        manifest = {
            "nodefusion_version": "1.0.0",
            "run_name": c.name,
            "program": c.program,
            "outcome": outcome,
            "program_exit_code": self.program_exit_code,
            "outcome_ambiguous": self.outcome_ambiguous,
            "trace_complete": trace_why is None,
            "trace_incomplete_reason": trace_why,
            "started_utc": started.isoformat(),
            "wall_seconds": round(wall, 2),
            "kernel_dir": str(c.kernel_dir),
            "kernel_kind": self.profile.kind,
            "kernel_elf": str(archived or kernel_elf_path),
            "kernel_elf_build_path": str(kernel_elf_path),
            "kernel_elf_identity": elf_ident,
            "kernel_elf_archived": str(archived) if archived else None,
            "lab_stage": lab_stage,
            "lab_stage_source": "命令行指定" if c.lab_stage is not None else "Makefile 默认值",
            "make_vars": c.make_vars,
            "cpus": c.cpus,
            "icount_shift": c.icount_shift,
            "sample_insns": c.sample_insns,
            "snap_insns": snap_insns,
            "boot_snap_insns": boot_snap,
            "snap_start_insn": snap_start,
            "program_start_insn": prog_start,
            "calibrated_total_insns": calibrated_total,
            "max_ram_bytes": c.max_ram_bytes,
            "wsl_env": env_info,
            "record_warnings": self.warnings,
            "watchlist_missing": wl.missing,
            "watch_source": watch_source,
            "watch_detect": detect_trace,
            "kernel_layout_kind": kl.kind,
            "kernel_layout_missing": kl.missing,
            "kernel_layout_notes": kl.notes,
            "build_log_tail": build_log[-2000:],
            "qemu_cmd": getattr(self, "qemu_cmd", ""),
            "qemu_stderr_tail": qemu_err[-4000:],
        }
        (self.run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        return RunResult(self.run_dir, outcome, console, trace_path, manifest)


def record(cfg: RunConfig) -> RunResult:
    return Recorder(cfg).run()
