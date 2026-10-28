"""Release guardrails using temporary repositories and synthetic HTTP/CLI responses."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import release
spec = importlib.util.spec_from_file_location('artifact', ROOT / 'scripts/check-artifact.py')
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


def normalize_fixture_version(root):
    # Keep fixture expectations stable when maintainers bump the real release version.
    current = release.ET.parse(root / 'appinfo/info.xml').getroot().findtext('version')
    if current != '1.0.1':
        fixture_notes = release.notes(current, root)
        (root / 'CHANGELOG.md').write_text('# Changelog\n\n## 1.0.1\n\n' + fixture_notes + '\n')
        for name in ('appinfo/info.xml', 'package.json', 'package-lock.json'):
            path = root / name
            path.write_text(path.read_text().replace(current, '1.0.1'))


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for entry in ('appinfo', 'scripts', 'screenshots'):
            if (ROOT / entry).exists(): shutil.copytree(ROOT / entry, self.root / entry)
        for entry in ('package.json', 'package-lock.json', 'CHANGELOG.md'):
            shutil.copy(ROOT / entry, self.root / entry)
        normalize_fixture_version(self.root)

    def test_real_metadata(self):
        self.assertEqual(release.metadata(self.root)[1], '1.0.1')

    def test_version_mismatch(self):
        path = self.root / 'package.json'
        path.write_text(path.read_text().replace('1.0.1', '1.0.2'))
        with self.assertRaisesRegex(ValueError, 'version differs'): release.metadata(self.root)

    def test_lock_mismatch(self):
        path = self.root / 'package-lock.json'
        value = json.loads(path.read_text()); value['packages']['']['version'] = '1.0.2'; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'version differs'): release.metadata(self.root)

    def test_missing_matrix_major(self):
        path = self.root / 'scripts/nextcloud-matrix.json'
        value = json.loads(path.read_text()); del value['33']; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'smoke matrix'): release.metadata(self.root)

    def test_screenshot_ref_rejects_unstable_branches(self):
        path = self.root / 'appinfo/info.xml'
        original = path.read_text()
        ref = release.ET.fromstring(original).findtext('screenshot').split('/')[5]
        for invalid in ('feature/screenshot', 'HEAD', 'a' * 39):
            path.write_text(original.replace('/' + ref + '/screenshots/', '/' + invalid + '/screenshots/'))
            with self.assertRaisesRegex(ValueError, 'Screenshot must reference'):
                release.metadata(self.root)

    def test_screenshot_size_and_type(self):
        path = self.root / 'screenshots/admin-settings.png'
        path.write_bytes(b'not a PNG')
        with self.assertRaisesRegex(ValueError, 'Screenshot missing'): release.metadata(self.root)
        with path.open('wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\n')
            handle.truncate(2 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, 'exceeds 2 MiB'): release.metadata(self.root)

    def test_version_shapes(self):
        for version in ('1.0.1', '1.0.1-beta.1', '1.0.1-rc.2'):
            self.assertRegex(version, '^' + release.VERSION + '$')
        for version in ('v1.0.1', '1.0.01', '1.0.1-beta.01', '1.0.1+build', '1.0.1-evil'):
            self.assertNotRegex(version, '^' + release.VERSION + '$')

    def test_changelog_exact_and_nonempty(self):
        path = self.root / 'CHANGELOG.md'
        for text in ('## 1.0.10\n- Wrong\n', '## 1.0.1\n### Added\n\n## 1.0.0\n- Previous\n',
                     '## 1.0.1\n<!-- later -->\n', '## 1.0.1\n- first\n## 1.0.1\n- duplicate\n'):
            path.write_text(text)
            with self.assertRaises(ValueError): release.notes('1.0.1', self.root)
        path.write_text('## 1.0.1 - 2026-10-10\n### Added\n- Something\n## 1.0.0\n- Old\n')
        self.assertEqual(release.notes('1.0.1', self.root), '### Added\n- Something')

    def test_platform_limit_ignores_unreleased(self):
        info = release.metadata(self.root)[0]
        release.check_platforms(info, [{'version': '34.0.4', 'hasRelease': True}])
        with self.assertRaises(ValueError):
            release.check_platforms(info, [{'version': '32.0.1', 'hasRelease': True}, {'version': '99.0.0', 'hasRelease': False}])

    def test_store_checks_channel_and_bounds(self):
        info = release.metadata(self.root)[0]
        entry = {'version': '1.0.1', 'isNightly': False, 'platformVersionSpec': '>=32.0.0 <36.0.0'}
        catalogue = [{'id': release.APP_ID, 'releases': [entry]}]
        self.assertEqual(release.verify_store(info, catalogue), entry['platformVersionSpec'])
        for field, value in [('isNightly', True), ('version', '1.0.0'), ('platformVersionSpec', '>=32.0.0 <34.0.0')]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError): release.verify_store(info, [{'id': release.APP_ID, 'releases': [{**entry, field: value}]}])

    def test_tag_rejects_mismatch_before_git(self):
        with patch.object(sys, 'argv', ['release.py', 'tag', 'v9.9.9']), patch.object(subprocess, 'check_output') as git:
            with self.assertRaisesRegex(ValueError, 'Tag must equal'): release.main()
            git.assert_not_called()

    def test_real_git_ancestry(self):
        def git(*args): return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()
        git('init', '-b', 'main'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture')
        git('add', '.'); git('commit', '-qm', 'fixture'); git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        git('tag', 'v1.0.1')
        command = [sys.executable, str(self.root / 'scripts/release.py'), 'tag', 'v1.0.1']
        self.assertEqual(subprocess.run(command, cwd=self.root, capture_output=True).returncode, 0)
        git('checkout', '-qb', 'unmerged'); (self.root / 'side').write_text('side branch'); git('add', 'side'); git('commit', '-qm', 'side'); git('tag', '-f', 'v1.0.1')
        self.assertNotEqual(subprocess.run(command, cwd=self.root, capture_output=True).returncode, 0)


class ArtifactTests(unittest.TestCase):
    def make_archive(self, extra=None, signed=False):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'test.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name in artifact.REQUIRED | ({'appinfo/signature.json'} if signed else set()):
                entry = tarfile.TarInfo(artifact.APP + '/' + name); entry.size = 1; archive.addfile(entry, io.BytesIO(b'x'))
            if extra is not None: archive.addfile(extra)
        return path

    def test_unsigned_and_signed_are_distinct(self):
        artifact.validate(self.make_archive())
        artifact.validate(self.make_archive(signed=True), signed=True)
        with self.assertRaises(ValueError): artifact.validate(self.make_archive(), signed=True)
        with self.assertRaises(ValueError): artifact.validate(self.make_archive(signed=True))

    def test_unsafe_archive_entries(self):
        for name in ('other/info.xml', 'integration_autophish/.git/config', 'integration_autophish/lib/../secret',
                     '/integration_autophish/LICENSE', 'integration_autophish/lib/.env', 'integration_autophish/lib/tests/test.php'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError): artifact.validate(self.make_archive(tarfile.TarInfo(name)))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            entry = tarfile.TarInfo('integration_autophish/lib/link'); entry.type = kind; entry.linkname = '/etc/passwd'
            with self.assertRaises(ValueError): artifact.validate(self.make_archive(entry))

    def test_archive_size_limit(self):
        path = self.make_archive()
        with path.open('ab') as f: f.truncate(20 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, '20 MiB'): artifact.validate(path)


class PublishTests(unittest.TestCase):
    def run_publish(self, token='', repository='LorenzLoesch/nextcloud_autophish_plugin', status='201', prerelease=False, allow=False):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        project = directory / 'project'; project.mkdir()
        for entry in ('scripts', 'appinfo', 'screenshots'):
            if (ROOT / entry).exists(): shutil.copytree(ROOT / entry, project / entry)
        for entry in ('package.json', 'package-lock.json', 'CHANGELOG.md'): shutil.copy(ROOT / entry, project / entry)
        normalize_fixture_version(project)
        if prerelease:
            for name in ('appinfo/info.xml', 'package.json', 'package-lock.json', 'CHANGELOG.md'):
                p = project / name; p.write_text(p.read_text().replace('1.0.1', '1.0.1-beta.1'))
        version = '1.0.1-beta.1' if prerelease else '1.0.1'
        dist = project / 'dist'; dist.mkdir()
        asset = dist / f'integration_autophish-{version}.tar.gz'
        with tarfile.open(asset, 'w:gz') as archive:
            for name in artifact.REQUIRED | {'appinfo/signature.json'}:
                entry = tarfile.TarInfo(artifact.APP + '/' + name); entry.size = 1; archive.addfile(entry, io.BytesIO(b'x'))
        Path(str(asset) + '.sig').write_text('synthetic-release-signature')
        binaries = directory / 'bin'; binaries.mkdir()
        curl = binaries / 'curl'
        curl.write_text('''#!/usr/bin/env python3
import os,pathlib,sys
args=sys.argv[1:]; log=pathlib.Path(os.environ['CURL_LOG']); log.write_text(log.read_text()+'call\\n' if log.exists() else 'call\\n')
out=pathlib.Path(args[args.index('--output')+1])
if '--request' in args:
    assert args[-1]=='https://apps.nextcloud.com/api/v1/apps/releases'
    assert os.environ['TEST_TOKEN'] not in ' '.join(args)
    headers=pathlib.Path(args[args.index('--header')+1][1:]); assert headers.stat().st_mode & 0o777 == 0o600
    assert headers.read_text()=='Authorization: Token '+os.environ['TEST_TOKEN']+'\\n'
    out.write_text('validation failed' if os.environ['STATUS']=='400' else '{}'); print(os.environ['STATUS'],end='')
else:
    assert '--header' not in args
    out.write_bytes(pathlib.Path(os.environ['ASSET']).read_bytes()); print('200',end='')
''')
        curl.chmod(0o755)
        env = {**os.environ, 'PATH': str(binaries) + ':' + os.environ['PATH'], 'GITHUB_REPOSITORY': repository,
               'APPSTORE_TOKEN': token, 'TEST_TOKEN': token, 'STATUS': status, 'ASSET': str(asset), 'CURL_LOG': str(directory / 'curl.log'),
               'GITHUB_OUTPUT': str(directory / 'output'), 'PUBLISH_PRERELEASES': 'true' if allow else 'false'}
        result = subprocess.run(['bash', 'scripts/publish-appstore.sh'], cwd=project, env=env, capture_output=True, text=True)
        return result, directory

    def test_no_token_makes_no_request(self):
        result, directory = self.run_publish(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((directory / 'curl.log').exists())

    def test_fork_refused(self):
        result, directory = self.run_publish(token='test', repository='someone/fork'); self.assertNotEqual(result.returncode, 0)
        self.assertFalse((directory / 'curl.log').exists())

    def test_prerelease_opt_in(self):
        result, directory = self.run_publish(token='test', prerelease=True); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((directory / 'curl.log').exists())
        result, directory = self.run_publish(token='test', prerelease=True, allow=True); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('published=true', (directory / 'output').read_text())

    def test_success_codes_and_validation_failure(self):
        for status in ('200', '201', '400'):
            with self.subTest(status=status):
                result, directory = self.run_publish(token='synthetic-token', status=status)
                self.assertEqual(result.returncode == 0, status != '400', result.stderr)
                if status == '400': self.assertIn('validation failed', result.stderr)
                self.assertNotIn('synthetic-token', result.stdout + result.stderr)



class GithubReleaseTests(unittest.TestCase):
    def setUp(self):
        module_spec = importlib.util.spec_from_file_location('github_release', ROOT / 'scripts/github-release.py')
        self.module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(self.module)
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); (self.root / 'dist').mkdir()
        self.names = ['integration_autophish-1.0.1.tar.gz' + suffix for suffix in ('', '.sha256', '.sha512', '.sig')]
        for name in self.names: (self.root / 'dist' / name).write_bytes(b'verified bytes')

    def run_with_existing(self, identical=True):
        calls = []
        def gh(*args):
            calls.append(args)
            if args[:2] == ('release', 'download'):
                destination = Path(args[args.index('--dir') + 1]) / args[args.index('--pattern') + 1]
                destination.write_bytes(b'verified bytes' if identical else b'changed bytes')
            return ''
        existing = json.dumps({'isDraft': True, 'assets': [{'name': self.names[0]}]})
        with patch.object(self.module.release, 'ROOT', self.root), patch.object(self.module.release, 'metadata', return_value=(None, '1.0.1')), \
             patch.object(self.module.release, 'notes', return_value='Release notes'), patch.object(self.module, 'gh', side_effect=gh), \
             patch.object(self.module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, existing, '')):
            self.module.main()
        return calls

    def test_resume_compares_existing_and_uploads_missing(self):
        calls = self.run_with_existing()
        self.assertEqual(sum(call[:2] == ('release', 'upload') for call in calls), 3)
        self.assertEqual(calls[-1], ('release', 'edit', 'v1.0.1', '--draft=false'))
        self.assertFalse(any('--clobber' in call for call in calls))

    def test_differing_existing_asset_refused(self):
        with self.assertRaisesRegex(ValueError, 'refusing to overwrite'): self.run_with_existing(False)

if __name__ == '__main__': unittest.main()
