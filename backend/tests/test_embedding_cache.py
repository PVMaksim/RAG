"""
test_embedding_cache.py — тесты для кэша эмбеддингов.

Проверяем:
- Кэш работает (повторный вызов не пересчитывает)
- Разные тексты → разные эмбеддинги
- Разные модели → разные эмбеддинги
- cache_stats() возвращает корректные данные
- clear_cache() сбрасывает состояние
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Сбрасываем кэш перед каждым тестом."""
    from embedding_cache import clear_cache
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def mock_model():
    """Мок SentenceTransformer — возвращает предсказуемые эмбеддинги."""
    import numpy as np

    call_count = 0
    model = MagicMock()

    def fake_encode(text):
        nonlocal call_count
        call_count += 1
        # Детерминированный эмбеддинг на основе текста
        seed = sum(ord(c) for c in text[:10])
        rng = np.random.RandomState(seed)
        return rng.randn(384).astype(np.float32)

    model.encode.side_effect = fake_encode
    model._call_count = lambda: call_count
    return model


class TestEmbeddingCache:

    def test_same_text_uses_cache(self, mock_model):
        """Повторный вызов с тем же текстом не вызывает model.encode()."""
        with patch("embedding_cache._get_model", return_value=mock_model):
            from embedding_cache import get_embedding, clear_cache
            clear_cache()

            result1 = get_embedding("обработка ошибок", "test-model")
            result2 = get_embedding("обработка ошибок", "test-model")

        # model.encode вызван только один раз
        assert mock_model.encode.call_count == 1
        # Результаты идентичны
        assert result1 == result2

    def test_different_texts_different_embeddings(self, mock_model):
        """Разные тексты → разные вычисления."""
        with patch("embedding_cache._get_model", return_value=mock_model):
            from embedding_cache import get_embedding, clear_cache
            clear_cache()

            r1 = get_embedding("авторизация", "test-model")
            r2 = get_embedding("база данных", "test-model")

        assert mock_model.encode.call_count == 2
        assert r1 != r2

    def test_returns_list_of_floats(self, mock_model):
        """get_embedding возвращает list[float]."""
        with patch("embedding_cache._get_model", return_value=mock_model):
            from embedding_cache import get_embedding, clear_cache
            clear_cache()
            result = get_embedding("тест", "test-model")

        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)
        assert len(result) == 384

    def test_cache_stats_tracks_hits_and_misses(self, mock_model):
        """cache_stats() показывает точные hits/misses."""
        with patch("embedding_cache._get_model", return_value=mock_model):
            from embedding_cache import get_embedding, cache_stats, clear_cache
            clear_cache()

            get_embedding("первый текст", "model")    # miss
            get_embedding("второй текст", "model")   # miss
            get_embedding("первый текст", "model")   # hit
            get_embedding("первый текст", "model")   # hit

        stats = cache_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 50.0

    def test_clear_cache_resets_stats(self, mock_model):
        """После clear_cache() — нулевые hits и misses."""
        with patch("embedding_cache._get_model", return_value=mock_model):
            from embedding_cache import get_embedding, cache_stats, clear_cache
            clear_cache()

            get_embedding("тест", "model")
            get_embedding("тест", "model")

        stats_before = cache_stats()
        assert stats_before["hits"] > 0

        from embedding_cache import clear_cache
        clear_cache()
        stats_after = cache_stats()
        assert stats_after["hits"] == 0
        assert stats_after["currsize"] == 0

    def test_maxsize_respected(self, mock_model):
        """Кэш не растёт бесконечно (maxsize=512)."""
        from embedding_cache import cache_stats
        stats = cache_stats()
        assert stats["maxsize"] == 512

    def test_different_models_cached_separately(self, mock_model):
        """Один текст в двух моделях — два разных вычисления."""
        with patch("embedding_cache._get_model", return_value=mock_model):
            from embedding_cache import get_embedding, clear_cache
            clear_cache()

            r1 = get_embedding("авторизация", "model-a")
            r2 = get_embedding("авторизация", "model-b")

        # Разные модели → два вызова encode
        assert mock_model.encode.call_count == 2
