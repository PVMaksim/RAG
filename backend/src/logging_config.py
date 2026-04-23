"""
logging_config.py — настройка структурированного логирования.

В production (DEBUG=false): JSON-формат → удобно для Datadog / Loki / CloudWatch.
В development (DEBUG=true): цветной человекочитаемый вывод.

Каждый лог-запись содержит:
  - timestamp    ISO-8601
  - level        DEBUG/INFO/WARNING/ERROR/CRITICAL
  - logger       имя модуля
  - message      текст сообщения
  - request_id   UUID запроса (если задан через контекстную переменную)
  - duration_ms  время выполнения (для операций с декоратором @timed)
  - **extra      любые дополнительные поля
"""
import json
import logging
import sys
import time
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from typing import Any

# ── Контекстная переменная для request_id ─────────────────────────────────────
# Устанавливается в middleware при получении запроса.
# Автоматически попадает в каждую запись лога из этого запроса.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


# ── JSON Formatter (production) ───────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Форматирует лог-записи как одну строку JSON."""

    SKIP_ATTRS = {
        "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno",
        "funcName", "created", "msecs", "relativeCreated", "thread",
        "threadName", "processName", "process", "name", "message",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Форматируем исключение если есть
        exc_text = None
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            record.exc_info = None  # не дублировать

        entry: dict[str, Any] = {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "level":      record.levelname,
            "logger":     record.name,
            "msg":        record.getMessage(),
            "request_id": request_id_var.get("-"),
        }

        # Добавляем extra-поля (все что не стандартные атрибуты LogRecord)
        for key, value in record.__dict__.items():
            if key not in self.SKIP_ATTRS and not key.startswith("_"):
                entry[key] = value

        if exc_text:
            entry["traceback"] = exc_text

        return json.dumps(entry, ensure_ascii=False, default=str)


# ── Dev Formatter (цветной текст) ─────────────────────────────────────────────

class DevFormatter(logging.Formatter):
    """Цветной форматтер для локальной разработки."""

    COLORS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    RESET = "\033[0m"
    GRAY  = "\033[90m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        rid = request_id_var.get("-")
        rid_str = f" {self.GRAY}[{rid[:8]}]{self.RESET}" if rid != "-" else ""

        # Собираем extra-поля
        standard = {
            "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno",
            "funcName", "created", "msecs", "relativeCreated", "thread",
            "threadName", "processName", "process", "name", "message",
            "taskName",
        }
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in standard and not k.startswith("_")
        }
        extra_str = ""
        if extras:
            parts = [f"{self.GRAY}{k}={v}{self.RESET}" for k, v in extras.items()]
            extra_str = " " + " ".join(parts)

        msg = (
            f"{self.GRAY}{self.formatTime(record, '%H:%M:%S')}{self.RESET} "
            f"{color}{record.levelname:<8}{self.RESET}"
            f"{rid_str} "
            f"{self.GRAY}{record.name}{self.RESET}: "
            f"{record.getMessage()}"
            f"{extra_str}"
        )

        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)

        return msg


# ── Инициализация ─────────────────────────────────────────────────────────────

def setup_logging(debug: bool = False) -> None:
    """
    Вызывается один раз при старте приложения.
    debug=True → цветной вывод для разработки
    debug=False → JSON для production
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Убираем стандартные хендлеры
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DevFormatter() if debug else JSONFormatter())
    root.addHandler(handler)

    # Приглушаем шумные библиотеки
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Логирование настроено",
        extra={"mode": "debug" if debug else "production"},
    )


# ── Декоратор @timed — логирование времени выполнения ────────────────────────

def timed(operation: str | None = None):
    """
    Декоратор для логирования времени выполнения async функций.

    @timed("embedding")
    async def _embed(self, text: str) -> list[float]:
        ...

    Лог: INFO services.query_engine: embedding завершён  duration_ms=142
    """
    def decorator(func):
        op_name = operation or func.__name__

        @wraps(func)
        async def wrapper(*args, **kwargs):
            log = logging.getLogger(func.__module__)
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = round((time.perf_counter() - start) * 1000)
                log.debug(f"{op_name} завершён", extra={"duration_ms": duration})
                return result
            except Exception as exc:
                duration = round((time.perf_counter() - start) * 1000)
                log.error(
                    f"{op_name} упал",
                    extra={"duration_ms": duration, "error": str(exc)},
                    exc_info=True,
                )
                raise

        return wrapper
    return decorator


# ── get_logger — удобный хелпер ───────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """
    Используй вместо logging.getLogger(__name__).
    Будущем можно добавить контекстные поля ко всем логам модуля.
    """
    return logging.getLogger(name)
