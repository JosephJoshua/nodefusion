
from __future__ import annotations

from ..rt import Memory, ReadCtx, Reader, Unavailable, Value

__all__ = [
    "Ptr", "Arc", "Weak", "OptionArc", "OptionWeak",
    "UnsafeCell", "UpSafeCell", "SpinLock", "Mutex", "SpinRwLock",
    "LazyInit", "Lazy", "LazyLock",
]



def _read_ptr(mem: Memory, addr: int, ctx: ReadCtx) -> int | None:
    if ctx.ptr_size == 8:
        return mem.u64(addr)
    if ctx.ptr_size == 4:
        return mem.u32(addr)
    return None


def _chain_off(ctx: ReadCtx, chain) -> int | None:
    total = 0
    prev: tuple[str, str] | None = None
    for type_name, field in chain:
        if not type_name and prev is not None:
            type_name = ctx.field_type(*prev)
        if not type_name:
            return None
        off = ctx.offset(type_name, field)
        if off is None:
            return None
        total += off
        prev = (type_name, field)
    return total


def _resolve(ctx: ReadCtx, chains) -> tuple[int, str] | None:
    for chain in chains:
        off = _chain_off(ctx, chain)
        if off is not None:
            via = " -> ".join(f"{t}.{f}" for t, f in chain)
            return off, f"DWARF（{via}）"
    return None


def _want(chains) -> str:
    return "、".join(
        " -> ".join(f"{t or '（构造时没给类型名，也没能从上一跳的字段推出来）'}.{f}"
                    for t, f in c)
        for c in chains) or "（没有候选）"


_WHY_NO_GUESS = (
    "包装层的字段顺序由编译器决定（repr(Rust) 允许重排），不是语言保证。"
    "实测 rCore ch6 是 Lazy{__0:0}、UPSafeCell{inner:0}、"
    "RefCell{borrow:0,value:8}，但那是那一个二进制的观察，不是承诺。"
    "拿常数兜底会落在同一个对象的**别的字段**上（比如把 RefCell 的借用标志"
    "当成内容），读出来像模像样却是错的，所以这里宁可说查不到")


def _no_offset(what: str, cls: str, chains, addr: int) -> Unavailable:
    return Unavailable(
        f"查不到 {cls} 的{what}偏移：DWARF 布局表里没有 {_want(chains)}。"
        f"{_WHY_NO_GUESS}", addr)


# ===========================================================================
# ===========================================================================

_MIN_PLAUSIBLE = 0x1000

_TOP_PAGE = 0x1000

_OK, _NULL, _SENTINEL, _MISALIGNED = "ok", "null", "sentinel", "misaligned"


def _classify(p: int, ctx: ReadCtx, min_addr: int) -> str:
    if p == 0:
        return _NULL
    if p < min_addr:
        return _SENTINEL
    if p >= (1 << (8 * ctx.ptr_size)) - _TOP_PAGE:
        return _SENTINEL
    if p % ctx.ptr_size:
        return _MISALIGNED
    return _OK


class _ArcLike:

    def __init__(self, inner: Reader | None = None, *,
                 inner_type: str | None = None,
                 data_off: int | None = None,
                 strong_off: int | None = None,
                 min_addr: int = _MIN_PLAUSIBLE) -> None:
        self.inner = inner
        self.inner_type = inner_type
        self.data_off = data_off
        self.strong_off = strong_off
        self.min_addr = min_addr

    def _data_off(self, ctx: ReadCtx) -> tuple[int, str]:
        if self.data_off is not None:
            return self.data_off, "DWARF 量的（ArcInner.data）"
        got = _resolve(ctx, [((self.inner_type, "data"),)])
        if got is not None:
            return got
        return 2 * ctx.ptr_size, (
            f"假设 +{2 * ctx.ptr_size}（= 2*ptr_size，riscv64 rCore 实测相符；"
            f"DWARF 里查不到 {self.inner_type or '（构造时没给 ArcInner 类型名）'}"
            f".data）")

    def provenance(self, ctx: ReadCtx) -> str:
        off, how = self._data_off(ctx)
        return (f"{type(self).__name__}（解引用后 ArcInner.data 在 +{off}，"
                f"{how}）")

    def _follow(self, mem: Memory, p: int, ctx: ReadCtx) -> Value:
        off, how = self._data_off(ctx)
        payload = p + off
        if self.inner is None:
            return payload
        got = self.inner(mem, payload, ctx)
        if isinstance(got, Unavailable) and how.startswith("假设"):
            return Unavailable(f"{got.reason}（ArcInner.data 的偏移是{how}）",
                               got.addr if got.addr is not None else payload)
        return got


class Ptr:

    def __init__(self, inner: Reader | None = None, *,
                 null_is_absent: bool = True) -> None:
        self.inner = inner
        self.null_is_absent = null_is_absent

    def provenance(self, ctx: ReadCtx) -> str:
        return f"Ptr（读 {ctx.ptr_size} 字节指针，不加偏移）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        p = _read_ptr(mem, addr, ctx)
        if p is None:
            return Unavailable(
                f"读不出指针（要 {ctx.ptr_size} 字节），地址不在快照范围内", addr)
        if p == 0 and self.null_is_absent:
            return None
        return self.inner(mem, p, ctx) if self.inner else p


class Arc(_ArcLike):

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        p = _read_ptr(mem, addr, ctx)
        if p is None:
            return Unavailable(
                f"读不出 Arc 的指针（要 {ctx.ptr_size} 字节），"
                f"地址不在快照范围内", addr)

        kind = _classify(p, ctx, self.min_addr)
        if kind == _NULL:
            return None
        if kind == _SENTINEL:
            return Unavailable(
                f"Arc 指向 {p:#x}，这不像个真地址（低于 {self.min_addr:#x} "
                f"或落在地址空间顶端）。活着的 Arc 不会指到这里，"
                f"多半是这块内存还没初始化，或者起始地址取错了", addr)
        if kind == _MISALIGNED:
            return Unavailable(
                f"Arc 指向 {p:#x}，没有按 {ctx.ptr_size} 字节对齐。"
                f"ArcInner 以 AtomicUsize 开头必然对齐，所以这个地址读错了位置",
                addr)
        return self._follow(mem, p, ctx)


class Weak(_ArcLike):

    def provenance(self, ctx: ReadCtx) -> str:
        off, how = self._data_off(ctx)
        return (f"Weak（悬垂阈值 {self.min_addr:#x}；"
                f"解引用后 ArcInner.data 在 +{off}，{how}）")

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        p = _read_ptr(mem, addr, ctx)
        if p is None:
            return Unavailable(
                f"读不出 Weak 的指针（要 {ctx.ptr_size} 字节），"
                f"地址不在快照范围内", addr)

        kind = _classify(p, ctx, self.min_addr)
        if kind in (_NULL, _SENTINEL):
            return None
        if kind == _MISALIGNED:
            return Unavailable(
                f"Weak 指向 {p:#x}，没有按 {ctx.ptr_size} 字节对齐。"
                f"这既不是空、也不像哨兵，更像是起始地址取错了", addr)

        if self.strong_off is not None:
            strong = _read_ptr(mem, p + self.strong_off, ctx)
            if strong == 0:
                return None
        return self._follow(mem, p, ctx)


class OptionArc(Arc):
    pass


class OptionWeak(Weak):
    pass


# ===========================================================================
# ===========================================================================

class UnsafeCell:

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None) -> None:
        self.inner = inner
        self.type_name = type_name

    def provenance(self, ctx: ReadCtx) -> str:
        return "UnsafeCell（repr(transparent)，内容在 +0，语言保证）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return self.inner(mem, addr, ctx) if self.inner else addr


class MaybeDangling:

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None) -> None:
        self.inner = inner
        self.type_name = type_name

    def provenance(self, ctx: ReadCtx) -> str:
        return "MaybeDangling（repr(transparent)，内容在 +0，语言保证且实测过）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return self.inner(mem, addr, ctx) if self.inner else addr


class MaybeUninit:

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None) -> None:
        self.inner = inner
        self.type_name = type_name

    def provenance(self, ctx: ReadCtx) -> str:
        return "MaybeUninit（union，值在 +0，语言保证且实测过）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        return self.inner(mem, addr, ctx) if self.inner else addr


class _Inline:

    _chains: tuple = ()
    _what: str = "内容"

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None) -> None:
        self.inner = inner
        self.type_name = type_name

    def _chain_list(self):
        return tuple(tuple((self.type_name if t is None else t, f)
                           for t, f in chain) for chain in self._chains)

    def provenance(self, ctx: ReadCtx) -> str:
        got = _resolve(ctx, self._chain_list())
        if got is None:
            return (f"{type(self).__name__}（{self._what}偏移查不到："
                    f"{_want(self._chain_list())}）")
        return f"{type(self).__name__}（{self._what}在 +{got[0]}，{got[1]}）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        got = _resolve(ctx, self._chain_list())
        if got is None:
            return _no_offset(self._what, type(self).__name__,
                              self._chain_list(), addr)
        payload = addr + got[0]
        return self.inner(mem, payload, ctx) if self.inner else payload


class UpSafeCell(_Inline):

    _chains = (
        ((None, "inner"), ("__cell__", "value")),   # UPSafeCell -> RefCell
        ((None, "value"),),
        ((None, "data"),),
    )

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None,
                 cell_type: str | None = None) -> None:
        super().__init__(inner, type_name=type_name)
        self.cell_type = cell_type

    def _chain_list(self):
        out = []
        for chain in self._chains:
            out.append(tuple(
                ((self.cell_type if t == "__cell__"
                  else self.type_name if t is None else t), f)
                for t, f in chain))
        return tuple(out)


class SpinLock(_Inline):

    _chains = (
        ((None, "data"),),
        ((None, "value"),),
        ((None, "__0"), ("__base__", "data")),
    )

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None,
                 base_type: str | None = None) -> None:
        super().__init__(inner, type_name=type_name)
        self.base_type = base_type

    def _chain_list(self):
        return tuple(tuple(
            ((self.base_type if t == "__base__"
              else self.type_name if t is None else t), f)
            for t, f in chain) for chain in self._chains)


class Mutex(_Inline):

    _chains = (
        ((None, "inner"), ("__ticket__", "value")),   # Mutex -> TicketMutex
        ((None, "data"),),
        ((None, "value"),),
    )

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None,
                 ticket_type: str | None = None) -> None:
        super().__init__(inner, type_name=type_name)
        self.ticket_type = ticket_type

    def _chain_list(self):
        return tuple(tuple(
            ((self.ticket_type if t == "__ticket__"
              else self.type_name if t is None else t), f)
            for t, f in chain) for chain in self._chains)


class SpinRwLock(_Inline):

    _chains = (
        ((None, "data"),),
        ((None, "__0"), ("__base__", "data")),
    )

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None,
                 base_type: str | None = None) -> None:
        super().__init__(inner, type_name=type_name)
        self.base_type = base_type

    def _chain_list(self):
        return tuple(tuple(
            ((self.base_type if t == "__base__"
              else self.type_name if t is None else t), f)
            for t, f in chain) for chain in self._chains)


# ===========================================================================
# ===========================================================================

class LazyInit(_Inline):

    _chains = (((None, "data"),), ((None, "value"),))
    _flags = (((None, "inited"),), ((None, "is_inited"),))

    def _flag_chain(self):
        return tuple(tuple((self.type_name if t is None else t, f)
                           for t, f in c) for c in self._flags)

    def provenance(self, ctx: ReadCtx) -> str:
        f = _resolve(ctx, self._flag_chain())
        d = _resolve(ctx, self._chain_list())
        fs = f"inited 在 +{f[0]}，{f[1]}" if f else "inited 偏移查不到"
        ds = f"内容在 +{d[0]}，{d[1]}" if d else "内容偏移查不到"
        return f"LazyInit（{fs}；{ds}）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        flag_at = _resolve(ctx, self._flag_chain())
        if flag_at is None:
            return _no_offset("inited 标志", "LazyInit", self._flag_chain(), addr)

        f_off, f_how = flag_at
        flag = mem.u8(addr + f_off)
        if flag is None:
            return Unavailable(
                f"读不出 LazyInit 的 inited 标志（在 +{f_off}，{f_how}），"
                f"地址不在快照范围内", addr + f_off)
        if flag == 0:
            return Unavailable(
                f"LazyInit 还没初始化（inited=0，在 +{f_off}），"
                f"内容是未初始化内存，读出来是垃圾。"
                f"快照可能抓在 init() 之前", addr)
        return super().__call__(mem, addr, ctx)


class Lazy(_Inline):

    _chains = (((None, "__0"), ("__once__", "data")),
               ((None, "__0"), ("__once__", "value")),
               ((None, "cell"), ("__once__", "data")),
               ((None, "cell"), ("__once__", "value")),
               ((None, "data"),), ((None, "value"),))
    _states = (((None, "__0"), ("__once__", "status")),
               ((None, "__0"), ("__once__", "state")),
               ((None, "cell"), ("__once__", "status")),
               ((None, "cell"), ("__once__", "state")),
               ((None, "status"),), ((None, "state"),))

    _NAMES = {0: "Incomplete（还没开始初始化）", 1: "Running（正在初始化）",
              2: "Complete（已完成）", 3: "Panicked（初始化时崩了）"}

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None,
                 once_type: str | None = None,
                 status_enum: str | None = None,
                 complete: int = 2) -> None:
        super().__init__(inner, type_name=type_name)
        self.once_type = once_type
        self.status_enum = status_enum
        self.complete = complete

    def _subst(self, chains):
        return tuple(tuple(
            ((self.once_type if t == "__once__"
              else self.type_name if t is None else t), f)
            for t, f in c) for c in chains)

    def _chain_list(self):
        return self._subst(self._chains)

    def _state_chain(self):
        return self._subst(self._states)

    def _complete_value(self, ctx: ReadCtx) -> tuple[int, str]:
        tbl = ctx.enums.get(self.status_enum or "") or {}
        for k, v in tbl.items():
            if str(v).lower() == "complete":
                return k, f"DWARF（{self.status_enum}）"
        return self.complete, f"假设 Complete=={self.complete}（spin crate 的常数）"

    def provenance(self, ctx: ReadCtx) -> str:
        s = _resolve(ctx, self._state_chain())
        d = _resolve(ctx, self._chain_list())
        done, c_how = self._complete_value(ctx)
        ss = f"status 在 +{s[0]}，{s[1]}" if s else "status 偏移查不到"
        ds = f"内容在 +{d[0]}，{d[1]}" if d else "内容偏移查不到"
        return f"Lazy（{ss}；{ds}；Complete=={done}，{c_how}）"

    def __call__(self, mem: Memory, addr: int, ctx: ReadCtx) -> Value:
        state_at = _resolve(ctx, self._state_chain())
        if state_at is None:
            return _no_offset("status 状态字", "Lazy", self._state_chain(), addr)

        s_off, s_how = state_at
        st = mem.u8(addr + s_off)
        if st is None:
            return Unavailable(
                f"读不出 Lazy/Once 的状态字（在 +{s_off}，{s_how}），"
                f"地址不在快照范围内", addr + s_off)

        done, c_how = self._complete_value(ctx)
        if st != done:
            what = self._NAMES.get(st, f"未知状态 {st}")
            return Unavailable(
                f"Lazy/Once 的状态是 {st}={what}，不是 Complete（{done}，{c_how}）。"
                f"内容还是未初始化内存，读出来是垃圾", addr)
        return super().__call__(mem, addr, ctx)


class LazyLock(_Inline):

    _chains = (
        ((None, "value"), ("__once__", "__0")),
        ((None, "value"), ("__once__", "0")),
    )

    def __init__(self, inner: Reader | None = None, *,
                 type_name: str | None = None,
                 once_type: str | None = None) -> None:
        super().__init__(inner, type_name=type_name)
        self.once_type = once_type

    def _chain_list(self):
        return tuple(tuple(
            ((self.once_type if t == "__once__"
              else self.type_name if t is None else t), f)
            for t, f in chain) for chain in self._chains)
