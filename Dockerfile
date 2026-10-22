FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PUBLIC_PORT=4175

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# 서버에 필요한 것만 넣는다: 화면 소스·테스트·.env 는 넣지 않음.
COPY server ./server
COPY frontend/build ./frontend/build
COPY data/samples ./data/samples

# 학습 모델은 이미지에 넣지 않고 실행할 때 /app/data/models 로 연결한다 (docker-compose.yml).
RUN useradd --system --no-create-home --uid 10001 v6 && mkdir -p /app/data/models && chown -R v6 /app/data/models
USER v6

EXPOSE 4175

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ['PUBLIC_PORT'], timeout=4)"

CMD ["sh", "-c", "exec uvicorn server.main:create_app --factory --host 0.0.0.0 --port ${PUBLIC_PORT} --no-access-log"]
