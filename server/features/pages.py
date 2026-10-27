"""대시보드 화면. frontend/build/V6.template.html 에 샘플 선반 자료를 끼워 넣어 만든다.
(예전처럼 V6.html 파일을 디스크에 쓰지 않는다.)

페이지는 약 19MB(화면 3.8MB + 예시 분석)라 요청마다 만들면 동시 접속 때 메모리가 크게 늘어 서버가 죽는다.
그래서 PageCache 가 한 번 만들어(gzip 압축본 포함) 기억해 두고, 샘플을 새로 저장하거나 기본 샘플을
바꿨을 때(PortfolioService.version() 이 바뀔 때)만 다시 만든다.
"""
from __future__ import annotations

import gzip
import json
import threading

from fastapi import APIRouter, Request
from starlette.responses import Response

from server.web import cached_html, checked_bytes

router = APIRouter(include_in_schema=False)

SNAPSHOT_MARKER = "<!--PF_SNAPSHOT-->"


@router.get("/")
@router.get("/index.html")
@router.get("/V6.html")
@router.get("/pf_study.html")
def dashboard(request: Request):
    state = request.app.state
    body, gzipped = state.page_cache.get(state.template, state.portfolio)
    return cached_html(body, gzipped, request)


@router.get("/favicon.ico")
def favicon():
    return Response(status_code=204, media_type="image/x-icon")


class PageCache:
    """완성된 화면 HTML(원본·gzip)을 기억해 둔다. 여러 요청이 동시에 와도 한 번만 만든다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._pages: tuple[bytes, bytes] | None = None

    def get(self, template: str, portfolio) -> tuple[bytes, bytes]:
        key = (id(template), portfolio.version())
        with self._lock:
            if self._key != key or self._pages is None:
                self._pages = None  # 새로 만드는 동안 예전 페이지를 먼저 놓아 메모리를 덜 쓴다
                text = render_html(template, portfolio.entries(), portfolio.default_id())
                body = checked_bytes(text.encode("utf-8"))
                del text
                self._pages, self._key = (body, gzip.compress(body, compresslevel=6)), key
            return self._pages


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
