FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

WORKDIR /app

COPY requirements.txt .
COPY bot/requirements.txt bot/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt \
    && python3 -m playwright install --with-deps chromium

RUN mkdir -p /app/capitulos_pdf_bot

COPY bot ./bot

# Default output directory for generated PDFs; can be overridden at runtime.
ENV OUTPUT_DIR=/app/capitulos_pdf_bot

CMD ["python3", "bot/telegram_bot.py"]
