import base64
import hashlib
import json
from pathlib import Path
import re
import zlib

import pytest


ARTIFACTS = Path(__file__).resolve().parents[2] / 'artifacts'
BUNDLE = re.compile(r'<script type="application/nodefusion"[^>]*>([^<]+)</script>')


@pytest.mark.parametrize('path', sorted(ARTIFACTS.rglob('*.html')),
                         ids=lambda path: str(path.relative_to(ARTIFACTS)))
def test_published_reports_include_hashed_source_files(path):
    bundles = BUNDLE.findall(path.read_text(encoding='utf-8'))
    assert bundles
    for encoded in bundles:
        data = json.loads(zlib.decompress(base64.b64decode(encoded)))
        source = data['source']
        assert source['status'] == 'ready'
        assert source['files']
        for file in source['files']:
            assert hashlib.sha256(file['text'].encode('utf-8')).hexdigest() == file['sha256']
        embedded = [location for frames in source['locations'].values() for location in frames
                    if location['file'] is not None]
        assert embedded
        assert any(location['line'] > 0 for location in embedded)
        assert all(0 <= location['file'] < len(source['files']) and location['line'] >= 0
                   for location in embedded)
        line_counts = [len(file['text'].split('\n')) for file in source['files']]
        assert all(location['line'] <= line_counts[location['file']] for location in embedded)


def test_cow_comparison_records_both_source_identities():
    folder = ARTIFACTS / 'xv6/lab3-cow'
    record = json.loads((folder / 'compare-cow.json').read_text())
    assert record['format'] == 'nodefusion.comparison-evidence/1'
    assert hashlib.sha256((folder / record['html']).read_bytes()).hexdigest() == record['html_sha256']
    assert len(record['runs']) == 2
    assert len({run['kernel_elf_sha256'] for run in record['runs']}) == 2
    for run in record['runs']:
        assert len(run['kernel_elf_sha256']) == 64
        assert 'source.snapshot.zlib' in run['source_sha256']
        assert all(len(digest) == 64 for digest in run['source_sha256'].values())
