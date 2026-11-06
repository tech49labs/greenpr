"""Explicit, reviewable project onboarding; never reads or copies dotenv files."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import shutil
import socket
import tomllib


@dataclass(frozen=True)
class ProjectConfig:
    source_root: Path
    project: str
    gates: tuple[str, ...]
    setup: tuple[str, ...]
    environment: dict[str, str]
    required_env: tuple[str, ...]
    executables: tuple[str, ...]
    services: tuple[tuple[str, int], ...]
    timeout_seconds: int = 300
    cleanup: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


def _strings(data, key, required=False):
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() or '\x00' in v for v in value):
        raise ValueError(f'{key} must be an array of nonempty strings')
    if required and not value:
        raise ValueError(f'{key} must specify every required verification command')
    return tuple(value)


def project_path(root, project):
    root = Path(root).resolve()
    path = (root / project).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise ValueError('Configured project must be an existing directory inside the checkout')
    return path


def load_config(repo_root):
    root = Path(repo_root).resolve()
    path = root / '.greenpr.toml'
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Onboarding config must be a regular file of at most 64 KiB')
    data = tomllib.loads(path.read_text(encoding='utf-8'))
    allowed = {'version', 'project', 'gates', 'setup', 'environment', 'required_env', 'executables', 'services', 'timeout_seconds', 'cleanup'}
    if set(data) - allowed or type(data.get('version')) is not int or data.get('version') != 1:
        raise ValueError('Unknown onboarding setting or unsupported version (expected 1)')
    project = data.get('project')
    if not isinstance(project, str) or not project or Path(project).is_absolute():
        raise ValueError('project must explicitly name a relative directory')
    project_path(root, project)
    timeout = data.get('timeout_seconds', 300)
    if type(timeout) is not int or not 1 <= timeout <= 7200:
        raise ValueError('timeout_seconds must be an integer between 1 and 7200')
    environment = data.get('environment', {})
    if not isinstance(environment, dict):
        raise ValueError('environment must be a table of non-secret test defaults')
    forbidden = {'PATH', 'PYTHONPATH', 'PYTHONHOME', 'HOME', 'USERPROFILE', 'SHELL', 'BASH_ENV', 'ENV', 'COMSPEC', 'LD_PRELOAD', 'NODE_OPTIONS', 'GIT_CONFIG', 'GIT_CONFIG_COUNT', 'GIT_DIR', 'GIT_WORK_TREE'}
    for name, value in environment.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or name.upper() in forbidden or name.upper() == 'GREENPR_RUN_ID':
            raise ValueError('Unsafe test environment variable name')
        if not isinstance(value, str) or '\x00' in value:
            raise ValueError('Test environment values must be strings without NUL bytes')
    required_env = _strings(data, 'required_env')
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) for key in required_env):
        raise ValueError('required_env must contain variable names only')
    services = []
    for entry in _strings(data, 'services'):
        host, separator, port = entry.rpartition(':')
        if host not in ('127.0.0.1', 'localhost', '[::1]') or not separator or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError('services must name loopback TCP endpoints, e.g. 127.0.0.1:5432')
        services.append((host.strip('[]'), int(port)))
    return ProjectConfig(root, project, _strings(data, 'gates', True), _strings(data, 'setup'), dict(environment), required_env, _strings(data, 'executables'), tuple(services), timeout, _strings(data, 'cleanup'))


def doctor(config, repo_root=None):
    """Read-only checks. Findings never include environment values or command output."""
    findings = []
    try:
        project_path(repo_root or config.source_root, config.project)
    except ValueError:
        findings.append(Finding('project', 'Configured project directory is missing or outside the checkout'))
    effective = dict(os.environ)
    effective.update(config.environment)
    for name in config.required_env:
        if not effective.get(name):
            findings.append(Finding('environment', f'Missing required test environment variable: {name}'))
    for executable in config.executables:
        if not shutil.which(executable):
            findings.append(Finding('executable', f'Missing executable: {executable}'))
    for host, port in config.services:
        try:
            with socket.create_connection((host, port), timeout=1):
                pass
        except OSError:
            findings.append(Finding('service', f'Test service unavailable at {host}:{port}'))
    return findings


def _isolated_project(config, worktree_root):
    root = Path(worktree_root).resolve()
    if root == config.source_root or not (root / '.git').is_file():
        raise ValueError('Configured setup requires a separate linked Git worktree')
    if Path.cwd().resolve() != project_path(root, config.project):
        raise ValueError('Configured setup must run from the isolated project directory')
    return root


def run_setup(config, worktree_root, runner):
    """Run explicit setup only in a separate linked worktree. Caller scopes env."""
    root = _isolated_project(config, worktree_root)
    for number, command in enumerate(config.setup, 1):
        if project_path(root, config.project) != Path.cwd().resolve():
            raise ValueError('Configured project changed during setup')
        result = runner(command, f'Configured test setup {number}', timeout=config.timeout_seconds)
        if result.returncode:
            raise RuntimeError(f'Configured test setup {number} failed; verification was not weakened')


def run_cleanup(config, worktree_root, runner):
    """Attempt every explicit cleanup; report failures without hiding the run error.

    Caller invokes this in finally while cwd and GREENPR_RUN_ID remain scoped.
    No cleanup commands are supplied or inferred by GreenPR.
    """
    failures = []
    for number, command in enumerate(config.cleanup, 1):
        _isolated_project(config, worktree_root)
        try:
            result = runner(command, f'Configured test cleanup {number}', timeout=config.timeout_seconds)
            if result.returncode:
                failures.append(Finding('cleanup', f'Configured cleanup {number} failed'))
        except Exception:
            failures.append(Finding('cleanup', f'Configured cleanup {number} could not complete'))
    return failures
