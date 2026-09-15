
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model.layout import StructLayout       # noqa: E402
from nodefusion.model.manifest import SourceSpec       # noqa: E402
from nodefusion.model.plan import compile_source       # noqa: E402

MAP, OPT, REF, NN, LEAF = 10, 11, 12, 13, 14
KARR, VARR, MU, MD, VAL, INTER, U64 = 15, 16, 17, 18, 19, 20, 21

REG_ADDR = 0x8020_0000

MAP_NAME = "BTreeMap<u64, axvm::VmRef, alloc::alloc::Global>"
LEAF_NAME = "LeafNode<u64, axvm::VmRef>"


class FakeVar:
    def __init__(self, name, addr, type_off):
        self.name = self.path = name
        self.addr, self.type_off = addr, type_off


class FakeDw:

    def __init__(self):
        self._structs = {
            MAP: StructLayout(name="BTreeMap<K, V, A>", path=MAP_NAME, size=24,
                              fields={"root": 0, "length": 16},
                              field_types={"root": OPT}),
            OPT: StructLayout(name="Option<NodeRef<u64, axvm::VmRef>>",
                              path="core::option::Option<NodeRef<u64, axvm::VmRef>>",
                              size=16, fields={}, field_types={}),
            REF: StructLayout(name="NodeRef<u64, axvm::VmRef>",
                              path="NodeRef<u64, axvm::VmRef>", size=16,
                              fields={"node": 0, "height": 8},
                              field_types={"node": NN}),
            LEAF: StructLayout(name=LEAF_NAME, path=LEAF_NAME, size=192,
                               fields={"parent": 0, "keys": 8, "vals": 96,
                                       "parent_idx": 184, "len": 186},
                               field_types={"keys": KARR, "vals": VARR}),
            MU: StructLayout(name="MaybeUninit<ManuallyDrop<axvm::VmRef>>",
                             path="MaybeUninit<ManuallyDrop<axvm::VmRef>>",
                             size=16, fields={"uninit": 0, "value": 0},
                             field_types={"uninit": MD, "value": MD}),
            MD: StructLayout(name="ManuallyDrop<axvm::VmRef>",
                             path="ManuallyDrop<axvm::VmRef>", size=16,
                             fields={"value": 0}, field_types={"value": VAL}),
            VAL: StructLayout(name="VmRef", path="axvm::VmRef", size=16,
                              fields={"id": 0, "name": 8}),
            INTER: StructLayout(name="InternalNode<u64, axvm::VmRef>",
                                path="InternalNode<u64, axvm::VmRef>", size=288,
                                fields={"data": 0, "edges": 192}),
        }
        self._names = {
            MAP: MAP_NAME, OPT: "Option<NodeRef<u64, axvm::VmRef>>",
            REF: "NodeRef<u64, axvm::VmRef>", NN: "NonNull<LeafNode<..>>",
            LEAF: LEAF_NAME, KARR: "[u64; 11]", VARR: "[MaybeUninit<..>; 11]",
            MU: "MaybeUninit<ManuallyDrop<axvm::VmRef>>",
            MD: "ManuallyDrop<axvm::VmRef>", VAL: "axvm::VmRef", U64: "u64",
            INTER: "InternalNode<u64, axvm::VmRef>",
        }
        self._sizes = {U64: 8, MU: 16, MD: 16, VAL: 16}

    def struct_at(self, off):
        return self._structs.get(off)

    def type_name(self, off):
        return self._names.get(off)

    def find(self, name):
        return next((s for s in self._structs.values()
                     if s.path == name or s.name == name), None)

    def type_off(self, name):
        return next((o for o, s in self._structs.items()
                     if s.path == name or s.name == name), None)

    def var(self, name):
        return FakeVar(name, REG_ADDR, MAP) if name == "VM_REGISTRY" else None

    def var_at(self, _addr):
        return None

    def array_of(self, off):
        return {KARR: (U64, 11), VARR: (MU, 11)}.get(off)

    def size_of(self, off):
        s = self._structs.get(off)
        return s.size if s is not None else self._sizes.get(off)

    def pointee(self, off):
        return LEAF if off == NN else None


def _plan(steps):
    return compile_source(FakeDw(), "vm",
                          SourceSpec(kind="registry", completeness="total",
                                     steps=steps), struct_path="axvm::VmRef")


ITER = {"iter": "btreemap", "key": "u64"}
STATIC = {"static": "VM_REGISTRY"}


def test_iter_btreemap_fills_in_the_map_type_and_the_whole_node_layout():
    p = _plan([STATIC, ITER])
    assert p.compiled, p.reason
    it = p.ops[-1]
    assert it.kind == "iter"
    assert it.args["btree_map_type"] == MAP_NAME
    assert it.args["key"] == "u64"
    assert {k: v for k, v in it.args.items() if k.startswith("btree_") } == {
        "btree_map_type": MAP_NAME,
        "btree_noderef_height": 8, "btree_noderef_node": 0,
        "btree_len": 186, "btree_keys": 8, "btree_vals": 96,
        "btree_key_size": 8, "btree_val_size": 16, "btree_edges": 192}


def test_the_cursor_after_iter_is_the_value_type_not_the_map():
    p = _plan([STATIC, ITER, {"field": "name"}])
    assert p.compiled, p.reason
    kinds = [o.kind for o in p.ops]
    assert "field_dyn" not in kinds, (
        f"iter 之后类型丢了，字段退成运行期解析：{p.trace}")
    assert p.ops[-1].kind == "offset" and p.ops[-1].args["n"] == 8, p.trace


def test_the_value_type_is_found_through_dwarf_not_by_splitting_the_name():
    dw = FakeDw()
    assert dw.type_name(dw.array_of(VARR)[0]).startswith("MaybeUninit")
    assert dw.type_name(dw.struct_at(MU).field_types["value"]).startswith(
        "ManuallyDrop")


def test_a_half_measured_layout_is_left_out_entirely():
    class NoVals(FakeDw):
        def __init__(self):
            super().__init__()
            leaf = self._structs[LEAF]
            self._structs[LEAF] = StructLayout(
                name=leaf.name, path=leaf.path, size=leaf.size,
                fields={k: v for k, v in leaf.fields.items() if k != "vals"},
                field_types=leaf.field_types)

    p = compile_source(NoVals(), "vm",
                       SourceSpec(kind="registry", completeness="total",
                                  steps=[STATIC, ITER]),
                       struct_path="axvm::VmRef")
    it = p.ops[-1]
    assert not [k for k in it.args if k.startswith("btree_")
                and k != "btree_map_type"], it.args


def test_a_non_map_iter_is_untouched_by_the_btreemap_branch():
    p = _plan([STATIC, {"iter": "array"}])
    assert not [k for k in p.ops[-1].args if k.startswith("btree_")]
