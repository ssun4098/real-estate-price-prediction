# 학습 모델 추가 방법

모델이 아직 없어도 앱은 정상 기동합니다. `GET /api/model/status`는 `not_configured`를,
`POST /api/model/predict`는 `503 MODEL_NOT_READY`를 반환합니다. 이 폴더는 컨테이너에
`/app/data/models`로 **읽기 전용** 마운트됩니다.

## 1. 계약 (`server/features/model.py`의 `Predictor`)

```python
class Predictor(Protocol):
    name: str
    version: str
    def load(self, model_dir: Path) -> None: ...                    # 시작 시 1회
    def predict(self, features: dict) -> dict: ...                  # JSON 직렬화 가능한 결과, 스레드 안전
```

## 2. 예시

`data/models/my_model.py`

```python
from pathlib import Path

class LandPricePredictor:
    name = "land-price"
    version = "0.1.0"

    def load(self, model_dir: Path) -> None:
        import joblib   # 필요한 라이브러리는 requirements.txt에 추가하고 이미지를 다시 빌드
        self.model = joblib.load(model_dir / "land_price.joblib")

    def predict(self, features: dict) -> dict:
        return {"pricePerM2": float(self.model.predict([[features["areaM2"]]])[0])}
```

`.env`

```
MODEL_ENTRYPOINT=my_model:LandPricePredictor
```

적용: `docker compose up -d --build api`

## 3. 규칙

- 잘못된 입력은 `ValueError`/`KeyError`/`TypeError`로 알리면 422가 됩니다. 그 외 예외는 500이며 내부 메시지는 응답에 나가지 않습니다.
- 모델 로드에 실패해도 앱은 뜹니다. 원인은 `GET /api/model/status`의 `error`(예외 종류만)와 컨테이너 로그에서 확인합니다.
- `pickle`/`joblib`은 불러오는 파일이 곧 실행 코드입니다. 신뢰할 수 있는 곳에서 만든 모델 파일만 이 폴더에 넣으세요.
- 분석 엔진(`server/domain/engine.py`)은 모델에 의존하지 않습니다. 모델 결과를 수지 계산에 연결할 때는
  `server/features/` 의 해당 기능에서 `request.app.state.model.predict(...)`를 호출하세요.
