"""토지 단가 모델의 입력 13개를 서버가 직접 만든다 (팀원 tools/build_context.py 와 같은 규칙).

자료: data/models/inputs/  (팀원 전달 자료 data/ 를 서버용으로 줄인 것. 변환 방법은 inputs/README.md)
    group_history.csv.gz    토지 그룹별 월간 거래단가 중앙값·면적 중앙값·거래 건수
    region_map.csv          시군구 코드 → 지표 지역 이름 (예: 11110 → 서울|종로구)
    macro_region_month.csv  지역·월별 거시 지표 6종 (지가변동률, 건축허가면적, ESI, 동행지수, M1, 비은행 대출)
    cofix_release.csv       COFIX 대상월·값·실제 공시일

날짜 규칙 (기준월 = forecast_month)
    입력월(feature_month) = 기준월 - 2개월     ← 거시 지표·과거 거래는 이 달 값만 쓴다
    예측 대상월(target_month) = 기준월 + 6개월
    COFIX 는 기준월 말일까지 실제로 공시된 가장 최근 값

없는 값은 0·이전 달·가까운 달로 채우지 않는다. 하나라도 없으면 InputsMissing 을 낸다.
"""
from __future__ import annotations

import csv
import gzip
import math
from dataclasses import dataclass
from pathlib import Path

INPUT_DIR = "inputs"
FEATURE_LAG_MONTHS = 2      # 지표 발표가 2개월 늦다는 학습 가정
HORIZON_MONTHS = 6          # 6개월 뒤를 예측
LOOKBACK_MONTHS = 6         # 최신 기준월에 그 그룹 거래가 없으면 최대 몇 달 앞 기준월까지 찾아볼지
MONTH_INDEX_BASE_YEAR = 2016

MACRO_COLUMNS = ("지가변동률", "건축허가면적", "경제심리지수_원계열", "동행종합지수_전월비", "M1_평잔_원계열", "비은행_주택관련대출")


class InputsMissing(ValueError):
    """예측에 필요한 자료가 없음. 0 으로 채우지 말고 '자료 없음'으로 알린다."""


# ---------------------------------------------------------------------------
# 월 계산 ("YYYY-MM" 문자열로 다룬다)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> "Month":
        try:
            year, month = (int(part) for part in str(text).strip()[:7].split("-"))
        except ValueError:
            raise ValueError(f"월은 YYYY-MM 형식이어야 합니다: {text}") from None
        if not 1 <= month <= 12:
            raise ValueError(f"월은 YYYY-MM 형식이어야 합니다: {text}")
        return cls(year, month)

    def plus(self, months: int) -> "Month":
        total = self.year * 12 + (self.month - 1) + months
        return Month(total // 12, total % 12 + 1)

    def last_day(self) -> str:
        nxt = self.plus(1)
        import datetime as dt
        return (dt.date(nxt.year, nxt.month, 1) - dt.timedelta(days=1)).isoformat()

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


# ---------------------------------------------------------------------------
# 입력 만들기
# ---------------------------------------------------------------------------
class InputBuilder:
    def __init__(self, model_dir: Path):
        folder = Path(model_dir) / INPUT_DIR
        self.history = _read_history(folder / "group_history.csv.gz")      # (그룹, 월) → (단가, 면적, 건수)
        self.regions = {r["lawd_cd"]: r for r in _read_csv(folder / "region_map.csv")}
        self.macro = {(r["지역키"], r["월"]): r for r in _read_csv(folder / "macro_region_month.csv")}
        self.cofix = sorted(_read_csv(folder / "cofix_release.csv"), key=lambda r: r["COFIX_공시일"])
        self.latest_month = self._latest_forecast_month()

    def _latest_forecast_month(self) -> Month:
        """자료가 모두 갖춰진 가장 최근 기준월 (거시 지표 마지막 달과 COFIX 공시 범위로 정해진다)."""
        last_macro = max(Month.parse(month) for _, month in self.macro)
        last_cofix_date = self.cofix[-1]["COFIX_공시일"]
        month = last_macro.plus(FEATURE_LAG_MONTHS)
        # 기준월 말일이 마지막 COFIX 공시가 있던 달을 넘으면, 그 사이 새 공시가 빠졌을 수 있어 쓰지 않는다.
        while month.last_day() > Month.parse(last_cofix_date).last_day():
            month = month.plus(-1)
        return month

    def build(self, group_key: str, forecast_month: Month) -> dict:
        """한 그룹·한 기준월의 입력. 원자료와 모델 입력 12개를 함께 돌려준다."""
        if forecast_month > self.latest_month:
            raise InputsMissing(f"{forecast_month} 기준월에 필요한 지표가 아직 없습니다 (최신 {self.latest_month}).")
        sgg = group_key.split("|", 1)[0]
        feature_month = forecast_month.plus(-FEATURE_LAG_MONTHS)

        history = self.history.get((group_key, str(feature_month)))
        if history is None:
            raise InputsMissing(f"{feature_month} 에 이 토지 그룹의 거래가 없습니다.")
        region = self.regions.get(sgg)
        if region is None:
            raise InputsMissing(f"지표 지역 대응표에 없는 시군구 코드입니다: {sgg}")
        macro = self.macro.get((region["입력지역키"], str(feature_month)))
        if macro is None:
            raise InputsMissing(f"{region['입력지역키']} 의 {feature_month} 거시 지표가 없습니다.")
        cofix = [r for r in self.cofix if r["COFIX_공시일"] <= forecast_month.last_day()]
        if not cofix:
            raise InputsMissing("기준월 이전에 공시된 COFIX 가 없습니다.")
        cofix = cofix[-1]

        raw = {name: float(macro[name]) for name in MACRO_COLUMNS}
        raw["신규취급액기준_COFIX"] = float(cofix["신규취급액기준_COFIX"])
        unit_price, median_area, trade_count = history
        context = {
            "landGroupKey": group_key,
            "region": f"{region['sido_nm']} {region['sigungu_nm']}",
            "regionMatch": region["지역대응방법"],
            "featureMonth": str(feature_month),
            "forecastMonth": str(forecast_month),
            "targetMonth": str(forecast_month.plus(HORIZON_MONTHS)),
            "cofixReleaseDate": cofix["COFIX_공시일"],
            "historyUnitPriceWonM2": unit_price,
            "historyMedianAreaM2": median_area,
            "historyTradeCount": trade_count,
            "raw": raw,
        }
        return {"context": context, "features": model_features(raw, unit_price, median_area, forecast_month)}

    def build_latest(self, group_key: str) -> dict:
        """최신 기준월부터 LOOKBACK_MONTHS 만큼 거슬러 올라가며, 자료가 다 있는 첫 기준월로 만든다.

        한 예측 안의 입력은 모두 같은 입력월 값이다 (달마다 섞지 않는다). 기준월이 다르면 예측 대상월도 다르다.
        """
        sgg = group_key.split("|", 1)[0]
        if sgg not in self.regions:
            raise InputsMissing(f"지표 지역 대응표에 없는 시군구 코드입니다: {sgg}")
        reasons = []
        for back in range(LOOKBACK_MONTHS):
            try:
                return self.build(group_key, self.latest_month.plus(-back))
            except InputsMissing as exc:
                reasons.append(str(exc))
        earliest = self.latest_month.plus(-(LOOKBACK_MONTHS - 1))
        if all("거래가 없습니다" in reason for reason in reasons):
            raise InputsMissing(f"최근 거래가 없는 토지 그룹입니다 ({earliest.plus(-FEATURE_LAG_MONTHS)} ~ "
                                f"{self.latest_month.plus(-FEATURE_LAG_MONTHS)} 사이 매달 거래 0건).")
        raise InputsMissing(f"최근 기준월({earliest} ~ {self.latest_month})에 쓸 수 있는 자료가 없습니다: {reasons[-1]}")


def model_features(raw: dict, history_unit_price: float, history_median_area: float, forecast_month: Month) -> dict:
    """원자료 → 모델 숫자 입력 12개 (팀원 linear_core.prepare_frame 과 같은 계산)."""
    month = forecast_month.month
    return {
        "지가변동률": raw["지가변동률"],
        "log_permit_area": math.log1p(raw["건축허가면적"]),
        "신규취급액기준_COFIX": raw["신규취급액기준_COFIX"],
        "경제심리지수_원계열": raw["경제심리지수_원계열"],
        "동행종합지수_전월비": raw["동행종합지수_전월비"],
        "log_m1_original": math.log1p(raw["M1_평잔_원계열"]),
        "log_nonbank_housing_loans": math.log1p(raw["비은행_주택관련대출"]),
        "log_history_median_area": math.log1p(history_median_area),
        "log_history_unit_price": math.log1p(history_unit_price),
        "forecast_month_index": float((forecast_month.year - MONTH_INDEX_BASE_YEAR) * 12 + month - 1),
        "forecast_month_sin": math.sin(2 * math.pi * month / 12),
        "forecast_month_cos": math.cos(2 * math.pi * month / 12),
    }


# ---------------------------------------------------------------------------
# 파일 읽기
# ---------------------------------------------------------------------------
def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_history(path: Path) -> dict:
    table = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            table[(row["land_group_key"], row["month"])] = (
                float(row["unit_price_won_m2"]), float(row["median_area_m2"]), int(row["trade_count"]))
    return table
