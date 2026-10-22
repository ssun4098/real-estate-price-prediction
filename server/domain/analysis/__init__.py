"""사업성 계산 엔진 (예전 domain/engine.py 를 주제별로 나눈 것. 함수 내용은 그대로).

밖에서는 이 두 개만 쓰면 됩니다.
    analyze(입력)              → 계산 결과
    validate_snapshot(저장본)  → 저장본을 믿지 않고 다시 계산한 결과

파일 지도 (계산 순서대로)
    engine.py        전체 순서: analyze, validate_snapshot, 지표(_okr)
    development.py   ① 개발 규모: 연면적·공급 세대수
    comparables.py   ② 비교사례 고르는 규칙: 기간·같은 동·반경
    revenue.py       ③ 분양 수입
    land_price.py    ④ 토지 매입가
    costs.py         ⑤ 사업비·예산 배분·금융비
    cashflow.py      ⑥ 현금흐름
    common.py        공통 도구: 숫자·날짜 검사, 통계, 비밀값 제거

부르는 방향: engine → (development, revenue, land_price, costs, cashflow) → comparables → common
"""
from server.domain.analysis.engine import analyze, validate_snapshot

__all__ = ["analyze", "validate_snapshot"]
