ARG BACKEND_BASE_IMAGE=mcr.microsoft.com/devcontainers/python:1-3.11-bookworm
FROM ${BACKEND_BASE_IMAGE}

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG no_proxy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DATABASE_PATH=/app/data/lingodoc.db \
    LOCAL_STORAGE_ROOT=/app/storage \
    LOCAL_STORAGE_CACHE_DIR=/app/tmp/storage-cache \
    PDF_TRANSLATION_FONT_REGULAR=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    PDF_TRANSLATION_FONT_BOLD=/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc \
    PDF_TRANSLATION_LATIN_FONT_REGULAR=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
    PDF_TRANSLATION_LATIN_FONT_BOLD=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

WORKDIR /app

RUN rm -f /etc/apt/sources.list.d/*yarn* \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-dejavu-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
