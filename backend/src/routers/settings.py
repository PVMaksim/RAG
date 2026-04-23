"""
settings.py — роутер для управления настройками приложения в runtime.

GET /api/settings   — текущие настройки (без секретов)
PUT /api/settings   — обновить изменяемые настройки (top_k, модель, CORS)

Примечание: ANTHROPIC_API_KEY и другие секреты никогда не возвращаются через API.
Для их изменения нужен рестарт (через .env).
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from config import get_settings
from dependencies import clear_all_caches

log = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    """Публичные настройки (без секретов)."""
    claude_model: str
    embedding_model: str
    default_top_k: int
    debug: bool
    cors_origins: str
    # Флаги наличия (без раскрытия значений)
    has_anthropic_key: bool
    has_telegram:      bool
    has_mcp_api_key:   bool
    has_webhook_secret: bool
    # Пути (для диагностики)
    chroma_db_path:     str
    graph_db_path:      str
    projects_base_path: str
    rag_rules_path:     str


class SettingsUpdateRequest(BaseModel):
    """Изменяемые в runtime настройки."""
    default_top_k: int | None = Field(None, ge=1, le=20)
    debug: bool | None = None


@router.get("/", response_model=SettingsResponse)
async def get_settings_endpoint(
    settings=Depends(get_settings),
) -> SettingsResponse:
    """
    Текущие настройки приложения.
    Секреты (API ключи, токены) не возвращаются — только флаги их наличия.
    """
    return SettingsResponse(
        claude_model     = settings.claude_model,
        embedding_model  = settings.embedding_model,
        default_top_k    = settings.default_top_k,
        debug            = settings.debug,
        cors_origins     = settings.cors_origins,
        # Флаги наличия секретов
        has_anthropic_key  = bool(settings.anthropic_api_key),
        has_telegram       = bool(settings.telegram_bot_token and settings.admin_telegram_id),
        has_mcp_api_key    = bool(settings.mcp_api_key),
        has_webhook_secret = bool(settings.webhook_secret),
        # Пути
        chroma_db_path     = str(settings.chroma_db_path),
        graph_db_path      = str(settings.graph_db_path),
        projects_base_path = str(settings.projects_base_path),
        rag_rules_path     = str(settings.rag_rules_path),
    )


@router.put("/")
async def update_settings(
    req: SettingsUpdateRequest,
    settings=Depends(get_settings),
) -> dict:
    """
    Обновляет изменяемые настройки в runtime.

    Важно: изменения действуют до рестарта. Для постоянного сохранения
    нужно обновить .env файл.

    Не изменяет: API ключи, пути к данным, модель эмбеддингов (требуют рестарт).
    """
    changed = {}

    if req.default_top_k is not None and req.default_top_k != settings.default_top_k:
        # Pydantic Settings иммутабельны по умолчанию → используем object.__setattr__
        object.__setattr__(settings, "default_top_k", req.default_top_k)
        # Сбрасываем QueryEngine синглтон чтобы подхватил новый top_k
        clear_all_caches()
        changed["default_top_k"] = req.default_top_k
        log.info("Настройка обновлена", extra={"key": "default_top_k", "value": req.default_top_k})

    if req.debug is not None and req.debug != settings.debug:
        from logging_config import setup_logging
        object.__setattr__(settings, "debug", req.debug)
        setup_logging(debug=req.debug)
        changed["debug"] = req.debug
        log.info("Настройка обновлена", extra={"key": "debug", "value": req.debug})

    if not changed:
        return {"status": "no_changes", "changed": {}}

    return {"status": "updated", "changed": changed}
