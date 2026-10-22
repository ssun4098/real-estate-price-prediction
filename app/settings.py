"""환경변수 → Settings. 설정은 전부 환경변수(.env)에서 옵니다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

from app import ROOT
from pf_config import read_keys


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        raise SystemExit(f"{name}: 정수 값이 필요합니다.") from None


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

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        keys = read_keys()  # 예전 서버(V6.py)와 같은 키 검증 규칙
        port = _int("PUBLIC_PORT", 4175)
        hosts = {h.strip().lower() for h in env("ALLOWED_HOSTS", "").split(",") if h.strip()}
        return cls(
            keys=keys,
            secrets=tuple(v for v in (*keys.values(), env("MYSQL_PASSWORD", "")) if v),
            database_url=_mysql_url(),
            db_connect_retries=_int("DB_CONNECT_RETRIES", 30),
            vworld_domain=env("VWORLD_DOMAIN", f"http://127.0.0.1:{port}"),
            public_port=port,
            allowed_hosts=frozenset(hosts or {f"127.0.0.1:{port}", f"localhost:{port}"}),
            enable_docs=env("ENABLE_DOCS", "").strip().lower() in ("1", "true", "yes", "on"),
            template_path=Path(env("TEMPLATE_PATH", ROOT / "web" / "V6.template.html")),
            samples_dir=Path(env("SAMPLES_DIR", ROOT / "samples")),
            model_dir=Path(env("MODEL_DIR", ROOT / "models")),
            model_entrypoint=env("MODEL_ENTRYPOINT", "").strip(),
        )
