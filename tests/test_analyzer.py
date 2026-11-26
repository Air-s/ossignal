import json

from src.analyzer import (
    Analysis,
    GitHubModelsAnalyzer,
    NoopAnalyzer,
    _parse_analyses,
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


def test_create_analyzer_prefers_github_models_when_token_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    a = create_analyzer(settings("auto"))
    assert isinstance(a, GitHubModelsAnalyzer)
    assert a.model == "m-gh"


def test_create_analyzer_falls_back_to_gemini(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    a = create_analyzer(settings("auto"))
    assert type(a).__name__ == "GeminiAnalyzer"
    assert a.model == "m-gem"


def test_create_analyzer_noop_without_keys(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(create_analyzer(settings("auto")), NoopAnalyzer)


def test_create_analyzer_provider_none_short_circuits(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert isinstance(create_analyzer(settings("none")), NoopAnalyzer)
