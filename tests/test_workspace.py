import json
from pathlib import Path

import pytest

import greenpr_core as core
import greenpr_cli as cli
from test_core import repo, finding


def workspace(repo, *, duplicate=False):
    root = {"workspaces": ["packages/*"], "scripts": {"test:ci": "root-ci", "typecheck": "root-types"}}
    (repo / "package.json").write_text(json.dumps(root))
    member = repo / "packages/app"
    member.mkdir(parents=True)
    (member / "package.json").write_text(json.dumps({"name": "app", "dependencies": {"demo": "1.0.0"}, "scripts": {"test:unit": "unit"}}))
    if duplicate:
        other = repo / "packages/other"
        other.mkdir()
        (other / "package.json").write_text('{"dependencies":{"demo":"1.0.0"}}')
    return member


def test_workspace_updates_unique_owner_and_runs_root_plus_owner_checks(repo, finding, tmp_path):
    member = workspace(repo)
    plan = core.plan_update(repo, finding, tmp_path)
    assert set(plan.files) == {member / "package.json"}
    assert json.loads(plan.files[member / "package.json"])["dependencies"] == {"demo": "1.2.0"}
    assert plan.cwd == repo
    assert plan.tests == [["npm", "run", "typecheck"], ["npm", "run", "test:ci"], ["npm", "run", "test:unit"]]
    assert plan.test_directories == [repo, repo, member]


def test_workspace_ambiguous_ownership_requires_manual_review(repo, finding, tmp_path):
    workspace(repo, duplicate=True)
    with pytest.raises(core.GreenPRError, match="Ambiguous"):
        core.plan_update(repo, finding, tmp_path)


def test_workspace_does_not_select_unrelated_nested_project(repo, finding, tmp_path):
    workspace(repo)
    unrelated = repo / "examples/unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "package.json").write_text('{"dependencies":{"demo":"99.0.0"}}')
    plan = core.plan_update(repo, finding, tmp_path)
    assert unrelated / "package.json" not in plan.files


def test_pnpm_workspace_configuration_and_exclusions(repo, finding, tmp_path, monkeypatch):
    member = workspace(repo, duplicate=True)
    (repo / "package-lock.json").unlink()
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    (repo / "pnpm-workspace.yaml").write_text("# preserve comment\npackages:\n  - 'packages/*'\n  - '!packages/other'\n")
    monkeypatch.setattr(core.shutil, "which", lambda name: "/bin/pnpm")
    plan = core.plan_update(repo, finding, tmp_path)
    assert set(plan.files) == {member / "package.json"}
    assert plan.commands[0][0] == "pnpm"
    assert (repo / "pnpm-workspace.yaml").read_text().startswith("# preserve comment")


def test_pnpm_transitive_override_preserves_workspace_text(repo, finding, tmp_path, monkeypatch):
    (repo / "package.json").write_text('{"scripts":{"test":"test"}}')
    (repo / "package-lock.json").unlink()
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    config = repo / "pnpm-workspace.yaml"
    original = "# keep this\npackages: []\n"
    config.write_text(original)
    monkeypatch.setattr(core.shutil, "which", lambda name: "/bin/pnpm")
    plan = core.plan_update(repo, finding, tmp_path)
    assert plan.files[config].startswith(original)
    assert '"demo": "1.2.0"' in plan.files[config]
    assert repo / "package.json" not in plan.files


@pytest.mark.parametrize("content", ["packages: []\npackages: []\n", "packages: ['../escape']\n", "packages: ['{apps,libs}/*']\n"])
def test_ambiguous_or_unsafe_workspace_configuration_rejected(repo, finding, tmp_path, content):
    (repo / "pnpm-workspace.yaml").write_text(content)
    with pytest.raises(core.GreenPRError):
        core.plan_update(repo, finding, tmp_path)


def test_failed_required_gate_does_not_get_replaced_by_build(tmp_path):
    commands = core.node_checks({"scripts": {"test": "failing", "typecheck": "passing", "build": "passing"}}, "npm")
    assert commands == [["npm", "run", "typecheck"], ["npm", "run", "test"]]
    assert core.node_checks({"scripts": {"build": "build-only"}}, "npm") == [["npm", "run", "build"]]


def test_scan_only_is_dry_run_alias():
    assert cli.parser().parse_args(["--scan-only"]).dry_run


@pytest.mark.parametrize("declaration", ["workspace:*", "file:../local", "git+https://example.invalid/repo.git", "npm:other@1.0.0"])
def test_workspace_does_not_replace_local_or_forked_dependency(repo, finding, tmp_path, declaration):
    member = workspace(repo)
    (member / "package.json").write_text(json.dumps({"dependencies": {"demo": declaration}}))
    with pytest.raises(core.GreenPRError, match="Local or aliased"):
        core.plan_update(repo, finding, tmp_path)


def test_verification_runs_each_gate_in_its_recorded_directory(tmp_path, monkeypatch):
    member = tmp_path / "member"
    member.mkdir()
    calls = []
    def fake(command, *, cwd, **kwargs):
        calls.append(cwd)
        return core.CommandResult(command, 0, cwd=str(cwd))
    monkeypatch.setattr(core, "run", fake)
    plan = core.UpdatePlan(tmp_path, {}, [], [["test-root"], ["test-member"]], test_directories=[tmp_path, member])
    evidence = []
    assert core.run_tests(plan, 10, evidence) == []
    assert calls == [tmp_path, member]
    assert evidence[1]["working_directory"] == str(member)
