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
