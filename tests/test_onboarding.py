import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine.onboarding import doctor, load_config, run_setup, run_cleanup


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def config(self, extra=''):
        (self.root / '.greenpr.toml').write_text('version=1\nproject="."\ngates=["npm test", "npm run typecheck"]\n'+extra, encoding='utf-8')
        return load_config(self.root)

    def test_absent_config_has_no_side_effects(self):
        self.assertIsNone(load_config(self.root))

    def test_all_gates_preserved(self):
        self.assertEqual(self.config().gates, ('npm test', 'npm run typecheck'))

    def test_timeout_bounds_and_run_identity_cannot_be_overridden(self):
        self.assertEqual(self.config().timeout_seconds, 300)
        for value in ('0', '-1', '7201', 'true', '1.5', '"300"'):
            with self.assertRaises(ValueError):
                self.config('timeout_seconds='+value)
        self.assertEqual(self.config('timeout_seconds=7200').timeout_seconds, 7200)
        with self.assertRaises(ValueError):
            self.config('[environment]\nGREENPR_RUN_ID="other-project"')

    def test_cleanup_defaults_empty_and_attempts_every_explicit_command(self):
        self.assertEqual(self.config().cleanup, ())
        config = self.config('timeout_seconds=45\ncleanup=["first", "second", "third"]')
        checkout = self.root / 'cleanup-worktree'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: elsewhere')
        calls = []
        def runner(command, label, timeout):
            self.assertEqual(timeout, 45)
            calls.append(command)
            if command == 'first':
                raise OSError('sensitive error text')
            return SimpleNamespace(returncode=int(command == 'second'))
        previous = Path.cwd()
        try:
            os.chdir(checkout)
            failures = run_cleanup(config, checkout, runner)
        finally:
            os.chdir(previous)
        self.assertEqual(calls, ['first', 'second', 'third'])
        self.assertEqual(len(failures), 2)
        self.assertNotIn('sensitive', str(failures))

    def test_cleanup_cannot_run_in_original(self):
        config = self.config('cleanup=["do-not-run"]')
        with self.assertRaises(ValueError):
            run_cleanup(config, self.root, lambda *a, **kw: self.fail('must not run'))

    def test_missing_gates_and_unknown_settings_rejected(self):
        for content in ('version=1\nproject="."', 'version=1\nproject="."\ngates=[]', 'version=1\nproject="."\ngates=["test"]\nfallback="true"'):
            (self.root / '.greenpr.toml').write_text(content)
            with self.assertRaises(ValueError):
                load_config(self.root)

    def test_project_escape_rejected(self):
        (self.root / '.greenpr.toml').write_text('version=1\nproject=".."\ngates=["test"]')
        with self.assertRaises(ValueError):
            load_config(self.root)

    def test_remote_service_and_process_injection_rejected(self):
        for extra in ('services=["example.com:443"]', '[environment]\nPATH="bad"', '[environment]\nNODE_OPTIONS="bad"'):
            with self.assertRaises(ValueError):
                self.config(extra)

    def test_doctor_reports_names_without_values_and_never_runs_setup(self):
        config = self.config('required_env=["GREENPR_TEST_MISSING"]\nexecutables=["greenpr-no-such-executable"]\nsetup=["do-not-run"]\n[environment]\nSAFE_TEST_VALUE="sensitive-looking-value"')
        with patch.dict(os.environ, {}, clear=True):
            findings = doctor(config)
        self.assertEqual({f.code for f in findings}, {'environment', 'executable'})
        self.assertNotIn('sensitive-looking-value', str(findings))

    def test_explicit_test_default_satisfies_required_environment(self):
        config = self.config('required_env=["TEST_MODE"]\n[environment]\nTEST_MODE="test"')
        self.assertEqual(doctor(config), [])

    def test_setup_refuses_original_checkout(self):
        config = self.config('setup=["test-command"]')
        (self.root / '.git').write_text('gitdir: elsewhere')
        with self.assertRaises(ValueError):
            run_setup(config, self.root, lambda *a, **k: self.fail('must not run'))

    def test_setup_runs_in_isolated_project_and_stops_on_failure(self):
        config = self.config('setup=["first", "second", "must-not-run"]')
        checkout = self.root / 'isolated'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: elsewhere')
        calls = []
        def runner(command, label, timeout):
            calls.append(command)
            return SimpleNamespace(returncode=int(command == 'second'))
        previous = Path.cwd()
        try:
            os.chdir(checkout)
            with self.assertRaises(RuntimeError):
                run_setup(config, checkout, runner)
        finally:
            os.chdir(previous)
        self.assertEqual(calls, ['first', 'second'])

    def test_unavailable_service_is_actionable(self):
        config = self.config('services=["127.0.0.1:5432"]')
        with patch('engine.onboarding.socket.create_connection', side_effect=OSError):
            findings = doctor(config)
        self.assertEqual(findings[0].code, 'service')
        self.assertIn('5432', findings[0].message)


if __name__ == '__main__':
    unittest.main()
