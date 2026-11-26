"""日报 Markdown 渲染、写文件、原文归档。"""
import re
from datetime import date
from pathlib import Path

from .analyzer import Analysis

CATEGORY_ORDER = ["AI基础设施", "大模型", "数据库", "DevOps", "前端", "安全", "其他", "未分类"]


def _category_sort_key(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)


def render_daily_report(day: date, analyses: list[Analysis], failures: list[str]) -> str:
    lines = [f"# 开源技术雷达日报 {day.isoformat()}", ""]
    if not analyses:
        lines += ["今日无值得关注的新动态。", ""]

    groups: dict[str, list[Analysis]] = {}
    for a in analyses:
        groups.setdefault(a.category or "其他", []).append(a)

    for category in sorted(groups, key=_category_sort_key):
        lines.append(f"## {category}")
        lines.append("")
        for a in groups[category]:
            lines.append(f"### [{a.event.title}]({a.event.url})")
            lines.append("")
            lines.append(f"- Stars: {a.event.stars}")
            if a.summary:
                lines.append(f"- 简介: {a.summary}")
            if a.highlights:
                lines.append(f"- 亮点: {a.highlights}")
            if a.recommendation:
                lines.append(f"- 推荐理由: {a.recommendation}")
            lines.append("")

    if failures:
        lines.append("## 采集异常")
        lines.append("")
        lines += [f"- {f}" for f in failures]
        lines.append("")

    return "\n".join(lines)


def write_report(content: str, reports_dir: Path, day: date) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{day.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return path


def archive_docs(analyses: list[Analysis], archive_dir: Path, day: date) -> list[Path]:
    """把事件原文（release notes / README 摘录）按日期归档，返回写入的文件。"""
    written: list[Path] = []
    for a in analyses:
        if not a.event.detail:
            continue
        safe_name = re.sub(r"[^\w.-]", "_", a.event.repo)
        path = archive_dir / day.isoformat() / f"{safe_name}--{a.event.kind}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {a.event.title}\n\n来源: {a.event.url}\n\n---\n\n{a.event.detail}\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
