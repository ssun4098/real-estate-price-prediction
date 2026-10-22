"""V6 FastAPI 서버.

파일 지도 (위에서부터 읽으면 됩니다)
    main.py              앱 조립: 설정 → DB 연결 → 기능 객체 생성 → URL 등록
    settings.py          환경변수(.env) → Settings
    env.py               .env 파일 읽기, 공공 API 키 형식 검사
    web.py               모든 요청에 공통인 규칙: 오류 응답, JSON 본문, 접속 주소 검사, 인증키 유출 차단
    db.py                테이블 정의, MySQL 연결, 기존 테이블 보호
    features/            기능별 파일. 한 파일 안에 "URL → 규칙 → DB" 가 위에서 아래로 들어 있음
        pages.py             대시보드 화면(HTML)
        system.py            상태 확인(/healthz, /api/status)
        public_data.py       공공 API 조회(필지·주소·실거래 등)와 지도 타일
        land_trade_table.py  토지 실거래를 직접 적재한 land_trade 테이블에서 읽기 (기본)
        land_store_mysql.py  토지 실거래를 API로 받아 앱 캐시 테이블에 보관 (LAND_TRADE_SOURCE=api 일 때)
        applyhome_table.py   청약홈 분양정보를 직접 적재한 applyhome_apt_* 테이블에서 읽기 (기본)
        snapshots.py         사업성 계산(/api/analyze)과 분석 저장본
        portfolio.py         샘플 선반(고정 보관 분석)
        model.py             학습 모델 자리 (아직 모델 없음)
    domain/              계산 엔진·공공 API 연결 (웹·DB를 모름). 목록은 domain/__init__.py

부르는 방향은 features → domain 한쪽뿐입니다. domain 은 features 를 import 하지 않습니다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 프로젝트 폴더
