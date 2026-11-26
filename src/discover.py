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
