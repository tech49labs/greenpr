import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import remediate as app
from engine.runtime import git


class OnboardingIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='greenpr-onboarding-integration-')
        self.original = Path.cwd()
        os.chdir(self.tmp.name)
        git('init', '-q')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        Path('requirements.txt').write_text('packaging==26.3\n')
        self.environment = dict(os.environ)

    def tearDown(self):
        os.chdir(self.tmp.name)
        for path in Path('.git/greenpr-runs').glob('*.json'):
            result = json.loads(path.read_text())
            git('worktree', 'remove', '--force', result['worktree'])
        os.chdir(self.original)
        os.environ.clear()
        os.environ.update(self.environment)
        self.tmp.cleanup()

    def config(self, extra='', gate='echo mandatory'):
        Path('.greenpr.toml').write_text('version = 1\nproject = "."\ngates = ['+json.dumps(gate)+']\n'+extra)
        git('add', '.')
        git('commit', '-qm', 'fixture')

    def invoke(self, *args):
        with patch.object(sys, 'argv', ['remediate.py', *args]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return app.main()

    def test_doctor_permits_dirty_repository_and_is_read_only(self):
        self.config()
        Path('requirements.txt').write_text('uncommitted\n')
        before = git('status', '--porcelain')
        with patch('engine.adapters.prepare_baseline') as install, patch.object(app, '_run_current_checkout') as remediation:
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--doctor')
        self.assertEqual(failure.exception.code, 0)
        self.assertEqual(git('status', '--porcelain'), before)
        self.assertFalse(Path('.git/greenpr-runs').exists())
        install.assert_not_called()
        remediation.assert_not_called()

    def test_setup_failure_runs_cleanup_restores_environment_and_keeps_diagnostics(self):
        self.config('setup = ["setup-fixture"]\ncleanup = ["cleanup-fixture"]\n[environment]\nSECRET_KEY = "scoped-fixture-secret"\n')
        os.environ['SECRET_KEY'] = 'original-fixture-secret'
        calls = []
        def runner(command, label, **kwargs):
            from engine.diagnostics import record_command
            calls.append((command, os.environ['SECRET_KEY'], Path.cwd()))
            result = subprocess.CompletedProcess(command, 1 if command == 'setup-fixture' else 0,
                                                 b'', b'decouple.UndefinedValueError: SECRET_KEY not found; scoped-fixture-secret')
            record_command(command, result, phase='setup' if command == 'setup-fixture' else 'cleanup', duration_seconds=.1)
            return result
        with patch('engine.adapters.prepare_baseline', return_value=None), patch.object(app, '_run_with_heartbeat', side_effect=runner), patch.object(app, '_run_current_checkout') as remediation:
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--skip-pr')
        self.assertEqual(failure.exception.code, 2)
        remediation.assert_not_called()
        self.assertEqual([call[0] for call in calls], ['setup-fixture', 'cleanup-fixture'])
        self.assertTrue(all(call[1] == 'scoped-fixture-secret' and call[2] != Path.cwd() for call in calls))
        self.assertEqual(os.environ['SECRET_KEY'], 'original-fixture-secret')
        result = json.loads(next(Path('.git/greenpr-runs').glob('*.json')).read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['original_head_unchanged'])
        self.assertEqual(len(result['commands']), 2)
        self.assertEqual(result['commands'][0]['classification'], 'environment_configuration')
        self.assertNotIn('scoped-fixture-secret', Path(result['commands'][0]['log_path']).read_text())
        self.assertEqual(git('status', '--porcelain'), '')

    def test_required_gate_cannot_be_bypassed_by_cli_gate(self):
        self.config(gate='mandatory-failing-gate')
        with patch('engine.adapters.prepare_baseline', return_value=None), patch.object(app, 'probe_and_select_verification_gate', return_value=(None, 0)) as gate, patch.object(app, 'run_vulnerability_radar') as scan:
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--skip-pr', '--test-cmd', 'echo weaker')
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(gate.call_args.kwargs['custom_cmd'], 'mandatory-failing-gate && echo weaker')
        scan.assert_not_called()

    def test_conflicting_project_rejected_before_worktree_or_setup(self):
        Path('other').mkdir()
        self.config()
        with patch('engine.adapters.prepare_baseline') as install:
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--project', 'other')
        self.assertEqual(failure.exception.code, 2)
        install.assert_not_called()
        self.assertFalse(Path('.git/greenpr-runs').exists())

    def test_pr_body_never_contains_gate_secret(self):
        captured = {}
        def run(command, **kwargs):
            if command[:3] == ['gh', 'pr', 'create']:
                captured['body'] = Path(command[command.index('--body-file')+1]).read_text()
            return subprocess.CompletedProcess(command, 0, 'https://github.com/fixture/repo/pull/1' if command[0] == 'gh' else '', '')
        with patch.dict(os.environ, {'DEPLOY_TOKEN': 'private-pr-fixture'}), patch.object(app.subprocess, 'run', side_effect=run):
            self.assertTrue(app.create_pull_request({'package':'example','target_version':'2.0','verified_gate':'TOKEN=private-pr-fixture pytest'}, None))
        self.assertNotIn('private-pr-fixture', captured['body'])
        self.assertIn('[REDACTED]', captured['body'])

    def test_pr_failure_retains_redacted_github_error_and_branch(self):
        vuln = {'package': 'example', 'target_version': '2.0', 'verified_gate': 'pytest'}
        def run(command, **kwargs):
            if command[0] == 'gh':
                self.assertIn('--head', command)
                raise subprocess.CalledProcessError(1, command, stderr='permission denied; Authorization: Bearer private-fixture')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(app.subprocess, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(app.create_pull_request(vuln, None))
        self.assertTrue(vuln['branch'].startswith('greenpr/'))
        self.assertIn('permission denied', vuln['publication_error'])
        self.assertNotIn('private-fixture', vuln['publication_error'])
        self.assertNotIn('pull_request_url', vuln)

    def test_pr_success_captures_url_and_explicit_head(self):
        vuln = {'package': 'example', 'target_version': '2.0', 'verified_gate': 'pytest'}
        def run(command, **kwargs):
            if command[0] == 'gh':
                self.assertEqual(command[command.index('--head')+1], vuln['branch'])
            return subprocess.CompletedProcess(command, 0, 'https://github.com/fixture/repo/pull/42' if command[0] == 'gh' else '', '')
        with patch.object(app.subprocess, 'run', side_effect=run):
            self.assertTrue(app.create_pull_request(vuln, None))
        self.assertEqual(vuln['pull_request_url'], 'https://github.com/fixture/repo/pull/42')

    def test_ignored_uncommitted_config_never_executes_setup_or_cleanup(self):
        self.config('setup = ["unsafe-setup"]\ncleanup = ["unsafe-cleanup"]\n')
        git('rm', '--cached', '.greenpr.toml')
        Path('.gitignore').write_text('.greenpr.toml\n')
        git('add', '.gitignore')
        git('commit', '-qm', 'ignore local config')
        with patch('engine.adapters.prepare_baseline') as install, patch.object(app, '_run_with_heartbeat') as runner:
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--skip-pr')
        self.assertEqual(failure.exception.code, 2)
        install.assert_not_called()
        runner.assert_not_called()

    def test_cleanup_failure_overrides_successful_system_exit(self):
        self.config('cleanup = ["failed-cleanup"]\n')
        with patch('engine.adapters.prepare_baseline', return_value=None), patch.object(app, '_run_current_checkout', side_effect=SystemExit(0)), patch.object(app, '_run_with_heartbeat', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--skip-pr')
        self.assertEqual(failure.exception.code, 2)
        receipt = json.loads(next(Path('.git/greenpr-runs').glob('*.json')).read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(len(receipt['config_sha256']), 64)
        self.assertTrue(receipt['original_checkout_clean'])

    def test_hosted_ci_skip_requires_opt_in_and_preserves_merge_protection(self):
        for opt_in in (False, True):
            with self.subTest(skip_hosted_ci=opt_in):
                calls = []
                bodies = []
                def run(command, **kwargs):
                    calls.append(command)
                    if command[0] == 'gh':
                        bodies.append(Path(command[command.index('--body-file')+1]).read_text())
                    return subprocess.CompletedProcess(command, 0, 'https://github.com/fixture/repo/pull/42' if command[0] == 'gh' else '', '')
                vuln = {'package':'example', 'target_version':'2.0', 'verified_gate':'pytest && npm test'}
                with patch.object(app.subprocess, 'run', side_effect=run):
                    self.assertTrue(app.create_pull_request(vuln, None, skip_hosted_ci=opt_in))
                commit = next(command for command in calls if command[:2] == ['git', 'commit'])
                self.assertEqual(commit[-1], 'fix(deps): update example to 2.0' + (' [skip ci]' if opt_in else ''))
                self.assertIn('pytest && npm test', bodies[0])
                self.assertFalse(any('--admin' in command or 'merge' in command for command in calls))
                if opt_in:
                    self.assertIn('all configured verification gates', bodies[0])
                    self.assertIn('checks may remain pending', bodies[0])
                    self.assertIn('does not bypass required checks', bodies[0])

    def test_skip_hosted_ci_does_not_bypass_failing_local_gate(self):
        self.config(gate='mandatory-failing-gate')
        with patch('engine.adapters.prepare_baseline', return_value=None), patch.object(app, 'probe_and_select_verification_gate', return_value=(None, 0)) as gate, patch.object(app, 'create_pull_request') as publish:
            with self.assertRaises(SystemExit) as failure:
                self.invoke('--skip-hosted-ci')
        self.assertEqual(failure.exception.code, 1)
        gate.assert_called_once()
        publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
