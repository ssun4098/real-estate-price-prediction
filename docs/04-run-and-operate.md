# 4. 실행과 운영

## 준비물

- **Docker Desktop** (실행 상태)와 **이미 떠 있는 MySQL 컨테이너** — 이 프로젝트는 MySQL을 새로 띄우지 않고 그것을 씁니다
- 정부 API 키 3종 (발급 방법은 [README.md](../README.md) 1장). 키가 없어도 저장된 예시 열람은 가능합니다.

## 처음 켜기

터미널(PowerShell)에서 프로젝트 폴더로 이동한 뒤 실행합니다.

1. **land-mysql 컨테이너를 같은 네트워크에 묶기 (처음 한 번, MySQL 재시작 없음)**
   ```powershell
   docker network create v6_mysql
   docker network connect v6_mysql land-mysql
   ```
2. **앱용 데이터베이스 만들기 (처음 한 번)** — 명령은 [README.md](../README.md) 2-1
3. **설정 파일 만들기**
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
   - `MYSQL_CONTAINER=land-mysql`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`: 기존 MySQL 컨테이너의 값 (`MYSQL_PORT`는 Docker 없이 켤 때만 사용)
   - `VWORLD_API_KEY`, `DATA_GO_KR_API_KEY`, `JUSO_API_KEY`: 발급받은 키
4. **켜기** (둘 중 하나)
   ```powershell
   docker compose up -d --build           # Docker로
   ```
   ```powershell
   python -m venv .venv                                           # Docker 없이: 처음 한 번
   .venv\Scripts\python.exe -m pip install -r requirements.txt   # Docker 없이: 처음 한 번
   .venv\Scripts\python.exe -m server                            # Docker 없이 켜기
   ```
   Docker 없이 켤 때는 `.env`의 `MYSQL_HOST=127.0.0.1`, `MYSQL_PORT`=`docker ps`의 PORTS 칸 왼쪽 번호를 씁니다.
5. **접속:** 브라우저에서 `http://127.0.0.1:4175/`
6. **끄기:** `docker compose down` (또는 Ctrl+C). MySQL 컨테이너와 자료는 그대로 남습니다.

## 서버에 올리기 (80번·443번 포트)

서버(방화벽·보안 그룹)에서 열어 둘 포트는 두 개입니다. 도메인이 없어도 서버 IP로 접속할 수 있습니다.

| 포트 | 쓰임 | 접속 주소 |
|---|---|---|
| 80 | HTTP (암호화 안 됨) | `http://서버IP/` |
| 443 | HTTPS | `https://서버IP/` (처음에는 자동으로 만든 시험용 인증서라 브라우저에 경고가 뜹니다. 계속 진행을 누르면 됩니다) |

- 앱(4175번)과 MySQL(3306번)은 서버 안에서만 쓰고 밖으로 열지 않습니다. 80·443번으로 온 요청은 nginx(`proxy` 컨테이너)가 받아서 앱에 전달합니다.
- 80번은 암호화되지 않아 분석 내용이 그대로 오갑니다. 민감한 자료는 443번(HTTPS)으로 접속하세요. 나중에 도메인과 정식 인증서가 생기면 80번을 443번으로 넘기도록 바꿀 수 있습니다.
- 서버를 관리하려고 SSH(22번)로 접속하는 것은 이 앱과 상관없습니다.

**순서**

1. 서버에 Docker를 설치하고 프로젝트 폴더를 올립니다.
2. 위 '처음 켜기'의 1~3번(MySQL 네트워크 연결, 데이터베이스 만들기, `.env` 만들기)을 서버에서 똑같이 합니다.
3. `.env`의 `VWORLD_DOMAIN`을 서버 주소로 바꾸고, 브이월드 사이트에 등록한 서비스 주소도 같은 값으로 맞춥니다. (203.0.113.10 은 예시이니 실제 서버 IP로)
   ```
   VWORLD_DOMAIN=http://203.0.113.10
   ```
4. 켜기: `docker compose --profile deploy up -d --build`
   처음 켤 때 `certs/` 폴더에 시험용 인증서(`fullchain.pem`, `privkey.pem`)가 저절로 만들어집니다.
5. 접속: 브라우저에서 `http://서버IP/` 또는 `https://서버IP/`

`--profile deploy`를 빼면 지금까지처럼 내 PC용(`127.0.0.1:4175`)으로만 켜집니다.

**나중에 도메인과 정식 인증서가 생기면:** `certs/`의 두 파일(이름 그대로)을 바꿔 넣고 `.env`의 `VWORLD_DOMAIN`을 도메인으로 고친 뒤 `docker compose --profile deploy up -d` 를 실행합니다.

> **주의:** 이 앱에는 로그인 기능이 없습니다. 80·443번을 인터넷 전체에 열면 주소를 아는 누구나 분석을 저장·조회하고 서버의 API 키 사용량을 쓸 수 있습니다. 방화벽에서 **접속을 허용할 IP를 제한**하세요.

## 자주 쓰는 명령

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 확인 | `docker compose ps` |
| 서버 로그 보기 (테이블 준비 결과 포함) | `docker compose logs api` |
| 코드 수정 후 반영 | `docker compose up -d --build` |
| 매일 적재 결과 확인 | 브라우저에서 `http://127.0.0.1:4175/api/daily-load` |
| 테스트 | `.venv\Scripts\python.exe tests/run_tests.py` |
| 재시작 | `docker compose restart api` |

`docker compose down -v`를 해도 이 프로젝트에는 MySQL 볼륨이 없으므로 기존 자료는 지워지지 않습니다. MySQL 컨테이너 자체는 따로 관리합니다.

## 설정(.env) 요약

| 항목 | 의미 |
|---|---|
| `MYSQL_*` | 기존 MySQL 컨테이너의 접속 정보 (호스트·포트·계정·데이터베이스) |
| `*_API_KEY` | 정부 사이트 이용 키 |
| `VWORLD_DOMAIN` | 브이월드에 등록한 서비스 주소. 접속 주소와 같아야 함 |
| `PUBLIC_PORT` | 접속 포트 (기본 4175) |
| `MODEL_ENTRYPOINT` | 학습 모델 지정. 지금은 비워 둠 |
| `LAND_TRADE_SOURCE` | 토지 실거래 출처. `table`(기본, 직접 적재한 DB) 또는 `api`(공공데이터포털) |
| `APPLYHOME_SOURCE` | 청약홈 분양정보 출처. `table`(기본, 직접 적재한 DB) 또는 `api`(공공데이터포털) |
| `DAILY_LOAD`, `DAILY_LOAD_TIME`, `DAILY_LOAD_MONTHS` | 매일 공공데이터 적재 켜기(`on`)/끄기(`off`), 실행 시각(기본 `03:00`), 토지 실거래를 다시 받는 개월 수(기본 3) |

`.env`는 비밀번호가 들어 있으므로 **다른 사람에게 공유하거나 올리지 않습니다.** (git 제외 설정 되어 있음)

## 보안상 기본 설정

- 웹은 **내 컴퓨터(127.0.0.1)에서만** 접속됩니다. 다른 기기에서 접속하게 하려면 의도적으로 설정을 바꿔야 합니다(위 '서버에 올리기').
- 시작할 때 **없는 테이블만** 만들고, 기존 테이블·자료는 지우거나 바꾸지 않습니다. 같은 이름인데 구조가 다른 테이블이 있으면 시작을 멈춥니다.
- 서버 프로그램은 관리자 권한 없이, 파일을 수정할 수 없는 상태로 실행됩니다.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| `MYSQL_PASSWORD 또는 DATABASE_URL 환경변수가 필요합니다` | `.env`의 `MYSQL_PASSWORD`가 비어 있음 |
| `MySQL에 연결할 수 없습니다` | land-mysql 컨테이너가 켜져 있는지(`docker ps`), `docker network connect v6_mysql land-mysql`를 했는지. Docker 없이 켤 때는 `MYSQL_PORT`가 PORTS 칸 왼쪽 번호와 같은지 |
| `network v6_mysql ... could not be found` | `docker network create v6_mysql` 을 먼저 실행 |
| `MySQL 계정 또는 비밀번호가 틀렸습니다` | `.env`의 `MYSQL_USER` / `MYSQL_PASSWORD` |
| `MYSQL_DATABASE로 지정한 데이터베이스가 없습니다` | README 2-1의 `CREATE DATABASE` 실행 |
| `기존 테이블 ...의 구조가 이 앱과 다릅니다` | 같은 이름의 다른 테이블이 있음. 자료 보호를 위해 멈춘 것. `MYSQL_DATABASE`를 다른 DB로 |
| 큰 분석 저장이 실패함 | MySQL `max_allowed_packet` 이 작음. README 2-1의 `SET PERSIST` 실행 |
| 서버에서 `proxy`가 계속 재시작됨 / 접속이 안 됨 | `docker compose logs proxy`. `certs/`에 `fullchain.pem`·`privkey.pem`이 있는지, 서버 방화벽에서 80·443번이 열려 있는지 |
| 화면은 뜨는데 조회가 안 됨 | API 키 입력·승인 상태, 브이월드 등록 주소 확인 → 수정 후 `docker compose up -d` |
| "다른 자료를 조회 중입니다" | 정상. 몇 초 뒤 다시 시도 |
| api가 계속 재시작됨 | `docker compose logs api` 로 원인 확인 (위 MySQL 안내문 중 하나가 찍혀 있음) |
| 비교사례에 "DB에 아직 적재되지 않았습니다" | 그 시군구·월이 `land_trade_job`에 적재 완료로 기록되지 않음. 적재 후 다시 조회 |
| 포트 사용 중 | `.env`에 `PUBLIC_PORT=4176` 처럼 다른 번호 지정, `VWORLD_DOMAIN`도 맞춰 수정 |

다음: [5. 용어집과 앞으로의 계획](05-glossary.md)
