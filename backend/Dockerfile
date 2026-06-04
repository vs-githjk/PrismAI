# Python 3.12 slim — matches Render's runtime; all deps in requirements.txt
# have prebuilt wheels for linux/arm64 + linux/amd64 so no build toolchain is
# needed in the image.
FROM python:3.12-slim

# System deps:
#   tesseract-ocr — pytesseract OCR for image/PDF text extraction
#   libgl1 / libglib2.0-0 — runtime libs pymupdf links against on slim images
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in a separate layer so code changes don't bust the
# pip cache. Render builds the same way.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend. .dockerignore keeps .env, __pycache__,
# tests/, etc. out of the image.
COPY . .

# Non-root user — Fargate doesn't require it but it's a security baseline
# and makes filesystem permissions explicit.
RUN useradd --create-home --uid 1000 prism && \
    chown -R prism:prism /app
USER prism

EXPOSE 8000

# Single worker. The realtime path keeps in-process state (`bot_store`,
# `_bot_state`, `_BOT_WAKE_ALIAS`, `_bot_settings_cache`) — multiple
# uvicorn workers would split that state and break the live-bot flow.
# Scale horizontally with more ECS tasks only AFTER moving bot state to
# Supabase (deferred debt — see CLAUDE.md "Known Limitations").
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
