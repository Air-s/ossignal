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
