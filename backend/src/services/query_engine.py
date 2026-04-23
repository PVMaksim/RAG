"""
query_engine.py — сервис поиска и генерации ответов.
Поддерживает SSE стриминг. Retry на Anthropic API.
"""
import asyncio
import logging
from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic
from exceptions import EmptyIndexError, GraphNotBuiltError, LLMError
from logging_config import timed
from retry import with_anthropic_retry
from storage.chroma_store import ChromaStore

log = logging.getLogger(__name__)


# ── Тип для истории разговора ─────────────────────────────────────────────────

from dataclasses import dataclass, field as dc_field

@dataclass
class ConversationMessage:
    """Одно сообщение в истории разговора."""
    role: str   # "user" | "assistant"
    content: str

ANSWER_SYSTEM = (
    "Ты старший разработчик. Тебе предоставлены фрагменты кода и документации "
    "из IT-проектов разработчика. Отвечай конкретно, ссылайся на файлы из контекста. "
    "Если информации не хватает — скажи об этом прямо. "
    "Отвечай на том же языке, на котором задан вопрос."
)

PATCH_SYSTEM = (
    "Ты старший разработчик. Предложи конкретный патч (diff или блоки кода). "
    "Указывай точный файл и место изменения. "
    "Уважай существующий стиль кода и архитектуру."
)

GLOBAL_SYSTEM = (
    "Ты технический архитектор. Тебе предоставлены тематические резюме кластеров кода. "
    "Синтезируй ответ, выделяй паттерны и архитектурные решения. "
    "Сравнивай подходы разных проектов если они различаются."
)


class QueryEngine:

    def __init__(
        self,
        chroma_store: ChromaStore,
        embedding_model: str,
        anthropic_api_key: str,
        claude_model: str,
        default_top_k: int = 5,
    ) -> None:
        self._chroma = chroma_store
        self._embedding_model_name = embedding_model
        self._claude_model = claude_model
        self._default_top_k = default_top_k
        self._anthropic = AsyncAnthropic(api_key=anthropic_api_key)

    @timed("embedding")
    async def _embed(self, text: str) -> list[float]:
        """Async embedding с LRU кэшем — повторные запросы возвращаются мгновенно."""
        from embedding_cache import get_embedding
        return await asyncio.get_event_loop().run_in_executor(
            None, get_embedding, text, self._embedding_model_name
        )

    # ── Поиск ─────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        project: str | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        k = top_k or self._default_top_k
        embedding = await self._embed(query)
        chunks = self._chroma.search(embedding, project_name=project, top_k=k)
        log.info(
            "Поиск выполнен",
            extra={"query_preview": query[:60], "results": len(chunks), "project": project},
        )
        return chunks

    @staticmethod
    def build_context(chunks: list[dict]) -> str:
        parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            parts.append(
                f"--- Фрагмент {i} | проект: {meta.get('project')} | "
                f"файл: {meta.get('rel_path')} | роль: {meta.get('graph_role')} | "
                f"релевантность: {chunk['score']} ---\n{chunk['content']}"
            )
        return "\n\n".join(parts)

    # ── LLM вызов с retry ─────────────────────────────────────────────────

    @with_anthropic_retry()
    async def _create_message(self, system: str, user_message: str, max_tokens: int = 2000):
        """Единая точка вызова Anthropic API — retry применяется здесь."""
        return await self._anthropic.messages.create(
            model=self._claude_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )

    # ── Ответ через LLM (SSE) ─────────────────────────────────────────────

    async def answer_stream(
        self,
        query: str,
        project: str | None = None,
        top_k: int | None = None,
        history: list[ConversationMessage] | None = None,
    ) -> AsyncGenerator[dict, None]:
        chunks = await self.search(query, project, top_k)
        if not chunks:
            raise EmptyIndexError(project)

        yield {
            "type": "sources",
            "chunks": [
                {
                    "project": c["metadata"].get("project"),
                    "file":    c["metadata"].get("rel_path"),
                    "role":    c["metadata"].get("graph_role"),
                    "score":   c["score"],
                    "content_preview": c["content"][:300],
                }
                for c in chunks
            ],
        }

        context = self.build_context(chunks)
        user_message = f"Контекст из RAG:\n\n{context}\n\n---\n\nВопрос: {query}"

        # Строим историю сообщений для многоходового диалога
        messages = []
        if history:
            for msg in history[-6:]:  # Максимум 6 последних сообщений (~3 хода)
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        log.info(
            "Начинаю стриминг ответа",
            extra={"mode": "answer", "chunks": len(chunks), "history_turns": len(history or [])},
        )
        total_tokens = 0

        try:
            async with self._anthropic.messages.stream(
                model=self._claude_model,
                max_tokens=2000,
                system=ANSWER_SYSTEM,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "token", "text": text}
                final = await stream.get_final_message()
                total_tokens = final.usage.input_tokens + final.usage.output_tokens
        except Exception as exc:
            # Конвертируем Anthropic ошибки — safe_sse_stream их поймает и отправит клиенту
            raise LLMError(f"Ошибка стриминга: {exc}") from exc

        log.info("Стриминг завершён", extra={"mode": "answer", "total_tokens": total_tokens})
        yield {"type": "done", "total_tokens": total_tokens}

    # ── Патчинг кода (SSE) ────────────────────────────────────────────────

    async def patch_stream(
        self,
        query: str,
        project: str | None = None,
        top_k: int | None = None,
        history: list[ConversationMessage] | None = None,
    ) -> AsyncGenerator[dict, None]:
        chunks = await self.search(query, project, top_k)
        if not chunks:
            raise EmptyIndexError(project)

        yield {
            "type": "sources",
            "chunks": [
                {"project": c["metadata"].get("project"), "file": c["metadata"].get("rel_path"), "score": c["score"]}
                for c in chunks
            ],
        }

        context = self.build_context(chunks)
        user_message = (
            f"Контекст из RAG:\n\n{context}\n\n---\n\n"
            f"Задача: {query}\n\n"
            "Предложи минимальный патч: файл, что изменить."
        )

        messages = []
        if history:
            for msg in history[-4:]:  # Для patch достаточно 2 хода
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        try:
            async with self._anthropic.messages.stream(
                model=self._claude_model,
                max_tokens=2000,
                system=PATCH_SYSTEM,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "token", "text": text}
        except Exception as exc:
            raise LLMError(f"Ошибка стриминга патча: {exc}") from exc

        yield {"type": "done"}

    # ── GlobalRAG (SSE) ───────────────────────────────────────────────────

    async def global_answer_stream(self, query: str) -> AsyncGenerator[dict, None]:
        embedding = await self._embed(query)
        summaries = self._chroma.search_summaries(embedding, top_k=10)

        if not summaries:
            raise GraphNotBuiltError()

        yield {
            "type": "sources",
            "summaries": [
                {
                    "title":   s["metadata"].get("title", "Кластер"),
                    "project": s["metadata"].get("project"),
                    "score":   s["score"],
                    "preview": s["summary"][:200],
                }
                for s in summaries
            ],
        }

        context = "\n\n".join(
            f"--- Кластер {i} | {s['metadata'].get('title','?')} | "
            f"проект: {s['metadata'].get('project','все')} | релевантность: {s['score']} ---\n{s['summary']}"
            for i, s in enumerate(summaries, 1)
        )
        user_message = f"Тематические резюме кластеров:\n\n{context}\n\n---\n\nВопрос: {query}"

        try:
            async with self._anthropic.messages.stream(
                model=self._claude_model,
                max_tokens=3000,
                system=GLOBAL_SYSTEM,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "token", "text": text}
        except Exception as exc:
            raise LLMError(f"Ошибка GlobalRAG стриминга: {exc}") from exc

        yield {"type": "done"}
