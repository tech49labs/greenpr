import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from engine.license import validate_offline_license


class OfflineLicenseTests(unittest.TestCase):
    def test_valid_tampered_expired_and_wrong_repository(self):
        private = Ed25519PrivateKey.generate()
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder, "public.pem")
            license_path = Path(folder, "license.json")
            public.write_bytes(private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
            payload = {"issuer": "GreenPR", "version": 1, "plan": "team", "organization_id": "test-org",
                       "repositories": ["test/repo"], "issued_at": "2026-01-01T00:00:00Z", "expires_at": "2027-01-01T00:00:00Z"}
            signature = base64.b64encode(private.sign(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())).decode()
            envelope = {"payload": payload, "signature": signature}
            license_path.write_text(json.dumps(envelope))
            with patch("engine.license.repository_identity", return_value="test/repo"):
                result = validate_offline_license(license_path, public, datetime(2026, 6, 1, tzinfo=timezone.utc))
                self.assertEqual(result["plan"], "team")
                with self.assertRaises(ValueError):
                    validate_offline_license(license_path, public, datetime(2028, 1, 1, tzinfo=timezone.utc))
            with patch("engine.license.repository_identity", return_value="other/repo"):
                with self.assertRaises(ValueError):
                    validate_offline_license(license_path, public, datetime(2026, 6, 1, tzinfo=timezone.utc))
            envelope["payload"]["plan"] = "enterprise"
            license_path.write_text(json.dumps(envelope))
            with self.assertRaises(ValueError):
                validate_offline_license(license_path, public, datetime(2026, 6, 1, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
