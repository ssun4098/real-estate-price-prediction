FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PUBLIC_PORT=4175

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Only what the service needs: no frontend sources, tests or .env.
COPY app ./app
COPY backend ./backend
COPY web ./web
COPY samples ./samples

# Trained models are mounted at /app/models (see docker-compose.yml); never baked into the image.
RUN useradd --system --no-create-home --uid 10001 v6 && mkdir -p /app/models && chown -R v6 /app/models
USER v6

EXPOSE 4175

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ['PUBLIC_PORT'], timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PUBLIC_PORT} --no-access-log"]
