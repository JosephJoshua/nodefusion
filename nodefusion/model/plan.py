
from __future__ import annotations

from dataclasses import dataclass, field

from .dwarfsrc import DwarfSource
from .manifest import SourceSpec
from .readers.registry import container_of as _container_of
from .readers.registry import inner_type as _inner_type
from .readers.registry import is_refcounted_shell as _is_refcounted
from .readers.registry import via_spec as _via_spec
from .resolve import (btree_opts, btree_value_die, elem_die, list_elem_die,
                      list_opts, resolve_path, vec_opts)
from .resolve import _walk_fields
from .resolve import refcounted_data_offset as _refcount_data_off
from .resolve import refcounted_strong_offset as _refcount_strong_off
from .resolve import refcounted_payload_die as _refcount_payload
from .symbols import Sym as _Sym


def _base_name(tn: str | None) -> str:
    if not tn:
        return ""
    return tn.split("<", 1)[0].rsplit("::", 1)[-1].lower()


def _container_payload(dw: DwarfSource, off: int | None,
                       via: object) -> tuple[int | None, int]:
    want = _container_of(via)
    if want is None or off is None:
        return None, 0
    cur, delta = off, 0
    for _ in range(8):
        if _base_name(dw.type_name(cur)) == want:
            return cur, delta
        st = dw.struct_at(cur)
        if st is None or not st.field_types:
            return None, 0
        pick: str | None = None
        if len(st.field_types) == 1:
            pick = next(iter(st.field_types))
        else:
            pick = next((c for c in ("data", "value")
                         if c in st.field_types), None)
        nxt = st.field_types.get(pick) if pick else None
        if nxt is None or nxt == cur:
            return None, 0
        delta += st.fields.get(pick, 0)
        cur = nxt
    return None, 0



@dataclass(frozen=True)
class Op:

    kind: str
    args: dict = field(default_factory=dict)

    def __str__(self) -> str:
        a = "，".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.kind}({a})"


@dataclass
class Plan:

    entity: str
    ops: list[Op] = field(default_factory=list)
    compiled: bool = True
    reason: str | None = None
    trace: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.compiled


_STEPS = frozenset((
    "static", "field", "deref", "unwrap", "descend_to",
    "iter", "walk", "percpu", "from", "index",
))

_STEP_ARGS = frozenset(("via", "key", "children", "link", "next", "terminator",
                        "layout"))


def _sole_field_type(dw: DwarfSource, outer: str | None) -> str | None:
    if not outer:
        return None
    st = dw.find(outer)
    if st is None:
        return None
    carriers = [t for t in st.field_types.values() if dw.size_of(t) != 0]
    if len(carriers) != 1:
        return None
    return dw.type_name(carriers[0])


def _descend_offset(dw: DwarfSource, outer: str | None,
                    target: str) -> tuple[int | None, str]:
    if not outer:
        return None, ("不知道当前是什么类型 —— descend_to 得先知道外层类型才能"
                      "在里面找。前面某一步没能定下类型（比如静态量没有 DWARF "
                      "类型信息）。")
    st = dw.find(outer)
    if st is None:
        return None, f"DWARF 里找不到外层类型 {outer!r}"
    want = target.rsplit("::", 1)[-1]
    hits: list[tuple[str, int]] = []
    for fname, toff in st.field_types.items():
        tn = dw.type_name(toff)
        if not tn:
            continue
        base = tn.split("<", 1)[0]
        if tn == target or base == target or base.rsplit("::", 1)[-1] == want:
            off = st.fields.get(fname)
            if off is not None:
                hits.append((fname, off))
    if not hits:
        got = "、".join(
            f"{f}:{dw.type_name(t) or '?'}" for f, t in
            list(st.field_types.items())[:8]) or "（没有字段类型信息）"
        return None, f"{outer} 里没有类型是 {target} 的字段。它的字段有：{got}"
    if len(hits) > 1:
        names = "、".join(f"{f}(+{o})" for f, o in hits)
        return None, (f"{outer} 里有不止一个字段类型是 {target}：{names}。"
                      f"挑哪个都是猜，所以不挑 —— 请在 manifest 里改用 "
                      f"field 明写字段名。")
    return hits[0][1], ""


_PERCPU_PREFIX = "__PERCPU_"


def _percpu_var(dw: DwarfSource, spec: str):
    for name, how in _percpu_candidates(spec):
        var = dw.var(name)
        if var is None or var.type_off is None:
            continue
        tn = dw.type_name(var.type_off) or ""
        if tn.endswith("_WRAPPER"):
            st = dw.struct_at(var.type_off)
            if st is None or not st.fields:
                continue
        return var, how
    return None, ""


def _percpu_type(dw: DwarfSource, spec: str) -> tuple[int | None, str]:
    var, how = _percpu_var(dw, spec)
    return (var.type_off, how) if var is not None else (None, "")


def _percpu_candidates(spec: str) -> list[tuple[str, str]]:
    head, _, last = spec.rpartition("::")
    if last.startswith(_PERCPU_PREFIX):
        return [(spec, "dwarf")]
    sib = f"{head}::{_PERCPU_PREFIX}{last}" if head else f"{_PERCPU_PREFIX}{last}"
    return [(spec, "dwarf"), (sib, f"dwarf经{_PERCPU_PREFIX}兄弟")]


_PERCPU_BOUNDS = ("_percpu_start", "_percpu_end",
                  "_percpu_load_start", "_percpu_load_end")

#:     ax_percpu::layout::PerCpuLayout  size=48
#:       region             +0   PerCpuRegion
#:       template_base      +24  usize
#:       area_size          +32  usize
#:       required_alignment +40  usize
#:     ax_percpu::region::PerCpuRegion  size=24
#:       runtime_base       +0   NonNull<u8>
#:       area_stride        +8   usize
#:       area_count         +16  NonZero<u32>
_PERCPU_LAYOUT_FIELDS = ("region", "template_base")
_PERCPU_REGION_FIELDS = ("runtime_base", "area_stride", "area_count")


def _peel_to_fields(dw: DwarfSource, off: int | None,
                    want: tuple[str, ...]) -> tuple[int | None, int]:
    cur, delta = off, 0
    for _ in range(8):
        st = dw.struct_at(cur) if cur is not None else None
        if st is None:
            return None, 0
        if all(n in st.fields for n in want):
            return cur, delta
        carriers = [f for f, t in st.field_types.items() if dw.size_of(t) != 0]
        pick = (carriers[0] if len(carriers) == 1 else
                next((c for c in ("data", "value") if c in carriers), None))
        nxt = st.field_types.get(pick) if pick else None
        if nxt is None or nxt == cur:
            return None, 0
        delta += st.fields.get(pick, 0)
        cur = nxt
    return None, 0


def _percpu_runtime_layout(dw: DwarfSource, spec: str,
                           layout: str) -> tuple[dict | None, int | None, str]:
    head, _, last = spec.rpartition("::")
    sib = (f"{head}::{_PERCPU_PREFIX}{last}" if head
           else f"{_PERCPU_PREFIX}{last}")
    var = dw.var(sib) or dw.var(spec)
    if var is None or var.addr is None:
        return None, None, (f"DWARF 里没有 {sib!r}（{spec!r} 也没有），"
                            f"查不到这个 per-CPU 量的模板地址")
    if not var.addr:
        return None, None, (f"{sib!r} 的地址是 0。ax_percpu 那套里模板在 .data 段、"
                            f"地址是真的；读到 0 说明拿错了变量")

    lay = dw.var(layout)
    if lay is None or lay.addr is None:
        return None, None, (f"DWARF 里没有布局量 {layout!r} —— ax_percpu 的 per-CPU 区"
                            f"在运行期才排好，基址和步长只能从它里面读")

    inner, shell = _peel_to_fields(dw, lay.type_off, _PERCPU_LAYOUT_FIELDS)
    if inner is None:
        return None, None, (
            f"{layout!r} 的类型 {dw.type_name(lay.type_off)!r} 剥不到有 "
            f"{'、'.join(_PERCPU_LAYOUT_FIELDS)} 的那一层")
    offs = {}
    for f in _PERCPU_REGION_FIELDS:
        _, o = _walk_fields(dw, inner, ("region", f))
        offs[f"region.{f}"] = o
    _, offs["template_base"] = _walk_fields(dw, inner, ("template_base",))
    missing = [n for n, o in offs.items() if o is None]
    if missing:
        return None, None, (
            f"{dw.type_name(inner)!r}（{layout} 剥掉 {shell} 字节壳之后）里查不到 "
            f"{'、'.join(missing)}。ax_percpu 的布局结构该有这几个字段，"
            f"对不上就不能照这套算")

    at = lambda f: lay.addr + shell + offs[f]
    return ({"base_at": at("region.runtime_base"),
             "stride_at": at("region.area_stride"),
             "count_at": at("region.area_count"),
             "template_base_at": at("template_base"),
             "template": var.addr, "name": spec,
             "how": f"ax_percpu 运行期布局（{layout}）"},
            var.type_off, "")

_PERCPU_ALIGNS = (64, 8, 1)


def _percpu_layout(dw: DwarfSource, syms, spec: str) -> tuple[dict | None, str]:
    var, how = _percpu_var(dw, spec)
    if var is None or var.addr is None:
        return None, (f"DWARF 里没有 per-CPU 量 {spec!r}（{_PERCPU_PREFIX} 兄弟"
                      f"也没有），不知道它在一份 per-CPU 数据里的偏移")

    elf = getattr(syms, "elf", None)
    if elf is None:
        return None, "没有符号表，查不到 per-CPU 区的边界"

    edge: dict[str, int] = {}
    missing: list[str] = []
    for n in _PERCPU_BOUNDS:
        s = elf.sym(n)
        if s is None:
            missing.append(n)
        else:
            edge[n] = s.value
    if missing:
        return None, (f"ELF 符号表里没有 {'、'.join(missing)}。这套名字是 percpu "
                      f"crate 的约定，这个内核要是自己排的 per-CPU 区，就得另找"
                      f"办法定位，不能照这套算")

    size = edge["_percpu_load_end"] - edge["_percpu_load_start"]
    span = edge["_percpu_end"] - edge["_percpu_start"]
    if size <= 0 or span <= 0:
        return None, (f"per-CPU 区的边界不成立：一份长 {size}、总共 {span}")

    for a in _PERCPU_ALIGNS:
        stride = -(-size // a) * a
        if stride and span % stride == 0:
            break
    else:
        return None, (f"总共 {span:#x} 不是一份 {size:#x} 的整数倍"
                      f"（按 {_PERCPU_ALIGNS} 这几种对齐都试过了），"
                      f"算不出有几个 CPU")

    return {"base": edge["_percpu_start"], "stride": stride,
            "ncpu": span // stride,
            "off": var.addr - edge["_percpu_load_start"],
            "name": spec, "how": how}, ""


def compile_source(dw: DwarfSource, entity: str, src: SourceSpec,
                   *, syms=None, struct_path: str | None = None) -> Plan:
    p = Plan(entity=entity)

    if not src.steps:
        # A source may deliberately assert that this kernel shape has no
        # entities to enumerate (rCore ch1 has neither tasks nor a batch
        # manager).  An empty executable plan is the exact representation of
        # that fact.  Empty steps anywhere else remain an error: accepting a
        # typo as an empty table would be a silent data loss bug.
        if src.kind == "batch" and src.completeness == "none":
            p.compiled = True
            p.trace.append("空计划：manifest 声明这一形态没有可枚举实体")
        else:
            p.compiled, p.reason = False, "这条 source 没有 steps"
        return p

    cur_type: str | None = None
    cur_off: int | None = None

    for i, step in enumerate(src.steps):
        keys = [k for k in step if k in _STEPS]
        if not keys:
            p.compiled = False
            p.reason = (f"第 {i} 步不认识：{sorted(step)}。"
                        f"认识的有 {'、'.join(sorted(_STEPS))}")
            return p
        if len(keys) > 1:
            p.compiled = False
            p.reason = f"第 {i} 步同时写了 {keys}，一步只能干一件事"
            return p
        stray = sorted(set(step) - _STEPS - _STEP_ARGS)
        if stray:
            p.compiled = False
            p.reason = (f"第 {i} 步有不认识的参数 {stray}；"
                        f"这一步认识的参数有 {sorted(_STEP_ARGS)}")
            return p

        k = keys[0]
        v = step[k]

        if k == "static":
            if syms is not None:
                sym, why = syms.resolve(v)
            else:
                var = dw.var(v)
                sym = None if var is None else _Sym(v, var.addr, 0, "dwarf",
                                                    var.type_off)
                why = ("没有提供符号表，只查了 DWARF 变量表 —— "
                       "lazy_static 的静态量在那里面查不到")
            if sym is None:
                p.compiled = False
                p.reason = f"第 {i} 步：找不到静态符号 {v!r}。{why}"
                return p
            p.ops.append(Op("load_static", {"addr": sym.addr, "name": v,
                                            "how": sym.how}))
            type_src = sym.how
            cur_off = sym.type_off
            if cur_off is None:
                by_addr = dw.var_at(sym.addr)
                if by_addr is not None and by_addr.type_off is not None:
                    cur_off = by_addr.type_off
                    type_src = f"{sym.how}+DWARF按地址({by_addr.path})"
            cur_type = dw.type_name(cur_off) if cur_off else None
            size = f" size={sym.size}" if sym.size else ""
            p.trace.append(f"[{i}] static {v} -> {sym.addr:#x}"
                           f"{size} : {cur_type or '类型未知（来自符号表）'}"
                           f" [{type_src}]")

        elif k == "field":
            #          struct { struct spinlock lock; struct buf buf[NBUF];
            #                   struct buf head; } bcache;
            #          { unwrap = ["Lazy", "Mutex"] }, { field = "queue" }
            got = None
            base = dw.struct_at(cur_off) if cur_off is not None else None
            if base is None and cur_type:
                base = dw.find(cur_type)
            if base is None and struct_path:
                base = dw.find(struct_path)
            if base is not None:
                got = resolve_path(dw, base, v)
            off = got.offset if got and got.ok else None
            if off is None:
                p.ops.append(Op("field_dyn", {"name": v}))
                p.trace.append(f"[{i}] field {v} -> 运行期再查（编译期不知道类型）")
                cur_type, cur_off = None, None
            else:
                p.ops.append(Op("offset", {"n": off, "name": v}))
                p.trace.append(f"[{i}] field {v} -> +{off}")
                cur_off = got.type_off if got else None
                cur_type = dw.type_name(cur_off) if cur_off else None

        elif k == "deref":
            p.ops.append(Op("deref", {}))
            cur_off = dw.pointee(cur_off) if cur_off is not None else None
            cur_type = dw.type_name(cur_off) if cur_off is not None else None
            p.trace.append(f"[{i}] deref -> {cur_type or '类型未知'}")

        elif k == "unwrap":
            chain = v if isinstance(v, list) else [v]
            types: list[str | None] = []
            nested: list[str | None] = []
            data_offs: list[int | None] = []
            strong_offs: list[int | None] = []
            t = cur_type
            off = cur_off
            for _layer in chain:
                types.append(t)
                nested.append(_sole_field_type(dw, t))
                data_offs.append(_refcount_data_off(dw, off)
                                 if _is_refcounted(str(_layer)) else None)
                strong_offs.append(_refcount_strong_off(dw, off)
                                   if _is_refcounted(str(_layer)) else None)

                nxt = _inner_type(t)
                nxt_off = None
                if nxt is None and _is_refcounted(str(_layer)):
                    nxt_off = _refcount_payload(dw, off)
                    nxt = dw.type_name(nxt_off) if nxt_off is not None else None
                if nxt is None:
                    nxt = nested[-1]
                if nxt is not None and nxt_off is None:
                    nxt_off = dw.type_off(nxt)
                t, off = nxt, nxt_off
            p.ops.append(Op("unwrap", {"chain": list(chain), "types": types,
                                       "nested": nested,
                                       "data_offs": data_offs,
                                       "strong_offs": strong_offs}))
            cur_type = t
            cur_off = off
            shown = " -> ".join(
                f"{lay}({ty})" if ty else f"{lay}(类型未知)"
                for lay, ty in zip(chain, types))
            p.trace.append(f"[{i}] unwrap {shown}")

        elif k == "descend_to":
            off, why = _descend_offset(dw, cur_type, str(v))
            if off is None:
                p.compiled = False
                p.reason = f"第 {i} 步：descend_to {v} 解不出来。{why}"
                return p
            p.ops.append(Op("offset", {"n": off, "name": f"->{v}"}))
            cur_type = v
            cur_off = None
            p.trace.append(f"[{i}] descend_to {v} = +{off}")

        elif k == "iter":
            args = {"container": v, **{kk: vv for kk, vv in step.items()
                                       if kk != "iter"}}
            via = step.get("via")
            if via is not None:
                actual = _container_of(via)
                want = str(v).lower()
                if actual != want:
                    p.compiled = False
                    p.reason = (f"第 {i} 步：iter={v!r}，但 via 展开的容器是 "
                                f"{actual!r}；两者必须一致")
                    return p
                rs, why = _via_spec(via, key=step.get("key"))
                if rs is None:
                    p.compiled = False
                    p.reason = f"第 {i} 步：iter 的 via 解不出容器。{why}"
                    return p
                # Executor dispatches by this reader specification.  Keeping
                # only the bare ``vec`` here would discard Option/Arc element
                # shells and treat their pointer bytes as inline entities.
                args["container"] = rs
            arr = dw.array_of(cur_off)
            elem_off = None
            if str(v).lower() == "btreemap":
                if cur_type:
                    args.setdefault("btree_map_type", cur_type)
                for k2, v2 in btree_opts(dw, cur_off).items():
                    args.setdefault(k2, v2)
                elem_off = btree_value_die(dw, cur_off)
            elif str(v).lower() == "list":
                for k2, v2 in list_opts(
                        dw, cur_off,
                        link=str(step.get("link", "links")),
                        next_field=str(step.get("next", "next"))).items():
                    args.setdefault(k2, v2)
                elem_off = list_elem_die(dw, cur_off)
            elif arr is not None:
                elem_off, count = arr
                if count is not None:
                    args.setdefault("count", count)
                es = dw.size_of(elem_off)
                if es is not None:
                    args.setdefault("elem_size", es)
            else:
                for k2, v2 in vec_opts(dw, cur_off).items():
                    args.setdefault(k2, v2)
                st = dw.struct_at(cur_off)
                if st is not None and "buf" in st.field_types:
                    elem_off = elem_die(dw, st.field_types["buf"])
            if elem_off is not None:
                args.setdefault("elem_type", dw.type_name(elem_off))
            cur_off = elem_off
            cur_type = dw.type_name(elem_off) if elem_off is not None else None
            p.ops.append(Op("iter", args))
            shown = (f"{v}（{args.get('count', '?')} 个 × "
                     f"{args.get('elem_size', '?')} 字节）"
                     if arr is not None else
                     f"{v} -> {cur_type or '元素类型未知'}")
            p.trace.append(f"[{i}] iter {shown}")

        elif k == "walk":
            args = {"edge": v, **{kk: vv for kk, vv in step.items()
                                  if kk != "walk"}}
            spec = v if isinstance(v, dict) else {"children": v}
            path = str(spec.get("children") or spec.get("next") or "")

            via = spec.get("via", step.get("via"))
            if via is not None:
                rs, why = _via_spec(via, key=spec.get("key", step.get("key")))
                if rs is None:
                    p.compiled = False
                    p.reason = f"第 {i} 步：walk 的 via 解不出容器。{why}"
                    return p
                args["reader"] = rs

            owner = cur_type or struct_path
            st = dw.struct_at(cur_off) if cur_off is not None else None
            if st is None and owner:
                st = dw.find(owner)
            if path and st is not None:
                got = resolve_path(dw, st, path)
                if got.ok:
                    base, delta = _container_payload(dw, got.type_off, via)
                    if base is None:
                        base, delta = got.type_off, 0
                    args.setdefault("edge_offset", got.offset + delta)
                    if _container_of(via) == "btreemap":
                        ct = dw.type_name(base)
                        if ct:
                            args.setdefault("btree_map_type", ct)
                        for k2, v2 in btree_opts(dw, base).items():
                            args.setdefault(k2, v2)
                    else:
                        args.update({kk: vv for kk, vv in
                                     vec_opts(dw, base).items()
                                     if kk not in args})
                else:
                    p.trace.append(f"[{i}] walk {path} 的偏移编译期没解出来："
                                   f"{got.reason}")
            p.ops.append(Op("walk", args))
            where = (f"+{args['edge_offset']}" if "edge_offset" in args
                     else "偏移待运行期查 __edges__")
            p.trace.append(f"[{i}] walk {path or v} -> "
                           f"{args.get('reader', '(via 未写)')} @{where}")

        elif k == "percpu":
            lay_sym = step.get("layout")
            tpl_off = None
            if lay_sym is not None:
                args, tpl_off, why = _percpu_runtime_layout(dw, str(v),
                                                            str(lay_sym))
            else:
                args, why = _percpu_layout(dw, syms, str(v))
            if args is None:
                p.compiled = False
                p.reason = f"第 {i} 步 percpu {v}：{why}"
                return p
            p.ops.append(Op("percpu", args))
            off, how = ((tpl_off, "ax_percpu 模板变量") if tpl_off is not None
                        else _percpu_type(dw, str(v)))
            if off is not None:
                cur_off = off
                cur_type = dw.type_name(off)
            where = (f"模板@{args['template']:#x} 布局@{args['base_at']:#x}"
                     f"（基址/步长/个数运行期读）" if "base_at" in args else
                     f"@{args['base']:#x}+{args['off']:#x} "
                     f"×{args['ncpu']}CPU 步长{args['stride']:#x}")
            p.trace.append(
                f"[{i}] percpu {v} {where}"
                + (f" : {cur_type} [{how}]" if off is not None
                   else " : 类型未知（DWARF 里没有这个量）"))

        elif k == "from":
            p.ops.append(Op("from", {"ref": v}))
            p.trace.append(f"[{i}] from {v}")

        elif k == "index":
            p.ops.append(Op("index", {"n": v}))
            p.trace.append(f"[{i}] index {v}")

    return p


def dependencies(src: SourceSpec) -> list[str]:
    out = []
    for step in src.steps:
        if "from" in step:
            out.append(str(step["from"]).split(".")[0])
    return out
