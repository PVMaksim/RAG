"""
test_projects.py — тесты для роутера управления проектами.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestListProjects:

    def test_list_returns_projects(self, client, mock_chroma):
        """GET /projects/ возвращает список проектов."""
        resp = client.get("/api/projects/")
        assert resp.status_code == 200
        data = resp.json()
        assert "projects" in data
        assert len(data["projects"]) == 2
        names = [p["name"] for p in data["projects"]]
        assert "my_bot" in names
        assert "fastapi_svc" in names

    def test_list_includes_graph_status(self, client, mock_chroma, mock_graph_store):
        """Каждый проект содержит has_graph флаг."""
        mock_graph_store.has_graph.return_value = True
        mock_graph_store.get_stats.return_value = {"nodes": 45, "edges": 30, "communities": 5}

        resp = client.get("/api/projects/")
        data = resp.json()
        project = data["projects"][0]
        assert "has_graph" in project
        assert "graph_stats" in project

    def test_list_empty_index(self, client, mock_chroma):
        """Пустой ChromaDB → пустой список."""
        mock_chroma.list_projects.return_value = []
        resp = client.get("/api/projects/")
        assert resp.status_code == 200
        assert resp.json()["projects"] == []


class TestDeleteProject:

    def test_delete_existing_project(self, client, mock_chroma, mock_graph_store):
        """Удаление существующего проекта → 200."""
        mock_chroma.delete_project.return_value = True
        resp = client.delete("/api/projects/my_bot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["project"] == "my_bot"
        # Graph тоже удаляется
        mock_graph_store.delete_project_nodes.assert_called_once_with("my_bot")

    def test_delete_nonexistent_project(self, client, mock_chroma):
        """Удаление несуществующего проекта → 404."""
        mock_chroma.delete_project.return_value = False
        resp = client.delete("/api/projects/ghost_project")
        assert resp.status_code == 404


class TestScanProject:

    def test_scan_returns_sse_stream(self, client, tmp_path):
        """Сканирование возвращает SSE поток."""
        # Создаём тестовый проект
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("print('hello')")
        (project_dir / "README.md").write_text("# Test Project")

        with patch("services.scanner.ProjectScanner.scan") as mock_scan:
            async def fake_scan(*args, **kwargs):
                from services.scanner import ScanProgress
                yield ScanProgress(type="start", project="test_project", files_total=2)
                yield ScanProgress(type="progress", project="test_project",
                                   files_scanned=1, files_indexed=1, files_total=2,
                                   current_file="main.py")
                yield ScanProgress(type="done", project="test_project",
                                   files_scanned=2, files_indexed=2,
                                   files_total=2, duration_sec=0.5)

            mock_scan.return_value = fake_scan()

            with patch("routers.projects.get_settings") as mock_settings:
                mock_settings.return_value.projects_base_path = tmp_path
                resp = client.post("/api/projects/test_project/scan")

            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            events = []
            for line in resp.text.split("\n"):
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

            event_types = [e["type"] for e in events]
            assert "start" in event_types
            assert "done" in event_types

    def test_scan_nonexistent_path_returns_error_event(self, client, tmp_path):
        """Несуществующий путь → SSE событие error (не 404)."""
        with patch("routers.projects.get_settings") as mock_settings:
            mock_settings.return_value.projects_base_path = tmp_path

            resp = client.post("/api/projects/ghost_project/scan")

        assert resp.status_code == 200  # SSE всегда 200
        events = [
            json.loads(line[6:])
            for line in resp.text.split("\n")
            if line.startswith("data: ")
        ]
        assert any(e["type"] == "error" for e in events)


class TestGraphEstimate:

    def test_estimate_returns_cost(self, client, mock_chroma):
        """Оценка стоимости GraphRAG возвращает токены и цену."""
        with patch("services.graphrag.GraphRAGEngine.estimate_cost") as mock_est:
            mock_est.return_value = {
                "file_count": 118,
                "estimated_tokens": 141600,
                "estimated_cost_usd": 0.003,
                "estimated_cost_display": "~$0.003",
            }
            resp = client.get("/api/projects/my_bot/graph/estimate")

        assert resp.status_code == 200
        data = resp.json()
        assert data["file_count"] == 118
        assert "estimated_cost_display" in data

    def test_estimate_nonexistent_project_returns_404(self, client, mock_chroma):
        """Оценка для несуществующего проекта → 404."""
        with patch("services.graphrag.GraphRAGEngine.estimate_cost") as mock_est:
            mock_est.return_value = {"error": "Проект не найден"}
            resp = client.get("/api/projects/ghost/graph/estimate")

        assert resp.status_code == 404
