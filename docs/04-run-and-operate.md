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

## 자주 쓰는 명령

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 확인 | `docker compose ps` |
| 서버 로그 보기 (테이블 준비 결과 포함) | `docker compose logs api` |
| 코드 수정 후 반영 | `docker compose up -d --build` |
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
| `ALLOWED_HOSTS` | 접속 허용 주소 추가. 다른 PC에서 접속하게 하려면 필요 |
| `MODEL_ENTRYPOINT` | 학습 모델 지정. 지금은 비워 둠 |

`.env`는 비밀번호가 들어 있으므로 **다른 사람에게 공유하거나 올리지 않습니다.** (git 제외 설정 되어 있음)

## 보안상 기본 설정

- 웹은 **내 컴퓨터(127.0.0.1)에서만** 접속됩니다. 다른 기기에서 접속하게 하려면 의도적으로 설정을 바꿔야 합니다.
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
| 접속하면 "허용된 실행 주소로 접속하세요" | 주소창을 `127.0.0.1:4175` 또는 `localhost:4175`로. 다른 주소를 쓰려면 `ALLOWED_HOSTS`에 추가 |
| 화면은 뜨는데 조회가 안 됨 | API 키 입력·승인 상태, 브이월드 등록 주소 확인 → 수정 후 `docker compose up -d` |
| "다른 자료를 조회 중입니다" | 정상. 몇 초 뒤 다시 시도 |
| api가 계속 재시작됨 | `docker compose logs api` 로 원인 확인 (위 MySQL 안내문 중 하나가 찍혀 있음) |
| 포트 사용 중 | `.env`에 `PUBLIC_PORT=4176` 처럼 다른 번호 지정, `VWORLD_DOMAIN`도 맞춰 수정 |

다음: [5. 용어집과 앞으로의 계획](05-glossary.md)
