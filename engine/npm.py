"""npm root/workspace manifest selection and installed/locked identity checks."""
import json
from pathlib import Path
import re
import subprocess

SECTIONS = ("dependencies", "devDependencies", "optionalDependencies")


def manifests():
    root = Path.cwd().resolve()
    manifest = root / "package.json"
    if manifest.is_symlink():
        raise ValueError("Symlinked manifests are not supported")
    root_data = json.loads(manifest.read_text(encoding="utf-8"))
    patterns = root_data.get("workspaces", [])
    if isinstance(patterns, dict):
        patterns = patterns.get("packages", [])
    if not isinstance(patterns, list) or any(not isinstance(p, str) or p.startswith(("!", "/")) or ".." in Path(p).parts for p in patterns):
        raise ValueError("Unsupported workspace declaration")
    paths = {manifest}
    for pattern in patterns:
        for directory in root.glob(pattern):
            child = directory / "package.json"
            if child.is_file():
                if child.is_symlink() or not child.resolve().is_relative_to(root) or any(p.is_symlink() for p in [directory, *directory.parents] if p != root):
                    raise ValueError("Workspace escapes repository or uses symlinks")
                paths.add(child)
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", relative], capture_output=True)
        if tracked.returncode:
            raise ValueError("Every package manifest must be tracked")
        yield path, json.loads(path.read_text(encoding="utf-8"))


def update(package, target):
    if not re.fullmatch(r"(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_][A-Za-z0-9_.-]*", package):
        raise ValueError("Unsafe package name")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?", target):
        raise ValueError("Target must be an exact version")
    if any(Path(p).exists() for p in ("pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock", "bun.lock", "bun.lockb")):
        raise ValueError("This release requires npm; other package managers need separate acceptance")
    updates = []
    for path, data in manifests():
        sections = [section for section in (*SECTIONS, "peerDependencies") if package in data.get(section, {})]
        if not sections:
            continue
        if len(sections) != 1 or sections[0] == "peerDependencies":
            raise ValueError("Ambiguous or peer-only dependency requires manual review")
        # Pin the selected fix exactly, so installation cannot silently test a
        # different newer version while reporting the selected one.
        data[sections[0]][package] = target
        updates.append((path, data))
    if not updates:
        raise ValueError("No direct declaration in the root or declared npm workspaces")
    for path, data in updates:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "npm install --ignore-scripts --no-audit --no-fund", "."


def validate_target(package, target):
    root = Path.cwd().resolve()
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    if lock.get("lockfileVersion") not in (2, 3) or not isinstance(lock.get("packages"), dict):
        raise ValueError("npm lockfile v2 or v3 is required")
    owners = []
    for manifest, data in manifests():
        sections = [s for s in SECTIONS if package in data.get(s, {})]
        if not sections:
            continue
        if any(data[s][package] != target for s in sections):
            raise ValueError("Manifest target changed during install or verification")
        owner = manifest.parent
        owner_key = owner.relative_to(root).as_posix()
        owner_key = "" if owner_key == "." else owner_key
        locked_owner = lock["packages"].get(owner_key, {})
        if any(locked_owner.get(s, {}).get(package) != target for s in sections):
            raise ValueError("Lockfile declaration does not match requested target")
        current = owner
        while True:
            installed = current / "node_modules" / package / "package.json"
            if installed.is_file():
                if not installed.resolve().is_relative_to(root):
                    raise ValueError("Installed dependency escapes isolated checkout")
                data_installed = json.loads(installed.read_text(encoding="utf-8"))
                lock_key = installed.parent.relative_to(root).as_posix()
                locked = lock["packages"].get(lock_key, {})
                if data_installed.get("version") != target or locked.get("version") != target:
                    raise ValueError("Installed/locked package differs from requested version")
                if not locked.get("integrity"):
                    raise ValueError("Installed registry package lacks lockfile integrity")
                owners.append(owner_key or ".")
                break
            if current == root:
                raise ValueError("Updated dependency is not installed for a declaring package")
            current = current.parent
    if not owners:
        raise ValueError("No dependency owners validated")
    return owners
