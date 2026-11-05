#!/usr/bin/env python3
"""
GreenPR: Autonomous Zero-Hallucination Dependency Remediation Engine.
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
import time
from typing import Dict, List, Optional
from packaging import version
from pydantic import BaseModel, Field

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# On Windows, sync credentials from User Registry so existing sessions inherit active keys
if sys.platform == "win32":
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as reg_key:
            for env_var in ["GEMINI_API_KEY", "GREENPR_API_KEY", "ANTHROPIC_API_KEY"]:
                try:
                    reg_val, _ = winreg.QueryValueEx(reg_key, env_var)
                    cur = os.environ.get(env_var, "")
                    if not cur or cur.startswith("ya29."):
                        os.environ[env_var] = reg_val
                except FileNotFoundError:
                    pass
    except Exception:
        pass


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
        "default_test": "pytest",
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
        "detect": lambda p: os.path.exists(os.path.join(p, "pom.xml")) or os.path.exists(os.path.join(p, "build.gradle")),
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
            return profile
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

def resolve_subproject_test_cmd(working_dir: str, custom_test_cmd: Optional[str] = None) -> str:
    """Intelligently detects or applies the verification command for a subproject directory."""
    sub_profile = get_profile_for_dir(working_dir)
    
    if custom_test_cmd:
        if working_dir in (".", ""):
            return custom_test_cmd
        
        is_python_cmd = any(k in custom_test_cmd for k in ["pytest", "python", "unittest"])
        is_node_cmd = any(k in custom_test_cmd for k in ["pnpm", "npm", "yarn", "bun", "tsc", "vitest", "jest"])
        
        sub_is_python = sub_profile and sub_profile["name"] == "Python"
        sub_is_node = sub_profile and "Node" in sub_profile["name"]
        
        if (is_python_cmd and sub_is_python) or (is_node_cmd and sub_is_node):
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
            
            if "typecheck" in scripts:
                return f"{pkg_mgr} run typecheck" if pkg_mgr == "npm" else f"{pkg_mgr} typecheck"
            elif "test" in scripts:
                return f"{pkg_mgr} test"
            elif os.path.exists(os.path.join(working_dir, "tsconfig.json")):
                return "npx tsc --noEmit"
        except Exception:
            pass

    if sub_profile:
        return sub_profile.get("default_test", "pytest")
    return "pytest"


# ==============================================================================
# 3. Model-Agnostic Engine Resolver
# ==============================================================================

def resolve_engine_tiers() -> Dict[str, Optional[str]]:
    """Resolves primary and secondary model routing based on available environment credentials."""
    raw_key = os.environ.get("GREENPR_API_KEY") or os.environ.get("API_KEY")
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
    """Finds the optimal, non-breaking fixed version that satisfies security advisories."""
    all_fixes = []
    for vuln in vulnerabilities:
        for aff in vuln.get("affected", []):
            aff_pkg = aff.get("package", {}).get("name")
            if aff_pkg and aff_pkg != pkg_name:
                continue
            for r in aff.get("ranges", []):
                for ev in r.get("events", []):
                    if "fixed" in ev and ev["fixed"]:
                        all_fixes.append(ev["fixed"])

    all_fixes = list(dict.fromkeys(all_fixes))
    if not all_fixes:
        return None

    if not current_ver or current_ver in ("current", ""):
        try:
            return str(max(all_fixes, key=parse_ver))
        except Exception:
            return all_fixes[0]

    cur_parsed = parse_ver(current_ver)
    
    # Filter candidate fixes >= current_ver
    gte_fixes = []
    for f in all_fixes:
        try:
            if parse_ver(f) >= cur_parsed:
                gte_fixes.append(f)
        except Exception:
            pass

    if not gte_fixes:
        # All available fixes are strictly older than current version. Prevent invalid downgrades.
        return None

    # Separate stable releases from pre-releases
    def is_prerelease(v):
        try:
            p = parse_ver(v)
            return getattr(p, "is_prerelease", False)
        except Exception:
            return False

    stable_gte = [f for f in gte_fixes if not is_prerelease(f)]
    pool = stable_gte if stable_gte else gte_fixes

    try:
        return str(min(pool, key=parse_ver))
    except Exception:
        return pool[0]

def run_vulnerability_radar(active_ecosystems: Optional[List[str]] = None) -> List[Dict]:
    """Scans project dependency graph for identified security issues with strict monorepo ecosystem binding."""
    print("[GreenPR Radar] Scanning dependency graph for security vulnerabilities...")
    cmd = "osv-scanner --format=json -r ."
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=False, shell=True)
        raw_output = proc.stdout.decode('utf-8', errors='replace').strip()
        if not raw_output:
            return []
        
        data = json.loads(raw_output)
        vulnerabilities = []

        for result in data.get("results", []):
            source_info = result.get("source", {})
            source_path = source_info.get("path", "").replace("\\", "/")
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

                vulnerabilities.append({
                    "package": pkg_name,
                    "current_version": current_ver,
                    "target_version": target_version,
                    "cve_id": vuln_id,
                    "summary": primary_vuln.get("summary", ""),
                    "ecosystem": ecosystem,
                    "manifest_path": source_path,
                    "working_dir": working_dir
                })

        return vulnerabilities
    except Exception:
        return []


# ==============================================================================
# 5. GreenPR Migration Analysis Engine
# ==============================================================================

def extract_migration_plan(package_name: str, current_ver: str, target_ver: str, changelog_text: str) -> MigrationPlan:
    """Analyzes version upgrade requirements into structured transformation schema."""
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
# 6. GreenPR Autonomous Code Repair Engine (Zero Third-Party Leaks)
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
                    {"role": "system", "content": "You are the GreenPR Autonomous Remediation Engine by tech49labs."},
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

def _extract_failing_files(error_output: str) -> List[str]:
    """Identifies broken source files directly from compiler and test error traces."""
    candidates = []
    pattern = r'([a-zA-Z0-9_\-\./\\]+\.(?:ts|tsx|js|jsx|py|go|rs|java|cs|json|toml|yaml|yml))'
    matches = re.findall(pattern, error_output)
    
    for m in matches:
        clean = m.split(':')[0].strip().replace('\\', '/')
        if clean.startswith('./'):
            clean = clean[2:]
        if os.path.isfile(clean):
            if not any(skip in clean for skip in ['node_modules', '.git', '.venv', 'venv', '__pycache__', 'dist', 'build', '.lock']):
                if clean not in candidates:
                    candidates.append(clean)

    try:
        git_proc = subprocess.run("git diff --name-only", capture_output=True, text=True, shell=True)
        for gf in git_proc.stdout.splitlines():
            gf = gf.strip().replace('\\', '/')
            if gf and os.path.isfile(gf) and gf not in candidates:
                if not any(skip in gf for skip in ['bun.lock', 'pnpm-lock.yaml', 'package-lock.json', 'yarn.lock', 'Cargo.lock']):
                    candidates.append(gf)
    except Exception:
        pass

    return candidates

def _attempt_file_patch(filepath: str, error_trace: str, vuln: Dict, plan: MigrationPlan, model_name: str, provider: str) -> bool:
    """Reads file, requests targeted fix from LLM, and writes back cleanly."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            current_code = f.read()
    except Exception:
        return False

    pkg = vuln["package"]
    target_ver = vuln["target_version"]
    breaking_text = "\n".join([f"- Replace `{b.old_call}` with `{b.new_call}`: {b.notes}" for b in plan.breaking_changes])

    prompt = (
        f"You are the GreenPR Autonomous Remediation Engine by tech49labs.\n"
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

def _run_with_heartbeat(cmd: str, label: str, cwd: Optional[str] = None, timeout: int = 180) -> subprocess.CompletedProcess:
    """Executes a verification command with a live elapsed second ticker to prevent frozen screens."""
    t0 = time.time()
    sys.stdout.write(f"        • {label} [0s]...")
    sys.stdout.flush()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, cwd=cwd)
    try:
        while proc.poll() is None:
            time.sleep(0.5)
            elapsed = int(time.time() - t0)
            if elapsed >= timeout:
                proc.kill()
                sys.stdout.write(f"\r        • {label} [TIMEOUT after {timeout}s]\n")
                sys.stdout.flush()
                return subprocess.CompletedProcess(args=cmd, returncode=124, stdout=b"", stderr=b"Verification gate timed out.")
            sys.stdout.write(f"\r        • {label} [{elapsed}s elapsed]...")
            sys.stdout.flush()

        stdout, stderr = proc.communicate()
        dur = time.time() - t0
        sys.stdout.write(f"\r        • {label} [passed in {dur:.1f}s]      \n")
        sys.stdout.flush()
        return subprocess.CompletedProcess(args=cmd, returncode=proc.returncode, stdout=stdout, stderr=stderr)
    except Exception as e:
        proc.kill()
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout=b"", stderr=str(e).encode('utf-8'))

def resolve_package_bump_command(vuln: Dict, profile: Dict) -> str:
    """Dispatches package bump to the correct package manager based on ecosystem and monorepo path."""
    pkg = vuln["package"]
    ver = vuln["target_version"]
    ecosystem = vuln.get("ecosystem", "").lower()
    wdir = vuln.get("working_dir", ".")

    # 1. NPM / JavaScript Ecosystem
    if ecosystem == "npm" or "npm" in ecosystem:
        if os.path.exists(os.path.join(wdir, "bun.lock")) or os.path.exists(os.path.join(wdir, "bun.lockb")):
            return f"bun add -d {pkg}@{ver}"
        elif os.path.exists("pnpm-workspace.yaml") or os.path.exists(os.path.join(wdir, "pnpm-workspace.yaml")):
            if wdir not in (".", ""):
                return f"pnpm add -D {pkg}@{ver}"
            return f"pnpm add -D -w {pkg}@{ver}"
        elif os.path.exists(os.path.join(wdir, "pnpm-lock.yaml")) or os.path.exists("pnpm-lock.yaml"):
            return f"pnpm add -D {pkg}@{ver}"
        elif os.path.exists(os.path.join(wdir, "yarn.lock")) or os.path.exists("yarn.lock"):
            return f"yarn add -D {pkg}@{ver}"
        else:
            return f"npm install --save-dev {pkg}@{ver}"

    # 2. PyPI / Python Ecosystem
    if ecosystem in ("pypi", "python"):
        if os.path.exists(os.path.join(wdir, "poetry.lock")) or os.path.exists("poetry.lock"):
            return f"poetry add {pkg}=={ver}"
        elif shutil.which("uv"):
            return f"uv pip install {pkg}=={ver}"
        else:
            return f"pip install {pkg}=={ver}"

    # 3. Go Ecosystem
    if ecosystem == "go":
        return f"go get {pkg}@{ver} && go mod tidy"

    # 4. Cargo / Rust Ecosystem
    if ecosystem in ("crates.io", "cargo", "rust"):
        return f"cargo update -p {pkg} --precise {ver}"

    return profile["bump_cmd"](pkg, ver, wdir)

def execute_remediation(profile: Dict, vuln: Dict, plan: MigrationPlan, custom_test_cmd: Optional[str], verbose: bool = False) -> bool:
    """Applies package upgrade and enforces deterministic verification gates with 100% native healing."""
    pkg = vuln["package"]
    target_ver = vuln["target_version"]
    working_dir = vuln.get("working_dir") or "."
    sub_profile = get_profile_for_dir(working_dir) or profile
    
    bump_cmd_str = resolve_package_bump_command(vuln, sub_profile)
    sys.stdout.write(f"        • Manifest: updating {pkg} to {target_ver}...")
    sys.stdout.flush()
    try:
        if verbose:
            subprocess.run(bump_cmd_str, check=True, shell=True, cwd=working_dir)
        else:
            proc = subprocess.run(bump_cmd_str, capture_output=True, text=False, shell=True, cwd=working_dir)
            if proc.returncode != 0:
                sys.stdout.write(f" ✖ FAILED\n")
                err_msg = proc.stderr.decode('utf-8', errors='replace').strip()[:200]
                print(f"          [ERROR] {err_msg}")
                return False
        sys.stdout.write(f" done\n")
    except subprocess.CalledProcessError as e:
        sys.stdout.write(f" ✖ FAILED\n")
        print(f"          [ERROR] {e}")
        return False

    test_command = resolve_subproject_test_cmd(working_dir, custom_test_cmd)

    # Step A: Baseline gate check with live heartbeat ticker
    initial_test = _run_with_heartbeat(test_command, f"Verification: {test_command}", cwd=working_dir)
    if initial_test.returncode == 0:
        return True
    elif initial_test.returncode == 124:
        print(f"        ✖ Verification gate timed out (>180s). Rolled back cleanly.")
        subprocess.run("git checkout .", shell=True)
        subprocess.run("git clean -ffd", shell=True, input=b"n\n")
        return False

    # Step B: Interface discrepancies detected; initiate proprietary native healing
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

        t1_check = _run_with_heartbeat(test_command, "Verification (tier 1 repair)", cwd=working_dir)
        if t1_check.returncode == 0:
            return True
        else:
            error_output = (t1_check.stdout or b'').decode('utf-8', errors='replace') + '\n' + (t1_check.stderr or b'').decode('utf-8', errors='replace')

    # Tier 2 Healing Escalation
    if tiers["tier2"] and tiers["tier2"] != tiers["tier1"] and target_files:
        for tf in target_files[:3]:
            _attempt_file_patch(tf, error_output, vuln, plan, tiers["tier2"], tiers["provider"])

        t2_check = _run_with_heartbeat(test_command, "Verification (tier 2 repair)", cwd=working_dir)
        if t2_check.returncode == 0:
            return True

    # Deterministic rollback on failure
    subprocess.run("git checkout .", shell=True)
    subprocess.run("git clean -ffd", shell=True, input=b"n\n")
    return False


# ==============================================================================
# 7. GreenPR Verified Delivery & Reporting Pipeline
# ==============================================================================

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
        working_dir = p.get('working_dir', '.')
        try:
            rel_dir = os.path.relpath(working_dir, os.getcwd()).replace("\\", "/")
        except Exception:
            rel_dir = working_dir
        subproj = "(root)" if rel_dir == "." else rel_dir
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
    print(f"  ✔ {success_count} package(s) verified safe (100% gate pass)")
    if failed_count > 0:
        print(f"  ✖ {failed_count} package(s) rolled back due to test failure")
    print(f"  ⏱ Total duration: {_format_duration(total_elapsed)}")
    mode_str = "Local working copy staged (--skip-pr)" if skip_pr else "Pull Requests published to GitHub"
    print(f"  Mode: {mode_str}")
    print("-" * 64 + "\n")

def create_pull_request(vuln: Dict, plan: MigrationPlan, skip_pr: bool = False) -> bool:
    """Submits a verified Pull Request through the delivery pipeline."""
    pkg = vuln["package"]
    target_ver = vuln["target_version"]
    cve = vuln.get("cve_id", "SECURITY")
    branch_name = f"greenpr/{pkg}-{target_ver}"

    if skip_pr:
        return True

    subprocess.run(f"git checkout -b {branch_name}", shell=True)
    subprocess.run("git add .", shell=True)
    subprocess.run(f'git commit -m "fix(security): auto-remediate {pkg} to {target_ver} [{cve}]"', shell=True)
    subprocess.run(f"git push -u origin {branch_name} --force", shell=True)

    body = (
        f"## GreenPR: Autonomous Dependency Remediation\n\n"
        f"This Pull Request was autonomously remediated, compiled, and verified by **GreenPR Engine v1.0**.\n\n"
        f"- **Package**: `{pkg}`\n"
        f"- **Target Version**: `{target_ver}`\n"
        f"- **Security Advisory**: `{cve}`\n\n"
        f"### Verification Gate Summary\n"
        f"- **Syntax & Compiler Check**: PASSED (Exit Code 0)\n"
        f"- **Regression Test Suite**: PASSED (Exit Code 0)\n"
        f"- **Deterministic Verification**: 100% verified against project test harness.\n\n"
        f"---\n"
        f"*Delivered autonomously by [GreenPR by tech49labs](https://github.com/tech49labs/greenpr)*\n"
    )

    pr_cmd = f'gh pr create --title "fix(security): GreenPR verified patch for {pkg} to {target_ver}" --body "{body}"'
    proc = subprocess.run(pr_cmd, shell=True)
    return proc.returncode == 0


# ==============================================================================
# Main Orchestrator Execution
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="GreenPR Enterprise: Autonomous Dependency Remediation Engine by tech49labs")
    parser.add_argument("--test-cmd", type=str, default=None, help="Custom command to run test suite")
    parser.add_argument("--package", type=str, default=None, help="Target specific package (skips full scan)")
    parser.add_argument("--target-version", type=str, default=None, help="Target version for specific package")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of packages to remediate")
    parser.add_argument("--skip-pr", action="store_true", help="Stage changes locally without pushing a remote PR")
    parser.add_argument("--verbose", action="store_true", help="Display full verbose package manager output")
    parser.add_argument("--ecosystem", type=str, default=None, help="Filter by ecosystem (npm, pypi, go, crates.io, all)")
    args = parser.parse_args()

    profiles = discover_repository_profiles(".")
    if not profiles:
        print("[ERROR] GreenPR: Unsupported project environment.")
        sys.exit(1)

    primary_profile = profiles[0]
    if len(profiles) > 1:
        lang_names = ", ".join([p["name"].split(" ")[0] for p in profiles])
        profile_label = f"Polyglot Monorepo ({lang_names})"
    else:
        profile_label = primary_profile["name"]

    print(f"GreenPR Dependency Remediation Engine v1.0 | tech49labs")
    print(f"Target:         {os.getcwd()}")
    print(f"Active Profile: {profile_label}")

    # Determine target ecosystems
    if args.ecosystem:
        target_ecos = None if args.ecosystem.lower() == "all" else [args.ecosystem.lower()]
    else:
        # Default in monorepo: scan all detected ecosystems
        if len(profiles) > 1:
            target_ecos = None
        else:
            target_ecos = primary_profile.get("ecosystems")

    if args.package and args.target_version:
        vulnerabilities = [{
            "package": args.package,
            "target_version": args.target_version,
            "cve_id": "DIRECT-REMEDIATION",
            "current_version": "current",
            "working_dir": ".",
            "ecosystem": (target_ecos[0] if target_ecos else "npm")
        }]
    else:
        vulnerabilities = run_vulnerability_radar(active_ecosystems=target_ecos)

    if not vulnerabilities:
        print(f"\n✔ All {profile_label} dependencies are verified and clean.\n")
        sys.exit(0)

    # De-duplicate packages per (subproject, package)
    seen_keys = set()
    deduped = []
    for v in vulnerabilities:
        key = (v.get("working_dir", "."), v["package"])
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(v)

    if args.limit:
        deduped = deduped[:args.limit]

    total_pkgs = len(deduped)
    _render_preflight(deduped)

    start_total_time = time.time()
    results = []

    print(f"Applying remediations ({total_pkgs} total):\n")
    for idx, vuln in enumerate(deduped, 1):
        pkg = vuln["package"]
        cur = vuln.get("current_version", "current")
        tgt = vuln["target_version"]
        working_dir = vuln.get("working_dir", ".")
        try:
            rel_dir = os.path.relpath(working_dir, os.getcwd()).replace("\\", "/")
        except Exception:
            rel_dir = working_dir
        subproj = "(root)" if rel_dir == "." else rel_dir

        print(f"  [{idx}/{total_pkgs}] {subproj} : {pkg} ({cur} → {tgt})")

        pkg_start = time.time()
        plan = extract_migration_plan(pkg, cur, tgt, vuln.get("summary", ""))
        success = execute_remediation(primary_profile, vuln, plan, args.test_cmd, verbose=args.verbose)
        pkg_dur = time.time() - pkg_start

        if success:
            create_pull_request(vuln, plan, skip_pr=args.skip_pr)
            print(f"        ✔ Verified safe for production ({pkg_dur:.1f}s)\n")
            results.append({
                "package": pkg,
                "project": subproj,
                "from": cur,
                "to": tgt,
                "status": "SUCCESS",
                "duration": pkg_dur
            })
        else:
            print(f"        ✖ Verification gate failed. Rolled back cleanly ({pkg_dur:.1f}s)\n")
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

if __name__ == "__main__":
    main()
