from datetime import date

from src.analyzer import Analysis
from src.collector import Event
from src.reporter import archive_docs, render_daily_report, write_report

DAY = date(2026, 11, 18)


def ana(repo, category, kind="new_release", detail="原文内容"):
    return Analysis(
        event=Event(kind=kind, repo=repo, title=f"{repo} 标题", url="http://u", detail=detail, stars=42),
        summary="简介", category=category, highlights="亮点", recommendation="推荐",
    )


def test_render_groups_by_category_with_order():
    analyses = [ana("x/1", "其他"), ana("x/2", "大模型"), ana("x/3", "数据库")]
    md = render_daily_report(DAY, analyses, [])
    assert md.startswith("# 开源技术雷达日报 2026-11-18")
    assert md.index("## 大模型") < md.index("## 数据库") < md.index("## 其他")
    assert "Stars: 42" in md
    assert "[x/1 标题](http://u)" in md


def test_render_empty_day():
    md = render_daily_report(DAY, [], [])
    assert "今日无值得关注的新动态" in md


def test_render_includes_failures_section():
    md = render_daily_report(DAY, [], ["org google: boom"])
    assert "## 采集异常" in md
    assert "org google: boom" in md


def test_write_report_creates_file(tmp_path):
    path = write_report("content", tmp_path / "reports", DAY)
    assert path.name == "2026-11-18.md"
    assert path.read_text(encoding="utf-8") == "content"


def test_archive_docs_sanitizes_filenames(tmp_path):
    written = archive_docs([ana("owner/repo", "大模型")], tmp_path, DAY)
    assert len(written) == 1
    assert written[0].name == "owner_repo--new_release.md"
    assert "原文内容" in written[0].read_text(encoding="utf-8")
    assert "http://u" in written[0].read_text(encoding="utf-8")
