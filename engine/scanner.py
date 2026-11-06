"""Scan constrained Python projects using their proven resolved pins.

Other manifests retain OSV's normal transitive resolution. A constraints file
alone is not a complete dependency graph: pip must prove its active-platform
closure without installing packages or executing source builds.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def _osv(command):
    result = subprocess.run(command, capture_output=True, timeout=180)
    if result.returncode not in (0, 1) or not result.stdout:
        raise RuntimeError("Scanner failed or returned no evidence")
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise RuntimeError("Unexpected scanner output schema")
    return data


def _tracked_local(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise RuntimeError("Python constraint path must remain inside the checkout")
    result = subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(path.relative_to(root))],
                            cwd=root, capture_output=True, timeout=30)
    if result.returncode or not path.is_file():
        raise RuntimeError("Constrained Python scanning requires tracked manifest and constraint files")


def constrained_projects(root):
    """Recognize explicit local -c declarations; never infer a lock by filename."""
    projects = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not name.startswith(".") and name not in
                   ("node_modules", "venv", "vendor", "target", "dist", "build", "__pycache__")]
        if "requirements.txt" not in files:
            continue
        manifest = Path(directory) / "requirements.txt"
        lines = [line.strip() for line in manifest.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        declarations = [line for line in lines if re.match(r"^(?:-c(?:\s|$)|--constraint(?:[=\s]|$))", line)]
        if not declarations:
            continue
        _tracked_local(manifest, root)
        pins, constraints = {}, []
        for declaration in declarations:
            match = re.fullmatch(r"(?:-c\s+|--constraint(?:=|\s+))([^\s#]+)(?:\s+#.*)?", declaration)
            if not match:
                raise RuntimeError("Unsupported Python constraint directive")
            candidate = manifest.parent / match.group(1)
            _tracked_local(candidate, root)
            constraints.append(candidate.resolve())
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
                if not line or line.startswith("#"):
                    continue
                requirement = Requirement(line)
                specs = list(requirement.specifier)
                if (requirement.url or requirement.marker or requirement.extras or len(specs) != 1
                        or specs[0].operator != "==" or "*" in specs[0].version):
                    raise RuntimeError("Constraints must contain unconditional exact package pins")
                name, version = canonicalize_name(requirement.name), str(Version(specs[0].version))
                if name in pins and pins[name] != version:
                    raise RuntimeError("Conflicting Python constraint pins")
                pins[name] = version
        for line in lines:
            if line in declarations:
                continue
            requirement = Requirement(re.split(r"\s+#", line, maxsplit=1)[0])
            name = canonicalize_name(requirement.name)
            if requirement.url or name not in pins or Version(pins[name]) not in requirement.specifier:
                raise RuntimeError("Every direct Python requirement must be covered by compatible exact constraints")
        projects.append((manifest, constraints, pins))
    return projects


def _resolved_pins(manifest, pins, directory):
    report = directory / "pip-report.json"
    command = [sys.executable, "-m", "pip", "--isolated", "install", "--dry-run", "--ignore-installed",
               "--only-binary=:all:", "--disable-pip-version-check", "--report", str(report), "-r", str(manifest)]
    result = subprocess.run(command, cwd=manifest.parent, capture_output=True, timeout=180)
    if result.returncode or not report.is_file():
        raise RuntimeError("Could not prove constrained Python dependency closure without installing packages")
    payload = json.loads(report.read_text(encoding="utf-8"))
    if payload.get("version") != "1" or not isinstance(payload.get("install"), list) or not payload["install"]:
        raise RuntimeError("Unsupported or empty pip resolution report")
    resolved = {}
    for item in payload["install"]:
        metadata = item["metadata"]
        name, version = canonicalize_name(metadata["name"]), str(Version(metadata["version"]))
        if pins.get(name) != version:
            raise RuntimeError("Python constraints do not pin the complete resolved dependency graph: " + name)
        resolved[name] = version
    return resolved, payload.get("environment", {})


def scan_source():
    root = Path.cwd().resolve()
    projects = constrained_projects(root)
    data = _osv(["osv-scanner", "scan", "source", "--format=json", "--all-packages", "-r", "."])
    for manifest, constraints, pins in projects:
        with tempfile.TemporaryDirectory(prefix="greenpr-python-scan-") as folder:
            temporary = Path(folder)
            resolved, environment = _resolved_pins(manifest, pins, temporary)
            exact = temporary / "requirements.txt"
            exact.write_text("".join(f"{name}=={value}\n" for name, value in sorted(resolved.items())), encoding="utf-8")
            proven = _osv(["osv-scanner", "scan", "source", "--format=json", "--all-packages", "--no-resolve",
                           "--lockfile", "requirements.txt:" + str(exact)])
            scanned = {canonicalize_name(item["package"]["name"]): str(Version(item["package"]["version"]))
                       for result in proven["results"] for item in result.get("packages", [])
                       if item["package"].get("ecosystem", "").lower() == "pypi"}
            if scanned != resolved:
                raise RuntimeError("Scanner did not return the complete constrained Python package set")
            replaced = {manifest.resolve(), *constraints}
            data["results"] = [result for result in data["results"]
                               if Path(result.get("source", {}).get("path", "")).resolve() not in replaced]
            for result in proven["results"]:
                result["source"] = {"path": str(manifest), "type": "lockfile",
                                    "greenpr_resolution": "pip-dry-run-complete-constraints",
                                    "constraints": [str(path) for path in constraints], "environment": environment}
                data["results"].append(result)
            print(f"[GreenPR Radar] Verified {len(resolved)} constrained Python packages: {manifest.relative_to(root)}")
    return data
