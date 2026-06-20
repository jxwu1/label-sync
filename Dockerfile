# 双端处理 / label-sync — 生产 Docker image
#
# Build: docker build -t label-sync:latest .
# Run:   docker compose up -d  (推荐, 见 docker-compose.yml)

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Europe/Athens

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖利用 layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tailwind CSS v4 standalone CLI（钉版本 + sha256 校验，防 latest 供应链漂移/不可复现构建）
ADD --checksum=sha256:2526d063ba03b71f9a3ea7d5cee14f0aec147f117f222d5adc97b1d736d45999 \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.1/tailwindcss-linux-x64 \
    /usr/local/bin/tailwindcss
RUN chmod +x /usr/local/bin/tailwindcss

# 拷代码 (.dockerignore 已剔除 .venv / .git / _scratch / *.db 等)
COPY . .

# 构建 Tailwind CSS
RUN tailwindcss -i static/css/input.css -o static/css/output.css --minify

# 运行时数据走 volume (stockpile.db / input / output / archive)
ENV LABEL_SYNC_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 5000

# 启动: 先升级 schema (幂等), 再启 waitress WSGI
CMD ["sh", "-c", "alembic upgrade head && python wsgi.py"]
