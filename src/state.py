"""增量状态：记录仓库快照与已见新仓库，避免重复报告。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "data" / "state.json"

# seen 软治理：只保留最近 N 天内见过的仓库，避免旧仓库被永久屏蔽、同时防止无限膨胀。
SEEN_MAX_AGE_DAYS = 90
SEEN_MAX_ITEMS = 5000


class State:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.repos: dict = data.get("repos", {})
        self.seen_new_repos: set[str] = set(data.get("seen_new_repos", []))
        # 已见仓库 → 首次记录时间（ISO 字符串）。老数据无时间戳时视为当前时间。
        self.seen_since: dict[str, str] = data.get("seen_since", {})
        self.http_cache: dict = data.get("http_cache", {})

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "State":
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def mark_seen(self, full_name: str) -> None:
        """记录一个仓库已见，并附带时间戳用于 TTL 治理。"""
        self.seen_new_repos.add(full_name)
        if full_name not in self.seen_since:
            self.seen_since[full_name] = datetime.now(timezone.utc).isoformat()

    def prune_seen(self) -> None:
        """软治理：过期（超 90 天）或超量的已见记录移除，让其重新进入视野。

        过期判定基于 seen_since 时间戳；老数据无时间戳的按最久处理，
        保留最近 SEEN_MAX_ITEMS 条（按时间戳排序）。
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=SEEN_MAX_AGE_DAYS)
        keep: set[str] = set()
        for name in self.seen_new_repos:
            since = self.seen_since.get(name)
            if since is None:
                # 无时间戳：保守保留（避免旧数据被误清导致回潮）
                keep.add(name)
                continue
            try:
                if datetime.fromisoformat(since) >= cutoff:
                    keep.add(name)
            except ValueError:
                keep.add(name)
        # 超量时按时间戳保留最近 SEEN_MAX_ITEMS 条
        if len(keep) > SEEN_MAX_ITEMS:
            with_ts = sorted(
                ((n, self.seen_since.get(n, "")) for n in keep),
                key=lambda x: x[1],
                reverse=True,
            )
            keep = {n for n, _ in with_ts[:SEEN_MAX_ITEMS]}
        self.seen_new_repos = keep
        self.seen_since = {n: self.seen_since[n] for n in keep if n in self.seen_since}

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.prune_seen()
        payload = {
            "repos": self.repos,
            "seen_new_repos": sorted(self.seen_new_repos),
            "seen_since": self.seen_since,
            "http_cache": self.http_cache,
            "last_run": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def repo_snapshot(self, repo: str) -> dict:
        return self.repos.get(repo, {})

    def update_repo(self, repo: str, *, stars: int, release: str | None, readme_sha: str | None) -> None:
        self.repos[repo] = {"stars": stars, "last_release": release, "readme_sha": readme_sha}
