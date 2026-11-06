import pytest

import greenpr_core as core
from test_core import repo, finding, fixture_plan


def other_package(finding, manifest="other/requirements.txt"):
    return {**finding, "package": "other", "manifest_path": manifest,
            "advisory_ids": ["OTHER-ADVISORY"], "current_version": "1.0.0"}


@pytest.mark.parametrize("manifest", ["other/requirements.txt", "package-lock.json"])
@pytest.mark.parametrize("vulnerable", [True, False])
def test_rescan_cannot_silently_drop_inventory(finding, manifest, vulnerable):
    other = other_package(finding, manifest)
    before = core.Scan([finding, other], [finding, other] if vulnerable else [finding], {})
    after = core.Scan([{**finding, "current_version": "1.2.0"}], [], {})
    with pytest.raises(core.GreenPRError, match="coverage"):
        core.verify_rescan(before, after, finding)


def test_unchanged_vulnerable_version_cannot_lose_its_advisory(finding):
    other = other_package(finding)
    before = core.Scan([finding, other], [finding, other], {})
    after = core.Scan([{**finding, "current_version": "1.2.0"}, other], [], {})
    with pytest.raises(core.GreenPRError, match="unchanged"):
        core.verify_rescan(before, after, finding)


def test_rescan_can_confirm_other_package_upgrade_and_new_inventory(finding):
    other = other_package(finding)
    before = core.Scan([finding, other], [finding, other], {})
    after = core.Scan([{**finding, "current_version": "1.2.0"},
                       {**other, "current_version": "2.0.0"},
                       {**other, "package": "new-dependency"}], [], {})
    core.verify_rescan(before, after, finding)


def test_old_vulnerable_target_version_cannot_hide_beside_new_version(finding):
    before = core.Scan([finding], [finding], {})
    after = core.Scan([finding, {**finding, "current_version": "1.2.0"}], [], {})
    with pytest.raises(core.GreenPRError, match="unchanged"):
        core.verify_rescan(before, after, finding)


def test_lost_rescan_coverage_prevents_delivery_and_preserves_checkout(repo, finding, monkeypatch):
    other = other_package(finding)
    before = core.Scan([finding, other], [finding, other], {})
    state = core.repository_state(repo)
    monkeypatch.setattr(core, "plan_update", fixture_plan)
    monkeypatch.setattr(core, "scan", lambda *a: core.Scan([{**finding, "current_version": "1.2.0"}], [], {}))
    def forbidden(*a, **k):
        pytest.fail("Delivery must not run after loss of scanner coverage")
    monkeypatch.setattr(core, "deliver", forbidden)
    result = core.run_remediation(repo, finding, before, state, scanner="fixture", timeout=10, tests=[], skip_pr=True)
    assert result["status"] == "failed"
    assert "coverage" in result["error"]
    assert core.repository_state(repo) == state
