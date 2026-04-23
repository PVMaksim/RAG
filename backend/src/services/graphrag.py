"""
graphrag.py — GraphRAG pipeline.
Шаги: entity extraction → Knowledge Graph → community detection → summaries.
"""
import asyncio
import hashlib
import json
import re
import logging
from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic
from sentence_transformers import SentenceTransformer

from exceptions import LLMError, LLMResponseParseError
from logging_config import timed
from retry import with_anthropic_retry
from storage.chroma_store import ChromaStore
from storage.graph_store import GraphStore

log = logging.getLogger(__name__)

# ─── Промпты ──────────────────────────────────────────────────────────────────

ENTITY_PROMPT = """\
Ты анализируешь исходный код IT-проекта. Твоя задача — извлечь сущности и связи.

Файл: {file_path}
Проект: {project_name}

Код:
{content}

Верни ТОЛЬКО валидный JSON (без markdown, без пояснений):
{{
  "entities": [
    {{"id": "уникальный_id", "name": "имя", "type": "function|class|module|config|entrypoint", "description": "краткое описание на английском"}}
  ],
  "relations": [
    {{"from_id": "id_источника", "to_id": "id_цели", "type": "uses|imports|registers|implements|calls|depends_on|configures", "description": "краткое описание"}}
  ]
}}

Правила:
- id формат: "{project_name}/{file_path}::{name}" (нижний регистр, без пробелов)
- Извлекай только значимые сущности (не локальные переменные)
- Если файл пустой или нечитаемый — верни {{"entities": [], "relations": []}}
"""

COMMUNITY_SUMMARY_PROMPT = """\
Ты технический архитектор. Проанализируй этот кластер взаимосвязанных файлов IT-проекта.

Проект: {project_name}
Файлы в кластере:
{nodes_info}

Напиши техническое резюме кластера (3-5 предложений на русском):
1. Что эти файлы делают вместе?
2. Какую архитектурную роль выполняет этот кластер?
3. Ключевые паттерны и технологии?

Также придумай короткое название кластера (3-5 слов).

Верни ТОЛЬКО JSON:
{{"title": "Название кластера", "summary": "Техническое резюме..."}}
"""





class GraphProgress:
    """Событие прогресса для SSE стриминга."""
    def __init__(self, type: str, **kwargs):
        self.type = type
        self.__dict__.update(kwargs)

    def dict(self) -> dict:
        return self.__dict__



def _parse_llm_json(text: str, context: str = "") -> dict:
    """
    Безопасно парсит JSON из ответа LLM.
    Обрабатывает markdown-блоки, trailing text, BOM.
    """
    # Убираем BOM и пробелы
    text = text.strip().lstrip("\ufeff")

    # Убираем markdown-блоки ```json ... ```
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.lstrip("json").strip()
            if candidate.startswith("{") or candidate.startswith("["):
                text = candidate
                break

    # Если в тексте есть JSON-объект — извлекаем его
    if not text.startswith(("{", "[")):
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if match:
            text = match.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMResponseParseError(raw_response=text, parse_error=str(e)) from e

class GraphRAGEngine:
    """
    Строит Knowledge Graph из уже проиндексированных проектов.
    
    Pipeline:
    1. Берём проиндексированные файлы из ChromaDB
    2. Для каждого файла — entity extraction через Claude
    3. Сохраняем nodes + edges в SQLite
    4. Community detection через networkx (Louvain)
    5. Генерируем summary для каждого кластера через Claude
    6. Индексируем summaries в ChromaDB для GlobalRAG поиска
    """

    def __init__(
        self,
        chroma_store: ChromaStore,
        graph_store: GraphStore,
        embedding_model: str,
        anthropic_api_key: str,
        claude_model: str,
    ) -> None:
        self._chroma = chroma_store
        self._graph = graph_store
        self._embedding_model_name = embedding_model
        self._claude_model = claude_model
        self._anthropic = AsyncAnthropic(api_key=anthropic_api_key)
        # Semaphore ограничивает параллельные вызовы Anthropic API
        # 3 = безопасный предел для tier-1 аккаунта
        self._api_semaphore = asyncio.Semaphore(3)

    @with_anthropic_retry()
    async def _call_anthropic(self, prompt: str, max_tokens: int = 1000):
        """Единая точка вызова Anthropic API с retry-логикой и rate limiting."""
        async with self._api_semaphore:
            return await self._anthropic.messages.create(
                model=self._claude_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

    async def _embed(self, text: str) -> list[float]:
        model = self._get_model()
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.encode(text).tolist()
        )

    # ── Оценка стоимости ──────────────────────────────────────────────────

    def estimate_cost(self, project_name: str) -> dict:
        """
        Оценивает количество токенов и стоимость построения графа.
        Используется для отображения в UI перед запуском.
        """
        collection = self._chroma.get_project(project_name)
        if not collection:
            return {"error": "Проект не найден в индексе"}

        file_count = collection.count()
        # Приблизительно: 800 токенов промпт + 400 токенов ответ на файл
        estimated_tokens = file_count * 1200
        # claude-sonnet-4-20250514: ~$3 per 1M input, $15 per 1M output
        estimated_cost_usd = (file_count * 800 / 1_000_000 * 3.0) + (
            file_count * 400 / 1_000_000 * 15.0
        )

        return {
            "file_count": file_count,
            "estimated_tokens": estimated_tokens,
            "estimated_cost_usd": round(estimated_cost_usd, 4),
            "estimated_cost_display": f"~${estimated_cost_usd:.3f}",
        }

    # ── Основной pipeline ─────────────────────────────────────────────────

    async def build_graph(
        self, project_name: str
    ) -> AsyncGenerator[dict, None]:
        """
        Асинхронный генератор событий прогресса для SSE стриминга.
        Полный GraphRAG pipeline для одного проекта.
        """
        collection = self._chroma.get_project(project_name)
        if not collection:
            yield {"type": "error", "message": f"Проект '{project_name}' не найден"}
            return

        # Получаем все проиндексированные файлы
        all_data = collection.get(include=["documents", "metadatas"])
        files = list(zip(all_data["documents"], all_data["metadatas"]))
        total = len(files)

        if total == 0:
            yield {"type": "error", "message": "Проект не содержит проиндексированных файлов"}
            return

        yield {
            "type": "start",
            "project": project_name,
            "total_files": total,
            "phase": "entity_extraction",
        }

        # Очищаем старый граф проекта
        self._graph.delete_project_nodes(project_name)

        # Шаг 1: Entity extraction — батчами по BATCH_SIZE файлов параллельно
        BATCH_SIZE = 5  # 5 файлов × semaphore(3) = безопасно для rate limits
        all_nodes: list[dict] = []
        all_edges: list[dict] = []
        errors = 0
        processed = 0

        # Разделяем на код (нужен LLM) и остальные (просто module-нода)
        code_files = []
        for content, meta in files:
            role = meta.get("graph_role", "code")
            fp = meta.get("rel_path", "unknown")
            if role not in ("code", "entrypoint"):
                all_nodes.append({
                    "id": self._make_node_id(project_name, fp, "module"),
                    "project": project_name,
                    "node_type": "module",
                    "name": fp,
                    "file_path": fp,
                    "description": f"{role} file",
                })
            else:
                code_files.append((content, meta))

        # Батчевая параллельная обработка кодовых файлов
        for batch_start in range(0, len(code_files), BATCH_SIZE):
            batch = code_files[batch_start : batch_start + BATCH_SIZE]

            async def process_file(item, _pname=project_name):
                bcontent, bmeta = item
                bpath = bmeta.get("rel_path", "unknown")
                try:
                    return await self._extract_entities(bcontent, bpath, _pname)
                except LLMResponseParseError as e:
                    log.warning(
                        "Entity extraction: невалидный JSON от LLM",
                        extra={"file": bpath, "error": str(e)},
                    )
                    return [], []
                except Exception:
                    log.error(
                        "Entity extraction неожиданная ошибка",
                        extra={"file": bpath},
                        exc_info=True,
                    )
                    return [], []

            # gather запускает BATCH_SIZE задач параллельно
            # semaphore внутри _call_anthropic ограничивает до 3 одновременных API вызовов
            results = await asyncio.gather(*[process_file(item) for item in batch])

            for (nodes, edges), (_, bmeta) in zip(results, batch):
                if nodes or edges:
                    all_nodes.extend(nodes)
                    all_edges.extend(edges)
                else:
                    errors += 1

            processed += len(batch)
            last_file = batch[-1][1].get("rel_path", "")
            yield {
                "type": "progress",
                "project": project_name,
                "phase": "entity_extraction",
                "processed": processed,
                "total": len(code_files),
                "current_file": last_file,
                "progress": round(processed / max(len(code_files), 1), 2),
            }
            await asyncio.sleep(0)

        # Сохраняем граф
        if all_nodes:
            self._graph.upsert_nodes(all_nodes)
        if all_edges:
            # Фильтруем рёбра: обе вершины должны существовать
            valid_ids = {n["id"] for n in all_nodes}
            valid_edges = [
                e for e in all_edges
                if e["source_id"] in valid_ids and e["target_id"] in valid_ids
            ]
            self._graph.upsert_edges(valid_edges)

        yield {
            "type": "progress",
            "project": project_name,
            "phase": "community_detection",
            "nodes_count": len(all_nodes),
            "edges_count": len(all_edges),
        }

        # Шаг 2: Community detection
        communities_map = self._detect_communities(project_name)
        self._graph.update_node_communities(communities_map)

        yield {
            "type": "progress",
            "project": project_name,
            "phase": "community_summaries",
            "communities_count": len(set(communities_map.values())),
        }

        # Шаг 3: Community summaries
        communities = await self._build_community_summaries(
            project_name, communities_map, all_nodes
        )
        self._graph.save_communities(communities)

        # Шаг 4: Индексируем summaries в ChromaDB для GlobalRAG
        await self._index_summaries_to_chroma(communities)

        yield {
            "type": "done",
            "project": project_name,
            "nodes": len(all_nodes),
            "edges": len(all_edges),
            "communities": len(communities),
            "errors": errors,
        }

    # ── Entity extraction ─────────────────────────────────────────────────

    async def _extract_entities(
        self, content: str, file_path: str, project_name: str
    ) -> tuple[list[dict], list[dict]]:
        """Извлечь сущности и связи из одного файла через Claude."""
        # Ограничиваем размер (экономим токены)
        content_trimmed = content[:3000]

        prompt = ENTITY_PROMPT.format(
            file_path=file_path,
            project_name=project_name,
            content=content_trimmed,
        )

        response = await self._call_anthropic(prompt, max_tokens=1000)

        text = response.content[0].text.strip()
        data = _parse_llm_json(text, file_path)
        entities = data.get("entities", [])
        relations = data.get("relations", [])

        # Нормализуем в формат GraphStore
        nodes = [
            {
                "id": self._make_node_id(project_name, e.get("id", ""), e.get("name", "")),
                "project": project_name,
                "node_type": e.get("type", "function"),
                "name": e.get("name", "unknown"),
                "file_path": file_path,
                "description": e.get("description", ""),
            }
            for e in entities
        ]

        edges = [
            {
                "id": hashlib.md5(
                    f"{r.get('from_id')}→{r.get('to_id')}".encode()
                ).hexdigest(),
                "source_id": self._make_node_id(project_name, r.get("from_id", ""), ""),
                "target_id": self._make_node_id(project_name, r.get("to_id", ""), ""),
                "relation": r.get("type", "uses"),
                "weight": 1.0,
                "description": r.get("description", ""),
            }
            for r in relations
        ]

        return nodes, edges

    # ── Community detection ───────────────────────────────────────────────

    def _detect_communities(self, project_name: str) -> dict[str, int]:
        """
        Обнаружение сообществ через networkx Louvain.
        Возвращает mapping: node_id → community_id.
        """
        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            log.warning("networkx не установлен, использую простую кластеризацию")
            nodes = self._graph.get_nodes(project_name)
            return {n["id"]: i % 5 for i, n in enumerate(nodes)}

        nodes = self._graph.get_nodes(project_name)
        edges = self._graph.get_edges(project_name)

        if not nodes:
            return {}

        G = nx.Graph()
        G.add_nodes_from([n["id"] for n in nodes])
        G.add_edges_from([(e["source_id"], e["target_id"]) for e in edges])

        if G.number_of_edges() == 0:
            # Нет рёбер — каждый файл в своём кластере (группируем по папке)
            result = {}
            folder_ids: dict[str, int] = {}
            for node in nodes:
                folder = str(node.get("file_path", "")).split("/")[0]
                if folder not in folder_ids:
                    folder_ids[folder] = len(folder_ids)
                result[node["id"]] = folder_ids[folder]
            return result

        try:
            communities = louvain_communities(G, seed=42)
            result = {}
            for community_id, community_nodes in enumerate(communities):
                for node_id in community_nodes:
                    result[node_id] = community_id
            return result
        except Exception as e:
            log.warning(f"Louvain не сработал: {e}, использую connected components")
            result = {}
            for component_id, component in enumerate(nx.connected_components(G)):
                for node_id in component:
                    result[node_id] = component_id
            return result

    # ── Community summaries ───────────────────────────────────────────────

    async def _build_community_summaries(
        self,
        project_name: str,
        communities_map: dict[str, int],
        all_nodes: list[dict],
    ) -> list[dict]:
        """Генерирует LLM-резюме для каждого кластера."""
        if not communities_map:
            return []

        # Группируем узлы по community
        community_nodes: dict[int, list[dict]] = {}
        node_by_id = {n["id"]: n for n in all_nodes}

        for node_id, community_id in communities_map.items():
            if community_id not in community_nodes:
                community_nodes[community_id] = []
            node = node_by_id.get(node_id)
            if node:
                community_nodes[community_id].append(node)

        summaries = []
        for community_id, nodes in community_nodes.items():
            if len(nodes) < 2:
                # Одиночный узел — простое резюме
                node = nodes[0]
                summaries.append({
                    "project": project_name,
                    "level": 0,
                    "title": node.get("name", "Unknown"),
                    "summary": node.get("description", "Single file component"),
                    "node_ids": [n["id"] for n in nodes],
                })
                continue

            nodes_info = "\n".join(
                f"- {n['name']} ({n['node_type']}): {n.get('description', '')}"
                for n in nodes[:20]  # Ограничиваем контекст
            )

            try:
                prompt = COMMUNITY_SUMMARY_PROMPT.format(
                    project_name=project_name,
                    nodes_info=nodes_info,
                )
                response = await self._anthropic.messages.create(
                    model=self._claude_model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                data = _parse_llm_json(text, f"community_{community_id}")

                summaries.append({
                    "project": project_name,
                    "level": 0,
                    "title": data.get("title", f"Кластер {community_id}"),
                    "summary": data.get("summary", ""),
                    "node_ids": [n["id"] for n in nodes],
                })
            except (LLMResponseParseError, LLMError) as e:
                log.warning(
                    "Ошибка генерации резюме кластера",
                    extra={"community_id": community_id, "error": str(e)},
                )
            except Exception as e:
                log.error(
                    "Неожиданная ошибка при генерации резюме",
                    extra={"community_id": community_id},
                    exc_info=True,
                )
                summaries.append({
                    "project": project_name,
                    "level": 0,
                    "title": f"Кластер {community_id}",
                    "summary": nodes_info[:500],
                    "node_ids": [n["id"] for n in nodes],
                })

            await asyncio.sleep(0)

        return summaries

    # ── Индексация summaries в ChromaDB ───────────────────────────────────

    async def _index_summaries_to_chroma(self, communities: list[dict]) -> None:
        """Индексирует community summaries в ChromaDB для GlobalRAG поиска."""
        if not communities:
            return

        col = self._chroma.get_or_create_summaries()
        model = self._get_model()

        ids, docs, embeds, metas = [], [], [], []
        for comm in communities:
            summary_text = f"{comm['title']}\n\n{comm['summary']}"
            embedding = await asyncio.get_event_loop().run_in_executor(
                None, lambda t=summary_text: model.encode(t).tolist()
            )
            comm_id = hashlib.md5(
                f"{comm['project']}/{comm['title']}".encode()
            ).hexdigest()
            ids.append(comm_id)
            docs.append(summary_text)
            embeds.append(embedding)
            metas.append({
                "project": comm["project"],
                "title": comm["title"],
                "level": comm.get("level", 0),
                "node_count": len(comm.get("node_ids", [])),
            })

        if ids:
            col.upsert(ids=ids, documents=docs, embeddings=embeds, metadatas=metas)
            log.info(f"Проиндексировано {len(ids)} community summaries")

    # ── Утилиты ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_node_id(project: str, path_or_id: str, name: str) -> str:
        key = f"{project}/{path_or_id}/{name}".lower().replace(" ", "_")
        return hashlib.md5(key.encode()).hexdigest()
