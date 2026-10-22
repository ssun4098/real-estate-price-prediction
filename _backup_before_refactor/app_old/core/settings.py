"""Process configuration. All values come from environment variables."""
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


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    keys: dict[str, str] = field(repr=False)
    vworld_domain: str
    public_port: int
    allowed_hosts: frozenset[str]
    database_url: str = field(repr=False)
    db_connect_retries: int
    template_path: Path
    samples_dir: Path
    enable_docs: bool
    model_dir: Path
    model_entrypoint: str
    secrets: tuple[str, ...] = field(default=(), repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        keys = read_keys()  # same validation/decoding rules as the legacy server
        port = _int("PUBLIC_PORT", 4175)
        hosts = os.environ.get("ALLOWED_HOSTS", "").strip()
        allowed = frozenset(h.strip().lower() for h in hosts.split(",") if h.strip()) or \
            frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})

        password = os.environ.get("MYSQL_PASSWORD", "")
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            if not password:
                raise SystemExit("MYSQL_PASSWORD 또는 DATABASE_URL 환경변수가 필요합니다.")
            url = "mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4".format(
                user=quote_plus(os.environ.get("MYSQL_USER", "v6")),
                pw=quote_plus(password),
                host=os.environ.get("MYSQL_HOST", "db"),
                port=_int("MYSQL_PORT", 3306),
                db=quote_plus(os.environ.get("MYSQL_DATABASE", "v6")),
            )
        secrets = tuple(v for v in (*keys.values(), password) if v)
        return cls(
            keys=keys,
            vworld_domain=os.environ.get("VWORLD_DOMAIN", "http://127.0.0.1:%d" % port),
            public_port=port,
            allowed_hosts=allowed,
            database_url=url,
            db_connect_retries=_int("DB_CONNECT_RETRIES", 30),
            template_path=Path(os.environ.get("TEMPLATE_PATH", ROOT / "web" / "V6.template.html")),
            samples_dir=Path(os.environ.get("SAMPLES_DIR", ROOT / "samples")),
            enable_docs=_flag("ENABLE_DOCS"),
            model_dir=Path(os.environ.get("MODEL_DIR", ROOT / "models")),
            model_entrypoint=os.environ.get("MODEL_ENTRYPOINT", "").strip(),
            secrets=secrets,
        )
