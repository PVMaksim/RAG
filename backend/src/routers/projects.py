"""
projects.py — роутер управления проектами.
CRUD + сканирование с SSE прогрессом.
"""
import logging
from pathlib import Path

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from config import get_settings
from rate_limiter import limiter
from dependencies import get_chroma, get_graph_store, get_graphrag, get_scanner
from exceptions import ProjectNotFoundError, ProjectPathNotFoundError
from middleware.error_handler import safe_sse_stream
from schemas import AddProjectRequest, CostEstimateResponse, ProjectInfo, ProjectsResponse
from services.graphrag import GraphRAGEngine
from services.scanner import ProjectScanner
from services.git_service import GitService, GitServiceError
from storage.chroma_store import ChromaStore
from storage.graph_store import GraphStore
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


def get_git_service(settings=Depends(get_settings)) -> GitService:
    return GitService(settings.projects_base_path)
router = APIRouter(prefix="/projects", tags=["projects"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/", response_model=ProjectsResponse)
async def list_projects(
    chroma: ChromaStore = Depends(get_chroma),
    graph_store: GraphStore = Depends(get_graph_store),
) -> ProjectsResponse:
    projects_raw = chroma.list_projects()
    projects = []
    for p in projects_raw:
        name = p["name"]
        has_graph = graph_store.has_graph(name)
        projects.append(ProjectInfo(
            name=name,
            file_count=p["file_count"],
            project_type=p["project_type"],
            has_graph=has_graph,
            graph_stats=graph_store.get_stats(name) if has_graph else {},
        ))
    return ProjectsResponse(projects=projects)


@router.post("/")
async def add_project(
    req: AddProjectRequest,
    settings=Depends(get_settings),
) -> dict:
    project_path = Path(req.path)

    if not project_path.exists():
        alt_path = settings.projects_base_path / req.path.lstrip("/")
        if alt_path.exists():
            project_path = alt_path
        else:
            raise ProjectPathNotFoundError(req.path)

    if not project_path.is_dir():
        from exceptions import RAGError
        raise RAGError(f"Путь не является директорией: {req.path}", http_status=400)

    name = req.name or project_path.name
    log.info("Проект добавлен", extra={"name": name, "path": str(project_path)})
    return {"status": "ok", "name": name, "path": str(project_path)}


@router.delete("/{project_name}")
async def delete_project(
    project_name: str,
    chroma: ChromaStore = Depends(get_chroma),
    graph_store: GraphStore = Depends(get_graph_store),
) -> dict:
    if not chroma.delete_project(project_name):
        raise ProjectNotFoundError(project_name)
    graph_store.delete_project_nodes(project_name)
    log.info("Проект удалён", extra={"project": project_name})
    return {"status": "deleted", "project": project_name}


@router.post("/{project_name}/scan")
@limiter.limit("5/minute")
async def scan_project(
    request: Request,
    project_name: str,
    scanner: ProjectScanner = Depends(get_scanner),
    settings=Depends(get_settings),
) -> StreamingResponse:
    """Сканировать проект из projects_base_path. SSE прогресс."""
    project_path = settings.projects_base_path / project_name

    async def _gen():
        if not project_path.exists():
            raise ProjectPathNotFoundError(str(project_path))
        async for progress in scanner.scan(project_path):
            yield progress.__dict__

    return StreamingResponse(
        safe_sse_stream(_gen(), f"scan:{project_name}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{project_name}/scan-path")
async def scan_project_by_path(
    project_name: str,
    req: AddProjectRequest,
    scanner: ProjectScanner = Depends(get_scanner),
) -> StreamingResponse:
    """Сканировать проект по произвольному пути (локальный режим)."""
    project_path = Path(req.path)

    async def _gen():
        if not project_path.exists():
            raise ProjectPathNotFoundError(req.path)
        async for progress in scanner.scan(project_path):
            yield progress.__dict__

    return StreamingResponse(
        safe_sse_stream(_gen(), f"scan-path:{project_name}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/{project_name}/stats")
async def project_stats(
    project_name: str,
    chroma: ChromaStore = Depends(get_chroma),
    graph_store: GraphStore = Depends(get_graph_store),
) -> dict:
    collection = chroma.get_project(project_name)
    if not collection:
        raise ProjectNotFoundError(project_name)
    return {
        "name": project_name,
        "file_count": collection.count(),
        "has_graph": graph_store.has_graph(project_name),
        "graph_stats": graph_store.get_stats(project_name),
    }


@router.get("/{project_name}/graph/estimate", response_model=CostEstimateResponse)
async def estimate_graph_cost(
    project_name: str,
    graphrag: GraphRAGEngine = Depends(get_graphrag),
) -> CostEstimateResponse:
    estimate = graphrag.estimate_cost(project_name)
    if "error" in estimate:
        raise ProjectNotFoundError(project_name)
    return CostEstimateResponse(**estimate)


@router.post("/{project_name}/graph/build")
@limiter.limit("3/minute")
async def build_graph(
    request: Request,
    project_name: str,
    graphrag: GraphRAGEngine = Depends(get_graphrag),
) -> StreamingResponse:
    """Построить Knowledge Graph. SSE прогресс."""
    async def _gen():
        async for event in graphrag.build_graph(project_name):
            yield event if isinstance(event, dict) else event.__dict__

    return StreamingResponse(
        safe_sse_stream(_gen(), f"graph-build:{project_name}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── Git интеграция ────────────────────────────────────────────────────────────

class GitCloneRequest(BaseModel):
    git_url: str = Field(..., description="Git URL (https:// или git@)")
    project_name: str | None = Field(None, description="Имя проекта (по умолчанию из URL)")


@router.post("/git/clone")
@limiter.limit("3/minute")
async def git_clone(
    request: Request,
    req: GitCloneRequest,
    git_svc: GitService = Depends(get_git_service),
    scanner: ProjectScanner = Depends(get_scanner),
) -> StreamingResponse:
    """
    Клонировать репозиторий по Git URL и сразу проиндексировать.
    SSE: clone_progress → scan_progress → done
    """
    # Валидируем URL до начала операции
    valid, err = GitService.validate_git_url(req.git_url)
    if not valid:
        from exceptions import RAGError
        raise RAGError(err, http_status=400)

    async def _gen():
        yield {"type": "git_start", "url": req.git_url}

        try:
            project_path = await git_svc.clone_or_pull(req.git_url, req.project_name)
        except GitServiceError as e:
            raise  # safe_sse_stream поймает и отправит error событие

        yield {"type": "git_done", "project": project_path.name, "path": str(project_path)}

        # После клонирования — сразу сканируем
        async for progress in scanner.scan(project_path):
            yield progress.__dict__

    return StreamingResponse(
        safe_sse_stream(_gen(), f"git-clone:{req.project_name or 'unknown'}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/git/pull/{project_name}")
@limiter.limit("5/minute")
async def git_pull(
    request: Request,
    project_name: str,
    git_svc: GitService = Depends(get_git_service),
    scanner: ProjectScanner = Depends(get_scanner),
) -> StreamingResponse:
    """
    Обновить существующий Git проект (git pull) и переиндексировать.
    """
    async def _gen():
        project_path = git_svc._base / project_name
        if not project_path.exists():
            from exceptions import ProjectPathNotFoundError
            raise ProjectPathNotFoundError(str(project_path))
        if not (project_path / ".git").exists():
            from exceptions import GitServiceError
            raise GitServiceError(f"'{project_name}' не является Git репозиторием")

        yield {"type": "git_start", "project": project_name}
        await git_svc.clone_or_pull(
            GitService._get_remote_url(project_path) or "",
            project_name
        )
        yield {"type": "git_done", "project": project_name}

        async for progress in scanner.scan(project_path):
            yield progress.__dict__

    return StreamingResponse(
        safe_sse_stream(_gen(), f"git-pull:{project_name}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/git/list")
async def git_list_local(
    git_svc: GitService = Depends(get_git_service),
) -> dict:
    """Список проектов в projects_base_path (локальные папки)."""
    return {"projects": git_svc.list_local()}
