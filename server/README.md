# server/ — 코드 지도

Python 코드는 전부 이 폴더에 있다. Spring에 익숙하다면 이렇게 보면 된다.

| Spring | 여기 |
|---|---|
| `@SpringBootApplication` + 설정 클래스 | `main.py` (조립), `settings.py` (설정값) |
| `@ControllerAdvice`, 필터 | `web.py` (오류 응답 모양, 요청 검사) |
| JPA 엔티티 + DataSource | `db.py` |
| Controller + Service + Repository | `features/` 의 파일 하나 (세 가지가 한 파일 안에 위에서부터 차례로) |
| 의존성으로 가져다 쓰는 계산 라이브러리 | `domain/` |

## 요청 하나가 지나가는 길

```
브라우저
  → main.py 의 guard            접속 주소 검사. 이후 어디서든 예외가 나면 여기서 표준 오류 응답으로 바꾼다
  → features/xxx.py 의 라우터    URL에 맞는 함수 (@router.get / @router.post)
  → 같은 파일의 Service 클래스   업무 규칙 + DB 읽기/쓰기
  → domain/                     계산 엔진·공공 API (필요할 때)
  → web.py 의 ok(...)           응답에 인증키가 섞이지 않았는지 확인하고 보낸다
```

## 파일 지도

```
server/
├─ __main__.py      python -m server 로 켤 때 진입점 (.env 를 읽고 uvicorn 실행)
├─ main.py          create_app(): 시작할 때 DB 연결 → Collector → 기능 객체를 만들어 app.state 에 둔다
├─ settings.py      환경변수 → Settings (DB 주소, 포트, 경로, 모델 설정)
├─ env.py           .env 파일 읽기, 공공 API 키 형식 검사, 허용하는 변수 이름 목록(APP_NAMES)
├─ web.py           ok()/html() 응답, error_response(), json_body(), check_host(), 비밀값 검사
├─ db.py            테이블 6개 정의, connect() (기존 테이블 보호), db_errors()
│
├─ features/        기능별 파일
│   ├─ pages.py             /  /index.html  /V6.html  /pf_study.html   대시보드 HTML
│   ├─ system.py            /healthz  /api/status
│   ├─ public_data.py       /api/parcels  /api/parcel  /api/address  /api/regions  /api/comparables
│   │                       /api/site-survey  /api/boundary-allocation  /api/data-coverage
│   │                       /api/land-cache  /api/tiles/...   (공공 API 조회, 동시 4건 제한)
│   ├─ snapshots.py         /api/analyze  /api/save  /api/export-json  /api/snapshots[/{id}]
│   ├─ portfolio.py         /api/portfolio-samples[/{id}]  /api/portfolio-default
│   ├─ model.py             /api/model/status  /api/model/predict   (학습 모델 자리)
│   ├─ land_trade_table.py  URL 없음. 토지 실거래를 직접 적재한 land_trade 테이블에서 읽기 (기본)
│   ├─ applyhome_table.py   URL 없음. 청약홈 분양정보를 직접 적재한 applyhome_apt_* 테이블에서 읽기 (기본)
│   └─ land_store_mysql.py  URL 없음. API로 받은 토지 실거래를 앱 캐시 테이블에 저장 (api 모드)
│
└─ domain/          웹·DB를 모르는 순수 계산 코드 (파일 지도는 domain/__init__.py)
    ├─ analysis/            사업성 계산 analyze() — 계산 단계별 파일 (지도는 analysis/__init__.py)
    │   engine.py  development.py  revenue.py  land_price.py  costs.py  cashflow.py
    │   comparables.py  common.py
    ├─ public_api.py        공공 API 호출 창구 Collector (브이월드·공공데이터포털·도로명주소), ApiError
    ├─ survey.py            입지 조사, 필지 정보 보강 (KOSIS·SGIS·주변시설)
    ├─ land.py              용도지역·지목 분류, 토지비 세부 계산
    ├─ boundary.py          필지가 여러 용도지역에 걸칠 때 면적 배분
    ├─ regions.py           시도·시군구·읍면동 목록
    ├─ persistence.py       저장할 때 빼야 할 자료 정리 (실시간 위치·분양사례 등)
    ├─ land_store.py        토지 실거래 캐시 규칙 (land_store_mysql.py 의 부모 클래스)
    └─ geometry.py          도형 계산 라이브러리(shapely, pyproj) 불러오기
```

## 토지 실거래·청약홈 자료는 어디서 오나

토지 실거래는 `.env`의 `LAND_TRADE_SOURCE`, 청약홈 분양정보는 `APPLYHOME_SOURCE`로 정한다. 둘 다 기본값은 `table`이다.

| 값 | 읽는 곳 | 공공데이터 API |
|---|---|---|
| `table` (기본) | 직접 적재한 `land_trade` 테이블 (`features/land_trade_table.py`) | 부르지 않음 |
| `api` | 공공데이터포털 → 앱 캐시 테이블 `land_complete` 등 (`features/land_store_mysql.py`) | 부름 |

`table` 모드 규칙
- `land_trade_job`에 기록이 있고 `loaded_rows ≥ total_count`인 달만 쓴다. 기록이 없는 달은 0건으로 치지 않고 "아직 적재되지 않음"(`LAND_NOT_LOADED`)으로 화면에 알린다.
- 거래 한 건의 판정(취소·지분·금액 0 제외)은 API 모드와 같은 함수 `domain/public_api.py`의 `land_trade_row()`를 쓴다.
- 이 앱은 `land_trade*` 테이블을 읽기만 한다.

청약홈 `table` 모드 (`features/applyhome_table.py`)
- `Collector.odcloud()`와 `Collector._coverage_count()`가 API 대신 `applyhome_apt_notice`·`applyhome_apt_model`을 조회한다. 분양사례 계산 코드는 바뀌지 않는다.
- 돌려주는 행은 API와 같은 대문자 필드 이름이다. 열 값을 먼저 쓰고, `extra`(JSON)의 나머지 원본 필드(특별공급 세대수 등)를 덧붙인다.
- 앱이 쓰는 조건(주택구분·상세구분·공고일·주소 포함·공고번호)만 받는다. 모르는 조건이 오면 조용히 무시하지 않고 오류를 낸다.
- 좌표 변환(브이월드 지오코더)은 계속 API를 쓴다.

**나중에 매일 적재하는 스케줄러를 만들 때:** API 호출 코드는 `domain/public_api.py`의 `Collector._land_page(시군구, 연월, 페이지)`에 그대로 남아 있다. 스케줄러는 이 함수로 하루치를 받아 `land_trade`에 넣고, `land_trade_job`에 `total_count`·`loaded_rows`를 기록하면 된다. 청약홈도 같은 방식이다(`Collector.odcloud()`는 `applyhome_table`이 비어 있을 때 API를 부른다). 서버 코드는 바꿀 필요가 없다.

## 기능 파일 읽는 법

`features/` 파일은 모두 같은 모양이다. `snapshots.py`를 예로 들면 이렇다.

1. **맨 위 설명**: 이 파일이 맡은 URL 목록과 핵심 규칙
2. **라우터**: `@router.post("/api/save")` 같은 함수. 하는 일은 요청을 받아 Service에 넘기고 `ok(...)`로 돌려주는 것뿐이다.
3. **Service 클래스**: `SnapshotService`. 업무 규칙과 DB 읽기/쓰기가 들어 있다.

라우터는 `request.app.state.snapshots`처럼 `main.py`가 미리 만들어 둔 객체를 꺼내 쓴다. Spring의 빈 주입과 같은 역할이다.

## 새 기능 추가하기 (예시: 메모)

**① `features/notes.py` 만들기**

```python
"""메모 (예시).

    GET /api/notes/{id}   메모 하나
"""
from fastapi import APIRouter, Request

from server.db import NoteRow, db_errors
from server.web import ApiError, ok

router = APIRouter()


@router.get("/api/notes/{ident}")
def read_note(request: Request, ident: str):
    return ok(request.app.state.notes.read(ident))


class NoteService:
    def __init__(self, sessions):
        self.sessions = sessions

    def read(self, ident: str) -> dict:
        with db_errors(), self.sessions() as session:
            row = session.get(NoteRow, ident)
        if row is None:
            raise ApiError("NOT_FOUND", "메모를 찾을 수 없습니다.", 404)
        return {"id": row.id, "text": row.text}
```

**② `db.py`에 테이블 클래스 추가** (`NoteRow`, 다른 Row 클래스와 같은 모양)

**③ `main.py`에 두 줄 추가**

```python
from server.features import model, notes, pages, ...           # import 에 notes 추가
app.state.notes = notes.NoteService(sessions)                  # lifespan 안
for feature in (pages, system, ..., model, notes):             # 라우터 등록 목록에 추가
```

## 지켜야 할 규칙

- **부르는 방향은 `features → domain` 한쪽뿐이다.** `domain/`에서는 FastAPI·SQLAlchemy·`features`를 import하지 않는다.
- **오류는 예외로 알린다.** 잘못된 입력은 `ValueError("이유")`를 던지면 400이 된다. 상태 코드를 지정하려면 `ApiError("코드", "메시지", 상태)`를 쓴다. 응답 모양은 `main.py`의 guard가 `{"error": {"code", "message"}}`로 통일한다.
- **응답은 `ok(data)`로 돌려준다.** dict를 그대로 돌려주지 않는다. 최대 64MB 문서를 두 번 변환하지 않으려는 것이고, 인증키 검사도 여기서 한다.
- **요청 본문은 `body: dict = Depends(json_body)`로 받는다.** JSON 형식, 64MB 제한, NaN 거부가 적용된다.
- **DB 접근은 `with db_errors(), self.sessions() as session:`으로 감싼다.** 쓰기는 `self.sessions.begin()`을 쓴다. DB 오류가 나면 접속 정보를 숨긴 503 응답이 된다.
- **기존 테이블을 지우거나 바꾸는 코드는 넣지 않는다.** `land-mysql`에는 직접 쌓은 실거래 자료가 있다.
- **라우터 함수는 `def`로 쓴다.** `async def`를 쓰지 않아도 FastAPI가 별도 스레드에서 실행해 준다. DB·외부 API 호출이 대부분이라 이쪽이 안전하다.
- **새 환경변수**는 `settings.py`에서 읽고, `env.py`의 `APP_NAMES`와 루트의 `.env.example`에도 추가한다.
