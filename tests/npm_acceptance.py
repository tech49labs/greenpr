"""Opt-in real npm + OSV acceptance in disposable repositories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ENGINE = str(Path(__file__).resolve().parents[1] / "remediate.py")
NPM = "npm.cmd" if os.name == "nt" else "npm"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Fixture:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greenpr-acceptance-")
        self.root = Path(self.temp.name)
        self.worktrees = []
        self.run(["git", "init", "-q"])
        self.run(["git", "config", "user.email", "test@example.invalid"])
        self.run(["git", "config", "user.name", "GreenPR Test"])
        (self.root / ".gitignore").write_text("node_modules/\n")
        return self

    def __exit__(self, *args):
        for worktree in self.worktrees:
            assert Path(worktree).parent.name.startswith("greenpr-run-")
            self.run(["git", "worktree", "remove", "--force", worktree])
        self.temp.cleanup()

    def run(self, args, expected=0, cwd=None):
        result = subprocess.run(args, cwd=cwd or self.root, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=1800 if ENGINE in args else 300)
        if result.returncode != expected:
            raise AssertionError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def commit(self):
        self.run(["git", "add", "."])
        self.run(["git", "commit", "-qm", "acceptance fixture"])

    def remediate(self, *args, expected=0):
        original = self.run(["git", "rev-parse", "HEAD"])
        output = self.run([sys.executable, ENGINE, *args, "--skip-pr"], expected=expected)
        print(output)
        receipt_path = next(line.split("=", 1)[1] for line in output.splitlines() if line.startswith("GREENPR_RESULT="))
        receipt = json.loads(Path(receipt_path).read_text())
        self.worktrees.append(receipt["worktree"])
        assert receipt["original_head_unchanged"]
        assert original == self.run(["git", "rev-parse", "HEAD"])
        assert not self.run(["git", "status", "--porcelain"])
        return Path(receipt["worktree"]), receipt


def package_fixture(fixture, package="is-number", version="6.0.0"):
    (fixture.root / "package.json").write_text(json.dumps({"name": "greenpr-acceptance", "private": True,
        "scripts": {"test": "node verify.cjs"}}))
    (fixture.root / "verify.cjs").write_text(
        f"const assert=require('node:assert/strict'); const pkg='{package}';"
        "assert.equal(require(pkg+'/package.json').version,require('./package.json').dependencies[pkg]);"
        + ("assert.equal(require(pkg)('42'),true); assert.equal(require(pkg)('x'),false);" if package == "is-number" else
           "assert.equal(require(pkg)(['--count','3']).count,3);"))
    fixture.run([NPM, "install", "--ignore-scripts", "--no-audit", "--no-fund", "--save-exact", f"{package}@{version}"])
    fixture.commit()


def main():
    with Fixture() as f:
        package_fixture(f)
        review, receipt = f.remediate("--package", "is-number", "--target-version", "7.0.0")
        assert receipt["status"] == "verified"
        assert json.loads((review / "node_modules/is-number/package.json").read_text())["version"] == "7.0.0"
        assert json.loads((f.root / "node_modules/is-number/package.json").read_text())["version"] == "6.0.0"
        assert set(f.run(["git", "diff", "--name-only"], cwd=review).splitlines()) == {"package.json", "package-lock.json"}
        print("PASS: direct update validated in isolated worktree; original remains at 6.0.0")
    with Fixture() as f:
        package_fixture(f, "minimist", "1.2.5")
        review, receipt = f.remediate("--ecosystem", "npm")
        assert receipt["status"] == "verified"
        assert json.loads((review / "node_modules/minimist/package.json").read_text())["version"] != "1.2.5"
        scan = json.loads(f.run(["osv-scanner", "scan", "source", "--format=json", "-r", "."], cwd=review))
        assert not [p for r in scan["results"] for p in r.get("packages", []) if p.get("vulnerabilities")]
        print("PASS: advisory-triggered upgrade and post-update rescan")
    with Fixture() as f:
        (f.root / "package.json").write_text(json.dumps({"name": "workspace-fixture", "private": True,
            "workspaces": ["packages/*"], "scripts": {"test": "node -e \"console.log('root checks pass')\""}}))
        for name in ("one", "two"):
            directory = f.root / "packages" / name
            directory.mkdir(parents=True)
            (directory / "package.json").write_text(json.dumps({"name": name, "version": "1.0.0", "private": True,
                "dependencies": {"is-number": "6.0.0"}, "scripts": {"test": "node verify.cjs"}}))
            (directory / "verify.cjs").write_text("const a=require('node:assert/strict');a.equal(require('is-number/package.json').version,require('./package.json').dependencies['is-number']);a.equal(require('is-number')('4'),true);")
        f.run([NPM, "install", "--ignore-scripts", "--no-audit", "--no-fund"])
        f.commit()
        review, receipt = f.remediate("--package", "is-number", "--target-version", "7.0.0")
        assert receipt["status"] == "verified"
        for name in ("one", "two"):
            assert json.loads((review / "packages" / name / "package.json").read_text())["dependencies"]["is-number"] == "7.0.0"
        print("PASS: both npm workspace declarations updated; root and workspace gates passed")
    with Fixture() as f:
        package_fixture(f)
        data = json.loads((f.root / "package.json").read_text())
        data["scripts"]["typecheck"] = "node reject.cjs"
        (f.root / "package.json").write_text(json.dumps(data))
        (f.root / "reject.cjs").write_text("if(require('is-number/package.json').version==='7.0.0')process.exit(1)")
        f.commit()
        review, receipt = f.remediate("--package", "is-number", "--target-version", "7.0.0", expected=1)
        assert receipt["status"] == "failed"
        assert json.loads((f.root / "node_modules/is-number/package.json").read_text())["version"] == "6.0.0"
        print("PASS: failed typecheck cannot be replaced by passing tests; original checkout preserved")


if __name__ == "__main__":
    main()
