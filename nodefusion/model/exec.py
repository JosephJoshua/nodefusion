
from __future__ import annotations

from dataclasses import dataclass, field

from .plan import Op, Plan
from .readers.registry import make as _make_reader
from .readers.registry import unwrap_reader as _unwrap_reader
from .readers.registry import via_spec as _via_spec
from .rt import Memory, ReadCtx, Unavailable, Value, is_ok


@dataclass
class Node:

    addr: int
    trail: list[str] = field(default_factory=list)

    def step(self, what: str, addr: int) -> "Node":
        return Node(addr=addr, trail=[*self.trail, what])


@dataclass
class Walk:

    nodes: list[Node] = field(default_factory=list)
    problems: list[Unavailable] = field(default_factory=list)
    truncated: bool = False
    cycles: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def fail(self, why: str, addr: int | None = None) -> "Walk":
        self.problems.append(Unavailable(why, addr))
        return self


class Executor:

    def __init__(self, mem: Memory, ctx: ReadCtx,
                 readers: dict[str, object] | None = None) -> None:
        self.mem = mem
        self.ctx = ctx
        self.readers = readers or {}


    def _reader(self, name: str):
        r = self.readers.get(name.lower())
        if r is None:
            avail = "、".join(sorted(self.readers)) or "（一个都没注册）"
            return None, f"没有叫 {name!r} 的 reader。已注册的有：{avail}"
        return r, ""

    def _plausible(self, addr: int) -> bool:
        return 0x1000 <= addr < 0xFFFF_FFFF_FFFF_F000


    def _apply(self, op: Op, nodes: list[Node], w: Walk) -> list[Node]:
        k = op.kind

        if k == "load_static":
            how = op.args.get("how", "")
            return [Node(op.args["addr"],
                         [f"{op.args['name']}@{op.args['addr']:#x}"
                          + (f"[{how}]" if how else "")])]

        if k == "percpu":
            a = op.args
            if "base_at" in a:
                base = self.mem.u64(a["base_at"])
                stride = self.mem.u64(a["stride_at"])
                ncpu = self.mem.u32(a["count_at"])
                tbase = self.mem.u64(a["template_base_at"])
                miss = [n for n, x in (("基址", base), ("步长", stride),
                                       ("CPU 个数", ncpu),
                                       ("模板基址", tbase)) if x is None]
                if miss:
                    w.fail(f"{a['name']}：per-CPU 布局读不出来（{'、'.join(miss)}"
                           f"读越界了）")
                    return []
                if not base or not ncpu:
                    w.fail(f"{a['name']}：per-CPU 区还没排布局"
                           f"（基址={base:#x} CPU 个数={ncpu}），这一帧没有")
                    return []
                off = a["template"] - tbase
            else:
                base, stride, off = a["base"], a["stride"], a["off"]
                ncpu = int(a["ncpu"])
            return [Node(base + i * stride + off, [f"{a['name']}@cpu{i}"])
                    for i in range(int(ncpu))]

        if k == "offset":
            n, name = op.args["n"], op.args.get("name", "")
            return [x.step(f"+{n}({name})", x.addr + n) for x in nodes]

        if k == "field_dyn":
            w.fail(f"字段 {op.args['name']!r} 的偏移编译期没解出来，"
                   f"运行期也没有类型信息可查")
            return []

        if k == "deref":
            out = []
            for x in nodes:
                p = self.mem.u64(x.addr)
                if p is None:
                    w.fail(f"解引用时读不到内存", x.addr)
                    continue
                if p == 0:
                    continue
                if not self._plausible(p):
                    w.fail(f"解引用读到 {p:#x}，不像个地址", x.addr)
                    continue
                out.append(x.step(f"*{x.addr:#x}", p))
            return out

        if k == "unwrap":
            chain = op.args["chain"]
            types = op.args.get("types") or [None] * len(chain)
            nested = op.args.get("nested") or [None] * len(chain)
            data_offs = op.args.get("data_offs") or [None] * len(chain)
            strong_offs = op.args.get("strong_offs") or [None] * len(chain)
            for layer, ty, nt, do, so in zip(chain, types, nested,
                                             data_offs, strong_offs):
                nodes = self._unwrap(str(layer), ty, nodes, w,
                                     nested=nt, data_off=do, strong_off=so)
            return nodes

        if k == "descend_to":
            w.fail(f"descend_to {op.args['type']!r} 应该在编译期就解成偏移了；"
                   f"运行期只有地址、没有类型，解不了。请用新版 plan.py 重编。")
            return []

        if k in ("iter", "walk", "from", "index"):
            return self._container(k, op, nodes, w)

        w.fail(f"不认识的操作 {k!r}")
        return []

    def _unwrap(self, layer: str, type_name: str | None,
                nodes: list[Node], w: Walk,
                *, nested: str | None = None,
                data_off: int | None = None,
                strong_off: int | None = None) -> list[Node]:
        r = self.readers.get(layer.lower())
        if r is None:
            r, why = _unwrap_reader(layer, type_name, nested,
                                    data_off=data_off, strong_off=strong_off)
            if r is None:
                w.fail(why)
                return []
        out = []
        for x in nodes:
            v = r(self.mem, x.addr, self.ctx)
            if isinstance(v, Unavailable):
                w.problems.append(v)
                continue
            if v is None:
                continue
            if not isinstance(v, int):
                w.fail(f"脱 {layer} 这层拿到的不是地址，是 {type(v).__name__}",
                       x.addr)
                continue
            if not self._plausible(v):
                w.fail(f"脱 {layer} 这层拿到 {v:#x}，不像个地址", x.addr)
                continue
            out.append(x.step(layer, v))
        return out

    def _container_reader(self, name: str, args: dict):
        r = self.readers.get(name.lower())
        if r is not None:
            return r, ""
        if "<" in name:
            spec = name
        elif name.lower() == "btreemap":
            kr = args.get("key")
            if not kr:
                return None, ("btreemap 遍历要写 key = \"...\" 指明键怎么读 —— "
                              "键是这一项的名字（VMId、任务号），不指定的话表里"
                              "每一行都只剩一个下标")
            spec = f"btreemap<{kr}, struct>"
        else:
            spec = f"{name}<struct>"
        rd, why = _make_reader(spec, opts=args)
        if rd is None:
            avail = "、".join(sorted(self.readers))
            extra = f"（显式注册过的：{avail}）" if avail else ""
            return None, f"{why}{extra}"
        return rd, ""

    def _container(self, k: str, op: Op, nodes: list[Node],
                   w: Walk) -> list[Node]:
        if k == "index":
            n = int(op.args["n"])
            return [x.step(f"[{n}]", x.addr + n * self.ctx.ptr_size)
                    for x in nodes]

        if k == "walk":
            return self._walk(op, nodes, w)

        name = {"iter": op.args.get("container", ""), "from": "from"}[k]
        r, why = self._container_reader(str(name), op.args)
        if r is None:
            w.fail(why)
            return []
        out: list[Node] = []
        for x in nodes:
            v = r(self.mem, x.addr, self.ctx)
            if isinstance(v, Unavailable):
                w.problems.append(v)
                continue
            if not isinstance(v, list):
                w.fail(f"{name} 应该展开成一串，实际是 {type(v).__name__}",
                       x.addr)
                continue
            for i, item in enumerate(v):
                if isinstance(item, Unavailable):
                    w.problems.append(item)
                    continue
                label = f"{name}[{i}]"
                if isinstance(item, list) and len(item) == 2:
                    k, item = item
                    if not isinstance(k, Unavailable):
                        label = f"{name}[{k}]"
                if isinstance(item, int):
                    if self._plausible(item):
                        out.append(x.step(label, item))
                    continue
                if item is not None:
                    w.fail(f"{name} 的第 {i} 项走出来是 {type(item).__name__}，"
                           f"不是一个地址；遍历没法拿它当实体，这一项被跳过了",
                           x.addr)
            if len(out) >= self.ctx.max_items:
                w.truncated = True
                del out[self.ctx.max_items:]
                break
        return out

    def _walk(self, op: Op, roots: list[Node], w: Walk) -> list[Node]:
        edge = op.args.get("edge")
        spec = edge if isinstance(edge, dict) else {"children": edge}
        path = str(spec.get("children") or spec.get("next") or "")

        name = op.args.get("reader")
        if not name:
            name, why = _via_spec(spec.get("via", op.args.get("via", [])),
                                  key=spec.get("key", op.args.get("key")))
            if name is None:
                w.fail(f"walk 造不出 reader：{why}")
                return list(roots)
        r, why = self._container_reader(str(name), op.args)
        if r is None:
            w.fail(why)
            return list(roots)

        off = self._edge_offset(path, op, w)

        seen: set[int] = set()
        out: list[Node] = []
        queue = list(roots)
        while queue:
            x = queue.pop(0)
            if x.addr in seen:
                w.cycles += 1
                continue
            seen.add(x.addr)
            out.append(x)
            if len(out) >= self.ctx.max_items:
                w.truncated = True
                break
            if off is None:
                continue
            v = r(self.mem, x.addr + off, self.ctx)
            if isinstance(v, Unavailable):
                w.problems.append(v)
                continue
            for i, kid in enumerate(v if isinstance(v, list) else []):
                if isinstance(kid, Unavailable):
                    w.problems.append(kid)
                    continue
                label = f"{path}[{i}]"
                if isinstance(kid, list) and len(kid) == 2:
                    kk, kid = kid
                    if not isinstance(kk, Unavailable):
                        label = f"{path}[{kk}]"
                if isinstance(kid, int):
                    if self._plausible(kid):
                        queue.append(x.step(label, kid))
                    continue
                if kid is not None:
                    w.fail(f"{path} 的第 {i} 项走出来是 {type(kid).__name__}，"
                           f"不是一个地址；这一支没往下走", x.addr)
        return out

    def _edge_offset(self, path: str, op: Op, w: Walk) -> int | None:
        pre = op.args.get("edge_offset")
        if pre is not None:
            return int(pre)
        off = self.ctx.layout.get("__edges__", {}).get(path)
        if off is None:
            w.fail(f"不知道 {path!r} 在对象里的偏移，走不下去")
        return off


    def run(self, plan: Plan) -> Walk:
        w = Walk()
        if not plan.compiled:
            return w.fail(f"计划没编译成功，不能跑：{plan.reason}")
        nodes: list[Node] = []
        for op in plan.ops:
            nodes = self._apply(op, nodes, w)
            if not nodes and op.kind not in ("load_static",):
                break
        w.nodes = nodes
        return w
