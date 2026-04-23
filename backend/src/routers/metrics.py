"""
metrics.py — Prometheus метрики для мониторинга в production.

Эндпоинт GET /metrics совместим с Prometheus scrape_config.
Не требует аутентификации (стандарт — закрывается на уровне nginx
или firewall, не в приложении).

Метрики:
  rag_requests_total{endpoint, method, status}    — количество запросов
  rag_request_duration_seconds{endpoint}          — время ответа (histogram)
  rag_search_chunks_returned{project}             — кол-во чанков в результате
  rag_indexed_projects_total                      — кол-во проиндексированных проектов
  rag_indexed_files_total                         — суммарно файлов в индексе
  rag_embedding_cache_hits_total                  — хиты embedding кэша
  rag_embedding_cache_misses_total                — миссы embedding кэша
  rag_graph_nodes_total{project}                  — нод в Knowledge Graph
"""
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Response

log = logging.getLogger(__name__)
router = APIRouter(prefix="/metrics", tags=["metrics"])


# ── In-memory счётчики ────────────────────────────────────────────────────────

class MetricsRegistry:
    """
    Простой in-memory реестр метрик.
    Для production заменить на prometheus_client библиотеку.
    """

    def __init__(self):
        self.request_counts: dict[str, int]    = defaultdict(int)
        self.request_durations: dict[str, list] = defaultdict(list)
        self.search_chunks: list[int]           = []
        self.start_time: float                  = time.time()

    def record_request(self, endpoint: str, method: str, status: int, duration: float):
        key = f"{method}:{endpoint}:{status}"
        self.request_counts[key] += 1
        self.request_durations[endpoint].append(duration)
        # Храним только последние 1000 значений
        if len(self.request_durations[endpoint]) > 1000:
            self.request_durations[endpoint] = self.request_durations[endpoint][-1000:]

    def record_search(self, chunks_count: int):
        self.search_chunks.append(chunks_count)
        if len(self.search_chunks) > 1000:
            self.search_chunks = self.search_chunks[-1000:]


# Singleton реестра
_registry = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _registry


# ── Форматирование в Prometheus text format ───────────────────────────────────

def _prometheus_format(metrics: list[tuple[str, str, dict, float]]) -> str:
    """
    Форматирует метрики в Prometheus text exposition format.
    Каждый элемент: (name, help, labels_dict, value)
    """
    lines = []
    for name, help_text, labels, value in metrics:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


@router.get("/", include_in_schema=False)
async def metrics(
    registry: MetricsRegistry = Depends(get_registry),
) -> Response:
    """
    Prometheus metrics endpoint.

    Scrape config:
      - job_name: 'rag-dev-assistant'
        static_configs:
          - targets: ['backend:8000']
        metrics_path: '/api/metrics'
    """
    from dependencies import get_chroma, get_graph_store
    from embedding_cache import cache_stats

    metric_lines = []

    # ── Uptime ────────────────────────────────────────────────────────────────
    uptime = time.time() - registry.start_time
    metric_lines.append(("rag_uptime_seconds", "Application uptime in seconds", {}, round(uptime)))

    # ── Requests ──────────────────────────────────────────────────────────────
    for key, count in registry.request_counts.items():
        method, endpoint, status = key.split(":", 2)
        metric_lines.append((
            "rag_requests_total",
            "Total number of requests",
            {"endpoint": endpoint, "method": method, "status": status},
            count,
        ))

    # ── Latency (P50, P95) ────────────────────────────────────────────────────
    for endpoint, durations in registry.request_durations.items():
        if durations:
            sorted_d = sorted(durations)
            n = len(sorted_d)
            p50 = sorted_d[int(n * 0.50)]
            p95 = sorted_d[int(n * 0.95)]
            metric_lines.append((
                "rag_request_duration_p50_seconds",
                "Request duration P50",
                {"endpoint": endpoint},
                round(p50, 4),
            ))
            metric_lines.append((
                "rag_request_duration_p95_seconds",
                "Request duration P95",
                {"endpoint": endpoint},
                round(p95, 4),
            ))

    # ── Search chunks ─────────────────────────────────────────────────────────
    if registry.search_chunks:
        avg_chunks = sum(registry.search_chunks) / len(registry.search_chunks)
        metric_lines.append((
            "rag_search_avg_chunks",
            "Average chunks returned per search",
            {},
            round(avg_chunks, 2),
        ))

    # ── ChromaDB проекты ──────────────────────────────────────────────────────
    try:
        chroma = get_chroma()
        projects = chroma.list_projects()
        metric_lines.append((
            "rag_indexed_projects_total",
            "Total number of indexed projects",
            {},
            len(projects),
        ))
        total_files = sum(p["file_count"] for p in projects)
        metric_lines.append((
            "rag_indexed_files_total",
            "Total number of indexed files across all projects",
            {},
            total_files,
        ))
        for project in projects:
            metric_lines.append((
                "rag_project_files",
                "Number of indexed files per project",
                {"project": project["name"]},
                project["file_count"],
            ))
    except Exception as e:
        log.debug(f"Metrics: ChromaDB недоступен: {e}")

    # ── Knowledge Graph ───────────────────────────────────────────────────────
    try:
        graph_store = get_graph_store()
        stats = graph_store.get_stats()
        metric_lines.append(("rag_graph_nodes_total",       "Total graph nodes",       {}, stats.get("nodes", 0)))
        metric_lines.append(("rag_graph_edges_total",       "Total graph edges",       {}, stats.get("edges", 0)))
        metric_lines.append(("rag_graph_communities_total", "Total graph communities", {}, stats.get("communities", 0)))
    except Exception as e:
        log.debug(f"Metrics: GraphStore недоступен: {e}")

    # ── Embedding cache ───────────────────────────────────────────────────────
    try:
        cs = cache_stats()
        metric_lines.append(("rag_embedding_cache_hits_total",   "Embedding cache hits",    {}, cs["hits"]))
        metric_lines.append(("rag_embedding_cache_misses_total", "Embedding cache misses",  {}, cs["misses"]))
        metric_lines.append(("rag_embedding_cache_size",         "Embedding cache current size", {}, cs["currsize"]))
        metric_lines.append(("rag_embedding_cache_hit_rate",     "Embedding cache hit rate %", {}, cs["hit_rate"]))
    except Exception as e:
        log.debug(f"Metrics: cache_stats недоступен: {e}")

    content = _prometheus_format(metric_lines)
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
