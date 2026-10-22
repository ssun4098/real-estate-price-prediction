# 개발사업성 분석 V6 — 팀 공유용

Made by 최태영

선택 필지의 토지·건축물·규제·주변 입지를 살펴보고, 분양 비교사례와 토지 실거래 자료로 개발사업 수지를 검토하는 웹 프로젝트다. React 화면(빌드 완료본 `frontend/build/V6.template.html`)과 Python FastAPI 서버(`server/`)로 구성되고, 저장소는 MySQL이다. 안산 장상동 27필지의 저장 예시가 포함되어 있다.

인증키는 **프로세스 환경변수 → 이 프로젝트 폴더의 `.env`** 순서로 읽는다. 키를 코드, HTML, React의 `VITE_*` 변수 또는 분석 JSON에 넣지 않는다. 화면은 Python 서버에 요청하고, 서버가 인증키를 붙여 외부 API를 호출한다.

## 1. 발급받아야 하는 API 키

여러 데이터 조회 주소를 쓴다고 해서 주소마다 별도의 키를 발급받는 것은 아니다. 핵심 기능의 발급처는 아래 **3곳**이다. 발급된 키의 서비스 권한과 활용신청 승인 여부도 확인해야 한다.

| 발급처·공식 링크 | 환경변수 | 이 프로젝트에서 불러오는 데이터·기능 |
|---|---|---|
| [브이월드(VWorld)](https://www.vworld.kr/) | `VWORLD_API_KEY` | 위성지도, 연속지적도·필지 경계, 용도지역 경계, 토지대장·토지이용계획·토지특성·건축물·개별공시지가 속성, 산업단지 공간정보 |
| [공공데이터포털](https://www.data.go.kr/) | `DATA_GO_KR_API_KEY` | 아래의 토지 매매 실거래가와 청약홈 분양정보. 코드에서는 같은 서비스키를 두 서비스에 사용한다. |
| [주소기반산업지원서비스](https://business.juso.go.kr/) | `JUSO_API_KEY` | 도로명주소 검색, 법정동·지번 등 주소 확인. **검색 API용 승인키**가 필요하다. |

### 브이월드 신청 시

OpenAPI 인증키를 발급하고 사용할 서비스와 서비스 주소를 확인한다. 지도·데이터 API, 국가공간정보 속성 조회, [Geocoder 주소 좌표 변환](https://www.vworld.kr/dev/v4dv_geocoderguide2_s001.do), [Search 장소 검색](https://www.vworld.kr/dev/v4dv_search2_s001.do)에 필요한 권한을 확인한다.

Geocoder와 Search를 별도 키로 발급받았다면 다음 두 값에 입력한다. 공란이면 공유용 코드는 `VWORLD_API_KEY`를 재사용한다. 기본 키에 해당 권한이 없다면 자동 재사용만으로 권한이 생기지는 않는다.

- `VWORLD_GEOCODER_API_KEY`: 분양 비교단지 등의 주소를 좌표로 변환한다.
- `VWORLD_SEARCH_API_KEY`: 학교·산·하천·산업단지·하수처리장 등 주변시설 후보를 장소 검색한다.

`VWORLD_DOMAIN`에는 해당 키에 등록한 서비스 주소를 입력한다. 로컬 실행 예시는 `http://127.0.0.1:4175`이며, 발급 화면의 허용 주소 조건과 실제 설정이 맞아야 한다. 원래 작성자의 도메인은 공유본에 기본값으로 넣지 않았다.

### 공공데이터포털에서는 아래 두 서비스를 각각 활용신청

1. [국토교통부_토지 매매 실거래가 자료](https://www.data.go.kr/data/15126466/openapi.do) — 계약일·거래금액·면적·지목·용도지역 등 토지 비교자료.
2. [한국부동산원_청약홈 분양정보 조회 서비스](https://www.data.go.kr/data/15098547/openapi.do) — APT 모집공고 및 주택형별 분양가격·공급면적 등 분양 비교자료.

두 서비스의 승인 상태를 확인하고 일반 인증키를 `DATA_GO_KR_API_KEY`에 넣는다. **Decoding 키를 권장**하며, Encoding 키도 코드에서 한 번 디코딩한 뒤 요청 시 인코딩한다. 청약홈 분양정보는 아파트 매매 실거래가와 다른 자료다. 현재 분양수입 비교자료를 위해 별도의 아파트 매매 실거래가 API를 신청할 필요는 없다.

### 선택 항목

| 변수 | 용도·제한 |
|---|---|
| `KOSIS_API_KEY` | [KOSIS OpenAPI](https://kosis.kr/openapi/) 통계 연동 코드용. 통계표·지역 코드 조건도 맞아야 한다. |
| `SGIS_CONSUMER_KEY`, `SGIS_CONSUMER_SECRET` | [SGIS 개발지원](https://sgis.mods.go.kr/developer/html/openApi/api/data.html) 인구 통계 연동 코드용. 행정구역 코드 등 추가 설정이 필요하다. |

선택 항목은 저장 예시 열람과 핵심 토지·분양 수지분석의 필수 키가 아니다. 키만 입력한다고 현재 모든 화면에 통계가 자동으로 채워지는 것은 아니다. 법정동 코드 목록은 내장 자료와 공개 내려받기를 사용하며 별도 인증키를 요구하지 않는다.

이 목록은 포함된 V6 코드에서 확인한 호출 기준이다. 과거 검토한 전국 철도역·공원·대학교·폐기물처리시설 데이터는 이 공유본에 새로 연결하지 않았다. 주변시설 장소검색 결과를 전국 시설 전수 통계로 해석하면 안 된다.

## 2. 실행

Python 서버를 Docker로 띄우거나(방법 A), PC에서 바로 띄운다(방법 B). 어느 쪽이든 MySQL은 **PC에 이미 떠 있는 MySQL 컨테이너**를 쓴다. 이 프로젝트는 MySQL을 새로 띄우지 않는다.

### 2-1. 기존 MySQL 컨테이너(land-mysql) 연결 준비 (처음 한 번)

api 컨테이너가 `land-mysql` 컨테이너를 이름으로 찾을 수 있게 같은 Docker 네트워크에 묶는다. MySQL 컨테이너를 다시 만들거나 재시작하지 않으므로 자료는 그대로다.

```powershell
docker network create v6_mysql
docker network connect v6_mysql land-mysql
docker inspect land-mysql --format "{{json .NetworkSettings.Networks}}"   # v6_mysql 이 보이면 성공
```

앱 테이블을 둘 데이터베이스를 만든다 (기존 토지 실거래 DB와 같은 곳을 써도 된다. 아래 '보호 규칙' 참고).

```powershell
docker exec -it land-mysql mysql -uroot -p
```

```sql
CREATE DATABASE IF NOT EXISTS v6 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 분석 문서가 최대 64MB라 기본값(64MB)보다 크게. 컨테이너를 다시 켜도 유지됨
SET PERSIST max_allowed_packet = 134217728;
```

`.env`에 `MYSQL_CONTAINER=land-mysql`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`를 적는다.

### 2-2. 실행

```powershell
Copy-Item .env.example .env          # MYSQL_* 와 API 키 입력

# 방법 A: Docker로 api만 띄우기 (land-mysql 컨테이너에 이름으로 접속)
docker compose up -d --build

# 방법 B: Docker 없이 PC에서 바로 (MYSQL_HOST=127.0.0.1, MYSQL_PORT=docker ps 의 PORTS 왼쪽 번호)
python -m venv .venv                                      # 처음 한 번 (Python 3.11 이상)
.venv\Scripts\python.exe -m pip install -r requirements.txt   # 처음 한 번
.venv\Scripts\python.exe -m server
```

브라우저에서 `http://127.0.0.1:4175/`로 접속한다. `network v6_mysql declared as external, but could not be found` 오류가 나면 2-1의 `docker network create`를 안 한 것이다.

### 2-3. 기존 자료 보호 규칙

시작할 때 `server/db.py`가 다음만 한다. 로그에 `새로 만듦: … / 기존 유지: …`가 찍힌다.

- 이 앱의 테이블 6개(`analysis_snapshots`, `portfolio_samples`, `app_settings`, `land_complete`, `land_pages`, `land_errors`) 중 **없는 것만 새로 만든다.**
- 이미 있는 테이블(직접 적재한 실거래 테이블 포함)은 **지우거나 구조를 바꾸지 않는다.**
- 같은 이름인데 구조가 다른 테이블이 있으면 **아무것도 하지 않고 시작을 멈춘다.** 이때는 `MYSQL_DATABASE`를 다른 DB로 지정한다.

### 2-4. 사용·저장 방식

- 키 없이도 저장된 안산 장상동 예시를 볼 수 있다. 새 검색·실시간 데이터 조회는 해당 키와 서비스 승인이 필요하다.
- 기본 예시는 `data/samples/default.json`이 지정한다. 새 분석을 저장하는 것만으로 기본 예시가 자동 교체되지는 않는다.
- 분석 저장본·샘플 선반·기본 샘플·토지 실거래 캐시는 MySQL에 들어간다. `/api/save`와 `/api/export-json`은 같은 레코드를 저장하며, 화면 HTML은 요청마다 DB에서 만든다.
- 화면의 PDF 기능은 기본조사 4개 탭과 수지분석 화면을 A4 가로 5장으로 출력한다.
- 접속 주소를 바꾸면 `.env`의 `ALLOWED_HOSTS`에 `호스트:포트`를 추가해야 한다(Host/Origin 검사).
- 학습 모델: 아직 없어도 기동한다. 추가 방법은 [data/models/README.md](data/models/README.md).

## 3. 코드 구조

```
server/
├─ main.py          앱 조립: 설정 → MySQL 연결 → 기능 객체 생성 → URL 등록
├─ settings.py      .env(환경변수) → Settings
├─ env.py           .env 파일 읽기, 공공 API 키 형식 검사
├─ web.py           공통 규칙: 오류 응답 모양, JSON 본문 검사, 접속 주소 검사, 인증키 유출 차단
├─ db.py            테이블 정의 + 연결 + 기존 테이블 보호
├─ features/        기능별 파일. 한 파일 안에 "URL → 업무 규칙 → DB" 가 위에서 아래로
│  ├─ pages.py             대시보드 HTML
│  ├─ system.py            /healthz, /api/status
│  ├─ public_data.py       공공 API 조회 (동시 4건 제한)
│  ├─ land_store_mysql.py  토지 실거래 캐시 MySQL 보관
│  ├─ snapshots.py         /api/analyze, 분석 저장본
│  ├─ portfolio.py         샘플 선반
│  └─ model.py             학습 모델 자리
└─ domain/          계산 엔진·공공 API 연결 (웹·DB를 모름)
   ├─ analysis/            사업성 계산 analyze()  (주제별로 나뉨)
   │   ├─ engine.py            전체 순서
   │   ├─ development.py       개발 규모
   │   ├─ comparables.py       비교사례 고르는 규칙
   │   ├─ revenue.py           분양 수입
   │   ├─ land_price.py        토지 매입가
   │   ├─ costs.py             사업비
   │   ├─ cashflow.py          현금흐름
   │   └─ common.py            공통 도구
   ├─ public_api.py        공공 API 호출 창구 Collector
   ├─ survey.py            입지 조사
   ├─ land.py  boundary.py  regions.py   토지 분류·경계 배분·지역 목록
   ├─ persistence.py       저장할 때 빼야 할 자료 정리
   ├─ land_store.py        토지 실거래 캐시 규칙
   └─ geometry.py          도형 계산 라이브러리 불러오기
```

부르는 방향은 `features → domain` 한쪽뿐이다. 하나의 기능을 고칠 때는 `features/` 안의 파일 하나만 열면 된다. Spring으로 치면 Controller·Service·Repository가 한 파일 안에 차례로 들어 있는 모양이고, `domain/`은 가져다 쓰는 계산 라이브러리다.

- 저장 위치: 분석 저장본·샘플 선반·기본 샘플·토지 실거래 캐시가 MySQL에 들어간다. `/api/save`와 `/api/export-json`은 같은 레코드를 저장하며 `V6.html` 파일은 쓰지 않는다(페이지는 요청마다 DB에서 만든다).
- 학습 모델: 아직 없어도 기동한다. 추가 방법은 [data/models/README.md](data/models/README.md). 상태는 `GET /api/model/status`, 추론은 `POST /api/model/predict`.
- 접속 주소를 바꾸면 `.env`의 `ALLOWED_HOSTS`에 `호스트:포트`를 추가해야 한다(Host/Origin 검사).
- 테이블 구조를 바꿔야 할 일이 생기면 그때 Alembic(DB 구조 변경 이력 도구) 도입이 필요하다.

## 4. 테스트

```powershell
.venv\Scripts\python.exe tests/run_tests.py
```

실제 인증키·외부 API·MySQL 없이 실행된다(MySQL 대신 SQLite 사용). 환경변수 처리, 응답의 비밀값 차단, `.env` 접근 차단, 계산, 저장 규칙, 기존 테이블 보호를 검사한다.

프런트엔드 소스 재빌드는 별도 작업이다. `frontend/`에서 `npm ci`, `npm run build`를 수행하면 `dist/index.html`이 생성되며, 이를 `frontend/build/V6.template.html`로 복사한다. 보호된 파일 규칙은 `frontend/AGENTS.md`를 따른다.

## 5. 자주 생기는 문제

| 증상 | 확인할 항목 |
|---|---|
| `인증 미준비` / `키 미입력` | `.env` 변수 이름 확인 후 서버 재시작 |
| 인증 오류 / 권한 오류 | 해당 서비스 활용신청 승인, 키 종류, VWorld 등록 주소·서비스 권한 확인 |
| 주소 검색만 되고 좌표가 없음 | VWorld Geocoder 권한 또는 전용 키 확인 |
| 주변시설 조회 실패 | VWorld Search 권한 또는 전용 키 확인 |
| 자료 없음·산정 보류 | 키 문제와 구분하여 화면의 누락 면적·조회 실패·비교자료 상태 확인. 미확보 값을 임의로 채우지 않음 |
| MySQL 연결 관련 | [docs/04-run-and-operate.md](docs/04-run-and-operate.md)의 문제 해결 표 |
