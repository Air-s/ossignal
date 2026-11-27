"""日报 Markdown 渲染、写文件、原文归档。"""
import re
from datetime import date
from pathlib import Path

from .analyzer import Analysis

CATEGORY_ORDER = ["AI基础设施", "大模型", "数据库", "DevOps", "前端", "安全", "其他", "未分类"]

# 形似密钥的长串（连续 20+ 位字母数字/hex/base64），用于脱敏，
# 避免 LLM 幻觉或原文中夹带的字符串被 GitHub secret scanning 误判为密钥而阻断 push。
_SECRETISH_RE = re.compile(r"[A-Za-z0-9+/_.\-]{20,}")

# 已知密钥前缀（GCP/OAuth/Generic），只要出现就整段打码，覆盖含 "." 等分隔符的情况。
_SECRET_PREFIXES = ("AIza", "GOCSPX", "ya29.", "ghp_", "gho_", "ghu_", "github_pat_", "sk-", "AKIA", "ASIA")


def _redact(text: str) -> str:
    """把形似密钥的长串打码，防止 GitHub 推送保护误报阻断日报提交。

    注意：跳过 URL（http/https）与 Markdown 链接，避免破坏仓库链接。
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
            p = _SECRETISH_RE.sub(lambda m: m.group(0)[:4] + "…[已脱敏]", p)
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
