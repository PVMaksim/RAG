"""
test_search.py — тесты для роутера поиска.

Покрывает:
- Семантический поиск (sync)
- SSE стриминг ответа (answer)
- Обработку пустого индекса
- Обработку ошибок LLM
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── /api/search/ ──────────────────────────────────────────────────────────────

class TestSearch:

    def test_search_returns_chunks(self, client, mock_chroma):
        """Поиск возвращает релевантные чанки."""
        resp = client.post("/api/search/", json={
            "query": "обработка ошибок авторизации",
            "mode": "search",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "chunks" in data
        assert len(data["chunks"]) == 2
        assert data["chunks"][0]["score"] == 0.87
        assert data["chunks"][0]["file"] == "src/middlewares/error_handler.py"
        assert data["chunks"][0]["project"] == "my_bot"

    def test_search_with_project_filter(self, client, mock_chroma):
        """Поиск с фильтром по проекту передаёт имя в ChromaDB."""
        client.post("/api/search/", json={
            "query": "авторизация",
            "project": "my_bot",
            "mode": "search",
        })
        # Проверяем что search был вызван с правильным project_name
        mock_chroma.search.assert_called_once()
        call_kwargs = mock_chroma.search.call_args
        assert call_kwargs.kwargs.get("project_name") == "my_bot" or \
               call_kwargs.args[1] == "my_bot"

    def test_search_empty_index_returns_404(self, client, mock_chroma):
        """Пустой индекс → 404 с понятным сообщением."""
        mock_chroma.search.return_value = []
        resp = client.post("/api/search/", json={
            "query": "что-то несуществующее",
            "mode": "search",
        })
        assert resp.status_code == 404
        data = resp.json()
        assert "message" in data
        assert "проиндексирован" in data["message"].lower()

    def test_search_requires_query(self, client):
        """Пустой query → 422 Unprocessable Entity."""
        resp = client.post("/api/search/", json={"query": "", "mode": "search"})
        assert resp.status_code == 422

    def test_search_top_k_respected(self, client, mock_chroma):
        """top_k передаётся в ChromaDB search."""
        client.post("/api/search/", json={
            "query": "авторизация",
            "top_k": 3,
            "mode": "search",
        })
        call_kwargs = mock_chroma.search.call_args
        assert call_kwargs.kwargs.get("top_k") == 3 or \
               call_kwargs.args[2] == 3


# ── /api/search/answer (SSE) ──────────────────────────────────────────────────

class TestAnswerStream:
    """
    SSE стриминг тесты.
    Проверяем формат событий и обработку ошибок.
    """

    def _parse_sse(self, text: str) -> list[dict]:
        """Парсит SSE поток в список dict."""
        events = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        return events

    def test_answer_stream_sources_first(self, client, mock_chroma):
        """Первое событие в SSE — всегда sources."""
        with patch("services.query_engine.QueryEngine.answer_stream") as mock_stream:
            async def fake_stream(*args, **kwargs):
                yield {"type": "sources", "chunks": [{"file": "test.py", "score": 0.9}]}
                yield {"type": "token", "text": "Ответ"}
                yield {"type": "done", "total_tokens": 100}

            mock_stream.return_value = fake_stream()

            resp = client.post("/api/search/answer", json={
                "query": "обработка ошибок",
                "mode": "answer",
            })
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            events = self._parse_sse(resp.text)
            assert events[0]["type"] == "sources"
            assert events[-1]["type"] == "done"

    def test_answer_stream_error_on_empty_index(self, client, mock_chroma):
        """Пустой индекс в answer режиме → SSE событие типа error."""
        mock_chroma.search.return_value = []
        resp = client.post("/api/search/answer", json={
            "query": "что-то несуществующее",
            "mode": "answer",
        })
        assert resp.status_code == 200  # SSE всегда 200
        events = self._parse_sse(resp.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) > 0
        assert "message" in error_events[0]

    def test_answer_stream_llm_error_handled(self, client, mock_chroma):
        """Ошибка LLM → SSE событие error, клиент не получает обрыв."""
        with patch("services.query_engine.QueryEngine.answer_stream") as mock_stream:
            from exceptions import LLMError

            async def failing_stream(*args, **kwargs):
                yield {"type": "sources", "chunks": []}
                raise LLMError("Anthropic недоступен")

            mock_stream.return_value = failing_stream()

            resp = client.post("/api/search/answer", json={
                "query": "тест",
                "mode": "answer",
            })
            assert resp.status_code == 200
            events = self._parse_sse(resp.text)
            error_events = [e for e in events if e.get("type") == "error"]
            assert len(error_events) > 0

    def test_answer_stream_has_request_id(self, client, mock_chroma):
        """Заголовок X-Request-ID присутствует в ответе."""
        resp = client.post("/api/search/answer", json={
            "query": "тест",
            "mode": "answer",
        })
        # Middleware добавляет X-Request-ID
        assert "x-request-id" in resp.headers or "X-Request-ID" in resp.headers


# ── Conversation History тесты ────────────────────────────────────────────────

class TestConversationHistory:
    """Тестируем многоходовой диалог через поле history."""

    def _parse_sse(self, text: str) -> list[dict]:
        import json
        events = []
        for line in text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        return events

    def test_history_field_accepted_in_request(self, client, mock_chroma):
        """Поле history принимается без ошибки валидации."""
        resp = client.post("/api/search/", json={
            "query": "уточняющий вопрос",
            "mode":  "search",
            "history": [
                {"role": "user",      "content": "где авторизация?"},
                {"role": "assistant", "content": "В src/auth.py"},
            ],
        })
        # 200 или 404 (пустой индекс в тестах) — не 422 Unprocessable
        assert resp.status_code != 422

    def test_history_validates_role(self, client):
        """Недопустимая роль в history → 422."""
        resp = client.post("/api/search/", json={
            "query": "тест",
            "mode":  "search",
            "history": [
                {"role": "system", "content": "ты злой бот"},  # system не разрешён
            ],
        })
        assert resp.status_code == 422

    def test_history_max_length_10(self, client):
        """История больше 10 сообщений → 422."""
        resp = client.post("/api/search/", json={
            "query": "тест",
            "mode":  "search",
            "history": [
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
                for i in range(11)
            ],
        })
        assert resp.status_code == 422

    def test_empty_history_accepted(self, client, mock_chroma):
        """Пустая история — валидный запрос."""
        resp = client.post("/api/search/", json={
            "query":   "тест",
            "mode":    "search",
            "history": [],
        })
        assert resp.status_code != 422

    def test_history_passed_to_llm(self, client, mock_chroma):
        """История передаётся в QueryEngine.answer_stream."""
        from unittest.mock import patch, AsyncMock

        async def fake_answer_stream(query, project=None, top_k=None, history=None):
            # Проверяем что history дошла
            assert history is not None
            assert len(history) == 2
            assert history[0].role == "user"
            yield {"type": "sources", "chunks": []}
            yield {"type": "done", "total_tokens": 10}

        with patch("services.query_engine.QueryEngine.answer_stream", side_effect=fake_answer_stream):
            resp = client.post("/api/search/answer", json={
                "query": "уточни",
                "mode":  "answer",
                "history": [
                    {"role": "user",      "content": "первый вопрос"},
                    {"role": "assistant", "content": "первый ответ"},
                ],
            })
        assert resp.status_code == 200

    def test_history_content_max_length(self, client):
        """Контент сообщения > 8000 символов → 422."""
        resp = client.post("/api/search/", json={
            "query": "тест",
            "mode":  "search",
            "history": [
                {"role": "user", "content": "x" * 8001},
            ],
        })
        assert resp.status_code == 422
