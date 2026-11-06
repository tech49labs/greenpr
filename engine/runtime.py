"""Isolated execution with a repository-wide exclusive writer lock."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="strict").stdout.strip()


@contextmanager
def repository_lock(root):
    common = Path(git("rev-parse", "--git-common-dir", cwd=root))
    if not common.is_absolute():
        common = (root / common).resolve()
    lock = common / "greenpr.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Another GreenPR run owns this repository, or a previous run stopped unexpectedly. Inspect greenpr.lock; never remove it while its process is active.") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}, file)
        yield common
    finally:
        lock.unlink()


@contextmanager
def isolated_checkout():
    original = Path.cwd().resolve()
    if Path(git("rev-parse", "--show-toplevel")).resolve() != original:
        raise RuntimeError("Run GreenPR from the repository root")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Run from a clean repository; commit or move existing changes first")
    with repository_lock(original) as common:
        head = git("rev-parse", "HEAD")
        run_id = uuid.uuid4().hex
        directory = Path(tempfile.mkdtemp(prefix="greenpr-run-"))
        checkout = directory / "checkout"
        git("worktree", "add", "--detach", str(checkout), head)
        receipt = {"run_id": run_id, "base_sha": head, "worktree": str(checkout),
                   "original_repository": str(original), "status": "running"}
        try:
            os.chdir(checkout)
            yield receipt
            receipt["status"] = "verified"
        except BaseException as exc:
            receipt["status"] = "verified" if isinstance(exc, SystemExit) and exc.code in (None, 0) else "failed"
            receipt["error_type"] = type(exc).__name__
            raise
        finally:
            os.chdir(original)
            receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
            receipt["original_head_unchanged"] = git("rev-parse", "HEAD") == head
            patch = subprocess.run(["git", "diff", "--binary", head], cwd=checkout,
                                   check=True, capture_output=True).stdout
            (directory / "changes.patch").write_bytes(patch)
            receipt["patch_sha256"] = hashlib.sha256(patch).hexdigest()
            receipts = common / "greenpr-runs"
            receipts.mkdir(exist_ok=True)
            receipt_path = receipts / f"{run_id}.json"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            (directory / "result.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            print(f"GREENPR_RESULT={receipt_path}")
            print(f"Review worktree retained: {checkout}")
            print("Original checkout was not used for install, tests, or remediation.")
