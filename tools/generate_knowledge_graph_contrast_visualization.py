"""Build an interactive clean/poisoned/LogicGuard knowledge-graph view.

This visualization is meant for project explanation rather than model training.
It reads already-generated Microsoft GraphRAG artifacts and Stage21 evidence
traces, then writes one standalone HTML page under ``outputs/visualizations``.

The page intentionally separates two levels of evidence:

1. Dataset-subset graph level: clean vs. LogicPoison GraphRAG entities and
   relationships, plus a merged difference graph.
2. Single-query path level: how the same query's retrieved evidence changes
   under clean, poisoned, guarded, and recovered contexts.

The global graph is the complete GraphRAG graph for the current debug_50
query-ready indexed subset, not the full original 2WikiMultiHopQA corpus.
"""

from __future__ import annotations

import html
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "visualizations"

CLEAN_GRAPH_DIR = (
    ROOT
    / "outputs"
    / "ms_graphrag"
    / "2wikimultihopqa"
    / "stage10_debug50_clean_query_ready"
    / "output"
)
POISONED_GRAPH_DIR = (
    ROOT
    / "outputs"
    / "ms_graphrag"
    / "2wikimultihopqa"
    / "stage10_debug50_poisoned_query_ready"
    / "output"
)

STAGE21_EVIDENCE = ROOT / "outputs" / "ms_graphrag_query" / "stage21_medium_evidence.jsonl"
STAGE21_METRICS = ROOT / "outputs" / "ms_graphrag_query" / "stage21_medium_metrics.csv"
QUERY_INTEGRITY = (
    ROOT
    / "outputs"
    / "attacks"
    / "logicpoison_official"
    / "2wikimultihopqa"
    / "query_integrity.jsonl"
)
CHANGED_DOCS = (
    ROOT
    / "outputs"
    / "attacks"
    / "logicpoison_official"
    / "2wikimultihopqa"
    / "changed_docs.jsonl"
)
CLEAN_CORPUS = ROOT / "data" / "logicpoison_official" / "clean" / "2wikimultihopqa" / "corpus.jsonl"
POISONED_CORPUS = ROOT / "data" / "logicpoison_official" / "poisoned" / "2wikimultihopqa" / "corpus.jsonl"

OUTPUT_HTML = OUTPUT_DIR / "14_知识图谱_Clean_vs_LogicPoison_vs_LogicGuard.html"
INDEX_HTML = OUTPUT_DIR / "00_索引_中文可视化说明.html"

QUERY_ID = "a457e11c0bdb11eba7f7acde48001122"
TOP_K = 10

METHODS = {
    "clean_bm25_reference": {
        "label": "Clean 干净检索",
        "short": "CLEAN",
        "state": "clean",
        "color": "#3b82f6",
        "description": "从干净参考索引中检索，作为理想对照。",
    },
    "poisoned_bm25": {
        "label": "LogicPoison 污染检索",
        "short": "POISONED",
        "state": "poisoned",
        "color": "#ef4444",
        "description": "从污染索引中检索，污染证据会进入上下文。",
    },
    "guarded_filter": {
        "label": "LogicGuard 仅过滤",
        "short": "GUARDED",
        "state": "guarded",
        "color": "#f59e0b",
        "description": "过滤高风险证据，安全性提升但关键证据可能被一并删除。",
    },
    "recovered_by_doc_id": {
        "label": "LogicGuard Recovery",
        "short": "RECOVERED",
        "state": "recovered",
        "color": "#22c55e",
        "description": "将已知污染证据替换为同 doc_id 的 clean reference 版本。",
    },
}


def main() -> None:
    """Generate the visualization and patch the local visualization index."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clean = load_graph_artifacts(CLEAN_GRAPH_DIR)
    poisoned = load_graph_artifacts(POISONED_GRAPH_DIR)
    changed_doc_ids = load_changed_doc_ids(CHANGED_DOCS)
    query_info = load_query_info(QUERY_ID)
    metrics = load_stage21_metrics(QUERY_ID, TOP_K)
    evidence = load_stage21_evidence(QUERY_ID, TOP_K)
    clean_corpus = load_corpus(CLEAN_CORPUS)
    poisoned_corpus = load_corpus(POISONED_CORPUS)

    clean_entity_titles = set(clean["entities"]["title"].astype(str))
    poisoned_entity_titles = set(poisoned["entities"]["title"].astype(str))
    clean_edge_keys = relationship_keys(clean["relationships"])
    poisoned_edge_keys = relationship_keys(poisoned["relationships"])

    graph_stats = {
        "clean_entities": len(clean_entity_titles),
        "poisoned_entities": len(poisoned_entity_titles),
        "shared_entities": len(clean_entity_titles & poisoned_entity_titles),
        "poisoned_only_entities": len(poisoned_entity_titles - clean_entity_titles),
        "clean_only_entities": len(clean_entity_titles - poisoned_entity_titles),
        "clean_edges": len(clean_edge_keys),
        "poisoned_edges": len(poisoned_edge_keys),
        "shared_edges": len(clean_edge_keys & poisoned_edge_keys),
        "poisoned_only_edges": len(poisoned_edge_keys - clean_edge_keys),
        "clean_only_edges": len(clean_edge_keys - poisoned_edge_keys),
    }

    page_data = {
        "cleanGraph": build_global_graph(
            artifacts=clean,
            state="clean",
            other_entity_titles=poisoned_entity_titles,
            changed_doc_ids=changed_doc_ids,
        ),
        "poisonedGraph": build_global_graph(
            artifacts=poisoned,
            state="poisoned",
            other_entity_titles=clean_entity_titles,
            changed_doc_ids=changed_doc_ids,
        ),
        "diffGraph": build_difference_graph(clean, poisoned, changed_doc_ids),
        "queryPath": build_query_path_graph(
            clean=clean,
            poisoned=poisoned,
            evidence=evidence,
            metrics=metrics,
            query_info=query_info,
        ),
    }

    html_text = render_html(
        graph_stats=graph_stats,
        query_info=query_info,
        metrics=metrics,
        page_data=page_data,
        evidence=evidence,
        clean_corpus=clean_corpus,
        poisoned_corpus=poisoned_corpus,
    )
    OUTPUT_HTML.write_text(html_text, encoding="utf-8")
    update_visualization_index(OUTPUT_HTML)
    print(f"生成完成：{OUTPUT_HTML}")


def load_graph_artifacts(root: Path) -> dict[str, pd.DataFrame]:
    """Read the GraphRAG parquet tables needed by this visualization."""

    required = ["entities", "relationships", "text_units", "documents", "communities"]
    artifacts: dict[str, pd.DataFrame] = {}
    for name in required:
        path = root / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Missing GraphRAG artifact: {path}")
        artifacts[name] = pd.read_parquet(path)
    return artifacts


def load_changed_doc_ids(path: Path) -> set[str]:
    """Load document ids whose clean and poisoned corpus text differs."""

    changed: set[str] = set()
    for row in read_jsonl(path):
        if bool(row.get("changed")):
            changed.add(str(row.get("doc_id")))
    return changed


def load_query_info(query_id: str) -> dict[str, Any]:
    """Load the query metadata and support ids used in the path view."""

    for row in read_jsonl(QUERY_INTEGRITY):
        if str(row.get("query_id")) == query_id:
            return row
    raise ValueError(f"Missing query_integrity row for query_id={query_id}")


def load_stage21_metrics(query_id: str, top_k: int) -> dict[str, dict[str, Any]]:
    """Load per-method Stage21 retrieval metrics for the selected query."""

    rows = pd.read_csv(STAGE21_METRICS)
    selected = rows[(rows["query_id"] == query_id) & (rows["top_k"] == top_k)]
    return {str(row["method"]): row.to_dict() for _, row in selected.iterrows()}


def load_stage21_evidence(query_id: str, top_k: int) -> dict[str, list[dict[str, Any]]]:
    """Load the retrieved evidence lists for clean/poisoned/guarded/recovered."""

    evidence = {method: [] for method in METHODS}
    for row in read_jsonl(STAGE21_EVIDENCE):
        if str(row.get("query_id")) == query_id and int(row.get("top_k", -1)) == top_k:
            method = str(row.get("method"))
            if method in evidence:
                evidence[method] = list(row.get("evidence", []))
    return evidence


def load_corpus(path: Path) -> dict[str, dict[str, Any]]:
    """Load corpus rows keyed by doc_id for clean/poisoned text comparison."""

    corpus: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        doc_id = row.get("doc_id") or row.get("id") or row.get("_id") or row.get("document_id")
        if doc_id is None:
            continue
        doc_id = str(doc_id)
        corpus[doc_id] = row
    return corpus


def build_global_graph(
    *,
    artifacts: dict[str, pd.DataFrame],
    state: str,
    other_entity_titles: set[str],
    changed_doc_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Build a complete entity-relationship graph for one GraphRAG workspace.

    The graph is complete at the indexed debug_50 workspace level. Nodes are
    GraphRAG entities and edges are GraphRAG relationships. Node colors encode
    whether an entity also exists in the other workspace or appears only in the
    current clean/poisoned graph.
    """

    text_unit_doc = text_unit_to_doc_id(artifacts["text_units"])
    entity_doc_ids = entity_to_doc_ids(artifacts["entities"], text_unit_doc)

    nodes: list[dict[str, Any]] = []
    for _, row in artifacts["entities"].iterrows():
        title = str(row["title"])
        only_here = title not in other_entity_titles
        related_changed = bool(entity_doc_ids.get(title, set()) & changed_doc_ids)
        degree = int(row.get("degree", 0) or 0)
        frequency = int(row.get("frequency", 0) or 0)

        if state == "clean":
            background = "#60a5fa" if only_here else "#dbeafe"
            border = "#2563eb"
            role = "clean-only" if only_here else "shared"
        else:
            background = "#ef4444" if only_here else "#e2e8f0"
            border = "#b91c1c" if only_here else "#64748b"
            role = "poisoned-only" if only_here else "shared"
        if related_changed:
            border = "#f97316"

        nodes.append({
            "id": title,
            "label": short_label(title, 24),
            "title": (
                f"<b>{escape(title)}</b><br>"
                f"类型：{escape(str(row.get('type', '')))}<br>"
                f"状态：{role}<br>"
                f"degree={degree}，frequency={frequency}<br>"
                f"关联 changed doc：{'是' if related_changed else '否'}"
            ),
            "color": {"background": background, "border": border},
            "borderWidth": 3 if related_changed else 1,
            "size": node_size(degree),
            "shape": "dot",
            "font": {"face": "Microsoft YaHei", "size": 14, "color": "#102a43"},
        })

    entity_titles = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    for _, row in artifacts["relationships"].iterrows():
        source = str(row.get("source", ""))
        target = str(row.get("target", ""))
        if source not in entity_titles or target not in entity_titles:
            continue
        weight = float(row.get("weight", 0.0) or 0.0)
        edges.append({
            "from": source,
            "to": target,
            "title": (
                f"{escape(source)} -> {escape(target)}<br>"
                f"weight={weight:.6f}<br>"
                f"{escape(str(row.get('description', ''))[:240])}"
            ),
            "color": {"color": "rgba(100,116,139,0.32)"},
            "width": max(0.5, min(3.0, 0.6 + math.sqrt(max(weight, 0.0)) * 25)),
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.35}},
        })
    return {"nodes": nodes, "edges": edges}


def build_difference_graph(
    clean: dict[str, pd.DataFrame],
    poisoned: dict[str, pd.DataFrame],
    changed_doc_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Build a merged graph highlighting clean-only and poisoned-only changes."""

    clean_titles = set(clean["entities"]["title"].astype(str))
    poisoned_titles = set(poisoned["entities"]["title"].astype(str))
    all_titles = clean_titles | poisoned_titles

    clean_degree = degree_by_title(clean["entities"])
    poisoned_degree = degree_by_title(poisoned["entities"])
    clean_doc_map = entity_to_doc_ids(clean["entities"], text_unit_to_doc_id(clean["text_units"]))
    poisoned_doc_map = entity_to_doc_ids(poisoned["entities"], text_unit_to_doc_id(poisoned["text_units"]))

    nodes: list[dict[str, Any]] = []
    for title in sorted(all_titles):
        in_clean = title in clean_titles
        in_poisoned = title in poisoned_titles
        degree = max(clean_degree.get(title, 0), poisoned_degree.get(title, 0))
        related_docs = clean_doc_map.get(title, set()) | poisoned_doc_map.get(title, set())
        related_changed = bool(related_docs & changed_doc_ids)

        if in_clean and in_poisoned:
            role = "shared"
            background = "#e2e8f0"
            border = "#64748b"
        elif in_clean:
            role = "clean-only"
            background = "#93c5fd"
            border = "#2563eb"
        else:
            role = "poisoned-only"
            background = "#fca5a5"
            border = "#dc2626"
        if related_changed:
            border = "#f97316"

        nodes.append({
            "id": title,
            "label": short_label(title, 24),
            "title": (
                f"<b>{escape(title)}</b><br>"
                f"差异角色：{role}<br>"
                f"clean degree={clean_degree.get(title, 0)}<br>"
                f"poisoned degree={poisoned_degree.get(title, 0)}<br>"
                f"关联 changed doc：{'是' if related_changed else '否'}"
            ),
            "color": {"background": background, "border": border},
            "borderWidth": 3 if related_changed else 1,
            "size": node_size(degree),
            "shape": "dot",
            "font": {"face": "Microsoft YaHei", "size": 14, "color": "#102a43"},
        })

    clean_edges = relationship_keys(clean["relationships"])
    poisoned_edges = relationship_keys(poisoned["relationships"])
    all_edges = clean_edges | poisoned_edges
    edges: list[dict[str, Any]] = []
    for source, target in sorted(all_edges):
        in_clean = (source, target) in clean_edges
        in_poisoned = (source, target) in poisoned_edges
        if in_clean and in_poisoned:
            color = "rgba(100,116,139,0.28)"
            role = "shared"
            width = 0.7
        elif in_clean:
            color = "rgba(37,99,235,0.52)"
            role = "clean-only"
            width = 1.3
        else:
            color = "rgba(220,38,38,0.58)"
            role = "poisoned-only"
            width = 1.5
        edges.append({
            "from": source,
            "to": target,
            "title": f"{escape(source)} -> {escape(target)}<br>差异角色：{role}",
            "color": {"color": color},
            "width": width,
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.35}},
        })
    return {"nodes": nodes, "edges": edges}


def build_query_path_graph(
    *,
    clean: dict[str, pd.DataFrame],
    poisoned: dict[str, pd.DataFrame],
    evidence: dict[str, list[dict[str, Any]]],
    metrics: dict[str, dict[str, Any]],
    query_info: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Build a readable four-condition query path graph.

    The path view uses Stage21's auditable evidence lists. For each condition we
    show the top retrieved documents and a small entity neighborhood extracted
    from the corresponding GraphRAG text_unit. The global graph remains complete;
    this path graph is deliberately pruned so the retrieval mechanism is legible.
    """

    clean_lookup = graph_lookup(clean)
    poisoned_lookup = graph_lookup(poisoned)
    support_ids = set(str(x) for x in query_info.get("support_doc_ids", []))
    changed_support_ids = set(str(x) for x in query_info.get("changed_support_doc_ids", []))

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    query = str(query_info.get("query", ""))
    answer = str(query_info.get("answer", ""))

    nodes.append({
        "id": "query",
        "label": f"实验 Query\n{short_label(query, 80)}",
        "title": f"<b>Query</b><br>{escape(query)}<br>Gold answer：{escape(answer)}",
        "x": 0,
        "y": -560,
        "fixed": True,
        "physics": False,
        "shape": "box",
        "color": {"background": "#eef6ff", "border": "#2f80ed"},
        "font": {"face": "Microsoft YaHei", "size": 18, "color": "#102a43"},
        "widthConstraint": {"minimum": 840, "maximum": 920},
    })

    x_positions = {
        "clean_bm25_reference": -760,
        "poisoned_bm25": -255,
        "guarded_filter": 255,
        "recovered_by_doc_id": 760,
    }

    for method, spec in METHODS.items():
        x = x_positions[method]
        metric = metrics.get(method, {})
        method_node = f"method::{method}"
        nodes.append({
            "id": method_node,
            "label": (
                f"{spec['short']}\n"
                f"召回 {rate(metric.get('gold_recall_at_k'))} | "
                f"暴露 {rate(metric.get('changed_doc_exposure_at_k'))}"
            ),
            "title": (
                f"<b>{escape(spec['label'])}</b><br>"
                f"{escape(spec['description'])}<br>"
                f"returned={metric.get('returned_count', '')}<br>"
                f"empty_context={metric.get('empty_context', '')}"
            ),
            "x": x,
            "y": -380,
            "fixed": True,
            "physics": False,
            "shape": "triangle",
            "size": 34,
            "color": {"background": spec["color"], "border": "#1f2937"},
            "font": {"face": "Microsoft YaHei", "size": 15, "color": "#102a43"},
        })
        edges.append(edge("query", method_node, "#64748b", width=1.8))

        method_evidence = evidence.get(method, [])[:6]
        if not method_evidence:
            empty_node = f"{method}::empty"
            nodes.append({
                "id": empty_node,
                "label": "无可用证据",
                "title": "过滤后没有留下证据，容易导致 UNKNOWN。",
                "x": x,
                "y": -220,
                "fixed": True,
                "physics": False,
                "shape": "box",
                "color": {"background": "#f8fafc", "border": "#94a3b8"},
                "font": {"face": "Microsoft YaHei", "size": 14, "color": "#102a43"},
            })
            edges.append(edge(method_node, empty_node, "#94a3b8"))
            continue

        displayed_entity_titles: set[str] = set()
        local_relationships: list[tuple[str, str]] = []

        for doc_index, item in enumerate(method_evidence):
            doc_id = str(item.get("logicguard_doc_id", ""))
            source_state = str(item.get("source_state", ""))
            risk_reasons = list(item.get("risk_reasons", []))
            recovered = bool(item.get("recovered_from_changed_doc"))
            known_changed = "known_changed_doc" in risk_reasons
            is_support = doc_id in support_ids
            is_changed_support = doc_id in changed_support_ids

            lookup = clean_lookup if source_state == "clean_reference" or method == "clean_bm25_reference" else poisoned_lookup
            unit = lookup["text_units_by_id"].get(str(item.get("text_unit_id", "")))
            if unit is None:
                unit = lookup["text_units_by_doc_id"].get(doc_id)

            if recovered:
                doc_background = "#bbf7d0"
                doc_border = "#16a34a"
                doc_state = "recovered clean"
            elif known_changed or is_changed_support:
                doc_background = "#fecaca"
                doc_border = "#dc2626"
                doc_state = "changed / polluted"
            elif source_state == "clean_reference":
                doc_background = "#bfdbfe"
                doc_border = "#2563eb"
                doc_state = "clean reference"
            else:
                doc_background = "#f8fafc"
                doc_border = "#64748b"
                doc_state = "ordinary candidate"

            doc_node = f"{method}::doc::{doc_id}::{doc_index}"
            nodes.append({
                "id": doc_node,
                "label": f"#{item.get('rank')} {doc_id}\n{short_label(str(item.get('title', '')), 32)}",
                "title": (
                    f"<b>{escape(str(item.get('title', '')))}</b><br>"
                    f"doc_id={doc_id}<br>"
                    f"状态：{doc_state}<br>"
                    f"source_state={escape(source_state)}<br>"
                    f"gold_support={'是' if is_support else '否'}<br>"
                    f"changed_support={'是' if is_changed_support else '否'}<br>"
                    f"risk_reasons={escape(str(risk_reasons))}<br>"
                    f"{escape(str(item.get('text', ''))[:280])}"
                ),
                "x": x,
                "y": -205 + doc_index * 92,
                "fixed": True,
                "physics": False,
                "shape": "box",
                "color": {"background": doc_background, "border": doc_border},
                "borderWidth": 4 if is_support else 2,
                "font": {"face": "Microsoft YaHei", "size": 13, "color": "#102a43"},
                "widthConstraint": {"minimum": 265, "maximum": 285},
            })
            edges.append(edge(method_node, doc_node, "#facc15" if is_support else "#94a3b8", width=2.4 if is_support else 1.2))

            if unit is None:
                continue
            entity_ids = as_list(unit.get("entity_ids"))[:3]
            for entity_index, entity_id in enumerate(entity_ids):
                entity = lookup["entities_by_id"].get(str(entity_id))
                if entity is None:
                    continue
                entity_title = str(entity.get("title", ""))
                displayed_entity_titles.add(entity_title)
                entity_node = f"{method}::entity::{entity_title}::{doc_index}::{entity_index}"
                nodes.append({
                    "id": entity_node,
                    "label": short_label(entity_title, 24),
                    "title": (
                        f"<b>{escape(entity_title)}</b><br>"
                        f"来自 doc_id={doc_id}<br>"
                        f"degree={entity.get('degree', '')}"
                    ),
                    "x": x - 120 + entity_index * 120,
                    "y": 385 + doc_index * 30,
                    "fixed": True,
                    "physics": False,
                    "shape": "dot",
                    "color": {"background": "#dbeafe", "border": "#2563eb"},
                    "size": 14,
                    "font": {"face": "Microsoft YaHei", "size": 12, "color": "#102a43"},
                })
                edges.append(edge(doc_node, entity_node, "#60a5fa", width=1.2))

            for rel_id in as_list(unit.get("relationship_ids"))[:8]:
                rel = lookup["relationships_by_id"].get(str(rel_id))
                if rel is not None:
                    local_relationships.append((str(rel.get("source", "")), str(rel.get("target", ""))))

        # Add a small number of real entity-to-entity relationship edges.  The
        # method prefix keeps the four columns visually independent even when
        # the same entity title appears in multiple conditions.
        title_node_ids = defaultdict(list)
        for node in nodes:
            node_id = str(node["id"])
            prefix = f"{method}::entity::"
            if node_id.startswith(prefix):
                title = node_id[len(prefix):].rsplit("::", 2)[0]
                title_node_ids[title].append(node_id)
        rel_count = 0
        for source, target in local_relationships:
            if source in title_node_ids and target in title_node_ids:
                edges.append(edge(title_node_ids[source][0], title_node_ids[target][0], "#cbd5e1", width=0.8, dashes=True))
                rel_count += 1
                if rel_count >= 10:
                    break

    return {"nodes": nodes, "edges": edges}


def render_html(
    *,
    graph_stats: dict[str, int],
    query_info: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
    page_data: dict[str, dict[str, list[dict[str, Any]]]],
    evidence: dict[str, list[dict[str, Any]]],
    clean_corpus: dict[str, dict[str, Any]],
    poisoned_corpus: dict[str, dict[str, Any]],
) -> str:
    """Render the standalone HTML page with tabs and four vis-network canvases."""

    metric_cards = render_metric_cards(graph_stats, metrics)
    evidence_table = render_evidence_table(query_info, evidence)
    text_compare = render_text_comparison(query_info, clean_corpus, poisoned_corpus)
    page_data_json = json.dumps(page_data, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>知识图谱 Clean vs LogicPoison vs LogicGuard</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    :root {{
      --text: #102a43;
      --muted: #52606d;
      --line: #d9e2ec;
      --panel: #ffffff;
      --bg: #fbfcfd;
      --blue: #2f80ed;
      --red: #ef4444;
      --green: #22c55e;
      --amber: #f59e0b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    }}
    header {{
      padding: 24px 30px 18px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    header h1 {{
      margin: 0 0 10px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    header p {{
      margin: 6px 0;
      color: var(--muted);
      line-height: 1.75;
      font-size: 15px;
    }}
    main {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 24px 24px 56px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(6, minmax(145px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px 14px;
      box-shadow: 0 7px 18px rgba(15, 23, 42, 0.05);
      min-height: 86px;
    }}
    .card .name {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }}
    .card .value {{
      margin-top: 8px;
      font-size: 24px;
      font-weight: 800;
      color: var(--text);
    }}
    .tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 18px 0 14px;
    }}
    .tab-button {{
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--text);
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 14px;
      cursor: pointer;
    }}
    .tab-button.active {{
      background: #102a43;
      color: #ffffff;
      border-color: #102a43;
    }}
    .tab-pane {{ display: none; }}
    .tab-pane.active {{ display: block; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 7px 18px rgba(15, 23, 42, 0.05);
    }}
    .network {{
      width: 100%;
      height: 760px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
    }}
    #queryPathNetwork {{ height: 980px; }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      margin: 12px 0 14px;
      color: var(--muted);
      font-size: 14px;
    }}
    .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .dot {{
      width: 13px;
      height: 13px;
      border-radius: 50%;
      display: inline-block;
      border: 1px solid #334155;
    }}
    .explain {{
      line-height: 1.85;
      color: #334155;
      font-size: 15px;
    }}
    .grid2 {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 16px;
      margin-top: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 14px;
      background: #ffffff;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 9px 10px;
      vertical-align: top;
      line-height: 1.55;
    }}
    th {{
      background: #f1f5f9;
      color: #102a43;
      text-align: left;
    }}
    .tag {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
      color: #102a43;
      background: #e2e8f0;
      margin-right: 4px;
      margin-bottom: 4px;
    }}
    .tag.red {{ background: #fecaca; }}
    .tag.green {{ background: #bbf7d0; }}
    .tag.blue {{ background: #bfdbfe; }}
    .tag.amber {{ background: #fde68a; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      line-height: 1.65;
      color: #334155;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      font-size: 13px;
      max-height: 360px;
      overflow: auto;
    }}
    .diff-clean {{
      font-weight: 800;
      color: #1d4ed8;
      background: #dbeafe;
      border-radius: 4px;
      padding: 0 3px;
    }}
    .diff-poison {{
      font-weight: 800;
      color: #991b1b;
      background: #fee2e2;
      border-radius: 4px;
      padding: 0 3px;
    }}
    @media (max-width: 1100px) {{
      .cards {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
      .grid2 {{ grid-template-columns: 1fr; }}
      .network {{ height: 700px; }}
    }}
  </style>
</head>
<body>
<header>
  <h1>知识图谱对比：Clean vs LogicPoison vs LogicGuard</h1>
  <p>数据来源：2WikiMultiHopQA debug_50 / query-ready 子集。全局图谱来自 Microsoft GraphRAG 索引表；单 Query 路径来自 Stage21 top-{TOP_K} 可审计证据流。</p>
  <p>注意：这里的“完整图谱”指当前已索引实验子集的完整实体-关系图，不是 2WikiMultiHopQA 原始全量语料图谱。</p>
</header>
<main>
  <section class="cards">{metric_cards}</section>

  <nav class="tabs">
    <button class="tab-button active" data-tab="overview">说明</button>
    <button class="tab-button" data-tab="clean">Clean 图谱</button>
    <button class="tab-button" data-tab="poisoned">LogicPoison 图谱</button>
    <button class="tab-button" data-tab="diff">差异图谱</button>
    <button class="tab-button" data-tab="path">单 Query 检索路径</button>
    <button class="tab-button" data-tab="text">证据文本对比</button>
  </nav>

  <section id="overview" class="tab-pane active panel">
    <div class="explain">
      <p><b>这张视图想说明什么：</b>LogicPoison 不只是让某个文档文本变错，它会影响 GraphRAG 索引中的实体和关系；在具体问题上，污染证据进入检索路径后会改变 LLM 看到的上下文。LogicGuard 的 Guard 阶段切断污染路径，Recovery 阶段尝试用 clean reference 把关键证据补回来。</p>
      <p><b>推荐阅读顺序：</b>先看 Clean 图谱和 LogicPoison 图谱的规模差异，再看差异图谱中红色新增实体/关系，最后看单 Query 检索路径中 poisoned、guarded、recovered 三种状态的变化。</p>
      <p><b>颜色约定：</b>红色通常表示 poisoned-only 或 changed/polluted；绿色表示 recovered clean evidence；蓝色表示 clean reference；橙色边框表示实体或证据关联 changed doc；黄色边表示 gold support 路径。</p>
    </div>
    {evidence_table}
  </section>

  <section id="clean" class="tab-pane panel">
    <div class="legend">
      <span><i class="dot" style="background:#dbeafe"></i>clean 中与 poisoned 共享实体</span>
      <span><i class="dot" style="background:#60a5fa"></i>clean-only 实体</span>
      <span><i class="dot" style="background:#ffffff;border-color:#f97316"></i>橙色边框：关联 changed doc</span>
    </div>
    <div id="cleanNetwork" class="network"></div>
  </section>

  <section id="poisoned" class="tab-pane panel">
    <div class="legend">
      <span><i class="dot" style="background:#e2e8f0"></i>poisoned 中与 clean 共享实体</span>
      <span><i class="dot" style="background:#ef4444"></i>poisoned-only 实体</span>
      <span><i class="dot" style="background:#ffffff;border-color:#f97316"></i>橙色边框：关联 changed doc</span>
    </div>
    <div id="poisonedNetwork" class="network"></div>
  </section>

  <section id="diff" class="tab-pane panel">
    <div class="legend">
      <span><i class="dot" style="background:#e2e8f0"></i>clean/poisoned 共有</span>
      <span><i class="dot" style="background:#93c5fd"></i>clean-only</span>
      <span><i class="dot" style="background:#fca5a5"></i>poisoned-only</span>
      <span><i class="dot" style="background:#ffffff;border-color:#f97316"></i>橙色边框：关联 changed doc</span>
    </div>
    <div id="diffNetwork" class="network"></div>
  </section>

  <section id="path" class="tab-pane panel">
    <div class="legend">
      <span><i class="dot" style="background:#3b82f6"></i>Clean</span>
      <span><i class="dot" style="background:#ef4444"></i>Poisoned</span>
      <span><i class="dot" style="background:#f59e0b"></i>Guarded</span>
      <span><i class="dot" style="background:#22c55e"></i>Recovered</span>
      <span><i class="dot" style="background:#fecaca"></i>污染/changed 文档</span>
      <span><i class="dot" style="background:#bbf7d0"></i>恢复后的 clean evidence</span>
    </div>
    <div id="queryPathNetwork" class="network"></div>
  </section>

  <section id="text" class="tab-pane panel">
    <div class="explain">
      <p>下面展示该 query 的 changed support 文档在 clean 与 LogicPoison 中的文本差异。红色路径中的污染文本会把错误信息交给 LLM；Recovery 的目标是用 clean reference 替换这类证据。</p>
    </div>
    {text_compare}
  </section>
</main>

<script>
const GRAPH_DATA = {page_data_json};
const networks = {{}};
const options = {{
  physics: {{
    enabled: true,
    stabilization: {{ iterations: 160 }},
    barnesHut: {{
      gravitationalConstant: -7200,
      springLength: 145,
      springConstant: 0.035,
      avoidOverlap: 0.22
    }}
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 120,
    navigationButtons: true,
    keyboard: true
  }},
  edges: {{
    smooth: {{ enabled: true, type: "dynamic" }}
  }}
}};
const fixedOptions = {{
  ...options,
  physics: {{ enabled: false }},
  edges: {{ smooth: {{ enabled: true, type: "cubicBezier" }} }}
}};

function createNetwork(key, elementId, fixed=false) {{
  const el = document.getElementById(elementId);
  if (!el || networks[key]) return;
  const data = {{
    nodes: new vis.DataSet(GRAPH_DATA[key].nodes),
    edges: new vis.DataSet(GRAPH_DATA[key].edges)
  }};
  const net = new vis.Network(el, data, fixed ? fixedOptions : options);
  networks[key] = net;
  if (!fixed) {{
    net.once("stabilizationIterationsDone", () => {{
      net.stopSimulation();
      net.setOptions({{ physics: false }});
      net.fit({{ animation: false }});
    }});
    window.setTimeout(() => {{
      net.stopSimulation();
      net.setOptions({{ physics: false }});
    }}, 2600);
  }}
}}

function showTab(tab) {{
  document.querySelectorAll(".tab-button").forEach(btn => {{
    btn.classList.toggle("active", btn.dataset.tab === tab);
  }});
  document.querySelectorAll(".tab-pane").forEach(pane => {{
    pane.classList.toggle("active", pane.id === tab);
  }});
  if (tab === "clean") createNetwork("cleanGraph", "cleanNetwork");
  if (tab === "poisoned") createNetwork("poisonedGraph", "poisonedNetwork");
  if (tab === "diff") createNetwork("diffGraph", "diffNetwork");
  if (tab === "path") createNetwork("queryPath", "queryPathNetwork", true);
  setTimeout(() => {{
    Object.values(networks).forEach(net => net.fit({{ animation: false }}));
  }}, 80);
}}

document.querySelectorAll(".tab-button").forEach(btn => {{
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
}});
</script>
</body>
</html>
"""


def render_metric_cards(graph_stats: dict[str, int], metrics: dict[str, dict[str, Any]]) -> str:
    """Render compact metric cards for graph size and Stage21 path quality."""

    recovered = metrics.get("recovered_by_doc_id", {})
    poisoned = metrics.get("poisoned_bm25", {})
    guarded = metrics.get("guarded_filter", {})
    cards = [
        ("Clean 实体", str(graph_stats["clean_entities"]), "clean GraphRAG 索引中的实体数"),
        ("Poisoned 实体", str(graph_stats["poisoned_entities"]), "LogicPoison 后 GraphRAG 索引中的实体数"),
        ("Poisoned-only 实体", str(graph_stats["poisoned_only_entities"]), "只在污染图谱中出现的实体"),
        ("Poisoned-only 关系", str(graph_stats["poisoned_only_edges"]), "只在污染图谱中出现的实体关系"),
        ("污染召回暴露", rate(poisoned.get("changed_doc_exposure_at_k")), "poisoned top-k 是否暴露 changed 证据"),
        ("Recovery 召回", rate(recovered.get("gold_recall_at_k")), "Recovery 后 gold support 召回比例"),
        ("Guard 空上下文", rate(guarded.get("empty_context")), "仅过滤后该 query 是否空上下文"),
        ("Recovery 暴露", rate(recovered.get("changed_doc_exposure_at_k")), "Recovery 后未恢复 changed 证据暴露"),
    ]
    return "\n".join(
        f'<article class="card"><div class="name">{escape(desc)}</div>'
        f'<div class="value">{escape(value)}</div><div class="name">{escape(name)}</div></article>'
        for name, value, desc in cards
    )


def render_evidence_table(query_info: dict[str, Any], evidence: dict[str, list[dict[str, Any]]]) -> str:
    """Render a small top evidence table for the overview tab."""

    rows = []
    for method, spec in METHODS.items():
        docs = []
        for item in evidence.get(method, [])[:6]:
            doc_id = str(item.get("logicguard_doc_id", ""))
            title = str(item.get("title", ""))
            state = str(item.get("source_state", ""))
            if item.get("recovered_from_changed_doc"):
                tag_class = "green"
                tag_text = "recovered"
            elif "known_changed_doc" in item.get("risk_reasons", []):
                tag_class = "red"
                tag_text = "changed"
            elif state == "clean_reference":
                tag_class = "blue"
                tag_text = "clean"
            else:
                tag_class = ""
                tag_text = "candidate"
            docs.append(
                f'<span class="tag {tag_class}">#{item.get("rank")} {escape(doc_id)} {escape(short_label(title, 22))} · {tag_text}</span>'
            )
        rows.append(
            "<tr>"
            f"<td><b>{escape(spec['label'])}</b></td>"
            f"<td>{''.join(docs) if docs else '无证据'}</td>"
            "</tr>"
        )
    return f"""
    <table>
      <tr><th>Query</th><td>{escape(str(query_info.get('query', '')))}</td></tr>
      <tr><th>Gold answer</th><td>{escape(str(query_info.get('answer', '')))}</td></tr>
      <tr><th>Gold support</th><td>{', '.join(escape(str(x)) for x in query_info.get('support_doc_ids', []))}</td></tr>
      <tr><th>Changed support</th><td>{', '.join(escape(str(x)) for x in query_info.get('changed_support_doc_ids', []))}</td></tr>
    </table>
    <table>
      <tr><th>状态</th><th>Top 证据摘要</th></tr>
      {''.join(rows)}
    </table>
    """


def render_text_comparison(
    query_info: dict[str, Any],
    clean_corpus: dict[str, dict[str, Any]],
    poisoned_corpus: dict[str, dict[str, Any]],
) -> str:
    """Render clean vs poisoned excerpts for the selected changed supports."""

    rows = []
    for doc_id in query_info.get("changed_support_doc_ids", []):
        clean = clean_corpus.get(str(doc_id), {})
        poisoned = poisoned_corpus.get(str(doc_id), {})
        clean_html, poisoned_html = diff_highlight_pair(
            excerpt(str(clean.get("text", "")), 1400),
            excerpt(str(poisoned.get("text", "")), 1400),
        )
        rows.append(
            "<tr>"
            f"<th colspan='2'>doc_id={escape(str(doc_id))} · {escape(str(clean.get('title') or poisoned.get('title') or ''))}</th>"
            "</tr>"
            "<tr>"
            f"<td><b>Clean</b><pre>{clean_html}</pre></td>"
            f"<td><b>LogicPoison</b><pre>{poisoned_html}</pre></td>"
            "</tr>"
        )
    return f"<table>{''.join(rows)}</table>"


def diff_highlight_pair(clean_text: str, poisoned_text: str) -> tuple[str, str]:
    """Return HTML for clean/poisoned text with changed token spans highlighted.

    The visualization should show semantic substitutions without requiring the
    reader to manually scan two long paragraphs.  Token-level matching is a good
    compromise here: it is more readable than character-level diff and more
    precise than sentence-level diff for names, locations, dates, and titles.
    """

    from difflib import SequenceMatcher

    clean_tokens = tokenize_for_diff(clean_text)
    poisoned_tokens = tokenize_for_diff(poisoned_text)
    matcher = SequenceMatcher(None, clean_tokens, poisoned_tokens, autojunk=False)

    clean_parts: list[str] = []
    poisoned_parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        clean_chunk = "".join(clean_tokens[i1:i2])
        poisoned_chunk = "".join(poisoned_tokens[j1:j2])
        if tag == "equal":
            clean_parts.append(escape(clean_chunk))
            poisoned_parts.append(escape(poisoned_chunk))
            continue
        if tag in {"replace", "delete"} and clean_chunk:
            clean_parts.append(wrap_diff(clean_chunk, "diff-clean"))
        if tag in {"replace", "insert"} and poisoned_chunk:
            poisoned_parts.append(wrap_diff(poisoned_chunk, "diff-poison"))
    return "".join(clean_parts), "".join(poisoned_parts)


def tokenize_for_diff(text: str) -> list[str]:
    """Split text into words, whitespace, and punctuation while preserving layout."""

    return re.findall(r"\s+|[\w'-]+|[^\w\s]", text, flags=re.UNICODE)


def wrap_diff(text: str, class_name: str) -> str:
    """Wrap a changed text chunk with a visible emphasis span."""

    if not text:
        return ""
    return f'<strong class="{class_name}">{escape(text)}</strong>'


def graph_lookup(artifacts: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    """Create lookup dictionaries used by the query path renderer."""

    entities_by_id = {str(row["id"]): row.to_dict() for _, row in artifacts["entities"].iterrows()}
    relationships_by_id = {str(row["id"]): row.to_dict() for _, row in artifacts["relationships"].iterrows()}
    text_units_by_id: dict[str, dict[str, Any]] = {}
    text_units_by_doc_id: dict[str, dict[str, Any]] = {}
    for _, row in artifacts["text_units"].iterrows():
        row_dict = row.to_dict()
        unit_id = str(row_dict["id"])
        text_units_by_id[unit_id] = row_dict
        doc_id = parse_doc_id(str(row_dict.get("text", "")))
        if doc_id is not None:
            text_units_by_doc_id[doc_id] = row_dict
    return {
        "entities_by_id": entities_by_id,
        "relationships_by_id": relationships_by_id,
        "text_units_by_id": text_units_by_id,
        "text_units_by_doc_id": text_units_by_doc_id,
    }


def text_unit_to_doc_id(text_units: pd.DataFrame) -> dict[str, str]:
    """Map GraphRAG text_unit ids to LogicGuard doc ids parsed from text."""

    mapping: dict[str, str] = {}
    for _, row in text_units.iterrows():
        doc_id = parse_doc_id(str(row.get("text", "")))
        if doc_id is not None:
            mapping[str(row["id"])] = doc_id
    return mapping


def entity_to_doc_ids(entities: pd.DataFrame, text_unit_doc: dict[str, str]) -> dict[str, set[str]]:
    """Map each entity title to the LogicGuard document ids that mention it."""

    mapping: dict[str, set[str]] = defaultdict(set)
    for _, row in entities.iterrows():
        title = str(row["title"])
        for text_unit_id in as_list(row.get("text_unit_ids")):
            doc_id = text_unit_doc.get(str(text_unit_id))
            if doc_id is not None:
                mapping[title].add(doc_id)
    return mapping


def degree_by_title(entities: pd.DataFrame) -> dict[str, int]:
    """Return the max degree observed for each entity title."""

    degrees: dict[str, int] = {}
    for _, row in entities.iterrows():
        title = str(row["title"])
        degrees[title] = max(degrees.get(title, 0), int(row.get("degree", 0) or 0))
    return degrees


def relationship_keys(relationships: pd.DataFrame) -> set[tuple[str, str]]:
    """Normalize relationships to source-target title pairs."""

    keys: set[tuple[str, str]] = set()
    for _, row in relationships.iterrows():
        source = str(row.get("source", "")).strip()
        target = str(row.get("target", "")).strip()
        if source and target:
            keys.add((source, target))
    return keys


def edge(
    source: str,
    target: str,
    color: str,
    *,
    width: float = 1.0,
    dashes: bool = False,
) -> dict[str, Any]:
    """Create a vis-network edge with project-consistent defaults."""

    return {
        "from": source,
        "to": target,
        "color": {"color": color},
        "width": width,
        "dashes": dashes,
        "arrows": {"to": {"enabled": True, "scaleFactor": 0.45}},
    }


def update_visualization_index(path: Path) -> None:
    """Add the new page to the existing visualization index if it exists."""

    if not INDEX_HTML.exists():
        return
    text = INDEX_HTML.read_text(encoding="utf-8")
    rel = path.name
    if rel in text:
        return
    card = (
        f'\n            <a class="card" href="{escape(rel)}">\n'
        f'              <div class="file">{escape(rel)}</div>\n'
        "              <p>实验子集级 clean / LogicPoison 全局图谱差异，以及单 Query 在 clean、poisoned、guarded、recovered 下的检索路径对比。</p>\n"
        "            </a>\n            "
    )
    marker = "  </section>"
    if marker in text:
        text = text.replace(marker, card + marker, 1)
        INDEX_HTML.write_text(text, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read UTF-8 or UTF-8-BOM JSONL rows."""

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def parse_doc_id(text: str) -> str | None:
    """Extract the LogicGuard document id embedded in exported GraphRAG text."""

    match = re.search(r"Document ID:\s*([^\n]+)", text)
    if not match:
        return None
    return match.group(1).strip()


def as_list(value: Any) -> list[Any]:
    """Return parquet list-like values as plain Python lists."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return converted if isinstance(converted, list) else [converted]
    return [value]


def node_size(degree: int) -> float:
    """Map GraphRAG entity degree to a readable node size."""

    return max(8.0, min(34.0, 9.0 + math.sqrt(max(degree, 0)) * 3.0))


def rate(value: Any) -> str:
    """Format a metric as a fixed-width decimal string."""

    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "-"


def short_label(text: str, limit: int) -> str:
    """Trim a label without changing the underlying tooltip text."""

    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)] + "…"


def excerpt(text: str, limit: int) -> str:
    """Return a compact text excerpt for side-by-side comparison."""

    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[:limit] + " ..."


def escape(value: Any) -> str:
    """HTML-escape arbitrary values."""

    return html.escape(str(value), quote=True)


if __name__ == "__main__":
    main()
