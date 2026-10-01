import hashlib
import json
import shutil
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from nodefusion.host import sourceview as S
from nodefusion.host.bundle import build
from nodefusion.host.analyze import Event
from nodefusion.tests.test_bundle_shape import _analysis, _state


def test_identity_survives_equal_display_names():
    a = _analysis(_state())
    names = ['_ZN2os4root17h1234567890abcdefE', '_ZN2os4root17hfedcba0987654321E']
    a.events = [Event(n, 0, 'func.root', 'function', func=raw,
                      entry_name=raw, function_entry=True) for n, raw in enumerate(names)]
    result = build(a)
    assert result['events']['func'][0] != result['events']['func'][1]
    assert result['dict']['raw_funcs'] == names
    assert result['dict']['funcs'] == ['os::root', 'os::root']


def test_caller_location_is_preserved_without_return_records():
    a = _analysis(_state())
    a.elf = NS(resolve_pc=lambda pc: ('parent', 0))
    a.events = [Event(1, 0, 'func.child', 'function', func='child',
                      function_entry=True, entry_name='child', return_address=32)]
    result = build(a)
    assert result['events']['stack'] == [None]
    assert result['events']['caller_pc'] == [31]
    assert result['dict']['raw_funcs'][result['events']['caller'][0]] == 'parent'


def test_source_roots_block_escape_and_symlinks(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    outside = tmp_path / 'secret.c'
    outside.write_text('secret')
    (root / 'link.c').symlink_to(outside)
    assert S.resolve_file(str(outside), [root], []) is None
    assert S.resolve_file('link.c', [root], []) is None
    assert S.resolve_file('../secret.c', [root], []) is None
    source = root / 'good.c'
    source.write_text('int good;')
    assert S.resolve_file('/build/good.c', [root], [('/build', str(root))]) == source
    assert S.resolve_file('/builder/good.c', [root], [('/build', str(root))]) is None
    assert S.resolve_file(r'E:\build\good.c', [root], [(r'E:\build', str(root))]) == source
    assert S.resolve_file(r'E:\builder\good.c', [root], [(r'E:\build', str(root))]) is None


def test_locations_inline_frames_and_deduplicated_files(tmp_path, monkeypatch):
    src = tmp_path / 'kernel.c'
    src.write_text('int a;\nint b;\n')
    elf = tmp_path / 'kernel.elf'
    elf.write_bytes(b'elf')
    monkeypatch.setattr(S, 'llvm_tool', lambda name: name)
    def run(cmd, **kwargs):
        return NS(stdout='\n'.join(json.dumps({'Symbol': [
            {'FileName': str(src), 'Line': 2, 'FunctionName': 'inline_fn'},
            {'FileName': str(src), 'Line': 1, 'FunctionName': 'outer'}]})
            for _ in kwargs['input'].splitlines()))
    monkeypatch.setattr(S.subprocess, 'run', run)
    resolved = []
    resolve = S.resolve_file
    def tracked(filename, roots, maps):
        resolved.append(filename)
        return resolve(filename, roots, maps)
    monkeypatch.setattr(S, 'resolve_file', tracked)
    result = S.build_source(elf, [16, 16, 32], roots=[tmp_path])
    assert result['status'] == 'ready'
    assert len(result['files']) == 1
    assert result['files'][0]['sha256'] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert len(result['locations']['0x10']) == 2
    assert result['locations']['0x20'][0]['file'] == 0
    assert resolved == [str(src)]


def test_no_source_roots_skip_filesystem_resolution(monkeypatch):
    monkeypatch.setattr(Path, 'resolve', lambda *args, **kwargs: pytest.fail('unexpected filesystem lookup'))
    assert S.resolve_file('/build/kernel.c', [], []) is None


def test_archived_source_wins_over_changed_live_file(tmp_path, monkeypatch):
    elf = tmp_path / 'kernel.elf'
    elf.write_bytes(b'elf')
    monkeypatch.setattr(S, 'llvm_tool', lambda _: 'symbolizer')
    monkeypatch.setattr(S.subprocess, 'run', lambda *args, **kwargs: NS(stdout=json.dumps(
        {'Symbol': [{'FileName': '/old/kernel.c', 'Line': 1, 'FunctionName': 'root'}]})))
    archived = {'path': 'kernel.c', 'text': 'original\n', 'sha256': 'test'}
    result = S.build_source(elf, [16], snapshot={'files': {'/old/kernel.c': archived}})
    assert result['files'] == [archived]
    assert result['snapshot'] == 'record'


def test_missing_tools_leave_report_usable(monkeypatch):
    monkeypatch.setattr(S, 'llvm_tool', lambda _: None)
    assert S.build_source(None, [16])['status'] == 'symbolizer_missing'
    assert S.full_names(['_ZN2os4root17h1234567890abcdefE']) == ['os::root']


def test_full_names_preserve_trait_and_remove_rust_hash():
    if not S.llvm_tool('llvm-cxxfilt'):
        pytest.skip('llvm-cxxfilt required')
    raw = '_RNvXs5_NtNtNtNtCsaZSK9boPIKd_13starry_kernel2mm6aspace7backend3cowNtB5_10CowBackendNtB7_10BackendOps9clone_map'
    full = S.full_names([raw, '_ZN2os4root17h1234567890abcdefE'])
    assert ' as ' in full[0] and 'BackendOps' in full[0]
    assert full[1] == 'os::root'


def test_escaped_rust_dwarf_names_keep_trait_information():
    from nodefusion.model.symbols import display_dwarf_name
    assert display_dwarf_name('_$LT$os..console..Stdout$u20$as$u20$core..fmt..Write$GT$::write_str') == '<os::console::Stdout as core::fmt::Write>::write_str'


def test_source_cli_options():
    from nodefusion.host.cli import build_parser
    parser = build_parser()
    options = parser.parse_args(['render', '--run', 'boot', '--source-root', '/kernel',
                                '--source-map', '/build=/kernel'])
    assert options.source_root == ['/kernel']
    assert options.source_map == ['/build=/kernel']
    assert parser.parse_args(['record', '--kernel', '/kernel', '--source-root', '/kernel']).source_root == ['/kernel']


def test_archive_hash_is_checked(tmp_path):
    a = _analysis(_state())
    a.run_dir = tmp_path
    (tmp_path / 'source.snapshot.zlib').write_bytes(b'changed')
    a.manifest['source_snapshot'] = {'path': 'source.snapshot.zlib', 'sha256': 'wrong'}
    a.source_roots = [tmp_path]
    with pytest.raises(ValueError, match='source snapshot hash mismatch'):
        build(a)


def test_samples_do_not_merge_instantiations():
    a = _analysis(_state())
    names = ['_ZN2os4root17h1234567890abcdefE', '_ZN2os4root17hfedcba0987654321E']
    a.elf = NS(resolve_pc=lambda pc: (names[pc - 1], 0))
    a.trace.samples = [NS(insn=pc, cpu=0, pc=pc, priv=1) for pc in (1, 2)]
    samples = build(a)['samples']
    assert samples['func'] == [0, 1]
    assert samples['raw_funcs'] == names
    assert samples['funcs'] == ['os::root', 'os::root']


def test_actual_riscv_dwarf_and_source_archive(tmp_path):
    compiler = next((str(p) for p in [Path('/opt/homebrew/opt/llvm/bin/clang'),
                                     Path('/usr/local/opt/llvm/bin/clang')] if p.is_file()), shutil.which('clang'))
    if not compiler or not S.llvm_tool('llvm-symbolizer'):
        pytest.skip('clang and llvm-symbolizer required')
    src = tmp_path / 'kernel.c'
    src.write_text('int first(int x) { return x + 1; }\nint second(int x) { return first(x); }\n')
    elf = tmp_path / 'kernel.o'
    subprocess.run([compiler, '--target=riscv64-unknown-elf', '-g', '-O0', '-c', str(src), '-o', str(elf)], check=True)
    linker = Path(compiler).with_name('ld.lld')
    if not linker.is_file():
        rustc = shutil.which('rustc')
        if rustc:
            sysroot = Path(subprocess.check_output([rustc, '--print', 'sysroot'], text=True).strip())
            linker = next(sysroot.glob('lib/rustlib/*/bin/rust-lld'), linker)
    if not linker.is_file():
        pytest.skip('RISC-V lld required')
    linked = tmp_path / 'kernel.elf'
    subprocess.run([str(linker), '-flavor', 'gnu', '-m', 'elf64lriscv', '-e', 'second', '-Ttext=0x80000000', str(elf), '-o', str(linked)], check=True)
    elf = linked
    from nodefusion.host.nfelf import Elf64
    pc = next(s.value for s in Elf64(str(elf)).symbols if s.name == 'second')
    result = S.build_source(elf, [pc], roots=[tmp_path])
    assert result['locations'][hex(pc)][0]['line'] == 2
    assert result['files'][0]['text'] == src.read_text()
    archive = tmp_path / 'source.snapshot.zlib'
    record = S.capture_snapshot(elf, archive, [tmp_path])
    assert record['files'] == 1
    payload = archive.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == record['sha256']
    src.write_text('changed')
    enriched = S.build_source(elf, [pc], snapshot=json.loads(zlib.decompress(payload)))
    assert 'int second' in enriched['files'][0]['text']
