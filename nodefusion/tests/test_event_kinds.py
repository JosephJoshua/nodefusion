
import sys
from pathlib import Path

import pytest


def _archived_xv6():
    from pathlib import Path as _P
    from nodefusion.host.kernels import archived_elf
    return archived_elf("xv6") or _P("/nonexistent/xv6.elf")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.host.analyze import (FUNC_EVENT_ALIASES,            # noqa: E402
                                     FUNC_EVENTS, HARDCODED_KERNEL,
                                     classify_event_kind, event_shape,
                                     possible_event_kinds)
from nodefusion.model import manifest as M                           # noqa: E402

DRAFTS = Path(__file__).resolve().parents[1] / "manifests"


def _load(tmp_path: Path, body: str) -> M.Manifest:
    p = tmp_path / "t.toml"
    p.write_text('[kernel]\nname = "t"\n\n' + body, encoding="utf-8")
    return M.load(p)



def test_a_bare_string_means_just_the_kind(tmp_path):
    m = _load(tmp_path, '[event]\nkalloc = "phys.alloc"\n')
    assert m.events["kalloc"].kind == "phys.alloc"
    assert m.events["kalloc"].args == []
    assert m.events["kalloc"].resource == ""


def test_a_table_can_narrow_the_resource_and_rename_the_args(tmp_path):
    m = _load(tmp_path, '[event]\n'
              'bread = { kind = "bcache.read", resource = "bcache" }\n'
              'panic = { kind = "kernel.panic", args = ["msg"] }\n')
    assert m.events["bread"].kind == "bcache.read"
    assert m.events["bread"].resource == "bcache"
    assert m.events["bread"].args == []
    assert m.events["panic"].args == ["msg"]
    assert m.events["panic"].resource == ""


def test_a_bit_classifier_is_validated_and_loaded(tmp_path):
    m = _load(tmp_path, '[event]\nclone = { kind = "proc.fork", '
              'args = ["return_slot", "uctx", "flags"], '
              'classify = { arg = "flags", mask = 65536, '
              'set = "thread.create" } }\n')
    assert m.events["clone"].classify == {
        "arg": "flags", "mask": 0x10000, "set": "thread.create"}


@pytest.mark.parametrize("classifier", [
    '{ arg = "flags", mask = 0, set = "thread.create" }',
    '{ arg = "missing", mask = 65536, set = "thread.create" }',
    '{ arg = "flags", mask = 65536, set = "proc.fork" }',
])
def test_a_bad_bit_classifier_is_rejected(tmp_path, classifier):
    with pytest.raises(M.ManifestError):
        _load(tmp_path, '[event]\nclone = { kind = "proc.fork", '
              'args = ["return_slot", "uctx", "flags"], '
              f'classify = {classifier} }}\n')


def test_clone_thread_bit_selects_without_defaulting_unknown_data():
    entry = {
        "params": ["return_slot", "uctx", "flags"],
        "classify": {"arg": "flags", "mask": 0x10000,
                     "set": "thread.create"},
    }
    assert classify_event_kind("proc.fork", "sys_clone", entry,
                               [0, 0, 17])[0] == "proc.fork"
    assert classify_event_kind("proc.fork", "sys_clone", entry,
                               [0, 0, 0x10000])[0] == "thread.create"
    kind, unknown = classify_event_kind(
        "proc.fork", "sys_clone", entry, [0, 0])
    assert kind == "func.sys_clone"
    assert unknown == "event_kind"
    assert possible_event_kinds("proc.fork", "sys_clone", entry) == {
        "proc.fork", "thread.create"}


def test_a_table_without_a_kind_is_an_error(tmp_path):
    with pytest.raises(M.ManifestError, match=r"缺 kind"):
        _load(tmp_path, '[event]\nbread = { resource = "bcache" }\n')


def test_something_that_is_neither_a_string_nor_a_table_is_an_error(tmp_path):
    with pytest.raises(M.ManifestError):
        _load(tmp_path, '[event]\nsleep = ["chan", "lock"]\n')


def test_an_unknown_key_is_an_error_not_a_shrug(tmp_path):
    with pytest.raises(M.ManifestError, match=r"arg"):
        _load(tmp_path, '[event]\npanic = { kind = "k", arg = ["msg"] }\n')


def test_a_manifest_without_the_section_still_loads(tmp_path):
    assert _load(tmp_path, "").events == {}



def _shape(name, *, kind="", resource="kernel", params=(), kernel):
    entry = {"resource": resource, "params": list(params)}
    if kind:
        entry["kind"] = kind
    return event_shape(name, entry, kernel_kind=kernel)


def test_a_kind_from_the_manifest_beats_the_hardcoded_table():
    assert "exec" in FUNC_EVENTS
    kind, _, _ = _shape("kexec", kind="proc.exec.manifest",
                        kernel=HARDCODED_KERNEL)
    assert kind == "proc.exec.manifest"


def test_a_non_xv6_kernel_gets_its_own_kinds():
    kind, _, _ = _shape("exec", kind="proc.exec", kernel="rcore")
    assert kind == "proc.exec"


def test_without_a_kind_a_non_xv6_kernel_still_falls_back_plainly():
    kind, _, _ = _shape("exec", kernel="rcore")
    assert kind == "func.exec"
    assert kind != FUNC_EVENTS["exec"][0]


def test_old_bundles_have_no_kind_so_they_still_read_the_table():
    assert _shape("kalloc", kernel=HARDCODED_KERNEL)[0] == \
        FUNC_EVENTS["kalloc"][0]



def test_xv6_manifest_covers_every_table_entry_the_rules_can_select():
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist
    elf_path = _archived_xv6()
    if not elf_path.exists():
        pytest.skip("没有 xv6 内核 ELF")
    wl, _, _ = select_watchlist(Elf64(str(elf_path)), elf_path, kind="xv6")
    picked = {e.name for e in wl.entries}
    ev = M.load(DRAFTS / "xv6.toml").events
    missing = sorted((set(FUNC_EVENTS) & picked) - set(ev))
    assert not missing, f"这些还留在表里没搬过来：{missing}"


def test_xv6_kinds_are_the_same_strings_the_table_had():
    ev = M.load(DRAFTS / "xv6.toml").events
    changed = {n: (FUNC_EVENTS[n][0], s.kind)
               for n, s in ev.items()
               if n in FUNC_EVENTS and FUNC_EVENTS[n][0] != s.kind}
    assert not changed, f"kind 变了：{changed}"


def test_the_selected_points_carry_the_kind_and_the_narrowed_resource():
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist
    elf_path = _archived_xv6()
    if not elf_path.exists():
        pytest.skip("没有 xv6 内核 ELF")
    wl, _, _ = select_watchlist(Elf64(str(elf_path)), elf_path, kind="xv6")
    by = {e.name: e for e in wl.entries}
    assert by["kalloc"].kind == "phys.alloc"
    assert by["kfree"].kind == "phys.free"
    assert by["bread"].resource == "bcache"
    assert by["panic"].params == ["msg"]
    assert by["swtch"].params == ["old_ctx", "new_ctx"]
    assert by["uvmalloc"].params[-1] == "xperm"
    plain = [e for e in wl.entries if not e.kind]
    assert plain, "全都有 kind 的话这条不变量就是空的"


def test_a_key_that_matches_nothing_gets_reported():
    from nodefusion.host import watchlist as W
    from nodefusion.host.nfelf import Elf64
    from nodefusion.model.dwarfsrc import DwarfSource
    elf_path = _archived_xv6()
    if not elf_path.exists():
        pytest.skip("没有 xv6 内核 ELF")
    man = M.load(DRAFTS / "xv6.toml")
    wl = W.build_from_manifest(
        Elf64(str(elf_path)), DwarfSource(str(elf_path)), man.watches,
        events={"kalloc": M.EventSpec(kind="phys.alloc"),
                "kalloc_typo": M.EventSpec(kind="phys.alloc")})
    dead = [m for m in wl.missing if "[event]" in m]
    assert len(dead) == 1 and "kalloc_typo" in dead[0]


def test_a_full_path_key_works_and_beats_the_short_name():
    from nodefusion.host import watchlist as W
    from nodefusion.host.nfelf import Elf64
    from nodefusion.model.dwarfsrc import DwarfSource
    import json
    run = Path(__file__).resolve().parents[1] / "runs" / "rcore-ch6-fs"
    if not run.exists():
        pytest.skip("没有 rCore 的 run 目录")
    elf_path = Path(json.loads((run / "manifest.json").read_text())["kernel_elf"])
    if not elf_path.exists():
        pytest.skip(f"bundle 指的 rCore ELF 不在：{elf_path}")
    man = M.load(DRAFTS / "rcore.toml")
    full = "os::mm::page_table::PageTable::map"
    wl = W.build_from_manifest(
        Elf64(str(elf_path)), DwarfSource(str(elf_path)), man.watches,
        events={full: M.EventSpec(kind="pagetable.map"),
                "map": M.EventSpec(kind="被短名抢走了")})
    hit = [e for e in wl.entries if e.symbol == full]
    assert hit, "这个 ELF 里没有这个符号，测试前提不成立"
    assert hit[0].kind == "pagetable.map"


def _archived_builds(kind: str) -> list[Path]:
    from nodefusion.host import kernels as K
    seen: set[str] = set()
    out: list[Path] = []
    for d in (K.ARCHIVE, K.BUILDS):
        if not d.is_dir():
            continue
        for p in sorted(d.glob(f"{kind}-*.elf")):
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                out.append(p)
    return out


def test_no_manifest_ships_a_dead_event_key():
    import re
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist
    pat = re.compile(r"\[event\] '([^']+)'")
    checked = 0
    for kind in sorted(M.load_dir(DRAFTS)):
        elfs = _archived_builds(kind)
        if not elfs:
            continue
        dead: set[str] | None = None
        for elf in elfs:
            wl, _, _ = select_watchlist(Elf64(str(elf)), elf, kind=kind)
            here = {m.group(1) for x in wl.missing if (m := pat.search(x))}
            dead = here if dead is None else (dead & here)
            if not dead:
                break
        # Integration patches intentionally add manifest keys before archived
        # course ELFs can contain them.  They are not typos: the shipped patch
        # is the producer, and its own apply/build test covers the symbol.
        integration_text = "\n".join(
            p.read_text(encoding="utf-8")
            for p in (DRAFTS.parent / "integrations").glob("*.patch"))
        unexplained = {name for name in (dead or set())
                       if name.rsplit("::", 1)[-1] not in integration_text}
        assert not unexplained, (
            f"{kind}：这些 `[event]` 键在手边 {len(elfs)} 份构建里**全都**没匹配上，"
            f"也没有由集成补丁提供，多半是键写错了（短名/全路径都试过了）："
            f"{sorted(unexplained)}")
        checked += 1
    if not checked:
        pytest.skip("一个内核 ELF 都没有")


def test_rcore_really_gets_kinds_of_its_own():
    import json
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist
    run = Path(__file__).resolve().parents[1] / "runs" / "rcore-ch6-fs"
    if not run.exists():
        pytest.skip("没有 rCore 的 run 目录")
    elf = Path(json.loads((run / "manifest.json").read_text())["kernel_elf"])
    if not elf.exists():
        pytest.skip(f"bundle 指的 rCore ELF 不在：{elf}")
    wl, _, _ = select_watchlist(Elf64(str(elf)), elf, kind="rcore")
    kinds = {e.name: e.kind for e in wl.entries if e.kind}
    assert kinds.get("__switch") == "sched.switch"
    assert kinds.get("panic") == "kernel.panic"
    assert kinds.get("map") == "pagetable.map"
    xv6 = M.load(DRAFTS / "xv6.toml").events
    shared = {s.kind for s in xv6.values()} & set(kinds.values())
    assert shared, "两个内核一个共有的事件类型都没有，那就没法比较"


def test_every_resource_override_actually_narrows_something():
    from nodefusion.host import watchlist as W
    from nodefusion.host.nfelf import Elf64
    from nodefusion.model.dwarfsrc import DwarfSource
    elf_path = _archived_xv6()
    if not elf_path.exists():
        pytest.skip("没有 xv6 内核 ELF")
    man = M.load(DRAFTS / "xv6.toml")
    raw = W.build_from_manifest(Elf64(str(elf_path)),
                                DwarfSource(str(elf_path)),
                                man.watches, events={})
    rule = {e.name: e.resource for e in raw.entries}
    noop = sorted(n for n, s in man.events.items()
                  if s.resource and rule.get(n) == s.resource)
    assert not noop, f"这些 resource 跟规则给的一样，白写：{noop}"



def test_the_code_table_and_the_xv6_manifest_still_agree():
    man = M.load(DRAFTS / "xv6.toml")
    both = sorted(set(FUNC_EVENTS) & set(man.events))

    assert len(both) >= 60, (
        f"重叠只剩 {len(both)} 条 —— 是哪张表被清空了，还是这条测试该退休了？")

    bad: list[str] = []
    for fn in both:
        kind, resource, argnames = FUNC_EVENTS[fn]
        spec = man.events[fn]
        if kind != spec.kind:
            bad.append(f"{fn}: kind 代码={kind!r} manifest={spec.kind!r}")
        if spec.resource and resource != spec.resource:
            bad.append(f"{fn}: resource 代码={resource!r} "
                       f"manifest={spec.resource!r}")
        if spec.args and list(argnames) != list(spec.args):
            bad.append(f"{fn}: args 代码={argnames} manifest={list(spec.args)}")

    assert not bad, (
        "同一份映射的两份拷贝对不上了。两处都得改，只改一处的话老录制和"
        "新录制解出来的类别不一样，而且不报错：\n  " + "\n  ".join(bad))


def test_the_manifest_covers_every_kind_the_code_table_knows():
    man = M.load(DRAFTS / "xv6.toml")

    assert len(FUNC_EVENTS) >= 60, (
        f"FUNC_EVENTS 只剩 {len(FUNC_EVENTS)} 条 —— 是被清空了，还是这条"
        f"测试该退休了？生成那步（_func_events_from_manifest）读不到 "
        f"manifest 时返回的就是空表")
    assert len(man.events) >= 60, (
        f"[event] 只剩 {len(man.events)} 条 —— 同上")

    covered = set(man.events) | {FUNC_EVENT_ALIASES.get(sym, sym)
                                 for sym in man.events}

    missing = sorted(set(FUNC_EVENTS) - covered)
    assert not missing, (
        "这些函数代码里有类别、manifest 换算过别名之后仍然没有。真把 "
        "FUNC_EVENTS 删了，它们会退成 func.*，而且不报错：\n  "
        + "\n  ".join(f"{fn} -> {FUNC_EVENTS[fn][0]}" for fn in missing))

    dropped = sorted(covered - set(FUNC_EVENTS))
    assert not dropped, (
        "manifest 里有这些键，生成出来的表里却没有 —— 生成那步漏了：\n  "
        + "\n  ".join(dropped))


def test_the_fallback_table_is_built_without_reading_the_kernel_elf():
    import nodefusion.model.dwarfsrc as D
    from nodefusion.host import analyze as A

    def boom(*a, **k):
        raise AssertionError("生成兜底表时不该读内核 ELF")

    orig = D.DwarfSource.__init__
    D.DwarfSource.__init__ = boom
    try:
        built = A._func_events_from_manifest()
    finally:
        D.DwarfSource.__init__ = orig

    assert len(built) >= 60, f"没读 ELF 就只生成出 {len(built)} 条"
    assert built == FUNC_EVENTS, "跟导入时生成的那份不一致"


def test_the_alias_map_is_not_a_second_hand_written_copy():
    assert FUNC_EVENT_ALIASES, "别名表空了，上一条的换算就退化成裸差集"
    bad = [f"{sym} -> {name}（值不在 FUNC_EVENTS 里）"
           for sym, name in FUNC_EVENT_ALIASES.items()
           if name not in FUNC_EVENTS]
    assert not bad, "别名表指向了不存在的条目：\n  " + "\n  ".join(bad)
