"""계산 엔진과 공공 API 연결 (웹·DB를 모르는 순수 계산 코드).

    analysis/        사업성 계산: analyze(입력) → 결과, validate_snapshot(저장본 재계산)
                     주제별 파일 지도는 analysis/__init__.py
    public_api.py    공공 API 호출 창구 Collector (브이월드·공공데이터포털·도로명주소), ApiError
    survey.py        입지 조사, 필지 정보 보강 (KOSIS·SGIS·주변시설)
    land.py          용도지역·지목 분류, 토지비 계산
    boundary.py      필지가 여러 용도지역에 걸칠 때 면적 배분
    regions.py       시도·시군구·읍면동 목록
    persistence.py   저장할 때 빼야 할 자료 정리 (실시간 위치·분양사례 등)
    land_store.py    토지 실거래 캐시 규칙 (MySQL 저장소의 부모 클래스)
    geometry.py      도형 계산 라이브러리(shapely, pyproj) 불러오기
"""
