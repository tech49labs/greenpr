import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from engine.runtime import git, isolated_checkout, repository_lock
from engine.npm import update, validate_target


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="greenpr-runtime-test-")
        self.previous = Path.cwd()
        os.chdir(self.directory.name)
        git("init", "-q")
        git("config", "user.name", "GreenPR Test")
        git("config", "user.email", "test@example.invalid")
        Path("source.txt").write_text("original")
        git("add", ".")
        git("commit", "-qm", "fixture")
        self.worktrees = []

    def tearDown(self):
        os.chdir(self.directory.name)
        for worktree in self.worktrees:
            self.assertTrue(Path(worktree).parent.name.startswith("greenpr-run-"))
            git("worktree", "remove", "--force", worktree)
        os.chdir(self.previous)
        self.directory.cleanup()

    def test_exclusive_lock_refuses_second_writer(self):
        with repository_lock(Path.cwd()):
            with self.assertRaises(RuntimeError):
                with repository_lock(Path.cwd()):
                    self.fail("Second writer entered")
        self.assertFalse(Path(".git/greenpr.lock").exists())

    def test_failure_leaves_original_head_and_content_unchanged(self):
        base = git("rev-parse", "HEAD")
        with self.assertRaises(RuntimeError):
            with isolated_checkout() as receipt:
                self.worktrees.append(receipt["worktree"])
                Path("source.txt").write_text("changed")
                Path("generated.txt").write_text("generated")
                raise RuntimeError("test failure")
        self.assertEqual(Path("source.txt").read_text(), "original")
        self.assertFalse(Path("generated.txt").exists())
        self.assertEqual(git("rev-parse", "HEAD"), base)
        self.assertEqual(git("status", "--porcelain"), "")
        result = json.loads(next(Path(".git/greenpr-runs").glob("*.json")).read_text())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["original_head_unchanged"])
        self.assertEqual(Path(result["worktree"], "source.txt").read_text(), "changed")

    def test_success_keeps_review_worktree_without_touching_original(self):
        with isolated_checkout() as receipt:
            self.worktrees.append(receipt["worktree"])
            Path("source.txt").write_text("verified")
        self.assertEqual(Path("source.txt").read_text(), "original")
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(len(receipt["patch_sha256"]), 64)

    def test_patch_capture_failure_preserves_original_failure_receipt(self):
        real_run = subprocess.run
        def runner(command, **kwargs):
            if command[:3] == ["git", "diff", "--binary"]:
                raise subprocess.CalledProcessError(1, command, stderr=b"fixture diff failure")
            return real_run(command, **kwargs)
        with patch("engine.runtime.subprocess.run", side_effect=runner):
            with self.assertRaisesRegex(RuntimeError, "original failure"):
                with isolated_checkout() as receipt:
                    self.worktrees.append(receipt["worktree"])
                    raise RuntimeError("original failure")
        result = json.loads(next(Path(".git/greenpr-runs").glob("*.json")).read_text())
        self.assertEqual(result["error_summary"], "original failure")
        self.assertEqual(result["status"], "failed")
        self.assertIn("finalization_error", result)
        self.assertNotIn("patch_sha256", result)

    def test_workspace_updates_all_declaring_manifests(self):
        Path("package.json").write_text(json.dumps({"private": True, "workspaces": ["packages/*"]}))
        for name in ("one", "two"):
            path = Path("packages", name)
            path.mkdir(parents=True)
            (path / "package.json").write_text(json.dumps({"name": name, "dependencies": {"example": "^1.0.0"}}))
        git("add", ".")
        command, cwd = update("example", "2.0.0")
        self.assertEqual(cwd, ".")
        for path in Path("packages").glob("*/package.json"):
            self.assertEqual(json.loads(path.read_text())["dependencies"]["example"], "2.0.0")

    def test_untracked_workspace_manifest_is_refused(self):
        Path("package.json").write_text(json.dumps({"workspaces": ["packages/*"]}))
        git("add", "package.json")
        Path("packages/one").mkdir(parents=True)
        Path("packages/one/package.json").write_text('{"dependencies":{"example":"1.0.0"}}')
        with self.assertRaises(ValueError):
            update("example", "2.0.0")


if __name__ == "__main__":
    unittest.main()
