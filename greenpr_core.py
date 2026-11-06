"""Conservative, auditable remediation primitives. No model or credential discovery."""
from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field

import yaml

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version, InvalidVersion


class GreenPRError(RuntimeError):
    pass


@dataclass
class CommandResult:
    command: list[str] | str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0
    truncated: bool = False
    cwd: str | None = None

    def evidence(self):
        # Never persist raw process output: it can contain project secrets.
        command = self.command if isinstance(self.command, list) else {
            "kind": "user_shell_command", "sha256": hashlib.sha256(self.command.encode()).hexdigest()}
        return {"command": command, "exit_code": self.returncode, "working_directory": self.cwd,
                "seconds": round(self.seconds, 3), "output_truncated": self.truncated}


def run(command, *, cwd, timeout=180, env=None, shell=False, max_output=2_000_000):
    """Drain both pipes continuously and bound retained output, including on timeout."""
    if shell and not isinstance(command, str):
        raise ValueError("Only explicit user test commands may use a shell")
    start = time.monotonic()
    executable_command = command
    if os.name == "nt" and isinstance(command, list) and command[0] in ("npm", "pnpm", "yarn"):
        manager = command[0]
        resolved = shutil.which(manager)
        if resolved and Path(resolved).suffix.lower() in (".cmd", ".bat", ".ps1"):
            scripts = {"npm": ["node_modules/npm/bin/npm-cli.js"],
                       "pnpm": ["node_modules/pnpm/bin/pnpm.cjs", "node_modules/corepack/dist/pnpm.js"],
                       "yarn": ["node_modules/yarn/bin/yarn.js", "node_modules/corepack/dist/yarn.js"]}[manager]
            entry = next((Path(resolved).parent / s for s in scripts if (Path(resolved).parent / s).is_file()), None)
            if entry is None:
                raise GreenPRError(f"Cannot safely resolve the Windows {manager} Node entry point")
            executable_command = ["node", str(entry), *command[1:]]
    kwargs = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x4}  # CREATE_SUSPENDED
    job = None
    try:
        proc = subprocess.Popen(executable_command, cwd=cwd, env=env, shell=shell,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        if os.name == "nt":
            from windows_job import Job
            try:
                job = Job(proc)
            except BaseException:
                proc.kill()
                proc.wait()
                proc.stdout.close()
                proc.stderr.close()
                raise
    except OSError as exc:
        raise GreenPRError(f"Cannot start {command[0] if isinstance(command, list) else 'test command'}: {type(exc).__name__}") from exc
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]

    def drain(stream, index):
        try:
            while chunk := stream.read(65536):
                buffers[index].extend(chunk)
                if len(buffers[index]) > max_output:
                    del buffers[index][:-max_output]
                    truncated[index] = True
        finally:
            stream.close()

    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((proc.stdout, proc.stderr))]
    for reader in readers:
        reader.start()

    def kill_tree():
        if os.name == "nt":
            job.terminate()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        proc.wait(timeout=15)

    timed_out = False
    next_progress = start + 10
    try:
        # A shell can exit while its child still owns the pipes. Include readers in deadline.
        while proc.poll() is None or any(t.is_alive() for t in readers):
            if time.monotonic() >= next_progress:
                print(f"GreenPR: command still running ({int(time.monotonic() - start)}s)", file=sys.stderr, flush=True)
                next_progress = time.monotonic() + 10
            if time.monotonic() - start >= timeout:
                timed_out = True
                kill_tree()
                break
            time.sleep(0.02)
    except BaseException:
        kill_tree()
        if job:
            job.close()
        raise
    for reader in readers:
        reader.join(timeout=2)
    if job:
        job.close()
    elif os.name != "nt":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    if any(t.is_alive() for t in readers):
        raise GreenPRError("Unable to stop a child holding command output; inspect runner processes")
    return CommandResult(command, 124 if timed_out else proc.returncode,
                         *(bytes(b).decode("utf-8", "replace") for b in buffers),
                         time.monotonic() - start, any(truncated), str(cwd))


def checked(command, cwd, **kwargs):
    result = run(command, cwd=cwd, **kwargs)
    if result.truncated:
        raise GreenPRError(f"Command output exceeded limit: {command[0]}")
    if result.returncode:
        raise GreenPRError(f"Command failed (exit {result.returncode}): {command[0]}")
    return result


def inside(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise GreenPRError("Path escapes the project checkout")
    return path


def ordered_version(value, ecosystem):
    value = str(value).removeprefix("v")
    if ecosystem.lower() == "pypi":
        return Version(value)
    # Limit auto-selection to stable SemVer. Ecosystem-specific/GIT versions fail closed.
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\+[0-9A-Za-z.-]+)?", value):
        raise ValueError("Unsupported or prerelease version")
    return tuple(map(int, value.split("+")[0].split(".")))


def affected_at(candidate, affected, ecosystem):
    """True = vulnerable; False = outside all known intervals; None = uncertain."""
    cv = ordered_version(candidate, ecosystem)
    for v in affected.get("versions", []):
        try:
            if ordered_version(v, ecosystem) == cv:
                return True
        except (ValueError, InvalidVersion):
            return None
    ranges = affected.get("ranges", [])
    if not ranges:
        return None  # An enumerated historical list cannot prove a future release safe.
    for interval in ranges:
        if interval.get("type") not in ("SEMVER", "ECOSYSTEM"):
            return None
        if interval.get("type") == "ECOSYSTEM" and ecosystem.lower() != "pypi":
            return None
        events = interval.get("events", [])
        if not events or "introduced" not in events[0]:
            return None
        lower = None
        opened = False
        for event in events:
            if len(event) != 1:
                return None
            kind, value = next(iter(event.items()))
            if kind == "introduced":
                if opened:
                    return None
                lower = None if value == "0" else ordered_version(value, ecosystem)
                opened = True
            elif kind in ("fixed", "last_affected", "limit") and opened:
                upper = ordered_version(value, ecosystem)
                if lower is not None and upper < lower:
                    return None
                if (lower is None or cv >= lower) and (cv <= upper if kind == "last_affected" else cv < upper):
                    return True
                opened = False
            else:
                return None
        if opened and (lower is None or cv >= lower):
            return True
    return False


def select_target_version(package, current, advisories, ecosystem="npm"):
    """Choose a stable forward fix proven outside every advisory, or refuse automation."""
    try:
        current_key = ordered_version(current, ecosystem)
        records = []
        fixes = set()
        for advisory in advisories:
            matching = [a for a in advisory.get("affected", [])
                        if a.get("package", {}).get("name") == package
                        and a.get("package", {}).get("ecosystem", ecosystem).lower() == ecosystem.lower()]
            if not matching:
                return None
            records.extend(matching)
            for affected in matching:
                for interval in affected.get("ranges", []):
                    for event in interval.get("events", []):
                        if event.get("fixed"):
                            fixes.add(event["fixed"])
        candidates = []
        for fix in fixes:
            try:
                key = ordered_version(fix, ecosystem)
                if isinstance(key, Version) and (key.is_prerelease or key.is_devrelease):
                    continue
                if key > current_key:
                    candidates.append(fix)
            except (ValueError, InvalidVersion):
                continue
        for candidate in sorted(candidates, key=lambda v: ordered_version(v, ecosystem)):
            if records and all(affected_at(candidate, a, ecosystem) is False for a in records):
                return candidate
    except (ValueError, InvalidVersion, TypeError, KeyError):
        pass
    return None


@dataclass
class Scan:
    packages: list[dict]
    findings: list[dict]
    evidence: dict


def scan(root: Path, scanner="osv-scanner", timeout=180):
    root = root.resolve()
    result = run([scanner, "scan", "source", "--format=json", "--all-packages", "-r", "."],
                 cwd=root, timeout=timeout, max_output=20_000_000)
    if result.returncode not in (0, 1) or result.truncated:
        raise GreenPRError(f"Security scan failed (exit {result.returncode}, truncated={result.truncated})")
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("missing results")
        packages, findings = [], []
        for group in data["results"]:
            source = inside(root, group["source"]["path"])
            relative = source.relative_to(root).as_posix()
            if not source.is_file() or not isinstance(group["packages"], list):
                raise ValueError("invalid source or packages")
            for record in group["packages"]:
                pkg = record["package"]
                if not all(isinstance(pkg.get(k), str) and pkg[k] for k in ("name", "version", "ecosystem")):
                    raise ValueError("invalid package identity")
                item = {"package": pkg["name"], "current_version": pkg["version"],
                        "ecosystem": pkg["ecosystem"].lower(), "manifest_path": relative,
                        "working_dir": source.parent.relative_to(root).as_posix()}
                packages.append(item)
                advisories = record.get("vulnerabilities", [])
                if not isinstance(advisories, list):
                    raise ValueError("invalid vulnerabilities")
                if advisories:
                    item = {**item, "advisories": advisories,
                            "advisory_ids": sorted(a["id"] for a in advisories),
                            "target_version": select_target_version(pkg["name"], pkg["version"], advisories, pkg["ecosystem"])}
                    findings.append(item)
        if not packages:
            raise ValueError("no packages inventoried")
        if (result.returncode == 1) != bool(findings):
            raise ValueError("scanner status disagrees with vulnerability inventory")
        return Scan(packages, findings, result.evidence())
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise GreenPRError("Scanner returned invalid, incomplete, or inconsistent JSON") from exc


def finding_key(item):
    return (item["manifest_path"], item["ecosystem"], item["package"])


def verify_rescan(before: Scan, after: Scan, finding):
    before_keys = {finding_key(p) for p in before.packages}
    after_keys = {finding_key(p) for p in after.packages}
    if before_keys - after_keys:
        # An absent package could be a legitimate graph removal OR missing scanner
        # coverage. Without independent removal evidence it cannot count as fixed.
        raise GreenPRError("Rescan lost manifest/package coverage; removed dependencies require manual review")
    after_versions = {(finding_key(p), p["current_version"]) for p in after.packages}
    after_assertions = {(finding_key(f), f["current_version"], advisory)
                        for f in after.findings for advisory in f["advisory_ids"]}
    for prior in before.findings:
        version_key = (finding_key(prior), prior["current_version"])
        if version_key in after_versions and any((*version_key, a) not in after_assertions for a in prior["advisory_ids"]):
            raise GreenPRError("Rescan omitted an advisory for an unchanged package version; manual review required")
    key = finding_key(finding)
    observed = [p for p in after.packages if finding_key(p) == key]
    if not observed or not any(p["current_version"].removeprefix("v") == finding["target_version"].removeprefix("v") for p in observed):
        raise GreenPRError("Rescan did not confirm the requested version in the original manifest")
    if any(finding_key(f) == key for f in after.findings):
        raise GreenPRError("Target package still has known vulnerabilities after remediation")
    old = {(finding_key(f), a) for f in before.findings for a in f["advisory_ids"]}
    new = {(finding_key(f), a) for f in after.findings for a in f["advisory_ids"]}
    if new - old:
        raise GreenPRError("Rescan found new vulnerabilities; manual review required")


def git(root, *args):
    return checked(["git", *args], root).stdout.strip()


@contextlib.contextmanager
def isolated_checkout(root: Path, base: str):
    # Worktree is created by this function in a fresh dedicated temporary parent.
    parent = Path(tempfile.mkdtemp(prefix="greenpr-"))
    path = parent / "checkout"
    added = False
    try:
        git(root, "worktree", "add", "--detach", str(path), base)
        added = True
        yield path, parent
    finally:
        if added:
            # Never remove or reset the user's checkout. Verify our exact owned target.
            if path.resolve().parent != parent.resolve() or not parent.name.startswith("greenpr-"):
                raise GreenPRError("Refusing unsafe worktree cleanup")
            git(root, "worktree", "remove", "--force", str(path))
        shutil.rmtree(parent)


def repository_state(root):
    return {"head": git(root, "rev-parse", "HEAD"),
            "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "status": git(root, "status", "--porcelain=v1", "--untracked-files=all")}


def preflight(root, *, scanner, delivery):
    resolved = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if root.resolve() != resolved:
        raise GreenPRError("Run from the repository root (or specify --repo)")
    state = repository_state(root)
    if git(root, "ls-files", ".gitmodules"):
        raise GreenPRError("Submodule remediation is not supported; review each repository separately")
    for tool in (scanner, "gh") if delivery else (scanner,):
        if not shutil.which(tool):
            raise GreenPRError(f"Required executable not found: {Path(tool).name}")
    scanner_version = checked([scanner, "--version"], root)
    if not re.search(r"\bv?2\.\d+", scanner_version.stdout + scanner_version.stderr):
        raise GreenPRError("Require OSV-Scanner v2; scanner version could not be verified")
    if delivery:
        git(root, "remote", "get-url", "origin")
        checked(["gh", "auth", "status"], root)
        if state["branch"] == "HEAD":
            raise GreenPRError("PR delivery requires an explicit checked-out base branch")
    return state


@dataclass
class UpdatePlan:
    cwd: Path
    files: dict[Path, str]
    commands: list[list[str]]
    tests: list[list[str] | str]
    env: dict | None = None
    setup: list[list[str]] = field(default_factory=list)
    test_directories: list[Path] = field(default_factory=list)


def node_manager(directory):
    locks = [("npm", "package-lock.json"), ("pnpm", "pnpm-lock.yaml"),
             ("yarn", "yarn.lock"), ("bun", "bun.lock"), ("bun", "bun.lockb")]
    found = {manager for manager, lock in locks if (directory / lock).is_file()}
    if len(found) != 1:
        raise GreenPRError("Require exactly one supported lockfile beside package.json")
    return found.pop()


def node_checks(data, manager):
    """Select meaningful gates without falling back after a failed required gate."""
    scripts = data.get("scripts", {})
    names = [name for name in ("typecheck", "test") if name in scripts]
    if "test" not in scripts:
        names += [name for name in ("test:unit", "test:ci") if name in scripts]
    if not names and "build" in scripts:
        names = ["build"]
    return [[manager, "run", name] for name in names]


def workspace_manifests(root, directory, data):
    """Only declared workspace members belong to a shared lockfile, never arbitrary nested projects."""
    config_file = inside(root, directory / "pnpm-workspace.yaml")
    config = None
    if config_file.exists():
        # Duplicate keys are ambiguous and should not be silently overwritten.
        class UniqueLoader(yaml.SafeLoader):
            pass
        def mapping(loader, node, deep=False):
            values = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in values:
                    raise GreenPRError("Duplicate pnpm workspace setting requires manual review")
                values[key] = loader.construct_object(value_node, deep=deep)
            return values
        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        try:
            config = yaml.load(config_file.read_text(encoding="utf-8"), Loader=UniqueLoader)
        except yaml.YAMLError as exc:
            raise GreenPRError("Invalid pnpm workspace configuration") from exc
        if not isinstance(config, dict):
            raise GreenPRError("pnpm workspace configuration must be an object")
        patterns = config.get("packages", [])
    else:
        patterns = data.get("workspaces", [])
        if isinstance(patterns, dict):
            patterns = patterns.get("packages", [])
    if not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns):
        raise GreenPRError("Unsupported workspace member patterns")
    members, exclusions = set(), []
    for pattern in patterns:
        excluding = pattern.startswith("!")
        pattern = pattern.removeprefix("!").removeprefix("./")
        if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts or any(c in pattern for c in "{}\\"):
            raise GreenPRError("Unsupported or unsafe workspace glob; use simple relative patterns")
        if excluding:
            exclusions.append(pattern)
        else:
            for match in directory.glob(pattern):
                member = inside(root, match)
                if any(part in ("node_modules", ".git", ".venv") for part in member.relative_to(directory).parts):
                    continue
                if member.is_dir() and (member / "package.json").is_file():
                    members.add(inside(root, member / "package.json"))
    manifests = [inside(root, directory / "package.json")]
    manifests += sorted(p for p in members if p not in manifests and not any(
        fnmatch.fnmatchcase(p.parent.relative_to(directory).as_posix(), pattern) for pattern in exclusions))
    return manifests, config_file, config


def node_update_plan(root, directory, package, target, custom_tests):
    manifest = inside(root, directory / "package.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GreenPRError("Invalid package.json")
    manager = node_manager(directory)
    if not shutil.which(manager):
        raise GreenPRError(f"Required package manager not found: {manager}")
    manifests, workspace_file, workspace_config = workspace_manifests(root, directory, data)
    projects = {p: json.loads(p.read_text(encoding="utf-8")) for p in manifests}
    owners = [(p, section) for p, doc in projects.items()
              for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
              if package in doc.get(section, {})]
    if len(owners) > 1 or (owners and owners[0][1] == "peerDependencies"):
        raise GreenPRError("Ambiguous or peer-only workspace dependency ownership requires manual review")
    files = {}
    owner = directory
    if owners:
        path, section = owners[0]
        owner = path.parent
        declared = projects[path][section][package]
        if not isinstance(declared, str) or any(c in declared for c in (":", "/", "\\")):
            raise GreenPRError("Local or aliased dependency declaration requires manual review")
        projects[path][section][package] = target
        files[path] = json.dumps(projects[path], indent=2) + "\n"
    else:
        # Preserve transitive support without adding the package as a new direct dependency.
        # Existing override policies may affect a different subtree; never replace them implicitly.
        if manager == "pnpm":
            if workspace_config is None or workspace_config.get("overrides") or data.get("pnpm", {}).get("overrides"):
                raise GreenPRError("Transitive pnpm repair needs an existing workspace file without override policies")
            if "overrides" in workspace_config:
                raise GreenPRError("Existing pnpm override block requires manual review")
            files[workspace_file] = workspace_file.read_text(encoding="utf-8").rstrip() + "\n\noverrides:\n  " + json.dumps(package) + ": " + json.dumps(target) + "\n"
        elif manager in ("npm", "bun", "yarn"):
            field = "resolutions" if manager == "yarn" else "overrides"
            if data.get(field):
                raise GreenPRError("Existing transitive override policy requires manual review")
            data[field] = {package: target}
            files[manifest] = json.dumps(data, indent=2) + "\n"
    commands = {"npm": [["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"]],
                "pnpm": [["pnpm", "install", "--no-frozen-lockfile", "--ignore-scripts"]],
                "yarn": [["yarn", "install", "--ignore-scripts"]],
                "bun": [["bun", "install", "--ignore-scripts"]]}[manager]
    tests = list(custom_tests) or node_checks(data, manager)
    if not tests:
        raise GreenPRError("No verification gate at the lockfile root; provide --test-cmd")
    test_directories = [directory] * len(tests)
    if owner != directory:
        owner_checks = node_checks(projects[owner / "package.json"], manager)
        tests += owner_checks
        test_directories += [owner] * len(owner_checks)
    return UpdatePlan(directory, files, commands, tests, test_directories=test_directories)


def plan_update(root: Path, finding, temp: Path, custom_tests=()):
    directory = inside(root, finding["working_dir"])
    source = inside(root, finding["manifest_path"])
    package, target = finding["package"], finding["target_version"]
    if not target:
        raise GreenPRError("No proven stable forward fix; manual review required")
    ecosystem = finding["ecosystem"]
    if ecosystem == "npm":
        return node_update_plan(root, directory, package, target, custom_tests)
    if ecosystem == "pypi":
        if source.name != "requirements.txt" or any((directory / name).exists() for name in ("pyproject.toml", "poetry.lock", "uv.lock")):
            raise GreenPRError("Automatic Python updates currently require plain requirements.txt; managed lockfiles need manual review")
        lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
        matches = []
        for i, line in enumerate(lines):
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            # Do not silently invalidate hashes, includes, index policy, markers, or URL requirements.
            if content.startswith("-") or "\\" in content or " #" in content:
                raise GreenPRError("Complex requirements files need a lock-aware manual update")
            try:
                req = Requirement(content)
            except Exception as exc:
                raise GreenPRError("Unsupported requirement syntax") from exc
            if req.url or req.marker:
                raise GreenPRError("URL or conditional requirements need manual review")
            if canonicalize_name(req.name) == canonicalize_name(package):
                if len(req.specifier) != 1 or next(iter(req.specifier)).operator != "==":
                    raise GreenPRError("Require an exact Python pin before automatic remediation")
                matches.append(i)
                extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
                lines[i] = f"{req.name}{extras}=={target}\n"
        if len(matches) != 1:
            raise GreenPRError("Target must appear exactly once as a direct requirement")
        venv = temp / "venv"
        bindir = venv / ("Scripts" if os.name == "nt" else "bin")
        python = str(bindir / ("python.exe" if os.name == "nt" else "python"))
        env = {**os.environ, "VIRTUAL_ENV": str(venv), "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
               "PYTHONNOUSERSITE": "1"}
        tests = list(custom_tests) or [[python, "-m", "pytest"]]
        return UpdatePlan(directory, {source: "".join(lines)},
                          [[python, "-m", "pip", "install", "-r", "requirements.txt"]], tests, env,
                          [[sys.executable, "-m", "venv", str(venv)]])
    raise GreenPRError(f"Automatic updates for {ecosystem} are not yet verified; finding retained for manual remediation")


def apply_plan(plan, timeout, evidence):
    for path, content in plan.files.items():
        path.write_text(content, encoding="utf-8")
    for command in plan.setup + plan.commands:
        result = run(command, cwd=plan.cwd, env=plan.env, timeout=timeout)
        evidence.append({"stage": "install", **result.evidence()})
        if result.returncode:
            raise GreenPRError(f"Dependency setup/update failed (exit {result.returncode})")


def run_tests(plan, timeout, evidence, stage="verification"):
    failed = []
    directories = plan.test_directories or [plan.cwd] * len(plan.tests)
    if len(directories) != len(plan.tests):
        raise GreenPRError("Verification command/directory mismatch")
    for command, directory in zip(plan.tests, directories):
        result = run(command, cwd=directory, env=plan.env, timeout=timeout, shell=isinstance(command, str))
        evidence.append({"stage": stage, **result.evidence()})
        if result.returncode:
            failed.append(result)
    return failed


def deliver(root, base_branch, finding, evidence, *, skip_pr):
    diff = git(root, "diff", "--name-only")
    if not diff:
        raise GreenPRError("No tracked dependency change to deliver")
    # Only tracked files are staged. Generated build/test artifacts are never swept into a PR.
    git(root, "add", "-u")
    git(root, "-c", "user.name=GreenPR", "-c", "user.email=greenpr@users.noreply.github.com",
        "commit", "-m", f"fix(security): update {finding['package']} to {finding['target_version']}")
    commit = git(root, "rev-parse", "HEAD")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", finding["package"]).strip("-.")[:60] or "dependency"
    branch = f"greenpr/{slug}-{uuid.uuid4().hex[:12]}"
    git(root, "branch", branch, commit)
    result = {"branch": branch, "commit": commit, "changed_files": diff.splitlines(), "status": "local_verified"}
    if skip_pr:
        return result
    try:
        git(root, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    except GreenPRError:
        return {**result, "status": "local_commit_push_failed",
                "error": "Local commit retained; push failed or its outcome is uncertain. Inspect origin before retrying."}
    result["status"] = "pushed_pr_pending"
    body = "## GreenPR verification evidence\n\n"
    body += f"Dependency: {finding['package']} → {finding['target_version']}\n\n"
    body += "Executed checks (exit 0 only describes these checks):\n"
    for check in evidence:
        if check["stage"] in ("baseline", "verification", "repair_verification"):
            body += f"- {check['stage']}: `{check['command']}` — exit {check['exit_code']}\n"
    body += "\nOSV rescan confirmed the target version and no remaining advisory for this package. Other findings may remain. Human review is required; this is not a production safety guarantee.\n"
    bodyfile = root.parent / "pr-body.md"
    bodyfile.write_text(body, encoding="utf-8")
    pr = run(["gh", "pr", "create", "--draft", "--base", base_branch, "--head", branch,
              "--title", f"fix(security): update {finding['package']} to {finding['target_version']}",
              "--body-file", str(bodyfile)], cwd=root)
    if pr.returncode or not re.fullmatch(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+", pr.stdout.strip()):
        result["error"] = "Branch was pushed, but draft PR creation failed or its result is uncertain. Inspect the branch before retrying."
        return result
    return {**result, "status": "draft_pr_created", "pr_url": pr.stdout.strip()}


def run_remediation(root, finding, before, state, *, scanner, timeout, tests, skip_pr, healer=None):
    evidence = []
    record = {"package": finding["package"], "manifest": finding["manifest_path"],
              "target": finding["target_version"], "status": "failed", "checks": evidence}
    try:
        with isolated_checkout(root, state["head"]) as (work, temp):
            plan = plan_update(work, finding, temp, tests)
            # Baseline installs the committed original manifest into the isolated checkout/environment.
            original = {p: p.read_text(encoding="utf-8") for p in plan.files}
            baseline_commands = [["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]] if plan.commands and plan.commands[0][0] == "npm" else plan.commands
            baseline = UpdatePlan(plan.cwd, original, baseline_commands, plan.tests, plan.env, plan.setup)
            apply_plan(baseline, timeout, evidence)
            if run_tests(plan, timeout, evidence, "baseline"):
                raise GreenPRError("Baseline checks failed; refusing to repair pre-existing failures")
            # Discard dependency-manager baseline writes only in our private checkout.
            git(work, "restore", "--worktree", "--staged", ".")
            plan.setup = []
            apply_plan(plan, timeout, evidence)
            failed = run_tests(plan, timeout, evidence)
            for stage in (3, 4):
                if not failed or not healer or any(r.returncode == 124 for r in failed):
                    break
                healer(work, plan.cwd, failed, finding, stage, evidence)
                failed = run_tests(plan, timeout, evidence, "repair_verification")
            if failed:
                raise GreenPRError("Verification failed or timed out; isolated attempt discarded")
            after = scan(work, scanner, timeout)
            evidence.append({"stage": "rescan", **after.evidence})
            verify_rescan(before, after, finding)
            record.update(deliver(work, state["branch"], finding, evidence, skip_pr=skip_pr))
    except (GreenPRError, OSError, ValueError) as exc:
        record["error"] = str(exc) if isinstance(exc, GreenPRError) else f"Local operation failed: {type(exc).__name__}"
        record["status"] = "failed"
    return record
