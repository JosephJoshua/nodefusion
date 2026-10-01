"""Rebuild archived reports with source metadata, preserving audited report data.

Source locations and observed stacks are reconstructed from the matching ELF
and trace. Existing snapshot refinements, event parameters, and sampling stay
unchanged. Source roots must refer to the recorded revision.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import zlib
from collections import defaultdict, deque
from pathlib import Path

from nodefusion.host.analyze import Analysis
from nodefusion.host.bundle import Interner, encode
from nodefusion.host.callstack import observed_stacks
from nodefusion.host.render import ASSETS, _PAGE, report_javascript
from nodefusion.host.sourceview import build_source, full_names, load_snapshot
from nodefusion.model.symbols import display_name
from scripts.regenerate_artifact import sha256

DATA = re.compile(r'(<script type="application/nodefusion"[^>]*>)([^<]+)(</script>)')


def enrich(data: dict, analysis: Analysis, *, roots=(), maps=()) -> dict:
    analysis.build_events()
    ev = data['events']
    lookup = defaultdict(deque)
    legacy = 'entry' not in ev
    keys = [(insn, ev['cpu'][i], int(ev['pc'][i], 0) if isinstance(ev['pc'][i], str) else ev['pc'][i] or 0,
             None if legacy else bool(ev['entry'][i])) for i, insn in enumerate(ev['insn'])]
    wanted = set(keys)
    for event in analysis.events:
        key = (event.insn, event.cpu, int(event.pc or 0), None if legacy else bool(event.function_entry))
        if key in wanted: lookup[key].append(event)
    retained = []
    for key in keys:
        event = lookup[key].popleft() if lookup[key] else None
        if key[3] and event is None:
            raise ValueError(f'recorded function entry not found: {key}')
        retained.append(event)
    if legacy:
        ev['entry'] = [int(bool(event and event.function_entry)) for event in retained]
        data['meta']['function_entries'] = {'raw': sum(event.function_entry for event in analysis.events),
                                            'retained': sum(ev['entry'])}
    pcs = {}
    stacks, counts = observed_stacks(analysis.events, analysis.trace.function_returns, analysis.elf,
                                    retained_ids={id(event) for event in retained if event}, raw_names=True, frame_pcs=pcs)
    funcs = Interner()
    old = data['dict']['funcs']
    columns = {key: [] for key in ('func', 'entry_name', 'caller', 'stack', 'stack_pc', 'caller_pc')}
    for i, event in enumerate(retained):
        pc = int(ev['pc'][i], 0) if isinstance(ev['pc'][i], str) else ev['pc'][i]
        raw = event.func if event else analysis.elf.resolve_pc(pc)[0] if pc else None
        columns['func'].append(funcs(raw or old[ev['func'][i]]))
        entry = bool(ev['entry'][i])
        columns['entry_name'].append(funcs(event.entry_name) if entry and event.entry_name else -1)
        caller = analysis.elf.resolve_pc(event.return_address)[0] if entry and event.return_address else None
        columns['caller'].append(funcs(caller) if caller else -1)
        columns['caller_pc'].append(event.return_address - 1 if caller else 0)
        stack = stacks.get(id(event)) if entry else None
        columns['stack'].append([funcs(name) for name in stack] if stack else None)
        columns['stack_pc'].append(pcs.get(id(event)) if entry else None)
    ev.update(columns)
    data['dict'].update(funcs=[display_name(name) for name in funcs.items], raw_funcs=funcs.items,
                        full_funcs=full_names(funcs.items))
    addresses = list(ev['pc']) + columns['caller_pc']
    addresses.extend(pc for chain in columns['stack_pc'] if chain for pc in chain)
    data['source'] = build_source(analysis.kernel_elf_path,
                                 (int(pc, 0) if isinstance(pc, str) else pc for pc in addresses), roots=roots, maps=maps,
                                 snapshot=load_snapshot(analysis.manifest, analysis.run_dir) if hasattr(analysis, 'manifest') else None)
    data['meta']['function_returns'] = counts
    return data


def regenerate(html: Path, run: Path, *, roots=(), maps=(), sidecar: Path | None = None):
    page = html.read_text()
    matches = list(DATA.finditer(page))
    if len(matches) != 1:
        raise ValueError('use one archived run per source enrichment')
    data = json.loads(zlib.decompress(base64.b64decode(matches[0][2])))
    metadata = json.loads(sidecar.read_text()) if sidecar else None
    evidence = metadata.get('report', metadata) if metadata else None
    if evidence:
        if evidence['html_sha256'] != sha256(html):
            raise ValueError('previous report checksum differs')
        for filename, expected in evidence.get('source_sha256', {}).items():
            if sha256(run / filename) != expected:
                raise ValueError(f'archived input differs: {filename}')
    analysis = Analysis(run, event_only=True)
    if evidence and sha256(analysis.kernel_elf_path) != evidence['kernel_elf_sha256']:
        raise ValueError('compiled ELF differs')
    before = json.dumps([data['states'], data.get('metrics'),
                         {k:v for k,v in data['events'].items() if k not in {'func','entry','entry_name','caller','stack','stack_pc','caller_pc'}}], sort_keys=True)
    enrich(data, analysis, roots=roots, maps=maps)
    after = json.dumps([data['states'], data.get('metrics'),
                        {k:v for k,v in data['events'].items() if k not in {'func','entry','entry_name','caller','stack','stack_pc','caller_pc'}}], sort_keys=True)
    if before != after:
        raise ValueError('source enrichment changed audited report data')
    if evidence and evidence.get('function_trace'):
        if data['meta']['function_returns']['raw'] != evidence['function_trace'].get('returns', 0):
            raise ValueError('raw return count changed')
    title = re.search(r'<title>(.*?)</title>', page, re.S)[1]
    updated = (_PAGE.replace('__TITLE__', title).replace('__CSS__', (ASSETS / 'app.css').read_text())
               .replace('__JS__', report_javascript()).replace('__DATA__', matches[0][1] + encode(data) + matches[0][3]))
    stage = html.with_name('.' + html.name + '.source.tmp')
    stage.write_text(updated)
    if evidence:
        evidence['html_sha256'] = sha256(stage); evidence['html_bytes'] = stage.stat().st_size
        evidence['source_view'] = {'files': len(data['source']['files']), 'locations': len(data['source']['locations']),
                                   'source_sha256': {file['path']: file['sha256'] for file in data['source']['files']}}
        if evidence.get('function_trace'):
            for name, key in [('returns', 'raw'), ('matched_returns', 'matched'), ('nested_entries', 'nested_entries')]:
                evidence['function_trace'][name] = data['meta']['function_returns'][key]
        staged_sidecar = sidecar.with_name('.' + sidecar.name + '.source.tmp')
        staged_sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    stage.replace(html)
    if evidence: staged_sidecar.replace(sidecar)
    return {'run': data['meta']['run'], 'files': len(data['source']['files']), 'locations': len(data['source']['locations'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--sidecar', type=Path)
    parser.add_argument('--source-root', type=Path, action='append', default=[])
    parser.add_argument('--source-map', action='append', default=[])
    args = parser.parse_args()
    maps = [tuple(item.split('=', 1)) for item in args.source_map]
    print(json.dumps(regenerate(args.html, args.run, roots=args.source_root, maps=maps, sidecar=args.sidecar)))


if __name__ == '__main__': main()
