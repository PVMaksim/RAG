# ── Stage 1: зависимости ──────────────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

# Системные зависимости для sentence-transformers и chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Предзагружаем embedding модель в образ (офлайн работа)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# ── Stage 2: production образ ─────────────────────────────────────────────────
FROM python:3.12-slim AS production

WORKDIR /app

# Копируем установленные пакеты из deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
# Копируем кэш sentence-transformers модели
COPY --from=deps /root/.cache /root/.cache

# Копируем исходный код
COPY backend/src/ ./src/
COPY backend/rag-rules.yaml .

# Создаём директории для данных (volumes будут смонтированы поверх)
RUN mkdir -p /app/data/chroma_db /app/projects

# Непривилегированный пользователь
RUN useradd -r -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/src

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
