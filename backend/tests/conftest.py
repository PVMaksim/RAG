"""
conftest.py — общие фикстуры для всех тестов.

Используем pytest + httpx AsyncClient для тестирования FastAPI эндпоинтов.
Все внешние зависимости (ChromaDB, Anthropic, SQLite) мокируются —
тесты работают без реального API ключа и без Docker.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient


# ── Fixtures: моки хранилищ ───────────────────────────────────────────────────

@pytest.fixture
def mock_chroma():
    """Мок ChromaStore — не нужен реальный ChromaDB."""
    chroma = MagicMock()
    chroma.list_projects.return_value = [
        {"name": "my_bot", "file_count": 118, "project_type": "telegram_bot"},
        {"name": "fastapi_svc", "file_count": 89, "project_type": "fastapi_service"},
    ]
    chroma.search.return_value = [
        {
            "content": "async def handle_error(bot: Bot, error: Exception):\n    await bot.send_message(...)",
            "metadata": {
                "project": "my_bot",
                "rel_path": "src/middlewares/error_handler.py",
                "graph_role": "code",
                "priority": "high",
            },
            "score": 0.87,
        },
        {
            "content": "class ErrorMiddleware:\n    pass",
            "metadata": {
                "project": "my_bot",
                "rel_path": "src/main.py",
                "graph_role": "entrypoint",
                "priority": "critical",
            },
            "score": 0.72,
        },
    ]
    chroma.get_project.return_value = MagicMock(count=MagicMock(return_value=118))
    chroma.delete_project.return_value = True
    chroma.search_summaries.return_value = []
    chroma.get_or_create_summaries.return_value = MagicMock()
    return chroma


@pytest.fixture
def mock_graph_store():
    """Мок GraphStore — не нужна реальная SQLite."""
    store = MagicMock()
    store.has_graph.return_value = False
    store.get_stats.return_value = {"nodes": 0, "edges": 0, "communities": 0}
    store.get_nodes.return_value = []
    store.get_edges.return_value = []
    store.get_communities.return_value = []
    return store


@pytest.fixture
def mock_settings(tmp_path):
    """Мок настроек — не нужен реальный .env."""
    settings = MagicMock()
    settings.anthropic_api_key = "sk-ant-test-key"
    settings.claude_model = "claude-sonnet-4-20250514"
    settings.embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
    settings.default_top_k = 5
    settings.chroma_db_path = tmp_path / "chroma_db"
    settings.graph_db_path = tmp_path / "graph.db"
    settings.projects_base_path = tmp_path / "projects"
    settings.rag_rules_path = Path(__file__).parent.parent / "rag-rules.yaml"
    settings.telegram_bot_token = None
    settings.admin_telegram_id = None
    settings.debug = True
    settings.backend_port = 8000
    settings.mcp_server_port = 27183
    settings.auth_enabled = False
    return settings


# ── Fixture: FastAPI тестовое приложение ──────────────────────────────────────

@pytest.fixture
def app(mock_chroma, mock_graph_store, mock_settings):
    """
    Создаёт FastAPI приложение с замоканными зависимостями.
    Все синглтоны сбрасываются после каждого теста.
    """
    from unittest.mock import patch
    import sys

    # Патчим get_settings и все зависимости ДО импорта app
    with (
        patch("config.get_settings", return_value=mock_settings),
        patch("dependencies.get_chroma", return_value=mock_chroma),
        patch("dependencies.get_graph_store", return_value=mock_graph_store),
    ):
        # Принудительно перезагружаем модули чтобы патчи применились
        for mod_name in list(sys.modules.keys()):
            if "rag" in mod_name or mod_name in (
                "main", "config", "dependencies",
                "routers.search", "routers.projects", "routers.graph",
            ):
                sys.modules.pop(mod_name, None)

        from main import app as fastapi_app
        yield fastapi_app


@pytest.fixture
def client(app):
    """Синхронный тест-клиент (для простых эндпоинтов)."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client(app):
    """Асинхронный тест-клиент (для SSE и streaming endpoints)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def clear_dependency_caches():
    """Сбрасываем синглтоны перед каждым тестом — нет утечки состояния."""
    try:
        from dependencies import clear_all_caches
        clear_all_caches()
    except Exception:
        pass  # Если модуль ещё не импортирован — ничего страшного
    yield
    try:
        from dependencies import clear_all_caches
        clear_all_caches()
    except Exception:
        pass
