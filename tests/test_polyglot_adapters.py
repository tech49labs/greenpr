import json
import os
from pathlib import Path
import tempfile
import unittest
from engine.adapters import update
from engine.runtime import git


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greenpr-adapter-test-")
        self.previous = Path.cwd()
        os.chdir(self.temp.name)
        git("init", "-q")

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def write(self, name, text):
        Path(name).write_text(text)
        git("add", name)

    def test_python_preserves_extras_marker_and_comment(self):
        self.write("requirements.txt", 'requests[socks]==2.31.0; python_version >= "3.11" # required proxy support\n')
        update({"package": "requests", "target_version": "2.32.4", "ecosystem": "pypi"})
        self.assertEqual(Path("requirements.txt").read_text(), 'requests[socks]==2.32.4; python_version >= "3.11" # required proxy support\n')

    def test_python_preserves_whitespace_before_comment(self):
        self.write("requirements.txt", "requests[socks]==2.31.0 # keep extras\n")
        update({"package": "requests", "target_version": "2.32.4", "ecosystem": "pypi"})
        result = Path("requirements.txt").read_text()
        self.assertEqual(result, "requests[socks]==2.32.4 # keep extras\n")
        from packaging.requirements import Requirement
        self.assertEqual(Requirement(result.split(" #", 1)[0]).extras, {"socks"})

    def test_nested_python_update_requires_project_selection_before_mutation(self):
        Path("service").mkdir()
        self.write("service/requirements.txt", "colorama==0.4.5\n")
        original = Path("service/requirements.txt").read_bytes()
        with self.assertRaises(ValueError):
            update({"package": "colorama", "target_version": "0.4.6", "ecosystem": "pypi", "working_dir": "service"})
        self.assertEqual(Path("service/requirements.txt").read_bytes(), original)

    def test_python_duplicate_declarations_refused(self):
        self.write("requirements.txt", "requests==2.31.0\nrequests==2.30.0\n")
        with self.assertRaises(ValueError):
            update({"package": "requests", "target_version": "2.32.4", "ecosystem": "pypi"})

    def test_go_osv_version_is_normalized_to_native_module_version(self):
        self.write("go.mod", "module example.invalid/test\nrequire github.com/google/uuid v1.3.0\n")
        vuln = {"package": "github.com/google/uuid", "target_version": "1.6.0", "ecosystem": "go"}
        command, _ = update(vuln)
        self.assertEqual(vuln["target_version"], "v1.6.0")
        self.assertEqual(command, "go get github.com/google/uuid@v1.6.0 && go mod tidy")

    def test_pep621_conditional_extras_refused_before_mutation(self):
        source = '[project]\nname="fixture"\nversion="1.0"\ndependencies=["requests[socks]==2.31.0; python_version >= \'3.11\'"]\n'
        self.write("pyproject.toml", source)
        with self.assertRaises(ValueError):
            update({"package": "requests", "target_version": "2.32.4", "ecosystem": "pypi"})
        self.assertEqual(Path("pyproject.toml").read_text(), source)

    def test_cargo_keeps_dependency_section_and_features(self):
        self.write("Cargo.toml", '[package]\nname="fixture"\nversion="1.0.0"\n[dev-dependencies]\nserde={version="1.0.0",features=["derive"]}\n')
        command, _ = update({"package": "serde", "target_version": "1.0.200", "ecosystem": "crates.io"})
        content = Path("Cargo.toml").read_text()
        self.assertIn('[dev-dependencies]', content)
        self.assertIn('version="=1.0.200",features=["derive"]', content)
        self.assertIn("cargo update -p serde --precise 1.0.200", command)

    def test_maven_updates_property_without_other_dependency(self):
        self.write("pom.xml", '<project><properties><library.version>1.0</library.version></properties><dependencies><dependency><groupId>group</groupId><artifactId>library</artifactId><version>${library.version}</version></dependency><dependency><groupId>group</groupId><artifactId>other</artifactId><version>1.0</version></dependency></dependencies></project>')
        update({"package": "group:library", "target_version": "2.0.0", "ecosystem": "maven"})
        content = Path("pom.xml").read_text()
        self.assertIn('<library.version>2.0.0</library.version>', content)
        self.assertIn('<artifactId>other</artifactId><version>1.0</version>', content)

    def test_gradle_replaces_literal_and_enables_locking(self):
        self.write("build.gradle", "dependencies { implementation 'group:library:1.0.0' }\n")
        command, _ = update({"package": "group:library", "target_version": "2.0.0", "ecosystem": "maven"})
        self.assertIn("group:library:2.0.0", Path("build.gradle").read_text())
        self.assertIn("lockAllConfigurations", Path("build.gradle").read_text())
        self.assertIn("--write-locks", command)

    def test_shell_injection_rejected_for_all_native_commands(self):
        for ecosystem in ("pypi", "go", "crates.io", "maven", "nuget"):
            with self.subTest(ecosystem=ecosystem), self.assertRaises(ValueError):
                update({"package": "example;evil", "target_version": "2.0.0", "ecosystem": ecosystem})


if __name__ == "__main__":
    unittest.main()
