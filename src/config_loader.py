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
    trending_days: int
    trending_min_stars: int
    trending_limit: int
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
        github_models_model=llm.get("openai", {}).get("model", "openai/gpt-4o-mini"),
        gemini_model=llm.get("gemini", {}).get("model", "gemini-2.0-flash"),
        max_items_per_run=raw.get("analysis", {}).get("max_items_per_run", 30),
        trending_days=raw.get("analysis", {}).get("trending_days", 1),
        trending_min_stars=raw.get("analysis", {}).get("trending_min_stars", 100),
        trending_limit=raw.get("analysis", {}).get("trending_limit", 20),
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
