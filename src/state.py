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
