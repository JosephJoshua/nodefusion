"""Build the teaching book and stage the repository's self-contained reports."""

from __future__ import annotations

import argparse
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zlib


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = re.compile(r'<script type="application/nodefusion"[^>]*>([^<]+)</script>')


class Page(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.ids.add(values['id'])
        for key in ('href', 'src'):
            if values.get(key):
                self.links.append(values[key])


def validate_links(folder: Path, base: str = '/') -> int:
    folder = folder.resolve()
    pages = {p.resolve(): Page(p.read_text(encoding='utf-8'))
             for p in folder.rglob('*.html')}
    errors = []
    for path, page in pages.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            relative = unquote(url.path)
            if relative.startswith('/'):
                if base != '/' and relative.startswith(base):
                    relative = relative[len(base):]
                target = folder / relative.lstrip('/')
            else:
                target = path.parent / relative if relative else path
            target = target.resolve()
            if not target.is_relative_to(folder.resolve()):
                errors.append(f'{path.relative_to(folder)}: {link} leaves the site')
                continue
            if target.is_dir():
                target /= 'index.html'
            if not target.is_file():
                errors.append(f'{path.relative_to(folder)}: missing {link}')
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                errors.append(f'{path.relative_to(folder)}: missing anchor {link}')
    if errors:
        raise ValueError('\n'.join(errors))
    for path in folder.rglob('*.svg'):
        ET.parse(path)
    return len(pages)


def stage_reports(artifacts: Path, destination: Path) -> list[dict]:
    reports = []
    files = sorted(p for p in artifacts.rglob('*') if p.suffix in ('.html', '.json', '.log'))
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'expected a regular artifact: {path}')
        payload = path.read_bytes()
        if path.suffix == '.json':
            json.loads(payload)
        elif path.suffix == '.html':
            text = payload.decode('utf-8')
            bundles = BUNDLE.findall(text)
            if not bundles:
                raise ValueError(f'report has no NodeFusion data: {path}')
            for bundle in bundles:
                data = json.loads(zlib.decompress(base64.b64decode(bundle, validate=True)))
                if not isinstance(data, dict) or not {'meta', 'events'} <= data.keys():
                    raise ValueError(f'invalid report data: {path}')
            reports.append({'path': path.relative_to(artifacts).as_posix(),
                            'sha256': hashlib.sha256(payload).hexdigest(),
                            'bytes': len(payload), 'runs': len(bundles)})
    # Validate all inputs before writing the report set.
    destination.mkdir(parents=True, exist_ok=True)
    for path in files:
        target = destination / path.relative_to(artifacts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (destination / 'index.json').write_text(
        json.dumps({'reports': reports}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return reports


def build(destination: Path, mdbook: str, artifacts: Path) -> tuple[int, int]:
    destination = destination.resolve()
    source = ROOT / 'site/src'
    if (destination in ROOT.parents or destination == ROOT or
            source.is_relative_to(destination) or artifacts.resolve().is_relative_to(destination) or
            destination.is_relative_to(source) or destination.is_relative_to(artifacts.resolve())):
        raise ValueError('destination overlaps source files or artifacts')
    subprocess.run([mdbook, 'build', str(ROOT / 'site'), '--dest-dir', str(destination)], check=True)
    reports = stage_reports(artifacts, destination / 'reports')
    config = tomllib.loads((ROOT / 'site/book.toml').read_text(encoding='utf-8'))
    pages = validate_links(destination, config['output']['html'].get('site-url', '/'))
    return pages, len(reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest-dir', type=Path, default=ROOT / 'site/book')
    parser.add_argument('--mdbook', default='mdbook')
    parser.add_argument('--artifacts', type=Path, default=ROOT / 'artifacts')
    args = parser.parse_args()
    pages, reports = build(args.dest_dir, args.mdbook, args.artifacts)
    print(f'Built {pages} pages, including {reports} reports: {args.dest_dir}')


if __name__ == '__main__':
    main()
