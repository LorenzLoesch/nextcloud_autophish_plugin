#!/usr/bin/env python3
"""Release metadata checks; no credentials or production access required."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
APP_ID = 'integration_autophish'
VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:beta|rc)\.(?:0|[1-9][0-9]*))?'


def metadata(root=ROOT):
    raw = (root / 'appinfo/info.xml').read_bytes()
    if len(raw) >= 512 * 1024 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('Invalid or oversized info.xml')
    info = ET.fromstring(raw)
    version = info.findtext('version', '')
    if info.findtext('id') != APP_ID or not re.fullmatch(VERSION, version):
        raise ValueError('Invalid app ID or release version')
    if info.findtext('licence') != 'AGPL-3.0-or-later':
        raise ValueError('AGPL-3.0-or-later is required')
    for name in ('package.json', 'package-lock.json'):
        package = json.loads((root / name).read_text())
        if package['version'] != version or (name == 'package-lock.json' and package['packages']['']['version'] != version):
            raise ValueError(f'{name} version differs from info.xml')
    bounds = info.find('dependencies/nextcloud')
    minimum, maximum = int(bounds.attrib['min-version']), int(bounds.attrib['max-version'])
    images = json.loads((root / 'scripts/nextcloud-matrix.json').read_text())
    if minimum != 32 or maximum < minimum or not set(range(minimum, maximum + 1)) <= set(map(int, images)):
        raise ValueError('Declared Nextcloud compatibility is not covered by the smoke matrix')
    for major, image in images.items():
        if not re.fullmatch(r'nextcloud:' + major + r'\.[0-9]+\.[0-9]+-apache@sha256:[a-f0-9]{64}', image):
            raise ValueError('Smoke images must be pinned official Nextcloud images')
    screenshots = info.findall('screenshot')
    if not 2 <= len(screenshots) <= 3:
        raise ValueError('Two or three App Store screenshots are required')
    prefix = 'https://raw.githubusercontent.com/LorenzLoesch/nextcloud_autophish_plugin/'
    for screenshot in screenshots:
        url = screenshot.text or ''
        match = re.fullmatch(re.escape(prefix) + r'(?:main|[a-f0-9]{40})/screenshots/([a-z0-9-]+\.png)', url)
        if not match:
            raise ValueError('Screenshot must reference a committed HTTPS PNG on main or an immutable commit')
        path = root / 'screenshots' / match.group(1)
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024 or path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Screenshot missing, not a PNG or exceeds 2 MiB')
    notes(version, root)
    return info, version, minimum, maximum, images


def notes(version, root=ROOT):
    text = (root / 'CHANGELOG.md').read_text()
    matches = list(re.finditer(r'^## ' + re.escape(version) + r'(?:[ \t]+-[ \t]+\d{4}-\d{2}-\d{2})?[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S))
    if len(matches) != 1:
        raise ValueError('Changelog must contain exactly one heading for the release version')
    body = matches[0].group(1).strip()
    if not re.sub(r'(?m)^#+[^\n]*|\s|<!--.*?-->', '', body, flags=re.S):
        raise ValueError('Changelog release section is empty')
    return body


def check_platforms(info, platforms):
    released = [tuple(map(int, item['version'].split('.'))) for item in platforms
                if item.get('hasRelease') and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', item['version'])]
    if not released or int(info.find('dependencies/nextcloud').attrib['max-version']) > max(released)[0] + 1:
        raise ValueError('Compatibility exceeds the current stable Nextcloud plus one')


def verify_store(info, catalogue):
    version = info.findtext('version')
    bounds = info.find('dependencies/nextcloud').attrib
    expected = f">={int(bounds['min-version'])}.0.0 <{int(bounds['max-version']) + 1}.0.0"
    app = next((item for item in catalogue if item['id'] == APP_ID), None)
    release = next((item for item in (app or {}).get('releases', []) if item['version'] == version and item.get('isNightly') is False), None)
    if not release:
        raise ValueError('Published non-nightly version not visible in the store catalogue yet')
    if release.get('platformVersionSpec') != expected:
        raise ValueError(f'Store compatibility differs from info.xml (expected {expected})')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'version', 'matrix', 'image', 'notes', 'tag', 'platforms', 'store'])
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    info, version, minimum, maximum, images = metadata()
    if args.command == 'version':
        print(version)
    elif args.command == 'matrix':
        matrix = [{'major': int(major), 'database': 'sqlite'} for major in images]
        matrix += [{'major': max(map(int, images)), 'database': database} for database in ('pgsql', 'mysql')]
        print(json.dumps({'include': matrix}, separators=(',', ':')))
    elif args.command == 'image':
        print(images[args.value or str(maximum)])
    elif args.command == 'notes':
        print(notes(version))
    elif args.command == 'tag':
        if args.value != 'v' + version:
            raise ValueError('Tag must equal info.xml, package.json and changelog version')
        tag = subprocess.check_output(['git', 'rev-parse', '--verify', f'refs/tags/{args.value}^{{commit}}'], text=True).strip()
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        if tag != head:
            raise ValueError('Checked out commit differs from release tag')
        subprocess.run(['git', 'merge-base', '--is-ancestor', tag, 'refs/remotes/origin/main'], check=True)
        print('Tag and main ancestry verified')
    elif args.command == 'platforms':
        check_platforms(info, json.loads(Path(args.value).read_text()))
    elif args.command == 'store':
        print(f'{APP_ID} {version}: non-nightly; ' + verify_store(info, json.loads(Path(args.value).read_text())))
    else:
        print('Release metadata validated')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, ET.ParseError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
