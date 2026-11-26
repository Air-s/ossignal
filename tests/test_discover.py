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
