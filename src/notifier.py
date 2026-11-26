"""webhook 摘要推送：飞书自定义机器人 / Server酱。"""
import base64
import hashlib
import hmac
import time

import requests

from .analyzer import Analysis


def build_summary(day_str: str, analyses: list[Analysis], report_url: str) -> str:
    lines = [f"开源雷达日报 {day_str}", f"共 {len(analyses)} 条动态："]
    for a in analyses[:10]:
        lines.append(f"· [{a.category}] {a.event.repo} - {a.summary}")
    if len(analyses) > 10:
        lines.append(f"... 等 {len(analyses)} 条")
    if report_url:
        lines.append(f"完整报告: {report_url}")
    return "\n".join(lines)


def _feishu_sign(timestamp: str, secret: str) -> str:
    """飞书自定义机器人签名：HMAC-SHA256(key=f"{ts}\\n{secret}", msg="") 再 base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_webhook(url: str, notifier_type: str, text: str, secret: str | None = None) -> None:
    if notifier_type == "serverchan":
        resp = requests.post(url, data={"title": "开源雷达日报", "desp": text}, timeout=15)
    else:  # 默认飞书自定义机器人
        payload: dict = {"msg_type": "text", "content": {"text": text}}
        if secret:
            ts = str(int(time.time()))
            payload["timestamp"] = ts
            payload["sign"] = _feishu_sign(ts, secret)
        resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
