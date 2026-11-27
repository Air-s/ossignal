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
    # 达标的 hot 记入 seen；已见过的 seen 保留；cold（star 不达标）不再写 seen，避免永久漏报
    assert "bigtech/seen" in state.seen_new_repos
    assert "bigtech/hot" in state.seen_new_repos
    assert "bigtech/cold" not in state.seen_new_repos


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


# ---- 质量闸门测试 ----

def test_quality_gate_blocks_mirror_fork_archived_empty():
    from src.collector import passes_quality_gate
    assert passes_quality_gate({"description": "Unmodified mirror of codec-d/cool_fox"}) is False
    assert passes_quality_gate({"description": "A real project", "fork": True}) is False
    assert passes_quality_gate({"description": "A real project", "archived": True}) is False
    assert passes_quality_gate({"description": "   "}) is False
    assert passes_quality_gate({"description": None}) is False
    assert passes_quality_gate({"description": "镜像 自动同步"}) is False
    assert passes_quality_gate({"description": "A legit deep learning library"}) is True


def test_trending_filters_out_mirror_repo():
    state = State()
    client = StubClient(
        repos_meta={"a/b": meta(0)},
        trending=[
            {"full_name": "x/mirror", "html_url": "h", "description": "Unmodified mirror of foo", "stargazers_count": 300},
            {"full_name": "x/real", "html_url": "h", "description": "A useful tool", "stargazers_count": 300},
        ],
    )
    events, _ = collect_events(client, ORG_CFG, REPO_CFG, state)
    assert [e.repo for e in events] == ["x/real"]


def test_org_new_repo_blocks_mirror():
    state = State()
    client = StubClient(
        repos_meta={"a/b": meta(0)},
        org_repos={"bigtech": [
            {"full_name": "bigtech/mirror", "created_at": iso(1), "stargazers_count": 80, "html_url": "h", "description": "fork of upstream", "fork": True},
            {"full_name": "bigtech/real", "created_at": iso(1), "stargazers_count": 80, "html_url": "h", "description": "real project"},
        ]},
    )
    events, _ = collect_events(client, ORG_CFG, REPO_CFG, state)
    assert [e.repo for e in events] == ["bigtech/real"]
