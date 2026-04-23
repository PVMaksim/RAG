"""
notifier.py — уведомления об ошибках в Telegram.
Стандарт PVMaksim: каждый production-сервис оповещает разработчика при сбое.

Retry-логика: 3 попытки с exponential backoff (1s, 2s, 4s).
Если Telegram недоступен — пишем в лог и продолжаем, не падаем.
"""
import asyncio
import logging
import traceback

import httpx

log = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0


async def notify_telegram(
    message: str,
    bot_token: str | None,
    admin_id: int | None,
) -> None:
    """
    Отправляет уведомление об ошибке в Telegram.
    Retry: 3 попытки с exponential backoff. Никогда не кидает исключение.
    """
    if not bot_token or not admin_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id":    admin_id,
        "text":       message[:4000],
        "parse_mode": "HTML",
    }

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return
                # 429 Too Many Requests — ждём дольше
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 10))
                    log.warning(
                        "Telegram rate limit, ждём",
                        extra={"retry_after": retry_after, "attempt": attempt},
                    )
                    await asyncio.sleep(retry_after)
                    continue
                log.warning(
                    "Telegram API вернул ошибку",
                    extra={"status": resp.status_code, "attempt": attempt},
                )
        except httpx.TimeoutException:
            log.warning("Telegram timeout", extra={"attempt": attempt})
        except Exception as e:
            log.warning(
                "Не удалось отправить Telegram уведомление",
                extra={"attempt": attempt, "error": str(e)},
            )

        if attempt < _RETRY_ATTEMPTS:
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 1s, 2s, 4s
            await asyncio.sleep(delay)

    log.error(
        "Telegram уведомление не отправлено после всех попыток",
        extra={"attempts": _RETRY_ATTEMPTS},
    )


def format_error(context: str, exc: Exception) -> str:
    """Форматирует исключение для Telegram HTML-сообщения."""
    # Ограничиваем traceback чтобы не превысить 4000 символов Telegram
    tb = traceback.format_exc()[:1500]
    exc_type = type(exc).__name__
    return (
        f"🔴 <b>RAG Dev Assistant — {exc_type}</b>\n"
        f"<code>{context}</code>\n\n"
        f"<pre>{tb}</pre>"
    )
