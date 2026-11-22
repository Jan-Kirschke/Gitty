FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --no-deps . && \
    useradd --system --no-create-home --uid 10001 gitty && \
    mkdir -p /data && chown gitty:gitty /data

USER gitty

EXPOSE 5555

CMD ["gitty-server"]
