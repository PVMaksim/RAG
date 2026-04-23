"""
chroma_store.py — обёртка над ChromaDB клиентом.
Singleton: одно подключение на весь процесс.
"""
import hashlib
import logging
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb import Collection

log = logging.getLogger(__name__)


class ChromaStore:
    """Управляет подключением к ChromaDB и коллекциями проектов."""

    def __init__(self, db_path: Path) -> None:
        db_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(db_path))
        log.info(f"ChromaDB подключена: {db_path}")

    # ── Коллекции проектов ────────────────────────────────────────────────

    def get_or_create_project(self, project_name: str, project_type: str) -> Collection:
        """Получить или создать коллекцию для проекта."""
        return self._client.get_or_create_collection(
            name=f"project_{project_name}",
            metadata={"project_type": project_type},
        )

    def get_project(self, project_name: str) -> Collection | None:
        """Получить коллекцию проекта или None если не существует."""
        try:
            return self._client.get_collection(f"project_{project_name}")
        except Exception as e:
            # ChromaDB кидает ValueError если коллекция не найдена
            if "does not exist" in str(e).lower() or isinstance(e, ValueError):
                return None
            log.error("ChromaDB get_collection error", extra={"project": project_name}, exc_info=True)
            return None

    def delete_project(self, project_name: str) -> bool:
        """Удалить коллекцию проекта. Возвращает True если удалено."""
        try:
            self._client.delete_collection(f"project_{project_name}")
            log.info("Коллекция удалена", extra={"project": project_name})
            return True
        except Exception as e:
            if "does not exist" in str(e).lower() or isinstance(e, ValueError):
                return False  # Не было — ничего страшного
            log.error("ChromaDB delete_collection error", extra={"project": project_name}, exc_info=True)
            return False

    def list_projects(self) -> list[dict]:
        """Список всех проиндексированных проектов с метаданными."""
        collections = self._client.list_collections()
        result = []
        for col in collections:
            if not col.name.startswith("project_"):
                continue
            project_name = col.name.removeprefix("project_")
            result.append({
                "name": project_name,
                "collection_name": col.name,
                "file_count": col.count(),
                "project_type": col.metadata.get("project_type", "unknown"),
            })
        return result

    # ── Community summaries (GraphRAG) ────────────────────────────────────

    def get_or_create_summaries(self) -> Collection:
        """Коллекция для community summaries всех проектов."""
        return self._client.get_or_create_collection(
            name="graph_summaries",
            metadata={"type": "community_summaries"},
        )

    # ── Поиск ─────────────────────────────────────────────────────────────

    def search(
        self,
        embedding: list[float],
        project_name: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Семантический поиск по всем проектам или конкретному.
        Возвращает отсортированные по релевантности чанки.
        """
        collections = self._client.list_collections()

        if project_name:
            target = f"project_{project_name}"
            collections = [c for c in collections if c.name == target]

        # Фильтруем только project_ коллекции (не summaries и т.п.)
        collections = [c for c in collections if c.name.startswith("project_")]

        if not collections:
            return []

        results: list[dict] = []
        for col in collections:
            count = col.count()
            if count == 0:
                continue
            res = col.query(
                query_embeddings=[embedding],
                n_results=min(top_k, count),
                include=["documents", "metadatas", "distances"],
            )
            for doc, meta, dist in zip(
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
            ):
                results.append({
                    "content": doc,
                    "metadata": meta,
                    "score": round(1 - dist, 3),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_summaries(
        self, embedding: list[float], top_k: int = 10
    ) -> list[dict]:
        """Поиск по community summaries для GlobalRAG запросов."""
        col = self.get_or_create_summaries()
        count = col.count()
        if count == 0:
            return []
        res = col.query(
            query_embeddings=[embedding],
            n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
        )
        results = []
        for doc, meta, dist in zip(
            res["documents"][0],
            res["metadatas"][0],
            res["distances"][0],
        ):
            results.append({
                "summary": doc,
                "metadata": meta,
                "score": round(1 - dist, 3),
            })
        return results

    # ── Утилиты ───────────────────────────────────────────────────────────

    @staticmethod
    def make_doc_id(project_name: str, rel_path: str) -> str:
        """Стабильный ID документа на основе проект+путь."""
        return hashlib.md5(f"{project_name}/{rel_path}".encode()).hexdigest()

    def get_existing_hashes(self, collection: Collection) -> dict[str, str]:
        """Хэши уже проиндексированных файлов для инкрементального обновления."""
        existing = collection.get(include=["metadatas"])
        return {
            m["rel_path"]: m.get("file_hash", "")
            for m in (existing["metadatas"] or [])
        }


@lru_cache
def get_chroma_store(db_path_str: str) -> ChromaStore:
    """Singleton ChromaStore."""
    return ChromaStore(Path(db_path_str))
