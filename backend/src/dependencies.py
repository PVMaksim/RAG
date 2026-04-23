"""
dependencies.py — FastAPI Depends: инъекция сервисов.

Синглтоны через lru_cache — создаются один раз при первом обращении.
clear_all_caches() позволяет сбросить их в тестах или при смене конфига.
"""
import logging
from functools import lru_cache

from config import get_settings
from services.graphrag import GraphRAGEngine
from services.query_engine import QueryEngine
from services.scanner import ProjectScanner
from storage.chroma_store import ChromaStore
from storage.graph_store import GraphStore

log = logging.getLogger(__name__)


@lru_cache
def get_chroma() -> ChromaStore:
    s = get_settings()
    return ChromaStore(s.chroma_db_path)


@lru_cache
def get_graph_store() -> GraphStore:
    s = get_settings()
    return GraphStore(s.graph_db_path)


@lru_cache
def get_scanner() -> ProjectScanner:
    s = get_settings()
    return ProjectScanner(
        rules_path=s.rag_rules_path,
        chroma_store=get_chroma(),
        embedding_model=s.embedding_model,
    )


@lru_cache
def get_query_engine() -> QueryEngine:
    s = get_settings()
    return QueryEngine(
        chroma_store=get_chroma(),
        embedding_model=s.embedding_model,
        anthropic_api_key=s.anthropic_api_key,
        claude_model=s.claude_model,
        default_top_k=s.default_top_k,
    )


@lru_cache
def get_graphrag() -> GraphRAGEngine:
    s = get_settings()
    return GraphRAGEngine(
        chroma_store=get_chroma(),
        graph_store=get_graph_store(),
        embedding_model=s.embedding_model,
        anthropic_api_key=s.anthropic_api_key,
        claude_model=s.claude_model,
    )


def clear_all_caches() -> None:
    """
    Сбрасывает все синглтоны.

    Используется в тестах (conftest autouse fixture) и при смене настроек.
    После вызова следующий Depends вызов создаст новые экземпляры.
    """
    get_chroma.cache_clear()
    get_graph_store.cache_clear()
    get_scanner.cache_clear()
    get_query_engine.cache_clear()
    get_graphrag.cache_clear()
    get_settings.cache_clear()
    log.debug("Все dependency кэши сброшены")
