from copy import deepcopy
from types import SimpleNamespace

from nodefusion.host.analyze import Event
from scripts.enrich_report_sources import enrich


def test_enrichment_preserves_snapshots_and_event_parameters(monkeypatch):
    raw = '_ZN2os3run17h0123456789abcdefE'
    event = Event(insn=10, cpu=0, kind='func.run', resource='task', pc=4096,
                  func=raw, function_entry=True, entry_name=raw)
    analysis = SimpleNamespace(events=[event], build_events=lambda: None,
                               trace=SimpleNamespace(function_returns=[]),
                               elf=SimpleNamespace(resolve_pc=lambda pc: (raw, 0)), kernel_elf_path=None)
    data = {'meta': {}, 'dict': {'funcs': ['os::run'], 'kinds': ['func.run']},
            'states': [{'procs': [{'pid': 7}], 'phys': [[1, 0, 32]]}],
            'metrics': {'by_kind': {'func.run': 1}},
            'events': {'insn': [10], 'cpu': [0], 'pc': [4096], 'entry': [1],
                       'func': [0], 'kind': [0], 'pid': [7], 'detail': [{'result': 42}]}}
    original = deepcopy(data)
    monkeypatch.setattr('scripts.enrich_report_sources.full_names', lambda names: ['os::run'])
    monkeypatch.setattr('scripts.enrich_report_sources.build_source', lambda *a, **k: {'files': [], 'locations': {}})
    enrich(data, analysis)
    assert data['states'] == original['states']
    assert data['metrics'] == original['metrics']
    for key in ('insn', 'cpu', 'pc', 'entry', 'kind', 'pid', 'detail'):
        assert data['events'][key] == original['events'][key]
    assert data['dict']['raw_funcs'] == [raw]
    assert data['dict']['full_funcs'] == ['os::run']


def test_enrichment_rejects_unmatched_recorded_entry(monkeypatch):
    import pytest
    analysis = SimpleNamespace(events=[], build_events=lambda: None)
    data = {'events': {'insn': [10], 'cpu': [0], 'pc': [4096], 'entry': [1]}}
    with pytest.raises(ValueError, match='recorded function entry not found'):
        enrich(data, analysis)


def test_event_only_analysis_cannot_decode_snapshots():
    import pytest
    from nodefusion.host.analyze import Analysis
    analysis = Analysis.__new__(Analysis)
    analysis._event_only = True
    with pytest.raises(ValueError, match='cannot rebuild snapshots'):
        analysis.rebuild_states()
