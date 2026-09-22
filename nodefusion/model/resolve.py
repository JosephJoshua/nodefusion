
from __future__ import annotations

from dataclasses import dataclass, field

from .dwarfsrc import DwarfSource
from .layout import StructLayout
from .readers.registry import (inline_payload_fields, inner_type,
                               is_refcounted_shell, split_spec)

PRESENT = "present"
ABSENT = "absent"
UNDECODABLE = "undecodable"

EMPTY = "empty"


@dataclass
class Resolved:

    state: str
    offset: int | None = None
    type_off: int | None = None
    type_name: str | None = None
    hops: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == PRESENT

    def __bool__(self) -> bool:
        return self.ok


def _descend_inline(dw: DwarfSource, start: StructLayout, want: str,
                    *, max_hops: int = 8,
                    visited: list[StructLayout] | None = None,
                    ) -> tuple[int, list[str], int | None] | None:
    level: list[tuple[StructLayout, int, list[str]]] = [(start, 0, [])]
    seen: set[str] = {start.path or start.name}
    if visited is not None:
        visited.append(start)

    for _ in range(max_hops):
        if not level:
            return None
        hits = [(base + s.fields[want], [*trail, want],
                 s.field_types.get(want))
                for s, base, trail in level if want in s.fields]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None

        nxt: list[tuple[StructLayout, int, list[str]]] = []
        for s, base, trail in level:
            for fname, foff in s.fields.items():
                sub = dw.struct_at(s.field_types.get(fname))
                if sub is None:
                    continue
                key = sub.path or sub.name
                if key in seen:
                    continue
                seen.add(key)
                if visited is not None:
                    visited.append(sub)
                nxt.append((sub, base + foff, [*trail, fname]))
        level = nxt
    return None


def _shorten(names: list[str], cap: int = 8) -> str:
    if len(names) <= cap:
        return ", ".join(names) or "无字段"
    return ", ".join(names[:cap]) + f", …（共 {len(names)} 个）"


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def _looked_in(looked: list[StructLayout], cap: int = 3) -> str:
    ranked = sorted(looked, key=lambda s: (-len(s.fields), s.path or s.name))
    parts = [f"{_clip(s.path or s.name, 70 if i == 0 else 44)}"
             f"{{{_shorten(sorted(s.fields), 24 if i == 0 else 6)}}}"
             for i, s in enumerate(ranked[:cap])]
    return (f"下潜共看过 {len(looked)} 个类型，其中字段最多的："
            + "；".join(parts))


def resolve_path(dw: DwarfSource, start: StructLayout, path: str,
                 *, max_hops: int = 8) -> Resolved:
    cur: StructLayout | None = start
    total = 0
    hops: list[str] = []
    last_ty: int | None = None

    for seg in [s for s in path.split(".") if s]:
        if cur is None:
            return Resolved(UNDECODABLE, hops=hops, reason=(
                f"路径 {path!r} 在 {'.'.join(hops) or start.name!r} 之后进了一个"
                f"非结构体类型，无法再往下取字段"))

        looked: list[StructLayout] = []
        found = _descend_inline(dw, cur, seg, max_hops=max_hops, visited=looked)
        if found is None:
            return Resolved(ABSENT, hops=hops, reason=(
                f"{cur.path or cur.name} 及其内联嵌套里都找不到 {seg!r}"
                f"（路径 {path!r}）。{_looked_in(looked)}。"
                f"两种可能：这个内核确实没有这个字段（内核之间加减字段是常态，"
                f"manifest 里标了 optional 就按缺席算）；或者这一跳要穿指针"
                f"（Arc、Box、裸指针），而下潜只穿内联层、不会自己解引用，"
                f"穿指针得在 manifest 里显式写 unwrap"))

        off, trail, tyoff = found
        total += off
        hops.extend(trail)
        cur = dw.struct_at(tyoff)
        last_ty = tyoff

    return Resolved(PRESENT, offset=total, type_off=last_ty,
                    type_name=dw.type_name(last_ty), hops=hops)



def eval_when(dw: DwarfSource, pred: dict | None) -> tuple[bool, str]:
    if not pred:
        return True, "无条件"

    if "type_exists" in pred:
        want = pred["type_exists"]
        hit = dw.find(want) is not None
        return hit, f"类型 {want} {'在' if hit else '不在'}"

    if "type_missing" in pred:
        want = pred["type_missing"]
        missing = dw.find(want) is None
        return missing, f"类型 {want} {'不在' if missing else '在'}"

    if "field_exists" in pred:
        spec = pred["field_exists"]
        s = dw.find(spec["type"])
        if s is None:
            return False, f"类型 {spec['type']} 不在"
        hit = spec["field"] in s.fields
        return hit, (f"{spec['type']}.{spec['field']} "
                     f"{'在' if hit else '不在'}")

    if "field_type" in pred:
        spec = pred["field_type"]
        s = dw.find(spec["type"])
        if s is None:
            return False, f"类型 {spec['type']} 不在"
        tn = dw.type_name(s.field_types.get(spec["field"]))
        if tn is None:
            return False, f"{spec['type']}.{spec['field']} 读不到类型"
        if "starts_with" in spec:
            hit = tn.startswith(spec["starts_with"])
            return hit, (f"{spec['type']}.{spec['field']} 是 {tn}，"
                         f"{'匹配' if hit else '不匹配'} {spec['starts_with']}*")
        if "equals" in spec:
            hit = tn == spec["equals"]
            return hit, f"{spec['type']}.{spec['field']} 是 {tn}"
        return False, f"field_type 谓词缺 starts_with/equals：{spec}"

    return False, f"看不懂的 when 谓词：{sorted(pred)}"


_PTR_CHASE_DEPTH = 6


_RAW_INNER_FIELD = "inner"
_RAW_MARKER_FIELD = "_marker"


def qualified_name(dw: DwarfSource, off: int | None) -> str | None:
    st = dw.struct_at(off) if off is not None else None
    path = getattr(st, "path", None) if st is not None else None
    return path or dw.type_name(off)


def raw_carrier(dw: DwarfSource, raw_off: int | None,
                ) -> tuple[str | None, int]:
    st = dw.struct_at(raw_off) if raw_off is not None else None
    if st is None:
        return None, 0
    if "ptr" in st.fields and "cap" in st.fields:
        return qualified_name(dw, raw_off), 0
    inner_off = st.field_types.get(_RAW_INNER_FIELD)
    ist = dw.struct_at(inner_off) if inner_off is not None else None
    if ist is None or "ptr" not in ist.fields or "cap" not in ist.fields:
        return None, 0
    base = st.fields.get(_RAW_INNER_FIELD)
    if base is None:
        return None, 0
    return qualified_name(dw, inner_off), base


def elem_die(dw: DwarfSource, raw_off: int | None) -> int | None:
    st = dw.struct_at(raw_off) if raw_off is not None else None
    if st is None:
        return None
    if "ptr" in st.field_types:
        return _chase_to_pointee(dw, st.field_types["ptr"])
    return dw.type_off(inner_type(dw.type_name(
        st.field_types.get(_RAW_MARKER_FIELD))))


def _chase_to_pointee(dw: DwarfSource, cur: int | None) -> int | None:
    for _ in range(_PTR_CHASE_DEPTH):
        if cur is None:
            return None
        po = dw.pointee(cur)
        if po is not None:
            return po
        st = dw.find(dw.type_name(cur) or "")
        if st is None or "pointer" not in st.fields:
            return None
        cur = st.field_types.get("pointer")
    return None


_REFCOUNT_PAYLOAD_FIELDS = ("data", "value")


def refcounted_payload_die(dw: DwarfSource, off: int | None) -> int | None:
    st = dw.struct_at(off) if off is not None else None
    if st is None or "ptr" not in st.field_types:
        return None
    inner = _chase_to_pointee(dw, st.field_types["ptr"])
    ist = dw.struct_at(inner) if inner is not None else None
    if ist is None:
        return None
    hit = [f for f in _REFCOUNT_PAYLOAD_FIELDS if f in ist.field_types]
    if len(hit) != 1:
        return None
    return ist.field_types[hit[0]]


def refcounted_strong_offset(dw: DwarfSource, off: int | None) -> int | None:
    ist = _arcinner_struct(dw, off)
    if ist is None or "strong" not in ist.fields:
        return None
    return ist.fields["strong"]


def _arcinner_struct(dw: DwarfSource, off: int | None):
    st = dw.struct_at(off) if off is not None else None
    if st is None or "ptr" not in st.field_types:
        return None
    inner = _chase_to_pointee(dw, st.field_types["ptr"])
    return dw.struct_at(inner) if inner is not None else None


def refcounted_data_offset(dw: DwarfSource, off: int | None) -> int | None:
    ist = _arcinner_struct(dw, off)
    if ist is None:
        return None
    hit = [f for f in _REFCOUNT_PAYLOAD_FIELDS if f in ist.fields]
    if len(hit) != 1:
        return None
    return ist.fields[hit[0]]


def _elem_size(dw: DwarfSource, raw_off: int | None) -> int | None:
    po = elem_die(dw, raw_off)
    if po is not None:
        sz = dw.size_of(po)
        return sz if sz else None
    st = dw.struct_at(raw_off) if raw_off is not None else None
    if st is None or "ptr" in st.field_types:
        return None
    sz = dw.size_by_name(inner_type(dw.type_name(
        st.field_types.get(_RAW_MARKER_FIELD))))
    return sz if sz else None


def vec_opts(dw: DwarfSource, type_off: int | None) -> dict:
    o: dict = {}
    tn = dw.type_name(type_off) if type_off is not None else None
    if not tn:
        return o
    o["vec_type"] = tn
    st = dw.find(tn)
    if st is not None:
        raw = st.field_types.get("buf")
        if raw is not None:
            rn, base = raw_carrier(dw, raw)
            if rn:
                o["raw_type"] = rn
                o["raw_base"] = base
            es = _elem_size(dw, raw)
            if es is not None:
                o["elem_size"] = es
    return o


_STRING_SEARCH_DEPTH = 4


def _looks_like_vec_u8(dw: DwarfSource, off: int | None) -> bool:
    st = dw.struct_at(off) if off is not None else None
    if st is None or "buf" not in st.field_types or "len" not in st.field_types:
        return False
    return raw_carrier(dw, st.field_types["buf"])[0] is not None


def shell_opts(dw: DwarfSource, type_off: int | None) -> dict:
    st = dw.struct_at(type_off) if type_off is not None else None
    if st is None:
        return {}
    carriers = [t for t in st.field_types.values() if dw.size_of(t) != 0]
    if len(carriers) != 1:
        return {}
    n = qualified_name(dw, carriers[0])
    return {"shell_nested": n} if n else {}


_TRANSPARENT = ("core::cell::UnsafeCell<",
                "core::mem::manually_drop::ManuallyDrop<")


def _peel_transparent_cell(dw: DwarfSource, off: int | None) -> int | None:
    for _ in range(4):
        name = qualified_name(dw, off) or ""
        if not name.startswith(_TRANSPARENT):
            return off
        nxt, _o = _walk_fields(dw, off, ("value",))
        if nxt is None:
            return off
        off = nxt
    return off


def peel_die(dw: DwarfSource, off: int | None, head: str,
             args: tuple[str, ...] = ()) -> int | None:
    if head == "astype" and args:
        return dw.type_off(args[0].strip())
    if off is None:
        return None
    if is_refcounted_shell(head):
        return refcounted_payload_die(dw, off)
    st = dw.struct_at(off)
    if st is None:
        return None
    if head == "field" and args:
        return st.field_types.get(args[0].strip())
    if head == "variant" and args:
        got = st.variants.get(args[0].strip())
        return None if got is None else got[2]
    for names in inline_payload_fields(head):
        die, _off = _walk_fields(dw, off, names)
        if die is not None:
            return _peel_transparent_cell(dw, die)
    carriers = [t for t in st.field_types.values() if dw.size_of(t) != 0]
    return carriers[0] if len(carriers) == 1 else None


def _reader_layers(dw: DwarfSource, spec: str, type_off: int | None):
    """Yield ``(reader head, arguments, DIE)`` for each linear reader layer.

    Reader specs and DWARF types have to advance together.  Keep that walk in
    one place: metadata collection and readers which need the DIE of a nested
    container must not grow subtly different peeling rules.
    """
    cur, s = type_off, spec
    while True:
        try:
            head, args = split_spec(s)
        except ValueError:
            return
        yield head, tuple(args), cur
        if not args or head == "btreemap":
            return
        nxt = (args[1] if head in ("field", "variant", "astype")
               and len(args) > 1 else args[0])
        cur, s = peel_die(dw, cur, head, tuple(args)), nxt


def reader_layer_die(dw: DwarfSource, spec: str, type_off: int | None,
                     want: str) -> int | None:
    """Return the exact DIE paired with the first ``want`` reader layer.

    A field's DIE describes its outermost type.  Container readers are often
    nested inside inline shells, for example Starry's
    ``spinlock<btreemap<...>>``.  Layout must be measured on the BTreeMap DIE,
    not on the SpinLock DIE; asking the outer type yields an empty layout while
    still looking superficially valid.
    """
    target = want.lower()
    for head, _args, cur in _reader_layers(dw, spec, type_off):
        if head == target:
            return cur
    return None


def layer_chain(dw: DwarfSource, spec: str, type_off: int | None) -> list[dict]:
    out: list[dict] = []
    for head, args, cur in _reader_layers(dw, spec, type_off):
        layer: dict = {"name": qualified_name(dw, cur)}
        if is_refcounted_shell(head):
            layer["data_off"] = refcounted_data_offset(dw, cur)
            layer["strong_off"] = refcounted_strong_offset(dw, cur)
            ist = _arcinner_struct(dw, cur)
            if ist is not None:
                layer["arcinner"] = ist.path
        layer.update(shell_opts(dw, cur))
        if head == "field" and args:
            st = dw.struct_at(cur) if cur is not None else None
            if st is not None:
                got = st.fields.get(args[0].strip())
                if got is not None:
                    layer["field_off"] = got
        if head == "variant":
            st = dw.struct_at(cur) if cur is not None else None
            if st is not None:
                layer["variants"] = dict(st.variants)
                if st.variant_tag is not None:
                    layer["tag_off"] = st.variant_tag[0]
                    layer["tag_size"] = dw.size_of(st.variant_tag[1])
        out.append(layer)
    return out


def string_opts(dw: DwarfSource, type_off: int | None) -> dict:
    o: dict = {}
    if type_off is None:
        return o
    seen: set[int] = set()
    stack: list[tuple[int, int]] = [(type_off, 0)]
    while stack:
        cur, depth = stack.pop()
        if cur in seen or depth > _STRING_SEARCH_DEPTH:
            continue
        seen.add(cur)
        st = dw.struct_at(cur)
        if st is None:
            continue

        vec_off = st.field_types.get("vec")
        if vec_off is not None and _looks_like_vec_u8(dw, vec_off):
            o["string_str_type"] = qualified_name(dw, cur)
            o["string_vec_type"] = qualified_name(dw, vec_off)
            vst = dw.struct_at(vec_off)
            if vst is not None:
                rn, base = raw_carrier(dw, vst.field_types.get("buf"))
                if rn:
                    o["string_raw_type"] = rn
                    o["string_raw_base"] = base
            return o

        if _looks_like_vec_u8(dw, cur):
            o["string_vec_type"] = qualified_name(dw, cur)
            rn, base = raw_carrier(dw, st.field_types.get("buf"))
            if rn:
                o["string_raw_type"] = rn
                o["string_raw_base"] = base
            return o

        for sub in st.field_types.values():
            stack.append((sub, depth + 1))
    return o


_OPTION_PREFIXES = ("core::option::Option<", "Option<")


def _strip_option(name: str | None) -> str | None:
    if not name:
        return None
    for pre in _OPTION_PREFIXES:
        if name.startswith(pre) and name.endswith(">"):
            return name[len(pre):-1].strip()
    return name


def btree_opts(dw: DwarfSource, type_off: int | None) -> dict:
    o: dict = {}
    mst = dw.struct_at(type_off) if type_off is not None else None
    if mst is None or "root" not in mst.field_types:
        return o

    ref_name = _strip_option(dw.type_name(mst.field_types["root"]))
    ref = dw.find(ref_name) if ref_name else None
    if ref is None or "node" not in ref.field_types:
        return o
    o["btree_noderef_height"] = ref.fields.get("height")
    o["btree_noderef_node"] = ref.fields.get("node")

    leaf_off = _chase_to_pointee(dw, ref.field_types["node"])
    leaf = dw.struct_at(leaf_off) if leaf_off is not None else None
    if leaf is None:
        return o
    for f in ("len", "keys", "vals"):
        o["btree_" + f] = leaf.fields.get(f)

    for f, key in (("keys", "btree_key_size"), ("vals", "btree_val_size")):
        arr = dw.array_of(leaf.field_types.get(f))
        if arr is not None:
            o[key] = dw.size_of(arr[0])

    leaf_name = dw.type_name(leaf_off) or ""
    if "LeafNode<" in leaf_name:
        inter = dw.find(leaf_name.replace("LeafNode<", "InternalNode<", 1))
        if inter is not None:
            o["btree_edges"] = inter.fields.get("edges")

    need = ("btree_noderef_height", "btree_noderef_node", "btree_len",
            "btree_keys", "btree_vals", "btree_key_size", "btree_val_size")
    if any(o.get(k) is None for k in need):
        return {}
    return o


def btree_value_die(dw: DwarfSource, type_off: int | None) -> int | None:
    mst = dw.struct_at(type_off) if type_off is not None else None
    if mst is None or "root" not in mst.field_types:
        return None
    ref_name = _strip_option(dw.type_name(mst.field_types["root"]))
    ref = dw.find(ref_name) if ref_name else None
    if ref is None or "node" not in ref.field_types:
        return None
    leaf_off = _chase_to_pointee(dw, ref.field_types["node"])
    leaf = dw.struct_at(leaf_off) if leaf_off is not None else None
    if leaf is None:
        return None
    arr = dw.array_of(leaf.field_types.get("vals"))
    if arr is None:
        return None
    return _peel_wrappers(dw, arr[0])


_STORAGE_WRAPPERS = ("MaybeUninit<", "ManuallyDrop<")

_PEEL_DEPTH = 4


def _peel_wrappers(dw: DwarfSource, off: int | None) -> int | None:
    for _ in range(_PEEL_DEPTH):
        name = dw.type_name(off) or ""
        if not name.startswith(_STORAGE_WRAPPERS):
            return off
        st = dw.struct_at(off)
        if st is None or "value" not in st.field_types:
            return off
        off = st.field_types["value"]
    return off


_LINK_SHELL_FIELDS = ("value", "entry")
_LINK_SHELL_DEPTH = 6


def _walk_fields(dw: DwarfSource, off: int | None, names: tuple[str, ...],
                 ) -> tuple[int | None, int | None]:
    total = 0
    for want in names:
        for _ in range(_LINK_SHELL_DEPTH):
            st = dw.struct_at(off) if off is not None else None
            if st is None:
                return None, None
            if want in st.fields:
                total += st.fields[want]
                off = st.field_types.get(want)
                break
            shell = next((f for f in _LINK_SHELL_FIELDS if f in st.fields), None)
            if shell is None and len(st.fields) == 1:
                shell = next(iter(st.fields))
            if shell is None:
                return None, None
            total += st.fields[shell]
            off = st.field_types.get(shell)
        else:
            return None, None
    return off, total


_PTR_NEWTYPES = ("core::option::Option", "Option",
                 "core::ptr::non_null::NonNull", "NonNull",
                 "core::ptr::unique::Unique", "Unique")


def option_ptr_pointee(dw: DwarfSource, off: int | None) -> int | None:
    direct = _chase_to_pointee(dw, off)
    if direct is not None:
        return direct
    name = dw.type_name(off)
    for _ in range(_PTR_CHASE_DEPTH):
        if not name:
            return None
        head = name.split("<", 1)[0]
        if head not in _PTR_NEWTYPES:
            return dw.type_off(name)
        nxt = inner_type(name)
        if nxt is None:
            return None
        name = nxt
    return None


def list_elem_die(dw: DwarfSource, type_off: int | None) -> int | None:
    head_off, _ = _walk_fields(dw, type_off, ("head",))
    return option_ptr_pointee(dw, head_off)


def list_opts(dw: DwarfSource, type_off: int | None, *,
              link: str = "links", next_field: str = "next") -> dict:
    o: dict = {}
    st = dw.struct_at(type_off) if type_off is not None else None
    if st is None:
        return o
    head_off, head_at = _walk_fields(dw, type_off, ("head",))
    if head_off is None:
        return o
    o["list_head_off"] = head_at
    elem = list_elem_die(dw, type_off)
    if elem is None:
        return o
    o["elem_type"] = dw.type_name(elem)
    _, next_at = _walk_fields(dw, elem, (link, next_field))
    if next_at is None:
        return o
    o["list_link_off"] = 0
    o["list_next_off"] = next_at
    return o
