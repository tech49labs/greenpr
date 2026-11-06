#!/usr/bin/env python3
"""
GreenPR: Dependency updates checked against your verification command.
Proprietary software by tech49labs. All rights reserved.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple
from packaging import version
from pydantic import BaseModel, Field

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ==============================================================================
# 1. GreenPR Semantic Protocol Schema
# ==============================================================================

class APISignatureChange(BaseModel):
    old_call: str = Field(description="The deprecated or removed API method or syntax")
    new_call: str = Field(description="The replacement API method or syntax")
    notes: Optional[str] = Field(default="", description="Key context or required argument differences")

class MigrationPlan(BaseModel):
    package_name: str
    target_version: str
    breaking_changes: List[APISignatureChange] = Field(default_factory=list)
    general_summary: str = Field(description="Summary of the changes and safety notes")


# ==============================================================================
# 2. Universal Language Adapters & Repository Discovery
# ==============================================================================

def parse_ver(v_str: str):
    """Parses arbitrary version strings into comparable objects safely."""
    clean = re.sub(r'^[v=\^~><\s]+', '', str(v_str).strip())
    try:
        return version.parse(clean)
    except Exception:
        parts = []
        for x in re.split(r'[\.\-+_]', clean):
            if x.isdigit():
                parts.append(int(x))
            else:
                parts.append(0)
        return tuple(parts)

LANGUAGE_PROFILES = {
    "node": {
        "name": "Node.js / TypeScript",
        "ecosystems": ["npm"],
        "detect": lambda p: os.path.exists(os.path.join(p, "package.json")),
        "bump_cmd": lambda pkg, ver, p=".": (
            f"bun add -d {pkg}@{ver}" if os.path.exists(os.path.join(p, "bun.lock")) or os.path.exists(os.path.join(p, "bun.lockb"))
            else f"pnpm add -D -w {pkg}@{ver}" if (p in (".", "") and os.path.exists("pnpm-workspace.yaml"))
            else f"pnpm add -D {pkg}@{ver}" if (os.path.exists(os.path.join(p, "pnpm-lock.yaml")) or os.path.exists("pnpm-lock.yaml") or os.path.exists("pnpm-workspace.yaml"))
            else f"yarn add -D {pkg}@{ver}" if os.path.exists(os.path.join(p, "yarn.lock")) or os.path.exists("yarn.lock")
            else f"npm install --save-dev {pkg}@{ver}"
        ),
        "lint_cmd": "npx eslint . --fix",
        "compile_cmd": "npx tsc --noEmit",
        "default_test": "npm test",
    },
    "python": {
        "name": "Python",
        "ecosystems": ["pypi"],
        "detect": lambda p: os.path.exists(os.path.join(p, "pyproject.toml")) or os.path.exists(os.path.join(p, "requirements.txt")) or os.path.exists(os.path.join(p, "poetry.lock")),
        "bump_cmd": lambda pkg, ver, p=".": (
            f"poetry add {pkg}=={ver}" if os.path.exists(os.path.join(p, "poetry.lock")) or os.path.exists("poetry.lock")
            else f"uv pip install {pkg}=={ver}" if shutil.which("uv")
            else f"pip install {pkg}=={ver}"
        ),
        "lint_cmd": "ruff check . --fix" if shutil.which("ruff") else None,
        "compile_cmd": "mypy ." if shutil.which("mypy") else None,
        "default_test": "python -m pytest",
    },
    "go": {
        "name": "Go",
        "ecosystems": ["go"],
        "detect": lambda p: os.path.exists(os.path.join(p, "go.mod")),
        "bump_cmd": lambda pkg, ver, p=".": f"go get {pkg}@{ver} && go mod tidy",
        "lint_cmd": "golangci-lint run --fix" if shutil.which("golangci-lint") else None,
        "compile_cmd": "go build ./...",
        "default_test": "go test ./...",
    },
    "rust": {
        "name": "Rust",
        "ecosystems": ["crates.io"],
        "detect": lambda p: os.path.exists(os.path.join(p, "Cargo.toml")),
        "bump_cmd": lambda pkg, ver, p=".": f"cargo update -p {pkg} --precise {ver}",
        "lint_cmd": "cargo clippy --fix --allow-dirty",
        "compile_cmd": "cargo check",
        "default_test": "cargo test",
    },
    "java": {
        "name": "Java (Maven / Gradle)",
        "ecosystems": ["maven"],
        "detect": lambda p: os.path.exists(os.path.join(p, "pom.xml")) or os.path.exists(os.path.join(p, "build.gradle")) or os.path.exists(os.path.join(p, "build.gradle.kts")),
        "bump_cmd": lambda pkg, ver, p=".": (
            f"mvn versions:use-dep-version -Dincludes={pkg} -DdepVersion={ver}" if os.path.exists(os.path.join(p, "pom.xml"))
            else "./gradlew dependencyUpdates"
        ),
        "lint_cmd": None,
        "compile_cmd": "mvn compile -q" if os.path.exists("pom.xml") else "./gradlew classes",
        "default_test": "mvn test" if os.path.exists("pom.xml") else "./gradlew test",
    },
    "dotnet": {
        "name": "C# / .NET",
        "ecosystems": ["nuget"],
        "detect": lambda p: len(glob.glob(os.path.join(p, "*.csproj"))) > 0 or len(glob.glob(os.path.join(p, "*.sln"))) > 0,
        "bump_cmd": lambda pkg, ver, p=".": f"dotnet add package {pkg} --version {ver}",
        "lint_cmd": "dotnet format",
        "compile_cmd": "dotnet build --no-restore",
        "default_test": "dotnet test",
    },
}

def get_profile_for_dir(dir_path: str = ".") -> Optional[Dict]:
    """Resolves language profile for a specific directory."""
    for key, profile in LANGUAGE_PROFILES.items():
        if profile["detect"](dir_path):
            selected = dict(profile)
            if key == "java":
                selected["default_test"] = "mvn -B -ntp test" if os.path.exists(os.path.join(dir_path, "pom.xml")) else "gradlew.bat test --no-daemon" if os.name == "nt" and os.path.exists(os.path.join(dir_path, "gradlew.bat")) else "./gradlew test --no-daemon" if os.path.exists(os.path.join(dir_path, "gradlew")) else "gradle test --no-daemon"
            return selected
    return None

def discover_repository_profiles(root_dir: str = ".") -> List[Dict]:
    """Discovers all active language profiles and subprojects across the repository."""
    found = []
    seen = set()

    root_prof = get_profile_for_dir(root_dir)
    if root_prof:
        found.append(root_prof)
        seen.add(root_prof["name"])

    try:
        for entry in os.scandir(root_dir):
            if entry.is_dir() and not entry.name.startswith(".") and entry.name not in ("node_modules", "dist", "build", "target", "vendor", "venv", ".venv", "__pycache__"):
                sub_p = get_profile_for_dir(entry.path)
                if sub_p and sub_p["name"] not in seen:
                    found.append(sub_p)
                    seen.add(sub_p["name"])
                try:
                    for sub_entry in os.scandir(entry.path):
                        if sub_entry.is_dir() and not sub_entry.name.startswith(".") and sub_entry.name not in ("node_modules", "dist", "build", "target", "vendor", "venv", ".venv", "__pycache__"):
                            leaf_p = get_profile_for_dir(sub_entry.path)
                            if leaf_p and leaf_p["name"] not in seen:
                                found.append(leaf_p)
                                seen.add(leaf_p["name"])
                except Exception:
                    pass
    except Exception:
        pass

    return found

def _kill_process_tree(pid: int):
    """Cleanly terminates a process and all of its spawned child processes across platforms."""
    if sys.platform == "win32":
        try:
            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    else:
        try:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            try:
                import signal
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

def locate_package_owner(pkg_name: str, repo_root: str = ".") -> Tuple[str, str, bool, Optional[str], Optional[str]]:
    """
    Intelligently inspects repository manifests across workspaces to isolate which project
    actually declares a dependency.
    Returns: (owner_dir, display_name, is_direct, dep_type, declared_version)
    """
    found = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', 'dist', 'build', '.next', '__pycache__', 'target', 'vendor', '.venv', 'venv')]
        if 'package.json' in files:
            pj_path = os.path.join(root, 'package.json')
            try:
                with open(pj_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                name = data.get('name') or os.path.relpath(root, repo_root).replace('\\', '/')
                if name == ".":
                    name = "(root)"
                deps = data.get('dependencies', {})
                dev_deps = data.get('devDependencies', {})
                peer_deps = data.get('peerDependencies', {})
                optional_deps = data.get('optionalDependencies', {})
                if pkg_name in deps:
                    found.append((root, name, True, 'dependencies', deps[pkg_name]))
                elif pkg_name in dev_deps:
                    found.append((root, name, True, 'devDependencies', dev_deps[pkg_name]))
                elif pkg_name in optional_deps:
                    found.append((root, name, True, 'optionalDependencies', optional_deps[pkg_name]))
                elif pkg_name in peer_deps:
                    found.append((root, name, True, 'peerDependencies', peer_deps[pkg_name]))
            except Exception:
                pass
    if found:
        # Prefer specific subproject over root if declared in subproject
        non_roots = [f for f in found if f[0] != repo_root and f[0] not in (".", "")]
        return non_roots[0] if non_roots else found[0]

    return (repo_root, "(transitive)", False, None, None)

def probe_and_select_verification_gate(repo_root: str = ".", custom_cmd: Optional[str] = None, timeout: int = 300) -> Tuple[Optional[str], float]:
    """
    Executes a pre-flight sanity check on the pristine repository BEFORE touching any code.
    Probes candidate gates in order of reliability to discard broken or hanging commands.
    """
    print("[GreenPR Baseline] Probing repository verification gates on clean branch...")
    candidates = []
    if custom_cmd:
        candidates.append(custom_cmd)

    pj_path = os.path.join(repo_root, "package.json")
    if os.path.exists(pj_path):
        try:
            with open(pj_path, "r", encoding="utf-8") as f:
                pj = json.load(f)
            scripts = pj.get("scripts", {})
            pkg_mgr = "bun" if os.path.exists(os.path.join(repo_root, "bun.lock")) else \
                      "pnpm" if os.path.exists(os.path.join(repo_root, "pnpm-lock.yaml")) else \
                      "yarn" if os.path.exists(os.path.join(repo_root, "yarn.lock")) else "npm"

            # Functional test suites are highest fidelity
            if "test" in scripts:
                candidates.append(f"{pkg_mgr} test")
            if "test:unit" in scripts:
                candidates.append(f"{pkg_mgr} run test:unit")
            if "test:ci" in scripts:
                candidates.append(f"{pkg_mgr} run test:ci")
            # Compilers / Typecheckers
            if "typecheck" in scripts:
                candidates.append(f"{pkg_mgr} run typecheck" if pkg_mgr == "npm" else f"{pkg_mgr} typecheck")
            if "build" in scripts:
                candidates.append(f"{pkg_mgr} run build" if pkg_mgr == "npm" else f"{pkg_mgr} build")
        except Exception:
            pass

    prof = get_profile_for_dir(repo_root)
    if prof and prof.get("default_test") and prof["default_test"] not in candidates:
        candidates.append(prof["default_test"])

    if custom_cmd:
        candidates = [custom_cmd]
    elif os.path.exists(pj_path):
        from engine.npm import manifests
        selected = []
        workspace_scripts = set()
        for path, manifest in manifests():
            available = [name for name in ("test", "test:unit", "test:ci", "typecheck", "build") if name in manifest.get("scripts", {})]
            if not available:
                print(f"[ERROR] No verification scripts configured for {path}")
                return None, 0.0
            if path.parent == __import__("pathlib").Path(repo_root).resolve():
                selected.extend(f"npm run {name}" for name in available)
            else:
                workspace_scripts.update(available)
        selected.extend(f"npm run {name} --workspaces --if-present" for name in sorted(workspace_scripts))
        candidates = [" && ".join(selected)] if selected else []
    # Every configured gate is mandatory; never weaken on failure.
    from engine.diagnostics import redact
    for cmd in candidates[:1]:  # Never substitute a weaker gate after a failure.
        started = time.monotonic()
        result = _run_with_heartbeat(cmd, "Baseline verification", cwd=repo_root,
                                     timeout=timeout, phase="baseline")
        duration = time.monotonic() - started
        if result.returncode == 0:
            print(f"[GreenPR Baseline] Verified passing gate: '{redact(cmd)}' (exit 0 in {duration:.1f}s)\n")
            return cmd, duration
    return None, 0.0


def resolve_subproject_test_cmd(working_dir: str, custom_test_cmd: Optional[str] = None) -> str:
    """Intelligently detects or applies the verification command for a subproject directory."""
    if custom_test_cmd:
        return custom_test_cmd

    pkg_json = os.path.join(working_dir, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8", errors="replace") as f:
                pj = json.load(f)
            scripts = pj.get("scripts", {})
            pkg_mgr = "bun" if os.path.exists(os.path.join(working_dir, "bun.lock")) or os.path.exists(os.path.join(working_dir, "bun.lockb")) else \
                      "pnpm" if os.path.exists(os.path.join(working_dir, "pnpm-lock.yaml")) or os.path.exists("pnpm-lock.yaml") or os.path.exists("pnpm-workspace.yaml") else \
                      "yarn" if os.path.exists(os.path.join(working_dir, "yarn.lock")) else "npm"
            
            if "test" in scripts:
                return f"{pkg_mgr} test"
            elif "typecheck" in scripts:
                return f"{pkg_mgr} run typecheck" if pkg_mgr == "npm" else f"{pkg_mgr} typecheck"
            elif os.path.exists(os.path.join(working_dir, "tsconfig.json")):
                return "npx tsc --noEmit"
        except Exception:
            pass

    sub_profile = get_profile_for_dir(working_dir)
    if sub_profile:
        return sub_profile.get("default_test", "pytest")
    return "pytest"

# ==============================================================================
# 3. Model-Agnostic Engine Resolver
# ==============================================================================

def resolve_engine_tiers() -> Dict[str, Optional[str]]:
    """Resolves primary and secondary model routing based on available environment credentials."""
    if os.environ.get("GREENPR_ENABLE_MODEL_REPAIR") != "1":
        return {"tier1": None, "tier2": None, "provider": "disabled"}
    raw_key = os.environ.get("GREENPR_API_KEY")
    explicit_model = os.environ.get("GREENPR_MODEL") or os.environ.get("MODEL")

    if raw_key:
        if raw_key.startswith("sk-ant-") and "ANTHROPIC_API_KEY" not in os.environ:
            os.environ["ANTHROPIC_API_KEY"] = raw_key
        elif (raw_key.startswith("AQ.") or raw_key.startswith("AIza")) and "GEMINI_API_KEY" not in os.environ:
            os.environ["GEMINI_API_KEY"] = raw_key
        elif raw_key.startswith("sk-") and "OPENAI_API_KEY" not in os.environ:
            os.environ["OPENAI_API_KEY"] = raw_key

    if explicit_model:
        return {"tier1": explicit_model, "tier2": explicit_model, "provider": "custom"}

    if "GEMINI_API_KEY" in os.environ:
        return {"tier1": "gemini-flash-latest", "tier2": "gemini-pro-latest", "provider": "gemini"}
    elif "ANTHROPIC_API_KEY" in os.environ:
        return {"tier1": "claude-3-5-haiku-latest", "tier2": "claude-3-5-sonnet-latest", "provider": "anthropic"}
    elif "OPENAI_API_KEY" in os.environ:
        return {"tier1": "gpt-4o-mini", "tier2": "gpt-4o", "provider": "openai"}
    elif "DEEPSEEK_API_KEY" in os.environ:
        return {"tier1": "deepseek-chat", "tier2": "deepseek-reasoner", "provider": "deepseek"}
    elif "GROQ_API_KEY" in os.environ:
        return {"tier1": "llama-3.3-70b-versatile", "tier2": "llama-3.3-70b-versatile", "provider": "groq"}

    return {"tier1": None, "tier2": None, "provider": "default"}


# ==============================================================================
# 4. GreenPR Security Radar & Semver Target Selector
# ==============================================================================

def select_target_version(pkg_name: str, current_ver: Optional[str], vulnerabilities: List[Dict]) -> Optional[str]:
    """Choose a stable newer fix outside every reported affected range; reject unknown ranges."""
    try:
        current = version.Version(re.sub(r"^[v=^~>< ]+", "", current_ver or ""))
        ranges = []
        fixes = set()
        listed_versions = set()
        for advisory in vulnerabilities:
            matching = [item for item in advisory.get("affected", []) if item.get("package", {}).get("name") == pkg_name]
            if not matching:
                return None
            for affected in matching:
                listed_versions.update(affected.get("versions", []))
                if not affected.get("ranges"):
                    return None
                for affected_range in affected["ranges"]:
                    if affected_range.get("type") not in ("SEMVER", "ECOSYSTEM"):
                        return None
                    lower = None
                    for event in affected_range.get("events", []):
                        if "introduced" in event:
                            if lower is not None:
                                return None
                            lower = version.Version(event["introduced"])
                        elif "fixed" in event:
                            if lower is None:
                                return None
                            upper = version.Version(event["fixed"])
                            ranges.append((lower, upper, False))
                            fixes.add(event["fixed"])
                            lower = None
                        elif "last_affected" in event:
                            if lower is None:
                                return None
                            ranges.append((lower, version.Version(event["last_affected"]), True))
                            lower = None
                        else:
                            return None
                    if lower is not None:
                        ranges.append((lower, None, False))
        for fix in sorted(fixes, key=version.Version):
            candidate = version.Version(fix)
            if candidate <= current or candidate.is_prerelease or candidate.is_devrelease or fix in listed_versions:
                continue
            if not any(candidate >= low and (high is None or candidate < high or (inclusive and candidate == high))
                       for low, high, inclusive in ranges):
                return fix
    except (version.InvalidVersion, TypeError, KeyError):
        return None
    return None


def run_vulnerability_radar(active_ecosystems: Optional[List[str]] = None) -> List[Dict]:
    """Scans project dependency graph for identified security issues with strict monorepo ecosystem binding."""
    print("[GreenPR Radar] Scanning dependency graph for security vulnerabilities...")
    try:
        from engine.scanner import scan_source
        data = scan_source()
        vulnerabilities = []

        for result in data.get("results", []):
            source_info = result.get("source", {})
            source_path = source_info.get("path", "").replace("\\", "/")
            if os.path.isabs(source_path):
                source_path = os.path.relpath(source_path, ".").replace("\\", "/")
            working_dir = os.path.dirname(source_path) if source_path else "."
            if not working_dir:
                working_dir = "."

            # Ignore untracked worktrees, build artifacts, test fixtures, and vendor folders
            skip_patterns = ["node_modules", "worktree", "acceptance-download", ".git", ".cache", "/tmp/", "/dist/", "/build/"]
            if any(p.lower() in source_path.lower() for p in skip_patterns):
                continue

            for package in result.get("packages", []):
                pkg_info = package.get("package", {})
                pkg_name = pkg_info.get("name")
                current_ver = pkg_info.get("version")
                ecosystem = pkg_info.get("ecosystem", "")

                # Monorepo ecosystem filter
                if active_ecosystems and ecosystem:
                    allowed = [e.lower() for e in active_ecosystems]
                    if ecosystem.lower() not in allowed:
                        continue

                vuln_list = package.get("vulnerabilities", [])
                target_version = select_target_version(pkg_name, current_ver, vuln_list)
                if not target_version:
                    continue

                primary_vuln = vuln_list[0] if vuln_list else {}
                vuln_id = primary_vuln.get("id", "SECURITY")

                if ecosystem.lower() == "npm":
                    owner_dir, subproj, is_direct, dep_type, decl_ver = locate_package_owner(pkg_name, ".")
                else:
                    owner_dir, subproj, is_direct, dep_type, decl_ver = working_dir, working_dir, True, None, current_ver

                vulnerabilities.append({
                    "package": pkg_name,
                    "current_version": decl_ver or current_ver,
                    "target_version": target_version,
                    "cve_id": vuln_id,
                    "summary": primary_vuln.get("summary", ""),
                    "ecosystem": ecosystem,
                    "manifest_path": source_path,
                    "working_dir": owner_dir,
                    "subproject": subproj,
                    "is_direct": is_direct,
                    "dep_type": dep_type
                })

        return vulnerabilities
    except Exception as exc:
        raise RuntimeError(f"Vulnerability scan incomplete: {exc}") from exc


# ==============================================================================
# 5. GreenPR Migration Analysis Engine
# ==============================================================================

def extract_migration_plan(package_name: str, current_ver: str, target_ver: str, changelog_text: str) -> MigrationPlan:
    """Analyzes version upgrade requirements into structured transformation schema."""
    if os.environ.get("GREENPR_ENABLE_MODEL_REPAIR") != "1":
        return MigrationPlan(package_name=package_name, target_version=target_ver, general_summary="Dependency update; model repair disabled.")
    prompt = (
        f"Analyze the following upgrade information for {package_name} from {current_ver} to {target_ver}. "
        f"Extract all breaking API changes into the schema. If no breaking changes exist, leave breaking_changes empty.\n\n"
        f"Changelog:\n{changelog_text}"
    )

    if "GEMINI_API_KEY" in os.environ:
        try:
            from google import genai
            client = genai.Client()
            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": MigrationPlan,
                }
            )
            return MigrationPlan.model_validate_json(response.text)
        except Exception:
            pass

    if "OPENAI_API_KEY" in os.environ or "DEEPSEEK_API_KEY" in os.environ:
        try:
            from openai import OpenAI
            client = OpenAI()
            response = client.beta.chat.completions.parse(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are an automated code migration compiler."},
                    {"role": "user", "content": prompt}
                ],
                response_format=MigrationPlan
            )
            return response.choices[0].message.parsed
        except Exception:
            pass

    return MigrationPlan(
        package_name=package_name,
        target_version=target_ver,
        breaking_changes=[],
        general_summary=f"Automated security remediation for {package_name} ({current_ver} -> {target_ver})."
    )


# ==============================================================================
# 6. GreenPR Optional Model-Assisted Source Repair
# ==============================================================================

def _strip_markdown(code_text: str) -> str:
    """Extracts raw code content from LLM markdown fences."""
    text = code_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
        return "\n".join(lines[1:])
    return text

def _call_native_llm(prompt: str, model_name: str, provider: str) -> Optional[str]:
    """Proprietary native inference call. Never invokes external CLIs or browser hooks."""
    if provider == "gemini" or "GEMINI_API_KEY" in os.environ:
        try:
            from google import genai
            client = genai.Client()
            clean_model = model_name.replace("gemini/", "") if model_name else "gemini-flash-latest"
            resp = client.models.generate_content(
                model=clean_model,
                contents=prompt
            )
            return resp.text.strip()
        except Exception:
            pass

    if provider == "openai" or "OPENAI_API_KEY" in os.environ or "DEEPSEEK_API_KEY" in os.environ:
        try:
            from openai import OpenAI
            client = OpenAI()
            clean_model = model_name.replace("openai/", "") if model_name else "gpt-4o-mini"
            resp = client.chat.completions.create(
                model=clean_model,
                messages=[
                    {"role": "system", "content": "You are the GreenPR dependency remediation engine."},
                    {"role": "user", "content": prompt}
                ]
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            pass

    if provider == "anthropic" or "ANTHROPIC_API_KEY" in os.environ:
        try:
            import anthropic
            client = anthropic.Anthropic()
            clean_model = model_name.replace("anthropic/", "") if model_name else "claude-3-5-haiku-latest"
            resp = client.messages.create(
                model=clean_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.content[0].text.strip()
        except Exception:
            pass

    return None

def safe_repair_path(filepath: str) -> bool:
    from pathlib import Path
    root = Path.cwd().resolve()
    path = Path(filepath)
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (ValueError, OSError):
        return False
    if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
        return False
    if resolved.suffix not in {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java", ".cs"}:
        return False
    if any(word in str(relative).lower() for word in ("test", "spec", "fixture", "node_modules", "vendor", "venv")):
        return False
    return subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(relative)],
                          capture_output=True).returncode == 0


def _extract_failing_files(error_output: str) -> List[str]:
    matches = re.findall(r'([a-zA-Z0-9_\-./\\]+\.(?:ts|tsx|js|jsx|py|go|rs|java|cs))', error_output)
    return list(dict.fromkeys(path for path in matches if safe_repair_path(path)))


def _attempt_file_patch(filepath: str, error_trace: str, vuln: Dict, plan: MigrationPlan, model_name: str, provider: str) -> bool:
    """Reads file, requests targeted fix from LLM, and writes back cleanly."""
    if not safe_repair_path(filepath):
        return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            current_code = f.read()
    except Exception:
        return False

    pkg = vuln["package"]
    target_ver = vuln["target_version"]
    breaking_text = "\n".join([f"- Replace `{b.old_call}` with `{b.new_call}`: {b.notes}" for b in plan.breaking_changes])

    prompt = (
        f"You are the GreenPR dependency remediation engine.\n"
        f"Package '{pkg}' was upgraded to version '{target_ver}'.\n"
        f"The compiler/test suite failed with this error:\n"
        f"```\n{error_trace[:4000]}\n```\n\n"
        f"File to repair: {filepath}\n"
        f"Current source code:\n"
        f"```\n{current_code[:15000]}\n```\n\n"
    )
    if breaking_text:
        prompt += f"Known API breaking signatures:\n{breaking_text}\n\n"
    prompt += (
        f"Rewrite this file so that all syntax, import, and type discrepancies are completely fixed and tests pass.\n"
        f"Return ONLY the complete updated file content inside a single ``` code block. Do NOT include any explanations, markdown comments, or external references."
    )

    remediation = _call_native_llm(prompt, model_name, provider)
    if not remediation:
        return False

    cleaned_code = _strip_markdown(remediation)
    if cleaned_code and len(cleaned_code) > 10:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(cleaned_code)
            return True
        except Exception:
            return False

    return False

def _run_with_heartbeat(cmd: str, label: str, cwd: Optional[str] = None, timeout: int = 180,
                        phase: Optional[str] = None) -> subprocess.CompletedProcess:
    """Execute a full gate and retain safe evidence, including timeout output."""
    from engine.diagnostics import record_command, redact
    started = time.monotonic()
    phase = phase or ("bootstrap" if "baseline dependenc" in label.lower() else
                      "install" if "install" in label.lower() else "final")
    safe_label = redact(label)
    sys.stdout.write(f"        • {safe_label} [0s]...")
    sys.stdout.flush()
    try:
        with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
            proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, shell=True,
                                    cwd=cwd, start_new_session=os.name != "nt")
            timed_out = False
            while proc.poll() is None:
                if time.monotonic() - started >= timeout:
                    timed_out = True
                    _kill_process_tree(proc.pid)
                    proc.wait(timeout=10)
                    break
                time.sleep(0.5)
                sys.stdout.write(f"\r        • {safe_label} [{int(time.monotonic() - started)}s elapsed]...")
                sys.stdout.flush()
            out_f.seek(0)
            err_f.seek(0)
            stdout, stderr = out_f.read(), err_f.read()
            raw = (subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
                   if timed_out else subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr))
            evidence = record_command(cmd, raw, phase=phase, duration_seconds=time.monotonic() - started)
            code = 124 if timed_out else proc.returncode
    except Exception as exc:
        evidence = record_command(cmd, exc, phase=phase, duration_seconds=time.monotonic() - started)
        code = 1
    status = "passed" if code == 0 else f"failed: {evidence['classification']}"
    print(f"\r        • {safe_label} [{status} in {evidence['elapsed_seconds']:.1f}s]")
    if code != 0:
        print(f"          {evidence['summary']}")
        if evidence.get("log_path"):
            print(f"          Diagnostic log: {evidence['log_path']}")
        else:
            # Standalone callers have no active receipt directory.
            preview = (evidence['stderr'] or evidence['stdout']).strip().splitlines()[-8:]
            for line in preview:
                print(f"          {line[:300]}")
    return subprocess.CompletedProcess(args=redact(cmd), returncode=code,
                                       stdout=evidence['stdout'].encode('utf-8'),
                                       stderr=evidence['stderr'].encode('utf-8'))


def resolve_package_bump_command(vuln: Dict, profile: Dict) -> Tuple[str, str]:
    from engine.npm import update
    if vuln.get("ecosystem", "").lower() != "npm":
        from engine.adapters import update as polyglot_update
        return polyglot_update(vuln)
    if not vuln.get("is_direct", True):
        raise ValueError("Transitive overrides require manual review")
    return update(vuln["package"], vuln["target_version"])


def verify_updated_target(vuln: Dict) -> bool:
    from engine.npm import validate_target
    try:
        if vuln.get("ecosystem", "").lower() == "npm":
            owners = validate_target(vuln["package"], vuln["target_version"])
        else:
            from engine.adapters import validate_target as validate_polyglot
            owners = validate_polyglot(vuln)
        from engine.scanner import scan_source
        payload = scan_source()
        for result in payload["results"]:
            for package in result.get("packages", []):
                info = package.get("package", {})
                if info.get("name") == vuln["package"] and info.get("ecosystem", "").lower() == vuln.get("ecosystem", "").lower() and package.get("vulnerabilities"):
                    raise ValueError("Target package still has reported vulnerabilities")
        vuln["verified_owners"] = owners
        vuln["post_update_scan"] = "no_reported_target_vulnerabilities"
        return True
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"[ERROR] Target verification failed: {exc}")
        return False


def execute_remediation(profile: Dict, vuln: Dict, plan: MigrationPlan, verified_gate: str, baseline_dur: float = 30.0, verbose: bool = False, verification_timeout: Optional[int] = None) -> bool:
    """Apply one update and require the selected verification command to pass."""
    pkg = vuln["package"]
    target_ver = vuln["target_version"]
    
    try:
        bump_cmd_str, target_cwd = resolve_package_bump_command(vuln, profile)
    except (ValueError, OSError) as exc:
        print(f"[ERROR] Update refused: {exc}")
        return False
    sys.stdout.write(f"        • Manifest: updating {pkg} to {target_ver}...")
    sys.stdout.flush()
    install = _run_with_heartbeat(bump_cmd_str, "Install updated dependency", cwd=target_cwd, timeout=300)
    if verbose:
        print((install.stdout or b"").decode("utf-8", errors="replace"))
        print((install.stderr or b"").decode("utf-8", errors="replace"))
    if install.returncode != 0:
        print("[ERROR] Dependency install failed; restoring tracked edits.")
        subprocess.run(["git", "restore", "--worktree", "--", "."], check=True)
        return False

    # Dynamic verification timeout based on baseline duration
    gate_timeout = verification_timeout if verification_timeout is not None else max(90, int(baseline_dur * 2.5))

    # Step A: Verified gate check with live heartbeat ticker
    initial_test = _run_with_heartbeat(verified_gate, f"Verification: {verified_gate}", timeout=gate_timeout)
    if initial_test.returncode == 0:
        return verify_updated_target(vuln)
    elif initial_test.returncode == 124:
        print(f"        ✖ Verification gate timed out (>{gate_timeout}s). Tracked edits restored; inspect any generated files.")
        subprocess.run(["git", "restore", "--worktree", "--", "."], check=True)
        return False

    # Display a concise failure trace.
    err_preview = (initial_test.stderr or initial_test.stdout or b'').decode('utf-8', errors='replace').strip()
    first_lines = [l for l in err_preview.splitlines() if l.strip()][:3]
    if first_lines:
        print("          Verification failure trace:")
        for line in first_lines:
            print(f"            {line[:120]}")

    # Optional model-assisted source repair.
    error_output = (initial_test.stdout or b'').decode('utf-8', errors='replace') + '\n' + (initial_test.stderr or b'').decode('utf-8', errors='replace')
    print(f"        • Healing: interface discrepancies detected, repairing...")

    target_files = _extract_failing_files(error_output)
    if not target_files:
        print("          No direct source file candidates isolated from error trace.")
    else:
        print(f"          Repairing candidate(s): {', '.join(target_files[:3])}")

    tiers = resolve_engine_tiers()

    # Tier 1 Healing
    if tiers["tier1"] and target_files:
        for tf in target_files[:3]:
            _attempt_file_patch(tf, error_output, vuln, plan, tiers["tier1"], tiers["provider"])

        t1_check = _run_with_heartbeat(verified_gate, "Verification (tier 1 repair)", timeout=gate_timeout)
        if t1_check.returncode == 0:
            return verify_updated_target(vuln)
        else:
            error_output = (t1_check.stdout or b'').decode('utf-8', errors='replace') + '\n' + (t1_check.stderr or b'').decode('utf-8', errors='replace')

    # Tier 2 Healing Escalation
    if tiers["tier2"] and tiers["tier2"] != tiers["tier1"] and target_files:
        for tf in target_files[:3]:
            _attempt_file_patch(tf, error_output, vuln, plan, tiers["tier2"], tiers["provider"])

        t2_check = _run_with_heartbeat(verified_gate, "Verification (tier 2 repair)", timeout=gate_timeout)
        if t2_check.returncode == 0:
            return verify_updated_target(vuln)

    # Deterministic rollback on failure
    subprocess.run(["git", "restore", "--worktree", "--", "."], check=True)
    return False

def _format_duration(seconds: float) -> str:
    """Formats seconds into readable human-friendly time string."""
    s = int(round(seconds))
    mins, secs = divmod(s, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    elif mins > 0:
        return f"{mins}m {secs}s"
    else:
        return f"{secs}s"

def _render_preflight(packages: List[Dict]):
    """Renders clean, enterprise-grade remediation inventory (Snyk / GitHub CLI style)."""
    print(f"\nDiscovered {len(packages)} security remediation(s):\n")
    print(f"  {'SUBPROJECT':<24} {'PACKAGE':<28} {'CURRENT':<12} {'TARGET':<12} {'ADVISORY'}")
    print("  " + "-" * 88)
    for p in packages:
        subproj = p.get('subproject') or '(root)'
        pkg_name = (p['package'][:25] + '...') if len(p['package']) > 28 else p['package']
        cur_v = p.get('current_version') or 'current'
        tgt_v = p['target_version']
        cve = p.get('cve_id') or 'SECURITY'
        print(f"  {subproj:<24} {pkg_name:<28} {cur_v:<12} → {tgt_v:<10} {cve}")
    print("  " + "-" * 88 + "\n")

def _render_summary_table(results: List[Dict], total_elapsed: float, skip_pr: bool):
    """Renders enterprise executive summary (Snyk / Renovate style)."""
    success_count = sum(1 for r in results if r["status"] == "SUCCESS")
    failed_count = len(results) - success_count

    print("-" * 64)
    print("Remediation Summary:")
    print(f"  ✔ {success_count} package(s) passed the configured verification command")
    if failed_count > 0:
        print(f"  ✖ {failed_count} package(s) rolled back due to test failure")
    print(f"  ⏱ Total duration: {_format_duration(total_elapsed)}")
    mode_str = "Isolated worktree retained for review (--skip-pr)" if skip_pr else "Pull Requests published to GitHub"
    print(f"  Mode: {mode_str}")
    print("-" * 64 + "\n")

def create_pull_request(vuln: Dict, plan: MigrationPlan, skip_pr: bool = False, skip_hosted_ci: bool = False) -> bool:
    """Publish only after every Git operation succeeds; never force push."""
    from engine.diagnostics import redact, record_command
    if skip_pr:
        return True
    pkg, target = vuln["package"], vuln["target_version"]
    branch = "greenpr/" + re.sub(r"[^A-Za-z0-9._-]", "-", f"{pkg}-{target}") + f"-{time.time_ns()}"
    body = (f"GreenPR updated `{pkg}` to `{target}`.\n\n"
            f"Verification command: `{vuln.get('verified_gate', 'unknown')}`\n"
            "Result: exit 0. This covers only the configured command; review the diff before merging.\n")
    body = redact(body)
    if skip_hosted_ci:
        body += "\nA [skip ci] marker requests skipping hosted push/pull_request workflows; all configured verification gates above ran locally. Required GitHub checks may remain pending and merge protections remain in effect. This does not bypass required checks or merge the PR.\n"
    title = redact(f"fix(deps): update {pkg} to {target}")
    def publish(command):
        started = time.monotonic()
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            evidence = record_command(command, exc, phase="publish", duration_seconds=time.monotonic() - started)
            vuln["publication_error"] = evidence['stderr'] or evidence['summary']
            raise
        record_command(command, result, phase="publish", duration_seconds=time.monotonic() - started)
        return result
    try:
        publish(["git", "switch", "-c", branch])
        vuln["branch"] = branch
        publish(["git", "add", "--update"])
        publish(["git", "commit", "-m", title + (" [skip ci]" if skip_hosted_ci else "")])
        publish(["git", "push", "-u", "origin", branch])
        with tempfile.TemporaryDirectory(prefix="greenpr-pr-") as tmp:
            body_path = os.path.join(tmp, "body.md")
            with open(body_path, "w", encoding="utf-8") as f:
                f.write(body)
            created = publish(["gh", "pr", "create", "--head", branch, "--title", title,
                               "--body-file", body_path])
            url = redact(created.stdout).strip()
            if not re.fullmatch(r"https://[^\s/]+/[^\s/]+/[^\s/]+/pull/[0-9]+", url):
                vuln["publication_error"] = "GitHub CLI returned no verifiable pull request URL; inspect the remote before retrying."
                print(f"[ERROR] {vuln['publication_error']}")
                return False
            vuln["pull_request_url"] = url
        return True
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"[ERROR] PR delivery failed; local changes preserved: {redact(str(exc))}")
        return False


# ==============================================================================
# Main Orchestrator Execution
# ==============================================================================

def _run_current_checkout(config=None):
    parser = argparse.ArgumentParser(description="GreenPR: dependency updates checked against your verification command")
    parser.add_argument("--test-cmd", action="append", default=None, help="Required verification command; repeat to require multiple commands")
    parser.add_argument("--project", default=".", help="Project directory relative to the repository root")
    parser.add_argument("--doctor", action="store_true", help="Check configured test prerequisites without modifying the repository")
    parser.add_argument("--package", type=str, default=None, help="Target specific package (skips full scan)")
    parser.add_argument("--target-version", type=str, default=None, help="Target version for specific package")
    parser.add_argument("--limit", type=int, default=1, help="One package per run; repeat after reviewing the result")
    parser.add_argument("--skip-pr", action="store_true", help="Retain a separate review worktree with patch and result receipt without publishing a PR")
    parser.add_argument("--skip-hosted-ci", action="store_true", help="Add [skip ci] to the published commit after all local gates pass; required GitHub checks remain pending")
    parser.add_argument("--dry-run", "--scan-only", dest="dry_run", action="store_true", help="Scan and display discovered vulnerabilities without modifying files")
    parser.add_argument("--enable-model-repair", action="store_true", help="Allow source and error traces to be sent to a configured model provider")
    parser.add_argument("--commercial", action="store_true", help="Verify a paid license for this GitHub origin before execution")
    parser.add_argument("--verbose", action="store_true", help="Display full verbose package manager output")
    parser.add_argument("--ecosystem", type=str, default=None, choices=["npm", "pypi", "go", "crates.io", "maven", "nuget", "all"], help="Filter by ecosystem (npm, pypi, go, crates.io, all)")
    args = parser.parse_args()
    if config:
        args.test_cmd = list(config.gates) + (args.test_cmd or [])
    os.environ["GREENPR_ENABLE_MODEL_REPAIR"] = "1" if args.enable_model_repair else "0"

    if bool(args.package) != bool(args.target_version):
        parser.error("--package and --target-version must be supplied together")
    if args.limit != 1:
        parser.error("This release supports one remediation per run (--limit 1)")
    if not args.dry_run:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True)
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if status.returncode or status.stdout.strip() or root.returncode:
            parser.error("Run from a clean Git repository root; commit or move existing changes first")

    profiles = discover_repository_profiles(".")
    if not profiles:
        print("[ERROR] GreenPR: Unsupported project environment.")
        sys.exit(1)

    if args.ecosystem and args.ecosystem.lower() != "all":
        requested = args.ecosystem.lower()
        matching = [p for p in LANGUAGE_PROFILES.values() if requested in p["ecosystems"] and p["detect"](".")]
        if not matching and not args.dry_run:
            parser.error("Selected ecosystem is not at this project root; use --project for its directory")
        if matching:
            profiles.insert(0, matching[0])
    if args.ecosystem == "all" and not args.dry_run:
        parser.error("Select one ecosystem/project for remediation; --ecosystem all is scan-only")
    primary_profile = profiles[0]
    root_profile = get_profile_for_dir(".")
    if not args.dry_run and not args.test_cmd and root_profile and primary_profile["ecosystems"] != root_profile["ecosystems"]:
        parser.error("Mixed manifests at one root require explicit --test-cmd gates for the selected ecosystem")
    if len(profiles) > 1:
        lang_names = ", ".join([p["name"].split(" ")[0] for p in profiles])
        profile_label = f"Polyglot Monorepo ({lang_names})"
    else:
        profile_label = primary_profile["name"]

    print("GreenPR Dependency Remediation Engine v1.0")
    print(f"Target:         {os.getcwd()}")
    print(f"Active Profile: {profile_label}")

    # Step 0: Autonomous Baseline Sanity Gate Check (Mandatory Pre-flight)
    verified_gate, baseline_dur = ("", 0.0) if args.dry_run else probe_and_select_verification_gate(".", custom_cmd=" && ".join(args.test_cmd) if args.test_cmd else None, timeout=config.timeout_seconds if config else 300)
    if not verified_gate and not args.dry_run:
        print("\n[ERROR] GreenPR: Cannot proceed. No passing verification gates found on clean repository.")
        print("The selected verification command must pass before updates begin.")
        print("Please resolve baseline test/typecheck failures on your branch before running remediation.\n")
        sys.exit(1)

    if not args.dry_run:
        after_baseline = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, check=True)
        if after_baseline.stdout.strip():
            parser.error("Baseline modified the checkout; review its changes before continuing")

    # Determine target ecosystems
    if args.ecosystem:
        target_ecos = None if args.ecosystem.lower() == "all" else [args.ecosystem.lower()]
    else:
        target_ecos = None if args.dry_run else primary_profile.get("ecosystems")

    if args.package and args.target_version:
        if target_ecos and target_ecos[0].lower() != "npm":
            owner_dir, subproj, is_direct, dep_type, decl_ver = ".", ".", True, None, None
        else:
            owner_dir, subproj, is_direct, dep_type, decl_ver = locate_package_owner(args.package, ".")
        vulnerabilities = [{
            "package": args.package,
            "target_version": args.target_version,
            "cve_id": "DIRECT-REMEDIATION",
            "current_version": decl_ver or "current",
            "working_dir": owner_dir,
            "subproject": subproj,
            "is_direct": is_direct,
            "dep_type": dep_type,
            "ecosystem": (target_ecos[0] if target_ecos else "npm")
        }]
    else:
        try:
            vulnerabilities = run_vulnerability_radar(active_ecosystems=target_ecos)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}")
            sys.exit(1)

    if not vulnerabilities:
        print(f"\n✔ No actionable updates found in this scan. This is not a security certification.\n")
        sys.exit(0)

    # De-duplicate packages per (subproject, package)
    seen_keys = set()
    deduped = []
    for v in vulnerabilities:
        key = (v.get("subproject", "(root)"), v["package"])
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(v)

    if args.limit:
        deduped = deduped[:args.limit]

    total_pkgs = len(deduped)
    _render_preflight(deduped)

    if args.dry_run:
        print(f"\n✔ Scan complete ({total_pkgs} vulnerabilities discovered). Dry run mode active: no files modified.\n")
        sys.exit(0)

    start_total_time = time.time()
    results = []

    print(f"Applying remediations ({total_pkgs} total):\n")
    for idx, vuln in enumerate(deduped, 1):
        pkg = vuln["package"]
        cur = vuln.get("current_version", "current")
        tgt = vuln["target_version"]
        subproj = vuln.get("subproject", "(root)")

        print(f"  [{idx}/{total_pkgs}] {subproj} : {pkg} ({cur} → {tgt})")

        pkg_start = time.time()
        plan = extract_migration_plan(pkg, cur, tgt, vuln.get("summary", ""))
        success = execute_remediation(primary_profile, vuln, plan, verified_gate, baseline_dur=baseline_dur, verbose=args.verbose, verification_timeout=config.timeout_seconds if config else None)
        pkg_dur = time.time() - pkg_start

        if success:
            vuln["verified_gate"] = verified_gate
            if not create_pull_request(vuln, plan, skip_pr=args.skip_pr, skip_hosted_ci=args.skip_hosted_ci):
                sys.exit(1)
            print(f"        ✔ Configured verification passed ({pkg_dur:.1f}s)\n")
            results.append({
                "package": pkg,
                "project": subproj,
                "from": cur,
                "to": tgt,
                "status": "SUCCESS",
                "verified_owners": vuln.get("verified_owners", []),
                "post_update_scan": vuln.get("post_update_scan"),
                "pull_request_url": vuln.get("pull_request_url"),
                "branch": vuln.get("branch"),
                "duration": pkg_dur
            })
        else:
            print(f"        ✖ Remediation failed. Inspect the retained worktree and result receipt ({pkg_dur:.1f}s)\n")
            results.append({
                "package": pkg,
                "project": subproj,
                "from": cur,
                "to": tgt,
                "status": "FAILED",
                "duration": pkg_dur
            })

    total_time = time.time() - start_total_time
    _render_summary_table(results, total_time, args.skip_pr)
    if any(r["status"] != "SUCCESS" for r in results):
        sys.exit(1)
    from engine.diagnostics import redact
    return {"updates": results, "verification_command": redact(verified_gate), "baseline_seconds": baseline_dur}

def main():
    from engine.runtime import isolated_checkout
    from engine.onboarding import load_config, doctor, run_setup, run_cleanup
    from engine.diagnostics import redact
    from pathlib import Path
    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        return _run_current_checkout()
    selection = argparse.ArgumentParser(add_help=False)
    selection.add_argument("--project", default=None)
    selection.add_argument("--ecosystem", default=None)
    selected, _ = selection.parse_known_args()
    original = Path.cwd().resolve()
    try:
        config = load_config(original)
        if config and selected.project is not None and selected.project != config.project:
            raise ValueError("--project conflicts with .greenpr.toml; use the configured project")
        selected.project = selected.project or (config.project if config else ".")
        if "--doctor" in sys.argv[1:]:
            if not config:
                print("[ERROR] Add a reviewed .greenpr.toml with the project and required gates first.")
                raise SystemExit(2)
            findings = doctor(config, original)
            for finding in findings:
                print(f"[{finding.code}] {finding.message}")
            if not findings:
                print("Configured prerequisites are available. Baseline tests still must pass before remediation.")
            raise SystemExit(1 if findings else 0)
    except (ValueError, OSError) as exc:
        print(f"[ERROR] {redact(str(exc))}", file=sys.stderr)
        raise SystemExit(2) from exc
    project = (original / selected.project).resolve()
    if not project.is_relative_to(original) or not project.is_dir():
        print("[ERROR] Project must stay inside the repository", file=sys.stderr)
        raise SystemExit(2)
    if "--commercial" in sys.argv[1:]:
        from engine.license import validate_commercial_license
        try:
            validate_commercial_license()
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    if any(flag in sys.argv[1:] for flag in ("--scan-only", "--dry-run")):
        try:
            os.chdir(project)
            return _run_current_checkout()
        finally:
            os.chdir(original)
    original_environment = dict(os.environ)
    try:
        with isolated_checkout() as receipt:
            from engine.adapters import prepare_baseline
            from dataclasses import replace
            candidate_config = load_config(receipt["worktree"])
            comparable = replace(candidate_config, source_root=original) if candidate_config else None
            if comparable != config:
                raise RuntimeError("Onboarding config differs from the committed candidate; commit the reviewed config before running")
            if candidate_config:
                import hashlib
                committed_config_bytes = (Path(receipt["worktree"]) / ".greenpr.toml").read_bytes()
                if committed_config_bytes != (original / ".greenpr.toml").read_bytes():
                    raise RuntimeError("Onboarding config changed during candidate creation")
                receipt["config_sha256"] = hashlib.sha256(committed_config_bytes).hexdigest()
            project = (Path.cwd() / selected.project).resolve()
            if not project.is_relative_to(Path.cwd().resolve()) or not project.is_dir():
                raise RuntimeError("Project must stay inside the repository")
            os.chdir(project)
            os.environ["GREENPR_RUN_ID"] = receipt["run_id"]
            if config:
                os.environ.update(config.environment)
            try:
                command = prepare_baseline(Path(receipt["worktree"]).parent, selected.ecosystem)
                if command:
                    install = _run_with_heartbeat(command, "Install baseline dependencies", timeout=config.timeout_seconds if config else 300)
                    if install.returncode:
                        raise RuntimeError("Baseline dependency install failed; inspect the retained diagnostic log")
                if config:
                    run_setup(config, receipt["worktree"], _run_with_heartbeat)
                    findings = doctor(config, receipt["worktree"])
                    if findings:
                        raise RuntimeError("; ".join(f.message for f in findings))
                result = _run_current_checkout(config)
                if isinstance(result, dict):
                    receipt.update(result)
                return result
            finally:
                if config:
                    cleanup_findings = run_cleanup(config, receipt["worktree"], _run_with_heartbeat)
                    receipt["cleanup_findings"] = [f.message for f in cleanup_findings]
                    for finding in cleanup_findings:
                        print(f"[cleanup] {finding.message}")
                    active_error = sys.exc_info()[1]
                    if cleanup_findings and (active_error is None or
                            isinstance(active_error, SystemExit) and active_error.code in (None, 0)):
                        raise RuntimeError("Configured cleanup failed; inspect retained diagnostics")
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {redact(str(exc))}", file=sys.stderr)
        raise SystemExit(2) from exc
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


if __name__ == "__main__":
    main()
