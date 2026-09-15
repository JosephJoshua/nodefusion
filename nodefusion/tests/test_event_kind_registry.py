
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nodefusion.host import analyze as A
from nodefusion.model import kinds as K
from nodefusion.model import manifest as M

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "manifests"
ANALYZE_PY = ROOT / "host/analyze.py"


def _manifests():
    mans = M.load_dir(DRAFT)
    return mans.items() if isinstance(mans, dict) else [(m.name, m) for m in mans]



def test_every_registered_kind_follows_the_naming_convention():
    pat = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    bad = sorted(k for k in K.KINDS if not pat.match(k))
    assert not bad, f"这些类别不合命名约定：{bad}"


def test_the_generated_prefix_is_not_in_the_table():
    leaked = sorted(k for k in K.KINDS
                    if any(k.startswith(p) for p in K.GENERATED_PREFIXES))
    assert not leaked, f"生成式前缀混进了正本表：{leaked}"
    assert K.is_registered("func.anything_at_all")
    assert not K.is_registered("nope.not_a_kind")



def test_every_kind_any_manifest_uses_is_registered():
    for name, m in _manifests():
        for fn, spec in (m.events or {}).items():
            assert K.is_registered(spec.kind), (
                f"{name} 的 {fn} 用了没登记的类别 {spec.kind!r}")


def test_an_unregistered_kind_is_refused_at_load():
    src = (DRAFT / "arceos.toml").read_text(encoding="utf-8")
    assert '"sched.switch"' in src, "样本变了，这条测试该跟着改"

    bad = src.replace('"sched.switch"', '"sched.contextswitch"', 1)
    tmp = ROOT / "tests" / "_tmp_kind_reject"
    tmp.mkdir(exist_ok=True)
    f = tmp / "arceos.toml"
    try:
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(K.UnknownKindError) as e:
            M.load(f)
        assert "sched.contextswitch" in str(e.value)
        assert "sched.switch" in str(e.value), str(e.value)

        f.write_text(src, encoding="utf-8")
        M.load(f)
    finally:
        f.unlink(missing_ok=True)
        tmp.rmdir()



_NOT_KINDS = {"nodefusion", "os", "self", "np", "json", "qemu", "nf",
              "console", "manifest", "kernel_layout", "watchlist", "trace",
              "mod", "events", "app", "libnf", "chrome", "wsl", "linker"}
_NOT_KIND_SUFFIX = (".json", ".log", ".rs", ".h", ".nfb", ".py", ".toml",
                    ".md", ".c", ".s", ".css", ".js", ".exe", ".so", ".dylib")


def test_every_kind_hardcoded_in_analyze_is_registered():
    src = ANALYZE_PY.read_text(encoding="utf-8")
    lit = set(re.findall(r'"([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)"', src))
    cand = {k for k in lit
            if k.split(".")[0] not in _NOT_KINDS
            and not k.endswith(_NOT_KIND_SUFFIX)}

    assert {k for k in cand if K.is_registered(k)}, (
        "一个已登记的类别字面量都没扫到，正则该跟着改了")

    bad = sorted(k for k in cand if not K.is_registered(k))
    assert not bad, (
        f"analyze.py 里写着这些类别，但正本表里没有：{bad}。"
        f"要么补进 KINDS，要么它们不是类别（那就加进 _NOT_KINDS）。")


def test_the_metric_table_only_asks_for_registered_kinds():
    for metric, kind in A.Analysis._METRIC_KINDS.items():
        assert K.is_registered(kind), f"指标 {metric} 问的 {kind!r} 没登记"



_TOTAL_GROUPS = 9


def test_unresolved_groups_are_completely_written():
    total = len(K.UNRESOLVED + K.RESOLVED_DISTINCT + K.RESOLVED_MERGED
                + K.RESOLVED_PENDING_CHANGE + K.RESOLVED_TOLERATED)
    assert total >= _TOTAL_GROUPS, (
        f"裁决表里只剩 {total} 组，少于 {_TOTAL_GROUPS} —— 有组被删掉了。"
        f"裁决是把组从 UNRESOLVED 搬进 RESOLVED_*，搬家不会让总数变小")
    for g in K.UNRESOLVED:
        assert g["group"], g
        assert len(g["kinds"]) >= 2, f"一组至少两个词才谈得上同义：{g}"
        assert g["why"] and g["needs"], f"{g['group']} 没写全：{g}"


def test_unresolved_groups_name_only_registered_kinds():
    for g in (K.UNRESOLVED + K.RESOLVED_DISTINCT
              + K.RESOLVED_PENDING_CHANGE + K.RESOLVED_TOLERATED):
        for k in g["kinds"]:
            assert K.is_registered(k), (
                f"{g.get('group', g['kinds'])} 提到 {k!r}，但它不在表里 —— "
                f"这组该更新或者删掉了")
    for g in K.RESOLVED_MERGED:
        for k in g["kinds"]:
            assert K.is_registered(k) or k in K.RETIRED, (
                f"{g['group']} 提到 {k!r}，它既不在 KINDS 里也不在 RETIRED 里 —— "
                f"并掉的词得在 RETIRED 里说明并到哪儿去了")


def test_declined_words_are_still_absent():
    assert K.RESOLVED_DECLINED, (
        "这张表空了 —— 空表本身不是问题，但这条测试就白跑了")
    for g in K.RESOLVED_DECLINED:
        assert g["kinds"], f"{g['group']} 没说拒的是哪个词"
        for k in g["kinds"]:
            assert not K.is_registered(k), (
                f"{g['group']} 说 {k!r} 被拒了，可它现在**在 KINDS 里**。"
                f"要么这组过时了该搬走，要么那个词是误加的 —— 两种都得处理，"
                f"不能让「决定不加」和事实对不上")
            assert k not in K.RETIRED, (
                f"{g['group']} 提到 {k!r}，它却在 RETIRED 里。RETIRED 的意思是"
                f"「用过、并掉了」，而这张表的意思是「从来没加过」—— "
                f"同一个词不可能两者都是")
        for field in ("proposed_for", "measured", "why", "decided"):
            assert g.get(field), f"{g['group']} 缺 {field!r}"
        assert "重新开" in str(g["decided"]), (
            f"{g['group']} 的 decided 里没写重新开的触发条件 —— "
            f"没有条件的「决定不加」和「拖着」分不出来")


def test_merged_groups_say_what_they_merged_into_and_what_retired():
    assert K.RESOLVED_MERGED, "这张表空了 —— 空表本身不是问题，但这条测试就白跑了"
    for g in K.RESOLVED_MERGED:
        into = g.get("merged_into")
        assert into and K.is_registered(into), (
            f"{g['group']}: merged_into={into!r} 不在 KINDS 里")
        retired = g.get("retired") or ()
        assert retired, f"{g['group']} 没写 retired —— 并了却没有词退休？"
        for k in retired:
            assert k in K.RETIRED, (
                f"{g['group']} 说 {k!r} 退休了，但 kinds.RETIRED 里没有这条")
            assert k not in K.KINDS, f"{k!r} 退休了却还留在 KINDS 里"
        d = g.get("decided") or ""
        assert d, f"{g['group']} 没写 decided"
        assert "触发条件" in d, (
            f"{g['group']} 的 decided 没写重新开的触发条件 —— "
            f"没有触发条件的『定了』跟『不想再想』长得一样")


def test_the_divergences_the_table_describes_are_still_real():
    by_kernel = {name: {s.kind for s in (m.events or {}).values()}
                 for name, m in _manifests()}

    for k in ("arceos", "rcore", "xv6"):
        assert "kernel.panic" in by_kernel[k], (
            f"{k} 的 panic 入口不叫 kernel.panic 了。这个词有四个消费者"
            f"（app.js 的标记/详情、video.py 的关键帧/崩溃判定），换名字"
            f"等于让那个内核崩溃时全程静默 —— 见 RESOLVED_MERGED 的 A 组")
    assert not any("panic.enter" in v for v in by_kernel.values()), (
        "panic.enter 又回来了 —— 它在 kinds.RETIRED 里，已经并进 kernel.panic")

    ar = {fn: s.kind for fn, s in
          dict(_manifests())["arceos"].events.items()}
    rc = {fn: s.kind for fn, s in
          dict(_manifests())["rcore"].events.items()}

    for name, ev in (("arceos", ar), ("rcore", rc)):
        trampoline = [k for fn, k in ev.items()
                      if fn.split("::")[-1] == "__rust_alloc_error_handler"]
        assert trampoline == ["panic.alloc_handler"], (
            f"{name} 的 __rust_alloc_error_handler 映成了 {trampoline}，"
            f"不是 panic.alloc_handler —— 那是 B 组裁决选定的跨内核对照点，"
            f"见 kinds.RESOLVED_DISTINCT 的 B 组")

    a_he = [k for fn, k in ar.items() if fn.endswith("handle_alloc_error")]
    r_he = [k for fn, k in rc.items() if fn.endswith("handle_alloc_error")]
    assert a_he == ["panic.alloc"], a_he
    assert r_he == ["kernel.alloc_error"], r_he

    assert "vm.map" in by_kernel["arceos"], "ArceOS 的区域级映射掉了"
    assert "vm.map" in by_kernel["xv6"], (
        "xv6 的 mappages 不在 vm.map 名下了 —— #70 被改回去了？"
        "它是区域级的（收 size、按页循环），跟 ArceOS 同档")
    assert "pagetable.map" in by_kernel["rcore"], (
        "rCore 的 PageTable::map 不在 pagetable.map 名下了 —— "
        "那个词现在专指「写一个 PTE」，只有它是")
    assert "pagetable.map" not in by_kernel["xv6"], (
        "xv6 又有 pagetable.map 了。它没有单 PTE 那一档的观察点，"
        "有就说明区域级的又被映回去了 —— #70 数出来的那对不可比的数会回来")


def test_the_page_fault_pair_is_not_quietly_merged():
    assert "trap.page_fault" in K.KINDS
    assert "trap.page_fault_handler" in K.KINDS
    assert A.Analysis._METRIC_KINDS.get("page_faults") in (None, "trap.page_fault")

    src = ANALYZE_PY.read_text(encoding="utf-8")
    assert 'counts.get("trap.page_fault"' in src, (
        "page_faults 不再数 trap.page_fault 了，C 组的说明该重写")



SPEC = ROOT / "spec/event-stream.md"


def test_the_spec_points_at_the_registry_as_the_source():
    text = SPEC.read_text(encoding="utf-8")
    i = text.index("### 3.3")
    head = text[i:i + 1200]
    assert "kinds.py" in head, "3.3 没指向正本"
    assert "举例" in head or "不全" in head, "3.3 没说明自己不是全集"

    for name in ("UNRESOLVED", "RESOLVED_DISTINCT", "RESOLVED_MERGED",
                 "RESOLVED_TOLERATED", "RESOLVED_PENDING_CHANGE",
                 "RESOLVED_DECLINED",
                 "UNDECIDABLE_FROM_TRACES", "RETIRED"):
        assert name in head, (
            f"3.3 没提 {name} —— 读的人在别的表里找不到已经裁决过的那几组，"
            f"会重新开一遍")

    tables = {n for n in dir(K)
              if n.isupper() and (n.startswith(("UNRESOLVED", "RESOLVED_",
                                                "UNDECIDABLE_"))
                                  or n == "RETIRED")}
    missing = sorted(n for n in tables if n not in head)
    assert not missing, (
        f"kinds.py 里有这些裁决表，规范 3.3 一张都没提：{missing}。"
        f"新开一张表就得在那张表格里加一行，否则读的人不知道它存在。")


def test_every_kind_the_spec_names_is_registered():
    text = SPEC.read_text(encoding="utf-8")
    i, j = text.index("### 3.3"), text.index("### 3.4")
    named = {k for k in
             re.findall(r"`([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`", text[i:j])
             if not k.endswith(_NOT_KIND_SUFFIX)}
    assert named, "3.3 里一个类别都没解出来，正则该跟着改了"
    bad = sorted(k for k in named if not K.is_registered(k))
    assert not bad, f"规范 3.3 提到了没登记的类别：{bad}"


def test_tolerated_groups_say_what_would_reopen_them():
    for g in K.RESOLVED_TOLERATED:
        assert g["group"] and g["kinds"], g
        d = g.get("decided")
        assert d, f"{g['group']} 没写 decided —— 那这组凭什么算裁决完了"
        assert "触发条件" in d, (
            f"{g['group']} 的 decided 没写重新开的触发条件。"
            f"没有触发条件的「容忍」就是「拖着」")
        assert "量" in d or "measured" in d.lower(), (
            f"{g['group']} 的 decided 没提测量 —— 不改也得有依据：{d[:80]}")


def test_the_tolerated_decision_is_not_the_retracted_one():
    g = next((x for x in K.RESOLVED_TOLERATED
              if "proc.spawn" in x["kinds"]), None)
    assert g, "G 组不在 RESOLVED_TOLERATED 里"
    d = g["decided"]
    assert "sched." in d and "撤回" in d, (
        f"decided 里没写「撤回挪到 sched.* 的提法」：{d[:120]}")
    assert "入口" in d, f"decided 里没说清错在入口打点：{d[:120]}"


def test_resolved_distinct_records_why_they_are_not_synonyms():
    assert K.RESOLVED_DISTINCT
    for g in K.RESOLVED_DISTINCT:
        assert g["why"], g
    pairs = {tuple(sorted(g["kinds"])) for g in K.RESOLVED_DISTINCT}
    assert ("sched.yield", "sched.yield_to_scheduler") in pairs
    assert ("heap.alloc", "phys.alloc") in pairs


XV6_VM_C = ROOT.parent / "xv6-riscv_teacher/kernel/vm.c"


def test_xv6_mappages_really_is_region_level():
    if not XV6_VM_C.is_file():
        pytest.skip("这台机器上没有 xv6 源码")
    src = XV6_VM_C.read_text(encoding="utf-8")
    i = src.index("int mappages(")
    body = src[i:src.index("\n}", i)]
    assert "uint64 size" in body.split("\n")[0], body.split("\n")[0]
    assert "PGSIZE" in body, "mappages 里没有按页步进，粒度结论该重看"
    assert "a += PGSIZE" in body.replace(" ", " "), body


XV6_PROC_C = ROOT.parent / "xv6-riscv_teacher/kernel/proc.c"


def test_this_xv6_never_loads_an_image_outside_exec():
    if not XV6_PROC_C.is_file():
        pytest.skip("这台机器上没有 xv6 源码")
    kern = XV6_PROC_C.parent
    hits = [p.name for p in kern.glob("*.c")
            if "uvmfirst" in p.read_text(encoding="utf-8", errors="replace")
            or "initcode" in p.read_text(encoding="utf-8", errors="replace")]
    assert not hits, (
        f"这版 xv6 又有 initcode/uvmfirst 了（{hits}）—— G 组那句"
        f"「映像只经由 exec 进来」要重写")

    src = XV6_PROC_C.read_text(encoding="utf-8")
    i = src.index("void userinit(void)")
    body = src[i:src.index("\n}", i)]
    assert "allocproc()" in body, body
    for bad in ("uvmfirst", "exec", "elf"):
        assert bad not in body, f"userinit 里出现了 {bad!r}：{body}"


def test_the_pagetable_granularity_finding_is_recorded_with_its_measurements():
    g = next((x for x in K.RESOLVED_DISTINCT
              if "pagetable.map" in x["kinds"]), None)
    assert g, "E 组不见了"
    ks = {row[0] for row in g["measured"]}
    assert ks == {"xv6", "arceos", "rcore"}, ks
    gran = {row[0]: row[3] for row in g["measured"]}
    assert gran["xv6"] == gran["arceos"] == "区域"
    assert gran["rcore"] == "单页"
    assert g["consequence"], "E 组没写后果"
    assert g.get("changed"), (
        "E 组没写 `changed` —— 它已经改完了（#70），得记下改了什么、"
        "基准的哪个数换了名字")
    for n in ("76583", "32318", "vm_maps"):
        assert n in str(g["changed"]), f"`changed` 里没提到 {n}"
    assert not any("pagetable.map" in x["kinds"]
                   for x in K.RESOLVED_PENDING_CHANGE), (
        "E 组还留在 RESOLVED_PENDING_CHANGE 里")
    assert not any("vm.map" in x["kinds"] for x in K.UNRESOLVED)


XV6_PROC_C = ROOT.parent / "xv6-riscv_teacher/kernel/proc.c"


def test_xv6_allocproc_really_builds_the_pagetable_and_trapframe():
    if not XV6_PROC_C.is_file():
        pytest.skip("这台机器上没有 xv6 源码")
    src = XV6_PROC_C.read_text(encoding="utf-8")
    i = src.index("allocproc(void)")
    body = src[i:src.index("\n}", i)]
    assert "p->trapframe" in body and "kalloc()" in body, body
    assert "proc_pagetable(p)" in body, body
    assert "elf" not in body.lower(), (
        "allocproc 里出现了 elf —— 它现在也装映像了？G 组结论得重看")


def test_the_task_creation_finding_is_recorded_with_its_measurements():
    g = next((x for x in K.RESOLVED_TOLERATED
              if "proc.create" in x["kinds"]), None)
    assert g, "G 组不见了"
    ks = {row[0] for row in g["measured"]}
    assert ks == {"xv6", "arceos", "rcore"}, ks
    stage = {row[0]: row[3] for row in g["measured"]}
    assert len(set(stage.values())) == 3, stage
    assert "已造好" in stage["arceos"] and "运行队列" in stage["arceos"], (
        stage["arceos"])
    assert g["consequence"] and g["decided"]
    assert not any("proc.create" in x["kinds"] for x in K.UNRESOLVED)
    assert not any("proc.create" in x["kinds"]
                   for x in K.RESOLVED_PENDING_CHANGE), (
        "G 组还留在 RESOLVED_PENDING_CHANGE 里 —— 决定是不改，那张表说的是"
        "「该改，还没改」")


def test_the_task_creation_phase_offset_is_recorded():
    g = next((x for x in K.RESOLVED_TOLERATED
              if "proc.create" in x["kinds"]), None)
    assert g, "G 组不见了"
    at = {row[0]: row[2] for row in g["at_entry"]}
    assert set(at) == {"xv6", "rcore", "arceos"}, sorted(at)
    assert "还没造出来" in at["xv6"] and "还没造出来" in at["rcore"], at
    assert "已经造好了" in at["arceos"], at["arceos"]
    assert "次数仍然可比" in g["consequence"], g["consequence"]


def test_arceos_maps_the_spawn_call_not_the_constructor():
    ar = dict(_manifests())["arceos"].events
    spawn = [fn for fn in ar if fn.endswith("spawn_task")]
    assert spawn, f"arceos 不再映射 spawn_task 了，G 组该重看：{sorted(ar)}"
    assert {ar[fn].kind for fn in spawn} == {"proc.create"}, (
        [(fn, ar[fn].kind) for fn in spawn])
    made = [fn for fn in ar if "TaskInner::new" in fn or fn.endswith("new")]
    assert not made, (
        f"arceos 现在也映射构造函数了（{made}）—— G 组的相位结论要重写："
        f"那样它就跟 xv6、rCore 一样在任务诞生**之前**打点了")


XV6_TRAP_C = ROOT.parent / "xv6-riscv_teacher/kernel/trap.c"


def test_xv6_kerneltrap_is_a_normal_path_that_returns():
    if not XV6_TRAP_C.is_file():
        pytest.skip("这台机器上没有 xv6 源码")
    src = XV6_TRAP_C.read_text(encoding="utf-8")
    i = src.index("kerneltrap()")
    body = src[i:src.index("\n}", i)]
    assert "devintr()" in body, "kerneltrap 不再认设备中断了？"
    assert "w_sepc(sepc)" in body and "w_sstatus(sstatus)" in body, body
    assert "devintr()) == 0" in body, body


def test_the_kernel_trap_finding_is_recorded_with_its_measurements():
    g = next((x for x in K.RESOLVED_DISTINCT
              if "trap.kernel" in x["kinds"]), None)
    assert g, "D 组不在 RESOLVED_DISTINCT 里"
    rows = {r[0]: r for r in g["measured"]}
    assert set(rows) == {"xv6", "rcore"}, sorted(rows)
    assert rows["xv6"][3] == "常规路径" and rows["xv6"][4] == 274, rows["xv6"]
    assert rows["rcore"][3] == "致命路径" and rows["rcore"][4] == 0, rows["rcore"]
    assert g.get("why_zero") and "设计" in g["why_zero"], g.get("why_zero")
    assert not any("trap.kernel" in x["kinds"] for x in K.UNRESOLVED)


def test_the_hardware_decoded_outer_kinds_never_depend_on_a_manifest():
    for name, m in _manifests():
        declared = {s.kind for s in (m.events or {}).values()}
        clash = declared & {"trap.page_fault", "interrupt.timer"}
        assert not clash, (
            f"{name}.toml 映了 {sorted(clash)} —— 这两个本来是 CSR 解出来的、"
            f"不依赖 manifest 的外层词。C/F 组的形状分析要重写")


def test_no_kind_is_both_unresolved_and_resolved():
    un = {k for g in K.UNRESOLVED for k in g["kinds"]}
    di = {k for g in K.RESOLVED_DISTINCT for k in g["kinds"]}
    both = sorted(un & di)
    assert not both, f"这些词两张名单上都有，自相矛盾：{both}"
