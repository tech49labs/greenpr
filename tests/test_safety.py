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


class RepositoryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greenpr-test-")
        self.previous = os.getcwd()
        os.chdir(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "GreenPR Test")
        Path("package.json").write_text(json.dumps({"scripts": {"test": "exit 1", "build": "exit 0"}, "dependencies": {"example": "1.0.0"}}))
        Path("source.py").write_text("value = 1\n")
        Path("test_source.py").write_text("assert True\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True)

    def test_failed_custom_gate_does_not_fall_back(self):
        gate, _ = app.probe_and_select_verification_gate(custom_cmd=f'"{sys.executable}" -c "raise SystemExit(1)"')
        self.assertIsNone(gate)

    def test_passing_custom_gate_is_retained(self):
        command = f'"{sys.executable}" -c "pass"'
        self.assertEqual(app.probe_and_select_verification_gate(custom_cmd=command)[0], command)

    def test_source_repair_cannot_touch_tests_or_manifest(self):
        self.assertTrue(app.safe_repair_path("source.py"))
        self.assertFalse(app.safe_repair_path("test_source.py"))
        self.assertFalse(app.safe_repair_path("package.json"))

    def test_source_repair_rejects_untracked_file(self):
        Path("untracked.py").write_text("secret = 1")
        self.assertFalse(app.safe_repair_path("untracked.py"))

    def test_source_repair_rejects_outside_repository(self):
        with tempfile.NamedTemporaryFile(suffix=".py") as outside:
            self.assertFalse(app.safe_repair_path(outside.name))

    def test_scanner_failure_is_not_clean(self):
        for code, output in [(127, b""), (0, b""), (0, b"{}"), (0, b"not-json")]:
            with self.subTest(code=code, output=output), patch.object(app.subprocess, "run", return_value=subprocess.CompletedProcess([], code, output, b"error")):
                with self.assertRaises(RuntimeError):
                    app.run_vulnerability_radar()

    def test_valid_empty_scan(self):
        with patch.object(app.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b'{"results": []}', b"")):
            self.assertEqual(app.run_vulnerability_radar(), [])

    def test_target_must_fix_all_advisories(self):
        def advisory(fix):
            return {"affected": [{"package": {"name": "example"}, "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": fix}]}]}]}
        self.assertEqual(app.select_target_version("example", "1.0.0", [advisory("1.2.0"), advisory("1.3.0")]), "1.3.0")
        self.assertIsNone(app.select_target_version("example", "2.0.0", [advisory("1.2.0")]))
        self.assertIsNone(app.select_target_version("example", "1.0.0", [advisory("2.0.0rc1")]))

    def test_unfixed_advisory_blocks_target(self):
        advisories = [{"affected": [{"package": {"name": "example"}, "ranges": [
            {"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.2.0"}]},
            {"type": "SEMVER", "events": [{"introduced": "1.1.0"}]}
        ]}]}]
        self.assertIsNone(app.select_target_version("example", "1.0.0", advisories))

    def test_unvalidated_adapter_refused(self):
        with self.assertRaises(ValueError):
            app.resolve_package_bump_command({"package": "example", "target_version": "2.0.0", "ecosystem": "pypi"}, {})

    def test_transitive_override_refused(self):
        with self.assertRaises(ValueError):
            app.resolve_package_bump_command({"package": "example", "target_version": "2.0.0", "ecosystem": "npm", "is_direct": False}, {})

    def test_package_shell_injection_rejected_before_mutation(self):
        before = Path("package.json").read_bytes()
        for package, version in [("example;echo unsafe", "2.0.0"), ("example", "2.0.0 & echo unsafe")]:
            with self.assertRaises(ValueError):
                app.resolve_package_bump_command({"package": package, "target_version": version}, {})
        self.assertEqual(Path("package.json").read_bytes(), before)

    def test_install_updates_runtime_dependencies(self):
        command, _ = app.resolve_package_bump_command({"package": "example", "target_version": "2.0.0", "ecosystem": "npm"}, {})
        self.assertEqual(command, "npm install --ignore-scripts --no-audit --no-fund")
        self.assertEqual(json.loads(Path("package.json").read_text())["dependencies"]["example"], "2.0.0")

    def test_failed_verification_restores_tracked_but_preserves_untracked(self):
        original = Path("package.json").read_bytes()
        Path("keep.txt").write_text("keep me")
        vuln = {"package": "example", "target_version": "2.0.0", "ecosystem": "npm"}
        plan = app.MigrationPlan(package_name="example", target_version="2.0.0", general_summary="test")
        actual_run = subprocess.run
        def runner(command, **kwargs):
            if command == "npm install":
                return subprocess.CompletedProcess(command, 0, b"", b"")
            return actual_run(command, **kwargs)
        with patch.object(app.subprocess, "run", side_effect=runner), patch.object(app, "_run_with_heartbeat", side_effect=[subprocess.CompletedProcess([], 0, b"", b""), subprocess.CompletedProcess([], 124, b"", b"timeout")]):
            self.assertFalse(app.execute_remediation({}, vuln, plan, "test"))
        self.assertEqual(Path("package.json").read_bytes(), original)
        self.assertEqual(Path("keep.txt").read_text(), "keep me")

    def test_failed_install_restores_manifest(self):
        before = Path("package.json").read_bytes()
        vuln = {"package": "example", "target_version": "2.0.0", "ecosystem": "npm"}
        with patch.object(app, "_run_with_heartbeat", return_value=subprocess.CompletedProcess([], 1, b"", b"install failed")) as run:
            self.assertFalse(app.execute_remediation({}, vuln, None, "test"))
            self.assertEqual(run.call_count, 1)
        self.assertEqual(Path("package.json").read_bytes(), before)

    def test_multiple_dependency_sections_refused_without_mutation(self):
        data = json.loads(Path("package.json").read_text())
        data["devDependencies"] = {"example": "1.0.0"}
        Path("package.json").write_text(json.dumps(data))
        before = Path("package.json").read_bytes()
        with self.assertRaises(ValueError):
            app.resolve_package_bump_command({"package": "example", "target_version": "2.0.0", "ecosystem": "npm"}, {})
        self.assertEqual(Path("package.json").read_bytes(), before)

    def test_failed_git_step_stops_delivery(self):
        vuln = {"package": "example", "target_version": "2.0.0"}
        with patch.object(app.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "git")) as run:
            self.assertFalse(app.create_pull_request(vuln, None))
        self.assertEqual(run.call_count, 1)

    def test_skip_pr_does_not_call_git(self):
        with patch.object(app.subprocess, "run") as run:
            self.assertTrue(app.create_pull_request({}, None, skip_pr=True))
            run.assert_not_called()

    def test_model_repair_disabled_by_default(self):
        with patch.dict(os.environ, {"GREENPR_ENABLE_MODEL_REPAIR": "0", "GEMINI_API_KEY": "not-a-real-key"}):
            self.assertIsNone(app.resolve_engine_tiers()["tier1"])
            self.assertEqual(app.extract_migration_plan("example", "1", "2", "").breaking_changes, [])

    def test_dirty_repository_refused_before_baseline(self):
        Path("source.py").write_text("user work\n")
        with patch.object(sys, "argv", ["remediate.py", "--skip-pr"]), patch.object(app, "probe_and_select_verification_gate") as gate, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                app.main()
            self.assertEqual(error.exception.code, 2)
            gate.assert_not_called()
        self.assertEqual(Path("source.py").read_text(), "user work\n")

    def test_scan_only_never_runs_baseline_or_model(self):
        with patch.object(sys, "argv", ["remediate.py", "--scan-only"]), patch.object(app, "run_vulnerability_radar", return_value=[]), patch.object(app, "probe_and_select_verification_gate") as gate:
            with self.assertRaises(SystemExit) as error:
                app.main()
            self.assertEqual(error.exception.code, 0)
            gate.assert_not_called()

    def test_scan_only_with_repair_flag_still_never_validates_or_calls_provider(self):
        with patch.object(sys, 'argv', ['remediate.py', '--scan-only', '--enable-model-repair']), patch.object(app, 'run_vulnerability_radar', return_value=[]), patch.object(app, 'resolve_engine_tiers') as routing:
            with self.assertRaises(SystemExit) as error:
                app.main()
            self.assertEqual(error.exception.code, 0)
            routing.assert_not_called()

    def test_git_crlf_conversion_preserves_reviewed_onboarding(self):
        Path('.gitattributes').write_bytes(b'.greenpr.toml text eol=crlf\n')
        Path('.greenpr.toml').write_bytes(b'version=1\nproject="."\ngates=["required-check"]\n')
        self.git('add', '.gitattributes', '.greenpr.toml')
        self.git('commit', '-qm', 'reviewed onboarding')
        self.assertEqual(self.git('status', '--porcelain').stdout, '')
        def check(config):
            self.assertEqual(config.gates, ('required-check',))
            self.assertIn(b'\r\n', Path('.greenpr.toml').read_bytes())
            return {}
        with patch.object(sys, 'argv', ['remediate.py', '--skip-pr']), patch('engine.adapters.prepare_baseline', return_value=None), patch.object(app, '_run_current_checkout', side_effect=check) as runner:
            app.main()
            runner.assert_called_once()
        self.assertEqual(self.git('status', '--porcelain').stdout, '')

    def test_config_content_change_during_candidate_creation_is_rejected(self):
        from engine.onboarding import load_config
        Path('.greenpr.toml').write_bytes(b'version=1\nproject="."\ngates=["required-check"]\n')
        self.git('add', '.greenpr.toml')
        self.git('commit', '-qm', 'reviewed onboarding')
        original = Path.cwd()
        def read_and_change(root):
            config = load_config(root)
            if Path(root) != original:
                with (original / '.greenpr.toml').open('ab') as file:
                    file.write(b'# concurrent edit\n')
            return config
        with patch.object(sys, 'argv', ['remediate.py', '--skip-pr']), patch('engine.onboarding.load_config', side_effect=read_and_change), patch('engine.adapters.prepare_baseline') as install, patch.object(app, '_run_current_checkout') as runner, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                app.main()
            self.assertEqual(error.exception.code, 2)
            install.assert_not_called()
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
