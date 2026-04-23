"""
graph_store.py — SQLite хранилище Knowledge Graph.
Таблицы: nodes, edges, communities.
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL,
    node_type   TEXT NOT NULL,
    name        TEXT NOT NULL,
    file_path   TEXT,
    description TEXT,
    community_id INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_id   TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,
    weight      REAL DEFAULT 1.0,
    description TEXT
);

CREATE TABLE IF NOT EXISTS communities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT,
    level       INTEGER DEFAULT 0,
    title       TEXT,
    summary     TEXT,
    node_ids    TEXT,
    embedding   BLOB,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nodes_project ON graph_nodes(project);
CREATE INDEX IF NOT EXISTS idx_edges_source  ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target  ON graph_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_communities_project ON communities(project);
"""


class GraphStore:
    """Управляет Knowledge Graph в SQLite."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._init_schema()
        log.info(f"GraphStore инициализирован: {db_path}")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL: не блокирует читателей при записи (важно при параллельном scan+query)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        # Ждём до 30с если БД заблокирована другим процессом
        conn.execute("PRAGMA busy_timeout = 30000")
        # Синхронизация: NORMAL = баланс скорость/надёжность
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
            conn.commit()
        except sqlite3.OperationalError as e:
            conn.rollback()
            from exceptions import StorageError
            raise StorageError(f"SQLite ошибка: {e}") from e
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ── Nodes ─────────────────────────────────────────────────────────────

    def upsert_nodes(self, nodes: list[dict]) -> None:
        """Добавить или обновить узлы графа."""
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO graph_nodes (id, project, node_type, name, file_path, description)
                   VALUES (:id, :project, :node_type, :name, :file_path, :description)
                   ON CONFLICT(id) DO UPDATE SET
                     description = excluded.description,
                     file_path   = excluded.file_path""",
                nodes,
            )

    def get_nodes(self, project: str | None = None) -> list[dict]:
        """Получить узлы графа (по проекту или все)."""
        with self._conn() as conn:
            if project:
                rows = conn.execute(
                    "SELECT * FROM graph_nodes WHERE project = ?", (project,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM graph_nodes").fetchall()
        return [dict(r) for r in rows]

    def delete_project_nodes(self, project: str) -> None:
        """Удалить все узлы и рёбра проекта."""
        with self._conn() as conn:
            node_ids = conn.execute(
                "SELECT id FROM graph_nodes WHERE project = ?", (project,)
            ).fetchall()
            ids = [r["id"] for r in node_ids]
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"DELETE FROM graph_edges WHERE source_id IN ({placeholders})",
                    ids,
                )
            conn.execute("DELETE FROM graph_nodes WHERE project = ?", (project,))
            conn.execute("DELETE FROM communities WHERE project = ?", (project,))

    # ── Edges ─────────────────────────────────────────────────────────────

    def upsert_edges(self, edges: list[dict]) -> None:
        """Добавить или обновить рёбра графа."""
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO graph_edges (id, source_id, target_id, relation, weight, description)
                   VALUES (:id, :source_id, :target_id, :relation, :weight, :description)
                   ON CONFLICT(id) DO UPDATE SET
                     weight      = excluded.weight,
                     description = excluded.description""",
                edges,
            )

    def get_edges(self, project: str | None = None) -> list[dict]:
        """Получить рёбра графа."""
        with self._conn() as conn:
            if project:
                rows = conn.execute(
                    """SELECT e.* FROM graph_edges e
                       JOIN graph_nodes n ON e.source_id = n.id
                       WHERE n.project = ?""",
                    (project,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM graph_edges").fetchall()
        return [dict(r) for r in rows]

    # ── Communities ───────────────────────────────────────────────────────

    def save_communities(self, communities: list[dict]) -> None:
        """Сохранить community summaries (заменяет старые для проекта)."""
        if not communities:
            return
        project = communities[0].get("project")
        with self._conn() as conn:
            if project:
                conn.execute("DELETE FROM communities WHERE project = ?", (project,))
            conn.executemany(
                """INSERT INTO communities (project, level, title, summary, node_ids)
                   VALUES (:project, :level, :title, :summary, :node_ids)""",
                [
                    {**c, "node_ids": json.dumps(c.get("node_ids", []))}
                    for c in communities
                ],
            )

    def get_communities(self, project: str | None = None) -> list[dict]:
        """Получить community summaries."""
        with self._conn() as conn:
            if project:
                rows = conn.execute(
                    "SELECT * FROM communities WHERE project = ?", (project,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM communities").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["node_ids"] = json.loads(d.get("node_ids") or "[]")
            d.pop("embedding", None)
            result.append(d)
        return result

    def update_node_communities(self, assignments: dict[str, int]) -> None:
        """Обновить community_id для узлов после кластеризации."""
        with self._conn() as conn:
            conn.executemany(
                "UPDATE graph_nodes SET community_id = ? WHERE id = ?",
                [(community_id, node_id) for node_id, community_id in assignments.items()],
            )

    # ── Stats ─────────────────────────────────────────────────────────────

    def has_graph(self, project: str) -> bool:
        """Проверить есть ли граф для проекта."""
        with self._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE project = ?", (project,)
            ).fetchone()[0]
        return count > 0

    def get_stats(self, project: str | None = None) -> dict:
        """Статистика графа."""
        with self._conn() as conn:
            if project:
                nodes = conn.execute(
                    "SELECT COUNT(*) FROM graph_nodes WHERE project = ?", (project,)
                ).fetchone()[0]
                edges = conn.execute(
                    """SELECT COUNT(*) FROM graph_edges e
                       JOIN graph_nodes n ON e.source_id = n.id
                       WHERE n.project = ?""",
                    (project,),
                ).fetchone()[0]
                communities = conn.execute(
                    "SELECT COUNT(*) FROM communities WHERE project = ?", (project,)
                ).fetchone()[0]
            else:
                nodes = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
                edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
                communities = conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
        return {"nodes": nodes, "edges": edges, "communities": communities}
