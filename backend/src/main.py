"""
main.py — точка входа FastAPI приложения RAG Dev Assistant.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request

from config import get_settings
from rate_limiter import limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from exceptions import RAGError
from logging_config import setup_logging
from middleware.error_handler import (
    RequestContextMiddleware,
    generic_exception_handler,
    rag_exception_handler,
)
from routers import graph, metrics, projects, search, settings as settings_router, upload, webhook

_settings = get_settings()
setup_logging(debug=_settings.debug)
log = logging.getLogger(__name__)

# ── Приложение ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="RAG Dev Assistant",
    description="Семантический поиск по IT-проектам + Knowledge Graph",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── Rate Limiter ──────────────────────────────────────────────────────────────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(RequestContextMiddleware)

# CORS origins берутся из переменной окружения CORS_ORIGINS
# В dev: http://localhost:3000,http://localhost:8080
# В prod: https://rag.yourdomain.com
_raw_origins = _settings.cors_origins
_cors_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Обработчики исключений ────────────────────────────────────────────────────

app.add_exception_handler(RAGError, rag_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── Роутеры ───────────────────────────────────────────────────────────────────

app.include_router(search.router,   prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(graph.router,    prefix="/api")
app.include_router(upload.router,   prefix="/api")
app.include_router(webhook.router,  prefix="/api")
app.include_router(metrics.router,          prefix="/api")
app.include_router(settings_router.router,  prefix="/api")

# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    from dependencies import get_chroma, get_graph_store
    settings = get_settings()
    checks: dict = {}

    try:
        chroma = get_chroma()
        projects_list = chroma.list_projects()
        checks["chroma"] = {"status": "ok", "projects": len(projects_list)}
    except Exception as e:
        log.error("ChromaDB health check failed", exc_info=True)
        checks["chroma"] = {"status": "error", "detail": str(e)}

    try:
        gs = get_graph_store()
        checks["graph_store"] = {"status": "ok", "stats": gs.get_stats()}
    except Exception as e:
        log.error("GraphStore health check failed", exc_info=True)
        checks["graph_store"] = {"status": "error", "detail": str(e)}

    checks["anthropic"] = {
        "status": "ok" if settings.anthropic_api_key else "missing",
        "model":  settings.claude_model,
    }

    # Статистика embedding кэша
    try:
        from embedding_cache import cache_stats
        checks["embedding_cache"] = {"status": "ok", **cache_stats()}
    except Exception:
        checks["embedding_cache"] = {"status": "unavailable"}

    # Дисковое пространство — критично для ChromaDB
    try:
        import shutil
        disk = shutil.disk_usage(str(settings.chroma_db_path.parent))
        free_gb  = round(disk.free  / 1024**3, 2)
        total_gb = round(disk.total / 1024**3, 2)
        used_pct = round((disk.used / disk.total) * 100, 1)
        disk_status = "ok"
        if used_pct > 90:
            disk_status = "critical"   # < 10% свободно
        elif used_pct > 80:
            disk_status = "warning"    # < 20% свободно
        checks["disk"] = {
            "status":   disk_status,
            "free_gb":  free_gb,
            "total_gb": total_gb,
            "used_pct": used_pct,
        }
    except Exception as e:
        log.debug(f"Disk check failed: {e}")
        checks["disk"] = {"status": "unavailable"}

    overall = "ok" if all(
        v.get("status") in ("ok", "unavailable") for v in checks.values()
    ) else "degraded"

    # Уведомить в Telegram если диск критически заполнен
    if checks.get("disk", {}).get("status") == "critical":
        import asyncio
        from services.notifier import notify_telegram
        asyncio.create_task(notify_telegram(
            f"⚠️ RAG Dev Assistant: диск заполнен на {checks['disk']['used_pct']}%! "
            f"Свободно: {checks['disk']['free_gb']}GB",
            settings.telegram_bot_token,
            settings.admin_telegram_id,
        ))

    return {"status": overall, "version": "1.0.0", "checks": checks}


@app.get("/", tags=["system"])
async def root():
    return {"message": "RAG Dev Assistant API", "docs": "/api/docs"}


# ── Metrics middleware ───────────────────────────────────────────────────────

@app.middleware("http")
async def record_metrics(request: Request, call_next):
    """Записывает метрики каждого запроса в MetricsRegistry."""
    import time
    from routers.metrics import get_registry
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Записываем только API запросы, не /health и /metrics
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/metrics"):
        get_registry().record_request(path, request.method, response.status_code, duration)

    return response


@app.on_event("startup")
async def startup():
    settings = get_settings()
    log.info(
        "RAG Dev Assistant запускается",
        extra={
            "chroma_path":   str(settings.chroma_db_path),
            "graph_path":    str(settings.graph_db_path),
            "projects_path": str(settings.projects_base_path),
            "model":         settings.claude_model,
            "cors_origins":  _cors_origins,
            "debug":         settings.debug,
        },
    )
