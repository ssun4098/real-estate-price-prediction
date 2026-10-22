"""대시보드 화면. frontend/build/V6.template.html 에 샘플 선반 자료를 끼워 넣어 요청마다 만든다.
(예전처럼 V6.html 파일을 디스크에 쓰지 않는다.)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.web import html

router = APIRouter(include_in_schema=False)

SNAPSHOT_MARKER = "<!--PF_SNAPSHOT-->"


@router.get("/")
@router.get("/index.html")
@router.get("/V6.html")
@router.get("/pf_study.html")
def dashboard(request: Request):
    state = request.app.state
    return html(render_html(state.template, state.portfolio.entries(), state.portfolio.default_id()))


@router.get("/favicon.ico")
def favicon():
    return Response(status_code=204, media_type="image/x-icon")


def render_html(template: str, portfolio=None, default_sample_id=None) -> str:
    """window.__PF_SNAPSHOT__ / __PF_PORTFOLIO__ / __PF_DEFAULT_SAMPLE_ID__ 를 심은 HTML."""
    portfolio = portfolio or []
    default_sample = next((item for item in portfolio if item.get("id") == default_sample_id), None)
    if not default_sample:
        default_sample_id = None
    script = ("<script>window.__PF_SNAPSHOT__=" + _inert_json(default_sample["snapshot"] if default_sample else None) +
              ";window.__PF_PORTFOLIO__=" + _inert_json(portfolio) +
              ";window.__PF_DEFAULT_SAMPLE_ID__=" + _inert_json(default_sample_id) + ";</script>")
    # 브라우저는 앞 1024바이트에서만 문자셋을 찾으므로 meta 태그를 자료보다 앞에 둔다.
    charset = '<meta charset="utf-8">'
    if SNAPSHOT_MARKER in template:
        rendered = template.replace(SNAPSHOT_MARKER, script)
        return rendered.replace("<head>", "<head>" + charset, 1) if "<head>" in rendered else charset + rendered
    if "<head>" in template:
        return template.replace("<head>", "<head>" + charset + script, 1)
    return charset + script + template


def _inert_json(value) -> str:
    """<script> 안에 넣어도 태그를 깨고 나오지 못하는 JSON."""
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
