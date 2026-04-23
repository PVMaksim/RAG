"""
retry.py — retry-логика для внешних API вызовов.

Anthropic API может вернуть:
  - 429 RateLimitError    → ждём retry-after и повторяем
  - 529 OverloadedError   → экспоненциальный backoff
  - 500/502 APIError      → повторяем с backoff
  - APIConnectionError    → сетевой сбой, повторяем

Все остальные ошибки (400 BadRequest, 401 AuthError) — не повторяем,
это ошибки конфигурации.
"""
import asyncio
import logging
import time
from functools import wraps
from typing import TypeVar, Callable, Any

import anthropic

from exceptions import LLMRateLimitError, LLMError

log = logging.getLogger(__name__)

T = TypeVar("T")


class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0    # секунды
    max_delay: float = 60.0    # максимальная пауза
    backoff_factor: float = 2.0


def with_anthropic_retry(config: RetryConfig | None = None):
    """
    Декоратор: повторяет async функцию при transient ошибках Anthropic API.

    Использование:
        @with_anthropic_retry()
        async def _call_claude(self, ...):
            return await self._anthropic.messages.create(...)
    """
    cfg = config or RetryConfig()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exc: Exception | None = None

            for attempt in range(1, cfg.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)

                except anthropic.RateLimitError as e:
                    # 429 — берём retry-after из заголовков если есть
                    retry_after = _parse_retry_after(e) or (cfg.base_delay * attempt)
                    log.warning(
                        "Anthropic rate limit",
                        extra={
                            "attempt": attempt,
                            "retry_after_sec": retry_after,
                            "function": func.__name__,
                        },
                    )
                    if attempt == cfg.max_attempts:
                        raise LLMRateLimitError(retry_after=int(retry_after)) from e
                    await asyncio.sleep(retry_after)
                    last_exc = e

                except anthropic.InternalServerError as e:
                    # 500/529 — сервер перегружен, экспоненциальный backoff
                    delay = min(cfg.base_delay * (cfg.backoff_factor ** (attempt - 1)), cfg.max_delay)
                    log.warning(
                        "Anthropic server error",
                        extra={
                            "attempt": attempt,
                            "delay_sec": delay,
                            "status_code": getattr(e, "status_code", "unknown"),
                            "function": func.__name__,
                        },
                    )
                    if attempt == cfg.max_attempts:
                        raise LLMError(f"Anthropic API недоступен после {cfg.max_attempts} попыток: {e}") from e
                    await asyncio.sleep(delay)
                    last_exc = e

                except anthropic.APIConnectionError as e:
                    # Сетевой сбой
                    delay = min(cfg.base_delay * (cfg.backoff_factor ** (attempt - 1)), cfg.max_delay)
                    log.warning(
                        "Anthropic connection error",
                        extra={
                            "attempt": attempt,
                            "delay_sec": delay,
                            "function": func.__name__,
                        },
                    )
                    if attempt == cfg.max_attempts:
                        raise LLMError(f"Нет соединения с Anthropic API: {e}") from e
                    await asyncio.sleep(delay)
                    last_exc = e

                except (anthropic.AuthenticationError, anthropic.BadRequestError):
                    # Эти ошибки не исправятся при повторе — сразу пробрасываем
                    raise

                except anthropic.APIError as e:
                    # Прочие API ошибки — пробрасываем как LLMError
                    raise LLMError(f"Anthropic API error: {e}") from e

            # Если дошли сюда — все попытки исчерпаны
            raise LLMError(f"Все {cfg.max_attempts} попытки исчерпаны") from last_exc

        return wrapper
    return decorator


def _parse_retry_after(exc: anthropic.RateLimitError) -> float | None:
    """Извлекает retry-after из заголовков ответа."""
    try:
        headers = getattr(exc, "response", None) and exc.response.headers
        if headers and "retry-after" in headers:
            return float(headers["retry-after"])
    except Exception:
        pass
    return None


# ── Декоратор для измерения времени LLM вызовов ───────────────────────────────

def log_llm_call(operation: str):
    """
    Логирует время выполнения и использование токенов для LLM вызовов.

    @log_llm_call("answer")
    async def answer_stream(self, query: str, ...):
        ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            log.info(
                f"LLM вызов: {operation}",
                extra={"operation": operation, "function": func.__name__},
            )
            try:
                result = await func(*args, **kwargs)
                duration = round((time.perf_counter() - start) * 1000)
                log.info(
                    f"LLM завершён: {operation}",
                    extra={"operation": operation, "duration_ms": duration},
                )
                return result
            except Exception as exc:
                duration = round((time.perf_counter() - start) * 1000)
                log.error(
                    f"LLM ошибка: {operation}",
                    extra={"operation": operation, "duration_ms": duration, "error": str(exc)},
                )
                raise
        return wrapper
    return decorator
