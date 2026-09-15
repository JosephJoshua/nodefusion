
from __future__ import annotations

import functools
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from ..model.manifest import Device, Manifest, builtin_dir, load_dir


class ProfileError(Exception):
    pass


def _crate_name(kernel_dir: Path) -> str:
    p = Path(kernel_dir) / "Cargo.toml"
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(
            f"{p} 不在。这个内核的 profile 用 {{crate}} 表示产物名，"
            f"要靠 Cargo.toml 的 [package] name 才知道它叫什么。") from None
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ProfileError(f"读不了 {p}：{e}") from e
    name = (raw.get("package") or {}).get("name")
    if not isinstance(name, str) or not name:
        raise ProfileError(f"{p} 里没有 [package] name，无法确定产物叫什么。")
    return name


@dataclass(frozen=True)
class KernelProfile:
    kind: str
    kernel_elf: str
    kernel_image: str
    build: str
    detect_files: tuple[str, ...]
    required_tools: tuple[str, ...]
    machine_opts: tuple[str, ...]
    interactive: bool
    prompt: str = ""
    ready_markers: tuple[str, ...] = ()
    done_markers: tuple[str, ...] = ()
    panic_markers: tuple[str, ...] = ("panic",)
    unsupported: tuple[str, ...] = ()
    build_deviation: str = ""
    devices: tuple[Device, ...] = ()
    protect: tuple[str, ...] = ()

    shell_probe: tuple[str, str] = ()
    shell_prompt: str = ""
    shell_ready_marker: str = ""
    stdin_preload: bool = False
    stdin_pad: str = ""
    event_snapshot_min_insns: int = 0
    exit_marker: str = ""
    halt_markers: tuple[str, ...] = ()

    def halts(self) -> tuple[str, ...]:
        return self.halt_markers or self.panic_markers

    @classmethod
    def from_spec(cls, kind: str, s) -> "KernelProfile":
        probe = s.shell_probe or {}
        return cls(
            kind=kind,
            kernel_elf=s.kernel_elf, kernel_image=s.kernel_image, build=s.build,
            detect_files=tuple(s.detect_files),
            required_tools=tuple(s.required_tools),
            machine_opts=tuple(s.machine_opts),
            interactive=s.interactive, prompt=s.prompt,
            ready_markers=tuple(s.ready_markers),
            done_markers=tuple(s.done_markers),
            panic_markers=tuple(s.panic_markers),
            unsupported=tuple(s.unsupported),
            build_deviation=s.build_deviation,
            devices=tuple(s.devices), protect=tuple(s.protect),
            shell_probe=(probe["dir"], probe["ident"]) if probe else (),
            shell_prompt=s.shell_prompt,
            shell_ready_marker=s.shell_ready_marker,
            stdin_preload=s.stdin_preload, stdin_pad=s.stdin_pad,
            event_snapshot_min_insns=s.event_snapshot_min_insns,
            exit_marker=s.exit_marker,
            halt_markers=tuple(s.halt_markers))

    def specialize(self, kernel_dir: Path) -> "KernelProfile":
        return self._expand(kernel_dir)._probe_shell(kernel_dir)

    def _expand(self, kernel_dir: Path) -> "KernelProfile":
        if not any("{crate}" in s for s in self._templated()):
            return self
        c = _crate_name(kernel_dir)

        def sub(s: str) -> str:
            return s.replace("{crate}", c)

        return replace(
            self,
            kernel_elf=sub(self.kernel_elf), kernel_image=sub(self.kernel_image),
            build=sub(self.build),
            machine_opts=tuple(sub(o) for o in self.machine_opts),
            protect=tuple(sub(f) for f in self.protect),
            devices=tuple(Device(file=sub(d.file),
                                 opts=tuple(sub(o) for o in d.opts),
                                 built_when=d.built_when)
                          for d in self.devices))

    def _templated(self) -> tuple[str, ...]:
        return (self.kernel_elf, self.kernel_image, self.build,
                *self.machine_opts, *self.protect,
                *(d.file for d in self.devices),
                *(o for d in self.devices for o in d.opts))

    def _probe_shell(self, kernel_dir: Path) -> "KernelProfile":
        if not self.shell_probe:
            return self
        rel, ident = self.shell_probe
        root = Path(kernel_dir) / rel
        found = any(
            ident in p.read_text(encoding="utf-8", errors="ignore")
            for p in root.rglob("*.rs")) if root.is_dir() else False
        if not found:
            return self
        return replace(
            self, interactive=True, prompt=self.shell_prompt,
            ready_markers=(self.shell_ready_marker,) if self.shell_ready_marker
            else self.ready_markers,
            unsupported=tuple(o for o in self.unsupported
                              if o not in ("program", "stdin_after")))

    def ram_bytes(self) -> tuple[int | None, str]:
        raw: str | None = None
        for i, o in enumerate(self.machine_opts):
            t = o.strip()
            if t == "-m" and i + 1 < len(self.machine_opts):
                raw = self.machine_opts[i + 1].strip()
                break
            if t.startswith("-m "):
                raw = t[3:].strip()
                break
        if raw is None:
            return None, "machine_opts 里没有 -m，交给 QEMU 和插件各自的默认值"

        if "=" in raw:
            part = None
            for seg in raw.split(","):
                k, _, v = seg.partition("=")
                if k.strip() == "size":
                    part = v.strip()
                    break
            if part is None:
                return None, f"-m 的值 {raw!r} 里没有 size=，读不出初始内存大小"
            raw = part
        else:
            raw = raw.split(",")[0].strip()

        mult = 1024 * 1024
        if raw and raw[-1] in "bBkKmMgG":
            mult = {"b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[raw[-1].lower()]
            raw = raw[:-1]
        try:
            n = int(raw)
        except ValueError:
            return None, f"-m 的值 {raw!r} 不是整数，读不出内存大小"
        if n <= 0:
            return None, f"-m 算出来是 {n} 字节，不是个合法的内存大小"
        return n * mult, ""

    def machine_args(self, kernel_dir: Path) -> tuple[str, ...]:
        opts = list(self.machine_opts)
        for d in self.devices:
            if (Path(kernel_dir) / d.file).exists():
                opts += d.opts
        return tuple(opts)

    def protected(self, kernel_dir: Path) -> tuple[Path, ...]:
        kd = Path(kernel_dir)
        return tuple(kd / f for f in
                     dict.fromkeys(list(self.protect) +
                                   [d.file for d in self.devices]))

    def builds(self, device: Device, kernel_dir: Path) -> bool:
        if not device.built_when:
            return True
        rel, needle = device.built_when
        try:
            return needle in (Path(kernel_dir) / rel).read_text(
                encoding="utf-8", errors="ignore")
        except OSError:
            return True

    def required_after_build(self, kernel_dir: Path) -> tuple[Path, ...]:
        kd = Path(kernel_dir)
        return tuple(kd / f for f in self.protect) + tuple(
            kd / d.file for d in self.devices if self.builds(d, kd))

    def classify(self, console: str) -> str:
        if any(m in console for m in self.done_markers):
            return "completed"
        if any(m in console for m in self.panic_markers):
            return "panic"
        return "qemu_exited"

    def booted(self, console: str) -> bool:
        if not self.ready_markers:
            return True
        return any(m in console for m in self.ready_markers)


ARCHIVE = Path(__file__).resolve().parents[1] / "kernels"


def archived_elf(kind: str) -> Path | None:
    hits = sorted(p for p in ARCHIVE.glob(f"{kind}-*.elf") if p.is_file())
    if not hits:
        return None
    if len(hits) > 1:
        raise ProfileError(
            f"{kind} 归档了不止一份 ELF，说不好该用哪份："
            + "、".join(p.name for p in hits)
            + "。按 kernel_elf_identity 里的哈希挑一份，路径写全。")
    return hits[0]


BUILDS = ARCHIVE / "builds"


def _sha256(path: Path) -> str | None:
    import hashlib
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def archived_elf_for_identity(identity: dict | None,
                              kind: str | None = None) -> Path | None:
    want = (identity or {}).get("sha256")
    if not want:
        return None

    pool = [p for p in (*ARCHIVE.glob("*.elf"), *BUILDS.glob("*.elf"))
            if p.is_file()]
    pool.sort(key=lambda p: (want[:8] not in p.name,
                             not (kind and p.name.startswith(f"{kind}-"))))
    for p in pool:
        if _sha256(p) == want:
            return p
    return None


def archive_build(elf_path: Path, kind: str,
                  identity: dict | None = None) -> Path | None:
    sha = (identity or {}).get("sha256") or _sha256(Path(elf_path))
    if not sha:
        return None
    have = archived_elf_for_identity({"sha256": sha})
    if have is not None:
        return have

    import shutil
    try:
        top = sorted(p for p in ARCHIVE.glob(f"{kind}-*.elf") if p.is_file())
        dest_dir = ARCHIVE if not top else BUILDS
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{kind}-{sha[:8]}.elf"
        tmp = dest.with_suffix(".elf.part")
        shutil.copyfile(elf_path, tmp)
        tmp.replace(dest)
        return dest
    except OSError:
        return None


@functools.lru_cache(maxsize=1)
def _manifests() -> dict[str, Manifest]:
    return load_dir(builtin_dir())


@functools.lru_cache(maxsize=1)
def _profiles() -> dict[str, KernelProfile]:
    return {name: KernelProfile.from_spec(name, m.profile)
            for name, m in _manifests().items() if m.profile is not None}


def recordable() -> list[str]:
    return sorted(_profiles())


def unrecordable() -> list[str]:
    return sorted(n for n, m in _manifests().items() if m.profile is None)


def _hint_unrecordable() -> str:
    miss = unrecordable()
    return (f"\n  这几份 manifest 只有读的规则、还没写 [profile]，因此录不了："
            f"{'、'.join(miss)}。" if miss else "")


def _most_specific(hits: list[str]) -> list[str]:
    ms = _manifests()
    bases = {ms[n].builds_on for n in hits if ms[n].builds_on}
    return [n for n in hits if n not in bases] or hits


def detect(kernel_dir: Path) -> KernelProfile:
    kernel_dir = Path(kernel_dir)
    ps = _profiles()
    hits = _most_specific(
        [n for n, p in ps.items()
         if p.detect_files
         and all((kernel_dir / f).exists() for f in p.detect_files)])

    if len(hits) == 1:
        return ps[hits[0]].specialize(kernel_dir)
    if len(hits) > 1:
        raise ProfileError(
            f"{kernel_dir} 同时符合 {'、'.join(sorted(hits))} 的特征，分不出是哪个。\n"
            f"  用 --kernel-kind 明确指定。")
    lines = "\n".join(f"  {n} 需要 {'、'.join(p.detect_files)}"
                      for n, p in sorted(ps.items()) if p.detect_files)
    raise ProfileError(
        f"认不出 {kernel_dir} 是哪种内核。\n{lines}\n"
        f"  可以用 --kernel-kind 显式指定（{'/'.join(sorted(ps))}）。"
        + _hint_unrecordable())


def by_kind(kind: str, kernel_dir: Path | None = None) -> KernelProfile:
    ps = _profiles()
    if kind not in ps:
        raise ProfileError(
            f"没有名为 {kind!r} 的内核 profile，能录的有：{'/'.join(sorted(ps))}。"
            + _hint_unrecordable())
    p = ps[kind]
    return p.specialize(kernel_dir) if kernel_dir is not None else p
