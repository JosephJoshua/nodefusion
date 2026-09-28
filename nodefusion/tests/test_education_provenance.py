import hashlib
from collections import Counter
import json
from pathlib import Path
import subprocess

import pytest

from scripts.regenerate_artifact import smoke_report

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('kernel,variant,run,users,tests,threads,alloc,freed,peak,raw', [
    ('rcore', 'basic', 'rcore-2026A-ch8-basic-observed-v3', 84, 20, 36, 1889, 1776, 932, 6529623),
    ('rcore', 'extended', 'rcore-2026A-ch8-extended-observed-v3', 84, 23, 43, 2602, 2489, 1576, 6756857),
    ('ucoreos', 'basic', 'ucore-2026A-ch8-basic-observed', 35, 23, 50, 795, 724, 135, 18298814),
])
def test_chapter_eight_reports_keep_raw_thread_and_source_identity(
        kernel, variant, run, users, tests, threads, alloc, freed, peak, raw):
    folder = ROOT / 'artifacts' / kernel / 'ch8/2026a'
    sidecar = folder / ('recording.json' if variant == 'basic' else run + '.json')
    record = json.loads(sidecar.read_text())
    report = record['report']
    observations = record['observations']
    bundle = smoke_report(folder / record['html'])
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert record['schema'] == 'nodefusion.education-recording/1'
    assert record['run'] == report['run'] == observations['run'] == run
    assert record['outcome'] == 'completed' and record['trace_complete']
    assert digest(folder / record['html']) == report['html_sha256']
    assert digest(folder / (run + '.log')) == record['console_sha256']
    assert bundle['meta']['capability']['coverage'] == report['coverage']
    assert report['coverage']['percent'] == 100.0 and not report['coverage']['blockers']
    assert report['coverage']['semantic_events']['unknown'] == 0
    assert report['event_selection']['raw'] == raw and report['event_selection']['retained'] == 150000
    assert report['function_trace']['raw'] == bundle['meta']['function_entries']['raw']
    assert report['function_trace']['retained'] == bundle['meta']['function_entries']['retained']
    assert observations['inputs']['trace.nfb'] == record['archive']['trace_sha256'] == report['source_sha256']['trace.nfb']
    assert record['archive']['trace_bytes'] == report['archive_bytes']['trace.nfb']
    assert observations['kernel_elf_sha256'] == report['kernel_elf_sha256']
    assert len(record['filesystem_before']['files']) == users
    assert record['filesystem_after']['added_files'] == ['filea']
    assert record['ordinary_course_check'] == {'status': 'PASS', 'tests': tests}
    assert len(observations['threads']) == observations['nftrace_counts']['3'] == threads
    assert observations['record_counts']['watchpc'] == sum(observations['function_counts'].values())
    assert observations['record_counts']['nftrace'] == sum(observations['nftrace_counts'].values())
    assert observations['nftrace_counts']['2'] == len(observations['forks'])
    assert observations['nftrace_counts']['4'] == sum(observations['switches'].values())
    balance = observations['allocation_balance']
    assert balance['every_record_balanced'] and balance['allocation_failures'] == 0
    assert (balance['successful_allocations'], balance['frees'], balance['peak_used_pages']) == (alloc, freed, peak)
    assert balance['final_used_pages'] == alloc - freed
    assert observations['end']['watch_drops'] == 0
    assert record['source']['kernel_commit'] == ('00b2a84360710640fbde595c194a7f2447e755f2' if kernel == 'rcore'
                                                  else '9d4fa96b67b449bc72f6530286b5a438e9de3ce5')
    assert len(record['source']['deployed_source_files']) == 204
    assert len(record['source']['source_archive']['sha256']) == 64
    assert len(record['source_provenance_sha256']) == 64
    assert len(record['kernel_patch_sha256']) == 64
    assert (ROOT / record['integration_patch']).is_file()
    assert record['record_command'] and '--no-build' in record['record_command']
    assert '--function-returns' in record['record_command'] and '--watch-all' in record['record_command']
    assert record['analysis_command'] and record['build_command']['argv']
    assert record['observation_check']['driver_sha256'] == observations['driver_sha256']
    if kernel == 'rcore' and variant == 'basic':
        assert record['analysis_recovery']['analysis_command_executed_separately'] == record['analysis_command']


CH7_VARIANTS = [('rcore', 'basic', 65), ('rcore', 'signals-peer', 65),
                ('rcore', 'signals-all', 65), ('rcore', 'redirect', 65),
                ('ucoreos', 'basic', 26), ('ucoreos', 'pipe-probe', 27)]


def chapter_seven(kernel, variant='basic'):
    folder = ROOT / 'artifacts' / kernel / 'ch7/2026a'
    kind = 'rcore' if kernel == 'rcore' else 'ucore'
    name = 'recording.json' if variant == 'basic' else f'{kind}-2026A-ch7-{variant}-observed.json'
    return json.loads((folder / name).read_text()), folder


@pytest.mark.parametrize('kernel,variant,users', CH7_VARIANTS)
def test_pipe_recordings_preserve_source_commands_and_disk_programs(kernel, variant, users):
    record, _ = chapter_seven(kernel, variant)
    source = record['source']
    shared = chapter_six('rcore')[0]['source']
    assert source['kernel_commit'] == ('c8e0313a55ed5926123d990f196061978c460aed' if kernel == 'rcore'
                                      else 'c6f384219f334280fd6a4acad2a58ad2222a9d25')
    for key in ['nodefusion_commit', 'nodefusion_runtime_overrides', 'deployed_source_files', 'plugin_sha256']:
        assert source[key] == shared[key]
    assert len(source['deployed_source_files']) == 204
    assert record['observation_check']['deployed_source_files'] == source['deployed_source_files']
    assert record['observation_check']['script']['sha256'] == record['observations']['driver_sha256']
    assert len(record['observation_check']['archive']['sha256']) == 64
    check = record['source_archive_check']
    assert check['verified_tool_files'] == 204 and check['verified_compiled_users'] == users
    assert check['source_archive_sha256'] == source['source_archive']['sha256']
    assert check['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    assert check['initial_disk_sha256'] == record['filesystem_before']['sha256']
    assert record['ordinary_course_check']['status'] == 'PASS'
    assert record['ordinary_course_check']['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    assert record['build_command'] and record['record_command'] and record['analysis_command']
    assert '--no-build' in record['record_command'] and '--watch-all' in record['record_command']
    assert '--function-returns' in record['record_command']
    assert record['record_command'][record['record_command'].index('--timeout') + 1] == '600'
    before, after = record['filesystem_before'], record['filesystem_after']
    assert len(before['files']) == users
    assert record['workload']['disk_programs'] == before['files']
    assert {row['name'] for row in before['files']} == set(record['observations']['filesystem_changes']['unchanged_files'])
    after_files = {row['name']: row for row in after['files']}
    for row in before['files']:
        assert {key: value for key, value in row.items() if key != 'compiled_payload'} == after_files[row['name']]
        payload = Path(row['compiled_payload']).name
        assert (payload.removesuffix('.elf') if kernel == 'rcore' else payload[:14]) == row['name']
    if variant == 'pipe-probe':
        assert record['build_context']['unchanged_course_programs'] == 26
        course = chapter_seven('ucoreos')[0]['filesystem_before']['files']
        assert {row['name']: row['sha256'] for row in course} == {
            row['name']: row['sha256'] for row in before['files'] if row['name'] != 'nfpipe_probe'}
        program = ROOT / 'site/src/ch7/nfpipe_probe.c'
        assert hashlib.sha256(program.read_bytes()).hexdigest() == '2fc259dff08078ae3484ae7c1214276ab1132de2b089556df0936f30f43eb003'


@pytest.mark.parametrize('kernel,variant,alloc,freed,peak', [
    ('rcore', 'basic', 1595, 1485, 745), ('rcore', 'signals-peer', 183, 73, 148),
    ('rcore', 'signals-all', 385, 275, 170), ('rcore', 'redirect', 164, 54, 147),
    ('ucoreos', 'basic', 674, 603, 127), ('ucoreos', 'pipe-probe', 114, 43, 104),
])
def test_pipe_reports_preserve_raw_counts_returns_and_actual_call_chains(kernel, variant, alloc, freed, peak):
    record, folder = chapter_seven(kernel, variant)
    observations = record['observations']
    bundle = smoke_report(folder / record['html'])
    assert hashlib.sha256((folder / record['html']).read_bytes()).hexdigest() == record['report']['html_sha256']
    assert hashlib.sha256((folder / record['html'].replace('.html', '.log')).read_bytes()).hexdigest() == record['console_sha256']
    assert observations['input_sha256'] == record['report']['source_sha256']
    assert observations['coverage'] == record['report']['coverage'] == bundle['meta']['capability']['coverage']
    assert observations['coverage']['status'] == 'complete' and not observations['coverage']['blockers']
    assert observations['coverage']['full_watch_scope'] and observations['coverage']['function_watch_drops'] == 0
    assert observations['raw_events'] == record['report']['event_selection']['raw']
    assert observations['raw_event_counts'] == dict(Counter(record['report']['event_selection']['retained_kinds']) + Counter(record['report']['event_selection'].get('dropped_kinds', {})))
    assert observations['watch_hits'] == sum(observations['function_counts'].values())
    assert observations['watch_hits'] - sum(observations['entries_replaced_by_semantic_channel'].values()) == observations['function_entries']['raw']
    for key in ['function_entries', 'function_returns']:
        assert observations[key] == bundle['meta'][key]
    balance = observations['allocation_balance']
    assert balance['every_record_balanced'] and balance['allocation_failures'] == 0
    assert balance['successful_allocations'] == observations['nftrace_counts']['1'] == alloc
    assert balance['frees'] == observations['nftrace_counts']['5'] == freed
    assert balance['peak_used_pages'] == peak
    assert balance['final_used_pages'] == alloc - freed == (110 if kernel == 'rcore' else 71)
    assert observations['nftrace_counts']['2'] == len(observations['forks'])
    assert observations['nftrace_counts']['4'] == sum(observations['switches'].values())
    events, functions = bundle['events'], bundle['dict']['funcs']
    chains = {(events['insn'][i], tuple(functions[index] for index in stack))
              for i, stack in enumerate(events['stack']) if stack}
    for example in observations['pipe_chain_examples']:
        assert (example['insn'], tuple(example['frames'])) in chains


def test_rust_pipe_byte_balance_is_derived_from_completed_operations_and_shared_addresses():
    record, _ = chapter_seven('rcore')
    observations, balance = record['observations'], record['pipe_balance']
    assert observations['pipe_helper_returns_unmatched'] == 0
    assert sum(count for name, count in observations['pipe_helper_returns_matched'].items() if name.endswith('::write_byte')) == 3018
    assert sum(count for name, count in observations['pipe_helper_returns_matched'].items() if name.endswith('::read_byte')) == 3018
    assert len(balance['buffers']) == 3 and balance['all_completed_byte_operations_matched']
    assert balance['capacity'] == 32
    assert sorted((row['written'], row['read'], row['unread'], row['peak_unread']) for row in balance['buffers'].values()) == [(5, 5, 0, 5), (13, 13, 0, 13), (3000, 3000, 0, 32)]
    for address, row in balance['buffers'].items():
        assert observations['pipe_buffer_byte_entries'][address] == {'write_byte': row['written'], 'read_byte': row['read']}
    large = next(row for row in balance['buffers'].values() if row['written'] == 3000)
    assert large['full_transitions'] == 93 and large['empty_transitions'] == 94
    assert balance['input_sha256']['trace.nfb'] == record['archive']['trace_sha256']
    assert balance['operation_data']['bytes'] > 0 and len(balance['operation_data']['sha256']) == 64
    assert 'not a0 values' in observations['pipe_return_capture']


def test_c_pipe_experiment_covers_chunk_boundaries_short_reads_and_allocation_rollback():
    record, _ = chapter_seven('ucoreos', 'pipe-probe')
    chunks = record['pipe_chunks']
    assert chunks['input_sha256']['trace.nfb'] == record['archive']['trace_sha256']
    assert chunks['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    check = chunks['workload_check']
    assert check == {'experiment': 'nfpipe_probe', 'read_bytes': 3000, 'read_calls': 24,
                     'short_reads': 6, 'eof': -1, 'closed_reader_write': -1,
                     'descriptor_pairs': 6, 'all_checks_passed': True}
    assert chunks['yield_callers'] == {'pipewrite': 6, 'piperead': 5}
    assert {name: chunks['function_counts'][name] for name in ['pipealloc', 'pipeclose', 'sys_pipe', 'pipewrite', 'piperead']} == {
        'pipealloc': 11, 'pipeclose': 22, 'sys_pipe': 11, 'pipewrite': 2, 'piperead': 25}
    for direction, count in [('write', 9), ('read', 27)]:
        rows = chunks['copy_chunks'][direction]
        assert len(rows) == count and sum(row['bytes'] for row in rows) == 3000
        assert any(row['crosses_user_page'] for row in rows)
        assert all(row['crosses_user_page'] == (row['user_address'] % 4096 + row['bytes'] > 4096) for row in rows)
        assert all(0 < row['bytes'] <= 512 for row in rows)


def chapter_six(kernel, variant='basic'):
    folder = ROOT / 'artifacts' / kernel / 'ch6/2026a'
    name = 'recording.json' if variant == 'basic' else 'rcore-2026A-ch6-extended-observed.json'
    return json.loads((folder / name).read_text()), folder


def test_filesystem_recordings_preserve_reconstructible_runtime_and_disk_program_identity(tmp_path):
    records = [chapter_six(kernel, variant)[0] for kernel, variant in
               [('rcore', 'basic'), ('rcore', 'extended'), ('ucoreos', 'basic')]]
    identity = records[0]['source']
    for record in records:
        source = record['source']
        rust = record['run'].startswith('rcore-')
        assert source['kernel_commit'] == ('b47c54b5c1f3254518238b0c7450af9c187b4231' if rust else
                                           'df045c4455f2dacb81caf39510aed994bf49ade7')
        assert source['deployed_source_files'] == identity['deployed_source_files']
        assert source['nodefusion_runtime_overrides'] == identity['nodefusion_runtime_overrides']
        assert record['filesystem_analysis_source']['deployed_source_files'] == source['deployed_source_files']
        assert record['filesystem_analysis_script_sha256'] == record['observations']['driver_sha256']
        assert record['filesystem_analysis_command'][-1] == record['run']
        assert record['filesystem_analysis_cwd'] == '/home/joseph'
        assert len(record['filesystem_analysis_source']['archive']['sha256']) == 64
        assert record['filesystem_analysis_source']['archive']['bytes'] > 0
        assert record['ordinary_course_check']['status'] == 'PASS'
        assert record['ordinary_course_check']['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
        assert record['build_command'] and record['record_command'] and record['analysis_command']
        before, after = record['filesystem_before'], record['filesystem_after']
        assert before['sha256'] == record['build_context']['reference_filesystem_sha256']
        assert before['sha256'] != after['sha256']
        assert record['build_context']['reference_kernel_elf_sha256'] != record['report']['kernel_elf_sha256']
        assert before['block_size'] == after['block_size'] == (512 if rust else 1024)
        assert len(before['files']) == (53 if rust else 24)
        assert record['workload']['disk_programs'] == before['files']
        names = {row['name'] for row in before['files']}
        assert names == set(record['observations']['filesystem_changes']['unchanged_files'])
        for row in before['files']:
            assert row['size'] > 0 and len(row['sha256']) == 64 and row['data_block_ids']
            payload = Path(row['compiled_payload']).name
            assert (payload.removesuffix('.elf') if rust else payload[:14]) == row['name']
        if rust:
            assert record['workload']['course_check']['program'] in ['ch6b_usertest', 'ch6_usertest']
        else:
            assert not record['workload']['course_check']['errors']
    overrides = {row['path']: row for row in identity['nodefusion_runtime_overrides']}
    assert len(identity['deployed_source_files']) == 204 and set(overrides) <= identity['deployed_source_files'].keys()
    for name, digest in identity['deployed_source_files'].items():
        assert name.startswith(('nodefusion/', 'scripts/')) and '..' not in Path(name).parts
        content = subprocess.check_output(['git', 'show', f'{identity["nodefusion_commit"]}:{name}'], cwd=ROOT)
        if name in overrides:
            output = tmp_path / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                           input=overrides[name]['patch'], text=True, check=True)
            content = output.read_bytes()
            assert overrides[name]['sha256'] == digest
        assert hashlib.sha256(content).hexdigest() == digest


@pytest.mark.parametrize('kernel,variant,alloc,freed,peak,cache,requests,files', [
    ('rcore', 'basic', 1443, 1333, 710, 2472, 804, ['filea']),
    ('rcore', 'extended', 2896, 2786, 718, 33155, 18652, ['filea', 'fname', 'fname1']),
    ('ucoreos', 'basic', 635, 564, 127, 636, 138, ['filea']),
])
def test_filesystem_reports_preserve_full_counts_disk_changes_and_actual_call_chains(kernel, variant, alloc, freed, peak, cache, requests, files):
    record, folder = chapter_six(kernel, variant)
    observations = record['observations']
    bundle = smoke_report(folder / record['html'])
    assert hashlib.sha256((folder / record['html']).read_bytes()).hexdigest() == record['report']['html_sha256']
    assert hashlib.sha256((folder / record['html'].replace('.html', '.log')).read_bytes()).hexdigest() == record['console_sha256']
    assert record['outcome'] == observations['record_status'] == 'completed' and record['trace_complete']
    assert observations['input_sha256'] == record['report']['source_sha256']
    assert observations['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    assert observations['coverage'] == record['report']['coverage'] == bundle['meta']['capability']['coverage']
    assert observations['coverage']['status'] == 'complete' and not observations['coverage']['blockers']
    selection = bundle['meta']['event_selection']
    assert selection == record['report']['event_selection']
    assert observations['raw_events'] == selection['raw'] > selection['retained'] == 150000
    assert observations['raw_event_counts'] == dict(Counter(selection['retained_kinds']) + Counter(selection['dropped_kinds']))
    assert observations['raw_event_counts']['bcache.read'] == cache
    assert observations['raw_event_counts']['disk.io'] == requests
    assert observations['watch_hits'] == sum(observations['function_counts'].values())
    assert observations['watch_hits'] - sum(observations['entries_replaced_by_semantic_channel'].values()) == observations['function_entries']['raw']
    for key in ['function_entries', 'function_returns']:
        assert observations[key] == bundle['meta'][key]
    assert observations['function_entries']['retained'] > 0
    balance = observations['allocation_balance']
    assert balance['successful_allocations'] == observations['nftrace_counts']['1'] == alloc
    assert balance['frees'] == observations['nftrace_counts']['5'] == freed
    assert balance['allocation_failures'] == 0 and balance['every_record_balanced']
    assert balance['peak_used_pages'] == peak
    assert balance['final_used_pages'] == alloc - freed
    assert observations['nftrace_counts']['4'] == sum(observations['switches'].values())
    assert observations['nftrace_counts']['2'] == len(observations['forks'])
    changes = observations['filesystem_changes']
    assert [row['name'] for row in changes['added_files']] == files
    assert not changes['removed_files'] and not changes['changed_files']
    filea = changes['added_files'][0]
    assert filea['size'] == (13 if kernel == 'rcore' else 14)
    assert filea['inode'] == (54 if kernel == 'rcore' else 26)
    assert filea['data_block_ids'] == ([3381] if kernel == 'rcore' else [192])
    before = {row['name']: row for row in record['filesystem_before']['files']}
    after = {row['name']: row for row in record['filesystem_after']['files']}
    for name in before:
        assert {key: value for key, value in before[name].items() if key != 'compiled_payload'} == after[name]
    funcs = bundle['dict']['funcs']
    chains = Counter(tuple(funcs[i] for i in stack) for stack in bundle['events']['stack'] if stack and len(stack) > 1)
    assert observations['filesystem_chain_examples']
    for example in observations['filesystem_chain_examples']:
        assert len(example['frames']) > 1
        assert chains[tuple(example['frames'])] == example['retained_occurrences'] > 0
    forks = {(row['insn'], row['parent_pid'], row['child_pid']) for row in observations['forks']}
    for i, kind in enumerate(bundle['events']['kind']):
        if bundle['dict']['kinds'][kind] == 'proc.fork':
            detail = bundle['events']['detail'][i]
            assert bundle['events']['pid'][i] == detail['parent_tid'] != detail['child_tid']
            assert (bundle['events']['insn'][i], detail['parent_tid'], detail['child_tid']) in forks


def chapter_five(kernel, variant='basic'):
    folder = ROOT / 'artifacts' / kernel / 'ch5/2026a'
    name = 'recording.json' if variant == 'basic' else 'rcore-2026A-ch5-extended-observed-v2.json'
    return json.loads((folder / name).read_text()), folder


@pytest.mark.parametrize('kernel,variant', [('rcore', 'basic'), ('rcore', 'extended'), ('ucoreos', 'basic')])
def test_process_recordings_have_reconstructible_recording_and_analysis_sources(kernel, variant, tmp_path):
    record, _ = chapter_five(kernel, variant)
    source, analysis = record['source'], record['analysis_source']
    attribution = record.get('attribution_analysis_source', analysis)
    pin = '023a5a0885fed8ae999406f17a494777c3e59af1' if kernel == 'rcore' else '386f10c55d0285273b78df19c4607c0f475e17a2'
    assert source['kernel_commit'] == pin
    changed = {name for name, digest in attribution['deployed_source_files'].items()
               if digest != source['deployed_source_files'][name]}
    assert changed == {'nodefusion/host/analyze.py', 'nodefusion/host/assets/app.js',
                       'nodefusion/host/assets/app.css', 'nodefusion/tests/test_phys_alloc_gate.py'}
    identities = [source, attribution] if attribution is analysis else [source, attribution, analysis]
    for identity in identities:
        assert len(identity['deployed_source_files']) == 204
        overrides = {row['path']: row for row in identity['nodefusion_runtime_overrides']}
        assert len(overrides) == len(identity['nodefusion_runtime_overrides'])
        assert set(overrides) <= identity['deployed_source_files'].keys()
        for name, digest in identity['deployed_source_files'].items():
            assert name.startswith(('nodefusion/', 'scripts/')) and '..' not in Path(name).parts
            content = subprocess.check_output(['git', 'show', f'{identity["nodefusion_commit"]}:{name}'], cwd=ROOT)
            if name in overrides:
                output = tmp_path / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
                subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                               input=overrides[name]['patch'], text=True, check=True)
                content = output.read_bytes()
                assert overrides[name]['sha256'] == digest
            assert hashlib.sha256(content).hexdigest() == digest
    assert analysis['deployed_source_files'] == analysis['source_file_hashes_after']
    assert analysis['command'] == record['analysis_command']
    assert record['original_report']['source_sha256'] == record['report']['source_sha256'] == analysis['source_sha256']
    assert record['original_report']['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    assert record['original_report']['html_sha256'] == attribution['previous_html_sha256']
    if kernel == 'rcore':
        assert analysis['previous_html_sha256'] == record['previous_report']['html_sha256']
        assert analysis['source_archive']['bytes'] > 0
        assert analysis['kernel_commit'] == source['kernel_commit']
        assert analysis['analysis_driver_sha256'] == analysis['deployed_source_files'][
            'scripts/regenerate_artifact.py']
        assert analysis['deployed_source_files'] == json.loads(
            (ROOT / 'artifacts/rcore/ch8/2026a/recording.json').read_text()
        )['source']['deployed_source_files']
    assert record['original_analysis_command'] and record['record_command'] and record['build_command']
    assert record['process_analysis_command'] and record['process_analysis_cwd']
    assert record['process_analysis_script_sha256'] == record['observations']['driver_sha256']
    assert record['process_analysis_source_archive']['bytes'] > 0


@pytest.mark.parametrize('kernel,variant,alloc,freed,peak,forks,switches', [
    ('rcore', 'basic', 1365, 1259, 710, 55, 275),
    ('rcore', 'extended', 1469, 1363, 797, 2, 25115),
    ('ucoreos', 'basic', 606, 539, 123, 60, 512674),
])
def test_process_recordings_preserve_counters_forks_and_explicit_event_ownership(kernel, variant, alloc, freed, peak, forks, switches):
    record, folder = chapter_five(kernel, variant)
    observations = record['observations']
    bundle = smoke_report(folder / record['html'])
    assert hashlib.sha256((folder / record['html']).read_bytes()).hexdigest() == record['report']['html_sha256']
    assert hashlib.sha256((folder / record['html'].replace('.html', '.log')).read_bytes()).hexdigest() == record['console_sha256']
    assert record['outcome'] == observations['record_status'] == 'completed' and record['trace_complete']
    assert record['report']['coverage'] == bundle['meta']['capability']['coverage']
    assert record['report']['coverage']['status'] == 'complete' and not record['report']['coverage']['blockers']
    assert observations['trace_sha256'] == record['report']['source_sha256']['trace.nfb']
    assert observations['manifest_sha256'] == record['report']['source_sha256']['manifest.json']
    assert observations['nftrace_counts']['2'] == len(observations['forks']) == forks
    assert observations['nftrace_counts']['4'] == observations['switch_entries'] == sum(observations['switches'].values()) == switches
    balance, marks = observations['allocation_balance'], observations['allocator_marks']
    assert balance['successful_allocations'] == observations['nftrace_counts']['1'] == alloc
    assert balance['frees'] == observations['nftrace_counts']['5'] == freed
    assert balance['allocation_failures'] == 0 and observations['nftrace_counts']['6'] == 1
    assert balance['peak_used_pages'] == max(mark['used'] for mark in marks) == peak
    assert marks[0]['used'] == 0 and marks[-1]['used'] == balance['final_used_pages'] == alloc - freed
    assert len(marks) == 1 + alloc + freed
    assert all(mark['free'] + mark['used'] == balance['initial_free_pages'] for mark in marks)
    deltas = [after['used'] - before['used'] for before, after in zip(marks, marks[1:])]
    assert deltas.count(1) == alloc and deltas.count(-1) == freed
    assert all(a['insn'] < b['insn'] for a, b in zip(marks, marks[1:]))
    events, kinds = bundle['events'], bundle['dict']['kinds']
    captured_forks = []
    for i, kind_id in enumerate(events['kind']):
        kind = kinds[kind_id]
        if kind in ['proc.fork', 'proc.exec', 'proc.exit', 'syscall.enter']:
            assert events['pid'][i] >= 0
        if kind == 'proc.fork':
            detail = events['detail'][i]
            assert events['pid'][i] == detail['parent_tid'] != detail['child_tid']
            captured_forks.append({'insn': events['insn'][i], 'parent_pid': detail['parent_tid'], 'child_pid': detail['child_tid']})
    assert captured_forks == observations['forks']
    for key in ['event_selection', 'function_entries', 'function_returns']:
        assert bundle['meta'][key] == record['analysis_source'][key]
    if kernel == 'rcore':
        funcs = bundle['dict']['funcs']
        assert not any(name.startswith('_ZN') for name in funcs)
        previous = record['previous_report']['function_trace']
        current = record['report']['function_trace']
        assert current['returns'] == previous['returns']
        assert current['matched_returns'] > previous['matched_returns']
        assert current['nested_entries'] > previous['nested_entries']
    assert bundle['meta']['event_selection'] == record['original_report']['event_selection']
    assert bundle['meta']['event_selection']['retained'] <= 150000
    expected_faults = [(15, 0xc000)] if kernel == 'rcore' and variant == 'basic' else ([(15, 0x10000000), (13, 0x10000000)] if kernel == 'rcore' else [])
    assert sorted((item['scause'], item['stval']) for item in observations['faults']) == sorted(expected_faults)


@pytest.mark.parametrize('kernel,variant,count', [('rcore', 'basic', 43), ('rcore', 'extended', 43), ('ucoreos', 'basic', 16)])
def test_process_recordings_identify_the_actual_embedded_program_format(kernel, variant, count):
    record, _ = chapter_five(kernel, variant)
    workload = record['workload']
    expected = workload['loaded_user_elfs'] if kernel == 'rcore' else workload['user_programs']
    embedded = workload['embedded_user_apps']
    assert len(embedded) == count
    assert {name: row['sha256'] for name, row in embedded.items()} == expected
    assert all(row['end'] - row['start'] == row['bytes'] + row['linker_padding_bytes'] > 0 for row in embedded.values())
    if kernel == 'rcore':
        assert all(name.endswith('.elf') for name in expected)
    else:
        assert not workload['loaded_user_elfs']



def chapter_four(kernel, variant='observed'):
    folder = ROOT / 'artifacts' / kernel / 'ch4/2026a'
    file = 'recording.json' if variant == 'observed' else 'ucore-2026A-ch4-pagetable.json'
    return json.loads((folder / file).read_text()), folder


@pytest.mark.parametrize('kernel,variant', [('rcore', 'observed'), ('ucoreos', 'observed'), ('ucoreos', 'pagetable')])
def test_memory_recordings_preserve_source_and_counter_meanings(kernel, variant, tmp_path):
    record, folder = chapter_four(kernel, variant)
    expected_pin = ('ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d' if kernel == 'rcore'
                    else '51f02268653c68f169f5599055da3b0391995ee6')
    assert record['source']['kernel_commit'] == expected_pin
    source = record['source']
    overrides = {item['path']: item for item in source['nodefusion_runtime_overrides']}
    assert len(source['deployed_source_files']) == 204 and len(overrides) == 8
    for name, digest in source['deployed_source_files'].items():
        assert name.startswith(('nodefusion/', 'scripts/')) and '..' not in Path(name).parts
        content = subprocess.check_output(['git', 'show', f'{source["nodefusion_commit"]}:{name}'], cwd=ROOT)
        if name in overrides:
            output = tmp_path / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                           input=overrides[name]['patch'], text=True, check=True)
            content = output.read_bytes()
            assert overrides[name]['sha256'] == digest
        assert hashlib.sha256(content).hexdigest() == digest
    observations = record['observations']
    bundle = smoke_report(folder / record['html'])
    assert observations['input_sha256'] == record['report']['source_sha256']
    assert observations['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    assert observations['watch_hits'] == sum(observations['function_counts'].values())
    assert observations['report_function_entries'] == bundle['meta']['function_entries']
    assert observations['report_function_returns'] == bundle['meta']['function_returns']
    assert observations['raw_events'] == bundle['meta']['event_selection']['raw']
    assert observations['allocator_record_counts']['6'] == 1
    initial, final = observations['allocator_initial'], observations['allocator_final']
    allocated = observations['allocator_record_counts']['1']
    freed = observations['allocator_record_counts'].get('5', 0)
    assert final['used'] - initial['used'] == initial['free'] - final['free'] == allocated - freed
    assert observations['console_sha256'] == hashlib.sha256((folder / record['html'].replace('.html', '.log')).read_bytes()).hexdigest()
    assert record['outcome'] == 'completed' and record['trace_complete']
    assert record['report']['coverage']['status'] == 'complete'
    assert record['build_command'] and record['record_command'] and record['analysis_command']


def test_memory_rust_recording_hashes_the_actual_embedded_elf_apps():
    record, _ = chapter_four('rcore')
    workload = record['workload']
    assert len(workload['loaded_user_elfs']) == 21
    assert all(name.endswith('.elf') for name in workload['loaded_user_elfs'])
    for variant in ['reference', 'observed']:
        embedded = workload['embedded_user_apps'][variant]
        assert {name: item['sha256'] for name, item in embedded.items()} == workload['loaded_user_elfs']
        assert all(item['bytes'] == item['end'] - item['start'] > 0 for item in embedded.values())
    observations = record['observations']
    assert observations['syscall_counts']['222'] == 13
    assert observations['syscall_counts']['215'] == 4
    assert observations['function_kind_counts']['vm.unmap'] == 2
    assert observations['allocator_record_counts']['5'] == 13
    assert observations['fault_counts'] == [
        {'destination_privilege': 1, 'cause': 13, 'count': 1},
        {'destination_privilege': 1, 'cause': 15, 'count': 3},
        {'destination_privilege': 3, 'cause': 2, 'count': 2},
    ]
    assert len(observations['faults']) == 6
    illegal = [item for item in observations['faults'] if item['priv'] == 3]
    assert all(item['mcause'] == 2 and item['flags'] == 0 and item['mepc'] == item['from_pc'] for item in illegal)
    assert all(item['mepc'] < 0x1000 for item in illegal)


@pytest.mark.parametrize('kernel,variant', [('rcore', 'observed'), ('ucoreos', 'observed'), ('ucoreos', 'pagetable')])
def test_memory_sampling_preserves_rare_kinds_and_separate_analysis_source(kernel, variant, tmp_path):
    record, folder = chapter_four(kernel, variant)
    analysis = record['analysis_source']
    source = record['source']
    assert analysis['nodefusion_commit'] == source['nodefusion_commit']
    changed = {name for name, digest in analysis['deployed_source_files'].items()
               if digest != source['deployed_source_files'][name]}
    expected_changed = {'nodefusion/host/bundle.py', 'nodefusion/tests/test_bundle_shape.py'}
    if kernel == 'ucoreos' and variant == 'observed':
        expected_changed.add('nodefusion/manifests/rcore.toml')
    assert changed == expected_changed
    overrides = {item['path']: item for item in analysis['nodefusion_runtime_overrides']}
    assert len(analysis['deployed_source_files']) == 204 and len(overrides) == 10
    for name in changed:
        content = subprocess.check_output(['git', 'show', f'{analysis["nodefusion_commit"]}:{name}'], cwd=ROOT)
        output = tmp_path / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                       input=overrides[name]['patch'], text=True, check=True)
        assert hashlib.sha256(output.read_bytes()).hexdigest() == overrides[name]['sha256'] == analysis['deployed_source_files'][name]
    assert analysis['deployed_source_files'] == analysis['source_file_hashes_after']
    assert analysis['source_sha256'] == record['report']['source_sha256']
    assert analysis['command'] == record['analysis_command']
    assert record['original_analysis_command']
    assert len(analysis['source_archive']['sha256']) == 64 and analysis['source_archive']['bytes'] > 0
    bundle = smoke_report(folder / record['html'])
    selection = bundle['meta']['event_selection']
    assert selection == analysis['event_selection']
    assert selection['policy'] == 'kind-preserving/systematic-v5'
    assert selection['retained'] <= 150000
    for kind, count in selection['retained_kinds'].items():
        floor = selection.get('minimum_per_diagnostic_kind' if kind.startswith('func.') else 'minimum_per_kind', 64)
        if count + selection['dropped_kinds'].get(kind, 0) <= floor:
            assert not selection['dropped_kinds'].get(kind)
    previous = record['original_report_observations']
    assert previous['report_function_entries']['raw'] == record['observations']['report_function_entries']['raw']
    assert record['report_observation_refinement']['fields'] == ['report_function_entries', 'report_function_returns']
    if kernel == 'rcore':
        expected = {'syscall.mmap': 13, 'syscall.munmap': 4, 'syscall.sbrk': 8,
                    'syscall.trace': 24, 'trap.page_fault': 4, 'vm.unmap': 2,
                    'func.MapArea::unmap@0': 2}
        assert all(selection['retained_kinds'][kind] == count for kind, count in expected.items())
        firmware = [(index, detail) for index, detail in enumerate(bundle['events']['detail'])
                    if bundle['dict']['kinds'][bundle['events']['kind'][index]] == 'firmware.trap'
                    and bundle['events']['insn'][index] >= record['observations']['kernel_start_insn']]
        illegal_insns = {bundle['events']['insn'][index] for index, detail in firmware if detail['cause_code'] == 2}
        assert illegal_insns == {fault['insn'] for fault in record['observations']['faults'] if fault['priv'] == 3}
        assert len(illegal_insns) == 2


def test_memory_c_reference_batch_and_temporary_page_table_are_distinct():
    batch, _ = chapter_four('ucoreos')
    experiment, _ = chapter_four('ucoreos', 'pagetable')
    assert batch['workload']['user_programs'] == experiment['workload']['user_programs']
    assert batch['report']['kernel_elf_sha256'] != experiment['report']['kernel_elf_sha256']
    assert not batch['observations']['function_kind_counts'].get('vm.unmap')
    assert not batch['observations']['allocator_record_counts'].get('5')
    proof = experiment['pagetable_experiment']
    assert proof['input_sha256'] == experiment['report']['source_sha256']
    assert proof['allocator_before'] == proof['allocator_after']
    allocations = [item for item in proof['nftrace'] if item['type'] == 1]
    frees = [item for item in proof['nftrace'] if item['type'] == 5]
    assert len(allocations) == len(frees) == 6
    assert sorted(item['a'][0] for item in allocations) == sorted(item['a'][0] for item in frees)
    unmaps = [item for item in proof['entries'] if item['name'] == 'uvmunmap']
    assert [item['a'][1:4] for item in unmaps] == [[0x4000, 1, 0], [0x4000, 1, 1], [0x3ffffff000, 1, 0]]
    assert all(len(item['a']) == 8 for item in unmaps)
    assert not any(unmaps[0]['insn'] <= item['insn'] < unmaps[1]['insn'] for item in frees)
    assert unmaps[1]['insn'] < frees[0]['insn'] < unmaps[2]['insn']
    maps = [item for item in proof['entries'] if item['name'] == 'nodefusion_pagetable_map' and item['a'][0] == 0x4000]
    assert len(maps) == 2 and maps[0]['a'][:3] == maps[1]['a'][:3]
    assert maps[0]['a'][2] == 0x17 and maps[0]['a'][1] == frees[0]['a'][0]


@pytest.mark.parametrize('kernel', ['rcore', 'ucoreos'])
def test_boot_recordings_have_reconstructible_tool_source(kernel, tmp_path):
    folder = ROOT / 'artifacts' / kernel / 'ch1/2026a'
    record = json.loads((folder / 'recording.json').read_text())
    source = record['source']
    base = source['nodefusion_commit']
    files = source['deployed_source_files']
    overrides = {entry['path']: entry for entry in source['nodefusion_runtime_overrides']}
    for name, digest in files.items():
        assert name.startswith(('nodefusion/', 'scripts/')) and '..' not in Path(name).parts
        content = subprocess.check_output(['git', 'show', f'{base}:{name}'], cwd=ROOT)
        if name in overrides:
            output = tmp_path / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                           input=overrides[name]['patch'], text=True, check=True)
            content = output.read_bytes()
            assert overrides[name]['sha256'] == digest
        assert hashlib.sha256(content).hexdigest() == digest
    assert set(overrides) <= files.keys()
    assert {'nodefusion/host/cli.py', 'nodefusion/host/analyze.py',
            'scripts/regenerate_artifact.py'} <= files.keys()
    assert record['source']['source_archive']['bytes'] > 0
    assert len(record['source']['source_archive']['sha256']) == 64
    assert record['archive']['trace_sha256'] == record['report']['source_sha256']['trace.nfb']
    assert record['observations']['total_insns'] == smoke_report(folder / record['html'])['meta']['total_insns']
    assert len(record['boot_analysis_script_sha256']) == 64
    assert record['build_command'] and record['record_command'] and record['analysis_command']
    assert record['build_context']['cwd'] == record['build_cwd']
    assert len(record['build_context']['inspection_script_sha256']) == 64
    if kernel == 'rcore':
        assert record['build_context']['versions']['rustc'].startswith('rustc 1.80.0-nightly ')
    if kernel == 'ucoreos':
        assert record['course_check']['status'] == 'PASS'
        assert record['course_check']['kernel_sha256'] == record['report']['kernel_elf_sha256']


@pytest.mark.parametrize('kernel,main,clean', [('rcore', 'rust_main', 'clear_bss'),
                                            ('ucoreos', 'main', 'clean_bss')])
def test_boot_observations_agree_with_linker_bounds(kernel, main, clean):
    folder = ROOT / 'artifacts' / kernel / 'ch1/2026a'
    record = json.loads((folder / 'recording.json').read_text())
    observations = record['observations']
    symbols = observations['symbols']
    assert observations['entries'][main][0]['sp'] == symbols['boot_stack_top']
    assert observations['entries'][main][0]['insn'] < observations['entries'][clean][0]['insn']
    lower = symbols['boot_stack_lower_bound' if kernel == 'rcore' else 'boot_stack']
    assert symbols['boot_stack_top'] - lower == 64 * 1024
    assert lower <= observations['entries'][clean][0]['sp'] < symbols['boot_stack_top']
    assert symbols['sbss' if kernel == 'rcore' else 's_bss'] == symbols['boot_stack_top']


def chapter_two(kernel, variant):
    name = 'ucore' if kernel == 'ucoreos' else kernel
    path = ROOT / 'artifacts' / kernel / 'ch2/2026a' / f'{name}-2026A-ch2-{variant}.json'
    return json.loads(path.read_text()), path.parent


@pytest.mark.parametrize('kernel,variant', [('rcore', 'reference'), ('ucoreos', 'reference'),
                                         ('ucoreos', 'stack-fixed'), ('ucoreos', 'faults')])
def test_batch_recordings_have_reconstructible_tool_source(kernel, variant, tmp_path):
    record, folder = chapter_two(kernel, variant)
    source = record['source']
    files = source['deployed_source_files']
    overrides = {entry['path']: entry for entry in source['nodefusion_runtime_overrides']}
    assert len(files) == 204 and len(overrides) == 8
    for name, digest in files.items():
        assert name.startswith(('nodefusion/', 'scripts/')) and '..' not in Path(name).parts
        content = subprocess.check_output(['git', 'show', f'{source["nodefusion_commit"]}:{name}'], cwd=ROOT)
        if name in overrides:
            output = tmp_path / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                           input=overrides[name]['patch'], text=True, check=True)
            content = output.read_bytes()
            assert overrides[name]['sha256'] == digest
        assert hashlib.sha256(content).hexdigest() == digest
    assert set(overrides) <= files.keys()
    bundle = smoke_report(folder / record['html'])
    observations = record['observations']
    assert bundle['meta']['total_insns'] == observations['total_insns']
    assert observations['input_sha256'] == record['report']['source_sha256']
    assert observations['kernel_elf_sha256'] == record['report']['kernel_elf_sha256']
    assert observations['script_sha256'] == record['batch_analysis_script_sha256']
    assert record['source']['source_archive']['bytes'] > 0
    assert len(record['source']['source_archive']['sha256']) == 64
    assert record['build_command'] and record['record_command'] and record['analysis_command']
    assert record['batch_analysis_command'][-1] == 'batch-observations-kernel.json'
    assert observations['function_entries'] == bundle['meta']['function_entries']
    if kernel == 'ucoreos':
        selection = bundle['meta']['event_selection']
        assert selection['retained_kinds'].get('kernel.panic', 0) + selection['dropped_kinds'].get('kernel.panic', 0) == 0


def test_reference_stack_overlap_and_separate_correction_are_preserved():
    reference, _ = chapter_two('ucoreos', 'reference')
    fixed, fixed_folder = chapter_two('ucoreos', 'stack-fixed')
    assert reference['outcome'] == 'timeout' and reference['course_check']['status'] == 'FAIL'
    assert fixed['outcome'] == 'completed' and fixed['build_context']['qemu_exit'] == 0
    log = (fixed_folder / fixed['html'].replace('.html', '.log')).read_text()
    assert log.count('sysexit(1234)') == 1 and log.count('sysexit(0)') == 2 and 'ALL DONE' in log
    assert reference['source']['kernel_commit'] == fixed['source']['kernel_commit']
    assert reference['workload']['user_programs'] == fixed['workload']['user_programs']
    assert reference['report']['kernel_elf_sha256'] != fixed['report']['kernel_elf_sha256']
    assert reference['archive']['trace_sha256'] != fixed['archive']['trace_sha256']
    assert 'kernel_sp = kstack;' not in reference['source']['kernel_patch']
    assert '+\ttrapframe->kernel_sp = kstack;' in fixed['source']['kernel_patch']
    observations = reference['observations']
    page = observations['symbols']['trap_page']['address']
    size = observations['symbols']['trap_page']['size']
    assert observations['symbols']['boot_stack_top']['address'] == page
    assert observations['entries']['usertrap'][0]['sp'] == page + size
    clear = next(entry for entry in observations['entries']['memset']
                 if entry['a'][:3] == [page, 0, size] and entry['insn'] > observations['entries']['usertrap'][0]['insn'])
    assert page <= clear['sp'] < page + size
    fault = observations['faults'][0]
    assert clear['insn'] < fault['insn'] and fault['mcause'] == 1 and fault['mepc'] == 0
    assert observations['function_counts']['usertrapret'] == 1
    assert observations['states'][-1]['app_cur'] == 1 and observations['states'][-1]['app_num'] == 3
    corrected = fixed['observations']
    assert corrected['function_counts']['sys_exit'] == 3
    assert corrected['function_counts']['usertrap'] == corrected['function_counts']['usertrapret'] == 16
    assert corrected['states'][-1]['app_cur'] == corrected['states'][-1]['app_num'] == 3
    assert all(entry['sp'] < page for entry in corrected['entries']['memset'] if entry['a'][:3] == [page, 0, size])


def test_batch_normal_and_fault_workloads_remain_distinct():
    rust, folder = chapter_two('rcore', 'reference')
    assert rust['source']['kernel_patch'] == ''
    assert rust['outcome'] == 'completed'
    counts = rust['observations']['function_counts']
    assert counts['trap_handler'] == 68 and counts['run_next_app'] == 8
    assert rust['observations']['syscall_counts'] == {'64': 61, '93': 4}
    assert len(rust['workload']['user_programs']) == 7
    bundle = smoke_report(folder / rust['html'])
    assert all(state['procs_ok'] and not state['procs'] for state in bundle['states'])
    manager = next(resource for resource in bundle['states'][-1]['resources'] if resource['name'] == 'batch_manager')
    assert manager['ok'] and manager['rows'] == [{'num_app': 7, 'current_app': 7}]
    assert rust['analysis_source']['deployed_source_files'] != rust['source']['deployed_source_files']
    assert rust['analysis_source']['source_sha256'] == rust['report']['source_sha256']
    faults, _ = chapter_two('ucoreos', 'faults')
    assert faults['outcome'] == 'completed'
    assert len(faults['workload']['user_programs']) == 3
    assert all('__ch2_bad_' in name for name in faults['workload']['user_programs'])
    obs = faults['observations']
    assert obs['syscall_counts'] == {} and obs['function_counts'].get('sys_exit', 0) == 0
    assert obs['function_counts']['usertrap'] == obs['function_counts']['usertrapret'] == 3
    assert [fault['mcause'] for fault in obs['faults']] == [7, 2, 2]
    assert obs['states'][-1]['app_cur'] == obs['states'][-1]['app_num'] == 3


def test_batch_analysis_source_is_reconstructible_and_distinct_from_recording(tmp_path):
    record, _ = chapter_two('rcore', 'reference')
    analysis = record['analysis_source']
    original = record['source']
    assert set(analysis['deployed_source_files']) == set(original['deployed_source_files'])
    assert [name for name, digest in analysis['deployed_source_files'].items()
            if digest != original['deployed_source_files'][name]] == ['nodefusion/manifests/rcore.toml']
    assert analysis['deployed_source_files'] == analysis['source_file_hashes_after']
    assert len(analysis['source_archive']['sha256']) == 64 and analysis['source_archive']['bytes'] > 0
    overrides = {item['path']: item for item in analysis['nodefusion_runtime_overrides']}
    for name, digest in analysis['deployed_source_files'].items():
        content = subprocess.check_output(['git', 'show', f'{analysis["nodefusion_commit"]}:{name}'], cwd=ROOT)
        if name in overrides:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            subprocess.run(['git', 'apply', '--no-index', '-'], cwd=tmp_path,
                           input=overrides[name]['patch'], text=True, check=True)
            content = path.read_bytes()
            assert overrides[name]['sha256'] == digest
        assert hashlib.sha256(content).hexdigest() == digest
    assert analysis['source_sha256'] == record['observations']['input_sha256']
