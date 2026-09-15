
from __future__ import annotations

from ..rt import Memory, ReadCtx, Reader, Unavailable, Value
from . import containers as _c
from . import pointers as _p
from . import scalars as _s

__all__ = [
    "Struct", "split_spec", "outer_name", "generic_args", "inner_type",
    "make", "unwrap_reader", "known_names",
]


class Struct:

    def provenance(self, ctx: ReadCtx) -> str:
        return "Struct（内嵌结构体，取地址本身，不访存）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return addr

    def __repr__(self) -> str:
        return "Struct()"



def split_spec(spec: str) -> tuple[str, list[str]]:
    s = spec.strip()
    i = s.find("<")
    if i < 0:
        return s.lower(), []
    if not s.endswith(">"):
        raise ValueError(f"reader 名 {spec!r} 的尖括号没闭合")
    head, body = s[:i].strip().lower(), s[i + 1:-1]
    args, depth, cur = [], 0, ""
    j = 0
    while j < len(body):
        ch = body[j]
        # `Lazy<Arc<Task, Global>, fn() -> Arc<Task, Global>, Spin>`，
        if ch == "-" and body[j + 1:j + 2] == ">":
            cur += "->"
            j += 2
            continue
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth < 0:
                raise ValueError(f"reader 名 {spec!r} 的尖括号不配对")
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
        j += 1
    if depth != 0:
        raise ValueError(f"reader 名 {spec!r} 的尖括号不配对")
    if cur.strip():
        args.append(cur.strip())
    return head, args


def outer_name(type_name: str) -> str:
    s = type_name.strip()
    i = s.find("<")
    if i >= 0:
        s = s[:i]
    return s.rsplit("::", 1)[-1].strip()


def generic_args(type_name: str) -> list[str]:
    s = type_name.strip()
    i = s.find("<")
    if i < 0 or not s.endswith(">"):
        return []
    _, args = split_spec(s[:i] + "<" + s[i + 1:-1] + ">")
    return args


def inner_type(type_name: str | None) -> str | None:
    if not type_name:
        return None
    args = generic_args(type_name)
    return args[0] if len(args) == 1 else None



_TERMINALS: dict[str, Reader] = {
    "u8": _s.u8, "u16": _s.u16, "u32": _s.u32, "u64": _s.u64,
    "i8": _s.i8, "i16": _s.i16, "i32": _s.i32, "i64": _s.i64,
    "usize": _s.usize, "isize": _s.isize,
    "ppn": _s.ppn,
    "bool": _s.bool_,
    "unit": _s.unit,
    "struct": Struct(),
    "ptr": _p.Ptr(),
}

_INLINE = {
    "unsafecell": _p.UnsafeCell,
    "maybedangling": _p.MaybeDangling,
    "maybeuninit": _p.MaybeUninit,
    "upsafecell": _p.UpSafeCell,
    "spinlock": _p.SpinLock,
    "basespinlock": _p.SpinLock,
    "mutex": _p.Mutex,
    "spinrwlock": _p.SpinRwLock,
    "lazyinit": _p.LazyInit,
    "lazy": _p.Lazy,
    "lazylock": _p.LazyLock,
}

_CROSS = {
    "arc": _p.Arc,
    "weak": _p.Weak,
    "ptr": _p.Ptr,
    "nonnull": _p.Ptr,
}

_OPTION = {
    "arc": _p.OptionArc,
    "weak": _p.OptionWeak,
}


_CONTAINERS = {"vec", "vecdeque", "array"}

#:     via = ["SpinLock", "btreemap", "Arc"], key = "newtype<u32>"
#:         -> "btreemap<newtype<u32>, arc>"
_MAPS = {"btreemap"}

_CONTAINERS_NOT_VIA = {"list"}

_TERMINATORS = {
    "null": _c.NullTerminated,
    "circular": _c.Circular,
    "circular_headed": _c.CircularHeaded,
}


def _terminator(spec: object) -> tuple[object | None, str]:
    if spec is None:
        return None, ("list 必须显式写 terminator（null / circular / "
                      "circular_headed，或者一个整数哨兵值）—— 三种链表在内存里"
                      "长得一样，DWARF 分不出来；猜错会把好好的链表报成坏的")
    if isinstance(spec, bool):
        return None, f"terminator 不能是布尔值：{spec!r}"
    if isinstance(spec, int):
        return _c.NullTerminated(sentinel=spec), ""
    cls = _TERMINATORS.get(str(spec).strip().lower())
    if cls is None:
        return None, (f"不认识的 terminator {spec!r}，"
                      f"认识的有 {'、'.join(sorted(_TERMINATORS))}，或一个整数")
    return cls(), ""


def via_spec(via: object, key: str | None = None) -> tuple[str | None, str]:
    layers = [str(x) for x in (via if isinstance(via, list) else [via])]
    layers = [x for x in layers if x.strip()]
    if not layers:
        return None, "via 是空的，不知道该按什么展开"
    for i, lay in enumerate(layers):
        low = lay.lower()
        if low not in _CONTAINERS and low not in _MAPS:
            continue
        rest = layers[i + 1:]
        spec = rest[-1].lower() if rest else "struct"
        for outer in reversed(rest[:-1]):
            spec = f"{outer.lower()}<{spec}>"
        if low in _MAPS:
            if not key:
                return None, (
                    f"via={layers} 从 {lay} 这层展开的是**映射**，元素 reader 要"
                    f"两个。值那一半 via 拼得出来（{spec}），键得另写 "
                    f"key = \"...\" —— 键是这一项在人眼里的名字（进程号、VMId），"
                    f"不指定的话表里每一行都只剩一个下标")
            return f"{low}<{key}, {spec}>", ""
        return f"{low}<{spec}>", ""
    hit = [x for x in layers if x.lower() in _CONTAINERS_NOT_VIA]
    if hit:
        return None, (
            f"via={layers} 里的 {hit[0]} 是个容器，但 via 拼不出它 —— 它要的"
            f"偏移只在 iter 那条路上量过。改用 iter = \"{hit[0]}\"")
    return None, (
        f"via={layers} 里没有一层是会展开成一串的容器（认识的："
        f"{'、'.join(sorted(_CONTAINERS))}；映射另外还认 "
        f"{'、'.join(sorted(_MAPS))}，那些要再写一个 key = \"...\"）。"
        f"不知道从哪一层开始展开就没法遍历")


def container_of(via: object) -> str | None:
    layers = [str(x).lower() for x in (via if isinstance(via, list) else [via])]
    for lay in layers:
        if lay in _CONTAINERS or lay in _MAPS:
            return lay
    return None


def inline_payload_fields(head: str) -> tuple[tuple[str, ...], ...]:
    chains = getattr(_INLINE.get(head), "_chains", None)
    if not chains:
        return ()
    return tuple(tuple(f for _t, f in chain) for chain in chains)


def known_names() -> list[str]:
    return sorted({*_TERMINALS, *_INLINE, *_CROSS, "atomic", "newtype",
                   "field", "variant", "astype", "enum", "cstr", "bitfield",
                   "option", "array", "vec", "vecdeque", "string", "btreemap"})



_NESTED_KW = {
    "upsafecell": "cell_type",
    "lazy":       "once_type",
    "lazylock":   "once_type",
    "mutex":      "ticket_type",
    "spinrwlock": "base_type",
    "spinlock":   "base_type",
}

_NESTED_GUESS = {"upsafecell": "RefCell", "lazy": "Once", "lazylock": "OnceLock"}


def _inline_reader(name: str, inner: Reader | None,
                   type_name: str | None, nested: str | None) -> Reader:
    cls = _INLINE[name]
    kw = _NESTED_KW.get(name)
    if kw is None:
        return cls(inner, type_name=type_name)
    val = nested
    if val is None and name in _NESTED_GUESS:
        it = inner_type(type_name)
        val = f"{_NESTED_GUESS[name]}<{it}>" if it else None
    if val is None:
        return cls(inner, type_name=type_name)
    return cls(inner, type_name=type_name, **{kw: val})


def make(spec: str, *, type_name: str | None = None,
         opts: dict | None = None) -> tuple[Reader | None, str]:
    o = dict(opts or {})
    try:
        head, args = split_spec(spec)
    except ValueError as e:
        return None, str(e)

    chain = o.get("layer_chain") or []
    mine = chain[0] if chain else {}
    if not type_name:
        type_name = mine.get("name")

    sub_o = {k: v for k, v in o.items() if k != "shell_nested"}
    sub_o["layer_chain"] = chain[1:]
    inner: Reader | None = None
    if args and head not in ("btreemap", "field", "variant", "astype"):
        sub_name = chain[1].get("name") if chain[1:] else None
        if not sub_name:
            sub_name = inner_type(type_name)
        sub, why = make(args[0], type_name=sub_name, opts=sub_o)
        if sub is None:
            return None, f"{spec} 的内层解不出来：{why}"
        inner = sub

    if head in _TERMINALS and not args:
        return _TERMINALS[head], ""

    if head in _INLINE:
        return _inline_reader(head, inner, type_name,
                              o.get("shell_nested")
                              or mine.get("shell_nested")), ""

    if head in _CROSS:
        cls = _CROSS[head]
        if head == "ptr":
            return cls(inner), ""
        return cls(inner, inner_type=o.get("inner_type") or mine.get("arcinner"),
                   data_off=mine.get("data_off"),
                   strong_off=mine.get("strong_off")), ""

    if head == "option":
        if not args:
            return None, "option 得写成 option<T>，光写 option 不知道里面是什么"
        base = split_spec(args[0])[0]
        if base in _OPTION:
            return _OPTION[base](), ""
        if base in ("struct", "ptr"):
            return _p.Ptr(), ""
        return None, (f"option<{args[0]}> 的 niche 布局没法一概而论 —— "
                      f"只认 option<arc>、option<weak>、option<struct>、"
                      f"option<ptr>")

    if head == "atomic":
        if inner is None:
            return None, "atomic 得写成 atomic<u32> 这种，要指明底下的宽度"
        return _s.Atomic(inner), ""

    if head == "newtype":
        if inner is None:
            return None, "newtype 得写成 newtype<usize> 这种"
        return _s.Newtype(inner, type_name), ""

    if head == "field":
        if len(args) != 2:
            return None, ("field 得写成 field<字段名, 内层 reader> 这种，"
                          "比如 field<root_paddr, usize>")
        name = args[0].strip()
        if not name:
            return None, "field 的第一个实参是字段名，不能是空的"
        sub, why = make(args[1], opts=sub_o)
        if sub is None:
            return None, f"field<{name}, …> 的内层解不出来：{why}"
        return _s.Field(sub, type_name, name, off=mine.get("field_off")), ""

    if head == "astype":
        #     TaskInner.task_ext  +784  Option<ax_task::task::AxTaskExt>
        #     AxTaskExt           16B   __0: extern_trait::Repr
        #     extern_trait::Repr  16B   __0: *mut ()   __1: *mut ()（vtable）
        if len(args) != 2:
            return None, ("astype 得写成 astype<类型名, 内层 reader> 这种，"
                          "比如 astype<starry_kernel::task::Thread, "
                          "field<proc_data, arc>>")
        name = args[0].strip()
        if not name:
            return None, "astype 的第一个实参是类型名，不能是空的"
        sub, why = make(args[1], type_name=name, opts=sub_o)
        if sub is None:
            return None, f"astype<{name}, …> 的内层解不出来：{why}"
        return sub, ""

    if head == "variant":
        if len(args) != 2:
            return None, ("variant 得写成 variant<变体名, 内层 reader> 这种，"
                          "比如 variant<Live, field<__0, weak<struct>>>")
        name = args[0].strip()
        if not name:
            return None, "variant 的第一个实参是变体名，不能是空的"
        sub, why = make(args[1], opts=sub_o)
        if sub is None:
            return None, f"variant<{name}, …> 的内层解不出来：{why}"
        vs = mine.get("variants") or {}
        got = vs.get(name)
        return _s.Variant(
            sub, type_name, name,
            payload_off=None if got is None else got[1],
            discr=None if got is None else got[0],
            tag_off=mine.get("tag_off"), tag_size=mine.get("tag_size"),
            known=tuple(sorted(vs))), ""

    if head == "enum":
        name = o.get("enum") or type_name
        if not name:
            return None, ("enum 要知道是哪个枚举类型才能把数字换成变体名，"
                          "在 manifest 那一行加上 enum = \"TaskStatus\"")
        return _s.Enum(name, int(o.get("size") or o.get("enum_size") or 4)), ""

    if head == "cstr":
        maxlen = o.get("maxlen")
        if maxlen is None:
            return None, ("cstr 必须给 maxlen —— 没有上限的话，一个没初始化的"
                          "指针会一路扫下去")
        return _s.CStr(int(maxlen)), ""

    if head == "string":
        vt = o.get("string_vec_type")
        if not vt:
            return None, (
                "string 要知道里面那个 Vec<u8> 的 DWARF 类型名，才查得到 "
                "len 和 buf 的偏移 —— 这两个字段不在 String 上（String 只有 "
                "vec）。这个名字由 probe 阶段按形状找出来填进 string_vec_type；"
                "没填上说明这个字段底下没找到 String 的形状")
        return _c.string(vt, str_type=o.get("string_str_type") or type_name,
                         raw_type=o.get("string_raw_type"),
                         raw_base=int(o.get("string_raw_base", 0)),
                         max_bytes=int(o.get("max_bytes", 4096))), ""

    if head == "btreemap":
        if len(args) != 2:
            return None, ("btreemap 得写成 btreemap<键, 值> 这种，键和值各要一个 "
                          "reader —— 只写一个的话不知道省掉的是哪一个")
        mt = o.get("btree_map_type") or type_name
        if not mt:
            return None, ("btreemap 要知道自己的 DWARF 类型名，才查得到 root 和 "
                          "length 的偏移")
        ga = generic_args(mt)
        kt = ga[0] if len(ga) > 0 else None
        vt = ga[1] if len(ga) > 1 else None
        key, why = make(args[0], type_name=kt, opts=sub_o)
        if key is None:
            return None, f"btreemap 的键解不出来：{why}"
        val, why = make(args[1], type_name=vt, opts=sub_o)
        if val is None:
            return None, f"btreemap 的值解不出来：{why}"
        need = ("btree_noderef_height", "btree_noderef_node", "btree_len",
                "btree_keys", "btree_vals", "btree_key_size", "btree_val_size")
        node = None
        if all(o.get(k) is not None for k in need):
            node = _c.BTreeNodeLayout(
                noderef_height=int(o["btree_noderef_height"]),
                noderef_node=int(o["btree_noderef_node"]),
                len=int(o["btree_len"]), keys=int(o["btree_keys"]),
                vals=int(o["btree_vals"]),
                key_size=int(o["btree_key_size"]),
                val_size=int(o["btree_val_size"]),
                edges=(None if o.get("btree_edges") is None
                       else int(o["btree_edges"])))
        return _c.btreemap(mt, key, val, node=node), ""

    if head == "list":
        if inner is None:
            return None, "list 得写成 list<struct> 这种，要说清每一格怎么读"
        if o.get("list_next_off") is None:
            return None, ("list 必须给 list_next_off（next 指针在元素里的偏移，"
                          "由 list_opts 从 DWARF 量出来）—— 猜一个 0 会把元素"
                          "开头的字节当成指针，走出一串合法但错误的地址")
        term, why = _terminator(o.get("terminator"))
        if term is None:
            return None, why
        return _c.list(int(o.get("list_link_off", 0)),
                       int(o["list_next_off"]), inner, terminator=term), ""

    if head == "bitfield":
        if "offset" not in o or "width" not in o:
            return None, "bitfield 要给 offset 和 width"
        return _s.Bitfield(int(o["offset"]), int(o["width"]),
                           size=int(o.get("size", 8))), ""

    if head == "array":
        if inner is None:
            return None, "array 得写成 array<usize> 这种"
        if "count" not in o:
            return None, ("array 必须给 count（来自 DWARF 的 DW_AT_count）—— "
                          "拿总大小除以元素大小会把尾部填充也数进去")
        if "elem_size" not in o:
            return None, "array 必须给 elem_size"
        return _c.array(int(o["elem_size"]), int(o["count"]), inner), ""

    if head in ("vec", "vecdeque"):
        if inner is None:
            return None, f"{head} 得写成 {head}<arc> 这种"
        vt = o.get("vec_type") or type_name
        if not vt:
            return None, (f"{head} 要知道自己的 DWARF 类型名才能查 buf 和下标"
                          f"字段的偏移")
        es = o.get("elem_size")
        if es is None:
            if split_spec(args[0])[0] in ("arc", "weak", "ptr"):
                es = 0
            else:
                return None, (f"{head}<{args[0]}> 要给 elem_size —— 只有元素是"
                              f"指针宽（arc/weak/ptr）时才推得出来")
        cls = _c.vec if head == "vec" else _c.vecdeque
        return cls(vt, int(es), inner, raw_type=o.get("raw_type"),
                   raw_base=int(o.get("raw_base", 0)),
                   unique_type=o.get("unique_type")), ""

    return None, (f"没有叫 {spec!r} 的 reader。认识的有："
                  f"{'、'.join(known_names())}")


def is_refcounted_shell(layer: str) -> bool:
    return outer_name(layer).lower() in ("arc", "weak")


def unwrap_reader(layer: str, type_name: str | None,
                  nested: str | None = None,
                  *, data_off: int | None = None,
                  strong_off: int | None = None
                  ) -> tuple[Reader | None, str]:
    name = outer_name(layer).lower()
    if name in _INLINE:
        return _inline_reader(name, None, type_name, nested), ""
    if name in _CROSS:
        if name == "ptr":
            return _p.Ptr(), ""
        if is_refcounted_shell(name) and (data_off is not None
                                          or strong_off is not None):
            return _CROSS[name](None, data_off=data_off,
                                strong_off=strong_off), ""
        return _CROSS[name](None), ""
    return None, (f"unwrap 不认识 {layer!r} 这层壳。认识的有："
                  f"{'、'.join(sorted({*_INLINE, *_CROSS}))}")
