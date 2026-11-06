"""Real issuance CLI roundtrips using only disposable fixture keys and grants."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from engine.license import validate_offline_license


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class IssuerAcceptance(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="greenpr-license-issue-test-")
        self.root = Path(self.workspace.name)
        self.source = self.root / "tool"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "engine").mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/issue_license.py", self.source / "scripts/issue_license.py")
        key = Ed25519PrivateKey.generate()
        self.key_path = self.root / "fixture-key.pem"
        self.key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.public_key = self.source / "engine/license_public_key.pem"
        self.public_key.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.output = self.root / "grant.json"
        self.audit = self.root / "grant.json.audit.json"
        self.customer = self.root / "customer"
        self.customer.mkdir()
        self.git("init", "-q")
        self.git("remote", "add", "origin", "https://github.com/example/customer.git")
        self.expiry = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    def tearDown(self):
        self.workspace.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.customer, capture_output=True, check=True)

    def issue(self, *extra, plan="team", repos=("example/customer",), expiry=None, output=None, key=None):
        args = [sys.executable, str(self.source / "scripts/issue_license.py"), "--plan", plan,
                "--organization-id", "fixture-org", "--payment-reference", "fixture-payment-never-charged",
                "--expires-at", expiry or self.expiry, "--output", str(output or self.output),
                "--signing-key", str(key or self.key_path)]
        for repository in repos:
            args.extend(["--repository", repository])
        return subprocess.run(args + list(extra), capture_output=True, text=True, encoding="utf-8", timeout=30)

    def verify(self):
        with working_directory(self.customer):
            return validate_offline_license(self.output, self.public_key)

    def test_cli_issues_verifiable_team_and_separate_audit(self):
        result = self.issue()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verify()["repository"], "example/customer")
        self.assertEqual(self.verify()["plan"], "team")
        self.assertNotIn("fixture-payment-never-charged", self.output.read_text())
        self.assertEqual(json.loads(self.audit.read_text())["payment_reference"], "fixture-payment-never-charged")
        self.assertEqual(list(self.root.glob(".greenpr-issue-*")), [])

    def test_wrong_repository_is_rejected(self):
        self.assertEqual(self.issue().returncode, 0)
        self.git("remote", "set-url", "origin", "https://github.com/example/another.git")
        with self.assertRaises(ValueError):
            self.verify()

    def test_existing_audit_cannot_leave_or_replace_license(self):
        self.audit.write_text("existing-audit")
        result = self.issue()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.audit.read_text(), "existing-audit")

    def test_existing_license_cannot_be_overwritten_or_create_audit(self):
        self.output.write_text("existing-license")
        result = self.issue()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output.read_text(), "existing-license")
        self.assertFalse(self.audit.exists())

    def test_wrong_signing_key_creates_nothing(self):
        wrong = self.root / "wrong-key.pem"
        wrong.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        result = self.issue(key=wrong)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.audit.exists())

    def test_expired_and_timezone_free_expiry_are_refused(self):
        for value in ("2000-01-01T00:00:00Z", "2099-01-01T00:00:00", "not-a-date"):
            with self.subTest(value=value):
                self.assertNotEqual(self.issue(expiry=value).returncode, 0)
                self.assertFalse(self.output.exists())

    def test_invalid_plan_scope_refused(self):
        cases = [dict(repos=("example/customer", "example/second")),
                 dict(plan="enterprise", repos=("example/customer", "other/second"))]
        for options in cases:
            with self.subTest(options=options):
                self.assertNotEqual(self.issue(**options).returncode, 0)
                self.assertFalse(self.output.exists())

    def test_enterprise_covers_one_organization_only(self):
        result = self.issue("--github-organization", "example", plan="enterprise", repos=())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verify()["plan"], "enterprise")
        self.git("remote", "set-url", "origin", "git@github.com:other/customer.git")
        with self.assertRaises(ValueError):
            self.verify()

    def test_output_inside_source_repository_refused(self):
        result = self.issue(output=self.source / "license.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.source / "license.json").exists())


if __name__ == "__main__":
    unittest.main()
