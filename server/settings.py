"""환경변수 → Settings. 설정은 전부 환경변수(.env)에서 옵니다."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

from server import ROOT
from server.env import read_keys


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        raise SystemExit(f"{name}: 정수 값이 필요합니다.") from None


def _choice(name: str, allowed: tuple[str, ...]) -> str:
    """허용된 값 중 하나. 비어 있으면 첫 번째 값."""
    value = os.environ.get(name, "").strip().lower() or allowed[0]
    if value not in allowed:
        raise SystemExit(f"{name}: {' 또는 '.join(allowed)} 중 하나여야 합니다.")
    return value


def _clock(name: str, default: str) -> str:
    """HH:MM 형식의 시각."""
    value = os.environ.get(name, "").strip() or default
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise SystemExit(f"{name}: HH:MM 형식(예: 03:00)이어야 합니다.")
    return value


def _mysql_url() -> str:
    """DATABASE_URL이 있으면 그대로, 없으면 MYSQL_* 값으로 만든다."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    password = os.environ.get("MYSQL_PASSWORD", "")
    if not password:
        raise SystemExit("MYSQL_PASSWORD 또는 DATABASE_URL 환경변수가 필요합니다.")
    return "mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4".format(
        user=quote_plus(os.environ.get("MYSQL_USER", "root")),
        pw=quote_plus(password),
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=_int("MYSQL_PORT", 3306),
        db=quote_plus(os.environ.get("MYSQL_DATABASE", "v6")),
    )


@dataclass(frozen=True)
class Settings:
    keys: dict[str, str] = field(repr=False)        # 공공 API 인증키
    secrets: tuple[str, ...] = field(repr=False)    # 응답·저장에 절대 섞이면 안 되는 값 (인증키 + DB 비밀번호)
    database_url: str = field(repr=False)
    db_connect_retries: int
    vworld_domain: str
    public_port: int
    allowed_hosts: frozenset[str]
    enable_docs: bool
    template_path: Path
    samples_dir: Path
    model_dir: Path
    model_entrypoint: str
    land_trade_source: str                          # "table"(직접 적재한 DB) 또는 "api"(공공데이터포털)
    applyhome_source: str                           # 청약홈 분양정보: "table" 또는 "api"
    daily_load: bool                                # 매일 공공데이터 적재 (features/daily_load.py)
    daily_load_time: str                            # 실행 시각 HH:MM (한국 시각)
    daily_load_months: int                          # 토지 실거래를 다시 받는 개월 수

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        keys = read_keys()  # 키 형식 검증 (env.py)
        port = _int("PUBLIC_PORT", 4175)
        hosts = {h.strip().lower() for h in env("ALLOWED_HOSTS", "").split(",") if h.strip()}
        return cls(
            keys=keys,
            secrets=tuple(v for v in (*keys.values(), env("MYSQL_PASSWORD", "")) if v),
            database_url=_mysql_url(),
            db_connect_retries=_int("DB_CONNECT_RETRIES", 30),
            vworld_domain=env("VWORLD_DOMAIN", f"http://127.0.0.1:{port}"),
            public_port=port,
            allowed_hosts=frozenset(hosts | {f"127.0.0.1:{port}", f"localhost:{port}"}),  # 적은 주소는 기본값에 더해진다
            enable_docs=env("ENABLE_DOCS", "").strip().lower() in ("1", "true", "yes", "on"),
            template_path=Path(env("TEMPLATE_PATH", ROOT / "frontend" / "build" / "V6.template.html")),
            samples_dir=Path(env("SAMPLES_DIR", ROOT / "data" / "samples")),
            model_dir=Path(env("MODEL_DIR", ROOT / "data" / "models")),
            model_entrypoint=env("MODEL_ENTRYPOINT", "").strip(),
            land_trade_source=_choice("LAND_TRADE_SOURCE", ("table", "api")),
            applyhome_source=_choice("APPLYHOME_SOURCE", ("table", "api")),
            daily_load=_choice("DAILY_LOAD", ("on", "off")) == "on",
            daily_load_time=_clock("DAILY_LOAD_TIME", "03:00"),
            daily_load_months=max(1, min(12, _int("DAILY_LOAD_MONTHS", 3))),
        )
