"""独立可视化脚本 —— 只读取 outputs/ 产物，不修改项目源码。

用法:
  cd F:\LogicGuard_project\logicguard

  # 1) 可视化单个 query 的轻量图检索路径
  .venv\Scripts\python.exe tools/visualize.py light \
    --trace outputs/baseline/2wikimultihopqa/full_500_traces.jsonl \
    --query-index 0

  # 2) 可视化 NaiveRAG BM25 检索结果
  .venv\Scripts\python.exe tools/visualize.py naive \
    --trace outputs/naive_rag/bm25/2wikimultihopqa/full_500_traces.jsonl \
    --query-index 0

  # 3) 可视化 MS GraphRAG official 实体-关系图
  .venv\Scripts\python.exe tools/visualize.py official \
    --workspace outputs/ms_graphrag/2wikimultihopqa/stage14_local_defense_5_poisoned_query_ready \
    --query-context outputs/ms_graphrag_query/stage14_5_official_query_pipeline_context.jsonl

  # 4) 对比视图: 干净检索 vs 污染检索 vs 过滤 vs 恢复
  .venv\Scripts\python.exe tools/visualize.py compare \
    --clean outputs/defense/logicpoison_official/2wikimultihopqa/naive_bm25_none_traces.jsonl \
    --guarded outputs/defense/logicpoison_official/2wikimultihopqa/naive_bm25_full_logicguard_traces.jsonl \
    --recovered outputs/defense/logicpoison_official/2wikimultihopqa/naive_bm25_full_logicguard_recovery_traces.jsonl \
    --query-index 0

输出目录: outputs/visualizations/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

OUTPUT_DIR = Path("outputs/visualizations")


def _load_traces(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ── 轻量图路径可视化 ──────────────────────────────────────────

def viz_lightweight(trace_path: Path, query_index: int) -> None:
    """可视化轻量 GraphRAG 的文档-实体路径（二部图检索）。"""
    from pyvis.network import Network

    traces = _load_traces(trace_path)
    trace = traces[query_index]
    net = Network(height="750px", width="100%", bgcolor="#ffffff", font_color="#222")
    net.set_options(_pyvis_options())

    query_entities = {e["normalized"]: e["text"] for e in trace["query_entities"]}

    # Query 根节点
    net.add_node("query", label=f"Q: {trace['query'][:50]}...",
                 color="#e74c3c", size=38, shape="star", title=trace["query"])

    # Query 实体
    for norm, surf in query_entities.items():
        node_id = f"ent_q:{norm}"
        net.add_node(node_id, label=surf, color="#e67e22", size=22, shape="dot",
                     title=f"Query entity: {surf}")
        net.add_edge("query", node_id, color="#e74c3c", dashes=True)

    # 候选路径（最多展示 6 个候选）
    colors = ["#2ecc71", "#3498db", "#9b59b6", "#1abc9c", "#f39c12", "#e91e63"]
    for rank, cand in enumerate(trace["candidates"][:6]):
        gold = cand["doc_id"] in trace["gold_doc_ids"]
        border = "#f1c40f" if gold else colors[rank % len(colors)]
        doc_node = f"doc:{cand['doc_id']}"
        title_short = cand["title"][:40]
        label = f"[GOLD] {title_short}" if gold else f"[{rank + 1}] {title_short}"

        net.add_node(doc_node, label=label, color=border if gold else colors[rank % len(colors)],
                     size=30 if gold else 22, shape="box",
                     title=f"doc_id={cand['doc_id']}\ntitle={cand['title']}\nscore={cand['score']:.4f}")

        prev_node = None
        for step_i, node in enumerate(cand["path_nodes"]):
            node_id = f"path_{cand['doc_id']}_{step_i}"
            if node.startswith("ent:") and node.removeprefix("ent:") not in query_entities:
                label_text = node.removeprefix("ent:")[:25]
                if node_id not in [n["id"] for n in net.nodes]:
                    net.add_node(node_id, label=label_text, color="#95a5a6", size=14, shape="dot",
                                 title=f"Bridge entity: {label_text}")
            elif node.startswith("query:"):
                if prev_node:
                    net.add_edge(prev_node, "query", color="#bdc3c7", dashes=True)
                continue
            elif node.startswith("doc:") and node == doc_node:
                continue
            else:
                continue

            if prev_node:
                net.add_edge(prev_node, node_id, color="#bdc3c7")
            prev_node = node_id

        # 连接到最终文档
        if prev_node:
            net.add_edge(prev_node, doc_node, color=border if gold else "#7f8c8d", width=2)
        else:
            # NaiveRAG 风格的两节点路径
            for ent_norm in cand.get("matched_query_entities", []):
                ent_node = f"ent_q:{ent_norm}"
                if ent_node in [n["id"] for n in net.nodes]:
                    net.add_edge(ent_node, doc_node, color=border if gold else "#7f8c8d", width=2)

    html_path = OUTPUT_DIR / f"light_q{query_index}_{trace['query_id'][:8]}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(html_path))
    print(f"[OK] light graph: {html_path}")


# ── MS GraphRAG 实体-关系图 ────────────────────────────────────

def viz_official(workspace: Path, query_context: Path | None) -> None:
    """可视化 Microsoft GraphRAG official 的实体-关系图。"""
    import pandas as pd
    from pyvis.network import Network

    entities = pd.read_parquet(workspace / "output" / "entities.parquet")
    relations = pd.read_parquet(workspace / "output" / "relationships.parquet")

    net = Network(height="800px", width="100%", bgcolor="#ffffff", font_color="#222")
    net.set_options(_pyvis_options())

    # 加载 context 中 selected entities/sources
    selected_entities: set[str] = set()
    changed_docs: set[str] = set()
    if query_context and query_context.exists():
        contexts = _load_traces(query_context)
        for ctx in contexts:
            cd = ctx.get("context_data", {})
            if isinstance(cd, dict):
                for ent in cd.get("entities", []):
                    if isinstance(ent, dict):
                        selected_entities.add(str(ent.get("title", ent.get("name", ""))))
                for src in cd.get("sources", []):
                    if isinstance(src, dict):
                        doc_id = str(src.get("logicguard_doc_id", src.get("document_id", "")))
                        changed_docs.add(doc_id)

    # 实体节点
    for _, row in entities.iterrows():
        title = str(row["title"])
        etype = str(row.get("type", ""))
        is_selected = title in selected_entities
        colors_map = {"PERSON": "#3498db", "ORGANIZATION": "#e74c3c", "GEO": "#2ecc71", "EVENT": "#f39c12"}
        color = colors_map.get(etype.upper(), "#95a5a6")
        net.add_node(title, label=title[:30],
                     color=color, size=20 if is_selected else 12,
                     shape="dot" if is_selected else "dot",
                     borderWidth=3 if is_selected else 0,
                     title=f"type={etype}\ndesc={str(row.get('description',''))[:120]}")

    # 关系边
    for _, row in relations.iterrows():
        src = str(row["source"])
        tgt = str(row["target"])
        weight = float(row.get("weight", 1))
        net.add_edge(src, tgt, value=weight, title=str(row.get("description", ""))[:100],
                     color="#bdc3c7")

    html_path = OUTPUT_DIR / f"official_{workspace.name}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(html_path))
    print(f"[OK] MS GraphRAG graph: {html_path}")
    print(f"  entities={len(entities)}, relations={len(relations)}, selected_entities={len(selected_entities)}")


# ── NaiveRAG 检索结果可视化 ────────────────────────────────────

def viz_naive(trace_path: Path, query_index: int) -> None:
    """可视化 NaiveRAG BM25/Hybrid 检索结果（无图路径，以列表视图展示）。"""
    from pyvis.network import Network

    traces = _load_traces(trace_path)
    trace = traces[query_index]
    net = Network(height="700px", width="100%", bgcolor="#ffffff", font_color="#222")
    net.set_options(_pyvis_options())

    query_text = trace["query"][:60]
    net.add_node("query", label=f"Q: {query_text}...", color="#e74c3c", size=35, shape="star")

    for rank, cand in enumerate(trace["candidates"][:8]):
        gold = cand["doc_id"] in trace["gold_doc_ids"]
        if gold:
            color, size, prefix = "#f1c40f", 28, "★ GOLD"
        else:
            color, size, prefix = "#3498db", 18, f"#{rank + 1}"
        doc_node = f"doc_{cand['doc_id']}"
        label = f"{prefix} {cand['title'][:35]}"
        net.add_node(doc_node, label=label, color=color, size=size, shape="box",
                     title=f"doc_id={cand['doc_id']}\nscore={cand['score']:.4f}\ntitle={cand['title']}\nsource={cand.get('bridge_entities',[])}")

        source_label = cand.get("bridge_entities", ["?"])[0] if cand.get("bridge_entities") else "?"
        edge_color = "#f1c40f" if gold else "#7f8c8d"
        net.add_edge("query", doc_node, color=edge_color, width=2, title=f"score={cand['score']:.4f} | {source_label}")

    html_path = OUTPUT_DIR / f"naive_q{query_index}_{trace['query_id'][:8]}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(html_path))
    print(f"[OK] NaiveRAG viz: {html_path}")


# ── 四条件对比视图 ─────────────────────────────────────────────

def viz_compare(clean_path: Path, guarded_path: Path, recovered_path: Path, query_index: int) -> None:
    """并排对比 clean / poisoned / guarded / recovered 四个条件的检索结果。"""
    from pyvis.network import Network

    clean_traces = _load_traces(clean_path)
    guarded_traces = _load_traces(guarded_path)
    recovered_traces = _load_traces(recovered_path)

    clean_trace = clean_traces[query_index]
    guarded_trace = guarded_traces[query_index]
    recovered_trace = recovered_traces[query_index]

    net = Network(height="900px", width="100%", bgcolor="#fafafa", font_color="#222")
    net.set_options(_pyvis_options())

    gold_ids = set(clean_trace["gold_doc_ids"])
    # 四个条件作为列头
    conditions = [
        ("POISONED", clean_trace, "#e74c3c"),   # 注意: clean_trace 在这里是 none 模式=poisoned 原始结果
        ("GUARDED", guarded_trace, "#e67e22"),
        ("RECOVERED", recovered_trace, "#2ecc71"),
    ]

    for cond_idx, (name, trace, color) in enumerate(conditions):
        group_node = f"group_{name}"
        net.add_node(group_node, label=name, color=color, size=32, shape="triangle",
                     x=cond_idx * 400 - 400, y=-200)

        for rank, cand in enumerate(trace["candidates"][:6]):
            node_id = f"{name}_d{cand['doc_id']}"
            gold = cand["doc_id"] in gold_ids
            recovered = "recovery" in str(cand.get("risk_reasons", []))
            risk = cand.get("risk_score", 0)

            if recovered:
                node_color, node_label = "#2ecc71", f"↻ {cand['title'][:30]}"
            elif gold:
                node_color, node_label = "#f1c40f", f"★ {cand['title'][:30]}"
            elif risk > 0:
                node_color, node_label = "#e74c3c", f"⚠ R{risk:.1f} {cand['title'][:25]}"
            else:
                node_color, node_label = "#95a5a6", f"{cand['title'][:30]}"

            net.add_node(node_id, label=node_label, color=node_color, size=20, shape="box",
                         title=f"rank={rank + 1}\ndoc_id={cand['doc_id']}\nrisk={risk}\nreasons={cand.get('risk_reasons',[])}")
            net.add_edge(group_node, node_id, color="#bdc3c7")

    html_path = OUTPUT_DIR / f"compare_q{query_index}_{clean_trace['query_id'][:8]}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(html_path))
    print(f"[OK] compare view: {html_path}")


# ── 工具函数 ────────────────────────────────────────────────────

def _pyvis_options() -> str:
    return """
{
  "physics": {
    "barnesHut": { "gravitationalConstant": -3000, "springLength": 180 },
    "minVelocity": 0.5
  },
  "interaction": {
    "hover": true,
    "tooltipDelay": 100,
    "navigationButtons": true
  }
}"""


# ── CLI ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LogicGuard 可视化工具")
    sub = parser.add_subparsers(dest="cmd")

    p1 = sub.add_parser("light", help="轻量 GraphRAG 检索路径")
    p1.add_argument("--trace", type=Path, required=True)
    p1.add_argument("--query-index", type=int, default=0)

    p2 = sub.add_parser("naive", help="NaiveRAG BM25 检索结果")
    p2.add_argument("--trace", type=Path, required=True)
    p2.add_argument("--query-index", type=int, default=0)

    p3 = sub.add_parser("official", help="MS GraphRAG 实体-关系图")
    p3.add_argument("--workspace", type=Path, required=True)
    p3.add_argument("--query-context", type=Path, default=None)

    p4 = sub.add_parser("compare", help="poisoned / guarded / recovered 对比")
    p4.add_argument("--clean", type=Path, required=True)
    p4.add_argument("--guarded", type=Path, required=True)
    p4.add_argument("--recovered", type=Path, required=True)
    p4.add_argument("--query-index", type=int, default=0)

    args = parser.parse_args()
    if args.cmd == "light":
        viz_lightweight(args.trace, args.query_index)
    elif args.cmd == "naive":
        viz_naive(args.trace, args.query_index)
    elif args.cmd == "official":
        viz_official(args.workspace, args.query_context)
    elif args.cmd == "compare":
        viz_compare(args.clean, args.guarded, args.recovered, args.query_index)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
