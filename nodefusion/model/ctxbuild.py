
from __future__ import annotations

from .dwarfsrc import DwarfSource
from .probe import ProbeResult
from .resolve import PRESENT, qualified_name
from .rt import ReadCtx


class LayoutView:

    def __init__(self, dw: DwarfSource) -> None:
        self._dw = dw
        self._cache: dict[str, dict[str, int] | None] = {}

    def get(self, name: str, default=None):
        if name in self._cache:
            return self._cache[name] if self._cache[name] is not None else default
        st = self._dw.find(name)
        got = dict(st.fields) if st is not None else None
        self._cache[name] = got
        return got if got is not None else default

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None


class FieldTypeView:

    def __init__(self, dw: DwarfSource) -> None:
        self._dw = dw
        self._cache: dict[str, dict[str, str]] = {}

    def get(self, name: str, default=None):
        got = self._cache.get(name)
        if got is None:
            st = self._dw.find(name)
            got = {}
            if st is not None:
                for fname, toff in (st.field_types or {}).items():
                    q = qualified_name(self._dw, toff)
                    if q:
                        got[fname] = q
            self._cache[name] = got
        return got or default

    def __contains__(self, name: str) -> bool:
        return bool(self.get(name))


class EnumView:

    def __init__(self, dw: DwarfSource) -> None:
        self._dw = dw
        self._cache: dict[str, dict[int, str]] = {}

    def _lookup(self, name: str) -> dict[str, int] | None:
        got = self._dw.enums.get(name)
        if got is not None:
            return got
        tail = "::" + name
        hits = [k for k in self._dw.enums if k == name or k.endswith(tail)]
        if len(hits) == 1:
            return self._dw.enums[hits[0]]
        return None

    def get(self, name: str, default=None):
        if name not in self._cache:
            raw = self._lookup(name)
            if raw is None:
                return default
            inv: dict[int, str] = {}
            for variant, val in raw.items():
                inv[val] = f"{inv[val]}/{variant}" if val in inv else variant
            self._cache[name] = inv
        return self._cache[name]

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None


def build_ctx(dw: DwarfSource, res: ProbeResult | None = None,
              *, ptr_size: int = 8, max_items: int = 4096) -> ReadCtx:
    layout = LayoutView(dw)
    edges: dict[str, int] = {}
    if res is not None:
        for e in res.entities:
            for f in e.fields:
                if f.state == PRESENT and f.offset is not None:
                    edges[f.path] = f.offset
    return ReadCtx(layout=_WithEdges(layout, edges), enums=EnumView(dw),
                   field_types=FieldTypeView(dw),
                   ptr_size=ptr_size, max_items=max_items)


class _WithEdges:

    def __init__(self, view: LayoutView, edges: dict[str, int]) -> None:
        self._view, self._edges = view, edges

    def get(self, name: str, default=None):
        if name == "__edges__":
            return self._edges
        return self._view.get(name, default)

    def __contains__(self, name: str) -> bool:
        return name == "__edges__" or name in self._view
