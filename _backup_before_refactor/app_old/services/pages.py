"""Builds the dashboard HTML with the sample shelf embedded as inert JSON."""
from __future__ import annotations

import json

from app.services.portfolio import PortfolioService

HTML_SNAPSHOT_MARKER = "<!--PF_SNAPSHOT-->"


def _inert_json(value) -> str:
    # Prevents </script> breakout and keeps the payload valid inside a <script> block.
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_html(template: str, portfolio=None, default_sample_id=None) -> str:
    portfolio = portfolio or []
    default_sample = next((item for item in portfolio if item.get("id") == default_sample_id), None)
    snapshot = default_sample["snapshot"] if default_sample else None
    if not default_sample:
        default_sample_id = None
    script = ("<script>window.__PF_SNAPSHOT__=" + _inert_json(snapshot) +
              ";window.__PF_PORTFOLIO__=" + _inert_json(portfolio) +
              ";window.__PF_DEFAULT_SAMPLE_ID__=" + _inert_json(default_sample_id) + ";</script>")
    # Browsers sniff only the first 1024 bytes for charset; keep a meta tag ahead of the payload.
    charset = '<meta charset="utf-8">'
    if HTML_SNAPSHOT_MARKER in template:
        rendered = template.replace(HTML_SNAPSHOT_MARKER, script)
        return rendered.replace("<head>", "<head>" + charset, 1) if "<head>" in rendered else charset + rendered
    if "<head>" in template:
        return template.replace("<head>", "<head>" + charset + script, 1)
    return charset + script + template


class PageService:
    def __init__(self, template: str, portfolio: PortfolioService):
        self.template = template
        self.portfolio = portfolio

    def dashboard(self) -> str:
        return render_html(self.template, self.portfolio.entries(), self.portfolio.default_id())
