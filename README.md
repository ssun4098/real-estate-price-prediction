# 개발사업성 분석 V6 — 팀 공유용

Made by 최태영

땅(필지)을 고르면 토지·건축물·규제·주변 입지 정보를 모으고, 토지 실거래·분양 사례로 **개발해서 팔면 이익이 남는지(사업성)** 계산해 주는 웹 프로그램이다. 안산 장상동 27필지의 저장 예시가 들어 있다.

```
브라우저 (React 화면)
   │
   ▼
server/  ── Python FastAPI 서버 ──►  정부 공공 API (브이월드·공공데이터포털·도로명주소)
   │
   ▼
MySQL (PC에 이미 떠 있는 land-mysql 컨테이너)
```

처음 보는 사람은 [docs/](docs/README.md)를 순서대로 읽으면 30분 안에 전체 그림을 잡을 수 있다. 코드를 고칠 사람은 [server/README.md](server/README.md)의 코드 지도부터 본다.

## 1. 빠른 시작 (Windows PowerShell)

준비물: Docker Desktop, 이미 떠 있는 MySQL 컨테이너(`land-mysql`), 공공 API 키 3종([부록](#부록-발급받아야-하는-api-키)). 키가 없어도 저장된 예시는 볼 수 있다.

### 처음 한 번

```powershell
# ① api 컨테이너가 land-mysql 을 이름으로 찾도록 같은 네트워크에 묶기 (MySQL 재시작 없음, 자료 영향 없음)
docker network create v6_mysql
docker network connect v6_mysql land-mysql

# ② 이 앱의 테이블을 둘 데이터베이스 만들기
docker exec -it land-mysql mysql -uroot -p
```

```sql
CREATE DATABASE IF NOT EXISTS v6 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 분석 문서가 최대 64MB라 MySQL 기본값(64MB)보다 크게. 컨테이너를 다시 켜도 유지됨
SET PERSIST max_allowed_packet = 134217728;
```

```powershell
# ③ 설정 파일: MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE 와 API 키 입력
Copy-Item .env.example .env
notepad .env
```

### 켜고 끄기

```powershell
docker compose up -d --build      # 켜기 → http://127.0.0.1:4175/
docker compose logs -f api        # 로그 ("MySQL 테이블 준비 완료" 가 보이면 정상)
docker compose down               # 끄기 (MySQL 컨테이너와 자료는 그대로)
```

Docker 없이 PC에서 바로 켤 수도 있다. 코드를 고치며 확인할 때 편하다. 이때는 `.env`의 `MYSQL_HOST=127.0.0.1`, `MYSQL_PORT`=`docker ps`의 PORTS 칸 왼쪽 번호를 쓴다.

```powershell
python -m venv .venv                                           # 처음 한 번 (Python 3.11 이상)
.venv\Scripts\python.exe -m pip install -r requirements.txt   # 처음 한 번
.venv\Scripts\python.exe -m server                            # 켜기 (끄기: Ctrl+C)
```

## 2. 폴더 구조

```
V6_team_share/
├─ README.md            지금 읽는 문서
├─ CLAUDE.md            AI 도우미(Claude Code)용 기술 요약
├─ docker-compose.yml   api 컨테이너 하나를 켜는 설정 (MySQL은 새로 띄우지 않음)
├─ Dockerfile           api 이미지 만드는 방법
├─ requirements.txt     Python 라이브러리 목록
├─ .env.example         설정 양식 (복사해서 .env 로 사용. .env 는 git 제외)
│
├─ server/              ★ Python 코드 전부 → 자세한 지도는 server/README.md
│   ├─ main.py  settings.py  env.py  web.py  db.py     조립·설정·공통 규칙·DB
│   ├─ features/        URL 창구 + 업무 규칙 + DB (기능별 파일 하나씩)
│   └─ domain/          계산 엔진·공공 API 연결 (웹·DB를 모름)
│       └─ analysis/        사업성 계산 analyze() (계산 단계별 파일)
│
├─ frontend/            React 화면 원본 소스 (보호 파일 규칙: frontend/AGENTS.md)
│   └─ build/V6.template.html   빌드된 화면. 서버가 이 파일을 브라우저로 보낸다
├─ data/
│   ├─ samples/         기본 제공 예시 분석 (default.json 이 기본 예시를 지정)
│   └─ models/          학습 모델 넣는 곳 (지금은 비어 있음 → data/models/README.md)
├─ tests/               자동 테스트 (python tests/run_tests.py)
└─ docs/                쉬운 설명 문서 5편
```

## 3. 저장과 기존 자료 보호

이 앱은 다음을 MySQL에 저장한다.

| 테이블 | 내용 |
|---|---|
| `analysis_snapshots` | 화면에서 "저장"한 분석 (`/api/save`, `/api/export-json` 둘 다 여기) |
| `portfolio_samples` | 샘플 선반: 한 번 보관하면 바뀌지 않는 분석 |
| `app_settings` | 화면을 열 때 보여줄 기본 샘플 |
| `land_complete`, `land_pages`, `land_errors` | 토지 실거래 조회 캐시 (최근 달 1시간, 지난 달 30일 재사용) |

`land-mysql`에는 직접 쌓은 실거래 자료도 있으므로, 서버는 시작할 때(`server/db.py`) 다음만 한다.

- 위 6개 중 **없는 테이블만 새로 만든다.**
- 이미 있는 테이블은 **지우거나 구조를 바꾸지 않는다.**
- 같은 이름인데 구조가 다른 테이블이 있으면 **아무것도 하지 않고 시작을 멈춘다.** 이때는 `.env`의 `MYSQL_DATABASE`를 다른 DB로 바꾼다.

그 밖의 규칙

- 저장할 때 화면이 보낸 계산값은 믿지 않고 서버가 다시 계산한다.
- 응답·저장 자료에 API 키나 DB 비밀번호가 섞이면 보내지(저장하지) 않는다.
- 웹은 `127.0.0.1`에서만 열린다. 다른 주소로 접속하게 하려면 `.env`의 `ALLOWED_HOSTS`에 `호스트:포트`를 추가한다.
- 새 분석을 저장해도 기본 예시는 저절로 바뀌지 않는다. 화면에서 직접 지정해야 한다.

## 4. 개발할 때

```powershell
.venv\Scripts\python.exe tests/run_tests.py     # 전체 테스트 (인증키·외부 API·MySQL 없이, SQLite로 대신)
docker compose up -d --build                     # 코드 고친 뒤 반영
```

| 하고 싶은 일 | 볼 곳 |
|---|---|
| 새 API(URL) 추가 | `server/features/`에 파일 하나 + `server/main.py`에 한 줄 ([server/README.md](server/README.md)) |
| 계산식 수정 | `server/domain/analysis/`의 해당 단계 파일 (예: 공사비 → `costs.py`) |
| 공공 API 호출 수정 | `server/domain/public_api.py`의 `Collector` |
| 설정 항목 추가 | `server/settings.py` + `server/env.py`의 `APP_NAMES` + `.env.example` |
| 학습 모델 연결 | [data/models/README.md](data/models/README.md) |
| 화면 수정 | `frontend/`에서 `npm ci`, `npm run build` → `dist/index.html`을 `frontend/build/V6.template.html`로 복사 |

테이블 구조를 바꿔야 할 일이 생기면 그때 DB 변경 이력 도구(Alembic) 도입이 필요하다. 지금은 시작할 때 없는 테이블만 만든다.

## 5. 자주 생기는 문제

| 증상 | 확인할 것 |
|---|---|
| `인증 미준비` / `키 미입력` | `.env` 변수 이름 확인 후 서버 재시작 |
| 인증 오류 / 권한 오류 | 해당 서비스 활용신청 승인, 키 종류, VWorld 등록 주소·서비스 권한 |
| 주소 검색만 되고 좌표가 없음 | VWorld Geocoder 권한 또는 전용 키 |
| 주변시설 조회 실패 | VWorld Search 권한 또는 전용 키 |
| 자료 없음·산정 보류 | 키 문제와 구분해서 화면의 누락 면적·조회 실패·비교자료 상태 확인. 없는 값을 임의로 채우지 않는다 |
| MySQL 연결·시작 오류 | [docs/04-run-and-operate.md](docs/04-run-and-operate.md)의 문제 해결 표 |

인증키는 **프로세스 환경변수 → `.env`** 순서로 읽는다. 키를 코드·HTML·React의 `VITE_*` 변수·분석 JSON에 넣지 않는다. 화면은 서버에 요청하고, 서버가 키를 붙여 외부 API를 부른다.

## 부록. 발급받아야 하는 API 키

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
