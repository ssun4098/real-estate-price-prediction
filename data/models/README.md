# 학습 모델 (토지 그룹 단가 예측 · CatBoost 23번)

이 폴더는 컨테이너에 `/app/data/models`로 **읽기 전용** 마운트됩니다.
모델은 팀원 전달 자료 `개발자전달_CatBoost23_20261027`의 23번 모델입니다
(depth 6, learning_rate 0.06, l2_leaf_reg 32, iterations 1600 → 조기 종료로 트리 873개).

| 파일 | git | 설명 |
|---|---|---|
| `land_price_model.py` | 올림 | 모델을 불러와 예측. 토지 그룹 이름 만들기 |
| `land_price_inputs.py` | 올림 | 모델 입력 13개를 `inputs/` 자료로 만들기 (팀원 `tools/build_context.py`와 같은 규칙) |
| `inputs/` | 올림 (약 9MB) | 입력 자료: 그룹별 월간 거래단가, 지역 대응표, 거시 지표, COFIX 공시 이력. 만드는 법은 `inputs/make_inputs.py` |
| `model_info.json` | 올림 | 모델 설명서 (팀원 제공): 입력 항목, 학습 그룹 5,085개, log1p 변환 |
| `model.cbm` | **안 올림** (약 110MB) | 학습된 모델. 전달 자료의 `model/model.cbm`을 PC·서버마다 직접 복사 |

`.env`

```
MODEL_ENTRYPOINT=land_price_model:LandPricePredictor
```

적용: `docker compose up -d --build api` → `GET /api/model/status`가 `"state": "ready"`면 성공.
파일이 없거나 서로 안 맞으면 앱은 그대로 뜨고 `state`만 `failed`가 됩니다.

## 모델이 예측하는 것

**시군구 × 지목 6그룹 × 용도지역 8그룹의 6개월 뒤 월간 거래단가 중앙값(원/㎡).**
필지 하나의 감정가가 아니라 그룹의 대표 단가입니다.

| 날짜 | 규칙 |
|---|---|
| 기준월 | 예측하는 시점 |
| 입력월 = 기준월 − 2개월 | 거시 지표·과거 거래는 이 달 값만 씀 (지표 발표가 2개월 늦다는 학습 가정) |
| 예측 대상월 = 기준월 + 6개월 | 이 달의 단가를 예측 |
| COFIX | 기준월 말일까지 실제로 공시된 가장 최근 값 |

없는 값은 0·이전 달·가까운 달로 **채우지 않습니다**. 자료가 없으면 `409 MODEL_DATA_MISSING`.

### 지금 자료로 가능한 범위

거시 지표가 2026-07까지, COFIX 공시가 2026-08까지라서
**가장 최근 기준월은 2026-08 → 예측 대상월 2027-02**입니다 (`/api/model/status`의 `data`).
그룹마다 최근 기준월부터 6개월(2026-03 ~ 2026-08)을 거슬러 올라가며 그 그룹의 입력월 거래가 있는 첫 달로 예측하므로,
그룹에 따라 예측 대상월이 2026-09 ~ 2027-02로 다를 수 있습니다. 6개월 내내 거래가 없는 그룹은 예측하지 않습니다.
더 최신으로 예측하려면 지표·거래 집계를 갱신해야 합니다 (아래 '자료 갱신').

## API

### `POST /api/model/land-estimate` — 필지별 모델 예측 토지매입대금 (화면에서 사용)

```json
{"parcels": [{"pnu": "4127111400100820000", "jimok": "전", "landUse": "자연녹지지역", "areaM2": 4879}]}
```

필지마다 `그룹 단가(원/㎡) × 면적`을 돌려주고, 모두 구하면 `totalWon`, 일부만 구하면 `totalWon: null`과 `partialWon`(산출분 소계)을 줍니다.
화면 '사업 수지분석 → 예상 토지매입대금' 칸 아래에 **기존 금액과 별도로** 표시되며, 수지표 계산에는 들어가지 않습니다.

### `POST /api/model/predict` — 그룹 하나

```json
{"features": {"sggCode": "11110", "jimok": "대", "landUse": "제2종일반주거지역"}}
```

- `forecastMonth: "2026-05"`를 넣으면 그 기준월로 예측 (없으면 자료가 있는 최근 기준월).
- 숫자 입력 12개를 직접 넣으면 그 값으로 예측 (팀원 예제 재현·검증용).

응답의 `result`: `unitPriceKrwPerM2`(원/㎡), `log1pUnitPrice`, `knownGroup`(학습 그룹 목록에 있는지),
`context`(입력월·기준월·예측 대상월·COFIX 공시일·원자료), `warnings`(학습 범위 밖 입력 등).

## 토지 그룹 (`land_group_key` = `"시군구코드|지목그룹|용도지역그룹"`)

팀원 전처리 코드(`reference_preprocessing/build_land_trade2.py`)의 대조표 그대로입니다.

| 그룹 | 원래 이름 |
|---|---|
| 지목 | `대`·`전`·`답`·`임야`·`공장용지`는 그대로, 나머지 지목은 모두 `기타` |
| 전용주거지역 | 제1종·제2종전용주거지역, 전용주거지역 |
| 일반주거지역 | 제1종·제2종·제3종일반주거지역, 일반주거지역 |
| 준주거지역 | 준주거지역 |
| 상업지역 | 중심·일반·근린·유통상업지역 |
| 공업지역 | 전용·일반·준공업지역 |
| 녹지지역 | 보전·생산·자연녹지지역 |
| 비도시지역 | 보전·생산·계획관리지역, 관리지역, 농림지역, 자연환경보전지역 |
| 용도미지정 등 | 용도미지정, 개발제한구역, 기타 |

표에 없는 용도지역 이름은 추측하지 않고 '분류 불가'로 돌려줍니다.

## 숫자 입력 12개 (서버가 만듦)

| 이름 | 계산 |
|---|---|
| `지가변동률` | 입력월 시군구 지가변동률(%) |
| `log_permit_area` | log1p(입력월 시도 건축허가 연면적 ㎡) |
| `신규취급액기준_COFIX` | 기준월 말일까지 공시된 최근 COFIX(%) |
| `경제심리지수_원계열` | 입력월 ESI |
| `동행종합지수_전월비` | 입력월 동행종합지수 전월비(%) |
| `log_m1_original` | log1p(입력월 M1 평잔 원계열) |
| `log_nonbank_housing_loans` | log1p(입력월 시도 비은행 주택관련대출) |
| `log_history_median_area` | log1p(입력월 그 그룹 거래 면적 중앙값) |
| `log_history_unit_price` | log1p(입력월 그 그룹 거래단가 중앙값) |
| `forecast_month_index` | (기준연도 − 2016) × 12 + 기준월 − 1 |
| `forecast_month_sin` / `cos` | sin / cos(2π × 기준월 / 12) |

팀원이 준 학습·예측 표본 6,000건과 숫자 12개가 모두 일치하고, 예제 5건의 예측값도 일치합니다 (`tests/test_land_price_model.py`).

## 자료 갱신 (새 달 예측이 필요할 때)

지금 `inputs/`는 팀원이 준 시점의 스냅샷입니다. 자동 수집기는 아직 없습니다.

1. 팀원에게 새 전달 자료(지표·거래 집계·COFIX 공시 이력)를 받거나, 같은 형식으로 갱신합니다.
2. `python data/models/inputs/make_inputs.py <전달자료 폴더> data/models/inputs` (pandas, pyarrow 필요)
3. 모델이 바뀌었으면 `model.cbm`과 `model_info.json`도 덮어씁니다.
4. `docker compose up -d --build api`

지표 출처·주의점은 전달 자료의 `docs/지표출처와갱신.md`를 따릅니다 (예: M1·대출 통화 단위를 바꾸지 않기, COFIX는 공시일 기준).

## 다른 모델을 추가할 때 (계약)

`server/features/model.py`의 `Predictor`:

```python
class Predictor(Protocol):
    name: str
    version: str
    def load(self, model_dir: Path) -> None: ...                    # 시작 시 1회
    def predict(self, features: dict) -> dict: ...                  # JSON 직렬화 가능한 결과, 스레드 안전
```

- 잘못된 입력은 `ValueError`/`KeyError`/`TypeError` → 422, 예측에 쓸 자료가 없으면 `LookupError` → 409.
  그 외 예외는 500이며 내부 메시지는 응답에 나가지 않습니다.
- `land-estimate`는 `predict` 결과의 `unitPriceKrwPerM2`, `landGroupKey`, `knownGroup`, `context`를 씁니다.
- 모델 로드에 실패해도 앱은 뜹니다. 원인은 `GET /api/model/status`의 `error`(예외 종류만)와 컨테이너 로그에서 확인합니다.
- `pickle`/`joblib`은 불러오는 파일이 곧 실행 코드입니다. 신뢰할 수 있는 곳에서 만든 모델 파일만 이 폴더에 넣으세요.
- 분석 엔진(`server/domain/analysis/`)은 모델에 의존하지 않습니다.
