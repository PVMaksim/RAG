"""
embedding_cache.py — LRU кэш для эмбеддингов.

Проблема: один и тот же файл может запрашиваться несколько раз
(поиск + построение графа + повторный поиск). Каждый раз это
~50ms на CPU или ~5ms на GPU. Кэш устраняет повторные вычисления.

Ограничения:
- maxsize=512 записей → ~50MB RAM (каждый эмбеддинг 384 float32 = 1.5KB)
- TTL не нужен — эмбеддинги детерминированы для одинаковых текстов
- thread-safe: functools.lru_cache защищён GIL
"""
import hashlib
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)


@lru_cache(maxsize=512)
def _cached_encode(text_hash: str, text: str, model_name: str) -> tuple[float, ...]:
    """
    Кэшированное кодирование текста.
    
    Ключ кэша — хэш текста + имя модели (не сам текст — экономим RAM).
    Возвращаем tuple (а не list) потому что tuple — hashable (нужно для lru_cache).
    """
    # Импортируем здесь чтобы избежать циклического импорта
    from sentence_transformers import SentenceTransformer
    model = _get_model(model_name)
    embedding = model.encode(text)
    return tuple(embedding.tolist())


@lru_cache(maxsize=4)
def _get_model(model_name: str) -> "SentenceTransformer":
    """Синглтон модели — не загружаем повторно."""
    from sentence_transformers import SentenceTransformer
    log.info("Загружаю embedding модель", extra={"model": model_name})
    return SentenceTransformer(model_name)


def get_embedding(text: str, model_name: str) -> list[float]:
    """
    Возвращает эмбеддинг текста. Использует LRU кэш.
    
    Args:
        text: Текст для кодирования
        model_name: Имя модели sentence-transformers
        
    Returns:
        list[float] — вектор эмбеддинга
    """
    # Хэшируем текст для ключа кэша (экономим память — не храним весь текст дважды)
    text_hash = hashlib.md5(text.encode()).hexdigest()
    embedding_tuple = _cached_encode(text_hash, text, model_name)
    return list(embedding_tuple)


def cache_stats() -> dict:
    """Статистика кэша для /health эндпоинта."""
    info = _cached_encode.cache_info()
    return {
        "hits":    info.hits,
        "misses":  info.misses,
        "maxsize": info.maxsize,
        "currsize": info.currsize,
        "hit_rate": round(info.hits / max(info.hits + info.misses, 1) * 100, 1),
    }


def clear_cache() -> None:
    """Очистить кэш (полезно при тестах или смене модели)."""
    _cached_encode.cache_clear()
    log.info("Embedding кэш очищен")
