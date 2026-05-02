"""
search.py — роутер поиска.
"""
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from dependencies import get_query_engine
from exceptions import EmptyIndexError
from middleware.error_handler import safe_sse_stream
from rate_limiter import limiter
from schemas import SearchRequest, SearchResponse
from services.query_engine import QueryEngine

log = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])

@router.post("/")
@limiter.limit("30/minute")
async def search(
    request: Request,
    req: SearchRequest,
    engine: QueryEngine = Depends(get_query_engine),
):
    """Семантический поиск без LLM."""
    chunks = await engine.search(req.query, req.project, req.top_k)
    if not chunks:
        raise EmptyIndexError(req.project)
    return JSONResponse(content=SearchResponse(chunks=[
        {
            "project": c["metadata"].get("project", ""),
            "file": c["metadata"].get("rel_path", ""),
            "role": c["metadata"].get("graph_role", ""),
            "score": c["score"],
            "content_preview": c["content"][:500],
        }
        for c in chunks
    ]).model_dump())
