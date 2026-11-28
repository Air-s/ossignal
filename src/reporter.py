"""日报 Markdown / HTML 渲染、写文件、原文归档。"""
import html
import re
from datetime import date
from pathlib import Path

from .analyzer import Analysis

CATEGORY_ORDER = ["AI基础设施", "大模型", "数据库", "DevOps", "前端", "安全", "其他", "未分类"]

# 已知密钥前缀（GCP/OAuth/Generic），只要出现就整段打码，覆盖含 "." 等分隔符的情况。
# 注意：不再用「20+ 位字母数字」的兜底长串规则——它会误伤 GitHub 仓库全名（owner/name
# 连起来常超 20 字符，如 schmidt21402/hwid-spoofer），把标题打成无意义的 "schm…[已脱敏]"。
# 真实密钥都有明确前缀（AIza/ghp_/sk- 等），精确匹配这些前缀已足够，不会误伤仓库名。
_SECRET_PREFIXES = ("AIza", "GOCSPX", "ya29.", "ghp_", "gho_", "ghu_", "github_pat_", "sk-", "AKIA", "ASIA")


def _redact(text: str) -> str:
    """把带已知前缀的密钥串打码，防止 GitHub 推送保护误报阻断日报提交。

    注意：跳过 URL（http/https）与 Markdown 链接，避免破坏仓库链接；
    只匹配已知密钥前缀，不再用宽泛长串规则，避免误伤 GitHub 仓库全名。
    """
    def _redact_one(segment: str) -> str:
        # 保护 URL：把 http(s)://... 拆出来，不脱敏
        parts = re.split(r"(https?://[^\s\)\]\"']+)", segment)
        out = []
        for p in parts:
            if p.startswith(("http://", "https://")):
                out.append(p)  # URL 原样保留
                continue
            for prefix in _SECRET_PREFIXES:
                p = re.sub(
                    rf"{re.escape(prefix)}[A-Za-z0-9_.\-]+",
                    lambda m: m.group(0)[:4] + "…[已脱敏]",
                    p,
                )
            out.append(p)
        return "".join(out)

    return _redact_one(text)


def _category_sort_key(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)


def _normalize_category(category: str) -> str:
    """把 LLM 可能返回的异常分类名规整到白名单，未知分类归入「其他」。"""
    c = (category or "").strip()
    return c if c in CATEGORY_ORDER else "其他"


def render_daily_report(day: date, analyses: list[Analysis], failures: list[str],
                        llm_errors: list[str] | None = None) -> str:
    """渲染日报。failures 为采集异常；llm_errors 为 LLM 分析降级信息，分章节展示。"""
    lines = [f"# 开源技术雷达日报 {day.isoformat()}", ""]
    if not analyses:
        lines += ["今日无值得关注的新动态。", ""]

    # 正文与降级分开展示：降级条目（degraded=True）不进正文，归入「降级条目」章节
    body = [a for a in analyses if not a.degraded]
    degraded = [a for a in analyses if a.degraded]

    groups: dict[str, list[Analysis]] = {}
    for a in body:
        cat = _normalize_category(a.category)
        groups.setdefault(cat, []).append(a)

    for category in sorted(groups, key=_category_sort_key):
        lines.append(f"## {category}")
        lines.append("")
        for a in groups[category]:
            _render_item(lines, a)

    if degraded:
        lines.append("## 降级条目")
        lines.append("")
        lines.append("> 以下条目因 LLM 分析失败，仅保留原始信息，未做技术解读。")
        lines.append("")
        for a in degraded:
            _render_item(lines, a)

    if llm_errors:
        lines.append("## 分析降级说明")
        lines.append("")
        lines += [f"- {e}" for e in llm_errors]
        lines.append("")

    if failures:
        lines.append("## 采集异常")
        lines.append("")
        lines += [f"- {f}" for f in failures]
        lines.append("")

    return "\n".join(lines)


def _render_item(lines: list[str], a: Analysis) -> None:
    """渲染单条动态为一个小节（标题 + 定位 + 解读 + 亮点 + 推荐 + 建议动作）。"""
    lines.append(f"### [{a.event.title}]({a.event.url})")
    lines.append("")
    lines.append(f"- Stars: {a.event.stars}")
    if a.summary:
        lines.append(f"- 定位: {_redact(a.summary)}")
    if a.interpretation:
        lines.append(f"- 技术解读: {_redact(a.interpretation)}")
    if a.highlights:
        lines.append(f"- 亮点: {_redact(a.highlights)}")
    if a.recommendation:
        lines.append(f"- 推荐理由: {_redact(a.recommendation)}")
    if a.diagram:
        lines.append("")
        lines.append("架构图：")
        lines.append("")
        lines.append("```mermaid")
        lines.append(a.diagram.strip())
        lines.append("```")
    lines.append("")


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
            f"# {a.event.title}\n\n来源: {a.event.url}\n\n---\n\n{_redact(a.event.detail)}\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


_HTML_CSS = """
:root {
  --bg: #ffffff; --surface: #f7f7f5; --text: #1a1a1a; --muted: #666666;
  --border: #e5e5e0; --accent: #378ADD; --accent-bg: #E6F1FB;
  --teal: #0F6E56; --teal-bg: #E1F5EE; --amber: #854F0B; --amber-bg: #FAEEDA;
  --red: #A32D2D; --red-bg: #FCEBEB;
}
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem; background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; line-height: 1.65; }
.container { max-width: 860px; margin: 0 auto; }
h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; }
.subtitle { color: var(--muted); font-size: 13px; margin: 0 0 1.5rem; }
.section-title { font-size: 16px; font-weight: 600; margin: 2rem 0 1rem;
  padding-left: 10px; border-left: 3px solid var(--accent); }
.card { background: var(--bg); border: 1px solid var(--border); border-radius: 12px;
  padding: 1.25rem 1.5rem; margin-bottom: 1.25rem; }
.card-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.repo-name { font-size: 16px; font-weight: 600; color: var(--accent); }
.repo-name a { color: inherit; text-decoration: none; }
.repo-name a:hover { text-decoration: underline; }
.tag { font-size: 11px; padding: 1px 8px; border-radius: 10px;
  background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 10px; margin: 0.9rem 0; }
.metric { background: var(--surface); border-radius: 8px; padding: 0.6rem 0.8rem; }
.metric .label { font-size: 11px; color: var(--muted); }
.metric .value { font-size: 18px; font-weight: 600; }
.field { margin: 0.5rem 0; font-size: 14px; }
.field .key { font-weight: 600; color: var(--text); }
.interp { margin: 0.5rem 0; font-size: 14px; }
.interp .i-title { font-weight: 600; color: var(--teal); }
.interp .i-title::before { content: ""; display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; background: var(--teal); margin-right: 6px; vertical-align: middle; }
.interp .i-body { color: var(--text); margin: 0.2rem 0 0.6rem; }
.flow-title { font-size: 13px; font-weight: 600; margin: 1rem 0 0.5rem; color: var(--teal); }
.mermaid-box { background: var(--surface); border-radius: 8px; padding: 1rem; overflow-x: auto; }
.action-box { background: var(--amber-bg); color: var(--amber); border-radius: 8px;
  padding: 0.6rem 0.9rem; margin-top: 0.8rem; font-size: 13px; }
.degraded-note { background: var(--red-bg); color: var(--red); border-radius: 8px;
  padding: 0.6rem 0.9rem; margin: 0.8rem 0 1.5rem; font-size: 13px; }
.mermaid-box svg { max-width: 100%; height: auto; }
"""


def _interp_blocks(interpretation: str) -> list[tuple[str, str]]:
    """把 interpretation 按【小标题】拆成 (标题, 正文) 段；无小标题则整体作为一段。"""
    if not interpretation:
        return []
    # 匹配 "【解决什么问题】xxx" 形式，允许正文跨到下一个标题前
    parts = re.split(r"【([^】]+)】", interpretation)
    blocks: list[tuple[str, str]] = []
    # parts[0] 是首个标题前的引导文字（可能为空）
    if parts[0].strip():
        blocks.append(("", parts[0].strip()))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            blocks.append((title, body))
    return blocks


def _html_escape(text: str) -> str:
    return html.escape(text, quote=False)


def _kind_label(kind: str) -> str:
    return {
        "new_repo": "新仓库", "new_release": "新发布", "readme_update": "README 更新",
        "star_spike": "Star 激增", "trending": "趋势",
    }.get(kind, kind)


def render_daily_html(day: date, analyses: list[Analysis], failures: list[str],
                      llm_errors: list[str] | None = None) -> str:
    """渲染 HTML 卡片版日报（内嵌 mermaid.js，本地/附件可看）。"""
    body = [a for a in analyses if not a.degraded]
    degraded = [a for a in analyses if a.degraded]

    groups: dict[str, list[Analysis]] = {}
    for a in body:
        cat = _normalize_category(a.category)
        groups.setdefault(cat, []).append(a)

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>开源技术雷达日报 {day.isoformat()}</title>",
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>',
        f"<style>{_HTML_CSS}</style>",
        "</head>",
        "<body>",
        '<div class="container">',
        f'<h1>开源技术雷达日报 <span style="font-weight:400;color:var(--muted)">{day.isoformat()}</span></h1>',
        '<p class="subtitle">每条动态附带「技术解读 + 架构流程图 + 建议动作」</p>',
    ]

    if not analyses:
        parts.append('<p>今日无值得关注的新动态。</p>')

    for category in sorted(groups, key=_category_sort_key):
        parts.append(f'<h2 class="section-title">{_html_escape(category)}</h2>')
        for a in groups[category]:
            parts.append(_render_html_item(a))

    if degraded:
        parts.append('<h2 class="section-title">降级条目</h2>')
        parts.append('<div class="degraded-note">以下条目因 LLM 分析失败，仅保留原始信息，未做技术解读。</div>')
        for a in degraded:
            parts.append(_render_html_item(a))

    if llm_errors:
        parts.append('<h2 class="section-title">分析降级说明</h2>')
        parts.append('<div class="card"><ul>' + "".join(
            f"<li>{_html_escape(e)}</li>" for e in llm_errors) + "</ul></div>")

    if failures:
        parts.append('<h2 class="section-title">采集异常</h2>')
        parts.append('<div class="card"><ul>' + "".join(
            f"<li>{_html_escape(f)}</li>" for f in failures) + "</ul></div>")

    parts.append("</div>")
    parts.append("<script>")
    parts.append("mermaid.initialize({ startOnLoad: true, theme: 'default', flowchart: { curve: 'basis' } });")
    parts.append("</script>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def _render_html_item(a: Analysis) -> str:
    """渲染单条动态为 HTML 卡片。"""
    url = _html_escape(a.event.url)
    name = _html_escape(a.event.repo)
    title = _html_escape(a.event.title)
    pieces: list[str] = ['<div class="card">']

    pieces.append('<div class="card-head">')
    pieces.append(f'<span class="repo-name"><a href="{url}" target="_blank" rel="noopener">{name}</a></span>')
    pieces.append(f'<span class="tag">{_html_escape(_kind_label(a.event.kind))}</span>')
    pieces.append(f'<span class="tag">{_html_escape(a.category)}</span>')
    pieces.append("</div>")

    pieces.append('<div class="metrics">')
    pieces.append(f'<div class="metric"><div class="label">Stars</div><div class="value">{a.event.stars}</div></div>')
    if title and title != name:
        pieces.append(f'<div class="metric" style="grid-column:1/-1"><div class="label">动态</div><div class="value" style="font-size:14px">{title}</div></div>')
    pieces.append("</div>")

    if a.summary:
        pieces.append(f'<div class="field"><span class="key">定位：</span>{_html_escape(_redact(a.summary))}</div>')

    if a.interpretation:
        blocks = _interp_blocks(a.interpretation)
        if blocks:
            pieces.append('<div class="interp">')
            for title_txt, body_txt in blocks:
                if title_txt:
                    pieces.append(f'<div class="i-title">{_html_escape(title_txt)}</div>')
                pieces.append(f'<div class="i-body">{_html_escape(_redact(body_txt))}</div>')
            pieces.append("</div>")
        else:
            pieces.append(f'<div class="field"><span class="key">技术解读：</span>{_html_escape(_redact(a.interpretation))}</div>')

    if a.highlights:
        pieces.append(f'<div class="field"><span class="key">亮点：</span>{_html_escape(_redact(a.highlights))}</div>')

    if a.diagram:
        pieces.append('<div class="flow-title">技术架构 / 数据流</div>')
        pieces.append('<div class="mermaid-box"><pre class="mermaid">')
        pieces.append(_html_escape(a.diagram.strip()))
        pieces.append("</pre></div>")

    if a.recommendation:
        pieces.append(f'<div class="action-box"><strong>建议动作：</strong>{_html_escape(_redact(a.recommendation))}</div>')

    pieces.append("</div>")
    return "\n".join(pieces)


def write_html_report(content: str, reports_dir: Path, day: date) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{day.isoformat()}.html"
    path.write_text(content, encoding="utf-8")
    return path
