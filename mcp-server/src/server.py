"""
mcp-server/src/server.py — MCP сервер RAG Dev Assistant.

Инструменты для AI-ассистентов (Claude Desktop, Cursor, Windsurf):
  - search_project    семантический поиск по коду
  - list_projects     список проиндексированных проектов
  - get_file_content  содержимое конкретного файла
  - get_graph_summary архитектурное резюме проекта

Аутентификация: Bearer token через заголовок Authorization.
  MCP_API_KEY="" → auth отключена (локальный режим)
  MCP_API_KEY="secret" → все запросы должны содержать "Authorization: Bearer secret"

Транспорт: HTTP SSE (работает и локально, и через VPS URL).
"""
import logging
import os
import time
from collections import defaultdict
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

log = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_INTERNAL_URL", "http://backend:8000")
MCP_API_KEY = os.getenv("MCP_API_KEY", "").strip()

server = Server("rag-dev-assistant")


# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Простой in-memory rate limiter: N запросов в M секунд на IP.
    Для production заменить на Redis-based.
    """
    def __init__(self, max_requests: int = 60, window_sec: int = 60):
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._counts: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """
        Проверяет допустимость запроса.
        Возвращает (allowed, remaining).
        """
        now = time.time()
        window_start = now - self.window_sec
        timestamps = self._counts[client_ip]

        # Убираем устаревшие записи
        self._counts[client_ip] = [t for t in timestamps if t > window_start]
        current = len(self._counts[client_ip])

        if current >= self.max_requests:
            return False, 0

        self._counts[client_ip].append(now)
        return True, self.max_requests - current - 1


_rate_limiter = RateLimiter(max_requests=60, window_sec=60)


# ── Auth + Rate Limit Middleware ──────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Проверяет Bearer token и rate limit для каждого запроса.
    Пропускает /health без аутентификации.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Health check — без auth
        if request.url.path == "/health":
            return await call_next(request)

        # Rate limiting по IP
        client_ip = request.client.host if request.client else "unknown"
        allowed, remaining = _rate_limiter.is_allowed(client_ip)

        if not allowed:
            log.warning("Rate limit exceeded", extra={"ip": client_ip})
            return JSONResponse(
                status_code=429,
                content={"error": "Too Many Requests", "message": "Лимит: 60 запросов в минуту"},
                headers={"Retry-After": "60"},
            )

        # Auth — только если MCP_API_KEY задан
        if MCP_API_KEY:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized", "message": "Требуется Authorization: Bearer <token>"},
                )
            token = auth_header.removeprefix("Bearer ").strip()
            if token != MCP_API_KEY:
                log.warning("Invalid MCP API key", extra={"ip": client_ip})
                return JSONResponse(
                    status_code=403,
                    content={"error": "Forbidden", "message": "Неверный API ключ"},
                )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# ── Инструменты ───────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_project",
            description=(
                "Semantic search over indexed IT projects (code, configs, docs). "
                "Use this when you need to find code related to a specific concept, "
                "function, or topic. Returns relevant code chunks with file paths. "
                "Start with this tool before asking general questions about the codebase."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (natural language or code)",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name to search in. Omit to search all projects.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (1-10, default 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_projects",
            description=(
                "List all indexed IT projects with their stats. "
                "Call this first to understand what projects are available "
                "before using search_project or get_graph_summary."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_graph_summary",
            description=(
                "Get a high-level architectural summary of a project or all projects. "
                "Use this to quickly understand project architecture without reading code. "
                "Perfect for onboarding: call this at the start of a session to get context. "
                "Requires Knowledge Graph to be built (via the app UI)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project name. Omit for cross-project summary.",
                    },
                },
            },
        ),
        Tool(
            name="get_file_content",
            description=(
                "Get the indexed content of a specific file from a project. "
                "Use after search_project when you need to see the complete file context. "
                "Note: returns the indexed version (may be signatures-only for large files)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project name",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Relative file path (e.g. 'src/handlers/start.py')",
                    },
                },
                "required": ["project", "file_path"],
            },
        ),
    ]


# ── Обработчики инструментов ──────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Добавляем auth заголовок если задан
    headers: dict[str, str] = {}
    if MCP_API_KEY:
        headers["X-Internal-Key"] = MCP_API_KEY

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        try:
            if name == "search_project":
                return await _search_project(client, arguments)
            elif name == "list_projects":
                return await _list_projects(client)
            elif name == "get_graph_summary":
                return await _get_graph_summary(client, arguments)
            elif name == "get_file_content":
                return await _get_file_content(client, arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
        except httpx.TimeoutException:
            log.error(f"Timeout calling backend for tool: {name}")
            return [TextContent(type="text", text="Error: Backend timeout. Убедись что бэкенд запущен.")]
        except httpx.ConnectError:
            log.error(f"Cannot connect to backend for tool: {name}")
            return [TextContent(type="text", text=f"Error: Не удалось подключиться к бэкенду ({BACKEND_URL}).")]
        except Exception as e:
            log.error(f"MCP tool error [{name}]: {e}", exc_info=True)
            return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _search_project(client: httpx.AsyncClient, args: dict) -> list[TextContent]:
    resp = await client.post(
        f"{BACKEND_URL}/api/search/",
        json={
            "query":   args["query"],
            "project": args.get("project"),
            "top_k":   min(int(args.get("top_k", 5)), 10),
            "mode":    "search",
        },
    )
    if resp.status_code == 404:
        return [TextContent(type="text", text="No results found. Make sure the project is indexed.")]
    resp.raise_for_status()
    data = resp.json()

    if not data.get("chunks"):
        return [TextContent(type="text", text="No results found in indexed projects.")]

    lines = [f"Found {len(data['chunks'])} relevant chunks:\n"]
    for i, chunk in enumerate(data["chunks"], 1):
        lines.append(
            f"[{i}] {chunk['project']}/{chunk['file']} "
            f"(score: {chunk['score']}, role: {chunk['role']})\n"
            f"{chunk['content_preview']}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


async def _list_projects(client: httpx.AsyncClient) -> list[TextContent]:
    resp = await client.get(f"{BACKEND_URL}/api/projects/")
    resp.raise_for_status()
    data = resp.json()

    projects = data.get("projects", [])
    if not projects:
        return [TextContent(type="text", text="No projects indexed yet. Add a project in the RAG Dev Assistant app.")]

    lines = [f"Indexed projects ({len(projects)}):\n"]
    for p in projects:
        graph_status = "✓ Graph built" if p["has_graph"] else "— No graph"
        lines.append(
            f"• {p['name']} — {p['file_count']} files, "
            f"type: {p['project_type']}, {graph_status}"
        )
    return [TextContent(type="text", text="\n".join(lines))]


async def _get_graph_summary(client: httpx.AsyncClient, args: dict) -> list[TextContent]:
    project = args.get("project")
    url = (
        f"{BACKEND_URL}/api/graph/summaries"
        + (f"?project={project}" if project else "")
    )
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()

    summaries = data.get("summaries", [])
    if not summaries:
        return [TextContent(
            type="text",
            text=(
                "Knowledge Graph not built yet. "
                "Please build it via the RAG Dev Assistant app: "
                "Projects → Build Knowledge Graph."
            ),
        )]

    lines = [f"Architecture summary ({len(summaries)} clusters):\n"]
    for s in summaries:
        lines.append(f"## {s['title']} (project: {s['project'] or 'all'})")
        lines.append(s["summary"])
        lines.append("")
    return [TextContent(type="text", text="\n".join(lines))]


async def _get_file_content(client: httpx.AsyncClient, args: dict) -> list[TextContent]:
    resp = await client.post(
        f"{BACKEND_URL}/api/search/",
        json={
            "query":   args["file_path"],
            "project": args["project"],
            "top_k":   1,
            "mode":    "search",
        },
    )
    resp.raise_for_status()
    data = resp.json()

    for chunk in data.get("chunks", []):
        if chunk["file"] == args["file_path"]:
            return [TextContent(
                type="text",
                text=f"File: {chunk['project']}/{chunk['file']}\n\n{chunk['content_preview']}",
            )]

    return [TextContent(
        type="text",
        text=f"File '{args['file_path']}' not found in project '{args['project']}'.",
    )]


# ── Starlette приложение ──────────────────────────────────────────────────────

sse_transport = SseServerTransport("/mcp/messages/")


async def handle_sse(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0], streams[1], server.create_initialization_options()
        )


async def health(request: Request):
    return JSONResponse({
        "status": "ok",
        "auth_enabled": bool(MCP_API_KEY),
        "backend_url": BACKEND_URL,
    })


app = Starlette(
    routes=[
        Route("/health",       endpoint=health),
        Route("/mcp/sse",      endpoint=handle_sse),
        Mount("/mcp/messages/", app=sse_transport.handle_post_message),
    ]
)

# Добавляем auth + rate limit middleware
app.add_middleware(AuthMiddleware)


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("MCP_SERVER_PORT", "27183"))
    log.info(f"MCP Server запускается на порту {port}, auth={'enabled' if MCP_API_KEY else 'disabled'}")
    uvicorn.run(app, host="0.0.0.0", port=port)
