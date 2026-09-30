import base64
import json
from pathlib import Path
import tempfile
import unittest
import zlib

from scripts.build_education_site import stage_reports, validate_links


class SiteBuildTests(unittest.TestCase):
    def test_manifest_guides_match_repository_docs(self):
        root = Path(__file__).resolve().parents[2]
        substitutions = {
            'AUTHORING.md': ('adding-kernel.md', {'(REFERENCE.md': '(manifest-reference.md',
                '(../../nodefusion/spec/event-stream.md)': '(https://github.com/JosephJoshua/nodefusion/blob/main/nodefusion/spec/event-stream.md)',
                '(../../nodefusion/integrations/README.md)': '(https://github.com/JosephJoshua/nodefusion/blob/main/nodefusion/integrations/README.md)'}),
            'REFERENCE.md': ('manifest-reference.md', {'(AUTHORING.md': '(adding-kernel.md'}),
        }
        for source, (target, links) in substitutions.items():
            with self.subTest(source=source):
                expected = (root / 'docs/manifests' / source).read_text(encoding='utf-8')
                for before, after in links.items():
                    expected = expected.replace(before, after)
                self.assertEqual((root / 'site/src/guides' / target).read_text(encoding='utf-8'), expected)

    def test_local_links_and_chinese_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'index.html').write_text('<a href="/nodefusion/ch.html#%E8%B0%83%E5%BA%A6">chapter</a>')
            (root / 'ch.html').write_text('<h2 id="调度">heading</h2><a href="https://example.com">source</a>')
            self.assertEqual(validate_links(root, '/nodefusion/'), 2)
            (root / 'ch.html').write_text('<a href="missing.html">broken</a>')
            with self.assertRaisesRegex(ValueError, 'missing'):
                validate_links(root, '/nodefusion/')

    def test_missing_fragment_and_directory_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for href in ('#absent', '../outside.html'):
                (root / 'index.html').write_text(f'<a href="{href}">link</a>')
                with self.assertRaises(ValueError):
                    validate_links(root)

    def test_reports_are_validated_before_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = root / 'input', root / 'output'
            source.mkdir()
            bundle = base64.b64encode(zlib.compress(json.dumps({'meta': {}, 'events': {}}).encode())).decode()
            (source / 'good.html').write_text(f'<script type="application/nodefusion">{bundle}</script>')
            (source / 'bad.json').write_text('{')
            with self.assertRaises(json.JSONDecodeError):
                stage_reports(source, target)
            self.assertFalse(target.exists())
            (source / 'bad.json').write_text('{}')
            reports = stage_reports(source, target)
            self.assertEqual(reports[0]['path'], 'good.html')
            self.assertEqual((target / 'good.html').read_bytes(), (source / 'good.html').read_bytes())
            self.assertTrue((target / 'index.json').is_file())


if __name__ == '__main__':
    unittest.main()
