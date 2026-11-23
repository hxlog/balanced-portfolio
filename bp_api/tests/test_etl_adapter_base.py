"""适配器公共工具测试：WAF 判定不能误伤 text/html 的正常行情响应。"""
from __future__ import annotations

from bp_etl.adapters.base import is_waf_html, json_body, SourceParseError


class Resp:
    def __init__(self, text: str, content_type: str = "text/html") -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}

    def json(self) -> object:
        import json

        return json.loads(self.text)


def test_normal_tencent_js_is_not_waf() -> None:
    resp = Resp('v_sh600036="1~招商银行~600036~43.26";', content_type="text/html; charset=UTF-8")
    assert is_waf_html(resp) is False


def test_html_page_is_waf() -> None:
    assert is_waf_html(Resp("<html><body>WAF</body></html>")) is True
    assert is_waf_html(Resp("<!DOCTYPE html><html>501</html>")) is True


def test_json_body_works_for_tencent_like_html_content_type() -> None:
    resp = Resp('{"code":0,"data":{}}', content_type="text/html; charset=UTF-8")
    assert json_body(resp, source="tencent_kline") == {"code": 0, "data": {}}


def test_json_body_rejects_html() -> None:
    import pytest

    with pytest.raises(SourceParseError):
        json_body(Resp("<html>WAF</html>"), source="tencent_kline")
