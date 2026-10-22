"""사업성 계산 엔진 (예전 domain/engine.py 를 주제별로 나눈 것. 함수 내용은 그대로).

밖에서는 이 두 개만 쓰면 됩니다.
    analyze(입력)              → 계산 결과
    validate_snapshot(저장본)  → 저장본을 믿지 않고 다시 계산한 결과

analyze() 가 계산하는 순서 (engine.py)
    ① 개발 규모        development.py   대지면적·용적률 → 연면적·공급 세대수
    ② 분양 수입        revenue.py       비교 분양사례 단가 × 공급면적
    ③ 토지 매입가      land_price.py    토지 실거래 비교사례
    ④ 금융 단가·예산   costs.py         _apply_finance_price, _budget_allocation
    ⑤ 현금흐름         cashflow.py      월별 수입·지출, 분양률 곡선
    ⑥ 사업비 합계      costs.py         _costs (금융비가 현금흐름에 달려 있어 ⑤ 다음)
    ⑦ 지표             engine.py        _okr

그 밖의 파일
    comparables.py   ②③이 함께 쓰는 비교사례 고르는 규칙: 기간·같은 동·반경
    common.py        모두가 쓰는 공통 도구: 숫자·날짜 검사, 통계, 비밀값 제거

부르는 방향: engine → (development, revenue, land_price, costs, cashflow) → comparables → common
"""
from server.domain.analysis.engine import analyze, validate_snapshot

__all__ = ["analyze", "validate_snapshot"]
