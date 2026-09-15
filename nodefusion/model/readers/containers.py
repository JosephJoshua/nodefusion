
from __future__ import annotations

from dataclasses import dataclass

from ..rt import Memory, ReadCtx, Reader, Unavailable, Value

_List = list

__all__ = [
    "Incomplete", "Truncated", "Cycle", "Broken", "incomplete_of",
    "array", "vec", "vecdeque", "string", "btreemap", "strongmap", "list",
    "strong",
    "BTreeNodeLayout", "NullTerminated", "Circular",
    "BTREE_B", "BTREE_CAPACITY", "BTREE_EDGES",
]



@dataclass(frozen=True)
class Incomplete(Unavailable):
    pass


@dataclass(frozen=True)
class Truncated(Incomplete):
    pass


@dataclass(frozen=True)
class Cycle(Incomplete):
    pass


@dataclass(frozen=True)
class Broken(Incomplete):
    pass


def incomplete_of(v: Value) -> Incomplete | None:
    if isinstance(v, _List) and v and isinstance(v[-1], Incomplete):
        return v[-1]
    return None



_PTR_METHOD = {8: "u64", 4: "u32"}


def _ptr(mem: Memory, at: int, ctx: ReadCtx) -> tuple[int | None, str]:
    m = _PTR_METHOD.get(ctx.ptr_size)
    if m is None:
        return None, (f"不认识的指针宽度 {ctx.ptr_size} 字节"
                      f"（只支持 {'/'.join(map(str, sorted(_PTR_METHOD)))}）")
    v = getattr(mem, m)(at)
    if v is None:
        return None, "这个地址读不出来（没映射，或者快照没覆盖到）"
    return v, ""


def _budget(ctx: ReadCtx) -> int:
    return max(0, int(ctx.max_items))



class array:

    def __init__(self, elem_size: int, count: int, elem: Reader) -> None:
        self.elem_size = elem_size
        self.count = count
        self.elem = elem

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        if self.elem_size <= 0:
            return Unavailable(
                f"数组元素大小是 {self.elem_size}，不合法。这个值应当来自 DWARF "
                f"里元素类型的 DW_AT_byte_size", addr)
        if self.count < 0:
            return Unavailable(
                f"数组元素个数是 {self.count}，不合法。这个值应当来自 DWARF 的 "
                f"DW_AT_count", addr)
        out: _List = []
        n = min(self.count, _budget(ctx))
        for i in range(n):
            out.append(self.elem(mem, addr + i * self.elem_size, ctx))
        if n < self.count:
            out.append(Truncated(
                f"数组共 {self.count} 格，只展开了前 {n} 格就撞上 "
                f"ctx.max_items={ctx.max_items}；后面 {self.count - n} 格没读",
                addr + n * self.elem_size))
        return out



class _RawVecBased:

    _own: tuple[str, ...] = ()
    _what: str = "容器"

    def __init__(self, ctype: str, elem_size: int, elem: Reader,
                 *, raw_type: str | None = None, raw_base: int = 0,
                 unique_type: str | None = None,
                 buf_field: str = "buf", ptr_field: str = "pointer",
                 offsets: dict[str, int] | None = None) -> None:
        self.ctype = ctype
        self.elem_size = elem_size
        self.elem = elem
        self.raw_type = raw_type
        self.raw_base = raw_base
        self.unique_type = unique_type
        self.buf_field = buf_field
        self.ptr_field = ptr_field
        self.offsets = dict(offsets) if offsets else None


    def _wanted(self) -> tuple[str, ...]:
        return ("ptr", "cap", *self._own)

    def _offsets(self, ctx: ReadCtx) -> tuple[dict[str, int] | None, str]:
        want = self._wanted()

        if self.offsets and all(f in self.offsets for f in want):
            return dict(self.offsets), ""

        got: dict[str, int] = dict(self.offsets or {})
        tried: _List = []

        for f in self._own:
            if f not in got:
                o = ctx.offset(self.ctype, f)
                if o is not None:
                    got[f] = o
        tried.append(f"{self.ctype!r}.{{{','.join(self._own)}}}")

        buf = ctx.offset(self.ctype, self.buf_field)
        if buf is not None and self.raw_type is not None:
            for f in ("cap", "ptr"):
                if f in got:
                    continue
                o = ctx.offset(self.raw_type, f)
                if o is not None:
                    got[f] = buf + self.raw_base + o
            tried.append(f"{self.ctype!r}.{self.buf_field}"
                         f"{f' + {self.raw_base}' if self.raw_base else ''}"
                         f" + {self.raw_type!r}.{{cap,ptr}}")

        for f in ("cap", "ptr"):
            if f not in got:
                o = ctx.offset(self.ctype, f)
                if o is not None:
                    got[f] = o
        tried.append(f"{self.ctype!r}.{{cap,ptr}}（摊平的兜底）")

        if "ptr" in got and self.unique_type is not None:
            o = ctx.offset(self.unique_type, self.ptr_field)
            if o is not None:
                got["ptr"] += o

        missing = [f for f in want if f not in got]
        if not missing:
            return got, ""

        hint = ""
        if self.raw_type is None and ("ptr" in missing or "cap" in missing):
            hint = ("；没给 raw_type，而真实 DWARF 里 ptr/cap 挂在 RawVec 上、"
                    "不在容器上（容器只有 buf 和下标），所以查不到是意料之中")
        return None, (
            f"偏移表里查不到 {'、'.join(missing)}。查过：{'；'.join(tried)}{hint}。"
            f"这几个偏移必须来自 DWARF —— RawVec 的字段顺序是编译器定的"
            f"（rCore ch6 实测 cap 在 +0、ptr 在 +8），假定顺序会把容量当地址用")


    def _head(self, mem: Memory, addr: int, ctx: ReadCtx,
              ) -> tuple[dict[str, int] | None, int, Unavailable | None]:
        esz = self.elem_size or ctx.ptr_size
        if esz <= 0:
            return None, 0, Unavailable(
                f"{self._what} 元素大小是 {self.elem_size}，不合法（应来自 DWARF "
                f"的 DW_AT_byte_size；0 表示按 ctx.ptr_size 算，而这里 "
                f"ctx.ptr_size={ctx.ptr_size}）", addr)

        off, why = self._offsets(ctx)
        if off is None:
            return None, esz, Unavailable(
                f"解不出 {self.ctype} 的内部布局：{why}", addr)

        vals: dict[str, int] = {}
        for f in self._wanted():
            at = addr + off[f]
            v, bad = _ptr(mem, at, ctx)
            if v is None:
                return None, esz, Unavailable(
                    f"读不到 {self._what} 的 {f} 字段：{bad}", at)
            vals[f] = v
        vals["_off_ptr"] = off["ptr"]

        if vals["len"] > vals["cap"]:
            return None, esz, Unavailable(
                f"{self._what} 的 len={vals['len']} 比 cap={vals['cap']} 还大，"
                f"不可能。要么偏移解错了（{self.ctype} 的字段顺序由编译器定），"
                f"要么这块内存还没初始化", addr)

        if vals["ptr"] == 0:
            return None, esz, Unavailable(
                f"{self._what} 的 ptr 读出来是 0。Rust 里即使容器为空，ptr 也是 "
                f"align_of::<T>() 的悬垂值，不会是空指针 —— 说明 ptr 的偏移"
                f"（+{off['ptr']}）解错了，或者这块内存没初始化",
                addr + off["ptr"])

        return vals, esz, None


# --------------------------------------------------------------------- Vec

class vec(_RawVecBased):

    _own = ("len",)
    _what = "Vec"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        vals, esz, bad = self._head(mem, addr, ctx)
        if bad is not None:
            return bad
        assert vals is not None
        ptr, ln = vals["ptr"], vals["len"]

        if ln == 0:
            return []

        out: _List = []
        n = min(ln, _budget(ctx))
        for i in range(n):
            out.append(self.elem(mem, ptr + i * esz, ctx))
        if n < ln:
            out.append(Truncated(
                f"Vec 有 {ln} 个元素，只展开了前 {n} 个就撞上 "
                f"ctx.max_items={ctx.max_items}；后面 {ln - n} 个没读",
                ptr + n * esz))
        return out


# ---------------------------------------------------------------- VecDeque

class vecdeque(_RawVecBased):

    _own = ("head", "len")
    _what = "VecDeque"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        vals, esz, bad = self._head(mem, addr, ctx)
        if bad is not None:
            return bad
        assert vals is not None
        ptr, cap, head, ln = (
            vals["ptr"], vals["cap"], vals["head"], vals["len"])

        if ln == 0:
            return []

        if head >= cap:
            return Unavailable(
                f"VecDeque 的 head={head} 不小于 cap={cap}，不可能 —— head 是"
                f"环里的下标，Rust 始终把它保持在 0..cap。多半是 head 和别的"
                f"字段的偏移认反了（{self.ctype} 的字段顺序由编译器定）", addr)

        out: _List = []
        n = min(ln, _budget(ctx))
        for i in range(n):
            out.append(self.elem(mem, ptr + ((head + i) % cap) * esz, ctx))
        if n < ln:
            out.append(Truncated(
                f"VecDeque 有 {ln} 个元素，只展开了前 {n} 个就撞上 "
                f"ctx.max_items={ctx.max_items}；后面 {ln - n} 个没读",
                ptr + ((head + n) % cap) * esz))
        return out


# ------------------------------------------------------------------- String

class string(_RawVecBased):

    _own = ("len",)
    _what = "String"

    def __init__(self, ctype: str, *, str_type: str | None = None,
                 raw_type: str | None = None, raw_base: int = 0,
                 unique_type: str | None = None,
                 vec_field: str = "vec", buf_field: str = "buf",
                 ptr_field: str = "pointer", offsets: dict[str, int] | None = None,
                 encoding: str = "utf-8", max_bytes: int = 4096) -> None:
        super().__init__(ctype, 1, _noop_elem, raw_type=raw_type,
                         raw_base=raw_base,
                         unique_type=unique_type, buf_field=buf_field,
                         ptr_field=ptr_field, offsets=offsets)
        self.str_type = str_type
        self.vec_field = vec_field
        self.encoding = encoding
        self.max_bytes = max_bytes

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        base = addr
        if self.str_type is not None and self.str_type != self.ctype:
            off = ctx.offset(self.str_type, self.vec_field)
            if off is None:
                return Unavailable(
                    f"偏移表里查不到 {self.str_type!r} 的 {self.vec_field!r} "
                    f"字段，走不到里面那个 Vec<u8>。String 不是 "
                    f"repr(transparent)，vec 在 +0 是观察不是保证，所以这里"
                    f"不兜底", addr)
            base = addr + off

        vals, _esz, bad = self._head(mem, base, ctx)
        if bad is not None:
            return bad
        assert vals is not None
        ptr, ln = vals["ptr"], vals["len"]

        if ln == 0:
            return ""
        if ln > self.max_bytes:
            return Unavailable(
                f"String 的 len 读出来是 {ln}，超过上限 {self.max_bytes}。"
                f"内核里的名字不会这么长 —— 多半是偏移解错了。这里不截前 "
                f"{self.max_bytes} 字节交差：那等于拿一段来路不明的内存冒充"
                f"一个名字", base)

        raw = mem.blob(ptr, ln)
        if raw is None:
            return Unavailable(
                f"String 的 {ln} 个字节没有全落在已观察到的物理内存里", ptr)
        try:
            return raw.decode(self.encoding, "strict")
        except UnicodeDecodeError as e:
            return Unavailable(
                f"第 {e.start} 字节起不是合法 {self.encoding}"
                f"（{raw[e.start:e.start + 4]!r}）—— 这段多半不是 String。"
                f"没有用 replace 糊过去：满屏 U+FFFD 看着像读到了一个怪名字，"
                f"而实际是这里根本不是字符串", ptr)


def _noop_elem(mem: Memory, addr: int, ctx: ReadCtx) -> Value:
    return Unavailable("string 不该逐元素读", addr)



class strong:

    def __init__(self, arcinner_type: str, inner: Reader,
                 *, data_field: str = "data") -> None:
        self.arcinner_type = arcinner_type
        self.inner = inner
        self.data_field = data_field

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        data_off = ctx.offset(self.arcinner_type, self.data_field)
        if data_off is None:
            return Unavailable(
                f"偏移表里查不到 {self.arcinner_type!r} 的 {self.data_field!r} "
                f"字段。Arc 指向 ArcInner{{strong, weak, data}}，data 的偏移取决于 "
                f"T 的对齐，必须从 DWARF 读，不能按 16 写死", addr)
        p, bad = _ptr(mem, addr, ctx)
        if p is None:
            return Unavailable(f"读不到 Arc 指针：{bad}", addr)
        if p == 0:
            return Unavailable(
                "Arc 指针读出来是 0。Arc 内部是 NonNull，不可能为空 —— "
                "要么槽位算错了，要么这块内存没初始化", addr)
        return self.inner(mem, p + data_off, ctx)


# ---------------------------------------------------------------- BTreeMap

BTREE_B = 6
BTREE_CAPACITY = 2 * BTREE_B - 1     # 11
BTREE_EDGES = 2 * BTREE_B            # 12

_MAX_HEIGHT = 32


@dataclass(frozen=True)
class BTreeNodeLayout:

    noderef_height: int
    noderef_node: int
    len: int
    keys: int
    vals: int
    key_size: int
    val_size: int
    edges: int | None = None


class btreemap:

    def __init__(self, map_type: str, key: Reader, value: Reader,
                 *, node: BTreeNodeLayout | None = None,
                 root_field: str = "root", length_field: str = "length") -> None:
        self.map_type = map_type
        self.key = key
        self.value = value
        self.node = node
        self.root_field = root_field
        self.length_field = length_field


    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        root_off = ctx.offset(self.map_type, self.root_field)
        len_off = ctx.offset(self.map_type, self.length_field)
        missing = [n for n, o in ((self.root_field, root_off),
                                  (self.length_field, len_off)) if o is None]
        if missing:
            return Unavailable(
                f"偏移表里查不到 {self.map_type!r} 的 {'、'.join(missing)} 字段，"
                f"无法定位 BTreeMap 的根和长度", addr)

        length, bad = _ptr(mem, addr + len_off, ctx)
        if length is None:
            return Unavailable(
                f"读不到 BTreeMap 的 {self.length_field}：{bad}", addr + len_off)

        L = self.node
        if L is None:
            if length == 0:
                return []
            return Unavailable(
                f"这个 BTreeMap 有 {length} 项，但没有给出结点布局，无法枚举。"
                f"LeafNode<K,V>/InternalNode<K,V> 是 alloc 里的私有类型，DWARF "
                f"里通常没有，而且 ctx.layout 只有偏移、装不下 K/V 的大小 —— "
                f"请由调用方量好 BTreeNodeLayout 传进来", addr)

        node_at = addr + root_off + L.noderef_node
        root_ptr, bad = _ptr(mem, node_at, ctx)
        if root_ptr is None:
            return Unavailable(f"读不到 BTreeMap 的根结点指针：{bad}", node_at)

        if root_ptr == 0:
            if length != 0:
                return Unavailable(
                    f"BTreeMap 的 root 是 None（根指针为 0）但 length={length}，"
                    f"两者对不上。要么 root/length 的偏移解错了，要么这块内存"
                    f"没初始化", addr)
            return []

        h_at = addr + root_off + L.noderef_height
        height, bad = _ptr(mem, h_at, ctx)
        if height is None:
            return Unavailable(f"读不到 BTreeMap 根结点的 height：{bad}", h_at)
        if height > _MAX_HEIGHT:
            return Unavailable(
                f"BTreeMap 根结点的 height 读出来是 {height}，远超合理范围"
                f"（上限 {_MAX_HEIGHT}）。B=6 的树装下 {length} 项用不了这么高 —— "
                f"多半是 NodeRef 的 height/node 偏移认反了", h_at)

        out: _List = []
        budget = {"items": _budget(ctx), "nodes": _budget(ctx)}
        stop = self._visit(mem, ctx, root_ptr, height, out, set(), budget)
        if stop is not None:
            out.append(stop)
            return out

        if len(out) != length:
            out.append(Broken(
                f"遍历出 {len(out)} 项，但 BTreeMap.length 说有 {length} 项，"
                f"对不上。结点布局或 K/V 的步长多半解错了，这份结果不可信", addr))
        return out


    def _visit(self, mem: Memory, ctx: ReadCtx, at: int, height: int,
               out: _List, seen: set, budget: dict) -> Incomplete | None:
        L = self.node
        assert L is not None

        if at in seen:
            return Cycle(f"B 树里出现环：结点 {at:#x} 被第二次走到，"
                         f"树结构已经坏了", at)
        if budget["nodes"] <= 0:
            return Truncated(
                f"展开的结点数撞上 ctx.max_items={ctx.max_items}，"
                f"从 {at:#x} 起的子树没有继续走", at)
        seen.add(at)
        budget["nodes"] -= 1

        n = mem.u16(at + L.len)
        if n is None:
            return Broken(f"读不到结点 {at:#x} 的 len 字段", at + L.len)
        if n > BTREE_CAPACITY:
            return Broken(
                f"结点 {at:#x} 的 len={n}，超过 B=6 时的上限 {BTREE_CAPACITY}。"
                f"说明 LeafNode 的 len 偏移解错了，或者这块内存不是 B 树结点",
                at + L.len)

        if height == 0:
            return self._emit(mem, ctx, at, 0, n, out, budget)

        if L.edges is None:
            return Broken(
                f"结点 {at:#x} 是内部结点（height={height}），但 BTreeNodeLayout "
                f"里没给 edges 的偏移，走不下去。只给叶子布局就只能读单层的树 —— "
                f"这里不会把这棵子树当成空的", at)

        for i in range(n + 1):
            e_at = at + L.edges + i * ctx.ptr_size
            child, bad = _ptr(mem, e_at, ctx)
            if child is None:
                return Broken(f"读不到结点 {at:#x} 的第 {i} 条边：{bad}", e_at)
            if child == 0:
                return Broken(
                    f"结点 {at:#x} 的第 {i} 条边是空指针，但它是内部结点、"
                    f"len={n}，前 {n + 1} 条边都该有。子树读不全", e_at)
            stop = self._visit(mem, ctx, child, height - 1, out, seen, budget)
            if stop is not None:
                return stop
            if i < n:
                stop = self._emit(mem, ctx, at, i, i + 1, out, budget)
                if stop is not None:
                    return stop
        return None


    def _emit(self, mem: Memory, ctx: ReadCtx, at: int, lo: int, hi: int,
              out: _List, budget: dict) -> Incomplete | None:
        L = self.node
        assert L is not None
        for i in range(lo, hi):
            if budget["items"] <= 0:
                return Truncated(
                    f"已展开 {len(out)} 项，撞上 ctx.max_items={ctx.max_items}；"
                    f"结点 {at:#x} 的第 {i} 项起没有继续读", at)
            budget["items"] -= 1
            k = self.key(mem, at + L.keys + i * L.key_size, ctx)
            v = self.value(mem, at + L.vals + i * L.val_size, ctx)
            out.append([k, v])
        return None



class strongmap:

    def __init__(self, make_map, arcinner_type: str | None = None,
                 value: Reader | None = None, *, data_field: str = "data",
                 hop: Reader | None = None) -> None:
        if hop is None:
            if arcinner_type is None or value is None:
                raise ValueError(
                    "strongmap 要么给 hop，要么把 arcinner_type 和 value 都给全")
            hop = strong(arcinner_type, value, data_field=data_field)
        self.hop = hop
        self.inner = make_map(hop)

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return self.inner(mem, addr, ctx)



@dataclass(frozen=True)
class NullTerminated:

    sentinel: int = 0


@dataclass(frozen=True)
class Circular:
    pass


@dataclass(frozen=True)
class CircularHeaded:
    pass


class list:

    def __init__(self, link_off: int, next_off: int, elem: Reader,
                 *, terminator: NullTerminated | Circular | CircularHeaded
                 = NullTerminated()) -> None:
        self.link_off = link_off
        self.next_off = next_off
        self.elem = elem
        self.terminator = terminator

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        if self.link_off < 0 or self.next_off < 0:
            return Unavailable(
                f"链表偏移不合法：link_off={self.link_off}、"
                f"next_off={self.next_off}，两者都该来自 DWARF", addr)

        rule = self.terminator
        circular = isinstance(rule, Circular)
        headed = isinstance(rule, CircularHeaded)
        if circular:
            head_at = addr + self.next_off
        elif headed or isinstance(rule, NullTerminated):
            head_at = addr
        else:
            return Unavailable(
                f"不认识的链表终止规则 {type(rule).__name__!r}，"
                f"只支持 NullTerminated / Circular / CircularHeaded", addr)

        link, bad = _ptr(mem, head_at, ctx)
        if link is None:
            return Unavailable(f"读不到链表头指针：{bad}", head_at)

        first = link

        out: _List = []
        seen: set = set()
        cap = _budget(ctx)
        while True:
            if circular:
                if link == addr:
                    break
            elif headed:
                if link == 0 or (out and link == first):
                    break
            elif link == rule.sentinel:
                break

            if link in seen:
                out.append(Cycle(
                    f"链表成环：link {link:#x} 被第二次走到（已经走了 "
                    f"{len(out)} 个元素）。这条链已经坏了，不是走到头了", link))
                break
            if len(out) >= cap:
                out.append(Truncated(
                    f"已展开 {len(out)} 个元素，撞上 ctx.max_items="
                    f"{ctx.max_items}；从 link {link:#x} 起没有继续走", link))
                break

            elem_at = link - self.link_off
            if elem_at < 0:
                out.append(Broken(
                    f"link 在 {link:#x}，减去 link_off={self.link_off} 之后是负数，"
                    f"算不出元素地址 —— link_off 多半解错了", link))
                break

            seen.add(link)
            out.append(self.elem(mem, elem_at, ctx))

            nxt_at = link + self.next_off
            nxt, bad = _ptr(mem, nxt_at, ctx)
            if nxt is None:
                out.append(Broken(
                    f"读不到第 {len(out)} 个元素的 next 指针：{bad}。"
                    f"链表在这里断了，后面还有多少不知道", nxt_at))
                break
            link = nxt

        return out
