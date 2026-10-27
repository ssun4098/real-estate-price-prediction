"""토지 단가 예측 모델 (팀원 CatBoost 23번 모델).

.env 에  MODEL_ENTRYPOINT=land_price_model:LandPricePredictor  로 켠다.

이 폴더에 함께 있어야 하는 것 (팀원 전달 자료 '개발자전달_CatBoost23_20261027')
    model.cbm         학습된 모델 (약 110MB). git 에 올리지 않고 직접 복사한다.
    model_info.json   모델 설명서. 입력 항목, 학습한 토지 그룹 목록, 목표값 변환(log1p) 등.
    inputs/           모델 입력을 만드는 자료 (land_price_inputs.py 가 읽는다)

모델이 하는 일
    시군구 × 지목 6그룹 × 용도지역 8그룹의 '6개월 뒤 월간 거래단가 중앙값(원/㎡)'을 예측한다.
    필지 하나의 감정가가 아니라 그 그룹의 대표 단가다.

입력 (POST /api/model/predict 의 "features") — 둘 중 하나
    1) 그룹만 주기: sggCode·jimok·landUse (또는 land_group_key), 선택으로 forecastMonth("YYYY-MM")
       → 서버가 inputs/ 자료로 숫자 12개를 만든다. forecastMonth 가 없으면 자료가 있는 가장 최근 기준월.
    2) 숫자 12개(NUMBER_FEATURES)까지 직접 주기 → 그대로 모델에 넣는다.
"""
from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from land_price_inputs import InputBuilder, InputsMissing, Month

MODEL_FILE = "model.cbm"
INFO_FILE = "model_info.json"

# 숫자 입력. 이름과 순서는 학습 때와 똑같아야 한다 (load 할 때 모델 파일·설명서와 대조한다).
NUMBER_FEATURES = (
    "지가변동률",
    "log_permit_area",            # log1p(건축허가면적)
    "신규취급액기준_COFIX",
    "경제심리지수_원계열",
    "동행종합지수_전월비",
    "log_m1_original",            # log1p(M1 평잔)
    "log_nonbank_housing_loans",  # log1p(비은행 주택관련대출)
    "log_history_median_area",    # log1p(입력월 그 그룹 거래 면적 중앙값)
    "log_history_unit_price",     # log1p(입력월 그 그룹 거래단가 중앙값)
    "forecast_month_index",       # (기준연도-2016)*12 + 기준월 - 1
    "forecast_month_sin",         # sin(2π·기준월/12)
    "forecast_month_cos",         # cos(2π·기준월/12)
)
GROUP_FEATURE = "land_group_key"
FEATURE_ORDER = NUMBER_FEATURES + (GROUP_FEATURE,)

# ---------------------------------------------------------------------------
# 토지 그룹: "시군구코드|지목그룹|용도지역그룹"   예) "11110|대|일반주거지역"
# 아래 표는 팀원 전처리 코드(build_land_trade2.py)의 대조표 그대로다.
# ---------------------------------------------------------------------------
MAIN_JIMOK = ("대", "전", "답", "임야", "공장용지")  # 이 다섯 개 말고는 모두 '기타'
OTHER_JIMOK = "기타"
ZONE_TABLE = {
    "전용주거지역": "제1종전용주거지역 제2종전용주거지역 전용주거지역",
    "일반주거지역": "제1종일반주거지역 제2종일반주거지역 제3종일반주거지역 일반주거지역",
    "준주거지역": "준주거지역",
    "상업지역": "중심상업지역 일반상업지역 근린상업지역 유통상업지역",
    "공업지역": "전용공업지역 일반공업지역 준공업지역",
    "녹지지역": "보전녹지지역 생산녹지지역 자연녹지지역",
    "비도시지역": "보전관리지역 생산관리지역 계획관리지역 관리지역 농림지역 자연환경보전지역 자연환경보전",
    "용도미지정 등": "용도미지정 개발제한구역 기타",
}
ZONE_OF = {name: group for group, names in ZONE_TABLE.items() for name in names.split()}


def zone_group(land_use) -> str:
    """원래 용도지역 이름 → 8그룹. 대조표에 없는 이름은 ValueError (추측해서 넣지 않는다)."""
    name = "".join(str(land_use or "").split())  # 띄어쓰기 제거
    if name in ZONE_OF:
        return ZONE_OF[name]
    raise ValueError(f"용도지역 '{land_use}' 를 모델의 8그룹에 대응할 수 없습니다.")


def jimok_group(jimok) -> str:
    name = str(jimok or "").strip()
    if not name:
        raise ValueError("지목이 비어 있습니다.")
    return name if name in MAIN_JIMOK else OTHER_JIMOK


def land_group_key(sgg_code, jimok, land_use) -> str:
    """시군구코드·지목·용도지역 → 모델이 쓰는 그룹 이름."""
    sgg = str(sgg_code or "").strip()
    if not (len(sgg) == 5 and sgg.isdigit()):
        raise ValueError("sggCode 는 시군구 코드 5자리 숫자여야 합니다.")
    return f"{sgg}|{jimok_group(jimok)}|{zone_group(land_use)}"


# ---------------------------------------------------------------------------
# 모델
# ---------------------------------------------------------------------------
class LandPricePredictor:
    name = "land-price-catboost"
    version = "unknown"  # load 할 때 모델의 학습 시각으로 바뀐다

    def load(self, model_dir: Path) -> None:
        from catboost import CatBoost  # catboost 는 모델을 켤 때만 필요

        model_dir = Path(model_dir)
        info = json.loads((model_dir / INFO_FILE).read_text(encoding="utf-8-sig"))
        model = CatBoost()
        model.load_model(str(model_dir / MODEL_FILE))

        # 코드·설명서·모델 파일이 서로 맞는지 확인. 하나라도 다르면 켜지 않는다.
        if tuple(info.get("input_features", ())) != FEATURE_ORDER or tuple(model.feature_names_) != FEATURE_ORDER:
            raise ValueError("모델(또는 model_info.json)의 입력 항목이 이 코드가 아는 13개와 다릅니다.")
        if info.get("target_transform") != "log1p" or info.get("forecast_horizon_months") != 6:
            raise ValueError("이 코드는 log1p 목표값·6개월 예측 모델만 다룹니다.")
        # 설명서와 다른 모델 파일(예: 예전 실험 모델)을 넣어 두면 켜지 않는다.
        params = info.get("model_parameters", {})
        if model.tree_count_ != info.get("stored_tree_count") or model.get_all_params().get("depth") != params.get("depth"):
            raise ValueError("model.cbm 이 model_info.json 과 다른 모델입니다. 같은 전달 자료의 두 파일을 함께 넣으세요.")

        self.model = model
        self.version = model.get_metadata().get("train_finish_time", "")[:16] or "unknown"
        self.training_groups = frozenset(info.get("training_groups", ()))
        self.ranges = self._training_ranges(model)
        self.inputs = InputBuilder(model_dir)
        self.lock = threading.Lock()

    def predict(self, features: dict) -> dict:
        group = self._group_key(features)
        context = None
        if any(name in features for name in NUMBER_FEATURES):
            numbers = {name: self._number(features, name) for name in NUMBER_FEATURES}
        else:
            built = self._build_inputs(group, features.get("forecastMonth"))
            numbers, context = built["features"], built["context"]

        with self.lock:
            log1p_price = float(self.model.predict([[numbers[n] for n in NUMBER_FEATURES] + [group]], thread_count=1)[0])
        known = group in self.training_groups
        return {
            "landGroupKey": group,
            "unitPriceKrwPerM2": max(math.expm1(log1p_price), 0.0),  # 원/㎡ (음수는 0)
            "log1pUnitPrice": log1p_price,                           # 모델이 내놓은 값 그대로
            "knownGroup": known,
            "context": context,  # 서버가 입력을 만들었을 때: 기준월·예측 대상월·원자료
            "warnings": self._warnings(numbers, known),
        }

    def data_info(self) -> dict:
        """화면 안내용: 자료가 있는 가장 최근 기준월과 그때의 예측 대상월."""
        latest = self.inputs.latest_month
        return {"latestForecastMonth": str(latest), "latestTargetMonth": str(latest.plus(6))}

    # ------------------------------------------------------------------
    # 입력 확인
    # ------------------------------------------------------------------
    def _build_inputs(self, group: str, forecast_month) -> dict:
        try:
            if forecast_month:
                return self.inputs.build(group, Month.parse(forecast_month))
            return self.inputs.build_latest(group)
        except InputsMissing as exc:
            raise LookupError(str(exc)) from None  # '자료 없음' → server 에서 409 로 바꾼다

    @staticmethod
    def _group_key(features: dict) -> str:
        if features.get(GROUP_FEATURE):
            return str(features[GROUP_FEATURE]).strip()
        if "sggCode" in features:
            return land_group_key(features["sggCode"], features.get("jimok"), features.get("landUse"))
        raise KeyError(f"{GROUP_FEATURE} 또는 sggCode·jimok·landUse 가 필요합니다.")

    @staticmethod
    def _number(features: dict, name: str) -> float:
        if name not in features:
            raise KeyError(f"{name} 값이 없습니다.")
        value = features[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} 는 숫자여야 합니다.")
        if not math.isfinite(value):
            raise ValueError(f"{name} 는 유한한 숫자여야 합니다.")
        return float(value)

    # ------------------------------------------------------------------
    # 주의 문구: 학습 범위 밖 입력, 학습 때 없던 그룹
    # ------------------------------------------------------------------
    @staticmethod
    def _training_ranges(model) -> dict:
        """학습 데이터에서 나온 구간 경계값의 최솟값·최댓값 (= 대략적인 학습 범위)."""
        ranges = {}
        for index, borders in model.get_borders().items():
            name = model.feature_names_[index]
            if name in NUMBER_FEATURES and borders:
                ranges[name] = (min(borders), max(borders))
        return ranges

    def _warnings(self, numbers: dict, known: bool) -> list[str]:
        warnings = []
        if not known:
            warnings.append("학습 때 없던 토지 그룹이라 그룹 정보 없이 예측했습니다.")
        for name, value in numbers.items():
            low, high = self.ranges.get(name, (-math.inf, math.inf))
            if value < low or value > high:
                warnings.append(f"{name} 값({value:g})이 학습 범위({low:g} ~ {high:g}) 밖이라 예측이 부정확할 수 있습니다.")
        return warnings
