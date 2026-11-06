import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from engine.diagnostics import classify_failure, diagnostic_session, record_command, redact


class DiagnosticTests(unittest.TestCase):
    def test_missing_configuration_is_not_an_assertion_failure(self):
        kind, summary = classify_failure('', 'decouple.UndefinedValueError: SECRET_KEY not found. Declare it as envvar or define a default value.', 1, 'baseline')
        self.assertEqual(kind, 'environment_configuration')
        self.assertIn('test-only', summary)
        self.assertEqual(classify_failure('FAILED test_math.py::test_sum - AssertionError', '', 1, 'baseline')[0], 'test_failure')
        self.assertEqual(classify_failure('', 'exit only', 1)[0], 'command_failure')

    def test_secrets_headers_query_credentials_and_private_keys_redacted(self):
        original = ('known=abc!verysecret https://example.test/?access_token=unknown&ok=yes\n'
                    'Authorization: Bearer bearer-secret\nCookie: session=secret-cookie\n'
                    'https://user:pass@host/path --api-key command-secret\n'
                    '{"SECRET_KEY": "json-secret"}\n'
                    '-----BEGIN PRIVATE KEY-----\nprivate-content\n-----END PRIVATE KEY-----')
        safe = redact(original, {'APP_SECRET': 'abc!verysecret'})
        for secret in ('abc!verysecret', 'unknown', 'bearer-secret', 'secret-cookie', 'user:pass', 'command-secret', 'json-secret', 'private-content'):
            self.assertNotIn(secret, safe)
        self.assertIn('ok=yes', safe)

    def test_retains_redacted_outputs_exit_timing_and_command_per_run(self):
        receipt = {}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SECRET_KEY': 'fixture-private-value'}):
            with diagnostic_session(receipt, directory):
                result = record_command(['pytest', '--token', 'cli-token'], subprocess.CompletedProcess([], 1, 'assert 1 == 2', 'SECRET_KEY=fixture-private-value'), phase='baseline', duration_seconds=1.23456)
            self.assertEqual(result['classification'], 'test_failure')
            self.assertEqual(result['elapsed_seconds'], 1.235)
            self.assertEqual(result['exit_code'], 1)
            raw = Path(result['log_path']).read_text()
            self.assertNotIn('fixture-private-value', raw)
            self.assertNotIn('cli-token', raw)
            self.assertEqual(json.loads(raw)['stdout'], 'assert 1 == 2')
            self.assertNotIn('stdout', receipt['commands'][0])
            self.assertEqual(receipt['last_failure']['log_path'], result['log_path'])
        standalone = record_command('true', subprocess.CompletedProcess([], 0, '', ''), phase='final', duration_seconds=0)
        self.assertNotIn('log_path', standalone)

    def test_timeout_retains_partial_bytes_and_setup_distinction(self):
        result = record_command('pytest', subprocess.TimeoutExpired('pytest', 5, output=b'partial output', stderr=b'Authorization: secret'), phase='baseline', duration_seconds=5)
        self.assertTrue(result['timed_out'])
        self.assertIsNone(result['exit_code'])
        self.assertEqual(result['stdout'], 'partial output')
        self.assertEqual(result['classification'], 'timeout')
        self.assertNotIn('secret', result['stderr'])
        self.assertEqual(classify_failure('', "ModuleNotFoundError: No module named 'django'", 1)[0], 'environment_dependencies')

    def test_missing_executable_and_encoded_environment_values(self):
        result = record_command('missing', FileNotFoundError('No such file or directory'), phase='bootstrap', duration_seconds=0.1)
        self.assertEqual(result['classification'], 'environment_dependencies')
        self.assertNotIn('a%2Fb%2Bc', redact('a%2Fb%2Bc', {'ACCESS_TOKEN': 'a/b+c'}))

    def test_real_gate_configuration_failure_is_logged_without_secret(self):
        import remediate
        import sys
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SECRET_KEY': 'real-fixture-secret'}):
            script = Path(directory) / 'fail.py'
            script.write_text("import os,sys\nprint(os.environ['SECRET_KEY'])\nprint('decouple.UndefinedValueError: SECRET_KEY not found',file=sys.stderr)\nraise SystemExit(1)\n")
            receipt = {}
            with diagnostic_session(receipt, Path(directory) / 'logs'):
                gate, _ = remediate.probe_and_select_verification_gate(directory, custom_cmd=f'"{sys.executable}" "{script}"', timeout=10)
            self.assertIsNone(gate)
            entry = receipt['commands'][0]
            self.assertEqual(entry['classification'], 'environment_configuration')
            self.assertEqual(entry['phase'], 'baseline')
            self.assertNotIn('real-fixture-secret', Path(entry['log_path']).read_text())

    def test_real_timeout_keeps_partial_output(self):
        import remediate
        import sys
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'wait.py'
            script.write_text("import time\nprint('output before timeout',flush=True)\ntime.sleep(30)\n")
            receipt = {}
            with diagnostic_session(receipt, Path(directory) / 'logs'):
                result = remediate._run_with_heartbeat(f'"{sys.executable}" "{script}"', 'Baseline verification', timeout=1, phase='baseline')
            self.assertEqual(result.returncode, 124)
            self.assertIn(b'output before timeout', result.stdout)
            self.assertTrue(receipt['commands'][0]['timed_out'])
            self.assertIn('output before timeout', Path(receipt['commands'][0]['log_path']).read_text())


if __name__ == '__main__':
    unittest.main()
