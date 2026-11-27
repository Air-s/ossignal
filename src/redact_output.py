"""提交前兜底脱敏：扫描 reports/ archive/ 下所有文件，把疑似密钥的长串打码。

GitHub 推送保护（secret scanning）会拦截含疑似密钥（GCP key、GitHub token、OAuth token 等）的提交。
LLM 输出或仓库原文里偶尔会夹带形似密钥的字符串（多为误报），在 push 前统一打码，避免日报提交被阻断。

用法：python -m src.redact_output
"""
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 已知密钥前缀 + 一般长串
_SECRET_PREFIXES = ("AIza", "GOCSPX", "ya29.", "ghp_", "gho_", "ghu_", "github_pat_", "sk-", "AKIA", "ASIA")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/_.\-]{20,}")


def redact_text(text: str) -> str:
    def _redact_one(segment: str) -> str:
        parts = re.split(r"(https?://[^\s\)\]\"']+)", segment)
        out = []
        for p in parts:
            if p.startswith(("http://", "https://")):
                out.append(p)
                continue
            for prefix in _SECRET_PREFIXES:
                p = re.sub(rf"{re.escape(prefix)}[A-Za-z0-9_.\-]+", lambda m: m.group(0)[:4] + "…[已脱敏]", p)
            p = _LONG_TOKEN.sub(lambda m: m.group(0)[:4] + "…[已脱敏]", p)
            out.append(p)
        return "".join(out)

    return _redact_one(text)


def main() -> None:
    changed = 0
    for d in ("reports", "archive"):
        root = BASE_DIR / d
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            original = f.read_text(encoding="utf-8")
            redacted = redact_text(original)
            if redacted != original:
                f.write_text(redacted, encoding="utf-8")
                changed += 1
    print(f"redact_output: 脱敏 {changed} 个文件")


if __name__ == "__main__":
    main()
