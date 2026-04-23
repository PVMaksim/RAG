"""
graph.py — роутер Knowledge Graph.
Отдаёт данные для react-force-graph визуализации во frontend.
"""
import logging

from fastapi import APIRouter, Depends

from dependencies import get_graph_store
from exceptions import GraphNotBuiltError
from storage.graph_store import GraphStore

log = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/summaries")
async def get_summaries(
    project: str | None = None,
    graph_store: GraphStore = Depends(get_graph_store),
) -> dict:
    """Community summaries для GlobalRAG (показываются в UI)."""
    communities = graph_store.get_communities(project)
    return {
        "summaries": [
            {
                "id":          c["id"],
                "project":     c["project"],
                "title":       c["title"],
                "summary":     c["summary"],
                "node_count":  len(c["node_ids"]),
            }
            for c in communities
        ],
        "total": len(communities),
    }


@router.get("/{project_name}")
async def get_project_graph(
    project_name: str,
    graph_store: GraphStore = Depends(get_graph_store),
) -> dict:
    """
    Данные Knowledge Graph для визуализации.
    Формат совместим с react-force-graph.
    """
    nodes = graph_store.get_nodes(project_name)
    edges = graph_store.get_edges(project_name)

    if not nodes:
        raise GraphNotBuiltError(project_name)

    graph_nodes = [
        {
            "id":          n["id"],
            "name":        n["name"],
            "type":        n["node_type"],
            "file":        n.get("file_path", ""),
            "description": n.get("description", ""),
            "community":   n.get("community_id"),
            "project":     n["project"],
        }
        for n in nodes
    ]

    graph_links = [
        {
            "source":   e["source_id"],
            "target":   e["target_id"],
            "relation": e["relation"],
            "weight":   e.get("weight", 1.0),
        }
        for e in edges
    ]

    stats       = graph_store.get_stats(project_name)
    communities = graph_store.get_communities(project_name)

    log.info(
        "Graph data fetched",
        extra={"project": project_name, "nodes": len(graph_nodes), "links": len(graph_links)},
    )

    return {
        "nodes":       graph_nodes,
        "links":       graph_links,
        "stats":       stats,
        "communities": [
            {"id": c["id"], "title": c["title"], "node_count": len(c["node_ids"])}
            for c in communities
        ],
    }


@router.get("/")
async def get_all_graphs(
    graph_store: GraphStore = Depends(get_graph_store),
) -> dict:
    """Граф всех проектов (для cross-project визуализации)."""
    nodes = graph_store.get_nodes()
    edges = graph_store.get_edges()

    return {
        "nodes": [
            {
                "id":        n["id"],
                "name":      n["name"],
                "type":      n["node_type"],
                "file":      n.get("file_path", ""),
                "community": n.get("community_id"),
                "project":   n["project"],
            }
            for n in nodes
        ],
        "links": [
            {
                "source":   e["source_id"],
                "target":   e["target_id"],
                "relation": e["relation"],
            }
            for e in edges
        ],
        "stats":       graph_store.get_stats(),
        "communities": graph_store.get_communities(),
    }
