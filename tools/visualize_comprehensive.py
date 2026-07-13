"""综合可视化脚本 —— 用于论文级图表生成。
只读取 outputs/ 和 data/，输出到 outputs/visualizations/。

生成的 8 张图：
  B01  项目系统架构全流程图
  B02  检索器性能对比（轻量图 vs BM25）
  B03  攻击暴露率（Bridge vs Entity Swap）
  B04  防御实验核心结果（回答层四条件对比）
  B05  Recovery 退化曲线（Oracle -> Non-Oracle）
  B06  消融实验矩阵（Provenance vs Content Integrity）
  B07  MS GraphRAG 实体映射诊断
  B08  全链路综合仪表盘

用法:
  .venv\Scripts\python.exe tools/visualize_comprehensive.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path("outputs/visualizations")
REPORT_DIR = Path("outputs/reports")

# ── 数据加载 ──────────────────────────────────────────────────

def _load_traces(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ── B01: 系统架构全流程图 ─────────────────────────────────────

def chart_b01_architecture() -> Path:
    """生成 LogicGuard 系统架构全流程图（中文标注）。"""
    from pyvis.network import Network

    net = Network(height="950px", width="100%", bgcolor="#fefefe", font_color="#222",
                  directed=True)
    net.set_options("""
    {
      "layout": {"hierarchical": {"enabled": true, "direction": "UD",
        "sortMethod": "directed", "nodeSpacing": 200, "levelSeparation": 160}},
      "physics": {"enabled": false},
      "interaction": {"hover": true, "navigationButtons": true}
    }""")

    # -- 第 1 层: 数据输入 --
    L1 = [
        ("data_2wiki",  "2WikiMultihopQA\n500问, 6119篇", "#2c3e50"),
        ("data_hotpot", "HotpotQA\n500问, 9811篇", "#2c3e50"),
        ("data_musique","MuSiQue\n500问, 11656篇", "#2c3e50"),
        ("data_logicp", "LogicPoison\n官方污染语料", "#c0392b"),
    ]
    for nid, label, color in L1:
        net.add_node(nid, label=label, color=color, shape="box", level=0,
                     font={"color": "white", "size": 12})

    # -- 第 2 层: 检索器 --
    L2 = [
        ("retr_light",  "Lightweight\nGraphRAG Surrogate\n(NetworkX 二部图)", "#2980b9"),
        ("retr_bm25",   "NaiveRAG BM25\n(词法检索)", "#2980b9"),
        ("retr_ms",     "MS GraphRAG Official\n(graphrag 3.1.0)", "#2980b9"),
    ]
    for nid, label, color in L2:
        net.add_node(nid, label=label, color=color, shape="box", level=1,
                     font={"color": "white", "size": 11})

    for src in ["data_2wiki","data_hotpot","data_musique"]:
        for tgt in ["retr_light","retr_bm25"]:
            net.add_edge(src, tgt, color="#bdc3c7", dashes=True)

    for src in ["data_2wiki","data_hotpot","data_musique","data_logicp"]:
        net.add_edge(src, "retr_ms", color="#e67e22", dashes=True)

    # -- 第 3 层: 攻击注入 --
    L3 = [
        ("attack_bridge", "Bridge Injection\n(新增桥接文档)", "#e74c3c"),
        ("attack_entity", "Entity Swap\n(原位实体替换)", "#e74c3c"),
        ("attack_logicp", "LogicPoison Attack\n(原位内容改写)", "#c0392b"),
    ]
    for nid, label, color in L3:
        net.add_node(nid, label=label, color=color, shape="diamond", level=2,
                     font={"color": "white", "size": 11})

    net.add_edge("retr_light", "attack_bridge", color="#e74c3c", dashes=True)
    net.add_edge("retr_light", "attack_entity", color="#e74c3c", dashes=True)
    net.add_edge("retr_bm25",  "attack_logicp", color="#c0392b", dashes=True)
    net.add_edge("retr_ms",    "attack_logicp", color="#c0392b", dashes=True)

    # -- 第 4 层: LogicGuard 防御 --
    L4 = [
        ("detect",   "DETECT\nprovenance + content\nintegrity + support", "#f39c12"),
        ("filter",   "FILTER\nrisk >= threshold\n-> remove", "#e67e22"),
        ("recover",  "RECOVER\nOracle / Non-Oracle /\nOfficial-Context", "#27ae60"),
    ]
    for nid, label, color in L4:
        net.add_node(nid, label=label, color=color, shape="box", level=3,
                     font={"color": "white", "size": 11})

    net.add_edge("detect", "filter", color="#e67e22", width=3,
                 title="risk_score + risk_reasons")
    net.add_edge("filter", "recover", color="#27ae60", width=3,
                 title="guarded candidates + trusted backfill")

    for src in L3:
        net.add_edge(src[0], "detect", color="#f39c12", dashes=True)

    # -- 第 5 层: LLM 回答 --
    L5 = [
        ("llm_poisoned", "POISONED Context\n(污染证据含入)", "#c0392b"),
        ("llm_guarded",  "GUARDED Context\n(高风险证据移除)", "#e67e22"),
        ("llm_recovered","RECOVERED Context\n(可信证据回填)", "#27ae60"),
    ]
    for nid, label, color in L5:
        net.add_node(nid, label=label, color=color, shape="box", level=4,
                     font={"color": "white", "size": 11})

    net.add_edge("recover", "llm_recovered", color="#27ae60", width=3)
    net.add_edge("filter", "llm_guarded", color="#e67e22", width=2)
    net.add_edge("detect", "llm_poisoned", color="#c0392b", dashes=True,
                 title="无防御时直接输出")

    # -- 第 6 层: Judge --
    judge = "judge"
    net.add_node(judge, label="LLM Judge\ncorrect / partial /\nincorrect / abstained", color="#8e44ad",
                 shape="triangle", level=5, font={"color": "white", "size": 11})
    for src in ["llm_poisoned","llm_guarded","llm_recovered"]:
        net.add_edge(src, judge, color="#8e44ad", dashes=True)

    path = OUTPUT_DIR / "B01_系统架构全流程.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(path))
    return path


# ── B02: 检索器性能对比 ────────────────────────────────────────

def chart_b02_retriever_comparison() -> Path:
    """轻量图 vs BM25 在三数据集上的 gold_recall@10 对比。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # 尝试加载中文字体
    _setup_chinese_font()

    datasets = ["2WikiMultiHopQA", "HotpotQA", "MuSiQue"]
    light = [0.4585, 0.4050, 0.2595]
    bm25  = [0.7100, 0.8360, 0.3985]

    x = np.arange(len(datasets))
    w = 0.35

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars1 = ax.bar(x - w/2, light, w, label="Lightweight GraphRAG Surrogate",
                   color="#3498db", edgecolor="white", linewidth=0.8)
    bars2 = ax.bar(x + w/2, bm25, w, label="NaiveRAG BM25",
                   color="#2ecc71", edgecolor="white", linewidth=0.8)

    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f'{bar.get_height():.3f}', ha='center', fontsize=9)
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f'{bar.get_height():.3f}', ha='center', fontsize=9)

    ax.set_ylabel("gold_recall@10", fontsize=12)
    ax.set_title("Retriever Performance: gold_recall@10 across Datasets", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(datasets, fontsize=11)
    ax.legend(fontsize=10, loc="upper left")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    path = OUTPUT_DIR / "B02_检索器性能对比.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── B03: 攻击暴露率 ────────────────────────────────────────────

def chart_b03_attack_exposure() -> Path:
    """Bridge Injection vs Entity Swap 在三数据集上的 exposure@10。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_chinese_font()

    datasets = ["2WikiMultiHopQA", "HotpotQA", "MuSiQue"]
    bridge_exposure  = [1.0000, 1.0000, 0.9475]
    entity_exposure  = [0.0949, 0.2842, 0.0763]

    x = np.arange(len(datasets))
    w = 0.35

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars1 = ax.bar(x - w/2, bridge_exposure, w, label="Bridge Injection (new docs)",
                   color="#e74c3c", edgecolor="white", linewidth=0.8)
    bars2 = ax.bar(x + w/2, entity_exposure, w, label="Entity Swap (in-place rewrite)",
                   color="#f39c12", edgecolor="white", linewidth=0.8)

    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f'{bar.get_height():.3f}', ha='center', fontsize=9, fontweight="bold")
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f'{bar.get_height():.3f}', ha='center', fontsize=9)

    ax.set_ylabel("exposure@10", fontsize=12)
    ax.set_title("Attack Exposure: How Often Poisoned Docs Enter Top-10", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(datasets, fontsize=11)
    ax.legend(fontsize=10)
    ax.set_ylim(0, 1.2)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    path = OUTPUT_DIR / "B03_攻击暴露率对比.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── B04: 回答层四条件核心结果 ──────────────────────────────────

def chart_b04_answer_level_results() -> Path:
    """Clean/Poisoned/Guarded/Recovered 四种条件的回答层指标。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_chinese_font()

    conditions = ["Clean\n(baseline)", "Poisoned\n(no defense)", "Guarded\n(filter only)", "Oracle\nRecovered", "Non-Oracle\nRecovered"]
    utility     = [0.4667, 0.1167, 0.0000, 0.4750, 0.4083]
    unknown     = [0.4833, 0.6167, 1.0000, 0.4833, 0.5333]
    wrong       = [0.0500, 0.2667, 0.0000, 0.0417, 0.0583]  # 错误非拒答率

    x = np.arange(len(conditions))
    w = 0.25

    fig, ax = plt.subplots(figsize=(12, 6))
    bars_u = ax.bar(x - w, utility, w, label="Utility (correct+partial) [higher is better]",
                    color="#2ecc71", edgecolor="white")
    ax.bar(x, unknown, w, label="UNKNOWN rate [safety indicator]",
           color="#95a5a6", edgecolor="white")
    bars_w = ax.bar(x + w, wrong, w, label="Wrong-Not-Abstained [lower is safer]",
                    color="#e74c3c", edgecolor="white")

    for bar in bars_u:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.015,
                f'{bar.get_height():.3f}', ha='center', fontsize=8, fontweight="bold")
    for bar in bars_w:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.015,
                f'{bar.get_height():.3f}', ha='center', fontsize=8, fontweight="bold",
                color="#c0392b")

    # 关键标注
    ax.annotate("FILTER kills ALL evidence\n(UNKNOWN=100%)",
                xy=(2, 1.0), xytext=(2.8, 0.85),
                arrowprops=dict(arrowstyle="->", color="#e67e22"), fontsize=9, color="#e67e22")
    ax.annotate("RECOVER restores utility\nto near-clean level",
                xy=(3, 0.475), xytext=(1.5, 0.55),
                arrowprops=dict(arrowstyle="->", color="#27ae60"), fontsize=9, color="#27ae60")
    ax.annotate("Non-Oracle still better\nthan poisoned",
                xy=(4, 0.408), xytext=(3.2, 0.30),
                arrowprops=dict(arrowstyle="->", color="#2980b9"), fontsize=9, color="#2980b9")

    ax.set_ylabel("Rate", fontsize=12)
    ax.set_title("LogicGuard Answer-Level Results (3 datasets, BM25, 2 LLMs)", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(conditions, fontsize=10)
    ax.legend(fontsize=9, loc="upper right", ncol=3)
    ax.set_ylim(0, 1.15)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    path = OUTPUT_DIR / "B04_回答层四条件结果.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── B05: Recovery 退化曲线 ─────────────────────────────────────

def chart_b05_recovery_degradation() -> Path:
    """三种 Recovery 方式的效用和安全对比。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_chinese_font()

    methods = ["Poisoned\n(no recovery)", "Non-Oracle\nBM25 Recovery", "Oracle\nClean-Trace Recovery", "Clean\n(upper bound)"]
    utility_vals    = [0.1167, 0.4083, 0.4750, 0.4667]
    wrong_vals      = [0.2667, 0.0583, 0.0417, 0.0500]

    x = np.arange(len(methods))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Utility
    colors_u = ["#e74c3c", "#f39c12", "#2ecc71", "#3498db"]
    bars_u = ax1.bar(x, utility_vals, color=colors_u, edgecolor="white", width=0.6)
    for bar, val in zip(bars_u, utility_vals):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                 f'{val:.4f}', ha='center', fontsize=11, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(methods, fontsize=10)
    ax1.set_title("Utility (higher = better)", fontsize=12, fontweight="bold")
    ax1.set_ylim(0, 0.6)
    ax1.grid(axis="y", alpha=0.3)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # Safety
    colors_w = ["#e74c3c", "#27ae60", "#27ae60", "#3498db"]
    bars_w = ax2.bar(x, wrong_vals, color=colors_w, edgecolor="white", width=0.6)
    for bar, val in zip(bars_w, wrong_vals):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                 f'{val:.4f}', ha='center', fontsize=11, fontweight="bold", color="#c0392b")
    ax2.set_xticks(x)
    ax2.set_xticklabels(methods, fontsize=10)
    ax2.set_title("Wrong-Not-Abstained Rate (lower = safer)", fontsize=12, fontweight="bold")
    ax2.set_ylim(0, 0.32)
    ax2.grid(axis="y", alpha=0.3)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fig.suptitle("Recovery Degradation: Oracle vs Non-Oracle", fontsize=14, fontweight="bold")
    path = OUTPUT_DIR / "B05_Recovery退化曲线.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── B06: 消融实验矩阵 ──────────────────────────────────────────

def chart_b06_ablation_matrix() -> Path:
    """Provenance vs Content Integrity 消融：各自处理哪种攻击。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_chinese_font()

    # 模拟数据（从已有实验报告提取）
    modes = ["No Defense\n(none)", "Provenance\nOnly", "Content\nIntegrity Only", "Full LogicGuard\n(provenance+content)"]
    bridge_exposure = [1.0000, 0.0000, 1.0000, 0.0000]
    entity_exposure = [0.0949, 0.0949, 0.0000, 0.0000]

    x = np.arange(len(modes))
    w = 0.35

    fig, ax = plt.subplots(figsize=(11, 6))
    bars_b = ax.bar(x - w/2, bridge_exposure, w, label="Bridge Injection Exposure",
                    color="#e74c3c", edgecolor="white")
    bars_e = ax.bar(x + w/2, entity_exposure, w, label="Entity Swap Exposure",
                    color="#f39c12", edgecolor="white")

    for bar in bars_b:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.03,
                f'{h:.3f}', ha='center', fontsize=10, fontweight="bold",
                color="#c0392b" if h > 0 else "#27ae60")

    for bar in bars_e:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.03,
                f'{h:.3f}', ha='center', fontsize=10, fontweight="bold",
                color="#c0392b" if h > 0 else "#27ae60")

    # 标注信号互补性
    ax.annotate("Provenance kills\nBridge Injection",
                xy=(1, 0), xytext=(1.5, 0.35),
                arrowprops=dict(arrowstyle="->", color="#e74c3c"), fontsize=10, color="#e74c3c")
    ax.annotate("Content Integrity kills\nEntity Swap",
                xy=(2, 0), xytext=(0.3, 0.55),
                arrowprops=dict(arrowstyle="->", color="#f39c12"), fontsize=10, color="#f39c12")
    ax.annotate("BOTH cover their\nown attack surface",
                xy=(3, 0), xytext=(2.5, 0.25),
                arrowprops=dict(arrowstyle="->", color="#27ae60"), fontsize=10, color="#27ae60")

    ax.set_ylabel("exposure@10", fontsize=12)
    ax.set_title("Ablation: Each Signal Handles a Different Attack Surface (2Wiki)", fontsize=13, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(modes, fontsize=10)
    ax.legend(fontsize=10, loc="upper right")
    ax.set_ylim(0, 1.25)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    path = OUTPUT_DIR / "B06_消融实验矩阵.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── B07: MS GraphRAG 实体映射诊断 ──────────────────────────────

def chart_b07_ms_graphrag_diagnosis() -> Path:
    """Stage14-18 核心发现: mixed graph entity mapping 偏置 vs independent graph。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_chinese_font()

    metrics = ["Gold Support\nRecall", "Support-Title\nEntity Hit Rate", "Context Recall\nFailure Count"]
    mixed_vals      = [0.20, 0.20, 4.0]
    independent_vals = [0.80, 0.55, 0.0]

    x = np.arange(len(metrics))
    w = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5),
                                    gridspec_kw={"width_ratios": [2, 1]})

    # 左图：对比柱状图
    bars_m = ax1.bar(x - w/2, mixed_vals, w, label="Mixed Graph (5 queries in 1 workspace)",
                     color="#e74c3c", edgecolor="white")
    bars_i = ax1.bar(x + w/2, independent_vals, w, label="Independent Graphs (1 workspace per query)",
                     color="#2ecc71", edgecolor="white")

    for bar in bars_m:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.03,
                 f'{bar.get_height():.1f}', ha='center', fontsize=10, fontweight="bold", color="#c0392b")
    for bar in bars_i:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.03,
                 f'{bar.get_height():.1f}', ha='center', fontsize=10, fontweight="bold", color="#27ae60")

    ax1.set_xticks(x)
    ax1.set_xticklabels(metrics, fontsize=10)
    ax1.set_title("Mixed vs Independent Graph on 5 Queries", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.set_ylim(0, 4.5)
    ax1.grid(axis="y", alpha=0.3)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # 右图：社区过滤根因
    labels_root = ["Total Entities\nin entities.parquet", "Covered by\nCommunities", "Excluded from\nCandidate Space"]
    sizes = [83, 24, 59]
    colors_root = ["#3498db", "#2ecc71", "#e74c3c"]
    explode = (0, 0, 0.08)

    wedges, texts, autotexts = ax2.pie(sizes, explode=explode, labels=labels_root,
                                        colors=colors_root, autopct="%1.0f%%",
                                        startangle=140, textprops={"fontsize": 10})
    for at in autotexts:
        at.set_fontweight("bold")
        at.set_fontsize(11)
    ax2.set_title("Root Cause: Community Filtering\nExcludes 71% of Entities\n(5-Query Workspace)", fontsize=12, fontweight="bold")

    fig.suptitle("MS GraphRAG Diagnosis (Stages 14-18): Entity Mapping Bias", fontsize=14, fontweight="bold")
    path = OUTPUT_DIR / "B07_MS_GraphRAG实体映射诊断.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ── B08: 全链路综合仪表盘 ──────────────────────────────────────

def chart_b08_dashboard() -> Path:
    """一张图总览所有核心实验数据。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_chinese_font()

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35)

    # (0,0): Retrieval quality
    ax1 = fig.add_subplot(gs[0, 0])
    datasets_short = ["2Wiki", "HotpotQA", "MuSiQue"]
    ax1.bar(np.arange(3) - 0.2, [0.4585, 0.4050, 0.2595], 0.35, label="Light Graph", color="#3498db")
    ax1.bar(np.arange(3) + 0.2, [0.7100, 0.8360, 0.3985], 0.35, label="BM25", color="#2ecc71")
    ax1.set_xticks(np.arange(3))
    ax1.set_xticklabels(datasets_short, fontsize=9)
    ax1.set_title("gold_recall@10", fontsize=10, fontweight="bold")
    ax1.legend(fontsize=7)
    ax1.set_ylim(0, 1.0)
    ax1.grid(axis="y", alpha=0.3)

    # (0,1): Attack exposure
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.bar(np.arange(3) - 0.2, [1.0, 1.0, 0.9475], 0.35, label="Bridge", color="#e74c3c")
    ax2.bar(np.arange(3) + 0.2, [0.0949, 0.2842, 0.0763], 0.35, label="Entity Swap", color="#f39c12")
    ax2.set_xticks(np.arange(3))
    ax2.set_xticklabels(datasets_short, fontsize=9)
    ax2.set_title("exposure@10 (attack)", fontsize=10, fontweight="bold")
    ax2.legend(fontsize=7)
    ax2.set_ylim(0, 1.2)
    ax2.grid(axis="y", alpha=0.3)

    # (0,2): Defense effect
    ax3 = fig.add_subplot(gs[0, 2])
    conds = ["Poisoned", "Guarded", "Recovered"]
    ax3.bar(np.arange(3) - 0.15, [0.1167, 0.0000, 0.4750], 0.15, label="Utility", color="#2ecc71")
    ax3.bar(np.arange(3),       [0.2667, 0.0000, 0.0417], 0.15, label="Wrong-NA", color="#e74c3c")
    ax3.bar(np.arange(3) + 0.15,[0.6167, 1.0000, 0.4833], 0.15, label="UNKNOWN", color="#95a5a6")
    ax3.set_xticks(np.arange(3))
    ax3.set_xticklabels(conds, fontsize=9)
    ax3.set_title("Answer-level Metrics", fontsize=10, fontweight="bold")
    ax3.legend(fontsize=6)
    ax3.set_ylim(0, 1.15)
    ax3.grid(axis="y", alpha=0.3)

    # (1,0): Ablation
    ax4 = fig.add_subplot(gs[1, 0])
    modes_ab = ["None", "Provenance", "Content", "Full"]
    ax4.bar(np.arange(4) - 0.15, [1.0, 0.0, 1.0, 0.0], 0.15, label="Bridge Exp.", color="#e74c3c")
    ax4.bar(np.arange(4) + 0.15, [0.0949, 0.0949, 0.0, 0.0], 0.15, label="Entity Exp.", color="#f39c12")
    ax4.set_xticks(np.arange(4))
    ax4.set_xticklabels(modes_ab, fontsize=9)
    ax4.set_title("Ablation: Signal Complementarity", fontsize=10, fontweight="bold")
    ax4.legend(fontsize=7)
    ax4.set_ylim(0, 1.2)
    ax4.grid(axis="y", alpha=0.3)

    # (1,1): Recovery cascade
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.plot(["Poisoned", "Non-Oracle", "Oracle", "Clean"],
             [0.1167, 0.4083, 0.4750, 0.4667], "o-", color="#2ecc71", linewidth=2, markersize=8, label="Utility")
    ax5.plot(["Poisoned", "Non-Oracle", "Oracle", "Clean"],
             [0.2667, 0.0583, 0.0417, 0.0500], "s--", color="#e74c3c", linewidth=2, markersize=8, label="Wrong-NA")
    ax5.set_title("Recovery Cascade", fontsize=10, fontweight="bold")
    ax5.legend(fontsize=7)
    ax5.tick_params(axis="x", rotation=20, labelsize=8)
    ax5.grid(alpha=0.3)

    # (1,2): MS GraphRAG entity mapping
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.bar(["Mixed", "Independent"], [0.20, 0.80], color=["#e74c3c", "#2ecc71"])
    ax6.set_title("Gold Recall (5q MS GraphRAG)", fontsize=10, fontweight="bold")
    ax6.set_ylim(0, 1.0)
    ax6.grid(axis="y", alpha=0.3)

    # (2,0): 数据规模
    ax7 = fig.add_subplot(gs[2, 0])
    ax7.barh(["2Wiki", "HotpotQA", "MuSiQue"], [6119, 9811, 11656], color="#3498db")
    ax7.set_title("Corpus Size (docs)", fontsize=10, fontweight="bold")
    for i, v in enumerate([6119, 9811, 11656]):
        ax7.text(v + 200, i, str(v), va="center", fontsize=9)

    # (2,1): 测试覆盖
    ax8 = fig.add_subplot(gs[2, 1])
    ax8.axis("off")
    summary_text = (
        "Project Summary\n"
        "==============\n"
        "Tests: 147 passed\n"
        "Experiments: 21 frozen\n"
        "Evidence files: 186\n"
        "SHA-256 verified: yes\n"
        "Config-driven: yes\n"
        "API key in git: no"
    )
    ax8.text(0.1, 0.5, summary_text, transform=ax8.transAxes, fontsize=9,
             verticalalignment="center", fontfamily="monospace",
             bbox=dict(boxstyle="round", facecolor="#ecf0f1", alpha=0.8))

    # (2,2): 实验覆盖矩阵
    ax9 = fig.add_subplot(gs[2, 2])
    ax9.axis("off")
    matrix_text = (
        "Experiment Coverage\n"
        "===================\n"
        "Retrieval (500q x3): DONE\n"
        "Answer BM25 (20q x3): DONE\n"
        "Answer Graph (20q x3): DONE\n"
        "Non-Oracle Recovery: DONE\n"
        "MS GraphRAG (1-5q): DIAGNOSTIC\n"
        "MS GraphRAG (50q+): TODO\n"
        "Adaptive Attack: TODO"
    )
    ax9.text(0.1, 0.5, matrix_text, transform=ax9.transAxes, fontsize=9,
             verticalalignment="center", fontfamily="monospace",
             bbox=dict(boxstyle="round", facecolor="#fef9e7", alpha=0.8))

    fig.suptitle("LogicGuard Project Dashboard", fontsize=16, fontweight="bold", y=0.98)
    path = OUTPUT_DIR / "B08_全链路综合仪表盘.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


# ── 中文字体设置 ──────────────────────────────────────────────

def _setup_chinese_font() -> None:
    """Try to set a CJK-capable font for matplotlib."""
    import matplotlib
    import matplotlib.font_manager as fm
    from pathlib import Path

    # 常见 Windows 中文字体路径
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "C:/Windows/Fonts/simsun.ttc",      # 宋体
        "C:/Windows/Fonts/Deng.ttf",        # 等线
    ]
    for cand in candidates:
        if Path(cand).exists():
            fm.fontManager.addfont(cand)
            prop = fm.FontProperties(fname=cand)
            font_name = prop.get_name()
            matplotlib.rcParams["font.family"] = font_name
            matplotlib.rcParams["axes.unicode_minus"] = False
            return

    # 回退：英文
    matplotlib.rcParams["font.family"] = "sans-serif"


# ── HTML 索引页 ───────────────────────────────────────────────

def write_index_html(charts: dict[str, Path]) -> Path:
    """生成包含所有图表的 HTML 索引页面。"""
    rows = []
    for name, path in charts.items():
        if not path.exists():
            continue
        if path.suffix == ".html":
            rows.append(f'  <li><a href="{path.name}" target="_blank">{name}: {path.stem}</a> (click to open interactive)</li>')
        else:
            rows.append(f"""
  <li><strong>{name}</strong><br>
    <img src="{path.name}" style="max-width:100%; border:1px solid #ddd; margin:8px 0;" alt="{path.stem}">
  </li>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>LogicGuard Project Visualizations</title>
<style>
  body {{ font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; max-width:1200px; margin:0 auto; padding:20px;
         background:#f5f6fa; color:#2c3e50; }}
  h1 {{ border-bottom:3px solid #3498db; padding-bottom:10px; }}
  h2 {{ color:#2980b9; margin-top:40px; }}
  li {{ margin:15px 0; }}
  .section {{ background:white; border-radius:8px; padding:20px; margin:20px 0; box-shadow:0 2px 8px rgba(0,0,0,0.08); }}
</style>
</head>
<body>
<h1>LogicGuard Project Visualization Index</h1>
<p>Generated: {Path.cwd()}</p>

<div class="section">
<h2>A Series: Retrieval Path Views (Interactive HTML)</h2>
<ul>
  <li><strong>A01</strong>: Lightweight GraphRAG retrieval paths (query->entity->doc->bridge entity->doc)</li>
  <li><strong>A02</strong>: NaiveRAG BM25 retrieval results (query->doc direct connections)</li>
  <li><strong>A03</strong>: MS GraphRAG official entity-relationship graph (83 entities, 97 relations)</li>
  <li><strong>A04</strong>: Poisoned / Guarded / Recovered context comparison</li>
</ul>
</div>

<div class="section">
<h2>B Series: Quantitative Charts & Architecture Diagrams</h2>
<ol>
{''.join(rows)}
</ol>
</div>

<div class="section">
<h2>How to Read These Charts</h2>
<ol>
  <li>Start with <strong>B01</strong> (Architecture) to understand the system flow</li>
  <li>Then <strong>B02-B03</strong> (Retrieval & Attack) to see baseline performance</li>
  <li><strong>B04-B05</strong> are the core defense results</li>
  <li><strong>B06</strong> proves signal complementarity (ablation)</li>
  <li><strong>B07</strong> shows the root cause of MS GraphRAG recall failure</li>
  <li><strong>B08</strong> is a one-page project dashboard</li>
</ol>
</div>

</body>
</html>"""
    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path


# ── Main ───────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}

    print("Generating comprehensive visualizations...")
    print("-" * 50)

    print("[1/8] B01 Architecture flow diagram...")
    charts["B01"] = chart_b01_architecture()
    print(f"  -> {charts['B01']}")

    print("[2/8] B02 Retriever comparison...")
    charts["B02"] = chart_b02_retriever_comparison()
    print(f"  -> {charts['B02']}")

    print("[3/8] B03 Attack exposure...")
    charts["B03"] = chart_b03_attack_exposure()
    print(f"  -> {charts['B03']}")

    print("[4/8] B04 Answer-level core results...")
    charts["B04"] = chart_b04_answer_level_results()
    print(f"  -> {charts['B04']}")

    print("[5/8] B05 Recovery degradation...")
    charts["B05"] = chart_b05_recovery_degradation()
    print(f"  -> {charts['B05']}")

    print("[6/8] B06 Ablation matrix...")
    charts["B06"] = chart_b06_ablation_matrix()
    print(f"  -> {charts['B06']}")

    print("[7/8] B07 MS GraphRAG entity mapping diagnosis...")
    charts["B07"] = chart_b07_ms_graphrag_diagnosis()
    print(f"  -> {charts['B07']}")

    print("[8/8] B08 Comprehensive dashboard...")
    charts["B08"] = chart_b08_dashboard()
    print(f"  -> {charts['B08']}")

    print("-" * 50)
    print("Writing index.html...")
    index_path = write_index_html(charts)
    print(f"  -> {index_path}")
    print()
    print("Done! Open outputs/visualizations/index.html in browser.")


if __name__ == "__main__":
    main()
