"""토지 단가 예측 모델 (팀원 선형회귀 모델, model.joblib).

.env 에  MODEL_ENTRYPOINT=land_price_linear:LandPriceLinearPredictor  로 켠다.
(예전 CatBoost 모델로 돌아가려면 land_price_model:LandPricePredictor)

이 폴더의 linear/ 에 함께 있어야 하는 것 (팀원 전달 파일 두 개, 이름 그대로)
    linear/model.joblib      학습된 모델 (약 65KB). 전처리(표준화·원-핫)와 log1p 되돌리기까지 들어 있다.
    linear/model_info.json   모델 설명서.

CatBoost 모델과 같은 것
    입력 13개(숫자 12개 + 토지 그룹), 토지 그룹 만드는 법, 입력 자료(inputs/) 만드는 법, 6개월 뒤 예측.
    그래서 land_price_model.LandPricePredictor 를 이어받고, '모델 불러오기'와 '모델 부르기'만 바꾼다.

다른 것
    모델이 단가(원/㎡)를 바로 낸다 (안에서 expm1 까지 한다). 음수는 0 으로 자른다.
    학습 때 없던 토지 그룹은 원-핫이 모두 0 → 그룹 보정 없이 기준 그룹 값으로 예측된다 (주의 문구로 알린다).
    선형 모델은 학습 범위 밖 값에서 크게 빗나갈 수 있어, 학습 자료 평균에서 4표준편차 넘게 벗어나면 주의 문구를 붙인다.

필요한 패키지: scikit-learn==1.9.1 (모델을 저장한 버전), pandas. 버전이 다르면 켜지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import math
import warnings
from pathlib import Path

from land_price_inputs import InputBuilder
from land_price_model import FEATURE_ORDER, GROUP_FEATURE, NUMBER_FEATURES, LandPricePredictor

MODEL_FOLDER = "linear"
MODEL_FILE = "model.joblib"
INFO_FILE = "model_info.json"
FORMAT_VERSION = 1   # 팀원 저장 형식 {"format_version", "pipeline", "config", "model_info"}
RANGE_SIGMA = 4      # 학습 평균 ± 몇 표준편차를 '학습 범위'로 볼지


class LandPriceLinearPredictor(LandPricePredictor):
    name = "land-price-linear"
    version = "unknown"  # load 할 때 모델 파일 지문(sha256 앞 12자리)으로 바뀐다

    def load(self, model_dir: Path) -> None:
        import joblib  # scikit-learn·pandas 는 이 모델을 켤 때만 필요
        import pandas
        from sklearn.exceptions import InconsistentVersionWarning

        model_dir = Path(model_dir)
        folder = model_dir / MODEL_FOLDER
        model_path = folder / MODEL_FILE
        info = json.loads((folder / INFO_FILE).read_text(encoding="utf-8-sig"))

        # 저장한 scikit-learn 과 버전이 다르면 경고만 나오고 값이 달라질 수 있어, 아예 켜지 않는다.
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            bundle = joblib.load(model_path)

        # 코드·설명서·모델 파일이 서로 맞는지 확인. 하나라도 다르면 켜지 않는다.
        if not isinstance(bundle, dict) or bundle.get("format_version") != FORMAT_VERSION:
            raise ValueError("model.joblib 이 이 코드가 아는 저장 형식이 아닙니다.")
        pipeline, config = bundle["pipeline"], bundle["config"]
        if (tuple(config.get("numeric_features", ())) != NUMBER_FEATURES
                or tuple(config.get("categorical_features", ())) != (GROUP_FEATURE,)
                or tuple(pipeline.feature_names_in_) != FEATURE_ORDER):
            raise ValueError("모델의 입력 항목이 이 코드가 아는 13개와 다릅니다.")
        if config.get("forecast_horizon_months") != 6 or info.get("forecast_horizon_months") != 6:
            raise ValueError("이 코드는 6개월 예측 모델만 다룹니다.")
        if bundle.get("model_info", {}).get("split_fingerprints") != info.get("split_fingerprints"):
            raise ValueError("model_info.json 이 model.joblib 과 다른 모델의 설명서입니다. 같이 받은 두 파일을 함께 넣으세요.")

        # 학습 때 없던 그룹마다 sklearn 이 로그에 경고를 남긴다. 응답의 knownGroup·주의 문구로 이미 알리므로 그 경고만 끈다.
        warnings.filterwarnings("ignore", message="Found unknown categories", category=UserWarning)

        preprocess = pipeline.named_steps["preprocess"]
        self.model = pipeline
        self.preprocess = preprocess                                    # 표준화 + 원-핫
        self.regressor = pipeline.named_steps["regressor"].regressor_   # log1p(단가)를 내는 선형회귀
        self.frame = pandas.DataFrame
        self.version = hashlib.sha256(model_path.read_bytes()).hexdigest()[:12]
        self.training_groups = frozenset(preprocess.named_transformers_["category"].categories_[0])
        self.ranges = self._scaler_ranges(preprocess.named_transformers_["numeric"])
        self.inputs = InputBuilder(model_dir)

    def _predict_log1p(self, numbers: dict, group: str) -> float:
        """한 줄짜리 표를 만들어 전처리 → 선형회귀. log1p(단가)를 돌려준다.

        모델 전체(pipeline.predict)는 여기에 expm1 까지 해서 단가를 내는데, 그 expm1 과 0 자르기는
        부모 클래스 predict 가 똑같이 한다. 그래서 결과 단가는 pipeline.predict 와 같다 (테스트로 확인).
        """
        row = self.frame([{**numbers, GROUP_FEATURE: group}], columns=list(FEATURE_ORDER))  # 모델이 열 이름으로 입력을 고른다
        return float(self.regressor.predict(self.preprocess.transform(row))[0])

    # ------------------------------------------------------------------
    @staticmethod
    def _scaler_ranges(scaler) -> dict:
        """표준화에 쓴 학습 평균·표준편차로 만든 대략적인 학습 범위."""
        return {name: (mean - RANGE_SIGMA * scale, mean + RANGE_SIGMA * scale)
                for name, mean, scale in zip(scaler.feature_names_in_, scaler.mean_, scaler.scale_)}

    def _warnings(self, numbers: dict, known: bool) -> list[str]:
        warnings_ = []
        if not known:
            warnings_.append("학습 때 없던 토지 그룹이라 그룹 보정 없이 예측했습니다 (정확도가 낮을 수 있음).")
        for name, value in numbers.items():
            low, high = self.ranges.get(name, (-math.inf, math.inf))
            if value < low or value > high:
                warnings_.append(f"{name} 값({value:g})이 학습 자료 평균 ± {RANGE_SIGMA}표준편차({low:g} ~ {high:g}) 밖이라 "
                                 "예측이 부정확할 수 있습니다.")
        return warnings_
