"""Docker 없이 PC에서 바로 실행: python -m server

.env 를 읽고(이미 설정된 환경변수가 우선) 127.0.0.1:PUBLIC_PORT 로 서버를 켠다.
MySQL은 .env 의 MYSQL_HOST(기본 127.0.0.1) / MYSQL_PORT 로 접속한다.
"""
import os

import uvicorn

from server import ROOT
from server.env import ConfigurationError, load_environment


def main() -> None:
    try:
        load_environment(ROOT / ".env")
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    port = int(os.environ.get("PUBLIC_PORT", "") or 4175)
    print(f"개발사업성 분석 V6 → http://127.0.0.1:{port}/  (끄기: Ctrl+C)")
    uvicorn.run("server.main:create_app", factory=True, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    main()
