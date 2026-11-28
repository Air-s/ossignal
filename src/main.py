"""oss-radar 入口：编排 采集 -> 分析 -> 报告 -> 通知。"""
import argparse
import os
from datetime import date
from pathlib import Path

from .analyzer import NoopAnalyzer, create_analyzer
from .collector import GitHubClient, collect_events
from .config_loader import load_orgs, load_repos, load_settings
from .notifier import build_summary, send_webhook
from .reporter import (
    archive_docs,
    render_daily_html,
    render_daily_report,
    write_html_report,
    write_report,
)
from .state import State

BASE_DIR = Path(__file__).resolve().parent.parent


def run_daily(dry_run: bool = False) -> int:
    settings = load_settings()
    org_cfg = load_orgs()
    repo_cfg = load_repos()
    state = State.load()

    client = GitHubClient(cache=state.http_cache)
    events, failures = collect_events(
        client, org_cfg, repo_cfg, state,
        trending_days=settings.trending_days,
        trending_min_stars=settings.trending_min_stars,
        trending_limit=settings.trending_limit,
    )

    analyzer = create_analyzer(settings)
    llm_errors: list[str] = []
    try:
        analyses = analyzer.analyze(events)
        llm_errors = getattr(analyzer, "last_errors", [])
    except Exception as e:  # noqa: BLE001 - LLM 失败降级，日报照常产出
        llm_errors.append(f"LLM 分析失败，已降级为原始信息: {e}")
        analyses = NoopAnalyzer().analyze(events)

    today = date.today()
    report = render_daily_report(today, analyses, failures, llm_errors)
    html_report = render_daily_html(today, analyses, failures, llm_errors)

    if dry_run:
        print(report)
        return 0

    write_report(report, BASE_DIR / "reports", today)
    html_path = write_html_report(html_report, BASE_DIR / "reports", today)
    archive_docs(analyses, BASE_DIR / "archive", today)
    state.save()

    webhook = os.environ.get("WEBHOOK_URL")
    if settings.notifier_enabled and webhook:
        repo_slug = os.environ.get("GITHUB_REPOSITORY", "")
        report_url = f"https://github.com/{repo_slug}/blob/main/reports/{today.isoformat()}.md" if repo_slug else ""
        try:
            send_webhook(
                webhook,
                settings.notifier_type,
                build_summary(today.isoformat(), analyses, report_url),
                secret=os.environ.get("WEBHOOK_SECRET"),
            )
        except Exception as e:  # noqa: BLE001
            print(f"webhook 推送失败: {e}")

    print(f"完成：{len(analyses)} 条动态，{len(failures)} 个异常")
    print(f"HTML 日报: {html_path}")
    return 0


def run_discover(dry_run: bool = False) -> int:
    import yaml

    from .discover import suggest, update_config_files

    settings = load_settings()
    client = GitHubClient()
    result = suggest(
        client,
        llm_token=os.environ.get("GITHUB_TOKEN"),
        llm_model=settings.github_models_model,
    )
    if dry_run:
        print(yaml.safe_dump(
            {"added_orgs": result["added_orgs"], "added_repos": result["added_repos"]},
            allow_unicode=True,
        ))
        return 0
    if not result["added_orgs"] and not result["added_repos"]:
        print("无新候选")
        return 0
    update_config_files(result)
    print(f"新增组织: {result['added_orgs']}")
    print(f"新增仓库: {result['added_repos']}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="oss-radar")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件、不推送、不改配置")
    parser.add_argument("--discover", action="store_true", help="列表自动维护模式")
    args = parser.parse_args()

    if args.discover:
        raise SystemExit(run_discover(dry_run=args.dry_run))
    raise SystemExit(run_daily(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
