"""
test_graphrag.py — тесты для GraphRAG pipeline.

Проверяем:
- Semaphore ограничивает параллельные вызовы
- Батчевая обработка работает правильно
- Оценка стоимости корректна
- Community detection работает без графа
- _parse_llm_json справляется с форматами LLM
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Фикстуры ──────────────────────────────────────────────────────────────────

@pytest.fixture
def graphrag_engine(mock_chroma, mock_graph_store):
    from services.graphrag import GraphRAGEngine
    return GraphRAGEngine(
        chroma_store=mock_chroma,
        graph_store=mock_graph_store,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        anthropic_api_key="sk-ant-test",
        claude_model="claude-sonnet-4-20250514",
    )


# ── Оценка стоимости ──────────────────────────────────────────────────────────

class TestEstimateCost:

    def test_estimate_for_existing_project(self, graphrag_engine, mock_chroma):
        mock_col = MagicMock()
        mock_col.count.return_value = 50
        mock_chroma.get_project.return_value = mock_col

        result = graphrag_engine.estimate_cost("my_bot")

        assert result["file_count"] == 50
        assert result["estimated_tokens"] == 50 * 1200
        assert "estimated_cost_display" in result
        assert result["estimated_cost_usd"] > 0

    def test_estimate_for_missing_project(self, graphrag_engine, mock_chroma):
        mock_chroma.get_project.return_value = None
        result = graphrag_engine.estimate_cost("ghost")
        assert "error" in result

    def test_estimate_scales_linearly(self, graphrag_engine, mock_chroma):
        """Стоимость 200 файлов = 2× стоимость 100 файлов."""
        def make_col(n):
            col = MagicMock()
            col.count.return_value = n
            return col

        mock_chroma.get_project.return_value = make_col(100)
        r100 = graphrag_engine.estimate_cost("p")["estimated_cost_usd"]

        mock_chroma.get_project.return_value = make_col(200)
        r200 = graphrag_engine.estimate_cost("p")["estimated_cost_usd"]

        assert abs(r200 / r100 - 2.0) < 0.01


# ── Semaphore ─────────────────────────────────────────────────────────────────

class TestSemaphore:

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_calls(self, graphrag_engine):
        """Максимум 3 параллельных вызова Anthropic API."""
        active_calls = []
        max_concurrent = 0

        async def fake_create(**kwargs):
            active_calls.append(1)
            nonlocal max_concurrent
            max_concurrent = max(max_concurrent, len(active_calls))
            await asyncio.sleep(0.01)
            active_calls.pop()
            return MagicMock(content=[MagicMock(text='{"entities":[],"relations":[]}')])

        with patch.object(graphrag_engine._anthropic.messages, 'create', side_effect=fake_create):
            # Запускаем 10 параллельных вызовов
            tasks = [graphrag_engine._call_anthropic("test prompt") for _ in range(10)]
            await asyncio.gather(*tasks)

        # Semaphore(3) → максимум 3 одновременно
        assert max_concurrent <= 3


# ── Build Graph pipeline ──────────────────────────────────────────────────────

class TestBuildGraph:

    def _make_collection(self, files: list[tuple[str, dict]]):
        """Создаёт мок коллекции с документами."""
        col = MagicMock()
        docs = [f[0] for f in files]
        metas = [f[1] for f in files]
        col.get.return_value = {"documents": docs, "metadatas": metas}
        col.count.return_value = len(files)
        return col

    @pytest.mark.asyncio
    async def test_build_graph_yields_start_event(self, graphrag_engine, mock_chroma, mock_graph_store):
        files = [
            ("def hello(): pass", {"rel_path": "main.py", "graph_role": "code"}),
            ("# config", {"rel_path": "config.yaml", "graph_role": "config"}),
        ]
        mock_chroma.get_project.return_value = self._make_collection(files)
        mock_graph_store.delete_project_nodes = MagicMock()
        mock_graph_store.upsert_nodes = MagicMock()
        mock_graph_store.upsert_edges = MagicMock()

        with patch.object(graphrag_engine, '_extract_entities', new_callable=AsyncMock) as mock_ext:
            mock_ext.return_value = (
                [{"id": "x", "project": "p", "node_type": "function", "name": "hello", "file_path": "main.py", "description": ""}],
                []
            )
            with patch.object(graphrag_engine, '_detect_communities', return_value={"x": 0}):
                with patch.object(graphrag_engine, '_build_community_summaries', new_callable=AsyncMock) as mock_summ:
                    mock_summ.return_value = []
                    with patch.object(graphrag_engine, '_index_summaries_to_chroma', new_callable=AsyncMock):
                        events = []
                        async for event in graphrag_engine.build_graph("test_project"):
                            events.append(event)

        event_types = [e["type"] for e in events]
        assert "start" in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_build_graph_skips_non_code_files(self, graphrag_engine, mock_chroma, mock_graph_store):
        """Config/docs файлы добавляются как module-ноды без LLM вызова."""
        files = [
            ("ANTHROPIC_API_KEY=test", {"rel_path": ".env.example", "graph_role": "config"}),
            ("# README", {"rel_path": "README.md", "graph_role": "documentation"}),
        ]
        mock_chroma.get_project.return_value = self._make_collection(files)
        mock_graph_store.delete_project_nodes = MagicMock()
        mock_graph_store.upsert_nodes = MagicMock()
        mock_graph_store.upsert_edges = MagicMock()

        with patch.object(graphrag_engine, '_extract_entities', new_callable=AsyncMock) as mock_ext:
            with patch.object(graphrag_engine, '_detect_communities', return_value={}):
                with patch.object(graphrag_engine, '_build_community_summaries', new_callable=AsyncMock, return_value=[]):
                    with patch.object(graphrag_engine, '_index_summaries_to_chroma', new_callable=AsyncMock):
                        async for _ in graphrag_engine.build_graph("test"):
                            pass

            # LLM не должен вызываться для config/docs файлов
            mock_ext.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_graph_missing_project_yields_error(self, graphrag_engine, mock_chroma):
        mock_chroma.get_project.return_value = None
        events = []
        async for event in graphrag_engine.build_graph("ghost_project"):
            events.append(event)

        assert any(e["type"] == "error" for e in events)


# ── Community Detection ───────────────────────────────────────────────────────

class TestCommunityDetection:

    def test_detect_communities_groups_connected_nodes(self, graphrag_engine, mock_graph_store):
        # 3 связанных ноды
        mock_graph_store.get_nodes.return_value = [
            {"id": "a", "file_path": "src/a.py"},
            {"id": "b", "file_path": "src/b.py"},
            {"id": "c", "file_path": "other/c.py"},
        ]
        mock_graph_store.get_edges.return_value = [
            {"source_id": "a", "target_id": "b"},  # a и b связаны
            # c не связан
        ]

        result = graphrag_engine._detect_communities("test")

        assert isinstance(result, dict)
        assert set(result.keys()) == {"a", "b", "c"}
        # a и b должны быть в одном кластере
        assert result["a"] == result["b"]

    def test_detect_communities_fallback_without_networkx(self, graphrag_engine, mock_graph_store):
        """Без networkx группируем по папкам."""
        mock_graph_store.get_nodes.return_value = [
            {"id": "a", "file_path": "src/main.py"},
            {"id": "b", "file_path": "src/config.py"},
            {"id": "c", "file_path": "tests/test.py"},
        ]
        mock_graph_store.get_edges.return_value = []

        with patch.dict('sys.modules', {'networkx': None}):
            # Импорт networkx упадёт → используем fallback
            result = graphrag_engine._detect_communities("test")

        assert isinstance(result, dict)
        # a и b должны быть в одной группе (одна папка src/)
        assert result["a"] == result["b"]
        assert result["c"] != result["a"]
