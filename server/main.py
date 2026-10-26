"""앱 조립. 실행: uvicorn server.main:create_app --factory

요청 하나가 지나가는 길
    브라우저 → guard(접속 주소 검사) → features/*.py 의 라우터 함수 → domain(계산 엔진) / MySQL → ok() 응답
    어디서든 예외가 나면 guard 가 받아서 web.error_response() 로 표준 오류 응답을 만든다.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from server import db
from server.features import daily_load, model, pages, portfolio, public_data, snapshots, system
from server.features.land_store_mysql import MySqlLandStore
from server.features.applyhome_table import ApplyhomeTable
from server.features.land_trade_table import LandTradeTable
from server.settings import Settings
from server.web import SafeJSONResponse, add_security_headers, check_host, error_response, set_secrets
from server.domain.public_api import Collector

# 요청 URL에 주소·인증키가 섞이므로 접속 로그는 끈다 (예전 서버와 같음).
logging.getLogger("uvicorn.access").disabled = True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- 시작할 때 한 번: 여기서 만든 객체를 app.state 에 두고 라우터가 꺼내 쓴다 ---
        set_secrets(settings.secrets)
        sessions = db.connect(settings.database_url, settings.db_connect_retries)

        collector = Collector(settings.keys, settings.vworld_domain)
        if settings.land_trade_source == "table":
            # 토지 실거래: 직접 적재한 land_trade 테이블에서만 읽는다 (공공데이터 API 호출 없음).
            collector.land_store, collector.land_source = LandTradeTable(sessions), "table"
        else:
            # 토지 실거래: 공공데이터포털 API로 받고 앱 캐시 테이블(land_complete 등)에 보관.
            collector.land_store = MySqlLandStore(sessions, secrets=settings.secrets)
        if settings.applyhome_source == "table":
            # 청약홈 분양정보: 직접 적재한 applyhome_apt_notice / applyhome_apt_model 에서 읽는다 (API 호출 없음).
            collector.applyhome_table = ApplyhomeTable(sessions)

        bundled, bundled_default = portfolio.load_bundled_samples(settings.samples_dir)
        holder = model.ModelHolder(settings.model_dir, settings.model_entrypoint)
        holder.load()

        app.state.sessions = sessions
        app.state.template = settings.template_path.read_text("utf-8")
        app.state.public_data = public_data.PublicData(collector)
        app.state.snapshots = snapshots.SnapshotService(sessions)
        app.state.portfolio = portfolio.PortfolioService(sessions, bundled, bundled_default)
        app.state.model = holder
        # 매일 공공데이터를 받아 land_trade·applyhome 테이블에 넣는 백그라운드 작업
        app.state.daily_load = daily_load.DailyLoader(
            sessions, collector, enabled=settings.daily_load,
            run_at=settings.daily_load_time, months=settings.daily_load_months)
        app.state.daily_load.start()
        try:
            yield
        finally:
            # --- 끌 때 ---
            app.state.daily_load.stop()
            db.close(sessions)
            collector.keys.clear()

    app = FastAPI(
        title="개발사업성 분석 V6",
        version="6.0.0",
        lifespan=lifespan,
        default_response_class=SafeJSONResponse,
        docs_url="/api/docs" if settings.enable_docs else None,
        openapi_url="/api/openapi.json" if settings.enable_docs else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        try:
            check_host(request, settings.allowed_hosts)
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - 모든 예외를 표준 오류로 (상세 내용은 기록·노출하지 않음)
            return error_response(exc)
        return add_security_headers(response)

    # FastAPI가 직접 처리하는 오류(404, 405, 입력 형식 오류)도 같은 모양으로.
    app.add_exception_handler(HTTPException, lambda _request, exc: error_response(exc))
    app.add_exception_handler(RequestValidationError, lambda _request, exc: error_response(exc))

    for feature in (pages, system, public_data, snapshots, portfolio, model, daily_load):
        app.include_router(feature.router)
    return app
