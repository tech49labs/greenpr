"""Local, redacted command evidence and actionable failure classification."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, quote_plus

_ACTIVE = ContextVar('greenpr_diagnostics', default=None)
_SECRET_NAME = re.compile(r'(secret|token|password|passwd|credential|api[_-]?key|private[_-]?key|authorization|cookie)', re.I)


def redact(value, environ=None):
    """Redact known secret values plus common credential syntaxes before persistence."""
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    text = str(value or '')
    env = os.environ if environ is None else environ
    secrets = set()
    for key, secret in env.items():
        if _SECRET_NAME.search(key) and secret:
            secrets.update((secret, quote(secret, safe=''), quote_plus(secret)))
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED PRIVATE KEY]', text, flags=re.S)
    text = re.sub(r'(?i)(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'(?im)((?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)([?&](?:[^\s=&]*(?:token|secret|password|credential|api[_-]?key|signature)[^\s=&]*)=)[^\s&#]+', r'\1[REDACTED]', text)
    text = re.sub(r'''(?i)((?:["']?)[\w.-]*(?:secret|token|password|passwd|credential|api[_-]?key|private[_-]?key)[\w.-]*(?:["']?)\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}&]+)''', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(--[\w-]*(?:token|secret|password|api-key|credential)[\w-]*\s+)\S+', r'\1[REDACTED]', text)
    return text


def classify_failure(stdout, stderr, returncode, phase='', timed_out=False):
    output = str(stdout or '') + '\n' + str(stderr or '')
    if timed_out:
        return 'timeout', 'Command exceeded its time limit. Inspect the retained output and adjust the test or timeout before retrying.'
    if returncode == 0:
        return 'passed', 'Command completed successfully.'
    if re.search(r'UndefinedValueError|ImproperlyConfigured|environment variable.*(?:missing|required|not set)|(?:SECRET_KEY|DATABASE_URL).*not found|KeyError:\s*[\'"](?:SECRET_KEY|DATABASE_URL)', output, re.I):
        return 'environment_configuration', 'Required application configuration is missing. Supply test-only environment settings in the original environment, then rerun; do not commit secrets.'
    if re.search(r'ModuleNotFoundError|ImportError:|command not found|is not recognized|No module named|No such file or directory', output, re.I):
        return 'environment_dependencies', 'A required dependency, executable, or file is unavailable. Complete repository setup and verify the selected interpreter and command.'
    if re.search(r'AssertionError|assert .*==|FAILED .*::|failures?=\d*[1-9]|[1-9]\d* failed', output, re.I):
        return 'test_failure', 'Tests reported failures. Review the retained assertion output and fix the baseline before attempting a dependency update.' if phase == 'baseline' else 'Tests reported failures. Review the retained assertion output before accepting the update.'
    return 'command_failure', 'Command failed. Review the retained stdout/stderr to identify the cause; a nonzero exit alone does not establish a test assertion failure.'


@contextmanager
def diagnostic_session(receipt, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    receipt.setdefault('commands', [])
    token = _ACTIVE.set((receipt, directory))
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def record_command(command, result, *, phase, duration_seconds):
    """Return safe output and append metadata/log to the active isolated run.

    Accept CompletedProcess, TimeoutExpired, or an execution exception. Raw
    process output must not be printed or placed in a PR by the caller.
    """
    timed_out = isinstance(result, subprocess.TimeoutExpired)
    stdout = redact(getattr(result, 'stdout', None) or getattr(result, 'output', None))
    stderr = redact(getattr(result, 'stderr', None))
    if isinstance(result, Exception) and not timed_out and not stderr:
        stderr = redact(str(result))
    code = getattr(result, 'returncode', None)
    classification, summary = classify_failure(stdout, stderr, code, phase, timed_out)
    entry = {'phase': redact(phase), 'command': redact(command if isinstance(command, str) else ' '.join(map(str, command))),
             'exit_code': code, 'elapsed_seconds': round(max(0, duration_seconds), 3),
             'timed_out': timed_out, 'classification': classification, 'summary': summary,
             'recorded_at': datetime.now(timezone.utc).isoformat()}
    active = _ACTIVE.get()
    if active:
        receipt, directory = active
        path = directory / f"{len(receipt['commands']) + 1:04d}.json"
        entry['log_path'] = str(path)
        with path.open('x', encoding='utf-8') as file:
            json.dump({**entry, 'stdout': stdout, 'stderr': stderr}, file, indent=2)
            file.write('\n')
        receipt['commands'].append(entry.copy())
        if code != 0:
            receipt['last_failure'] = entry.copy()
    return {**entry, 'stdout': stdout, 'stderr': stderr}
