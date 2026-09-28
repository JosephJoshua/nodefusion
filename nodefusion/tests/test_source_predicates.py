from types import SimpleNamespace
from pathlib import Path

import pytest

from nodefusion.model.resolve import eval_when, resolve_path
from nodefusion.model.layout import StructLayout
from nodefusion.model.manifest import load


def source(symbols, process=False):
    return SimpleNamespace(defined_symbols=symbols,
                           find=lambda name: object() if process and name == 'proc' else None)


def early_stage():
    return {'all': [{'type_missing': 'proc'}, {'symbol_exists': 'clean_bss'},
                    {'symbol_missing': 'pool'}, {'symbol_missing': 'allocproc'},
                    {'symbol_missing': 'scheduler'}]}


def test_early_stage_has_no_process_table():
    assert eval_when(source({'clean_bss', 'main'}), early_stage())[0]


@pytest.mark.parametrize('symbols', [None, set(), {'clean_bss', 'pool'},
                                    {'clean_bss', 'allocproc'}, {'clean_bss', 'scheduler'}])
def test_missing_process_debug_type_does_not_hide_kernel_objects(symbols):
    assert not eval_when(source(symbols), early_stage())[0]


def test_process_type_prevents_empty_source():
    assert not eval_when(source({'clean_bss'}, process=True), early_stage())[0]


@pytest.mark.parametrize('predicate', [{'all': []}, {'all': [{}]}, {'all': 'proc'},
                                     {'all': [None]}, {'symbol_missing': ''},
                                     {'type_missing': 'proc', 'symbol_missing': 'pool'}])
def test_invalid_conditions_do_not_match(predicate):
    assert not eval_when(source({'clean_bss'}), predicate)[0]


def test_undefined_symbol_does_not_prove_presence():
    assert not eval_when(source(set()), {'symbol_exists': 'pool'})[0]
    assert not eval_when(source(None), {'symbol_missing': 'pool'})[0]


@pytest.mark.parametrize('wrapped', [False, True])
def test_rcore_task_address_fields_resolve_inline_and_cell_wrapped_layouts(wrapped):
    manifest = load(Path(__file__).resolve().parents[1] / 'manifests/rcore.toml')
    task = next(entity for entity in manifest.entities if entity.name == 'task')
    layouts = {
        1: StructLayout('PhysPageNum', 8, {'__0': 0}, field_types={'__0': 0}),
        2: StructLayout('PageTable', 32, {'root_ppn': 24}, field_types={'root_ppn': 1}),
        3: StructLayout('MemorySet', 56, {'page_table': 16}, field_types={'page_table': 2}),
        4: StructLayout('TaskData', 160, {'memory_set': 48, 'trap_cx_ppn': 120},
                        field_types={'memory_set': 3, 'trap_cx_ppn': 1}),
        5: StructLayout('UnsafeCell', 160, {'value': 0}, field_types={'value': 4}),
        6: StructLayout('UPSafeCell', 168, {'inner': 8}, field_types={'inner': 5}),
    }
    outer = (StructLayout('TaskControlBlock', 192, {'inner': 16}, field_types={'inner': 6})
             if wrapped else layouts[4])
    dwarf = SimpleNamespace(struct_at=lambda offset: layouts.get(offset),
                            type_name=lambda offset: 'usize' if offset == 0 else layouts[offset].name)
    fields = {field.name: field for field in task.fields}
    prefix = 24 if wrapped else 0
    root = resolve_path(dwarf, outer, fields['pgtbl'].path)
    context = resolve_path(dwarf, outer, fields['trapcx'].path)
    assert root.ok and root.offset == prefix + 48 + 16 + 24
    assert context.ok and context.offset == prefix + 120
    assert fields['pgtbl'].reader == fields['trapcx'].reader == 'ppn'
