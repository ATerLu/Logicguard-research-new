"""Generate Chinese showcase visualizations for the current LogicGuard results.

This script is intentionally read-only with respect to experiment artifacts:
it only reads CSV/JSONL/Parquet outputs and writes HTML files under
``outputs/visualizations``.  The goal is to make the latest useful results easy
to explain in a paper draft or group-meeting demo.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Iterable

import pandas as pd
from pyvis.network import Network


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "visualizations"

STAGE21_SUMMARY = ROOT / "outputs" / "ms_graphrag_query" / "stage21_medium_summary.csv"
STAGE21_METRICS = ROOT / "outputs" / "ms_graphrag_query" / "stage21_medium_metrics.csv"
STAGE21_EVIDENCE = ROOT / "outputs" / "ms_graphrag_query" / "stage21_medium_evidence.jsonl"

STAGE22_SUMMARY = ROOT / "outputs" / "ms_graphrag_query" / "stage22_poisoned5_query_guard_summary.csv"
STAGE22_METRICS = ROOT / "outputs" / "ms_graphrag_query" / "stage22_poisoned5_query_guard_metrics.csv"
STAGE22_SEED_PLAN = ROOT / "outputs" / "ms_graphrag_query" / "stage22_poisoned5_query_seed_plan.jsonl"
STAGE22_WORKSPACE = (
    ROOT
    / "outputs"
    / "ms_graphrag"
    / "2wikimultihopqa"
    / "stage10_debug50_poisoned_query_ready"
    / "output"
)


METHOD_LABELS = {
    "poisoned_bm25": "污染 BM25",
    "title_boosted_poisoned": "标题增强污染检索",
    "guarded_filter": "仅过滤 Guard",
    "recovered_by_doc_id": "Recovery 替换恢复",
    "clean_bm25_reference": "干净参考检索",
    "mixed_baseline": "官方默认混合检索",
    "budget_expansion": "扩大上下文预算",
    "all_entities_baseline": "全部实体基线",
    "title_seeding": "标题实体前置",
    "entity_rerank": "实体重排序",
    "cluster_suppression": "异常簇抑制",
    "full_query_guard": "完整查询层 Guard",
}


def main() -> None:
    """Build every showcase page and print the generated file paths."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generated = [
        build_stage21_overview(),
        build_atomised_evidence_flow(),
        build_stage22_official_query_layer(),
        build_stage22_seed_graph(),
        build_project_flow(),
        build_stage_roadmap(),
        build_stage21_safety_utility_tradeoff(),
        build_stage21_recovery_effect(),
        build_stage22_cost_recall_bubble(),
        build_stage22_query_heatmap(),
        build_stage22_query_entity_source_graph(),
        build_stage22_query_seed_network(),
        build_stage22_anomaly_entity_network(),
    ]
    generated.append(build_index(generated))

    print("生成完成：")
    for path in generated:
        print(f" - {path}")


def build_stage21_overview() -> Path:
    """Visualize the strongest current defense evidence: Stage21, 50 queries."""
    df = pd.read_csv(STAGE21_SUMMARY)
    df = df[(df["top_k"] == 10) & (df["method"].isin([
        "poisoned_bm25",
        "guarded_filter",
        "recovered_by_doc_id",
        "clean_bm25_reference",
    ]))]

    net = _network("900px", physics=False)
    _add_page_title_node(
        net,
        "Stage21：50 个问题上的防御效果总览",
        "核心观察：仅过滤可以把污染暴露降为 0，但会严重丢失证据；Recovery 能把召回恢复到污染检索水平，同时保持污染暴露为 0。",
        y=-330,
    )

    positions = {
        "poisoned_bm25": (-630, -60),
        "guarded_filter": (-210, -60),
        "recovered_by_doc_id": (210, -60),
        "clean_bm25_reference": (630, -60),
    }
    colors = {
        "poisoned_bm25": "#e74c3c",
        "guarded_filter": "#f39c12",
        "recovered_by_doc_id": "#2ecc71",
        "clean_bm25_reference": "#3498db",
    }

    for _, row in df.iterrows():
        method = row["method"]
        x, y = positions[method]
        recall = _rate(row["avg_gold_recall_at_k"])
        exposure = _rate(row["avg_changed_doc_exposure_at_k"])
        empty = _rate(row["empty_context_rate"])
        recovered = float(row["avg_recovered_evidence_count"])

        label = (
            f"{METHOD_LABELS[method]}\n"
            f"证据召回 {recall}\n"
            f"污染暴露 {exposure}\n"
            f"空上下文 {empty}"
        )
        title = (
            f"<b>{METHOD_LABELS[method]}</b><br>"
            f"gold recall：金标准证据召回，越高越好 = {recall}<br>"
            f"changed exposure：污染证据暴露，越低越安全 = {exposure}<br>"
            f"empty context：完全没有可用上下文的比例，越低越好 = {empty}<br>"
            f"avg recovered：平均恢复证据数 = {recovered:.2f}"
        )
        net.add_node(
            method,
            label=label,
            title=title,
            x=x,
            y=y,
            fixed=True,
            physics=False,
            shape="box",
            color={"background": colors[method], "border": "#2d3436"},
            font={"color": "#ffffff", "size": 20, "face": "Microsoft YaHei"},
            widthConstraint={"minimum": 240, "maximum": 260},
            heightConstraint={"minimum": 120},
        )

        _add_metric_badge(
            net,
            f"{method}_recall",
            "召回",
            recall,
            "越高越好；表示正确支撑证据是否被找回来。",
            x,
            y + 185,
            _metric_color(float(row["avg_gold_recall_at_k"]), higher_is_better=True),
        )
        _add_metric_badge(
            net,
            f"{method}_exposure",
            "污染暴露",
            exposure,
            "越低越好；表示污染证据是否进入上下文。",
            x,
            y + 300,
            _metric_color(float(row["avg_changed_doc_exposure_at_k"]), higher_is_better=False),
        )
        net.add_edge(method, f"{method}_recall", color="#95a5a6", arrows="to")
        net.add_edge(method, f"{method}_exposure", color="#95a5a6", arrows="to")

    flow = ["poisoned_bm25", "guarded_filter", "recovered_by_doc_id", "clean_bm25_reference"]
    for left, right in zip(flow, flow[1:]):
        net.add_edge(left, right, color="#34495e", width=3, arrows="to")

    path = OUTPUT_DIR / "01_总览_Stage21_50问防御效果.html"
    return _save(
        net,
        path,
        "Stage21 50问防御效果总览",
        [
            "数据来源：stage21_medium_summary.csv，2WikiMultihopQA，top_k=10，query_count=50。",
            "金标准证据召回越高越好；污染证据暴露越低越安全；空上下文率越低越可用。",
            "最适合放在论文中说明 LogicGuard 的核心机制：Guard 负责降风险，Recovery 负责恢复可用性。",
        ],
    )


def build_atomised_evidence_flow() -> Path:
    """Visualize one concrete query so the three-stage mechanism is inspectable."""
    query_id = "a457e11c0bdb11eba7f7acde48001122"
    query = "Who is the mother of the director of film Atomised (Film)?"
    methods = ["poisoned_bm25", "guarded_filter", "recovered_by_doc_id", "clean_bm25_reference"]

    metrics = pd.read_csv(STAGE21_METRICS)
    metrics = metrics[(metrics["query_id"] == query_id) & (metrics["top_k"] == 10)]
    metric_by_method = {row["method"]: row for _, row in metrics.iterrows()}

    evidence_by_method: dict[str, list[dict]] = {method: [] for method in methods}
    for row in _jsonl(STAGE21_EVIDENCE):
        if row["query_id"] == query_id and row["top_k"] == 10 and row["method"] in methods:
            evidence_by_method[row["method"]] = row["evidence"]

    net = _network("1100px", physics=False)
    _add_page_title_node(
        net,
        "样例：Atomised 问题的证据流",
        "这张图展示同一个问题在污染检索、仅过滤、Recovery、干净参考四种状态下到底拿到了哪些文档。",
        y=-430,
    )
    net.add_node(
        "query",
        label=f"问题\n{query}",
        title=f"<b>查询 ID</b><br>{query_id}",
        x=0,
        y=-290,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": "#eef6ff", "border": "#2f80ed"},
        font={"color": "#102a43", "size": 20, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 820, "maximum": 880},
        heightConstraint={"minimum": 90},
    )

    x_positions = {
        "poisoned_bm25": -690,
        "guarded_filter": -230,
        "recovered_by_doc_id": 230,
        "clean_bm25_reference": 690,
    }
    method_colors = {
        "poisoned_bm25": "#e74c3c",
        "guarded_filter": "#f39c12",
        "recovered_by_doc_id": "#2ecc71",
        "clean_bm25_reference": "#3498db",
    }

    for method in methods:
        row = metric_by_method[method]
        x = x_positions[method]
        method_node = f"method_{method}"
        label = (
            f"{METHOD_LABELS[method]}\n"
            f"召回 {_rate(row['gold_recall_at_k'])} | 暴露 {_rate(row['changed_doc_exposure_at_k'])}\n"
            f"返回 {int(row['returned_count'])} 篇"
        )
        net.add_node(
            method_node,
            label=label,
            title=(
                f"hit@k={_rate(row['hit_at_k'])}<br>"
                f"gold_recall={_rate(row['gold_recall_at_k'])}<br>"
                f"changed_exposure={_rate(row['changed_doc_exposure_at_k'])}<br>"
                f"precision={_rate(row['precision_at_k'])}<br>"
                f"empty_context={int(row['empty_context'])}"
            ),
            x=x,
            y=-120,
            fixed=True,
            physics=False,
            shape="box",
            color={"background": method_colors[method], "border": "#2d3436"},
            font={"color": "#ffffff", "size": 18, "face": "Microsoft YaHei"},
            widthConstraint={"minimum": 285, "maximum": 310},
            heightConstraint={"minimum": 95},
        )
        net.add_edge("query", method_node, color="#7f8c8d", arrows="to")

        support_ids = set(_split_ids(row["support_doc_ids"]))
        gold_hit_ids = set(_split_ids(row["gold_hit_ids"]))
        changed_hit_ids = set(_split_ids(row["changed_gold_hit_ids"]))
        evidence = evidence_by_method[method]

        if not evidence:
            empty_node = f"{method}_empty"
            net.add_node(
                empty_node,
                label="没有返回证据",
                title="Guard 过滤后没有留下可用证据，容易导致拒答或 UNKNOWN。",
                x=x,
                y=60,
                fixed=True,
                physics=False,
                shape="box",
                color={"background": "#ecf0f1", "border": "#95a5a6"},
                font={"color": "#2d3436", "size": 16, "face": "Microsoft YaHei"},
            )
            net.add_edge(method_node, empty_node, color="#bdc3c7", arrows="to")
            continue

        for index, item in enumerate(evidence[:10]):
            doc_id = str(item["logicguard_doc_id"])
            node_id = f"{method}_{doc_id}_{index}"
            is_support = doc_id in support_ids
            is_gold_hit = doc_id in gold_hit_ids
            is_changed_hit = doc_id in changed_hit_ids
            is_recovered = bool(item.get("recovered_from_changed_doc"))
            risk_reasons = item.get("risk_reasons", [])
            is_known_changed = "known_changed_doc" in risk_reasons
            source_state = item.get("source_state", "")

            if is_recovered:
                state = "已恢复"
                background = "#2ecc71"
                font_color = "#ffffff"
            elif is_known_changed:
                state = "污染"
                background = "#e74c3c"
                font_color = "#ffffff"
            elif source_state == "clean_reference":
                state = "干净参考"
                background = "#3498db"
                font_color = "#ffffff"
            else:
                state = "普通候选"
                background = "#ecf0f1"
                font_color = "#2d3436"

            border = "#f1c40f" if is_gold_hit else "#7f8c8d"
            border_width = 5 if is_gold_hit else 1
            label = (
                f"#{int(item['rank'])} [{state}]\n"
                f"{doc_id} {str(item['title'])[:28]}"
            )
            title = (
                f"<b>{html.escape(str(item['title']))}</b><br>"
                f"doc_id={doc_id}<br>"
                f"rank={item['rank']}，score={float(item.get('score', 0.0)):.4f}<br>"
                f"source_state={html.escape(str(source_state))}<br>"
                f"gold_support={is_support}，gold_hit={is_gold_hit}<br>"
                f"changed_gold_hit={is_changed_hit}<br>"
                f"risk_reasons={html.escape(str(risk_reasons))}<br>"
                f"文本片段：{html.escape(str(item.get('text', ''))[:260])}"
            )
            net.add_node(
                node_id,
                label=label,
                title=title,
                x=x,
                y=40 + index * 82,
                fixed=True,
                physics=False,
                shape="box",
                color={"background": background, "border": border},
                borderWidth=border_width,
                font={"color": font_color, "size": 14, "face": "Microsoft YaHei"},
                widthConstraint={"minimum": 320, "maximum": 340},
                heightConstraint={"minimum": 58},
            )
            edge_color = "#f1c40f" if is_gold_hit else "#bdc3c7"
            net.add_edge(method_node, node_id, color=edge_color, arrows="to")

    path = OUTPUT_DIR / "02_样例_Atomised问题_证据流.html"
    return _save(
        net,
        path,
        "Atomised 问题三阶段证据流",
        [
            "红色表示已知被改写或污染的证据；绿色表示从干净参考中恢复回来的替换证据；黄色边框表示命中 gold support。",
            "这个样例清楚展示：仅过滤会把污染证据清掉，但也会丢掉关键支撑；Recovery 将关键证据以干净版本补回。",
            "数据来源：stage21_medium_evidence.jsonl 与 stage21_medium_metrics.csv，top_k=10。",
        ],
    )


def build_stage22_official_query_layer() -> Path:
    """Show the newest official GraphRAG query-layer comparison."""
    df = pd.read_csv(STAGE22_SUMMARY)
    ordered = [
        "mixed_baseline",
        "budget_expansion",
        "all_entities_baseline",
        "title_seeding",
        "entity_rerank",
        "cluster_suppression",
        "full_query_guard",
    ]
    df = df.set_index("method").loc[ordered].reset_index()

    net = _network("950px", physics=False)
    _add_page_title_node(
        net,
        "Stage22：official GraphRAG 查询层方法对比",
        "这张图展示我们已经能控制 official LocalSearchMixedContext 的查询层，但当前主要解决的是召回问题，还没有完成 sources 级 recovery。",
        y=-360,
    )

    x0 = -720
    gap = 240
    for idx, row in df.iterrows():
        method = row["method"]
        x = x0 + idx * gap
        recall = float(row["avg_gold_support_recall"])
        exposure = float(row["avg_changed_support_exposure"])
        sources = float(row["avg_source_count"])
        failures = int(row["context_recall_failure_count"])

        if method == "full_query_guard":
            color = "#16a085"
        elif method == "budget_expansion":
            color = "#d35400"
        elif method in {"title_seeding", "cluster_suppression"}:
            color = "#2980b9"
        else:
            color = "#7f8c8d"

        label = (
            f"{METHOD_LABELS[method]}\n"
            f"召回 {_rate(recall)}\n"
            f"污染暴露 {_rate(exposure)}\n"
            f"平均 sources {sources:.1f}\n"
            f"失败 {failures}/5"
        )
        title = (
            f"<b>{METHOD_LABELS[method]}</b><br>"
            f"gold_support_recall：正确支撑证据召回率 = {_rate(recall)}<br>"
            f"changed_support_exposure：污染支撑证据暴露率 = {_rate(exposure)}<br>"
            f"avg_source_count：平均上下文来源数 = {sources:.1f}<br>"
            f"context_recall_failure_count：完全没召回 gold support 的问题数 = {failures}"
        )
        net.add_node(
            method,
            label=label,
            title=title,
            x=x,
            y=-80,
            fixed=True,
            physics=False,
            shape="box",
            color={"background": color, "border": "#2d3436"},
            font={"color": "#ffffff", "size": 16, "face": "Microsoft YaHei"},
            widthConstraint={"minimum": 205, "maximum": 220},
            heightConstraint={"minimum": 135},
        )
        _add_metric_badge(
            net,
            f"{method}_recall",
            "召回",
            _rate(recall),
            "越高越好；Stage22 中 full_query_guard 达到 0.90。",
            x,
            130,
            _metric_color(recall, higher_is_better=True),
        )
        _add_metric_badge(
            net,
            f"{method}_exposure",
            "暴露",
            _rate(exposure),
            "越低越安全；这里与召回同步升高，说明还需要 recovery。",
            x,
            250,
            _metric_color(exposure, higher_is_better=False),
        )
        _add_metric_badge(
            net,
            f"{method}_sources",
            "sources",
            f"{sources:.1f}",
            "不是越高越好；过高意味着上下文过宽、噪声和污染入口变多。",
            x,
            370,
            "#f39c12" if sources > 50 else "#3498db",
        )
        net.add_edge(method, f"{method}_recall", color="#bdc3c7", arrows="to")
        net.add_edge(method, f"{method}_exposure", color="#bdc3c7", arrows="to")
        net.add_edge(method, f"{method}_sources", color="#bdc3c7", arrows="to")

    net.add_node(
        "next_step",
        label="下一步\n把 Recovery 接到 official sources 后处理",
        title="当前 Stage22 已经证明查询层可控，但 changed exposure 仍然高。下一步要替换或压制 sources 中的污染证据。",
        x=0,
        y=560,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": "#f3e8ff", "border": "#8e44ad"},
        font={"color": "#102a43", "size": 20, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 560, "maximum": 620},
        heightConstraint={"minimum": 80},
    )
    net.add_edge("full_query_guard", "next_step", color="#8e44ad", width=3, arrows="to")

    path = OUTPUT_DIR / "03_对比_Stage22_官方GraphRAG查询层.html"
    return _save(
        net,
        path,
        "Stage22 official GraphRAG 查询层对比",
        [
            "数据来源：stage22_poisoned5_query_guard_summary.csv，5 个 poisoned query-ready 问题。",
            "full_query_guard 将 gold recall 提高到 0.90，且 avg sources 控制在 25.8，明显优于简单 budget_expansion 的 95.8。",
            "但 changed exposure 仍为 0.90，说明这不是最终防御成功，而是证明 official 查询层已经可被 LogicGuard 控制。",
        ],
    )


def build_stage22_seed_graph() -> Path:
    """Visualize the query-layer seed neighborhood in the official graph.

    The full official graph is useful for debugging, but it is too dense for a
    presentation slide.  For this showcase page we keep all include/exclude
    seeds, then add their highest-degree one-hop neighbors.  This keeps the
    graph explainable while preserving the part directly touched by
    ``full_query_guard``.
    """
    entities = pd.read_parquet(STAGE22_WORKSPACE / "entities.parquet")
    relationships = pd.read_parquet(STAGE22_WORKSPACE / "relationships.parquet")

    include_entities: set[str] = set()
    exclude_entities: set[str] = set()
    for row in _jsonl(STAGE22_SEED_PLAN):
        method = row.get("methods", {}).get("full_query_guard", {})
        include_entities.update(str(x) for x in method.get("include_entity_names", []))
        exclude_entities.update(str(x) for x in method.get("exclude_entity_names", []))

    all_entity_names = set(str(x) for x in entities["title"])
    focus_entities = (include_entities | exclude_entities) & all_entity_names
    neighbor_entities: set[str] = set()
    for _, row in relationships.iterrows():
        source = str(row["source"])
        target = str(row["target"])
        if source in focus_entities or target in focus_entities:
            neighbor_entities.add(source)
            neighbor_entities.add(target)

    # Keep the graph readable: all focus nodes plus the strongest one-hop
    # neighbors by GraphRAG degree.  This is a visualization choice only; it
    # does not change any experiment result.
    degree_by_entity = {
        str(row["title"]): float(row.get("degree", 0) or 0)
        for _, row in entities.iterrows()
    }
    selected_entities = set(focus_entities)
    for name in sorted(neighbor_entities - focus_entities, key=lambda x: degree_by_entity.get(x, 0), reverse=True):
        if len(selected_entities) >= 90:
            break
        selected_entities.add(name)

    entities = entities[entities["title"].astype(str).isin(selected_entities)].copy()
    relationships = relationships[
        relationships["source"].astype(str).isin(selected_entities)
        & relationships["target"].astype(str).isin(selected_entities)
    ].copy()
    relationships["touches_focus"] = (
        relationships["source"].astype(str).isin(focus_entities)
        | relationships["target"].astype(str).isin(focus_entities)
    )
    relationships = relationships.sort_values(
        ["touches_focus", "combined_degree"], ascending=[False, False]
    ).head(160)

    node_positions = _seed_graph_positions(entities, include_entities, exclude_entities)

    net = _network("1200px", physics=False)
    _add_page_title_node(
        net,
        "Stage22：official 图谱中的查询种子邻域",
        "这里只展示 include/exclude 实体及其高关联一跳邻居；绿色边框是主动前置实体，红色边框是被抑制的高噪声/异常实体。",
        y=-760,
    )

    net.add_node(
        "include_hub",
        label=f"前置实体\n{len(include_entities)} 个",
        title="include entity：查询层显式加入，用来提高相关证据召回。",
        x=-430,
        y=-520,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": "#2ecc71", "border": "#145a32"},
        font={"color": "#ffffff", "size": 18, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 150, "maximum": 180},
        heightConstraint={"minimum": 70},
        size=35,
    )
    net.add_node(
        "exclude_hub",
        label=f"抑制实体\n{len(exclude_entities)} 个",
        title="exclude entity：查询层显式排除，用来减少异常簇、泛化实体和噪声路径。",
        x=430,
        y=-520,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": "#e74c3c", "border": "#922b21"},
        font={"color": "#ffffff", "size": 18, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 150, "maximum": 180},
        heightConstraint={"minimum": 70},
        size=35,
    )

    for _, row in entities.iterrows():
        title = str(row["title"])
        degree = float(row.get("degree", 1) or 1)
        frequency = float(row.get("frequency", 1) or 1)
        is_include = title in include_entities
        is_exclude = title in exclude_entities

        background = "#ecf0f1"
        border = "#95a5a6"
        font_color = "#2d3436"
        if is_include and is_exclude:
            background, border, font_color = "#f39c12", "#7d6608", "#ffffff"
        elif is_include:
            background, border, font_color = "#2ecc71", "#145a32", "#ffffff"
        elif is_exclude:
            background, border, font_color = "#e74c3c", "#922b21", "#ffffff"
        elif degree >= 30:
            background, border = "#d6eaf8", "#2980b9"

        node_size = min(35, 10 + degree * 0.45 + frequency * 1.5)
        x, y = node_positions.get(title, (0.0, 0.0))
        net.add_node(
            title,
            label=title[:28],
            title=(
                f"<b>{html.escape(title)}</b><br>"
                f"type={html.escape(str(row.get('type', '')))}<br>"
                f"degree={degree:.0f}，frequency={frequency:.0f}<br>"
                f"include={is_include}，exclude={is_exclude}<br>"
                f"说明：绿色表示提高召回的种子，红色表示被抑制的噪声/异常实体。"
            ),
            x=x,
            y=y,
            fixed=True,
            physics=False,
            shape="dot",
            color={"background": background, "border": border},
            borderWidth=4 if (is_include or is_exclude) else 1,
            font={"color": font_color, "size": 14, "face": "Microsoft YaHei"},
            size=node_size,
        )

        if is_include:
            net.add_edge("include_hub", title, color="#27ae60", width=2, dashes=True)
        if is_exclude:
            net.add_edge("exclude_hub", title, color="#c0392b", width=2, dashes=True)

    for _, row in relationships.iterrows():
        source = str(row["source"])
        target = str(row["target"])
        if source not in set(entities["title"]) or target not in set(entities["title"]):
            continue
        touches_excluded = source in exclude_entities or target in exclude_entities
        touches_included = source in include_entities or target in include_entities
        color = "#c0392b" if touches_excluded else "#95a5a6"
        width = 2.4 if touches_included or touches_excluded else 0.8
        net.add_edge(
            source,
            target,
            color=color,
            width=width,
            title=(
                f"{html.escape(source)} -> {html.escape(target)}<br>"
                f"weight={float(row.get('weight', 0.0) or 0.0):.4f}<br>"
                f"combined_degree={row.get('combined_degree', '')}"
            ),
        )

    path = OUTPUT_DIR / "04_图谱_Stage22_查询种子与异常实体.html"
    return _save(
        net,
        path,
        "Stage22 official 图谱与查询种子",
        [
            "数据来源：stage10_debug50_poisoned_query_ready/output/entities.parquet、relationships.parquet 与 stage22 query seed plan。",
            "绿色实体是 full_query_guard 显式 include 的查询种子；红色实体是显式 exclude 的异常或泛化实体。",
            "为便于展示，本页只保留 include/exclude 实体及其高关联一跳邻居，不代表完整 official 图谱规模。",
            "这张图适合解释：LogicGuard 接入 official 查询层时，并不是直接改 GraphRAG 索引，而是在查询上下文构建阶段控制实体入口。",
        ],
    )


def build_project_flow() -> Path:
    """Create a high-level system flow diagram for non-specialist readers."""
    steps = [
        ("原始数据集", "2Wiki / HotpotQA / MuSiQue 等多跳问答语料", "#dbeafe"),
        ("LogicPoison 攻击语料", "将关键事实改写为污染版本，形成 poisoned corpus", "#fee2e2"),
        ("RAG / GraphRAG 索引", "BM25、轻量图检索、official GraphRAG local context", "#ede9fe"),
        ("查询与证据召回", "从文档、实体、关系和 sources 中构建上下文", "#e0f2fe"),
        ("LogicGuard Guard", "识别 changed / abnormal / risky context 并过滤", "#fef3c7"),
        ("Recovery", "用可信候选或干净参考替换被过滤的关键证据", "#dcfce7"),
        ("LLM 回答与 Judge", "评估正确性、拒答、污染输出和证据质量", "#f3f4f6"),
    ]
    cards = []
    for index, (title, desc, color) in enumerate(steps):
        arrow = '<div class="arrow">→</div>' if index < len(steps) - 1 else ""
        cards.append(
            f"""
            <div class="flow-card" style="background:{color}">
              <div class="step-num">{index + 1}</div>
              <h2>{html.escape(title)}</h2>
              <p>{html.escape(desc)}</p>
            </div>
            {arrow}
            """
        )
    body = f"""
    <section class="flow-wrap">
      {''.join(cards)}
    </section>
    <section class="explain">
      <h2>这张图想表达什么</h2>
      <p>
        本项目不是单独研究一个检索器，而是研究“污染语料进入 RAG/GraphRAG 后，如何在检索上下文层阻断错误事实，并尽量恢复正确证据”。
        因此主线必须同时看三件事：污染是否进入上下文、正确证据是否还在、最终回答是否可用。
      </p>
    </section>
    """
    style = """
    .flow-wrap {
      display: flex;
      flex-wrap: wrap;
      align-items: stretch;
      gap: 14px;
      margin-top: 24px;
    }
    .flow-card {
      position: relative;
      width: 220px;
      min-height: 170px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 18px 16px 16px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.07);
    }
    .flow-card h2 {
      margin: 10px 0 8px;
      font-size: 19px;
      color: #102a43;
    }
    .flow-card p {
      margin: 0;
      line-height: 1.65;
      color: #334155;
      font-size: 14px;
    }
    .step-num {
      width: 30px;
      height: 30px;
      border-radius: 50%;
      background: #102a43;
      color: #fff;
      display: grid;
      place-items: center;
      font-weight: 700;
    }
    .arrow {
      display: grid;
      place-items: center;
      font-size: 34px;
      color: #64748b;
      min-width: 22px;
    }
    .explain {
      margin-top: 28px;
      padding: 20px;
      border-left: 5px solid #2f80ed;
      background: #eef6ff;
      border-radius: 8px;
    }
    .explain h2 { margin: 0 0 8px; font-size: 20px; }
    .explain p { margin: 0; line-height: 1.8; color: #334155; }
    """
    return _save_static_html(
        OUTPUT_DIR / "05_总流程_LogicGuard攻防流程.html",
        "LogicGuard 项目攻防流程总览",
        [
            "这张图用于向读者解释项目整体流程：语料污染如何进入 RAG/GraphRAG，以及 LogicGuard 在哪里介入。",
            "它不是实验结果图，而是系统结构图，适合放在汇报或论文方法部分开头。",
        ],
        body,
        style,
    )


def build_stage_roadmap() -> Path:
    """Create a stage timeline that explains how the project reached Stage22."""
    stages = [
        ("阶段 1", "调研与方法设想", "围绕 RAG / GraphRAG 安全、LogicPoison、KG-RAG 攻击防御形成初步路线。"),
        ("阶段 2", "基础环境与数据集", "使用 uv 管理 Python 环境，整理 2Wiki、HotpotQA、MuSiQue 和 LogicPoison 语料。"),
        ("阶段 3", "早期模拟攻击", "实现 Entity Swap、Bridge Injection、BridgeV2，验证污染事实能影响回答。"),
        ("阶段 4", "检索层防御", "做多数据集召回、暴露、消融实验，发现单纯 Guard 会牺牲可用性。"),
        ("阶段 5", "LogicPoison 接入", "把外部 poisoned corpus 接入 LogicGuard，验证真实污染语料下的防御表现。"),
        ("阶段 6", "GraphRAG 接入", "跑通 Microsoft GraphRAG minimal / local context，定位 official workflow 的约束。"),
        ("阶段 7", "Stage21 50-query", "证明 Recovery 能在 top10 下保持 gold_recall=0.8050，同时 changed_exposure=0。"),
        ("阶段 8", "Stage22 official query layer", "证明 full_query_guard 能控制 official 查询层，gold_recall=0.9000，但还缺 sources 级 recovery。"),
    ]
    items = []
    for index, (phase, title, desc) in enumerate(stages):
        active = " active" if index >= 6 else ""
        items.append(
            f"""
            <div class="stage{active}">
              <div class="badge">{html.escape(phase)}</div>
              <h2>{html.escape(title)}</h2>
              <p>{html.escape(desc)}</p>
            </div>
            """
        )
    body = f"""
    <section class="timeline">
      {''.join(items)}
    </section>
    <section class="current">
      <h2>当前定位</h2>
      <p>
        项目已经完成“污染可造成风险”“Guard 可降低风险”“Recovery 可恢复可用性”“official 查询层可控”四个核心证明。
        当前缺口是把 Recovery 真正接到 official GraphRAG sources 后处理，再扩展到更大 query 数和 answer-level LLM 评估。
      </p>
    </section>
    """
    style = """
    .timeline {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-top: 22px;
    }
    .stage {
      background: #fff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 18px;
      min-height: 168px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
    }
    .stage.active {
      border-color: #2f80ed;
      background: #eef6ff;
    }
    .badge {
      display: inline-block;
      padding: 4px 9px;
      border-radius: 999px;
      background: #102a43;
      color: #fff;
      font-size: 13px;
      font-weight: 700;
    }
    .stage h2 { margin: 12px 0 8px; font-size: 20px; color: #102a43; }
    .stage p { margin: 0; line-height: 1.75; color: #52606d; }
    .current {
      margin-top: 26px;
      padding: 20px;
      background: #f0fdf4;
      border-left: 5px solid #22c55e;
      border-radius: 8px;
    }
    .current h2 { margin: 0 0 8px; font-size: 20px; }
    .current p { margin: 0; line-height: 1.8; color: #334155; }
    """
    return _save_static_html(
        OUTPUT_DIR / "06_路线图_项目阶段与当前进度.html",
        "项目阶段路线图",
        [
            "这张图用于解释项目从早期模拟到 official GraphRAG 查询层实验的推进过程。",
            "蓝色高亮阶段表示当前最能支撑论文主线的实验资产。",
        ],
        body,
        style,
    )


def build_stage21_safety_utility_tradeoff() -> Path:
    """Plot Stage21 recall versus poisoned evidence exposure."""
    df = pd.read_csv(STAGE21_SUMMARY)
    df = df[(df["top_k"] == 10) & (df["method"].isin([
        "poisoned_bm25",
        "guarded_filter",
        "recovered_by_doc_id",
        "clean_bm25_reference",
    ]))]
    width, height = 980, 640
    left, right, top, bottom = 95, 55, 70, 90
    plot_w, plot_h = width - left - right, height - top - bottom
    colors = {
        "poisoned_bm25": "#e74c3c",
        "guarded_filter": "#f39c12",
        "recovered_by_doc_id": "#2ecc71",
        "clean_bm25_reference": "#3498db",
    }

    def sx(v: float) -> float:
        return left + v * plot_w

    def sy(v: float) -> float:
        return top + (1.0 - v) * plot_h

    points = []
    for _, row in df.iterrows():
        method = row["method"]
        exposure = float(row["avg_changed_doc_exposure_at_k"])
        recall = float(row["avg_gold_recall_at_k"])
        points.append(
            f"""
            <g>
              <circle cx="{sx(exposure):.1f}" cy="{sy(recall):.1f}" r="18"
                      fill="{colors[method]}" stroke="#102a43" stroke-width="2"/>
              <text x="{sx(exposure) + 26:.1f}" y="{sy(recall) - 6:.1f}" class="label">{html.escape(METHOD_LABELS[method])}</text>
              <text x="{sx(exposure) + 26:.1f}" y="{sy(recall) + 16:.1f}" class="small">召回 {recall:.3f} / 暴露 {exposure:.3f}</text>
            </g>
            """
        )
    grid = []
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        grid.append(f'<line x1="{sx(tick):.1f}" y1="{top}" x2="{sx(tick):.1f}" y2="{height-bottom}" class="grid"/>')
        grid.append(f'<text x="{sx(tick):.1f}" y="{height-bottom+28}" class="tick" text-anchor="middle">{tick:.2f}</text>')
        grid.append(f'<line x1="{left}" y1="{sy(tick):.1f}" x2="{width-right}" y2="{sy(tick):.1f}" class="grid"/>')
        grid.append(f'<text x="{left-18}" y="{sy(tick)+5:.1f}" class="tick" text-anchor="end">{tick:.2f}</text>')

    svg = f"""
    <svg viewBox="0 0 {width} {height}" class="chart">
      <rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>
      <rect x="{left}" y="{top}" width="{plot_w*0.18:.1f}" height="{plot_h*0.25:.1f}" fill="#dcfce7" opacity="0.85"/>
      <text x="{left+16}" y="{top+28}" class="ideal">理想区：低污染暴露 + 高证据召回</text>
      {''.join(grid)}
      <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis"/>
      <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis"/>
      <text x="{width/2}" y="{height-28}" class="axis-label" text-anchor="middle">污染证据暴露 changed_doc_exposure，越低越安全</text>
      <text x="28" y="{height/2}" class="axis-label" text-anchor="middle" transform="rotate(-90 28 {height/2})">正确证据召回 gold_recall，越高越可用</text>
      {''.join(points)}
    </svg>
    """
    body = f"""
    <section class="chart-wrap">{svg}</section>
    <section class="takeaway">
      <b>读图结论：</b>
      `poisoned_bm25` 在右上角，说明召回高但污染暴露也高；
      `guarded_filter` 在左下角，说明安全但不可用；
      `recovered_by_doc_id` 靠近左上角，说明当前最接近“安全且可用”的目标。
    </section>
    """
    return _save_static_html(
        OUTPUT_DIR / "07_权衡图_Stage21安全性与可用性.html",
        "Stage21 安全性-可用性权衡图",
        [
            "横轴越低越安全，纵轴越高越可用。",
            "这张图用于一眼说明 LogicGuard 的核心价值：Recovery 把系统从“安全但拒答”拉回到“安全且有召回”。",
        ],
        body,
        _chart_style(),
    )


def build_stage21_recovery_effect() -> Path:
    """Show how recovery restores evidence after the guard removes changed docs."""
    df = pd.read_csv(STAGE21_SUMMARY)
    df = df[(df["top_k"] == 10) & (df["method"].isin([
        "poisoned_bm25",
        "guarded_filter",
        "recovered_by_doc_id",
        "clean_bm25_reference",
    ]))]
    ordered = ["poisoned_bm25", "guarded_filter", "recovered_by_doc_id", "clean_bm25_reference"]
    rows = {row["method"]: row for _, row in df.iterrows()}
    max_count = 10.0
    width, height = 1040, 560
    group_w = 220
    base_y = 430
    cards = []
    for i, method in enumerate(ordered):
        row = rows[method]
        x = 90 + i * 240
        changed = float(row["avg_changed_evidence_count"])
        recovered = float(row["avg_recovered_evidence_count"])
        empty = float(row["empty_context_rate"])
        changed_h = changed / max_count * 260
        recovered_h = recovered / max_count * 260
        cards.append(
            f"""
            <g>
              <rect x="{x}" y="70" width="{group_w}" height="390" rx="8" fill="#ffffff" stroke="#d9e2ec"/>
              <text x="{x+group_w/2}" y="102" text-anchor="middle" class="label">{html.escape(METHOD_LABELS[method])}</text>
              <rect x="{x+48}" y="{base_y-changed_h:.1f}" width="48" height="{changed_h:.1f}" fill="#e74c3c" rx="5"/>
              <rect x="{x+124}" y="{base_y-recovered_h:.1f}" width="48" height="{recovered_h:.1f}" fill="#2ecc71" rx="5"/>
              <text x="{x+72}" y="{base_y-changed_h-10:.1f}" text-anchor="middle" class="small">{changed:.2f}</text>
              <text x="{x+148}" y="{base_y-recovered_h-10:.1f}" text-anchor="middle" class="small">{recovered:.2f}</text>
              <text x="{x+72}" y="{base_y+28}" text-anchor="middle" class="tick">污染证据</text>
              <text x="{x+148}" y="{base_y+28}" text-anchor="middle" class="tick">恢复证据</text>
              <text x="{x+group_w/2}" y="148" text-anchor="middle" class="small">召回 {float(row['avg_gold_recall_at_k']):.3f}</text>
              <text x="{x+group_w/2}" y="172" text-anchor="middle" class="small">污染暴露 {float(row['avg_changed_doc_exposure_at_k']):.3f}</text>
              <text x="{x+group_w/2}" y="196" text-anchor="middle" class="small">空上下文 {empty:.3f}</text>
            </g>
            """
        )
        if i < len(ordered) - 1:
            cards.append(f'<path d="M{x+group_w+14} 255 L{x+group_w+54} 255" stroke="#64748b" stroke-width="3" marker-end="url(#arrow)"/>')
    svg = f"""
    <svg viewBox="0 0 {width} {height}" class="chart">
      <defs>
        <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
          <path d="M0,0 L0,6 L9,3 z" fill="#64748b"/>
        </marker>
      </defs>
      {''.join(cards)}
      <rect x="92" y="502" width="18" height="18" fill="#e74c3c" rx="3"/>
      <text x="120" y="517" class="tick">平均污染证据数，越低越好</text>
      <rect x="330" y="502" width="18" height="18" fill="#2ecc71" rx="3"/>
      <text x="358" y="517" class="tick">平均恢复证据数，表示 Recovery 补回的证据规模</text>
    </svg>
    """
    body = f"""
    <section class="chart-wrap">{svg}</section>
    <section class="takeaway">
      <b>读图结论：</b>
      污染检索 top10 平均暴露 9.56 个 changed evidence；
      Guard 将污染证据清零，但空上下文率升到 0.72；
      Recovery 平均补回 9.62 个证据，同时保持 changed exposure 为 0。
    </section>
    """
    return _save_static_html(
        OUTPUT_DIR / "08_恢复图_Stage21证据替换效果.html",
        "Stage21 Recovery 证据替换效果",
        [
            "这张图解释 Recovery 为什么是当前方法的关键组件。",
            "红柱表示污染证据仍在上下文中，绿柱表示被 Recovery 替换回来的证据。",
        ],
        body,
        _chart_style(),
    )


def build_stage22_cost_recall_bubble() -> Path:
    """Plot Stage22 recall, source cost, and changed exposure together."""
    df = pd.read_csv(STAGE22_SUMMARY)
    width, height = 1060, 660
    left, right, top, bottom = 105, 65, 80, 95
    plot_w, plot_h = width - left - right, height - top - bottom
    max_sources = max(100.0, float(df["avg_source_count"].max()) * 1.05)

    def sx(v: float) -> float:
        return left + v / max_sources * plot_w

    def sy(v: float) -> float:
        return top + (1.0 - v) * plot_h

    grid = []
    for tick in [0, 25, 50, 75, 100]:
        grid.append(f'<line x1="{sx(tick):.1f}" y1="{top}" x2="{sx(tick):.1f}" y2="{height-bottom}" class="grid"/>')
        grid.append(f'<text x="{sx(tick):.1f}" y="{height-bottom+28}" class="tick" text-anchor="middle">{tick}</text>')
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        grid.append(f'<line x1="{left}" y1="{sy(tick):.1f}" x2="{width-right}" y2="{sy(tick):.1f}" class="grid"/>')
        grid.append(f'<text x="{left-18}" y="{sy(tick)+5:.1f}" class="tick" text-anchor="end">{tick:.2f}</text>')

    points = []
    for _, row in df.iterrows():
        method = row["method"]
        recall = float(row["avg_gold_support_recall"])
        exposure = float(row["avg_changed_support_exposure"])
        sources = float(row["avg_source_count"])
        radius = 11 + exposure * 18
        color = _exposure_color(exposure)
        points.append(
            f"""
            <g>
              <circle cx="{sx(sources):.1f}" cy="{sy(recall):.1f}" r="{radius:.1f}" fill="{color}" stroke="#102a43" stroke-width="2" opacity="0.9"/>
              <text x="{sx(sources)+radius+8:.1f}" y="{sy(recall)-4:.1f}" class="label">{html.escape(METHOD_LABELS[method])}</text>
              <text x="{sx(sources)+radius+8:.1f}" y="{sy(recall)+17:.1f}" class="small">sources {sources:.1f} / 暴露 {exposure:.1f}</text>
            </g>
            """
        )
    svg = f"""
    <svg viewBox="0 0 {width} {height}" class="chart">
      <rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>
      <rect x="{left}" y="{top}" width="{plot_w*0.35:.1f}" height="{plot_h*0.20:.1f}" fill="#dcfce7" opacity="0.8"/>
      <text x="{left+16}" y="{top+28}" class="ideal">理想区：少 sources + 高召回 + 低污染暴露</text>
      {''.join(grid)}
      <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis"/>
      <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis"/>
      <text x="{width/2}" y="{height-30}" class="axis-label" text-anchor="middle">平均 source 数，越低越精简</text>
      <text x="28" y="{height/2}" class="axis-label" text-anchor="middle" transform="rotate(-90 28 {height/2})">gold support recall，越高越好</text>
      {''.join(points)}
      <text x="{width-250}" y="48" class="small">气泡越大/越红：污染暴露越高</text>
    </svg>
    """
    body = f"""
    <section class="chart-wrap">{svg}</section>
    <section class="takeaway">
      <b>读图结论：</b>
      budget_expansion 召回最高但 sources 接近 96，代价过大；
      full_query_guard 在 sources 约 25.8 时达到 0.90 召回，更可控；
      但气泡仍偏红，说明 official sources 级 recovery 还没有完成。
    </section>
    """
    return _save_static_html(
        OUTPUT_DIR / "09_气泡图_Stage22官方GraphRAG召回成本.html",
        "Stage22 official GraphRAG 召回-成本-暴露气泡图",
        [
            "横轴是平均上下文来源数，纵轴是正确证据召回，气泡大小和颜色表示污染暴露。",
            "这张图用于解释 Stage22 的真实意义：查询层可控，但还不是最终防御闭环。",
        ],
        body,
        _chart_style(),
    )


def build_stage22_query_heatmap() -> Path:
    """Create a per-query heatmap for Stage22 methods."""
    df = pd.read_csv(STAGE22_METRICS)
    methods = [
        "mixed_baseline",
        "budget_expansion",
        "all_entities_baseline",
        "title_seeding",
        "entity_rerank",
        "cluster_suppression",
        "full_query_guard",
    ]
    queries = (
        df[["query_id", "query"]]
        .drop_duplicates()
        .reset_index(drop=True)
        .to_dict("records")
    )
    width = 250 + len(methods) * 150
    row_h = 86
    height = 95 + len(queries) * row_h + 60
    cells = []
    for col, method in enumerate(methods):
        x = 250 + col * 150
        cells.append(f'<text x="{x+75}" y="55" text-anchor="middle" class="small">{html.escape(METHOD_LABELS[method])}</text>')
    for row_i, query_info in enumerate(queries):
        y = 82 + row_i * row_h
        q_label = f"Q{row_i+1}: {_short_text(query_info['query'], 34)}"
        cells.append(f'<text x="20" y="{y+31}" class="query-label">{html.escape(q_label)}</text>')
        qdf = df[df["query_id"] == query_info["query_id"]].set_index("method")
        for col, method in enumerate(methods):
            item = qdf.loc[method]
            recall = float(item["gold_support_recall"])
            exposure = float(item["changed_support_exposure"])
            sources = int(item["source_count"])
            x = 250 + col * 150
            color = _recall_color(recall)
            stroke = _exposure_color(exposure)
            cells.append(
                f"""
                <g>
                  <rect x="{x+5}" y="{y}" width="140" height="70" rx="6" fill="{color}" stroke="{stroke}" stroke-width="{2 + exposure*4:.1f}"/>
                  <text x="{x+75}" y="{y+25}" text-anchor="middle" class="cell-text">R {recall:.1f} / E {exposure:.1f}</text>
                  <text x="{x+75}" y="{y+49}" text-anchor="middle" class="cell-small">sources {sources}</text>
                </g>
                """
            )
    svg = f"""
    <svg viewBox="0 0 {width} {height}" class="chart wide-chart">
      <text x="20" y="55" class="axis-label">查询</text>
      {''.join(cells)}
    </svg>
    """
    body = f"""
    <section class="scroll-wrap">{svg}</section>
    <section class="legend-row">
      <span><b>R</b> = gold support recall，越高越好。</span>
      <span><b>E</b> = changed support exposure，越低越安全。</span>
      <span>单元格底色越绿召回越高，边框越红污染暴露越高。</span>
    </section>
    """
    style = _chart_style() + """
    .scroll-wrap { overflow-x: auto; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
    .wide-chart { min-width: 1280px; display: block; }
    .query-label { font-size: 14px; fill: #102a43; font-weight: 700; }
    .cell-text { font-size: 14px; fill: #102a43; font-weight: 700; }
    .cell-small { font-size: 12px; fill: #334155; }
    .legend-row { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 16px; color: #52606d; line-height: 1.7; }
    """
    return _save_static_html(
        OUTPUT_DIR / "10_热力图_Stage22查询级表现.html",
        "Stage22 查询级表现热力图",
        [
            "这张图把平均数拆成每个 query 的表现，帮助观察 full_query_guard 是否稳定。",
            "它也能暴露失败点：某些方法在个别 query 上召回为 0，说明 official 查询层仍存在样本差异。",
        ],
        body,
        style,
    )


def build_stage22_query_entity_source_graph() -> Path:
    """Show one official full-query-guard context as entity-to-source graph."""
    ctx = next(_jsonl(ROOT / "outputs" / "ms_graphrag_query" / "stage22_poisoned5_query_guard_contexts_full_query_guard.jsonl"))
    metrics = pd.read_csv(STAGE22_METRICS)
    metric = metrics[(metrics["query_id"] == ctx["query_id"]) & (metrics["method"] == "full_query_guard")].iloc[0]
    support_ids = set(_split_ids(metric["support_doc_ids"]))
    changed_ids = set(_split_ids(metric["changed_support_doc_ids"]))
    gold_hit_ids = set(_split_ids(metric["gold_support_hit_ids"]))

    include = set(ctx.get("include_entity_names", []))
    exclude = set(ctx.get("exclude_entity_names", []))
    context_entities = [str(item.get("entity", "")) for item in ctx["context_data"].get("entities", [])]
    sources = ctx["context_data"].get("sources", [])
    ordered_sources = sorted(
        sources,
        key=lambda s: (
            str(s.get("logicguard_doc_id", "")) not in support_ids,
            str(s.get("logicguard_doc_id", "")),
        ),
    )[:18]

    net = _network("1250px", physics=False)
    _add_page_title_node(
        net,
        "单问题：FullQueryGuard 实体到证据网络",
        "展示 Atomised 问题在 official context 中选择了哪些实体，以及这些实体连接到了哪些 sources 文档。",
        y=-710,
    )
    net.add_node(
        "query",
        label=f"问题\n{_short_text(ctx['query'], 80)}",
        title=ctx["query"],
        x=0,
        y=-560,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": "#eef6ff", "border": "#2f80ed"},
        font={"color": "#102a43", "size": 18, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 760, "maximum": 860},
        heightConstraint={"minimum": 80},
    )
    net.add_node("include_hub", label="include\n前置实体", x=-520, y=-405, fixed=True, physics=False, shape="box", color="#2ecc71", font={"color": "#ffffff"})
    net.add_node("exclude_hub", label="exclude\n抑制实体", x=520, y=-405, fixed=True, physics=False, shape="box", color="#e74c3c", font={"color": "#ffffff"})
    net.add_edge("query", "include_hub", color="#27ae60", arrows="to")
    net.add_edge("query", "exclude_hub", color="#c0392b", arrows="to")

    positions = _context_entity_positions(context_entities, include, exclude)
    for entity in context_entities:
        is_include = entity in include
        is_exclude = entity in exclude
        if is_include and is_exclude:
            color = "#f39c12"
        elif is_include:
            color = "#2ecc71"
        elif is_exclude:
            color = "#e74c3c"
        else:
            color = "#dbeafe"
        x, y = positions[entity]
        net.add_node(entity, label=entity[:26], title=f"entity={entity}<br>include={is_include}<br>exclude={is_exclude}", x=x, y=y, fixed=True, physics=False, shape="dot", color=color, size=20)
        if is_include:
            net.add_edge("include_hub", entity, color="#27ae60", width=2, dashes=True)
        if is_exclude:
            net.add_edge("exclude_hub", entity, color="#c0392b", width=2, dashes=True)

    for index, source in enumerate(ordered_sources):
        doc_id = str(source.get("logicguard_doc_id", ""))
        title = str(source.get("title", ""))
        x = -840 + (index % 6) * 335
        y = 230 + (index // 6) * 115
        is_support = doc_id in support_ids
        is_changed = doc_id in changed_ids
        is_gold_hit = doc_id in gold_hit_ids
        background = "#fee2e2" if is_changed else "#f8fafc"
        border = "#f1c40f" if is_gold_hit else ("#e74c3c" if is_changed else "#94a3b8")
        net.add_node(
            f"src_{doc_id}_{index}",
            label=f"{doc_id} {title[:28]}",
            title=f"doc_id={doc_id}<br>title={html.escape(title)}<br>support={is_support}<br>changed={is_changed}<br>{html.escape(str(source.get('text',''))[:260])}",
            x=x,
            y=y,
            fixed=True,
            physics=False,
            shape="box",
            color={"background": background, "border": border},
            borderWidth=4 if is_gold_hit else 2,
            font={"color": "#102a43", "size": 13, "face": "Microsoft YaHei"},
            widthConstraint={"minimum": 260, "maximum": 300},
        )
        text_lower = str(source.get("text", "")).lower()
        linked = 0
        for entity in context_entities:
            if entity.lower() in text_lower:
                net.add_edge(entity, f"src_{doc_id}_{index}", color="#94a3b8", width=1.2, arrows="to")
                linked += 1
                if linked >= 4:
                    break

    for rel in ctx["context_data"].get("relationships", [])[:70]:
        source = str(rel.get("source", ""))
        target = str(rel.get("target", ""))
        if source in context_entities and target in context_entities:
            net.add_edge(source, target, color="#cbd5e1", width=0.8, title=f"{source} -> {target}")

    return _save(
        net,
        OUTPUT_DIR / "11_实体图_单问题实体到证据网络.html",
        "单问题 FullQueryGuard 实体到证据网络",
        [
            "绿色实体来自 include，红色实体来自 exclude；下方是 official context sources。",
            "黄色边框 source 表示命中 gold support；浅红 source 表示该文档属于 changed support。",
        ],
    )


def build_stage22_query_seed_network() -> Path:
    """Show which include/exclude entities are shared by the five Stage22 queries."""
    plans = list(_jsonl(STAGE22_SEED_PLAN))
    include_entities: set[str] = set()
    exclude_entities: set[str] = set()
    for plan in plans:
        method = plan["methods"]["full_query_guard"]
        include_entities.update(method.get("include_entity_names", []))
        exclude_entities.update(method.get("exclude_entity_names", []))
    both = include_entities & exclude_entities
    include_only = sorted(include_entities - both)
    exclude_only = sorted(exclude_entities - both)
    both_only = sorted(both)

    net = _network("1100px", physics=False)
    _add_page_title_node(
        net,
        "5 个查询的 include / exclude 实体种子网络",
        "这张图展示不同 query 共享或冲突使用了哪些实体种子，用于判断种子选择是否过于全局化。",
        y=-650,
    )

    for i, plan in enumerate(plans):
        qid = f"Q{i+1}"
        y = -410 + i * 150
        net.add_node(qid, label=f"{qid}\n{_short_text(plan['query'], 42)}", title=plan["query"], x=-760, y=y, fixed=True, physics=False, shape="box", color={"background": "#eef6ff", "border": "#2f80ed"}, font={"color": "#102a43", "size": 14})

    entity_positions: dict[str, tuple[float, float]] = {}
    for idx, name in enumerate(include_only):
        entity_positions[name] = (-240 + (idx % 3) * 170, -460 + (idx // 3) * 95)
    for idx, name in enumerate(both_only):
        entity_positions[name] = (260, -120 + idx * 110)
    for idx, name in enumerate(exclude_only):
        entity_positions[name] = (520 + (idx % 3) * 170, -460 + (idx // 3) * 95)

    for name, (x, y) in entity_positions.items():
        if name in both:
            color = "#f39c12"
            role = "include 与 exclude 均出现"
        elif name in include_entities:
            color = "#2ecc71"
            role = "include"
        else:
            color = "#e74c3c"
            role = "exclude"
        net.add_node(name, label=name[:24], title=f"{name}<br>{role}", x=x, y=y, fixed=True, physics=False, shape="dot", color=color, size=20)

    for i, plan in enumerate(plans):
        qid = f"Q{i+1}"
        method = plan["methods"]["full_query_guard"]
        for name in method.get("include_entity_names", []):
            if name in entity_positions:
                net.add_edge(qid, name, color="#27ae60", width=2, arrows="to")
        for name in method.get("exclude_entity_names", []):
            if name in entity_positions:
                net.add_edge(qid, name, color="#c0392b", width=2, dashes=True, arrows="to")

    return _save(
        net,
        OUTPUT_DIR / "12_实体图_五问题种子实体网络.html",
        "Stage22 五问题种子实体网络",
        [
            "左侧是 5 个 query，右侧是 full_query_guard 使用的 include/exclude 实体。",
            "橙色实体说明它在不同 query 中角色冲突，后续应做 query-specific 判断。",
        ],
    )


def build_stage22_anomaly_entity_network() -> Path:
    """Create an entity graph focused only on anomalous/excluded entities."""
    entities = pd.read_parquet(STAGE22_WORKSPACE / "entities.parquet")
    relationships = pd.read_parquet(STAGE22_WORKSPACE / "relationships.parquet")
    exclude_entities: set[str] = set()
    for row in _jsonl(STAGE22_SEED_PLAN):
        exclude_entities.update(row["methods"]["full_query_guard"].get("exclude_entity_names", []))
    exclude_entities &= set(str(x) for x in entities["title"])

    degree = {str(row["title"]): float(row.get("degree", 0) or 0) for _, row in entities.iterrows()}
    related = set(exclude_entities)
    for _, rel in relationships.iterrows():
        source = str(rel["source"])
        target = str(rel["target"])
        if source in exclude_entities or target in exclude_entities:
            related.add(source)
            related.add(target)
    selected = set(exclude_entities)
    for name in sorted(related - exclude_entities, key=lambda x: (-degree.get(x, 0), x)):
        if len(selected) >= 55:
            break
        selected.add(name)

    net = _network("1050px", physics=False)
    _add_page_title_node(
        net,
        "异常实体抑制网络",
        "红色节点是 full_query_guard 抑制的异常/泛化实体，灰蓝节点是它们的一跳高连接邻居。",
        y=-600,
    )
    net.add_node("anomaly_hub", label=f"异常实体\n{len(exclude_entities)} 个", x=0, y=-430, fixed=True, physics=False, shape="box", color={"background": "#e74c3c", "border": "#922b21"}, font={"color": "#ffffff", "size": 18})

    exclude_sorted = sorted(exclude_entities, key=lambda x: (-degree.get(x, 0), x))
    for i, name in enumerate(exclude_sorted):
        angle = 2 * math.pi * i / max(1, len(exclude_sorted))
        x = math.cos(angle) * 360
        y = -110 + math.sin(angle) * 220
        net.add_node(name, label=name[:24], title=f"{name}<br>degree={degree.get(name,0):.0f}<br>exclude=True", x=x, y=y, fixed=True, physics=False, shape="dot", color="#e74c3c", size=22)
        net.add_edge("anomaly_hub", name, color="#c0392b", dashes=True, width=2)

    neighbors = sorted(selected - exclude_entities, key=lambda x: (-degree.get(x, 0), x))
    for i, name in enumerate(neighbors):
        x = -780 + (i % 7) * 260
        y = 270 + (i // 7) * 95
        net.add_node(name, label=name[:24], title=f"{name}<br>degree={degree.get(name,0):.0f}", x=x, y=y, fixed=True, physics=False, shape="dot", color="#dbeafe", size=min(28, 11 + degree.get(name, 0) * 0.35))

    for _, rel in relationships.iterrows():
        source = str(rel["source"])
        target = str(rel["target"])
        if source in selected and target in selected and (source in exclude_entities or target in exclude_entities):
            net.add_edge(source, target, color="#94a3b8", width=1.2, title=f"{source} -> {target}")

    return _save(
        net,
        OUTPUT_DIR / "13_实体图_异常实体抑制网络.html",
        "Stage22 异常实体抑制网络",
        [
            "这张图专门解释 exclude 机制：哪些实体被判定为异常/泛化入口，以及它们连接到哪些邻居。",
            "它可以辅助分析为什么某些实体需要被 query-layer suppression 压制。",
        ],
    )


def build_index(files: list[Path]) -> Path:
    """Create a small Chinese index page for quick navigation."""
    descriptions = {
        "01_总览_Stage21_50问防御效果.html": (
            "Stage21 50 个问题的核心防御结果：Guard 清零污染暴露但损害召回，Recovery 兼顾召回和安全。"
        ),
        "02_样例_Atomised问题_证据流.html": (
            "单个问题的证据级解释：可以看到污染证据如何被过滤，以及 Recovery 如何用干净参考补回。"
        ),
        "03_对比_Stage22_官方GraphRAG查询层.html": (
            "official GraphRAG 查询层方法对比：说明 full_query_guard 提高召回，但仍需 sources 级 recovery。"
        ),
        "04_图谱_Stage22_查询种子与异常实体.html": (
            "official 图谱结构与查询种子诊断：绿色是 include 实体，红色是 exclude 异常实体。"
        ),
        "05_总流程_LogicGuard攻防流程.html": (
            "项目总流程图：从原始语料、污染语料、GraphRAG 索引到 Guard、Recovery 和最终评估。"
        ),
        "06_路线图_项目阶段与当前进度.html": (
            "项目阶段路线图：按大阶段梳理已经完成的工作、当前进度和下一步缺口。"
        ),
        "07_权衡图_Stage21安全性与可用性.html": (
            "Stage21 安全性-可用性权衡图：横轴污染暴露，纵轴正确证据召回。"
        ),
        "08_恢复图_Stage21证据替换效果.html": (
            "Stage21 Recovery 替换效果：展示污染证据如何被过滤，以及干净参考如何补回。"
        ),
        "09_气泡图_Stage22官方GraphRAG召回成本.html": (
            "Stage22 official GraphRAG 气泡图：同时展示召回、source 成本和污染暴露。"
        ),
        "10_热力图_Stage22查询级表现.html": (
            "Stage22 查询级热力图：逐 query 对比不同方法的召回、暴露和 source 数。"
        ),
        "11_实体图_单问题实体到证据网络.html": (
            "单问题实体到证据网络：展示 full_query_guard 的实体如何连接到 official sources。"
        ),
        "12_实体图_五问题种子实体网络.html": (
            "五问题种子实体网络：展示不同 query 共享或冲突使用的 include/exclude 实体。"
        ),
        "13_实体图_异常实体抑制网络.html": (
            "异常实体抑制网络：聚焦被 exclude 的异常/泛化实体及其一跳邻居。"
        ),
    }
    cards = []
    for path in files:
        name = path.name
        cards.append(
            f"""
            <a class="card" href="{html.escape(name)}">
              <div class="file">{html.escape(name)}</div>
              <p>{html.escape(descriptions.get(name, "LogicGuard 可视化页面"))}</p>
            </a>
            """
        )

    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>LogicGuard 中文可视化索引</title>
  <style>
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: #1f2933;
      background: #f5f7fb;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 40px 28px 56px;
    }}
    h1 {{ margin: 0 0 10px; font-size: 32px; }}
    .lead {{ color: #52606d; line-height: 1.8; margin-bottom: 28px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 18px;
    }}
    .card {{
      display: block;
      text-decoration: none;
      color: inherit;
      background: #fff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 20px;
      min-height: 150px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }}
    .card:hover {{ border-color: #2f80ed; }}
    .file {{ font-weight: 700; margin-bottom: 12px; color: #102a43; }}
    p {{ line-height: 1.75; margin: 0; color: #52606d; }}
    .note {{
      margin-top: 28px;
      padding: 16px 18px;
      background: #eef6ff;
      border-left: 4px solid #2f80ed;
      border-radius: 6px;
      line-height: 1.8;
    }}
  </style>
</head>
<body>
<main>
  <h1>LogicGuard 中文可视化索引</h1>
  <p class="lead">
    这些页面基于当前最值得展示的 Stage21 和 Stage22 实验结果生成。
    每张图都在页面顶部写明了数据来源、指标含义和应当得出的结论。
  </p>
  <section class="grid">
    {''.join(cards)}
  </section>
  <div class="note">
    阅读顺序建议：先看 01 总览理解总体结论，再看 02 样例理解证据替换机制，
    然后看 03 了解 official GraphRAG 查询层进展，最后看 04 解释实体种子和异常实体控制。
  </div>
</main>
</body>
</html>
"""
    path = OUTPUT_DIR / "00_索引_中文可视化说明.html"
    path.write_text(content, encoding="utf-8")
    return path


def _save_static_html(
    path: Path,
    title: str,
    notes: list[str],
    body: str,
    extra_style: str = "",
) -> Path:
    """Save a standalone Chinese HTML page for non-network visualizations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    notes_html = "".join(f"<li>{html.escape(note)}</li>" for note in notes)
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: #102a43;
      background: #fbfcfd;
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 28px 56px;
    }}
    .lg-header {{
      padding: 20px 26px 16px;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      background: #ffffff;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
    }}
    .lg-header h1 {{
      margin: 0 0 10px;
      font-size: 28px;
      color: #102a43;
    }}
    .lg-header ul {{
      margin: 0;
      padding-left: 20px;
      color: #52606d;
      line-height: 1.75;
      font-size: 14px;
    }}
    {extra_style}
  </style>
</head>
<body>
<main>
  <section class="lg-header">
    <h1>{html.escape(title)}</h1>
    <ul>{notes_html}</ul>
  </section>
  {body}
</main>
</body>
</html>
"""
    path.write_text(content, encoding="utf-8")
    return path


def _chart_style() -> str:
    """Shared SVG chart styling."""
    return """
    .chart-wrap {
      margin-top: 22px;
      background: #ffffff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
    }
    .chart {
      display: block;
      width: 100%;
      height: auto;
    }
    .grid { stroke: #d9e2ec; stroke-width: 1; }
    .axis { stroke: #334155; stroke-width: 2; }
    .axis-label { fill: #102a43; font-size: 15px; font-weight: 700; }
    .label { fill: #102a43; font-size: 15px; font-weight: 700; }
    .small { fill: #52606d; font-size: 13px; }
    .tick { fill: #52606d; font-size: 12px; }
    .ideal { fill: #166534; font-size: 14px; font-weight: 700; }
    .takeaway {
      margin-top: 18px;
      padding: 18px 20px;
      border-left: 5px solid #2f80ed;
      background: #eef6ff;
      border-radius: 8px;
      color: #334155;
      line-height: 1.85;
    }
    """


def _recall_color(value: float) -> str:
    """Green-ish scale for recall heatmaps."""
    if value >= 0.85:
        return "#bbf7d0"
    if value >= 0.50:
        return "#fef3c7"
    if value > 0:
        return "#fed7aa"
    return "#fee2e2"


def _exposure_color(value: float) -> str:
    """Red-ish scale for changed evidence exposure."""
    if value >= 0.85:
        return "#ef4444"
    if value >= 0.50:
        return "#f97316"
    if value > 0:
        return "#facc15"
    return "#22c55e"


def _short_text(text: str, limit: int) -> str:
    """Trim labels while keeping them readable."""
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)] + "…"


def _context_entity_positions(
    entities: list[str],
    include: set[str],
    exclude: set[str],
) -> dict[str, tuple[float, float]]:
    """Stable coordinates for a query-context entity layer."""
    positions: dict[str, tuple[float, float]] = {}
    include_items = [e for e in entities if e in include and e not in exclude]
    exclude_items = [e for e in entities if e in exclude and e not in include]
    both_items = [e for e in entities if e in include and e in exclude]
    other_items = [e for e in entities if e not in include and e not in exclude]

    for i, entity in enumerate(include_items):
        positions[entity] = (-760 + (i % 4) * 160, -270 + (i // 4) * 95)
    for i, entity in enumerate(exclude_items):
        positions[entity] = (260 + (i % 4) * 160, -270 + (i // 4) * 95)
    for i, entity in enumerate(both_items):
        positions[entity] = (-85 + i * 170, -300)
    for i, entity in enumerate(other_items):
        positions[entity] = (-560 + (i % 5) * 280, 20 + (i // 5) * 90)
    return positions


def _seed_graph_positions(
    entities: pd.DataFrame,
    include_entities: set[str],
    exclude_entities: set[str],
) -> dict[str, tuple[float, float]]:
    """Return stable coordinates for the Stage22 seed-neighborhood graph.

    The 04 visualization is meant for explanation, not graph exploration.  A
    deterministic layout is clearer than force-directed physics here because it
    keeps the title, hubs, controlled entities, and ordinary neighbors in
    separate bands.
    """
    degree_by_name = {
        str(row["title"]): float(row.get("degree", 0) or 0)
        for _, row in entities.iterrows()
    }
    names = [str(name) for name in entities["title"]]

    both = [
        name for name in names
        if name in include_entities and name in exclude_entities
    ]
    include_only = [
        name for name in names
        if name in include_entities and name not in exclude_entities
    ]
    exclude_only = [
        name for name in names
        if name in exclude_entities and name not in include_entities
    ]
    regular = [
        name for name in names
        if name not in include_entities and name not in exclude_entities
    ]

    def sort_key(name: str) -> tuple[float, str]:
        return (-degree_by_name.get(name, 0), name)

    positions: dict[str, tuple[float, float]] = {}

    # Nodes that are both include and exclude are intentionally placed between
    # the two hubs because their role depends on the query.
    for index, name in enumerate(sorted(both, key=sort_key)):
        positions[name] = (-95 + index * 190, -430)

    def place_grid(
        items: list[str],
        *,
        x_start: float,
        y_start: float,
        x_gap: float,
        y_gap: float,
        cols: int,
    ) -> None:
        for index, name in enumerate(sorted(items, key=sort_key)):
            col = index % cols
            row = index // cols
            positions[name] = (x_start + col * x_gap, y_start + row * y_gap)

    place_grid(
        include_only,
        x_start=-760,
        y_start=-390,
        x_gap=165,
        y_gap=95,
        cols=4,
    )
    place_grid(
        exclude_only,
        x_start=280,
        y_start=-390,
        x_gap=165,
        y_gap=95,
        cols=4,
    )
    place_grid(
        regular,
        x_start=-840,
        y_start=120,
        x_gap=240,
        y_gap=105,
        cols=8,
    )

    return positions


def _network(height: str, physics: bool) -> Network:
    """Create a PyVis network with consistent project-wide styling."""
    net = Network(
        height=height,
        width="100%",
        bgcolor="#fbfcfd",
        font_color="#1f2933",
        directed=True,
        cdn_resources="remote",
    )
    net.set_options(json.dumps({
        "physics": {
            "enabled": physics,
            "barnesHut": {
                "gravitationalConstant": -5200,
                "springLength": 130,
                "springConstant": 0.035,
            },
            "minVelocity": 0.75,
        },
        "interaction": {
            "hover": True,
            "tooltipDelay": 120,
            "navigationButtons": True,
            "keyboard": True,
        },
        "nodes": {
            "font": {"face": "Microsoft YaHei", "size": 16},
            "shadow": {"enabled": True, "size": 4, "x": 1, "y": 1},
        },
        "edges": {
            "smooth": {"enabled": True, "type": "dynamic"},
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.55}},
        },
    }, ensure_ascii=False))
    return net


def _add_page_title_node(net: Network, title: str, subtitle: str, y: int) -> None:
    """Add a fixed title card inside the graph canvas for screenshots."""
    net.add_node(
        "page_title",
        label=f"{title}\n{subtitle}",
        title=subtitle,
        x=0,
        y=y,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": "#eef6ff", "border": "#2f80ed"},
        font={"color": "#102a43", "size": 21, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 1000, "maximum": 1180},
        heightConstraint={"minimum": 105},
    )


def _add_metric_badge(
    net: Network,
    node_id: str,
    name: str,
    value: str,
    explanation: str,
    x: float,
    y: float,
    color: str,
) -> None:
    """Add a compact metric node with a Chinese tooltip."""
    net.add_node(
        node_id,
        label=f"{name}\n{value}",
        title=f"<b>{html.escape(name)}</b><br>{html.escape(explanation)}",
        x=x,
        y=y,
        fixed=True,
        physics=False,
        shape="box",
        color={"background": color, "border": "#2d3436"},
        font={"color": "#ffffff", "size": 16, "face": "Microsoft YaHei"},
        widthConstraint={"minimum": 130, "maximum": 150},
        heightConstraint={"minimum": 72},
    )


def _save(net: Network, path: Path, title: str, notes: list[str]) -> Path:
    """Save a PyVis page, then inject a Chinese header and legend."""
    path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(path), notebook=False)
    text = path.read_text(encoding="utf-8")

    style = """
<style>
  body {
    margin: 0;
    font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    background: #fbfcfd;
  }
  .lg-header {
    padding: 20px 26px 14px;
    border-bottom: 1px solid #d9e2ec;
    background: #ffffff;
  }
  .lg-header h1 {
    margin: 0 0 8px;
    font-size: 24px;
    color: #102a43;
  }
  .lg-header ul {
    margin: 0;
    padding-left: 20px;
    color: #52606d;
    line-height: 1.75;
    font-size: 14px;
  }
  #mynetwork {
    border: 0 !important;
  }
</style>
"""
    header = (
        '<div class="lg-header">'
        f"<h1>{html.escape(title)}</h1>"
        "<ul>"
        + "".join(f"<li>{html.escape(note)}</li>" for note in notes)
        + "</ul></div>"
    )
    if "</head>" in text:
        text = text.replace("</head>", style + "</head>", 1)
    if "<body>" in text:
        text = text.replace("<body>", "<body>" + header, 1)
    else:
        text = header + text
    path.write_text(text, encoding="utf-8")
    return path


def _jsonl(path: Path) -> Iterable[dict]:
    """Stream JSONL rows with UTF-8 decoding."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _split_ids(value: object) -> list[str]:
    """Split semicolon-separated id fields from CSV cells."""
    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _rate(value: object) -> str:
    """Format a metric as a four-decimal rate string."""
    return f"{float(value):.4f}"


def _metric_color(value: float, higher_is_better: bool) -> str:
    """Map metric quality to a simple red/yellow/green color."""
    if higher_is_better:
        if value >= 0.75:
            return "#2ecc71"
        if value >= 0.35:
            return "#f39c12"
        return "#e74c3c"
    if value <= 0.05:
        return "#2ecc71"
    if value <= 0.50:
        return "#f39c12"
    return "#e74c3c"


if __name__ == "__main__":
    main()
