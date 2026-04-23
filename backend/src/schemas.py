"""
schemas.py — Pydantic модели для запросов и ответов API.
"""
from pathlib import Path

from pydantic import BaseModel, Field


# ── Поиск ─────────────────────────────────────────────────────────────────────

class HistoryMessage(BaseModel):
    """Одно сообщение в истории диалога для многоходового поиска."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=8000)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    project: str | None = None
    top_k: int = Field(5, ge=1, le=20)
    mode: str = Field("answer", pattern="^(search|answer|patch|global)$")
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=10,
        description="История предыдущих сообщений для многоходового диалога",
    )


class ChunkResult(BaseModel):
    project: str
    file: str
    role: str
    score: float
    content_preview: str


class SearchResponse(BaseModel):
    chunks: list[ChunkResult]


# ── Проекты ───────────────────────────────────────────────────────────────────

class AddProjectRequest(BaseModel):
    path: str = Field(..., description="Абсолютный путь к папке проекта")
    name: str | None = Field(None, description="Имя проекта (по умолчанию — имя папки)")


class ProjectInfo(BaseModel):
    name: str
    file_count: int
    project_type: str
    has_graph: bool = False
    graph_stats: dict = Field(default_factory=dict)


class ProjectsResponse(BaseModel):
    projects: list[ProjectInfo]


# ── Граф ──────────────────────────────────────────────────────────────────────

class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    stats: dict


class CostEstimateResponse(BaseModel):
    file_count: int
    estimated_tokens: int
    estimated_cost_usd: float
    estimated_cost_display: str
