"""
test_exceptions_and_logging.py — юнит-тесты для инфраструктурного кода.

Проверяем:
- Иерархию исключений
- JSON-форматтер логов
- Retry-декоратор
- safe_sse_stream
- _parse_llm_json
"""
import json
import logging
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ── Тесты exceptions.py ───────────────────────────────────────────────────────

class TestExceptions:

    def test_project_not_found_has_correct_status(self):
        from exceptions import ProjectNotFoundError
        exc = ProjectNotFoundError("my_bot")
        assert exc.http_status == 404
        assert exc.log_level == "warning"
        assert "my_bot" in str(exc)

    def test_empty_index_has_correct_status(self):
        from exceptions import EmptyIndexError
        exc = EmptyIndexError("my_bot")
        assert exc.http_status == 404
        assert "проиндексирован" in exc.message.lower()

    def test_llm_rate_limit_has_retry_after(self):
        from exceptions import LLMRateLimitError
        exc = LLMRateLimitError(retry_after=30)
        assert exc.http_status == 429
        assert exc.retry_after == 30

    def test_llm_response_parse_error_stores_raw(self):
        from exceptions import LLMResponseParseError
        exc = LLMResponseParseError(raw_response='{"broken": json', parse_error="Expecting value")
        assert exc.raw_response == '{"broken": json'
        assert "Expecting value" in exc.message

    def test_rag_error_context_in_str(self):
        """context-поля попадают в строковое представление."""
        from exceptions import RAGError
        exc = RAGError("тест", project="my_bot", file="main.py")
        s = str(exc)
        assert "my_bot" in s
        assert "main.py" in s

    def test_is_subclass_of_exception(self):
        """Все RAGError — потомки Exception (совместимость)."""
        from exceptions import (
            ProjectNotFoundError, EmptyIndexError,
            LLMError, LLMRateLimitError, RAGError,
        )
        assert issubclass(ProjectNotFoundError, Exception)
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMError, RAGError)


# ── Тесты logging_config.py ───────────────────────────────────────────────────

class TestJSONFormatter:

    def _make_record(self, msg: str, level=logging.INFO, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.module",
            level=level,
            pathname="test.py",
            lineno=42,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_json_formatter_output_is_valid_json(self):
        from logging_config import JSONFormatter
        formatter = JSONFormatter()
        record = self._make_record("тест сообщение")
        output = formatter.format(record)
        parsed = json.loads(output)  # не должен кидать исключение
        assert parsed["msg"] == "тест сообщение"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.module"

    def test_json_formatter_includes_request_id(self):
        from logging_config import JSONFormatter, request_id_var
        formatter = JSONFormatter()
        token = request_id_var.set("test-req-123")
        try:
            record = self._make_record("тест")
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["request_id"] == "test-req-123"
        finally:
            request_id_var.reset(token)

    def test_json_formatter_includes_extra_fields(self):
        from logging_config import JSONFormatter
        formatter = JSONFormatter()
        record = self._make_record("тест", duration_ms=142, project="my_bot")
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["duration_ms"] == 142
        assert parsed["project"] == "my_bot"

    def test_json_formatter_handles_exception(self):
        from logging_config import JSONFormatter
        formatter = JSONFormatter()
        try:
            raise ValueError("тестовая ошибка")
        except ValueError:
            record = self._make_record("упало", exc_info=sys.exc_info())
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "traceback" in parsed
        assert "ValueError" in parsed["traceback"]


# ── Тесты retry.py ────────────────────────────────────────────────────────────

class TestRetryDecorator:

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Успешный вызов — никакого retry."""
        from retry import with_anthropic_retry

        call_count = 0

        @with_anthropic_retry()
        async def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await func()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        """RateLimitError → retry после паузы."""
        import anthropic
        from retry import with_anthropic_retry, RetryConfig

        call_count = 0
        config = RetryConfig()
        config.max_attempts = 3
        config.base_delay = 0.01  # Минимальная пауза в тестах

        @with_anthropic_retry(config)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise anthropic.RateLimitError("rate limit", response=MagicMock(), body={})
            return "ok"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await flaky_func()

        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        """После исчерпания попыток — кидает LLMRateLimitError."""
        import anthropic
        from exceptions import LLMRateLimitError
        from retry import with_anthropic_retry, RetryConfig

        config = RetryConfig()
        config.max_attempts = 2
        config.base_delay = 0.01

        @with_anthropic_retry(config)
        async def always_rate_limit():
            raise anthropic.RateLimitError("rate limit", response=MagicMock(), body={})

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(LLMRateLimitError):
                await always_rate_limit()

    @pytest.mark.asyncio
    async def test_auth_error_not_retried(self):
        """AuthenticationError не повторяется — это конфиг ошибка."""
        import anthropic
        from retry import with_anthropic_retry

        call_count = 0

        @with_anthropic_retry()
        async def bad_auth():
            nonlocal call_count
            call_count += 1
            raise anthropic.AuthenticationError("invalid key", response=MagicMock(), body={})

        with pytest.raises(anthropic.AuthenticationError):
            await bad_auth()

        assert call_count == 1  # Только одна попытка


# ── Тесты _parse_llm_json ─────────────────────────────────────────────────────

class TestParseLLMJson:
    """Парсер JSON из ответа LLM должен справляться с разными форматами."""

    def _parse(self, text: str) -> dict:
        from services.graphrag import _parse_llm_json
        return _parse_llm_json(text)

    def test_clean_json(self):
        result = self._parse('{"entities": [], "relations": []}')
        assert result == {"entities": [], "relations": []}

    def test_json_in_markdown_block(self):
        text = '```json\n{"entities": [{"name": "test"}]}\n```'
        result = self._parse(text)
        assert result["entities"][0]["name"] == "test"

    def test_json_in_plain_code_block(self):
        text = '```\n{"entities": []}\n```'
        result = self._parse(text)
        assert result["entities"] == []

    def test_json_with_leading_text(self):
        text = 'Вот сущности:\n\n{"entities": [{"name": "foo"}]}'
        result = self._parse(text)
        assert result["entities"][0]["name"] == "foo"

    def test_invalid_json_raises_parse_error(self):
        from exceptions import LLMResponseParseError
        with pytest.raises(LLMResponseParseError) as exc_info:
            self._parse("это точно не json")
        assert exc_info.value.raw_response == "это точно не json"

    def test_bom_stripped(self):
        text = "\ufeff{\"entities\": []}"
        result = self._parse(text)
        assert result["entities"] == []


# ── Тесты safe_sse_stream ─────────────────────────────────────────────────────

class TestSafeSSEStream:

    @pytest.mark.asyncio
    async def test_normal_events_pass_through(self):
        from middleware.error_handler import safe_sse_stream

        async def good_gen():
            yield {"type": "sources", "chunks": []}
            yield {"type": "token", "text": "hello"}
            yield {"type": "done"}

        events = []
        async for line in safe_sse_stream(good_gen(), "test"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        types = [e["type"] for e in events]
        assert types == ["sources", "token", "done"]

    @pytest.mark.asyncio
    async def test_rag_error_becomes_sse_error(self):
        """RAGError внутри генератора → SSE событие error."""
        from exceptions import EmptyIndexError
        from middleware.error_handler import safe_sse_stream

        async def failing_gen():
            yield {"type": "sources", "chunks": []}
            raise EmptyIndexError("my_bot")

        events = []
        async for line in safe_sse_stream(failing_gen(), "test"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "message" in error_events[0]

    @pytest.mark.asyncio
    async def test_unexpected_exception_becomes_sse_error(self):
        """Любое исключение → SSE событие error, не падение всего стрима."""
        from middleware.error_handler import safe_sse_stream

        async def crashing_gen():
            yield {"type": "start"}
            raise RuntimeError("неожиданное падение")

        events = []
        async for line in safe_sse_stream(crashing_gen(), "test"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        # Внутренняя ошибка не раскрывает детали клиенту
        assert error_events[0]["message"] == "Внутренняя ошибка сервера"

    @pytest.mark.asyncio
    async def test_stream_always_ends_cleanly(self):
        """Стрим завершается даже при ошибке — не зависает."""
        from middleware.error_handler import safe_sse_stream

        async def gen():
            raise Exception("упало сразу")
            yield  # для AsyncGenerator типа

        lines = []
        async for line in safe_sse_stream(gen(), "test"):
            lines.append(line)

        # Должны получить хотя бы одну строку (событие error)
        assert len(lines) > 0


# ── Тесты health endpoint ─────────────────────────────────────────────────────

class TestHealth:

    def test_health_ok(self, client, mock_chroma, mock_graph_store):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "checks" in data
        assert "chroma" in data["checks"]
        assert "anthropic" in data["checks"]

    def test_health_degraded_on_chroma_error(self, client, mock_chroma, mock_graph_store):
        mock_chroma.list_projects.side_effect = Exception("ChromaDB упала")
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["chroma"]["status"] == "error"

    def test_health_has_version(self, client):
        resp = client.get("/health")
        assert resp.json()["version"] == "1.0.0"
