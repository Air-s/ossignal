import src.notifier as notifier
from src.analyzer import Analysis
from src.collector import Event
from src.notifier import build_summary, send_webhook


def ana(i):
    return Analysis(
        event=Event(kind="new_repo", repo=f"o/r{i}", title=f"t{i}", url="u", detail="d", stars=1),
        summary=f"简介{i}", category="大模型", highlights="", recommendation="",
    )


def test_build_summary_truncates_to_ten():
    text = build_summary("2026-11-18", [ana(i) for i in range(15)], "http://report")
    assert "共 15 条动态" in text
    assert "o/r9" in text
    assert "o/r10" not in text
    assert "等 15 条" in text
    assert "http://report" in text


def test_send_webhook_feishu_posts_text_message(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, data=None, timeout=None):
        captured.update(url=url, json=json, data=data)
        return Resp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_webhook("http://hook", "feishu", "hello")
    assert captured["json"] == {"msg_type": "text", "content": {"text": "hello"}}


def test_send_webhook_feishu_with_secret_adds_sign(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, data=None, timeout=None):
        captured.update(json=json)
        return Resp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_webhook("http://hook", "feishu", "hello", secret="s3cr3t")
    assert captured["json"]["content"]["text"] == "hello"
    assert "timestamp" in captured["json"]
    assert "sign" in captured["json"]


def test_send_webhook_serverchan_posts_form(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, data=None, timeout=None):
        captured.update(url=url, json=json, data=data)
        return Resp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_webhook("http://hook", "serverchan", "hello")
    assert captured["data"]["desp"] == "hello"
    assert captured["data"]["title"] == "开源雷达日报"
