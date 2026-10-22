"""V6 FastAPI 서버.

파일 지도 (위에서부터 읽으면 됩니다)
    main.py              앱 조립: 설정 → DB 연결 → 기능 객체 생성 → URL 등록
    settings.py          환경변수(.env) 읽기
    web.py               모든 요청에 공통인 규칙: 오류 응답, JSON 본문, 접속 주소 검사, 인증키 유출 차단
    db.py                테이블 정의, MySQL 연결, 기존 테이블 보호
    features/            기능별 파일. 한 파일 안에 "URL → 규칙 → DB" 가 위에서 아래로 들어 있음
        pages.py           대시보드 화면(HTML)
        system.py          상태 확인(/healthz, /api/status)
        public_data.py     공공 API 조회(필지·주소·실거래 등)와 지도 타일
        land_store.py      토지 실거래 캐시를 MySQL에 보관
        snapshots.py       사업성 계산(/api/analyze)과 분석 저장본
        portfolio.py       샘플 선반(고정 보관 분석)
        model.py           학습 모델 자리 (아직 모델 없음)

backend/ 의 계산 엔진·공공 API 모듈(pf_*.py)은 그대로 가져다 씁니다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# backend/ 모듈들은 `from pf_engine import ...` 처럼 폴더 없이 import 하므로 경로에 추가한다.
_backend = str(ROOT / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)
