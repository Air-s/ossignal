"""GitHub API 客户端与增量事件采集。"""
import base64
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from .config_loader import OrgConfig, RepoConfig
from .state import State

API = "https://api.github.com"

# 描述中命中这些关键词的仓库大概率是镜像/搬运/自动生成，直接拦下。
_MIRROR_MARKERS = (
    "mirror", "fork of ", "forked from", "unmodified mirror", "copy of ",
    "自动同步", "镜像", "搬运", "同步自", "fork自",
)

# 明显非技术/灰产关键词：外挂、作弊、破解、安装器、盗版软件等，不进技术雷达。
# 这些刷星灰产仓库命名有强规律：xxx-spoofer / xxx-cheat / xxx-sniper / xxx-bot /
# xxx-activator / xxx-crack，命名本身即暴露属性，命中即拦下。
# 用子串匹配（含词边界语义），对 "trading bot"、"sniping bot" 等空格分隔的也生效。
_SPAM_MARKERS = (
    "cheat", "cheats", "aimbot", "wallhack", "esp ", "undetect",
    "money dupe", "dupe", "crack", "cracked", "keygen", "trainer",
    "mod menu", "installer", "warez", "roblox", "aim ", "combat aid",
    "in-game", "外挂", "作弊", "破解", "刷", "辅助",
    # 刷星灰产高发命名（spoofer/sniper/bot/activator 等，几乎全是钓鱼或作弊工具）
    "spoofer", "sniper", " bot", "trading-bot", "trade-bot",
    "activator", "auto-buy", "autobuy", "auto-sell", "flipper",
    "airdrop", "claimer", "farming", "unlocker", "bypass",
    "fortnite", "cs2", "csgo", "valorant", "warzone", "pubg",
    "minecraft", "gta5", "gta v", "injector",
    "token grabber", "stealer", "infostealer", "info stealer",
    "exitlag", "hwid", "patcher", "patched", "pro-patcher", "pro patcher",
)


@dataclass
class Event:
    kind: str   # new_repo | new_release | readme_update | star_spike | trending
    repo: str   # "owner/name"
    title: str
    url: str
    detail: str
    stars: int = 0


def passes_quality_gate(item: dict) -> bool:
    """判断一个仓库是否值得进入日报（过滤镜像/fork/archived/空描述/灰产外挂）。

    item 为 GitHub API 返回的仓库对象（Search API 或 org repos 条目）。
    返回 False 表示应被拦下。

    灰产/镜像关键词同时检查 description 与 full_name：刷星灰产常把特征藏在
    仓库名里（如 xxx-patcher / xxx-installer），而描述写得很中性。
    """
    if item.get("fork"):
        return False
    if item.get("archived"):
        return False
    if item.get("disabled"):
        return False
    desc = (item.get("description") or "").strip().lower()
    if not desc:
        return False
    # 综合检查文本：描述 + 仓库全名（后者用小写，含 owner/name 与 - 连字符）
    full_name = (item.get("full_name") or "").strip().lower()
    haystack = f"{desc} {full_name}"
    for marker in _MIRROR_MARKERS:
        if marker.lower() in haystack:
            return False
    for marker in _SPAM_MARKERS:
        if marker.lower() in haystack:
            return False
    return True


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
                body = resp.json()
                # 列表类接口（org repos 等）响应体巨大，只缓存 ETag 不缓存 body，
                # 避免 state.json 无限膨胀；单对象接口才缓存完整 JSON。
                if isinstance(body, list):
                    self.cache[key] = {"etag": etag, "json": []}
                else:
                    self.cache[key] = {"etag": etag, "json": body}
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
            q=f"created:>{since} stars:>={min_stars} fork:false archived:false",
            sort="stars", order="desc", per_page=limit,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])


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
        # 先过 star 阈值再写 seen：避免当时不达标、后来涨上来的仓库被永久漏报。
        if item["stargazers_count"] < cfg.new_repo_min_stars:
            continue
        if not passes_quality_gate(item):
            state.mark_seen(full)  # 质量不达标的也标记已见，避免每日重复扫描
            continue
        state.mark_seen(full)
        events.append(Event(
            kind="new_repo", repo=full,
            title=full,  # 标题直接用仓库全名
            url=item["html_url"],
            detail=(item.get("description") or "")[:500],
            stars=item["stargazers_count"],
        ))
    return events


def collect_events(client: GitHubClient, org_cfg: OrgConfig, repo_cfg: RepoConfig, state: State,
                   trending_days: int = 1, trending_min_stars: int = 100,
                   trending_limit: int = 20) -> tuple[list[Event], list[str]]:
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
        for item in client.search_trending(days=trending_days, min_stars=trending_min_stars, limit=trending_limit):
            full = item["full_name"]
            if full in tracked or full in state.seen_new_repos:
                continue
            state.mark_seen(full)  # 记入 seen，避免同一趋势仓库跨日重复上报
            if not passes_quality_gate(item):
                continue  # 镜像/搬运/空描述等，拦下不进日报
            events.append(Event(
                kind="trending", repo=full,
                title=full,  # 标题直接用仓库全名，避免冗余前缀
                url=item["html_url"],
                detail=(item.get("description") or "")[:500],
                stars=item["stargazers_count"],
            ))
    except Exception as e:  # noqa: BLE001
        failures.append(f"trending: {e}")

    return events, failures
