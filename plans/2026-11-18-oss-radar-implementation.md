# oss-radar 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 GitHub Actions 驱动的每日开源技术雷达：自动扫描大厂组织新仓库、精选仓库更新与趋势项目，用免费 LLM 生成中文日报，提交回仓库并可选 webhook 推送。

**Architecture:** Python 单仓脚本，GitHub Actions cron 触发。流程：collector（GitHub API 增量采集，与 data/state.json 比对去重）→ analyzer（GitHub Models 优先、Gemini 备选、无 Key 降级）→ reporter（生成 reports/ 日报与 archive/ 原文归档）→ notifier（可选 webhook）。discover 模块每周自动维护监控列表并以 PR 提交。

**Tech Stack:** Python 3.11、requests、PyYAML、pytest、GitHub Actions、GitHub Models API / Gemini API。

**设计文档:** `specs/2026-11-18-oss-radar-design.md`

**项目根目录:** 仓库根 `ossignal/`（代码直接落在仓库根，`plans/` `specs/` 保留；复用现有仓库、不执行 `git init`；默认分支统一为 `main`）

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/config_loader.py` | 加载 config/*.yaml 为强类型 dataclass |
| `src/state.py` | 增量状态读写（已见仓库、快照） |
| `src/collector.py` | GitHub API 客户端 + 事件采集（Event dataclass、collect_events） |
| `src/analyzer.py` | LLM 分析（Analysis dataclass、三个 provider、create_analyzer 工厂） |
| `src/reporter.py` | 日报渲染、写文件、原文归档 |
| `src/notifier.py` | 摘要构造与 webhook 推送（飞书/Server酱） |
| `src/discover.py` | 候选组织/仓库发现、LLM 过滤、回写 config |
| `src/main.py` | CLI 入口与流程编排（日常模式 / --discover / --dry-run） |
| `config/settings.yaml` `orgs.yaml` `repos.yaml` | 行为配置与监控列表 |
| `data/state.json` | 增量状态（由 bot 提交） |
| `.github/workflows/daily.yml` `discover.yml` | 每日运行 / 每周列表维护 |
| `tests/` | 各模块单测 |

---

### Task 1: 项目骨架与依赖

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `conftest.py`
- Create: `config/settings.yaml`
- Create: `config/orgs.yaml`
- Create: `config/repos.yaml`
- Create: `data/.gitkeep`
- Create: `reports/.gitkeep`
- Create: `archive/.gitkeep`

- [ ] **Step 1: 创建骨架文件**

`requirements.txt`:
```text
requests>=2.31
PyYAML>=6.0
pytest>=8.0
```

`.gitignore`:
```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
```

`src/__init__.py`、`tests/__init__.py`、`conftest.py`、`data/.gitkeep`、`reports/.gitkeep`、`archive/.gitkeep` 均为空文件（conftest.py 存在即可保证 pytest 把项目根加入 sys.path）。

`config/settings.yaml`:
```yaml
llm:
  provider: auto            # auto | github-models | gemini | none
  github_models:
    model: openai/gpt-4o-mini
  gemini:
    model: gemini-2.0-flash
analysis:
  max_items_per_run: 30     # 单次最多分析的事件数，控制 LLM 成本
notifier:
  enabled: false            # 配置 WEBHOOK_URL secret 后改为 true
  type: feishu              # feishu | serverchan
```

`config/orgs.yaml`:
```yaml
orgs:
  - google
  - google-deepmind
  - microsoft
  - meta
  - openai
  - NVIDIA
  - aws
  - alibaba
  - tencent
  - bytedance
  - antgroup
  - deepseek-ai
  - QwenLM
  - apache
new_repo:
  max_age_days: 7           # 创建 7 天内视为新仓库
  min_stars: 50             # 且 star 达到该阈值才关注
updates:
  star_spike_threshold: 200 # 距上次快照 star 增长超过此值视为激增
```

`config/repos.yaml`:
```yaml
repos:
  - vllm-project/vllm
  - ollama/ollama
  - langchain-ai/langchain
  - huggingface/transformers
  - modelscope/modelscope
```

- [ ] **Step 2: 创建虚拟环境、安装依赖**

复用现有 `ossignal` 仓库（不执行 `git init`），代码直接落在仓库根目录，并把默认分支统一为 `main`。

Run:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
git branch -M main
```
Expected: 依赖安装成功，无报错；当前分支为 `main`。

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "chore: 项目骨架与监控配置种子"
```

---

### Task 2: 配置加载 config_loader

**Files:**
- Create: `src/config_loader.py`
- Test: `tests/test_config_loader.py`

- [ ] **Step 1: 写失败测试**

`tests/test_config_loader.py`:
```python
from pathlib import Path

from src.config_loader import load_orgs, load_repos, load_settings


def _write_config_dir(tmp_path: Path, settings: str, orgs: str, repos: str) -> Path:
    (tmp_path / "settings.yaml").write_text(settings, encoding="utf-8")
    (tmp_path / "orgs.yaml").write_text(orgs, encoding="utf-8")
    (tmp_path / "repos.yaml").write_text(repos, encoding="utf-8")
    return tmp_path


def test_load_settings_defaults_on_empty_file(tmp_path):
    cfg_dir = _write_config_dir(tmp_path, "", "orgs: []\n", "repos: []\n")
    s = load_settings(cfg_dir)
    assert s.llm_provider == "auto"
    assert s.github_models_model == "openai/gpt-4o-mini"
    assert s.max_items_per_run == 30
    assert s.notifier_enabled is False


def test_load_settings_reads_values(tmp_path):
    cfg_dir = _write_config_dir(
        tmp_path,
        "llm:\n  provider: gemini\n  gemini:\n    model: gemini-x\n"
        "analysis:\n  max_items_per_run: 5\n"
        "notifier:\n  enabled: true\n  type: serverchan\n",
        "orgs: [google]\nnew_repo:\n  max_age_days: 3\n  min_stars: 10\n"
        "updates:\n  star_spike_threshold: 99\n",
        "repos: [a/b]\n",
    )
    s = load_settings(cfg_dir)
    assert s.llm_provider == "gemini"
    assert s.gemini_model == "gemini-x"
    assert s.max_items_per_run == 5
    assert s.notifier_enabled is True
    assert s.notifier_type == "serverchan"

    o = load_orgs(cfg_dir)
    assert o.orgs == ["google"]
    assert o.new_repo_max_age_days == 3
    assert o.new_repo_min_stars == 10
    assert o.star_spike_threshold == 99

    r = load_repos(cfg_dir)
    assert r.repos == ["a/b"]


def test_load_orgs_defaults(tmp_path):
    cfg_dir = _write_config_dir(tmp_path, "", "", "")
    o = load_orgs(cfg_dir)
    assert o.orgs == []
    assert o.new_repo_max_age_days == 7
    assert o.new_repo_min_stars == 50
    assert o.star_spike_threshold == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.config_loader'`

- [ ] **Step 3: 实现 config_loader**

`src/config_loader.py`:
```python
"""加载 config/ 下的 YAML 配置为强类型 dataclass。"""
from dataclasses import dataclass
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    github_models_model: str
    gemini_model: str
    max_items_per_run: int
    notifier_enabled: bool
    notifier_type: str


@dataclass(frozen=True)
class OrgConfig:
    orgs: list[str]
    new_repo_max_age_days: int
    new_repo_min_stars: int
    star_spike_threshold: int


@dataclass(frozen=True)
class RepoConfig:
    repos: list[str]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: Path = CONFIG_DIR) -> Settings:
    raw = _load_yaml(config_dir / "settings.yaml")
    llm = raw.get("llm", {})
    notifier = raw.get("notifier", {})
    return Settings(
        llm_provider=llm.get("provider", "auto"),
        github_models_model=llm.get("github_models", {}).get("model", "openai/gpt-4o-mini"),
        gemini_model=llm.get("gemini", {}).get("model", "gemini-2.0-flash"),
        max_items_per_run=raw.get("analysis", {}).get("max_items_per_run", 30),
        notifier_enabled=notifier.get("enabled", False),
        notifier_type=notifier.get("type", "feishu"),
    )


def load_orgs(config_dir: Path = CONFIG_DIR) -> OrgConfig:
    raw = _load_yaml(config_dir / "orgs.yaml")
    new_repo = raw.get("new_repo", {})
    updates = raw.get("updates", {})
    return OrgConfig(
        orgs=raw.get("orgs", []),
        new_repo_max_age_days=new_repo.get("max_age_days", 7),
        new_repo_min_stars=new_repo.get("min_stars", 50),
        star_spike_threshold=updates.get("star_spike_threshold", 200),
    )


def load_repos(config_dir: Path = CONFIG_DIR) -> RepoConfig:
    raw = _load_yaml(config_dir / "repos.yaml")
    return RepoConfig(repos=raw.get("repos", []))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/config_loader.py tests/test_config_loader.py
git commit -m "feat: YAML 配置加载"
```

---

### Task 3: 增量状态 state

**Files:**
- Create: `src/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: 写失败测试**

`tests/test_state.py`:
```python
from src.state import State


def test_load_missing_file_returns_empty_state(tmp_path):
    s = State.load(tmp_path / "nope.json")
    assert s.repos == {}
    assert s.seen_new_repos == set()


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s = State()
    s.update_repo("a/b", stars=100, release="v1", readme_sha="abc")
    s.seen_new_repos.add("org/new")
    s.save(path)

    loaded = State.load(path)
    assert loaded.repo_snapshot("a/b") == {"stars": 100, "last_release": "v1", "readme_sha": "abc"}
    assert "org/new" in loaded.seen_new_repos


def test_repo_snapshot_unknown_repo_returns_empty_dict(tmp_path):
    s = State()
    assert s.repo_snapshot("x/y") == {}


def test_http_cache_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s = State()
    s.http_cache['/repos/a/b?'] = {"etag": 'W/"1"', "json": {"stargazers_count": 1}}
    s.save(path)

    loaded = State.load(path)
    assert loaded.http_cache['/repos/a/b?']["etag"] == 'W/"1"'
    assert loaded.http_cache['/repos/a/b?']["json"] == {"stargazers_count": 1}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_state.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.state'`

- [ ] **Step 3: 实现 state**

`src/state.py`:
```python
"""增量状态：记录仓库快照与已见新仓库，避免重复报告。"""
import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "data" / "state.json"


class State:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.repos: dict = data.get("repos", {})
        self.seen_new_repos: set[str] = set(data.get("seen_new_repos", []))
        self.http_cache: dict = data.get("http_cache", {})

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "State":
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "repos": self.repos,
            "seen_new_repos": sorted(self.seen_new_repos),
            "http_cache": self.http_cache,
            "last_run": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def repo_snapshot(self, repo: str) -> dict:
        return self.repos.get(repo, {})

    def update_repo(self, repo: str, *, stars: int, release: str | None, readme_sha: str | None) -> None:
        self.repos[repo] = {"stars": stars, "last_release": release, "readme_sha": readme_sha}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_state.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat: 增量状态管理"
```

---

### Task 4: GitHub 客户端 GitHubClient

**Files:**
- Create: `src/collector.py`（本任务只含 GitHubClient 与 Event，采集函数在 Task 5）
- Test: `tests/test_collector.py`（本任务只测客户端方法）

- [ ] **Step 1: 写失败测试**

`tests/test_collector.py`:
```python
import base64

import pytest
import requests

from src.collector import Event, GitHubClient


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.text = payload if isinstance(payload, str) else ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """按 URL 子串路由到 FakeResponse。值为列表时按调用顺序弹出。"""

    def __init__(self, routes: dict):
        self.routes = routes
        self.headers: dict = {}
        self.calls: list[str] = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                if isinstance(resp, list):
                    return resp.pop(0)
                return resp
        raise AssertionError(f"unexpected GET {url}")


def make_client(routes) -> GitHubClient:
    return GitHubClient(token="t", session=FakeSession(routes))


def test_get_latest_release_returns_none_on_404():
    client = make_client({"/releases/latest": FakeResponse({}, status=404)})
    assert client.get_latest_release("a/b") is None


def test_get_latest_release_returns_payload():
    payload = {"tag_name": "v1.0", "html_url": "http://x", "body": "notes"}
    client = make_client({"/releases/latest": FakeResponse(payload)})
    assert client.get_latest_release("a/b") == payload


def test_get_readme_decodes_base64_and_sha():
    content = base64.b64encode("# hello".encode()).decode()
    client = make_client({"/readme": FakeResponse({"content": content, "sha": "abc123"})})
    text, sha = client.get_readme("a/b")
    assert text == "# hello"
    assert sha == "abc123"


def test_get_readme_returns_none_on_404():
    client = make_client({"/readme": FakeResponse({}, status=404)})
    assert client.get_readme("a/b") is None


def test_get_reuses_cache_on_304_and_sends_if_none_match():
    payload = {"stargazers_count": 7, "html_url": "h"}
    etag = 'W/"abc"'
    seen_headers: list[dict] = []

    class CacheSession:
        def __init__(self):
            self.headers: dict = {}
            self.calls = 0

        def get(self, url, params=None, timeout=None, headers=None):
            seen_headers.append(headers or {})
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(payload, headers={"ETag": etag})
            return FakeResponse({}, status=304, headers={"ETag": etag})

    cache: dict = {}
    client = GitHubClient(token="t", session=CacheSession(), cache=cache)
    assert client.get_repo("a/b") == payload
    assert client.get_repo("a/b") == payload
    assert seen_headers[1]["If-None-Match"] == etag
    assert cache['/repos/a/b?']["etag"] == etag


def test_search_trending_passes_query_and_returns_items():
    captured = {}

    class S(FakeSession):
        def get(self, url, params=None, timeout=None, headers=None):
            captured.update(params or {})
            return FakeResponse({"items": [{"full_name": "x/y"}]})

    client = GitHubClient(token="t", session=S({}))
    items = client.search_trending(days=3, min_stars=50, limit=5)
    assert items == [{"full_name": "x/y"}]
    assert "created:>" in captured["q"]
    assert "stars:>=50" in captured["q"]
    assert captured["per_page"] == 5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collector.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.collector'`

- [ ] **Step 3: 实现 GitHubClient 与 Event**

`src/collector.py`:
```python
"""GitHub API 客户端与增量事件采集。"""
import base64
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.github.com"


@dataclass
class Event:
    kind: str   # new_repo | new_release | readme_update | star_spike | trending
    repo: str   # "owner/name"
    title: str
    url: str
    detail: str
    stars: int = 0


class CachedResponse:
    """304 命中缓存时的轻量响应：复用缓存 body，状态码视作 200。"""

    status_code = 200

    def __init__(self, json_data: dict, headers: dict | None = None):
        self._json = json_data
        self.headers = headers or {}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        return None


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        session: requests.Session | None = None,
        cache: dict | None = None,
    ):
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        # 跨运行 ETag 缓存：{cache_key: {"etag": str, "json": dict}}，由 State 持久化
        self.cache: dict = cache if cache is not None else {}

    def _cache_key(self, path: str, params: dict) -> str:
        clean = {k: v for k, v in params.items() if v is not None}
        return f"{path}?{urllib.parse.urlencode(sorted(clean.items()))}"

    def _get(self, path: str, use_cache: bool = True, **params) -> requests.Response:
        """GET，带 ETag 条件请求与限流退避。304 命中缓存时返回 CachedResponse。"""
        key = self._cache_key(path, params)
        extra_headers: dict = {}
        if use_cache and key in self.cache:
            extra_headers["If-None-Match"] = self.cache[key]["etag"]

        resp = self.session.get(f"{API}{path}", params=params, timeout=30, headers=extra_headers or None)
        for _ in range(2):
            if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                time.sleep(max(reset - time.time(), 1) + 1)
                resp = self.session.get(f"{API}{path}", params=params, timeout=30, headers=extra_headers or None)
            else:
                break

        if use_cache and resp.status_code == 304 and key in self.cache:
            return CachedResponse(self.cache[key]["json"], resp.headers)
        if use_cache and resp.status_code == 200:
            etag = resp.headers.get("ETag")
            if etag:
                self.cache[key] = {"etag": etag, "json": resp.json()}
        return resp

    def get_repo(self, repo: str) -> dict:
        resp = self._get(f"/repos/{repo}")
        resp.raise_for_status()
        return resp.json()

    def get_latest_release(self, repo: str) -> dict | None:
        resp = self._get(f"/repos/{repo}/releases/latest")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_readme(self, repo: str) -> tuple[str, str] | None:
        """返回 (README 文本, sha)；无 README 返回 None。"""
        resp = self._get(f"/repos/{repo}/readme")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return text, data["sha"]

    def iter_org_repos_by_created(self, org: str):
        """按创建时间倒序逐页产出组织仓库（dict）。"""
        page = 1
        while True:
            resp = self._get(
                f"/orgs/{org}/repos",
                per_page=100, page=page, type="public", sort="created", direction="desc",
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                return
            yield from batch
            if len(batch) < 100:
                return
            page += 1

    def search_trending(self, days: int = 1, min_stars: int = 100, limit: int = 20) -> list[dict]:
        """用 Search API 作为趋势代理：近 days 天创建且 star 达标的仓库，按 star 降序。"""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        resp = self._get(
            "/search/repositories",
            use_cache=False,  # 查询按日期变化且响应体量大，不进 ETag 缓存，避免 state.json 膨胀
            q=f"created:>{since} stars:>={min_stars}",
            sort="stars", order="desc", per_page=limit,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collector.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/collector.py tests/test_collector.py
git commit -m "feat: GitHub API 客户端（限流退避、release/README/趋势查询）"
```

---

### Task 5: 事件采集函数 collect_events

**Files:**
- Modify: `src/collector.py`（追加采集函数）
- Test: `tests/test_collect_events.py`

- [ ] **Step 1: 写失败测试**

`tests/test_collect_events.py`:
```python
from datetime import datetime, timedelta, timezone

from src.collector import Event, collect_events
from src.config_loader import OrgConfig, RepoConfig
from src.state import State


def iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class StubClient:
    """按测试需要预置数据的假客户端。"""

    def __init__(self, repos_meta=None, releases=None, readmes=None, org_repos=None, trending=None):
        self.repos_meta = repos_meta or {}
        self.releases = releases or {}
        self.readmes = readmes or {}
        self.org_repos = org_repos or {}
        self.trending = trending or []

    def get_repo(self, repo):
        return self.repos_meta[repo]

    def get_latest_release(self, repo):
        return self.releases.get(repo)

    def get_readme(self, repo):
        return self.readmes.get(repo)

    def iter_org_repos_by_created(self, org):
        yield from self.org_repos.get(org, [])

    def search_trending(self, days=1, min_stars=100, limit=20):
        return self.trending


ORG_CFG = OrgConfig(orgs=["bigtech"], new_repo_max_age_days=7, new_repo_min_stars=50, star_spike_threshold=200)
REPO_CFG = RepoConfig(repos=["a/b"])


def meta(stars):
    return {"stargazers_count": stars, "html_url": "http://x"}


def test_tracked_repo_new_release_and_baseline_rule():
    state = State()
    state.update_repo("a/b", stars=100, release="v1", readme_sha="s1")
    client = StubClient(
        repos_meta={"a/b": meta(150)},
        releases={"a/b": {"tag_name": "v2", "html_url": "http://r", "body": "notes"}},
        readmes={"a/b": ("readme text", "s1")},
    )
    events, failures = collect_events(client, ORG_CFG, REPO_CFG, state)
    kinds = [e.kind for e in events]
    assert "new_release" in kinds
    assert "readme_update" not in kinds          # sha 未变
    assert "star_spike" not in kinds             # +50 < 200
    assert failures == []
    assert state.repo_snapshot("a/b")["last_release"] == "v2"


def test_first_run_records_baseline_without_events():
    state = State()
    client = StubClient(
        repos_meta={"a/b": meta(500)},
        releases={"a/b": {"tag_name": "v9", "html_url": "http://r", "body": "x"}},
        readmes={"a/b": ("t", "s1")},
    )
    events, _ = collect_events(client, ORG_CFG, REPO_CFG, state)
    assert events == []
    assert state.repo_snapshot("a/b")["stars"] == 500


def test_star_spike_and_readme_update():
    state = State()
    state.update_repo("a/b", stars=100, release=None, readme_sha="old")
    client = StubClient(
        repos_meta={"a/b": meta(400)},
        readmes={"a/b": ("new readme", "newsha")},
    )
    events, _ = collect_events(client, ORG_CFG, REPO_CFG, state)
    kinds = sorted(e.kind for e in events)
    assert kinds == ["readme_update", "star_spike"]


def test_org_new_repo_filters_by_age_stars_and_seen():
    state = State()
    state.seen_new_repos.add("bigtech/seen")
    client = StubClient(
        repos_meta={"a/b": meta(0)},
        org_repos={"bigtech": [
            {"full_name": "bigtech/hot", "created_at": iso(1), "stargazers_count": 80, "html_url": "h", "description": "d"},
            {"full_name": "bigtech/seen", "created_at": iso(1), "stargazers_count": 80, "html_url": "h", "description": "d"},
            {"full_name": "bigtech/cold", "created_at": iso(1), "stargazers_count": 10, "html_url": "h", "description": "d"},
            {"full_name": "bigtech/old", "created_at": iso(30), "stargazers_count": 999, "html_url": "h", "description": "d"},
        ]},
    )
    events, _ = collect_events(client, ORG_CFG, REPO_CFG, state)
    assert [e.repo for e in events] == ["bigtech/hot"]
    # 所有扫描过的都记入 seen，避免重复扫描；old 触发提前终止不记入
    assert "bigtech/seen" in state.seen_new_repos
    assert "bigtech/cold" in state.seen_new_repos


def test_trending_dedupes_tracked_and_seen():
    state = State()
    state.seen_new_repos.add("x/old")
    client = StubClient(
        repos_meta={"a/b": meta(0)},
        trending=[
            {"full_name": "a/b", "html_url": "h", "description": "d", "stargazers_count": 1},
            {"full_name": "x/old", "html_url": "h", "description": "d", "stargazers_count": 1},
            {"full_name": "x/new", "html_url": "h", "description": "d", "stargazers_count": 300},
        ],
    )
    events, _ = collect_events(client, ORG_CFG, REPO_CFG, state)
    assert [e.repo for e in events] == ["x/new"]
    assert events[0].kind == "trending"
    assert "x/new" in state.seen_new_repos        # 写入 seen，次日不再重复上报
    assert "a/b" not in state.seen_new_repos      # 精选仓库不写入 seen


def test_single_source_failure_does_not_break_others():
    class BoomClient(StubClient):
        def get_repo(self, repo):
            raise RuntimeError("api down")

    state = State()
    client = BoomClient(trending=[{"full_name": "x/new", "html_url": "h", "description": "d", "stargazers_count": 300}])
    events, failures = collect_events(client, ORG_CFG, REPO_CFG, state)
    assert [e.repo for e in events] == ["x/new"]
    assert any("a/b" in f for f in failures)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collect_events.py -v`
Expected: FAIL，`ImportError: cannot import name 'collect_events' from 'src.collector'`

- [ ] **Step 3: 实现采集函数（追加到 `src/collector.py` 末尾）**

```python
from .config_loader import OrgConfig, RepoConfig  # noqa: E402
from .state import State  # noqa: E402


def _repo_events(client: GitHubClient, repo: str, cfg: OrgConfig, state: State) -> list[Event]:
    """单个精选仓库的增量事件：star 激增 / 新 release / README 变更。首次运行只记基线。"""
    events: list[Event] = []
    meta = client.get_repo(repo)
    stars = meta["stargazers_count"]
    snap = state.repo_snapshot(repo)
    is_baseline = not snap

    prev_stars = snap.get("stars")
    if prev_stars is not None and stars - prev_stars >= cfg.star_spike_threshold:
        events.append(Event(
            kind="star_spike", repo=repo,
            title=f"{repo} star 激增 +{stars - prev_stars}",
            url=meta["html_url"],
            detail=f"Stars: {prev_stars} -> {stars}",
            stars=stars,
        ))

    release = client.get_latest_release(repo)
    rel_tag = release["tag_name"] if release else None
    if release and not is_baseline and rel_tag != snap.get("last_release"):
        events.append(Event(
            kind="new_release", repo=repo,
            title=f"{repo} 发布 {rel_tag}",
            url=release["html_url"],
            detail=(release.get("body") or "")[:3000],
            stars=stars,
        ))

    readme = client.get_readme(repo)
    readme_sha = readme[1] if readme else None
    if readme and not is_baseline and snap.get("readme_sha") and readme_sha != snap["readme_sha"]:
        events.append(Event(
            kind="readme_update", repo=repo,
            title=f"{repo} README 更新",
            url=meta["html_url"],
            detail=readme[0][:3000],
            stars=stars,
        ))

    state.update_repo(repo, stars=stars, release=rel_tag, readme_sha=readme_sha)
    return events


def _new_repo_events(client: GitHubClient, org: str, cfg: OrgConfig, state: State) -> list[Event]:
    """组织内新仓库事件。按创建时间倒序扫描，遇到超龄仓库即停止。"""
    events: list[Event] = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cfg.new_repo_max_age_days)
    for item in client.iter_org_repos_by_created(org):
        created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
        if created < cutoff:
            break
        full = item["full_name"]
        if full in state.seen_new_repos:
            continue
        state.seen_new_repos.add(full)
        if item["stargazers_count"] >= cfg.new_repo_min_stars:
            events.append(Event(
                kind="new_repo", repo=full,
                title=f"新仓库 {full}",
                url=item["html_url"],
                detail=(item.get("description") or "")[:500],
                stars=item["stargazers_count"],
            ))
    return events


def collect_events(client: GitHubClient, org_cfg: OrgConfig, repo_cfg: RepoConfig, state: State) -> tuple[list[Event], list[str]]:
    """汇总三路来源的事件。单源失败记录到 failures，不影响其他来源。"""
    events: list[Event] = []
    failures: list[str] = []

    for repo in repo_cfg.repos:
        try:
            events.extend(_repo_events(client, repo, org_cfg, state))
        except Exception as e:  # noqa: BLE001 - 单仓库失败不阻塞整体
            failures.append(f"repo {repo}: {e}")

    for org in org_cfg.orgs:
        try:
            events.extend(_new_repo_events(client, org, org_cfg, state))
        except Exception as e:  # noqa: BLE001
            failures.append(f"org {org}: {e}")

    try:
        tracked = set(repo_cfg.repos)
        for item in client.search_trending():
            full = item["full_name"]
            if full in tracked or full in state.seen_new_repos:
                continue
            state.seen_new_repos.add(full)  # 记入 seen，避免同一趋势仓库跨日重复上报
            events.append(Event(
                kind="trending", repo=full,
                title=f"趋势新仓库 {full}",
                url=item["html_url"],
                detail=(item.get("description") or "")[:500],
                stars=item["stargazers_count"],
            ))
    except Exception as e:  # noqa: BLE001
        failures.append(f"trending: {e}")

    return events, failures
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collect_events.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/collector.py tests/test_collect_events.py
git commit -m "feat: 三路来源增量事件采集与去重"
```

---

### Task 6: LLM 分析器 analyzer

**Files:**
- Create: `src/analyzer.py`
- Test: `tests/test_analyzer.py`

- [ ] **Step 1: 写失败测试**

`tests/test_analyzer.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analyzer.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.analyzer'`

- [ ] **Step 3: 实现 analyzer**

`src/analyzer.py`:
```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_analyzer.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py tests/test_analyzer.py
git commit -m "feat: 可插拔 LLM 分析器（GitHub Models/Gemini/降级）"
```

---

### Task 7: 日报生成 reporter

**Files:**
- Create: `src/reporter.py`
- Test: `tests/test_reporter.py`

- [ ] **Step 1: 写失败测试**

`tests/test_reporter.py`:
```python
from datetime import date

from src.analyzer import Analysis
from src.collector import Event
from src.reporter import archive_docs, render_daily_report, write_report

DAY = date(2026, 11, 18)


def ana(repo, category, kind="new_release", detail="原文内容"):
    return Analysis(
        event=Event(kind=kind, repo=repo, title=f"{repo} 标题", url="http://u", detail=detail, stars=42),
        summary="简介", category=category, highlights="亮点", recommendation="推荐",
    )


def test_render_groups_by_category_with_order():
    analyses = [ana("x/1", "其他"), ana("x/2", "大模型"), ana("x/3", "数据库")]
    md = render_daily_report(DAY, analyses, [])
    assert md.startswith("# 开源技术雷达日报 2026-11-18")
    assert md.index("## 大模型") < md.index("## 数据库") < md.index("## 其他")
    assert "Stars: 42" in md
    assert "[x/1 标题](http://u)" in md


def test_render_empty_day():
    md = render_daily_report(DAY, [], [])
    assert "今日无值得关注的新动态" in md


def test_render_includes_failures_section():
    md = render_daily_report(DAY, [], ["org google: boom"])
    assert "## 采集异常" in md
    assert "org google: boom" in md


def test_write_report_creates_file(tmp_path):
    path = write_report("content", tmp_path / "reports", DAY)
    assert path.name == "2026-11-18.md"
    assert path.read_text(encoding="utf-8") == "content"


def test_archive_docs_sanitizes_filenames(tmp_path):
    written = archive_docs([ana("owner/repo", "大模型")], tmp_path, DAY)
    assert len(written) == 1
    assert written[0].name == "owner_repo--new_release.md"
    assert "原文内容" in written[0].read_text(encoding="utf-8")
    assert "http://u" in written[0].read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reporter.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.reporter'`

- [ ] **Step 3: 实现 reporter**

`src/reporter.py`:
```python
"""日报 Markdown 渲染、写文件、原文归档。"""
import re
from datetime import date
from pathlib import Path

from .analyzer import Analysis

CATEGORY_ORDER = ["AI基础设施", "大模型", "数据库", "DevOps", "前端", "安全", "其他", "未分类"]


def _category_sort_key(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)


def render_daily_report(day: date, analyses: list[Analysis], failures: list[str]) -> str:
    lines = [f"# 开源技术雷达日报 {day.isoformat()}", ""]
    if not analyses:
        lines += ["今日无值得关注的新动态。", ""]

    groups: dict[str, list[Analysis]] = {}
    for a in analyses:
        groups.setdefault(a.category or "其他", []).append(a)

    for category in sorted(groups, key=_category_sort_key):
        lines.append(f"## {category}")
        lines.append("")
        for a in groups[category]:
            lines.append(f"### [{a.event.title}]({a.event.url})")
            lines.append("")
            lines.append(f"- Stars: {a.event.stars}")
            if a.summary:
                lines.append(f"- 简介: {a.summary}")
            if a.highlights:
                lines.append(f"- 亮点: {a.highlights}")
            if a.recommendation:
                lines.append(f"- 推荐理由: {a.recommendation}")
            lines.append("")

    if failures:
        lines.append("## 采集异常")
        lines.append("")
        lines += [f"- {f}" for f in failures]
        lines.append("")

    return "\n".join(lines)


def write_report(content: str, reports_dir: Path, day: date) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{day.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return path


def archive_docs(analyses: list[Analysis], archive_dir: Path, day: date) -> list[Path]:
    """把事件原文（release notes / README 摘录）按日期归档，返回写入的文件。"""
    written: list[Path] = []
    for a in analyses:
        if not a.event.detail:
            continue
        safe_name = re.sub(r"[^\w.-]", "_", a.event.repo)
        path = archive_dir / day.isoformat() / f"{safe_name}--{a.event.kind}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {a.event.title}\n\n来源: {a.event.url}\n\n---\n\n{a.event.detail}\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reporter.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/reporter.py tests/test_reporter.py
git commit -m "feat: 日报渲染与原文归档"
```

---

### Task 8: 通知 notifier

**Files:**
- Create: `src/notifier.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: 写失败测试**

`tests/test_notifier.py`:
```python
import src.notifier as notifier
from src.analyzer import Analysis
from src.collector import Event
from src.notifier import build_summary, send_webhook


def ana(i):
    return Analysis(
        event=Event(kind="new_repo", repo=f"o/r{i}", title=f"t{i}", url="u", detail="d", stars=1),
        summary=f"简介{i}", category="大模型", highlights="", recommendation="",
    )


def test_build_summary_truncates_to_ten():
    text = build_summary("2026-11-18", [ana(i) for i in range(15)], "http://report")
    assert "共 15 条动态" in text
    assert "o/r9" in text
    assert "o/r10" not in text
    assert "等 15 条" in text
    assert "http://report" in text


def test_send_webhook_feishu_posts_text_message(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, data=None, timeout=None):
        captured.update(url=url, json=json, data=data)
        return Resp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_webhook("http://hook", "feishu", "hello")
    assert captured["json"] == {"msg_type": "text", "content": {"text": "hello"}}


def test_send_webhook_feishu_with_secret_adds_sign(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, data=None, timeout=None):
        captured.update(json=json)
        return Resp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_webhook("http://hook", "feishu", "hello", secret="s3cr3t")
    assert captured["json"]["content"]["text"] == "hello"
    assert "timestamp" in captured["json"]
    assert "sign" in captured["json"]


def test_send_webhook_serverchan_posts_form(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, data=None, timeout=None):
        captured.update(url=url, json=json, data=data)
        return Resp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_webhook("http://hook", "serverchan", "hello")
    assert captured["data"]["desp"] == "hello"
    assert captured["data"]["title"] == "开源雷达日报"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_notifier.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.notifier'`

- [ ] **Step 3: 实现 notifier**

`src/notifier.py`:
```python
"""webhook 摘要推送：飞书自定义机器人 / Server酱。"""
import base64
import hashlib
import hmac
import time

import requests

from .analyzer import Analysis


def build_summary(day_str: str, analyses: list[Analysis], report_url: str) -> str:
    lines = [f"开源雷达日报 {day_str}", f"共 {len(analyses)} 条动态："]
    for a in analyses[:10]:
        lines.append(f"· [{a.category}] {a.event.repo} - {a.summary}")
    if len(analyses) > 10:
        lines.append(f"... 等 {len(analyses)} 条")
    if report_url:
        lines.append(f"完整报告: {report_url}")
    return "\n".join(lines)


def _feishu_sign(timestamp: str, secret: str) -> str:
    """飞书自定义机器人签名：HMAC-SHA256(key=f"{ts}\\n{secret}", msg="") 再 base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_webhook(url: str, notifier_type: str, text: str, secret: str | None = None) -> None:
    if notifier_type == "serverchan":
        resp = requests.post(url, data={"title": "开源雷达日报", "desp": text}, timeout=15)
    else:  # 默认飞书自定义机器人
        payload: dict = {"msg_type": "text", "content": {"text": text}}
        if secret:
            ts = str(int(time.time()))
            payload["timestamp"] = ts
            payload["sign"] = _feishu_sign(ts, secret)
        resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_notifier.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "feat: webhook 摘要推送（飞书/Server酱）"
```

---

### Task 9: 列表自动维护 discover

**Files:**
- Create: `src/discover.py`
- Test: `tests/test_discover.py`

- [ ] **Step 1: 写失败测试**

`tests/test_discover.py`:
```python
import json

import src.discover as discover
from src.discover import _llm_filter, suggest, update_config_files


class StubClient:
    def __init__(self, org_items, repo_items):
        self.org_items = org_items
        self.repo_items = repo_items

    def search_trending(self, days=14, min_stars=1000, limit=30):
        return self.repo_items

    def _get(self, path, **params):
        class Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        if "search/users" in path:
            return Resp({"items": self.org_items})
        return Resp({"items": self.repo_items})


def _client():
    return StubClient(
        org_items=[{"login": "neworg"}, {"login": "google"}],
        repo_items=[
            {"full_name": "fresh/hot", "html_url": "h", "description": "d", "stargazers_count": 2000},
            {"full_name": "vllm-project/vllm", "html_url": "h", "description": "d", "stargazers_count": 5000},
        ],
    )


def test_suggest_merges_and_dedupes_candidates(tmp_path):
    (tmp_path / "settings.yaml").write_text("", encoding="utf-8")
    (tmp_path / "orgs.yaml").write_text("orgs: [google]\n", encoding="utf-8")
    (tmp_path / "repos.yaml").write_text("repos: [vllm-project/vllm]\n", encoding="utf-8")

    result = suggest(_client(), config_dir=tmp_path, llm_token=None, llm_model="m")
    assert result["added_orgs"] == ["neworg"]
    assert result["added_repos"] == ["fresh/hot"]
    assert result["orgs"] == ["google", "neworg"]
    assert result["repos"] == ["fresh/hot", "vllm-project/vllm"]


def test_llm_filter_returns_all_on_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(discover.requests, "post", boom)
    assert _llm_filter(["a", "b"], "组织", token="t", model="m") == ["a", "b"]


def test_llm_filter_parses_keep_list(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            keep = json.dumps({"keep": ["b"]})
            return {"choices": [{"message": {"content": f"```json\n{keep}\n```"}}]}

    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: Resp())
    assert _llm_filter(["a", "b"], "组织", token="t", model="m") == ["b"]


def test_llm_filter_without_token_returns_all():
    assert _llm_filter(["a"], "组织", token=None, model="m") == ["a"]


def test_update_config_files_preserves_other_keys(tmp_path):
    (tmp_path / "orgs.yaml").write_text("orgs: [google]\nnew_repo:\n  min_stars: 50\n", encoding="utf-8")
    (tmp_path / "repos.yaml").write_text("repos: [a/b]\n", encoding="utf-8")
    update_config_files({"orgs": ["google", "neworg"], "repos": ["a/b", "c/d"]}, config_dir=tmp_path)

    import yaml
    orgs = yaml.safe_load((tmp_path / "orgs.yaml").read_text(encoding="utf-8"))
    repos = yaml.safe_load((tmp_path / "repos.yaml").read_text(encoding="utf-8"))
    assert orgs["orgs"] == ["google", "neworg"]
    assert orgs["new_repo"] == {"min_stars": 50}
    assert repos["repos"] == ["a/b", "c/d"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_discover.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.discover'`

- [ ] **Step 3: 实现 discover**

`src/discover.py`:
```python
"""监控列表自动维护：发现候选组织/仓库，LLM 辅助过滤，回写 config（CI 中以 PR 提交）。"""
import json
from pathlib import Path

import requests
import yaml

from .collector import GitHubClient
from .config_loader import CONFIG_DIR, load_orgs, load_repos

CANDIDATE_ORG_MIN_FOLLOWERS = 20000
CANDIDATE_REPO_MIN_STARS = 1000
CANDIDATE_REPO_MAX_AGE_DAYS = 14


def _llm_filter(names: list[str], kind: str, token: str | None, model: str) -> list[str]:
    """让 LLM 判断哪些候选值得长期监控。无 token 或调用失败时保留全部（最终由人工 PR 把关）。"""
    if not token or not names:
        return names
    prompt = (
        f"以下是 GitHub {kind}候选列表：{json.dumps(names, ensure_ascii=False)}。"
        "请判断哪些属于知名科技公司或高质量开源项目，适合纳入技术雷达长期监控。"
        '仅输出 JSON 对象，形如 {"keep": ["name1", "name2"]}。'
    )
    try:
        resp = requests.post(
            "https://models.github.ai/inference/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=120,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        keep = set(json.loads(text).get("keep", []))
        return [n for n in names if n in keep]
    except Exception as e:  # noqa: BLE001
        print(f"LLM 过滤失败，保留全部候选: {e}")
        return names


def _find_orgs(client: GitHubClient, known: set[str]) -> list[str]:
    resp = client._get(
        "/search/users",
        q=f"type:org followers:>={CANDIDATE_ORG_MIN_FOLLOWERS}",
        sort="followers", order="desc", per_page=50,
    )
    resp.raise_for_status()
    known_lower = {k.lower() for k in known}
    return [it["login"] for it in resp.json().get("items", []) if it["login"].lower() not in known_lower]


def _find_repos(client: GitHubClient, known: set[str]) -> list[str]:
    items = client.search_trending(
        days=CANDIDATE_REPO_MAX_AGE_DAYS, min_stars=CANDIDATE_REPO_MIN_STARS, limit=30
    )
    return [it["full_name"] for it in items if it["full_name"] not in known]


def suggest(client: GitHubClient, config_dir: Path = CONFIG_DIR, llm_token: str | None = None, llm_model: str = "") -> dict:
    """返回合并去重后的完整列表与本次新增候选。"""
    org_cfg = load_orgs(config_dir)
    repo_cfg = load_repos(config_dir)

    added_orgs = _llm_filter(_find_orgs(client, set(org_cfg.orgs)), "组织", llm_token, llm_model)
    added_repos = _llm_filter(_find_repos(client, set(repo_cfg.repos)), "仓库", llm_token, llm_model)

    return {
        "orgs": sorted(set(org_cfg.orgs) | set(added_orgs)),
        "repos": sorted(set(repo_cfg.repos) | set(added_repos)),
        "added_orgs": added_orgs,
        "added_repos": added_repos,
    }


def update_config_files(result: dict, config_dir: Path = CONFIG_DIR) -> None:
    """把合并后的列表写回 YAML，保留文件中的其他配置节。"""
    for filename, key in (("orgs.yaml", "orgs"), ("repos.yaml", "repos")):
        path = config_dir / filename
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data[key] = result[key]
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_discover.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/discover.py tests/test_discover.py
git commit -m "feat: 监控列表候选发现与 LLM 过滤"
```

---

### Task 10: 主编排 main

**Files:**
- Create: `src/main.py`

main 是薄编排层，不做单测，用 `--dry-run` 真实验证（Step 3）。

- [ ] **Step 1: 实现 main**

`src/main.py`:
```python
"""oss-radar 入口：编排 采集 -> 分析 -> 报告 -> 通知。"""
import argparse
import os
from datetime import date
from pathlib import Path

from .analyzer import NoopAnalyzer, create_analyzer
from .collector import GitHubClient, collect_events
from .config_loader import load_orgs, load_repos, load_settings
from .notifier import build_summary, send_webhook
from .reporter import archive_docs, render_daily_report, write_report
from .state import State

BASE_DIR = Path(__file__).resolve().parent.parent


def run_daily(dry_run: bool = False) -> int:
    settings = load_settings()
    org_cfg = load_orgs()
    repo_cfg = load_repos()
    state = State.load()

    client = GitHubClient(cache=state.http_cache)
    events, failures = collect_events(client, org_cfg, repo_cfg, state)
    events = events[: settings.max_items_per_run]

    analyzer = create_analyzer(settings)
    try:
        analyses = analyzer.analyze(events)
    except Exception as e:  # noqa: BLE001 - LLM 失败降级，日报照常产出
        failures.append(f"LLM 分析失败，已降级为原始信息: {e}")
        analyses = NoopAnalyzer().analyze(events)

    today = date.today()
    report = render_daily_report(today, analyses, failures)

    if dry_run:
        print(report)
        return 0

    write_report(report, BASE_DIR / "reports", today)
    archive_docs(analyses, BASE_DIR / "archive", today)
    state.save()

    webhook = os.environ.get("WEBHOOK_URL")
    if settings.notifier_enabled and webhook:
        repo_slug = os.environ.get("GITHUB_REPOSITORY", "")
        report_url = f"https://github.com/{repo_slug}/blob/main/reports/{today.isoformat()}.md" if repo_slug else ""
        try:
            send_webhook(
                webhook,
                settings.notifier_type,
                build_summary(today.isoformat(), analyses, report_url),
                secret=os.environ.get("WEBHOOK_SECRET"),
            )
        except Exception as e:  # noqa: BLE001
            print(f"webhook 推送失败: {e}")

    print(f"完成：{len(analyses)} 条动态，{len(failures)} 个异常")
    return 0


def run_discover(dry_run: bool = False) -> int:
    import yaml

    from .discover import suggest, update_config_files

    settings = load_settings()
    client = GitHubClient()
    result = suggest(
        client,
        llm_token=os.environ.get("GITHUB_TOKEN"),
        llm_model=settings.github_models_model,
    )
    if dry_run:
        print(yaml.safe_dump(
            {"added_orgs": result["added_orgs"], "added_repos": result["added_repos"]},
            allow_unicode=True,
        ))
        return 0
    if not result["added_orgs"] and not result["added_repos"]:
        print("无新候选")
        return 0
    update_config_files(result)
    print(f"新增组织: {result['added_orgs']}")
    print(f"新增仓库: {result['added_repos']}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="oss-radar")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件、不推送、不改配置")
    parser.add_argument("--discover", action="store_true", help="列表自动维护模式")
    args = parser.parse_args()

    if args.discover:
        raise SystemExit(run_discover(dry_run=args.dry_run))
    raise SystemExit(run_daily(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 全量测试确认无回归**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 全部 40 个测试通过

- [ ] **Step 3: 本地 dry-run 真实验证**

Run: `.\.venv\Scripts\python.exe -m src.main --dry-run`
Expected: 终端打印一份 Markdown 日报（首次运行建立基线，内容为"今日无值得关注的新动态"或少量趋势条目）；不写入 reports/、data/（可用 `git status` 确认无新文件）。

> 无 GITHUB_TOKEN 时 GitHub API 限额 60 次/小时，本地验证足够；CI 中自动携带。

- [ ] **Step 4: 再跑一次 dry-run 验证增量逻辑**

Run: `.\.venv\Scripts\python.exe -m src.main`（**不带** --dry-run，写入基线）然后再 `.\.venv\Scripts\python.exe -m src.main --dry-run`
Expected: 第二次运行不再重复报告已见过的条目；`data/state.json` 已生成。

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat: 主编排入口（daily/discover/dry-run）"
```

---

### Task 11: GitHub Actions workflows

**Files:**
- Create: `.github/workflows/daily.yml`
- Create: `.github/workflows/discover.yml`

- [ ] **Step 1: 创建 daily.yml**

`.github/workflows/daily.yml`:
```yaml
name: daily-radar

on:
  schedule:
    - cron: '0 23 * * *'   # UTC 23:00 = 北京时间 07:00
  workflow_dispatch:        # 支持手动触发验证

permissions:
  contents: write           # 提交 reports/ archive/ data/
  models: read              # 调用 GitHub Models 推理 API

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run radar
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          WEBHOOK_URL: ${{ secrets.WEBHOOK_URL }}
          WEBHOOK_SECRET: ${{ secrets.WEBHOOK_SECRET }}
        run: python -m src.main

      - name: Commit results
        run: |
          git config user.name "oss-radar-bot"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add reports archive data
          git diff --cached --quiet || git commit -m "docs: daily report $(date -u +%F)"
          git push
```

- [ ] **Step 2: 创建 discover.yml**

`.github/workflows/discover.yml`:
```yaml
name: weekly-discover

on:
  schedule:
    - cron: '0 22 * * 0'   # UTC 周日 22:00 = 北京时间周一 06:00
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  models: read

jobs:
  discover:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Discover candidates
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python -m src.main --discover

      - name: Create PR with candidates
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          git config user.name "oss-radar-bot"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          branch="discover/$(date -u +%F)"
          git checkout -b "$branch"
          git add config/
          git diff --cached --quiet && echo "无候选变更" && exit 0
          git commit -m "chore: 监控列表候选 $(date -u +%F)"
          git push -u origin "$branch"
          gh pr create --title "chore: 监控列表候选更新 $(date -u +%F)" \
            --body "自动发现的候选组织/仓库（已经 LLM 初筛），请人工审核后合并；不合适的条目直接从 config 中删除再合。" \
            --base main
```

- [ ] **Step 3: 校验 YAML 语法**

Run: `.\.venv\Scripts\python.exe -c "import yaml, pathlib; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflows yaml ok')"`
Expected: 输出 `workflows yaml ok`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows
git commit -m "ci: 每日雷达与每周列表维护 workflow"
```

---

### Task 12: README 与上线验证

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README**

`README.md`:
```markdown
# oss-radar

每日自动扫描国内外大厂开源动态，LLM 生成中文技术雷达日报，为技术预研做准备。

## 工作原理

1. **采集**（GitHub Actions 每日 07:00 北京时间）：
   - 监控组织（`config/orgs.yaml`）7 天内创建且 star 达标的新仓库
   - 精选仓库（`config/repos.yaml`）的新 release、README 变更、star 激增
   - GitHub 趋势新仓库（Search API 代理）
2. **分析**：GitHub Models（内置 GITHUB_TOKEN，零配置）→ 中文简介/分类/亮点/推荐理由；
   可选 Gemini 备选；无 Key 自动降级为原始信息罗列
3. **产出**：`reports/YYYY-MM-DD.md` 日报 + `archive/` 原文归档 + `data/state.json` 增量状态，全部提交回本仓库
4. **通知**（可选）：飞书 / Server酱 webhook 推送摘要

## 快速开始

1. Fork 或 push 本仓库到你的 GitHub 账号
2. （可选）仓库 Settings → Secrets 添加：
   - `GEMINI_API_KEY`：改用 Gemini（`config/settings.yaml` 里 provider 设为 `gemini`）
   - `WEBHOOK_URL`：飞书自定义机器人或 Server酱地址，同时把 `settings.yaml` 的 `notifier.enabled` 改为 `true`
   - `WEBHOOK_SECRET`（可选）：飞书自定义机器人开启"签名校验"时填写，notifier 会自动附带 `timestamp` + `sign`
3. Actions 页签手动触发 `daily-radar` 验证，首次运行建立基线，次日开始产出增量日报

## 配置

| 文件 | 说明 |
|------|------|
| `config/orgs.yaml` | 监控组织列表 + 新仓库判定阈值（年龄/star） |
| `config/repos.yaml` | 精选跟踪仓库 |
| `config/settings.yaml` | LLM provider、单次分析上限、通知开关 |

## 列表自动维护

每周一 06:00（北京时间）`weekly-discover` 自动发现候选组织/仓库，LLM 初筛后以 PR 提交，
你审核合并即生效；不合适的条目删掉再合即可。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.\.venv\Scripts\python.exe -m pytest tests/ -v     # 测试
.\.venv\Scripts\python.exe -m src.main --dry-run   # 干跑，不写文件
```
```

- [ ] **Step 2: Commit 并推送到 GitHub**

```bash
git add README.md
git commit -m "docs: README 使用说明"
git branch -M main
git remote add origin https://github.com/<你的用户名>/oss-radar.git
git push -u origin main
```

- [ ] **Step 3: 线上手动触发验证**

在 GitHub 仓库页面 → Actions → `daily-radar` → Run workflow。
Expected: 运行成功；仓库出现 `reports/<日期>.md` 与 `data/state.json` 的 bot 提交。
再手动触发一次 `weekly-discover`，验证能产出候选 PR（或日志输出"无新候选"）。

---

## Self-Review 记录

- **Spec 覆盖**：设计文档的 6 个模块（collector/discover/analyzer/reporter/notifier/main）、三路数据源、增量基线、LLM 降级、PR 式列表维护、两个 workflow、中文日报、YAGNI 项（无数据库/无 Web/不追历史）均有对应任务。
- **占位符**：无 TBD/TODO，所有代码步骤含完整代码。
- **布局修订**：代码直接落在仓库根（复用 `ossignal` 仓库、不 `git init`），默认分支统一 `main`；设计文档引用路径校正为 `specs/`。
- **加固项**：`GitHubClient` 增加跨运行 ETag 条件请求（304 复用缓存，`http_cache` 随 `state.json` 持久化）；trending 事件写入 `seen_new_repos` 防跨日重复；`notifier` 支持飞书签名校验（`WEBHOOK_SECRET` 可选）。测试总数 40。
- **类型一致性**：`Event`/`Analysis`/`State`/`Settings`/`OrgConfig`/`RepoConfig` 字段在测试与实现中一致；`collect_events` 返回 `(events, failures)` 与 main 使用一致；`suggest`/`update_config_files` 的 dict 键（orgs/repos/added_orgs/added_repos）一致。
