from datetime import date

from src.analyzer import Analysis
from src.collector import Event
from src.reporter import (
    _interp_blocks,
    archive_docs,
    render_daily_html,
    render_daily_report,
    write_html_report,
    write_report,
)

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


def test_render_interpretation_field():
    a = ana("x/1", "大模型")
    a.interpretation = "解决XX问题，与YY对比，值得跟进"
    md = render_daily_report(DAY, [a], [])
    assert "技术解读: 解决XX问题" in md
    assert "定位: 简介" in md


def test_render_degraded_goes_to_separate_section():
    a = ana("x/1", "大模型")
    a.degraded = True
    md = render_daily_report(DAY, [a], [], ["LLM 解析失败"])
    assert "## 降级条目" in md
    assert "## 分析降级说明" in md
    assert "LLM 解析失败" in md
    # 降级条目不应出现在分类章节
    assert "## 大模型" not in md


def test_render_unknown_category_normalized():
    a = ana("x/1", "AI/ML")
    md = render_daily_report(DAY, [a], [])
    assert "## 其他" in md
    assert "## AI/ML" not in md


def test_redact_masks_secret_like_long_strings():
    from src.reporter import _redact
    # 40 位 GCP key 风格字符串应被脱敏
    assert "已脱敏" in _redact("key=AIzaSyA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    # 短字符串 / 正常中文不受影响
    assert _redact("这是一个正常的简介") == "这是一个正常的简介"
    assert _redact("支持量化") == "支持量化"


def test_render_redacts_secret_like_text():
    a = ana("x/1", "大模型")
    a.interpretation = "示例密钥 AIzaSyA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ 请勿泄露"
    md = render_daily_report(DAY, [a], [])
    assert "AIzaSyA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in md
    assert "已脱敏" in md


def test_redact_preserves_urls():
    from src.reporter import _redact
    text = "链接 https://github.com/storytold/craft-anything 请查看"
    assert "https://github.com/storytold/craft-anything" in _redact(text)


def test_redact_still_masks_secrets_alongside_urls():
    from src.reporter import _redact
    text = "链接 https://github.com/a/b 密钥 AIzaSyA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = _redact(text)
    assert "https://github.com/a/b" in out
    assert "AIzaSyA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in out
    assert "已脱敏" in out


def test_redact_preserves_repo_full_name():
    """仓库全名 owner/name（含长用户名）不应被脱敏，这是修复标题误伤的关键回归。"""
    from src.reporter import _redact
    # 真实案例：schmidt21402/hwid-spoofer 曾被打成 schm…[已脱敏]
    assert _redact("schmidt21402/hwid-spoofer") == "schmidt21402/hwid-spoofer"
    assert _redact("sergeijang/windows-11-activator") == "sergeijang/windows-11-activator"
    # 真实密钥前缀仍要脱敏
    assert "已脱敏" in _redact("ghp_abcdefghijklmnopqrstuvwxyz1234567890")
    assert "已脱敏" in _redact("sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD")


def test_redact_output_preserves_repo_name():
    """redact_output 兜底脚本同样不能误伤仓库名。"""
    from src.redact_output import redact_text
    assert redact_text("schmidt21402/hwid-spoofer") == "schmidt21402/hwid-spoofer"
    assert "已脱敏" in redact_text("AIzaSyA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ")


# ---- mermaid 与 HTML 卡片渲染 ----

def test_render_includes_mermaid_block_when_diagram_present():
    a = ana("x/1", "大模型")
    a.diagram = "flowchart LR\n  A-->B"
    md = render_daily_report(DAY, [a], [])
    assert "```mermaid" in md
    assert "flowchart LR" in md


def test_render_omits_mermaid_when_no_diagram():
    md = render_daily_report(DAY, [ana("x/1", "大模型")], [])
    assert "```mermaid" not in md


def test_interp_blocks_splits_by_bracket_headings():
    text = "【解决什么问题】痛点A。【核心机制】机制B。【值不值得跟进】建议C。"
    blocks = _interp_blocks(text)
    assert blocks == [
        ("解决什么问题", "痛点A。"),
        ("核心机制", "机制B。"),
        ("值不值得跟进", "建议C。"),
    ]


def test_interp_blocks_without_headings_is_single_block():
    text = "没有小标题的一段解读"
    blocks = _interp_blocks(text)
    assert blocks == [("", "没有小标题的一段解读")]


def test_render_html_contains_card_and_mermaid():
    a = ana("x/1", "大模型")
    a.interpretation = "【解决什么问题】痛点A。【核心机制】机制B。"
    a.diagram = "flowchart LR\n  A-->B"
    html_out = render_daily_html(DAY, [a], [])
    assert "<!DOCTYPE html>" in html_out
    assert 'class="card"' in html_out
    assert "mermaid" in html_out
    assert "flowchart LR" in html_out
    assert "解决什么问题" in html_out
    assert "核心机制" in html_out


def test_render_html_escapes_html_in_content():
    a = ana("x/1", "大模型")
    a.summary = "<script>alert(1)</script>"
    html_out = render_daily_html(DAY, [a], [])
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_write_html_report_creates_file(tmp_path):
    path = write_html_report("<!DOCTYPE html><html></html>", tmp_path / "reports", DAY)
    assert path.name == "2026-11-18.html"
    assert path.read_text(encoding="utf-8") == "<!DOCTYPE html><html></html>"
