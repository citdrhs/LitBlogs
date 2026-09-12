"""Shared-site scope guarantees, with no Nginx process or host writes."""
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('cit_nginx_route', ROOT / 'deploy/cit-public/nginx_route.py')
route = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(route)


class NginxRouteTests(unittest.TestCase):
    def test_only_litblogs_location_and_its_old_comment_change(self):
        before = 'server {\n  location /dreb { proxy_pass http://other; }\n'
        after = '  location /drsu { alias /unchanged/; }\n}\n'
        old = '  # /dren -> old LitBlogs\n  location /dren {\n    proxy_set_header X-Example "}"; # }\n    if ($x) { return 400; }\n    proxy_pass http://old;\n  }\n'
        new = '  location = /dren { return 308 /dren/; }\n  location ^~ /dren/ { proxy_pass https://local/; }\n'
        self.assertEqual(route.replace_location(before + old + after, new), before + new + after)

    def test_ambiguous_missing_wrong_case_and_unterminated_blocks_fail_closed(self):
        for text in ('location /dreb {}', 'location /DREN {}', 'location /drenfoo {}',
                     'location /dren {\n', 'location /dren {}\nlocation /dren {}\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                route.replace_location(text, 'location /dren/ {}\n')

    def test_adjacent_suffix_and_unrelated_comments_survive_byte_for_byte(self):
        source = '# unrelated\nlocation /dren {}\nlocation /dren-other {}\n'
        self.assertEqual(route.replace_location(source, 'location = /dren {}\n'),
                         '# unrelated\nlocation = /dren {}\nlocation /dren-other {}\n')


class NginxTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='litblogs-nginx-test-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.nginx = root / 'nginx'
        self.enabled = self.nginx / 'sites-enabled'
        self.enabled.mkdir(parents=True)
        self.site = self.enabled / 'default'
        self.main = self.nginx / 'nginx.conf'
        self.sibling = self.enabled / 'another-project'
        self.state = root / 'state'
        self.state.mkdir()
        self.before = b'server {\n location /dren { return 404; }\n}\n'
        self.site.write_bytes(self.before)
        self.sibling.write_bytes(b'server { listen 9443; }\n')
        (self.nginx / 'fastcgi_params').write_bytes(b'fastcgi_param QUERY_STRING $query_string;\n')
        self.main.write_text('http { include /etc/nginx/sites-enabled/*; }\n')
        (self.state / 'nginx-dren.conf').write_text(' location = /dren { return 308 /dren/; }\n')
        self.patches = patch.multiple(route, STATE=self.state, SITE=self.site, LINK=self.site, MAIN=self.main)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.events = []
        self.on_command = lambda action: None
        self.after_write = lambda data: None
        self.real_atomic = route.atomic_site
        self.real_directory_fsync = route.fsync_directory

        def fake_command(arguments):
            if '-c' in arguments:
                action = 'check:rollback' if 'rollback' in arguments[-1] else 'check:candidate'
            else:
                action = 'reload' if 'reload' in arguments else 'check:live'
            self.events.append(action)
            self.on_command(action)

        def fake_atomic(data, metadata):
            self.events.append('write:before' if data == self.before else 'write:candidate')
            self.site.write_bytes(data)
            self.after_write(data)

        for name, value in (('command', fake_command), ('atomic_site', fake_atomic)):
            patcher = patch.object(route, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        # The production directory fsync is exercised separately on POSIX.
        patcher = patch.object(route, 'fsync_directory', lambda path: self.events.append('fsync:directory'), create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            route.stage()
        except OSError as error:
            if os.name == 'nt' and getattr(error, 'winerror', None) == 1314:
                self.skipTest('requires Windows symbolic-link privilege; full suite runs on Ubuntu')
            raise
        self.candidate = (self.state / 'default.candidate').read_bytes()
        self.events.clear()

    def test_commit_validates_before_write_and_reload(self):
        route.commit()
        self.assertEqual(self.events, ['check:candidate', 'write:candidate', 'check:live', 'reload'])
        self.assertEqual(self.site.read_bytes(), self.candidate)

    def test_ambiguous_reload_failure_restores_and_reloads_original(self):
        def fail_first_reload(action):
            if action == 'reload' and self.events.count('reload') == 1:
                raise TimeoutError('uncertain reload')
        self.on_command = fail_first_reload
        with self.assertRaises(TimeoutError):
            route.commit()
        self.assertEqual(self.site.read_bytes(), self.before)
        self.assertEqual(self.events[-3:], ['write:before', 'check:live', 'reload'])

    def test_failed_live_syntax_check_recovers_without_reload(self):
        def fail_first_live_check(action):
            if action == 'check:live' and self.events.count(action) == 1:
                raise ValueError('candidate syntax rejected')
        self.on_command = fail_first_live_check
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.site.read_bytes(), self.before)
        self.assertNotIn('reload', self.events)
        self.assertEqual(self.events[-2:], ['write:before', 'check:live'])

    def test_write_failure_after_replace_is_recovered(self):
        def fail_candidate_fsync(data):
            if data == self.candidate:
                raise OSError('directory fsync failed after rename')
        self.after_write = fail_candidate_fsync
        with self.assertRaises(OSError):
            route.commit()
        self.assertEqual(self.site.read_bytes(), self.before)
        self.assertNotIn('reload', self.events)

    def test_sibling_edit_during_candidate_validation_prevents_write(self):
        self.on_command = lambda action: self.sibling.write_bytes(b'changed by another operator\n')
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.site.read_bytes(), self.before)
        self.assertEqual(self.events, ['check:candidate'])

    def test_new_enabled_site_since_stage_prevents_validation_or_reload(self):
        (self.enabled / 'new-project').write_bytes(b'new unrelated configuration\n')
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.events, [])

    def test_main_edit_after_install_prevents_reload_and_restores_only_our_file(self):
        changed = b'other operator main configuration\n'
        def edit_after_check(action):
            if action == 'check:live':
                self.main.write_bytes(changed)
        self.on_command = edit_after_check
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.site.read_bytes(), self.before)
        self.assertEqual(self.main.read_bytes(), changed)
        self.assertNotIn('reload', self.events)

    def test_concurrent_site_edit_is_never_overwritten_by_recovery(self):
        changed = b'sibling project edit in shared site\n'
        def edit_after_check(action):
            if action == 'check:live':
                self.site.write_bytes(changed)
        self.on_command = edit_after_check
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.site.read_bytes(), changed)
        self.assertNotIn('write:before', self.events)
        self.assertNotIn('reload', self.events)

    def test_rollback_prevalidation_failure_keeps_candidate(self):
        route.commit()
        self.events.clear()
        def reject_original(action):
            if action == 'check:rollback':
                raise ValueError('original no longer validates')
        self.on_command = reject_original
        with self.assertRaises(ValueError):
            route.rollback()
        self.assertEqual(self.site.read_bytes(), self.candidate)
        self.assertEqual(self.events, ['check:rollback'])

    def test_rollback_reload_failure_restores_and_reloads_candidate(self):
        route.commit()
        self.events.clear()
        def fail_first_reload(action):
            if action == 'reload' and self.events.count('reload') == 1:
                raise TimeoutError('uncertain rollback reload')
        self.on_command = fail_first_reload
        with self.assertRaises(TimeoutError):
            route.rollback()
        self.assertEqual(self.site.read_bytes(), self.candidate)
        self.assertEqual(self.events[-3:], ['write:candidate', 'check:live', 'reload'])

    def test_changed_staged_validation_file_cannot_be_committed(self):
        (self.state / 'nginx-test.conf').write_bytes(b'different validation target\n')
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.events, [])

    def test_candidate_and_rollback_keep_relative_include_targets(self):
        for name in ('nginx-test.conf', 'nginx-rollback-test.conf'):
            relative = (self.state / name).parent / 'fastcgi_params'
            self.assertTrue(relative.is_symlink())
            self.assertEqual(relative.resolve(), self.nginx / 'fastcgi_params')
            self.assertEqual(relative.read_bytes(), (self.nginx / 'fastcgi_params').read_bytes())
        self.assertTrue((self.state / 'sites-enabled').is_symlink())
        self.assertEqual((self.state / 'sites-enabled' / 'another-project').read_bytes(), self.sibling.read_bytes())

    def test_changed_relative_include_link_fails_before_validation(self):
        mirror = self.state / 'fastcgi_params'
        mirror.unlink(missing_ok=True)
        mirror.write_bytes(b'replacement configuration at the staged include path\n')
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.events, [])

    def test_missing_relative_include_link_fails_before_validation(self):
        (self.state / 'fastcgi_params').unlink(missing_ok=True)
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.events, [])

    @unittest.skipUnless(os.name == 'posix', 'requires unprivileged symbolic links')
    def test_retargeted_relative_include_link_is_rejected(self):
        mirror = self.state / 'fastcgi_params'
        mirror.unlink(missing_ok=True)
        mirror.symlink_to(self.sibling)
        with self.assertRaises(ValueError):
            route.commit()
        self.assertEqual(self.events, [])

    def test_stage_fsyncs_every_artifact_and_directory_before_validation(self):
        fresh = self.state / 'fresh'
        fresh.mkdir()
        (fresh / 'nginx-dren.conf').write_text(' location = /dren { return 308 /dren/; }\n')
        self.events.clear()
        with patch.object(route, 'STATE', fresh), patch.object(route.os, 'fsync', lambda fd: self.events.append('fsync:file')):
            route.stage()
        self.assertGreaterEqual(self.events.count('fsync:file'), 5)
        self.assertLess(self.events.index('fsync:directory'), self.events.index('check:candidate'))

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX ownership and directory fsync')
    def test_atomic_file_replacement_preserves_custody_and_cleans_temporary_file(self):
        information = self.site.stat()
        metadata = {'mode': stat.S_IMODE(information.st_mode),
                    'uid': information.st_uid, 'gid': information.st_gid}
        with patch.object(route, 'fsync_directory', self.real_directory_fsync):
            self.real_atomic(self.candidate, metadata)
        current = self.site.stat()
        self.assertEqual(self.site.read_bytes(), self.candidate)
        self.assertEqual((stat.S_IMODE(current.st_mode), current.st_uid, current.st_gid),
                         (metadata['mode'], metadata['uid'], metadata['gid']))
        self.assertEqual(list(self.enabled.glob('.litblogs-dren-*')), [])
        self.assertEqual(stat.S_IMODE((self.state / 'default.before').stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == 'posix', 'requires unprivileged symbolic links')
    def test_snapshot_includes_external_file_symlink_contents(self):
        target = self.state / 'external.conf'
        target.write_bytes(b'external included configuration\n')
        (self.enabled / 'external').symlink_to(target)
        before = route.configuration_snapshot()
        target.write_bytes(b'external configuration changed\n')
        self.assertNotEqual(before, route.configuration_snapshot())

    @unittest.skipUnless(os.name == 'posix', 'requires unprivileged symbolic links')
    def test_snapshot_rejects_directory_symlink(self):
        (self.nginx / 'linked-directory').symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(ValueError):
            route.configuration_snapshot()


if __name__ == '__main__':
    unittest.main()
