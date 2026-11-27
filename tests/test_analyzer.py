import json

import pytest

from src.analyzer import (
    Analysis,
    GitHubModelsAnalyzer,
    NoopAnalyzer,
    _parse_analyses,
    _strip_code_fence,
    create_analyzer,
)
from src.collector import Event
from src.config_loader import Settings


def ev(repo="a/b", kind="new_release"):
    return Event(kind=kind, repo=repo, title="t", url="u", detail="d", stars=1)


def settings(provider="auto"):
    return Settings(
        llm_provider=provider,
        github_models_model="m-gh",
        gemini_model="m-gem",
        max_items_per_run=30,
        trending_days=1,
        trending_min_stars=100,
        trending_limit=20,
        notifier_enabled=False,
        notifier_type="feishu",
    )


def test_parse_analyses_handles_json_code_fence():
    events = [ev()]
    raw = "```json\n" + json.dumps([{
        "index": 0, "repo": "a/b", "summary": "s", "category": "数据库",
        "highlights": "h", "recommendation": "r",
    }]) + "\n```"
    result = _parse_analyses(raw, events)
    assert len(result) == 1
    assert result[0].category == "数据库"
    assert result[0].event is events[0]


def test_parse_analyses_skips_out_of_range_index():
    events = [ev()]
    raw = json.dumps([{"index": 9, "repo": "a/b", "summary": "s", "category": "c", "highlights": "h", "recommendation": "r"}])
    assert _parse_analyses(raw, events) == []


def test_noop_analyzer_passthrough():
    events = [ev("x/y", "trending")]
    result = NoopAnalyzer().analyze(events)
    assert len(result) == 1
    assert result[0].category == "未分类"
    assert result[0].event is events[0]


def test_create_analyzer_auto_prefers_gemini_when_key_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    a = create_analyzer(settings("auto"))
    assert type(a).__name__ == "GeminiAnalyzer"
    assert a.model == "m-gem"


def test_create_analyzer_auto_uses_github_models_without_gemini(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    a = create_analyzer(settings("auto"))
    assert isinstance(a, GitHubModelsAnalyzer)
    assert a.model == "m-gh"


def test_create_analyzer_explicit_github_models(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    a = create_analyzer(settings("github-models"))
    assert isinstance(a, GitHubModelsAnalyzer)


def test_create_analyzer_explicit_gemini_without_key_is_noop(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(create_analyzer(settings("gemini")), NoopAnalyzer)


def test_create_analyzer_openai_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://x.example/v1")
    a = create_analyzer(settings("openai"))
    assert type(a).__name__ == "OpenAICompatAnalyzer"


def test_create_analyzer_noop_without_keys(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(create_analyzer(settings("auto")), NoopAnalyzer)


def test_create_analyzer_provider_none_short_circuits(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert isinstance(create_analyzer(settings("none")), NoopAnalyzer)


# ---- 健壮性新增测试 ----

def test_strip_code_fence_tolerates_preamble_text():
    raw = '好的，以下是结果：\n```json\n[{"index": 0}]\n```'
    assert _strip_code_fence(raw).startswith("[")


def test_strip_code_fence_handles_uppercase_and_space():
    assert _strip_code_fence('```JSON\n[{"index": 0}]\n```').startswith("[")
    assert _strip_code_fence('``` json\n[{"index": 0}]\n```').startswith("[")


def test_strip_code_fence_empty_returns_empty():
    assert _strip_code_fence("") == ""
    assert _strip_code_fence("   ") == ""


def test_parse_analyses_empty_content_raises():
    with pytest.raises(ValueError):
        _parse_analyses("", [ev()])


def test_parse_analyses_non_json_raises():
    with pytest.raises(ValueError):
        _parse_analyses("this is not json at all", [ev()])


def test_parse_analyses_returns_interpretation_field():
    raw = json.dumps([{
        "index": 0, "summary": "s", "category": "数据库",
        "highlights": "h", "recommendation": "r", "interpretation": "解读内容",
    }])
    result = _parse_analyses(raw, [ev()])
    assert result[0].interpretation == "解读内容"
    assert result[0].degraded is False


def test_parse_analyses_normalizes_unknown_category():
    raw = json.dumps([{"index": 0, "category": "不存在的分类"}])
    result = _parse_analyses(raw, [ev()])
    assert result[0].category == "其他"


def test_github_models_analyzer_handles_empty_content(monkeypatch):
    """HTTP 层 mock：content 为空时应降级而非崩溃。"""
    import src.analyzer as az

    class Resp:
        def json(self):
            return {"choices": [{"message": {"content": ""}}]}
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(az.requests, "post", lambda *a, **k: Resp())
    a = GitHubModelsAnalyzer("t", "m")
    result = a.analyze([ev()])
    assert len(result) == 1
    assert result[0].degraded is True
    assert len(a.last_errors) == 1


def test_github_models_analyzer_success(monkeypatch):
    import src.analyzer as az

    good = json.dumps([{
        "index": 0, "summary": "s", "category": "大模型",
        "highlights": "h", "recommendation": "r", "interpretation": "i",
    }])

    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": good}}]}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(az.requests, "post", lambda *a, **k: Resp())
    a = GitHubModelsAnalyzer("t", "m")
    result = a.analyze([ev()])
    assert len(result) == 1
    assert result[0].degraded is False
    assert result[0].summary == "s"
    assert a.last_errors == []


def test_github_models_analyzer_retries_then_degrades(monkeypatch):
    import src.analyzer as az

    calls = {"n": 0}

    class BadResp:
        status_code = 500

        def raise_for_status(self):
            raise Exception("500")

    def fake_post(*a, **k):
        calls["n"] += 1
        return BadResp()

    monkeypatch.setattr(az.requests, "post", fake_post)
    monkeypatch.setattr(az, "_backoff", lambda attempt: None)  # 免等待
    a = GitHubModelsAnalyzer("t", "m")
    result = a.analyze([ev()])
    assert calls["n"] >= 2  # 至少重试过
    assert len(result) == 1
    assert result[0].degraded is True
