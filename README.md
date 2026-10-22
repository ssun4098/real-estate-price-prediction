# 개발사업성 분석 V6 — 팀 공유용

Made by 최태영

선택 필지의 토지·건축물·규제·주변 입지를 살펴보고, 분양 비교사례와 토지 실거래 자료로 개발사업 수지를 검토하는 웹 프로젝트다. React 화면과 Python 로컬 서버로 구성된다. 안산 장상동 27필지의 저장 예시가 포함되어 있다.

**가장 빠른 실행:** ZIP 전체를 압축 해제한 뒤, Python 라이브러리를 설치하고 `.env.example`을 `.env`로 복사해 자신의 키를 입력한다. 이후 `python V6.py`를 실행한다. HTML만 따로 옮기면 새 주소·필지 조회는 동작하지 않는다.

## 1. 포함 파일

| 경로 | 용도 |
|---|---|
| `V6.py` | 실행 진입점. 같은 폴더의 `.env`를 읽고 서버를 시작한다. |
| `V6.html` | 저장 예시가 포함된 화면. 더블클릭으로 저장 결과를 열람할 수 있다. |
| `backend/` | 수정 가능한 Python 분석·공공 API·저장·서버 소스 |
| `frontend/` | React 화면 원본, 구성 파일, 잠금 파일, 보호된 런타임 검증 스크립트 |
| `web/V6.template.html` | 로컬 서버가 사용하는 빌드 완료 화면 |
| `samples/` | 공개를 허용한 기본 예시와 기본 예시 지정 파일 |
| `.env.example` | 값이 비어 있는 환경변수 양식. 실제 키가 아니다. |
| `requirements.txt` | Python 필수 라이브러리 |
| `scripts/run_tests.py` | 환경변수·비밀값 비노출·계산·저장 회귀 테스트 |
| `scripts/package_share.py` | `.env`·실행 결과 등을 제외하고 공유 ZIP을 다시 만드는 도구 |

기존 PC의 Windows 암호화 인증키 파일을 자동 탐색하는 기능을 제거했다. 인증키는 **프로세스 환경변수 → 이 프로젝트 폴더의 `.env`** 순서로 읽는다. 키를 코드, HTML, React의 `VITE_*` 변수 또는 분석 JSON에 넣지 않는다. 화면은 로컬 Python 서버에 요청하고, Python이 인증키를 붙여 외부 API를 호출한다.

## 2. 발급받아야 하는 API 키

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

## 3. 실행 방법 — Windows PowerShell

Python **3.11 이상**이 필요하며, 64비트 Python 3.12 또는 3.13을 권장한다. Node.js는 빌드 완료 화면을 실행할 때 필요하지 않다. 새 데이터 조회와 지도 타일에는 인터넷 연결이 필요하다.

ZIP을 압축 해제하고 `V6.py`가 있는 폴더에서 터미널을 연다. 다음 명령을 순서대로 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

`python` 명령이 없다면 먼저 Python을 설치하거나 첫 줄의 `python`을 `py -3.12`로 바꾼다. `.env`의 등호 오른쪽에 자신의 키를 입력하고 UTF-8로 저장한다. 키 값 뒤에 주석을 붙이지 않는다. `.env.txt`로 저장되지 않았는지 확인한다. 파일은 처음 한 번만 복사하며 기존 `.env`가 있다면 덮어쓰지 않는다.

```powershell
.\.venv\Scripts\python.exe V6.py
```

브라우저가 자동으로 열리며, 기본 주소는 `http://127.0.0.1:4175/`다. 기본 포트가 이미 사용 중이면 빈 포트를 선택하고 터미널에 주소를 표시한다. 종료는 터미널에서 `Ctrl+C`다. 가상환경 활성화 명령을 사용하지 않으므로 PowerShell 실행 정책을 변경할 필요가 없다.

필요하면 포트를 고정하거나 브라우저 자동 열기를 끌 수 있다.

```powershell
.\.venv\Scripts\python.exe V6.py --port 4176 --no-browser
```

다른 폴더에서 절대경로로 `V6.py`를 실행해도 `.env`·기본 예시·기본 저장 위치는 프로젝트 폴더를 기준으로 한다. 운영체제 환경변수를 이미 설정했다면 `.env`보다 우선한다. 환경변수가 빈 문자열인 경우에도 `.env`로 덮어쓰지 않는다. Geocoder/Search의 최종 값이 비어 있으면 기본 VWorld 키를 재사용한다.

macOS·Linux에서는 같은 구조로 아래 명령을 사용할 수 있다. 이 공유본의 실제 설치·실행 검증은 Windows / Python 3.12에서 수행했다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 편집기로 .env에 키 입력
.venv/bin/python V6.py
```

## 4. 사용·저장 방식

- 키 없이도 저장된 안산 장상동 예시를 볼 수 있다. 새 검색·실시간 데이터 조회는 해당 키와 서비스 승인이 필요하다. 저장되지 않은 지도 타일 등은 키가 없으면 표시되지 않을 수 있다.
- 기본 예시는 `samples/default.json`이 지정한다. 새 분석을 저장하는 것만으로 기본 예시가 자동 교체되지는 않는다.
- 새 JSON·HTML·예시·토지 조회 캐시는 `runtime/outputs/` 아래에 생성된다. 이 폴더와 개인 `.env`는 공유 ZIP 대상에서 제외한다.
- `V6.html`을 직접 열면 저장 결과를 보는 용도로 사용할 수 있다. 새 주소·필지 조회는 `V6.py`로 연 로컬 주소에서 수행한다.
- 화면의 PDF 기능은 기본조사 4개 탭과 수지분석 화면을 A4 가로 5장으로 출력한다. 렌더링된 화면을 고해상도 PNG로 담는 방식이며 글꼴·이미지 로드 상태에 영향을 받는다.
- 이 ZIP은 **팀원 각자의 PC에서 실행하는 로컬 프로젝트**다. 인터넷 공개 호스팅이나 Python 서버 배포는 포함하지 않는다. 해당 PC의 Python을 종료하면 실시간 조회 서버도 종료된다.

## 5. 개발·검증

Python 소스 변경은 `backend/`, 화면 변경은 `frontend/src/content/`에서 시작한다. 화면 원본의 `frontend/AGENTS.md`에 파일 경계와 빌드 절차가 정리되어 있다. 보호된 런타임 검사 파일과 잠금 파일을 함께 보관했다.

```powershell
.\.venv\Scripts\python.exe scripts/run_tests.py
```

이 테스트는 실제 인증키와 외부 API 호출 없이 실행된다. 환경변수 우선순위, 인코딩된 키 처리, HTTP 응답의 비밀값 차단, `.env` 접근 차단, 계산과 예시 저장 동작을 검사한다.

프런트엔드 소스 재빌드는 별도 개발 작업이다. 제공된 `web/V6.template.html`은 이미 빌드되어 있다. Node/Vite로 소스를 빌드하려면 호환되는 Node.js(22.12 이상 또는 Vite가 지원하는 버전)와 `frontend/package-lock.json` 기준 의존성이 필요하다. `frontend/`에서 `npm ci`, `npm run build`를 수행하면 `dist/index.html`이 생성되며, 이를 `web/V6.template.html`로 복사하면 Python 서버에서 변경된 화면을 제공한다. 기본 제공 ZIP에 `node_modules`는 포함하지 않는다. 이 공유 작업에서는 프런트엔드 원본 무결성을 검사했으며 npm 재설치·재빌드는 수행하지 않았다.

## 6. 다시 공유할 때

프로젝트 폴더에서 다음 명령으로 공유 ZIP을 만든다. ZIP은 기본적으로 프로젝트의 상위 폴더에 생성된다.

```powershell
.\.venv\Scripts\python.exe scripts/package_share.py
```

허용된 소스·문서·기본 예시만 포함한다. `.env`, 암호화 인증파일, 개인 분석 결과, 로그, 데이터베이스, 가상환경, 의존성 설치 폴더, Git 이력은 제외한다. `.gitignore`도 동일한 민감·생성 파일을 제외하도록 구성했다. **폴더 전체를 탐색기에서 그대로 압축하지 말고 이 명령을 사용한다.** 코드를 직접 수정해 키를 하드코딩한 경우까지 자동으로 안전해지는 것은 아니므로 키는 계속 환경변수로 관리한다.

본 공유 ZIP은 작성자의 현재 인증키 값 및 인코딩 형태 대조와 민감 파일 제외 검사를 거쳐 생성했다. 실제 키를 사용하는 외부 데이터 API의 신규 호출 성공 여부는 팀원별 키 권한·등록 주소·승인 상태·호출 한도에 따라 달라진다.

## 7. 자주 생기는 문제

| 증상 | 확인할 항목 |
|---|---|
| `인증 미준비` / `키 미입력` | `.env` 파일 이름·위치, 변수 이름, 환경변수 우선순위 확인 후 서버 재시작 |
| 인증 오류 / 권한 오류 | 해당 서비스 활용신청 승인, 키 종류, VWorld 등록 주소·서비스 권한 확인 |
| 주소 검색만 되고 좌표가 없음 | VWorld Geocoder 권한 또는 전용 키 확인 |
| 주변시설 조회 실패 | VWorld Search 권한 또는 전용 키 확인 |
| 경계 계산 라이브러리 없음 | 실행한 Python이 `.venv`의 Python인지 확인하고 `requirements.txt` 설치 |
| 화면은 열리지만 새 조회 불가 | HTML 파일이 아닌 실행 중인 Python의 로컬 주소로 접속 |
| 포트 사용 중 | 기존 서버를 확인하거나 `--port`로 다른 포트 지정 |
| 자료 없음·산정 보류 | 키 문제와 구분하여 화면의 누락 면적·조회 실패·비교자료 상태 확인. 미확보 값을 임의로 채우지 않음 |

## 8. FastAPI + MySQL 서비스

`python V6.py`(로컬 단독 실행, 파일 저장)는 그대로 동작한다. 별도로 FastAPI 서버가 `app/`에 있고, 저장소로 **PC에 이미 떠 있는 MySQL 컨테이너**를 쓴다. 이 프로젝트는 MySQL을 새로 띄우지 않는다.

### 8-1. 기존 MySQL 컨테이너(land-mysql) 연결 준비 (처음 한 번)

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

### 8-2. 실행

```powershell
Copy-Item .env.example .env          # MYSQL_* 와 API 키 입력

# 방법 A: Docker로 api만 띄우기 (land-mysql 컨테이너에 이름으로 접속)
docker compose up -d --build

# 방법 B: Docker 없이 PC에서 바로 (MYSQL_HOST=127.0.0.1, MYSQL_PORT=docker ps 의 PORTS 왼쪽 번호)
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app
```

브라우저에서 `http://127.0.0.1:4175/`로 접속한다. `network v6_mysql declared as external, but could not be found` 오류가 나면 8-1의 `docker network create`를 안 한 것이다.

### 8-3. 기존 자료 보호 규칙

시작할 때 `app/db.py`가 다음만 한다. 로그에 `새로 만듦: … / 기존 유지: …`가 찍힌다.

- 이 앱의 테이블 6개(`analysis_snapshots`, `portfolio_samples`, `app_settings`, `land_complete`, `land_pages`, `land_errors`) 중 **없는 것만 새로 만든다.**
- 이미 있는 테이블(직접 적재한 실거래 테이블 포함)은 **지우거나 구조를 바꾸지 않는다.**
- 같은 이름인데 구조가 다른 테이블이 있으면 **아무것도 하지 않고 시작을 멈춘다.** 이때는 `MYSQL_DATABASE`를 다른 DB로 지정한다.

### 8-4. 코드 구조 (`app/`)

```
app/
├─ main.py          앱 조립: 설정 → MySQL 연결 → 기능 객체 생성 → URL 등록
├─ settings.py      .env(환경변수) 읽기
├─ web.py           공통 규칙: 오류 응답 모양, JSON 본문 검사, 접속 주소 검사, 인증키 유출 차단
├─ db.py            테이블 정의 + 연결 + 기존 테이블 보호
└─ features/        기능별 파일. 한 파일 안에 "URL → 업무 규칙 → DB" 가 위에서 아래로
   ├─ pages.py          대시보드 HTML
   ├─ system.py         /healthz, /api/status
   ├─ public_data.py    공공 API 조회 (동시 4건 제한)
   ├─ land_store.py     토지 실거래 캐시 MySQL 보관
   ├─ snapshots.py      /api/analyze, 분석 저장본
   ├─ portfolio.py      샘플 선반
   └─ model.py          학습 모델 자리
```

하나의 기능을 고칠 때는 `features/` 안의 파일 하나만 열면 된다. Spring으로 치면 Controller·Service·Repository가 한 파일 안에 차례로 들어 있는 모양이다. 계산 엔진·공공 API 연결은 `backend/`(변경 없음)에 있다.

- 저장 위치: 분석 저장본·샘플 선반·기본 샘플·토지 실거래 캐시가 MySQL에 들어간다. `/api/save`와 `/api/export-json`은 같은 레코드를 저장하며 `V6.html` 파일은 쓰지 않는다(페이지는 요청마다 DB에서 만든다).
- 학습 모델: 아직 없어도 기동한다. 추가 방법은 [models/README.md](models/README.md). 상태는 `GET /api/model/status`, 추론은 `POST /api/model/predict`.
- 접속 주소를 바꾸면 `.env`의 `ALLOWED_HOSTS`에 `호스트:포트`를 추가해야 한다(Host/Origin 검사).
- 테이블 구조를 바꿔야 할 일이 생기면 그때 Alembic(DB 구조 변경 이력 도구) 도입이 필요하다.

공유본 구성일: 2026-10-16. API 명칭과 공식 링크는 위 발급처 안내를 기준으로 확인한다.
