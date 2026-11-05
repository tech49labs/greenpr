import io
import json
from pathlib import Path
import urllib.error

import pytest

import gemini_provider as gemini
import greenpr_core as core
from test_core import repo, finding, fixture_plan


def test_credentials_are_google_only_and_empty_values_ignored(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_ACCESS_TOKEN", "GREENPR_API_KEY", "GREENPR_MODEL", "GREENPR_FLASH_MODEL", "GREENPR_PRO_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(core.GreenPRError):
        gemini.GeminiConfig.from_environment()
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-fixture-not-real")
    config = gemini.GeminiConfig.from_environment()
    assert config.auth == "api_key" and "AIza" not in repr(config)
    monkeypatch.setenv("GEMINI_API_KEY", "ya29.fixture-not-real")
    assert gemini.GeminiConfig.from_environment().auth == "oauth"


def test_models_are_separate_validated_and_do_not_use_moving_alias(monkeypatch):
    client = gemini.GeminiClient(gemini.GeminiConfig("fixture"))
    monkeypatch.setattr(client, "available_models", lambda: {"gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-flash-latest"})
    result = client.resolve_models()
    assert result["stage3_flash"] == "gemini-3.8-flash"
    assert result["stage4_pro"] == "gemini-3.1-pro-preview"
    client.config.flash = "unavailable"
    with pytest.raises(core.GreenPRError, match="not available"):
        client.resolve_models()


def test_legacy_flash_override_does_not_overwrite_pro(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    monkeypatch.setenv("GREENPR_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("GREENPR_FLASH_MODEL", raising=False)
    monkeypatch.delenv("GREENPR_PRO_MODEL", raising=False)
    config = gemini.GeminiConfig.from_environment()
    assert config.flash == "gemini-2.5-flash" and config.pro is None


def test_model_listing_pages_and_generation_capability(monkeypatch):
    client = gemini.GeminiClient(gemini.GeminiConfig("fixture"))
    results = iter([{"models": [{"name": "models/flash", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "page-two"},
                    {"models": [{"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]}])
    monkeypatch.setattr(client, "request", lambda path: next(results))
    assert client.available_models() == {"flash"}


@pytest.mark.parametrize("status,phrase", [(400, "invalid request"), (401, "expired"), (403, "permission"), (404, "unavailable"), (429, "quota")])
def test_provider_errors_explicit_without_leaking_body(monkeypatch, status, phrase):
    def fail(*a, **k):
        raise urllib.error.HTTPError("https://example.invalid", status, "raw credential SECRET", {}, io.BytesIO(b'{"error":{"message":"SECRET"}}'))
    monkeypatch.setattr(gemini.urllib.request, "urlopen", fail)
    with pytest.raises(core.GreenPRError, match=phrase) as caught:
        gemini.GeminiClient(gemini.GeminiConfig("SECRET")).available_models()
    assert "SECRET" not in str(caught.value)


def test_oauth_uses_bearer_not_api_key_header(monkeypatch):
    captured = []
    def response(req, **kw):
        captured.append(req)
        return io.BytesIO(b'{"models":[]}')
    monkeypatch.setattr(gemini.urllib.request, "urlopen", response)
    gemini.GeminiClient(gemini.GeminiConfig("fixture-token", "oauth")).available_models()
    assert captured[0].get_header("Authorization") == "Bearer fixture-token"
    assert not captured[0].has_header("X-goog-api-key")


def test_subproject_candidates_exclude_tests_config_and_other_root_files(repo):
    sub = repo / "apps/api"
    sub.mkdir(parents=True)
    for name in ("main.py", "test_main.py", "settings.py"):
        (sub / name).write_text("old = 1\n")
    (repo / "main.py").write_text("wrong root file")
    core.git(repo, "add", ".")
    assert gemini.source_candidates(repo, sub, "main.py:1 test_main.py:2 settings.py:3 ../other.py:4") == ["apps/api/main.py"]


def test_exact_patch_preserves_entire_file_and_rejects_invalid_batch(tmp_path):
    source = "header\nold = 1\n" + "# unchanged tail\n" * 1500
    (tmp_path / "main.py").write_text(source)
    original = {"main.py": source}
    with pytest.raises(core.GreenPRError):
        gemini.apply_edits(tmp_path, original, {"edits": [
            {"path": "main.py", "old_text": "old = 1", "new_text": "new = 1"},
            {"path": "../outside.py", "old_text": "x", "new_text": "y"}]})
    assert (tmp_path / "main.py").read_text() == source
    gemini.apply_edits(tmp_path, original, {"edits": [{"path": "main.py", "old_text": "old = 1", "new_text": "new = 1"}]})
    assert (tmp_path / "main.py").read_text() == source.replace("old = 1", "new = 1")


@pytest.mark.parametrize("first_repair_passes,expected", [(True, [3]), (False, [3, 4])])
def test_pro_only_follows_failed_flash_verification(repo, finding, monkeypatch, first_repair_passes, expected):
    monkeypatch.setattr(core, "plan_update", fixture_plan)
    calls = []
    failure = [core.CommandResult(["fixture"], 1, "main.py: error")]
    results = iter([[], failure, []] if first_repair_passes else [[], failure, failure, []])
    monkeypatch.setattr(core, "run_tests", lambda *a, **k: next(results))
    monkeypatch.setattr(core, "scan", lambda *a: core.Scan([{**finding, "current_version": "1.2.0"}], [], {}))
    def healer(root, cwd, failed, item, stage, evidence):
        calls.append(stage)
    record = core.run_remediation(repo, finding, core.Scan([finding], [finding], {}), core.repository_state(repo),
        scanner="fixture", timeout=10, tests=[], skip_pr=True, healer=healer)
    assert record["status"] == "local_verified", record
    assert calls == expected


def test_timeout_never_triggers_paid_healing(repo, finding, monkeypatch):
    monkeypatch.setattr(core, "plan_update", fixture_plan)
    results = iter([[], [core.CommandResult(["fixture"], 124)]])
    monkeypatch.setattr(core, "run_tests", lambda *a, **k: next(results))
    calls = []
    record = core.run_remediation(repo, finding, core.Scan([], [], {}), core.repository_state(repo), scanner="fixture",
        timeout=10, tests=[], skip_pr=True, healer=lambda *a: calls.append(a))
    assert record["status"] == "failed" and calls == []
