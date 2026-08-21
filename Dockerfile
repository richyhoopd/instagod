# Imagen única de instagod (api + worker + publisher + daemon). Multi-arch:
# funciona igual en amd64 y arm64 (Oracle Ampere, Apple Silicon).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=America/Mexico_City

# Dependencias de sistema: tesseract (OCR flyers), libGL/glib (OpenCV),
# fuentes base y curl (healthcheck). Las libs de Chromium las instala Playwright.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
        libgl1 libglib2.0-0 \
        fonts-dejavu-core fonts-noto-color-emoji \
        curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Primero deps (capa cacheable), luego el código.
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Usuario sin privilegios; data/ y out/ son volúmenes montados desde el host.
RUN useradd -m -u 1000 instagod \
    && mkdir -p /app/data /app/out /app/secrets \
    && chown -R instagod:instagod /app /ms-playwright
USER instagod

EXPOSE 8100
# Comando por defecto = API; compose sobreescribe para worker/publisher/daemon.
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers", "--forwarded-allow-ips", "*"]
