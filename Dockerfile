# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-slim
LABEL org.opencontainers.image.title="job-bot" \
      org.opencontainers.image.description="Telegram bot: daily job digest and application follow-ups"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/jobbot.sqlite3 \
    SEARCH_CONFIG=/app/config/search.yaml
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
 && mkdir /data && chown app /data
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY config ./config
USER 10001
VOLUME ["/data"]
CMD ["python", "-m", "app.main"]
