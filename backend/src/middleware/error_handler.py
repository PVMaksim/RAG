"""
middleware/error_handler.py — middleware для обработки ошибок и request tracing.

Добавляет:
1. Request ID — уникальный UUID каждого запроса, попадает в логи и заголовок ответа
2. Timing — время обработки каждого запроса в заголовке X-Response-Time
3. Exception mapper — бизнес-исключения → правильные HTTP ответы
4. Safe SSE wrapper — ловит исключения внутри SSE-стримов
"""
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from exceptions import RAGError
from logging_config import request_id_var

log = logging.getLogger(__name__)


# ── Request ID + Timing Middleware ────────────────────────────────────────────

class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Для каждого входящего запроса:
      - Генерирует request_id (или берёт из заголовка X-Request-ID)
      - Записывает его в контекстную переменную → попадает в ВСЕ логи
      - Добавляет request_id и время ответа в заголовки ответа
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Берём request_id из заголовка или генерируем новый
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(rid)

        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000)

            # Добавляем заголовки — полезно для отладки в браузере
            response.headers["X-Request-ID"] = rid
            response.headers["X-Response-Time"] = f"{duration_ms}ms"

            # Логируем запрос
            log.info(
                f"{request.method} {request.url.path}",
                extra={
                    "method":      request.method,
                    "path":        request.url.path,
                    "status":      response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000)
            log.error(
                f"Unhandled exception in {request.method} {request.url.path}",
                extra={"duration_ms": duration_ms},
                exc_info=True,
            )
            raise
        finally:
            # Сбрасываем request_id чтобы не утекал в другие запросы
            request_id_var.reset(token)


# ── Exception → HTTP Response mapper ─────────────────────────────────────────

async def rag_exception_handler(request: Request, exc: RAGError) -> JSONResponse:
    """
    Маппит бизнес-исключения на правильные HTTP ответы.
    Логирует с правильным уровнем (warning для 404, error для 500).
    """
    logger = getattr(logging, exc.log_level, logging.error)
    logger(
        str(exc),
        extra={"http_status": exc.http_status, **exc.context},
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": type(exc).__name__,
            "message": exc.message,
            "request_id": request_id_var.get("-"),
        },
        headers={"X-Request-ID": request_id_var.get("-")},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Ловит все необработанные исключения.
    Логирует с полным traceback, отправляет Telegram alert.
    """
    from config import get_settings
    from services.notifier import format_error, notify_telegram
    import asyncio

    rid = request_id_var.get("-")
    context = f"{request.method} {request.url.path}"

    log.critical(
        f"Необработанное исключение: {context}",
        extra={"exception_type": type(exc).__name__, "request_id": rid},
        exc_info=True,
    )

    # Telegram alert в фоне (не блокируем ответ)
    settings = get_settings()
    asyncio.create_task(
        notify_telegram(
            format_error(f"{context} | request_id={rid}", exc),
            settings.telegram_bot_token,
            settings.admin_telegram_id,
        )
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "Внутренняя ошибка сервера",
            "request_id": rid,
        },
        headers={"X-Request-ID": rid},
    )


# ── Safe SSE generator wrapper ────────────────────────────────────────────────

async def safe_sse_stream(
    generator: AsyncGenerator[dict, None],
    operation: str = "sse",
) -> AsyncGenerator[str, None]:
    """
    Оборачивает AsyncGenerator в безопасный SSE стрим.

    Гарантирует что:
    1. Любое исключение внутри стрима → SSE событие {type: error}
    2. Клиент всегда получает сообщение вместо обрыва соединения
    3. Ошибка логируется с полным traceback
    4. Стрим всегда завершается корректно

    Использование:
        return StreamingResponse(
            safe_sse_stream(engine.answer_stream(query), "answer"),
            media_type="text/event-stream",
        )
    """
    rid = request_id_var.get("-")
    log.debug(f"SSE стрим начат: {operation}", extra={"operation": operation})

    try:
        async for event in generator:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    except RAGError as exc:
        # Ожидаемые бизнес-ошибки — warning уровень
        log.warning(
            f"SSE бизнес-ошибка: {operation}",
            extra={"operation": operation, "error": str(exc)},
        )
        yield f"data: {json.dumps({'type': 'error', 'message': exc.message, 'request_id': rid}, ensure_ascii=False)}\n\n"

    except Exception as exc:
        # Неожиданные ошибки — error уровень с traceback
        log.error(
            f"SSE неожиданная ошибка: {operation}",
            extra={"operation": operation, "error": str(exc)},
            exc_info=True,
        )
        yield f"data: {json.dumps({'type': 'error', 'message': 'Внутренняя ошибка сервера', 'request_id': rid}, ensure_ascii=False)}\n\n"

    finally:
        log.debug(f"SSE стрим завершён: {operation}", extra={"operation": operation})
