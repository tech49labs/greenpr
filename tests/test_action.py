import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_action_keeps_custom_command_in_one_argument():
    bash = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe") if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).exists():
        pytest.skip("Git Bash/bash unavailable")
    script = Path(__file__).resolve().parents[1] / "scripts/action-run.sh"
    command = 'npm test -- --runInBand; echo "literal adapter input"'
    env = {**os.environ, "SCRIPT": script.as_posix(), "GREENPR_ACTION_PATH": "/project with spaces",
           "GREENPR_TEST_CMD": command, "GREENPR_DRY_RUN": "false", "GREENPR_ENABLE_HEALING": "false",
           "RUNNER_TEMP": "/tmp", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"}
    result = subprocess.run([bash, "-c", 'python() { printf "<%s>\\n" "$@"; }; export -f python; bash "$SCRIPT"'], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["</project with spaces/remediate.py>", "<--report>",
                                         "</tmp/greenpr-report-1-1.json>", "<--test-cmd>", "<" + command + ">"]
