"""LLM 分析：可插拔 provider（GitHub Models / Gemini），无可用 Key 时降级为原始信息。"""
import json
import os
from dataclasses import dataclass

import requests

from .collector import Event
from .config_loader import Settings

PROMPT = """你是技术雷达分析师，读者是做技术预研的工程师。下面是今日 GitHub 上值得关注的事件列表（JSON）。
请逐条给出中文分析，严格输出 JSON 数组，每项包含：
- index: 输入事件的 index（原样返回）
- summary: 一句话简介（<=50字）
- category: 技术分类，从以下选择: AI基础设施 / 大模型 / 数据库 / DevOps / 前端 / 安全 / 其他
- highlights: 亮点（<=80字）
- recommendation: 推荐理由（<=50字）

事件列表：
{events}
"""


@dataclass
class Analysis:
    event: Event
    summary: str
    category: str
    highlights: str
    recommendation: str


def _events_payload(events: list[Event]) -> str:
    items = [
        {"index": i, "repo": e.repo, "kind": e.kind, "title": e.title, "detail": e.detail[:1000], "stars": e.stars}
        for i, e in enumerate(events)
    ]
    return json.dumps(items, ensure_ascii=False, indent=2)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


def _parse_analyses(raw: str, events: list[Event]) -> list[Analysis]:
    result: list[Analysis] = []
    for item in json.loads(_strip_code_fence(raw)):
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(events)):
            continue
        result.append(Analysis(
            event=events[index],
            summary=item.get("summary", ""),
            category=item.get("category", "其他"),
            highlights=item.get("highlights", ""),
            recommendation=item.get("recommendation", ""),
        ))
    return result


class BaseAnalyzer:
    def analyze(self, events: list[Event]) -> list[Analysis]:
        raise NotImplementedError


class GitHubModelsAnalyzer(BaseAnalyzer):
    """GitHub Models 推理 API，使用 Actions 内置 GITHUB_TOKEN。"""

    ENDPOINT = "https://models.github.ai/inference/chat/completions"

    def __init__(self, token: str, model: str):
        self.token = token
        self.model = model

    def analyze(self, events: list[Event]) -> list[Analysis]:
        if not events:
            return []
        resp = requests.post(
            self.ENDPOINT,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": PROMPT.format(events=_events_payload(events))}],
                "temperature": 0.3,
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_analyses(content, events)


class GeminiAnalyzer(BaseAnalyzer):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def analyze(self, events: list[Event]) -> list[Analysis]:
        if not events:
            return []
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        resp = requests.post(
            url,
            params={"key": self.api_key},
            json={
                "contents": [{"parts": [{"text": PROMPT.format(events=_events_payload(events))}]}],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_analyses(content, events)


class NoopAnalyzer(BaseAnalyzer):
    """无 LLM 降级：直接用原始信息填充。"""

    def analyze(self, events: list[Event]) -> list[Analysis]:
        return [Analysis(event=e, summary=e.title, category="未分类", highlights=e.detail[:200], recommendation="") for e in events]


def create_analyzer(settings: Settings) -> BaseAnalyzer:
    """按 provider 配置与可用密钥选择实现。auto 优先 GitHub Models，其次 Gemini。"""
    provider = settings.llm_provider
    gh_token = os.environ.get("GITHUB_TOKEN")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if provider == "none":
        return NoopAnalyzer()
    if provider in ("auto", "github-models") and gh_token:
        return GitHubModelsAnalyzer(gh_token, settings.github_models_model)
    if provider in ("auto", "gemini") and gemini_key:
        return GeminiAnalyzer(gemini_key, settings.gemini_model)
    return NoopAnalyzer()
