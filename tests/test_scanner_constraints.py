"""Real pip resolver regressions using local binary wheels, with no installs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from engine import scanner


class ConstraintScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="greenpr-constraint-test-")
        self.previous = Path.cwd()
        self.root = Path(self.temporary.name)
        os.chdir(self.root)
        subprocess.run(["git", "init", "-q"], check=True)
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        self.wheel("greenpr_leaf_fixture", "2.0")
        self.wheel("greenpr_parent_fixture", "2.0", "greenpr-leaf-fixture>=1.0")

    def tearDown(self):
        os.chdir(self.previous)
        self.temporary.cleanup()

    def wheel(self, name, version, dependency=None):
        info = f"{name}-{version}.dist-info"
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        if dependency:
            metadata += "Requires-Dist: " + dependency + "\n"
        with zipfile.ZipFile(self.wheels / f"{name}-{version}-py3-none-any.whl", "w") as archive:
            archive.writestr(info + "/METADATA", metadata + "\n")
            archive.writestr(info + "/WHEEL", "Wheel-Version: 1.0\nGenerator: greenpr-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            archive.writestr(info + "/RECORD", "")

    def project(self, constraints="greenpr-parent-fixture==2.0\ngreenpr-leaf-fixture==2.0\n"):
        (self.root / "requirements.txt").write_text("-c requirements.lock.txt\ngreenpr-parent-fixture>=1.0\n")
        (self.root / "requirements.lock.txt").write_text(constraints)
        subprocess.run(["git", "add", "requirements.txt", "requirements.lock.txt"], check=True)

    def local_resolver(self):
        actual_run = subprocess.run
        def run(command, **kwargs):
            if "--dry-run" in command:
                self.assertIn("--ignore-installed", command)
                self.assertIn("--only-binary=:all:", command)
                command = [*command, "--no-index", "--find-links", str(self.wheels)]
            return actual_run(command, **kwargs)
        return patch.object(scanner.subprocess, "run", side_effect=run)

    def test_real_pip_proves_lower_bound_and_transitive_pins_without_install(self):
        self.project()
        manifest, _, pins = scanner.constrained_projects(self.root)[0]
        with self.local_resolver():
            resolved, environment = scanner._resolved_pins(manifest, pins, self.root)
        self.assertEqual(resolved, {"greenpr-parent-fixture": "2.0", "greenpr-leaf-fixture": "2.0"})
        self.assertIn("python_version", environment)
        report = json.loads((self.root / "pip-report.json").read_text())
        self.assertEqual(len(report["install"]), 2)
        import importlib.metadata
        with self.assertRaises(importlib.metadata.PackageNotFoundError):
            importlib.metadata.version("greenpr-parent-fixture")

    def test_unpinned_transitive_dependency_fails_closed_after_real_resolution(self):
        self.project("greenpr-parent-fixture==2.0\n")
        manifest, _, pins = scanner.constrained_projects(self.root)[0]
        with self.local_resolver(), self.assertRaisesRegex(RuntimeError, "complete resolved dependency graph"):
            scanner._resolved_pins(manifest, pins, self.root)

    def test_conflicting_constraints_fail_before_resolution(self):
        self.project("greenpr-parent-fixture==2.0\ngreenpr-parent-fixture==1.0\n")
        with self.assertRaisesRegex(RuntimeError, "Conflicting"):
            scanner.constrained_projects(self.root)

    def test_external_constraint_and_url_requirement_are_refused(self):
        self.project()
        (self.root / "requirements.txt").write_text("-c ../outside.txt\ngreenpr-parent-fixture>=1.0\n")
        with self.assertRaises(RuntimeError):
            scanner.constrained_projects(self.root)
        (self.root / "requirements.txt").write_text("-c requirements.lock.txt\ngreenpr-parent-fixture @ https://example.invalid/package.whl\n")
        with self.assertRaises(RuntimeError):
            scanner.constrained_projects(self.root)

    def test_replace_only_proven_python_sources_preserving_other_transitive_findings(self):
        self.project()
        other = {"source": {"path": str(self.root / "nested/package-lock.json")},
                 "packages": [{"package": {"name": "transitive-npm", "version": "1.0", "ecosystem": "npm"},
                               "vulnerabilities": [{"id": "REAL-OTHER-FINDING"}]}]}
        commands = []
        def osv(command):
            commands.append(command)
            if "--no-resolve" not in command:
                return {"results": [other, {"source": {"path": str(self.root / "requirements.txt")},
                    "packages": [{"package": {"name": "greenpr-parent-fixture", "version": "1.0", "ecosystem": "PyPI"},
                                  "vulnerabilities": [{"id": "FICTITIOUS-LOWER-BOUND"}]}]}]}
            exact = Path(command[-1].removeprefix("requirements.txt:"))
            packages = [{"package": {"name": name, "version": version, "ecosystem": "PyPI"}}
                        for name, version in (line.split("==") for line in exact.read_text().splitlines())]
            return {"results": [{"source": {"path": str(exact)}, "packages": packages}]}
        with self.local_resolver(), patch.object(scanner, "_osv", side_effect=osv):
            result = scanner.scan_source()
        self.assertEqual(result["results"][0], other)
        proven = result["results"][1]
        self.assertEqual(proven["source"]["greenpr_resolution"], "pip-dry-run-complete-constraints")
        self.assertEqual(len(proven["packages"]), 2)
        self.assertNotIn("FICTITIOUS", json.dumps(result))
        self.assertNotIn("--no-resolve", commands[0])
        self.assertIn("--no-resolve", commands[1])


if __name__ == "__main__":
    unittest.main()
