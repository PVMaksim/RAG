"""
search.py — роутер поиска.
Эндпоинты: /search (sync), /answer (SSE), /patch (SSE), /global (SSE).
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from dependencies import get_query_engine
from exceptions import EmptyIndexError
from middleware.error_handler import safe_sse_stream
from rate_limiter import limiter
from schemas import SearchRequest, SearchResponse
from services.query_engine import QueryEngine

log = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.post("/", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search(
    request: Request,
    req: SearchRequest,
    engine: QueryEngine = Depends(get_query_engine),
) -> SearchResponse:
    """Семантический поиск без LLM. Возвращает top-K чанков."""
    chunks = await engine.search(req.query, req.project, req.top_k)

    if not chunks:
        raise EmptyIndexError(req.project)

    return SearchResponse(chunks=[
        {
            "project":         c["metadata"].get("project", ""),
            "file":            c["metadata"].get("rel_path", ""),
            "role":            c["metadata"].get("graph_role", ""),
            "score":           c["score"],
            "content_preview": c["content"][:500],
        }
        for c in chunks
    ])


@router.post("/answer")
@limiter.limit("20/minute")
async def answer(
    request: Request,
    req: SearchRequest,
    engine: QueryEngine = Depends(get_query_engine),
) -> StreamingResponse:
    """
    Поиск + ответ Claude. SSE стриминг.
    События: sources → token × N → done | error
    """
    return StreamingResponse(
        safe_sse_stream(
            engine.answer_stream(
                req.query,
                req.project,
                req.top_k,
                history=[
                    __import__("services.query_engine", fromlist=["ConversationMessage"])
                    .ConversationMessage(role=h.role, content=h.content)
                    for h in req.history
                ] if req.history else None,
            ),
            operation="answer",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/patch")
@limiter.limit("10/minute")
async def patch(
    request: Request,
    req: SearchRequest,
    engine: QueryEngine = Depends(get_query_engine),
) -> StreamingResponse:
    """Режим патчинга кода. SSE стриминг."""
    return StreamingResponse(
        safe_sse_stream(
            engine.patch_stream(req.query, req.project, req.top_k),
            operation="patch",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/global")
@limiter.limit("10/minute")
async def global_search(
    request: Request,
    req: SearchRequest,
    engine: QueryEngine = Depends(get_query_engine),
) -> StreamingResponse:
    """
    GlobalRAG: поиск по community summaries.
    Отвечает на архитектурные вопросы уровня всех проектов.
    """
    return StreamingResponse(
        safe_sse_stream(
            engine.global_answer_stream(req.query),
            operation="global_rag",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
