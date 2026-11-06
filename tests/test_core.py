import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import greenpr_core as core
import greenpr_cli as cli


def advisory(fix="1.2.0", events=None, ecosystem="npm", kind="SEMVER", id="TEST-1"):
    return {"id": id, "affected": [{"package": {"name": "demo", "ecosystem": ecosystem},
            "ranges": [{"type": kind, "events": events or [{"introduced": "0"}, {"fixed": fix}]}]}]}


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    core.git(path, "init", "-b", "main")
    core.git(path, "config", "user.name", "Test")
    core.git(path, "config", "user.email", "test@example.invalid")
    (path / "package.json").write_text(json.dumps({"dependencies": {"demo": "1.0.0"},
                                                   "scripts": {"test": "test-runner", "typecheck": "tsc"}}))
    (path / "package-lock.json").write_text("{}")
    (path / "valuable.txt").write_text("original")
    core.git(path, "add", ".")
    core.git(path, "commit", "-m", "fixture")
    return path


@pytest.fixture
def finding():
    return {"package": "demo", "current_version": "1.0.0", "target_version": "1.2.0",
            "ecosystem": "npm", "working_dir": ".", "manifest_path": "package-lock.json",
            "advisory_ids": ["TEST-1"], "advisories": [advisory()]}


def test_all_advisories_and_maintained_branches():
    assert core.select_target_version("demo", "1.0.0", [advisory("1.1.0"), advisory("1.2.0")]) == "1.2.0"
    branches = [{"introduced": "0"}, {"fixed": "1.2.0"}, {"introduced": "2.0.0"}, {"fixed": "2.1.0"}]
    assert core.select_target_version("demo", "1.0.0", [advisory(events=branches)]) == "1.2.0"
    assert core.select_target_version("demo", "2.0.5", [advisory(events=branches)]) == "2.1.0"


@pytest.mark.parametrize("events", [[{"introduced": "0"}], [{"introduced": "0"}, {"last_affected": "9.0.0"}],
                                   [{"fixed": "1.2.0"}], [{"introduced": "0"}, {"fixed": "1.2.0-beta.1"}]])
def test_uncertain_or_unfixed_records_not_automated(events):
    assert core.select_target_version("demo", "1.0.0", [advisory(), advisory(events=events)]) is None


def test_git_ranges_unknown_versions_and_downgrades_refused():
    assert core.select_target_version("demo", "1.0.0", [advisory(kind="GIT")]) is None
    assert core.select_target_version("demo", "unknown", [advisory()]) is None
    assert core.select_target_version("demo", "2.0.0", [advisory()]) is None
    assert core.select_target_version("demo", "1.0.0", [advisory("1.2.0rc1", ecosystem="PyPI", kind="ECOSYSTEM")], "pypi") is None


@pytest.mark.parametrize("returncode,output", [(127, ""), (128, ""), (0, "not-json"), (0, "{}"), (0, '{"results":[]}')])
def test_scan_errors_never_clean(repo, monkeypatch, returncode, output):
    monkeypatch.setattr(core, "run", lambda *a, **k: core.CommandResult([], returncode, output))
    with pytest.raises(core.GreenPRError):
        core.scan(repo)


def scan_payload(path, vulnerabilities):
    return json.dumps({"results": [{"source": {"path": str(path)}, "packages": [{
        "package": {"name": "demo", "ecosystem": "npm", "version": "1.0.0"},
        "vulnerabilities": vulnerabilities}]}]})


def test_scan_keeps_unfixed_and_validates_paths(repo, monkeypatch):
    payload = scan_payload(repo / "package-lock.json", [advisory(events=[{"introduced": "0"}])])
    monkeypatch.setattr(core, "run", lambda *a, **k: core.CommandResult([], 1, payload))
    assert core.scan(repo).findings[0]["target_version"] is None
    payload = scan_payload(repo.parent / "outside", [])
    with pytest.raises(core.GreenPRError):
        core.scan(repo)


def test_rescan_must_observe_target_and_no_new_advisories(finding):
    before = core.Scan([finding], [finding], {})
    updated = {**finding, "current_version": "1.2.0"}
    core.verify_rescan(before, core.Scan([updated], [], {}), finding)
    for after in [core.Scan([], [], {}), core.Scan([finding], [], {}),
                  core.Scan([updated], [finding], {}),
                  core.Scan([updated], [{**finding, "package": "other", "advisory_ids": ["NEW"]}], {})]:
        with pytest.raises(core.GreenPRError):
            core.verify_rescan(before, after, finding)


def test_verbose_success_does_not_deadlock(tmp_path):
    result = core.run([sys.executable, "-c", "import sys; sys.stdout.write('x'*3000000); sys.stderr.write('y'*3000000)"], cwd=tmp_path, timeout=10, max_output=4096)
    assert result.returncode == 0
    assert result.truncated and len(result.stdout) == len(result.stderr) == 4096


def test_timeout_stops_child_before_late_write(tmp_path):
    code = "import time,pathlib; time.sleep(2); pathlib.Path('escaped').write_text('bad')"
    script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(code) + "]); time.sleep(20)"
    result = core.run([sys.executable, "-c", script], cwd=tmp_path, timeout=0.3)
    assert result.returncode == 124
    time.sleep(2.1)
    assert not (tmp_path / "escaped").exists()


def test_runtime_category_and_both_checks_preserved(repo, finding, tmp_path):
    plan = core.plan_update(repo, finding, tmp_path)
    manifest = json.loads(plan.files[repo / "package.json"])
    assert manifest["dependencies"]["demo"] == "1.2.0"
    assert "devDependencies" not in manifest
    assert plan.tests == [["npm", "run", "typecheck"], ["npm", "run", "test"]]
    assert all("--save-dev" not in c for c in plan.commands)


def test_transitive_update_preserves_direct_dependencies(repo, finding, tmp_path):
    (repo / "package.json").write_text('{"dependencies":{},"scripts":{"test":"test"}}')
    plan = core.plan_update(repo, finding, tmp_path)
    updated = json.loads(plan.files[repo / "package.json"])
    assert updated["dependencies"] == {}
    assert updated["overrides"] == {"demo": "1.2.0"}
    (repo / "package.json").write_text('{"overrides":{"other":"1.0.0"},"scripts":{"test":"test"}}')
    with pytest.raises(core.GreenPRError, match="override"):
        core.plan_update(repo, finding, tmp_path)


def test_python_update_persists_pin_and_uses_private_venv(tmp_path, finding):
    (tmp_path / "requirements.txt").write_text("# pin\ndemo==1.0.0\npytest==8.4.2\n")
    f = {**finding, "ecosystem": "pypi", "manifest_path": "requirements.txt"}
    plan = core.plan_update(tmp_path, f, tmp_path / "temp")
    assert "demo==1.2.0" in plan.files[tmp_path / "requirements.txt"]
    assert "venv" in plan.commands[0][0]
    assert plan.setup[0][1:3] == ["-m", "venv"]
    assert (tmp_path / "requirements.txt").read_text().startswith("# pin\ndemo==1.0.0")


@pytest.mark.parametrize("text", ["demo>=1.0\n", "demo==1.0 --hash=sha256:abc\n", "-r other.txt\n", "demo==1.0; python_version>'3'\n"])
def test_complex_python_requirements_fail_closed(tmp_path, finding, text):
    (tmp_path / "requirements.txt").write_text(text)
    with pytest.raises(core.GreenPRError):
        core.plan_update(tmp_path, {**finding, "ecosystem": "pypi", "manifest_path": "requirements.txt"}, tmp_path / "temp")


def test_worktree_cleanup_preserves_all_existing_work(repo):
    (repo / "valuable.txt").write_text("unstaged user work")
    (repo / "staged.txt").write_text("staged user work")
    core.git(repo, "add", "staged.txt")
    (repo / "untracked.txt").write_text("untracked user work")
    state = core.repository_state(repo)
    with pytest.raises(RuntimeError):
        with core.isolated_checkout(repo, state["head"]) as (work, _):
            (work / "valuable.txt").write_text("broken repair")
            (work / "junk").write_text("temporary")
            raise RuntimeError("test failure")
    assert core.repository_state(repo) == state
    assert (repo / "valuable.txt").read_text() == "unstaged user work"
    assert (repo / "untracked.txt").read_text() == "untracked user work"
    assert len(core.git(repo, "worktree", "list", "--porcelain").split("worktree ")) == 2


def fixture_plan(work, f, temp, tests):
    manifest = work / "package.json"
    data = json.loads(manifest.read_text())
    data["dependencies"]["demo"] = f["target_version"]
    check = [sys.executable, "-c", "import json; assert json.load(open('package.json'))['dependencies']['demo'] in ['1.0.0','1.2.0']"]
    return core.UpdatePlan(work, {manifest: json.dumps(data)}, [], [check])


def test_real_git_end_to_end_local_delivery_preserves_dirty_checkout(repo, finding, monkeypatch):
    (repo / "valuable.txt").write_text("keep me")
    (repo / "untracked.txt").write_text("keep too")
    state = core.repository_state(repo)
    before = core.Scan([finding], [finding], {})
    monkeypatch.setattr(core, "plan_update", fixture_plan)
    monkeypatch.setattr(core, "scan", lambda work, *a: core.Scan([{**finding, "current_version": "1.2.0"}], [], {}))
    record = core.run_remediation(repo, finding, before, state, scanner="fixture", timeout=10, tests=[], skip_pr=True)
    assert record["status"] == "local_verified", record
    assert core.repository_state(repo) == state
    committed = json.loads(core.git(repo, "show", record["commit"] + ":package.json"))
    assert committed["dependencies"]["demo"] == "1.2.0"
    assert core.git(repo, "rev-parse", record["commit"] + "^") == state["head"]
    assert [c["stage"] for c in record["checks"]] == ["baseline", "verification", "rescan"]


def test_failed_install_does_not_leave_user_changes_or_false_success(repo, finding, monkeypatch):
    state = core.repository_state(repo)
    def failing_plan(work, f, temp, tests):
        plan = fixture_plan(work, f, temp, tests)
        plan.commands = [[sys.executable, "-c", "raise SystemExit(7)"]]
        return plan
    monkeypatch.setattr(core, "plan_update", failing_plan)
    record = core.run_remediation(repo, finding, core.Scan([], [], {}), state, scanner="fixture", timeout=10, tests=[], skip_pr=True)
    assert record["status"] == "failed" and "setup/update failed" in record["error"]
    assert core.repository_state(repo) == state


def test_pr_failure_is_not_success_and_preserves_branch_identity(repo, finding, monkeypatch):
    commands = []
    def fake_git(root, *args):
        commands.append(args)
        return "package.json" if args[0] == "diff" else "abc123"
    monkeypatch.setattr(core, "git", fake_git)
    monkeypatch.setattr(core, "run", lambda *a, **k: core.CommandResult([], 1))
    result = core.deliver(repo, "main", finding, [], skip_pr=False)
    assert result["status"] == "pushed_pr_pending" and result["branch"].startswith("greenpr/")
    assert "--force" not in str(commands)


def test_cli_scan_error_reports_nonzero(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "preflight", lambda *a, **k: core.repository_state(repo))
    monkeypatch.setattr(cli, "scan", lambda *a, **k: (_ for _ in ()).throw(core.GreenPRError("scan failed")))
    report = tmp_path / "report.json"
    assert cli.main(["--repo", str(repo), "--skip-pr", "--report", str(report)]) == 1
    assert json.loads(report.read_text())["status"] == "failed"


def test_dry_run_reports_unfixed_without_installing(repo, finding, tmp_path, monkeypatch):
    finding["target_version"] = None
    monkeypatch.setattr(cli, "preflight", lambda *a, **k: core.repository_state(repo))
    monkeypatch.setattr(cli, "scan", lambda *a, **k: core.Scan([finding], [finding], {}))
    report = tmp_path / "report.json"
    assert cli.main(["--repo", str(repo), "--dry-run", "--report", str(report)]) == 2
    data = json.loads(report.read_text())
    assert data["findings"][0]["target_version"] is None and data["results"][0]["status"] == "blocked"


def test_report_cannot_overwrite_user_file(repo, tmp_path):
    report = tmp_path / "existing.json"
    report.write_text("precious")
    with pytest.raises(SystemExit):
        cli.main(["--repo", str(repo), "--report", str(report)])
    assert report.read_text() == "precious"


def test_evidence_does_not_capture_raw_process_output():
    result = core.CommandResult(["test"], 1, "secret stdout", "secret stderr")
    assert "secret" not in json.dumps(result.evidence())
