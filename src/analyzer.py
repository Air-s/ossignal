"""LLM 分析：可插拔 provider（GitHub Models / Gemini / OpenAI 兼容），无 Key 时降级为原始信息。

健壮性设计：
- 强制 JSON 结构化输出（response_format / responseMimeType / response_format）
- 重试（网络错误 + 5xx + 429，最多 2 次）
- 分批（每批最多 BATCH_SIZE 条），单批失败不影响其它批（单条级降级）
- 解析健壮：空内容 / 自然语言 / 围栏变体均不崩
- 原始响应留痕，便于事后诊断
"""
import json
import os
import re
import time
from dataclasses import dataclass, field

import requests

from .collector import Event
from .config_loader import Settings

BATCH_SIZE = 20         # 每批最多分析的事件数。调大以合并请求：Gemini 免费层每日配额极低，
                        # 一次请求分析完当天所有条目，可把请求数降到最低（20 条 = 1 次请求）。
MAX_RETRIES = 3         # 网络/服务端错误的重试次数
REQUEST_TIMEOUT = 120
BATCH_INTERVAL = 3      # 批间休眠秒数，降低触发限流的概率

PROMPT = """你是技术雷达分析师，读者是做技术预研的工程师。下面是今日 GitHub 上值得关注的事件列表（JSON）。
请逐条给出中文分析，严格输出 JSON 数组（不要输出任何解释文字，不要用 markdown 代码块包裹），每项包含：
- index: 输入事件的 index（原样返回，必须为整数）
- summary: 一句话定位（<=50字）：这个仓库/动态是什么
- category: 技术分类，从以下选择（只允许这 7 个值之一）: AI基础设施 / 大模型 / 数据库 / DevOps / 前端 / 安全 / 其他
- highlights: 亮点（<=80字）：技术上有什么值得注意的点
- recommendation: 推荐理由（<=50字）：为什么今天值得关注
- interpretation: 技术解读（150~250字）：解决什么问题、怎么用、与已有方案/竞品的关系、值不值得跟进

事件列表：
{events}
"""

VALID_CATEGORIES = {"AI基础设施", "大模型", "数据库", "DevOps", "前端", "安全", "其他"}


@dataclass
class Analysis:
    event: Event
    summary: str
    category: str
    highlights: str
    recommendation: str
    interpretation: str = ""
    degraded: bool = False          # True 表示本条为降级产物（LLM 分析失败）


@dataclass
class _BatchResult:
    analyses: list[Analysis] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _events_payload(events: list[Event]) -> str:
    items = [
        {"index": i, "repo": e.repo, "kind": e.kind, "title": e.title,
         "detail": e.detail[:1000], "stars": e.stars}
        for i, e in enumerate(events)
    ]
    return json.dumps(items, ensure_ascii=False, indent=2)


def _strip_code_fence(text: str) -> str:
    """去除 markdown 代码围栏（容忍 ```json、```JSON、``` json 带空格、前置解释文字等变体）。"""
    if not text:
        return ""
    text = text.strip()
    # 若以 ``` 开头，去掉第一行围栏标记
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        else:
            text = text[3:]
    # 去掉结尾的 ```
    text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    # 若整体不是 JSON，尝试提取首个 [...] 片段（容忍前置解释文字）
    if text and not text.lstrip().startswith(("[", "{")):
        m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if m:
            text = m.group(1)
    return text.strip()


def _parse_analyses(raw: str, events: list[Event]) -> list[Analysis]:
    """解析 LLM 返回的 JSON 数组，逐条校验；无法解析时抛异常交由调用方降级。"""
    text = _strip_code_fence(raw)
    if not text:
        raise ValueError("LLM 返回内容为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM 返回不是合法 JSON: {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"LLM 返回不是 JSON 数组: {type(data).__name__}")

    result: list[Analysis] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(events)):
            continue
        category = item.get("category", "其他")
        if category not in VALID_CATEGORIES:
            category = "其他"
        result.append(Analysis(
            event=events[index],
            summary=str(item.get("summary", "")).strip(),
            category=category,
            highlights=str(item.get("highlights", "")).strip(),
            recommendation=str(item.get("recommendation", "")).strip(),
            interpretation=str(item.get("interpretation", "")).strip(),
        ))
    return result


def _noop_analysis(e: Event) -> Analysis:
    """降级产物：用原始信息填充，明确打标 degraded。"""
    return Analysis(
        event=e, summary=e.title, category="未分类",
        highlights=e.detail[:200], recommendation="",
        interpretation="", degraded=True,
    )


class BaseAnalyzer:
    def __init__(self):
        self.last_errors: list[str] = []

    def analyze(self, events: list[Event]) -> list[Analysis]:
        raise NotImplementedError


def _post_json(url: str, payload: dict, headers: dict, timeout: int = REQUEST_TIMEOUT) -> dict:
    """POST + 重试：网络错误 / 429 / 5xx 时退避重试，最多 MAX_RETRIES 次。"""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = requests.HTTPError(f"HTTP {resp.status_code}")
                _backoff(attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_exc = e
            _backoff(attempt)
    raise RuntimeError(f"LLM 请求失败（重试 {MAX_RETRIES} 次后）: {last_exc}")


def _backoff(attempt: int) -> None:
    # 指数退避，上限 30s：429/503 需要比 1~2s 更长的等待
    if attempt < MAX_RETRIES:
        time.sleep(min(2 ** (attempt + 1), 30))


def _sanitize_request_error(e: requests.RequestException) -> Exception:
    """去掉异常信息中的 key 参数（如 ?key=AQ.xxx），避免密钥泄漏到日报/日志。"""
    msg = str(e)
    msg = re.sub(r"(\?|&)key=[^&\s\)\]\"']+", r"\1key=***", msg)
    return type(e)(msg)


# 形似密钥的长串（连续 20+ 位字母数字/hex/base64，含 . / _ / - 分隔符），用于脱敏。
_SECRETISH_RE = re.compile(r"[A-Za-z0-9._\-]{20,}")


def _redact_secretish(text: str) -> str:
    """把形似密钥的长串打码（如 API key、token），用于留痕时避免泄漏到日志/日报。"""
    if not text:
        return ""
    return _SECRETISH_RE.sub(lambda m: m.group(0)[:4] + "…[已脱敏]", text)


class GitHubModelsAnalyzer(BaseAnalyzer):
    """GitHub Models 推理 API，使用 Actions 内置 GITHUB_TOKEN。"""

    ENDPOINT = "https://models.github.ai/inference/chat/completions"

    def __init__(self, token: str, model: str):
        self.token = token
        self.model = model

    def _analyze_batch(self, events: list[Event]) -> _BatchResult:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": PROMPT.format(events=_events_payload(events))}],
            "temperature": 0.3,
            # 强制 JSON 结构输出（针对 OpenAI 兼容接口）
            "response_format": {"type": "json_object"},
        }
        resp_json = _post_json(
            self.ENDPOINT, payload,
            {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        content = resp_json["choices"][0]["message"]["content"]
        try:
            return _BatchResult(analyses=_parse_analyses(content, events))
        except ValueError as e:
            return _BatchResult(errors=[f"解析失败（原始返回前 200 字: {content[:200]!r}）: {e}"])

    def analyze(self, events: list[Event]) -> list[Analysis]:
        return _analyze_in_batches(self, events)


class GeminiAnalyzer(BaseAnalyzer):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _analyze_batch(self, events: list[Event]) -> _BatchResult:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": PROMPT.format(events=_events_payload(events))}]}],
            # 强制 JSON 输出；temperature 已被 Gemini 3.x 废弃，不再传采样参数
            "generationConfig": {"responseMimeType": "application/json"},
        }
        return self._gemini_batch(events, url, payload)

    def _gemini_batch(self, events: list[Event], url: str, payload: dict) -> _BatchResult:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                # key 必须通过 x-goog-api-key 请求头传递，而非 ?key= 查询参数
                resp = requests.post(
                    url, json=payload, timeout=REQUEST_TIMEOUT,
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = requests.HTTPError(self._describe_http_error(resp))
                    _backoff(attempt)
                    continue
                resp.raise_for_status()
                content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                try:
                    return _BatchResult(analyses=_parse_analyses(content, events))
                except ValueError as e:
                    return _BatchResult(errors=[f"解析失败（原始返回前 200 字: {content[:200]!r}）: {e}"])
            except requests.RequestException as e:
                last_exc = _sanitize_request_error(e)
                _backoff(attempt)
        return _BatchResult(errors=[f"LLM 请求失败（重试 {MAX_RETRIES} 次后）: {last_exc}"])

    @staticmethod
    def _describe_http_error(resp) -> str:
        """把非 2xx 响应的状态码 + 响应体摘要拼进错误信息，便于事后诊断。

        响应体可能包含密钥/敏感信息，截断到 300 字并做一次脱敏。
        """
        body = ""
        try:
            text = resp.text[:300]
            body = _redact_secretish(text)
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTP {resp.status_code}" + (f" | body: {body}" if body else "")

    def analyze(self, events: list[Event]) -> list[Analysis]:
        return _analyze_in_batches(self, events)


class OpenAICompatAnalyzer(BaseAnalyzer):
    """OpenAI 兼容端点（自定义 base_url + model + api_key）。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model

    def _analyze_batch(self, events: list[Event]) -> _BatchResult:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": PROMPT.format(events=_events_payload(events))}],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
        resp_json = _post_json(
            self.base_url, payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        content = resp_json["choices"][0]["message"]["content"]
        try:
            return _BatchResult(analyses=_parse_analyses(content, events))
        except ValueError as e:
            return _BatchResult(errors=[f"解析失败（原始返回前 200 字: {content[:200]!r}）: {e}"])

    def analyze(self, events: list[Event]) -> list[Analysis]:
        return _analyze_in_batches(self, events)


def _analyze_in_batches(analyzer, events: list[Event]) -> list[Analysis]:
    """分批分析，逐批降级：单批失败只降级该批，不影响其它批。错误写入 analyzer.last_errors。"""
    if not events:
        return []
    analyzer.last_errors = []
    results: list[Analysis] = []
    for i, start in enumerate(range(0, len(events), BATCH_SIZE)):
        batch = events[start:start + BATCH_SIZE]
        if i > 0:
            time.sleep(BATCH_INTERVAL)  # 批间休眠，降低限流
        try:
            br = analyzer._analyze_batch(batch)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001 - 单批失败降级该批
            br = _BatchResult(errors=[str(e)])
        if br.errors:
            results.extend(_noop_analysis(e) for e in batch)
            analyzer.last_errors.extend(br.errors)
        else:
            results.extend(br.analyses)
            # 补齐漏掉的 index（LLM 少返回的条目），打标降级
            covered = {a.event.repo for a in br.analyses}
            for e in batch:
                if e.repo not in covered:
                    results.append(_noop_analysis(e))
                    analyzer.last_errors.append(f"{e.repo} 未在 LLM 返回中出现，已降级")
    return results


class NoopAnalyzer(BaseAnalyzer):
    """无 LLM 降级：直接用原始信息填充，明确打标。"""

    def analyze(self, events: list[Event]) -> list[Analysis]:
        self.last_errors = []
        return [_noop_analysis(e) for e in events]


def create_analyzer(settings: Settings) -> BaseAnalyzer:
    """按 provider 配置选择实现。

    重要：GitHub Models 已于 2026-07-30 全面退役，models.github.ai 端点只返回
    text/plain 的 "OK" 占位符，不再提供推理。因此不再支持 github-models provider，
    自动降级到 Gemini / OpenAI 兼容端点。

    - provider 显式指定 gemini / openai / none 时，走指定 provider；
    - provider 为 auto 时，有 GEMINI_API_KEY 用 Gemini，否则有 OPENAI_* 用 OpenAI 兼容；
    - 完全无 Key 时降级 NoopAnalyzer（纯采集模式）。
    """
    provider = settings.llm_provider
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_base = os.environ.get("OPENAI_BASE_URL")

    if provider == "none":
        return NoopAnalyzer()

    if provider == "gemini":
        return GeminiAnalyzer(gemini_key, settings.gemini_model) if gemini_key else NoopAnalyzer()

    if provider == "openai":
        model = os.environ.get("OPENAI_MODEL", settings.github_models_model)
        return OpenAICompatAnalyzer(openai_base, openai_key, model) if (openai_key and openai_base) else NoopAnalyzer()

    # auto（github-models 已退役，不再支持）：优先 Gemini，其次 OpenAI 兼容端点
    if gemini_key:
        return GeminiAnalyzer(gemini_key, settings.gemini_model)
    if openai_key and openai_base:
        model = os.environ.get("OPENAI_MODEL", settings.github_models_model)
        return OpenAICompatAnalyzer(openai_base, openai_key, model)
    return NoopAnalyzer()
