import base64

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
