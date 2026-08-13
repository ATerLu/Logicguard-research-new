"""Generate a standalone Stage43--47 LogicGuard research dashboard.

The page is derived only from the curated Stage46/47 artifacts tracked in this
repository.  All CSS, JavaScript and chart data are embedded in the output, so
the resulting HTML can be opened directly without a server or external CDN.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE46_SUMMARY = ROOT / "artifacts/results/stage46_cross_dataset_answer_final_summary.csv"
STAGE47_SUMMARY = ROOT / "artifacts/results/stage47_adaptive_attack_final_summary.csv"
STAGE47_EXAMPLES = ROOT / "artifacts/results/stage47_adaptive_attack_examples.jsonl"
DEFAULT_OUTPUT = (
    ROOT / "artifacts/visualizations/Stage43-47_LogicGuard_统一可视化.html"
)

ATTACK_FAMILIES = ("low_drift", "candidate_collision", "natural_bridge")
DEFENSE_STAGES = (
    "unprotected",
    "stage43_recovery",
    "stage44_top12",
    "stage45_top14",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _as_int(row: dict[str, str], key: str) -> int:
    return int(row[key])


def _as_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _weighted_count(row: dict[str, str], rate_key: str, denominator_key: str) -> int:
    return round(_as_float(row, rate_key) * _as_int(row, denominator_key))


def _aggregate_stage47(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, dict[str, dict[str, float | int]]]]:
    """Aggregate strict Stage47 metrics for all-data and per-dataset views."""

    scopes = {
        "all": rows,
        "hotpotqa": [row for row in rows if row["dataset"] == "hotpotqa"],
        "musique": [row for row in rows if row["dataset"] == "musique"],
    }
    output: dict[str, dict[str, dict[str, dict[str, float | int]]]] = {}
    for scope, scope_rows in scopes.items():
        output[scope] = {}
        for family in ATTACK_FAMILIES:
            output[scope][family] = {}
            for stage in DEFENSE_STAGES:
                selected = [
                    row
                    for row in scope_rows
                    if row["attack_family"] == family
                    and row["defense_stage"] == stage
                ]
                attempted = sum(_as_int(row, "attempted_attack_count") for row in selected)
                generated = sum(
                    _as_int(row, "generated_valid_attack_count") for row in selected
                )
                valid = sum(_as_int(row, "valid_attack_count") for row in selected)
                exposed = sum(_as_int(row, "exposed_attack_count") for row in selected)
                target_exposed = sum(
                    _as_int(row, "target_exposed_attack_count") for row in selected
                )
                targeted_success = sum(
                    _weighted_count(
                        row,
                        "targeted_asr_exposure_conditioned",
                        "target_exposed_attack_count",
                    )
                    for row in selected
                )
                broad_success = sum(
                    _weighted_count(
                        row,
                        "broad_asr_exposure_conditioned",
                        "exposed_attack_count",
                    )
                    for row in selected
                )
                detections = sum(
                    _weighted_count(row, "risk_detection_rate", "valid_attack_count")
                    for row in selected
                )
                wrong_recoveries = sum(
                    _weighted_count(
                        row, "wrong_candidate_recovery_rate", "valid_attack_count"
                    )
                    for row in selected
                )
                utility_count = sum(
                    _weighted_count(row, "final_utility_rate", "valid_attack_count")
                    for row in selected
                )
                output[scope][family][stage] = {
                    "attempted": attempted,
                    "generated": generated,
                    "valid": valid,
                    "exposed": exposed,
                    "target_exposed": target_exposed,
                    "targeted_success": targeted_success,
                    "targeted_asr": _ratio(targeted_success, target_exposed),
                    "broad_success": broad_success,
                    "broad_asr": _ratio(broad_success, exposed),
                    "detections": detections,
                    "detection_rate": _ratio(detections, valid),
                    "wrong_recoveries": wrong_recoveries,
                    "wrong_recovery_rate": _ratio(wrong_recoveries, valid),
                    "utility_rate": _ratio(utility_count, valid),
                }
    return output


def _prepare_stage46(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "dataset": row["dataset"],
            "method": row["method"],
            "query_count": _as_int(row, "query_count"),
            "utility_rate": _as_float(row, "final_utility_rate"),
            "attack_success_rate": _as_float(row, "final_attack_success_rate"),
            "abstain_rate": _as_float(row, "final_abstain_rate"),
            "changed_exposure_rate": _as_float(
                row, "actual_unrecovered_changed_exposure_rate"
            ),
        }
        for row in rows
    ]


def _prepare_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        record = row["attack_record"]
        prepared.append(
            {
                "dataset": row["dataset"],
                "attack_family": row["attack_family"],
                "query_id": row["query_id"],
                "query": row["query"],
                "gold_answer": row["gold_answer"],
                "malicious_answer": row["malicious_answer"],
                "target_title": record.get("target_title", ""),
                "collision_candidate_title": record.get(
                    "collision_candidate_title", ""
                ),
                "entity_drift": float(record.get("entity_drift", 0.0)),
                "original_excerpt": str(record.get("original_excerpt", ""))[:720],
                "attacked_excerpt": str(record.get("attacked_excerpt", ""))[:720],
                "results": [
                    {
                        "defense_stage": result["defense_stage"],
                        "attack_exposed": bool(result["attack_exposed"]),
                        "risk_detected": bool(result["risk_detected"]),
                        "collision_recovered": bool(
                            result["candidate_collision_recovered"]
                        ),
                        "generated_answer": result["generated_answer"],
                        "final_label": result["final_label"],
                        "targeted_success": bool(result["targeted_attack_success"]),
                    }
                    for result in row["results"]
                ],
            }
        )
    return prepared


def build_payload() -> dict[str, Any]:
    stage46_rows = _read_csv(STAGE46_SUMMARY)
    stage47_rows = _read_csv(STAGE47_SUMMARY)
    stage47_examples = _read_jsonl(STAGE47_EXAMPLES)
    aggregate = _aggregate_stage47(stage47_rows)

    unprotected = [
        row for row in stage47_rows if row["defense_stage"] == "unprotected"
    ]
    funnel = {
        "attempted": sum(_as_int(row, "attempted_attack_count") for row in unprotected),
        "generated": sum(
            _as_int(row, "generated_valid_attack_count") for row in unprotected
        ),
        "valid": sum(_as_int(row, "valid_attack_count") for row in unprotected),
        "target_exposed": sum(
            _as_int(row, "target_exposed_attack_count") for row in unprotected
        ),
    }
    expected_funnel = {
        "attempted": 75,
        "generated": 35,
        "valid": 21,
        "target_exposed": 19,
    }
    if funnel != expected_funnel:
        raise ValueError(f"Unexpected Stage47 funnel: {funnel!r}")

    return {
        "stage46": _prepare_stage46(stage46_rows),
        "stage47": aggregate,
        "funnel": funnel,
        "examples": _prepare_examples(stage47_examples),
        "source_files": [
            str(STAGE46_SUMMARY.relative_to(ROOT)),
            str(STAGE47_SUMMARY.relative_to(ROOT)),
            str(STAGE47_EXAMPLES.relative_to(ROOT)),
        ],
    }


def render_html(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c")
    return HTML_TEMPLATE.replace("__LOGICGUARD_DATA__", encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(build_payload()), encoding="utf-8")
    print(f"Generated: {output}")


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LogicGuard Stage43–47 统一可视化</title>
<style>
:root {
  --ink: #102a43;
  --muted: #5f7184;
  --paper: #f5f7f8;
  --card: #ffffff;
  --line: #d8e0e7;
  --blue: #236aa1;
  --blue-soft: #eaf3fa;
  --green: #18785b;
  --green-soft: #e7f5ef;
  --amber: #ad6b0d;
  --amber-soft: #fff4dc;
  --red: #b6342b;
  --red-soft: #fcebea;
  --purple: #6a4b92;
  --purple-soft: #f1ecf7;
  --shadow: 0 14px 35px rgba(24, 45, 66, .08);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Inter, "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif;
  line-height: 1.65;
}
a { color: inherit; }
.shell { width: min(1220px, calc(100% - 32px)); margin: 0 auto; }
.hero {
  background: #102a43;
  color: white;
  padding: 54px 0 42px;
  border-bottom: 5px solid #2d84bd;
}
.eyebrow { margin: 0 0 10px; color: #9ed0ee; font-size: 13px; font-weight: 800; letter-spacing: .14em; }
h1 { margin: 0; max-width: 950px; font-size: clamp(30px, 5vw, 58px); line-height: 1.12; letter-spacing: -.03em; }
.hero-copy { max-width: 880px; margin: 18px 0 0; color: #d6e5ef; font-size: 17px; }
.hero-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 28px; }
.hero-stat { padding: 16px; border: 1px solid #35536a; background: #173650; border-radius: 10px; }
.hero-stat strong { display: block; font-size: 28px; line-height: 1; }
.hero-stat span { display: block; margin-top: 8px; color: #bbd2e1; font-size: 13px; }
.nav {
  position: sticky; top: 0; z-index: 20; background: rgba(245,247,248,.96);
  border-bottom: 1px solid var(--line); backdrop-filter: blur(10px);
}
.nav .shell { display: flex; gap: 6px; overflow-x: auto; padding: 10px 0; }
.nav a { flex: 0 0 auto; padding: 8px 12px; border-radius: 7px; text-decoration: none; color: #425d72; font-size: 13px; font-weight: 750; }
.nav a:hover { color: var(--blue); background: var(--blue-soft); }
main { padding: 26px 0 70px; }
.section { margin: 18px 0; padding: 28px; background: var(--card); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); }
.section-head { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
.section-kicker { margin: 0 0 5px; color: var(--blue); font-size: 12px; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
h2 { margin: 0; font-size: clamp(23px, 3vw, 34px); line-height: 1.25; }
h3 { margin: 0; font-size: 18px; line-height: 1.35; }
.section-note { max-width: 560px; margin: 0; color: var(--muted); font-size: 14px; }
.callout { padding: 15px 17px; border-left: 4px solid var(--blue); background: var(--blue-soft); border-radius: 0 9px 9px 0; color: #294c65; }
.callout.warning { border-color: var(--amber); background: var(--amber-soft); color: #68460e; }
.pipeline { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.stage-card { position: relative; padding: 17px 15px; border: 1px solid var(--line); border-top: 5px solid var(--stage-color, var(--blue)); border-radius: 10px; background: #fbfcfd; }
.stage-card:not(:last-child)::after { content: "→"; position: absolute; right: -14px; top: 42%; z-index: 2; color: #8da0ae; font-weight: 900; }
.stage-no { color: var(--stage-color, var(--blue)); font-size: 12px; font-weight: 900; }
.stage-card p { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.detector-layout { display: grid; grid-template-columns: 1.05fr .95fr; gap: 24px; align-items: start; }
.logic-flow { padding: 18px; background: #f8fafb; border: 1px solid var(--line); border-radius: 12px; }
.logic-node { padding: 13px 14px; text-align: center; border: 2px solid var(--blue); background: white; border-radius: 9px; font-weight: 800; }
.logic-node.danger { border-color: var(--red); background: var(--red-soft); color: #7a241e; }
.logic-node.warn { border-color: var(--amber); background: var(--amber-soft); color: #70490c; }
.logic-node.safe { border-color: var(--green); background: var(--green-soft); color: #155c47; }
.down-arrow { padding: 5px; text-align: center; color: #8093a1; font-size: 20px; font-weight: 900; }
.branch { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.branch-label { margin-bottom: 5px; text-align: center; color: var(--muted); font-size: 12px; font-weight: 800; }
.formula { margin-top: 12px; padding: 12px; background: #102a43; color: #e5f1f8; border-radius: 8px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; }
.truth-list { display: grid; gap: 11px; }
.truth-item { padding: 16px; border: 1px solid var(--line); border-left: 5px solid var(--attack-color); border-radius: 9px; background: white; }
.truth-item p { margin: 7px 0 0; color: var(--muted); font-size: 13px; }
.truth-badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 999px; background: #edf2f5; color: #425d72; font-size: 12px; font-weight: 800; }
.badge.red { background: var(--red-soft); color: var(--red); }
.badge.green { background: var(--green-soft); color: var(--green); }
.badge.amber { background: var(--amber-soft); color: var(--amber); }
.badge.purple { background: var(--purple-soft); color: var(--purple); }
.tabs { display: flex; flex-wrap: wrap; gap: 7px; }
.tab { border: 1px solid #b9c6cf; background: white; color: #405a6f; padding: 8px 13px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 13px; font-weight: 800; }
.tab.active { border-color: var(--blue); background: var(--blue); color: white; }
.stage46-chart { display: grid; gap: 12px; }
.method-row { display: grid; grid-template-columns: 190px 1fr; gap: 15px; align-items: center; padding: 13px; border: 1px solid var(--line); border-radius: 10px; }
.method-label strong { display: block; }
.method-label span { display: block; color: var(--muted); font-size: 12px; }
.metric-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
.metric-title { display: flex; justify-content: space-between; font-size: 12px; font-weight: 800; }
.bar-track { height: 12px; margin-top: 6px; overflow: hidden; border-radius: 999px; background: #e8edf1; }
.bar-fill { height: 100%; border-radius: 999px; transition: width .45s ease; }
.bar-fill.utility { background: var(--green); }
.bar-fill.asr { background: var(--red); }
.funnel { display: grid; gap: 8px; margin-top: 8px; }
.funnel-row { display: grid; grid-template-columns: 160px 1fr 90px; gap: 12px; align-items: center; }
.funnel-label strong { display: block; }
.funnel-label span { color: var(--muted); font-size: 12px; }
.funnel-track { height: 48px; display: flex; align-items: center; background: #edf1f4; border-radius: 8px; overflow: hidden; }
.funnel-fill { height: 100%; display: flex; align-items: center; justify-content: flex-end; min-width: 46px; padding-right: 13px; color: white; font-size: 18px; font-weight: 900; background: var(--funnel-color); }
.funnel-rate { text-align: right; color: var(--muted); font-size: 13px; font-weight: 800; }
.attack-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 13px; margin-top: 20px; }
.attack-card { padding: 18px; border: 1px solid var(--line); border-top: 6px solid var(--attack-color); border-radius: 11px; background: #fbfcfd; }
.attack-card p { margin: 8px 0; color: var(--muted); font-size: 13px; }
.attack-numbers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 13px; }
.attack-number { padding: 9px 5px; text-align: center; background: white; border: 1px solid var(--line); border-radius: 7px; }
.attack-number strong { display: block; font-size: 19px; }
.attack-number span { color: var(--muted); font-size: 10px; }
.detail-layout { display: grid; grid-template-columns: 260px 1fr; gap: 20px; }
.family-tabs { display: grid; gap: 8px; }
.family-tab { width: 100%; padding: 13px; text-align: left; border: 1px solid var(--line); border-left: 5px solid var(--attack-color); border-radius: 9px; background: white; cursor: pointer; color: var(--ink); font: inherit; }
.family-tab.active { background: #edf4f9; border-color: var(--blue); }
.family-tab strong, .family-tab span { display: block; }
.family-tab span { margin-top: 3px; color: var(--muted); font-size: 12px; }
.attack-stage-chart { display: grid; gap: 11px; }
.attack-stage-row { padding: 13px; border: 1px solid var(--line); border-radius: 9px; }
.attack-stage-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 9px; }
.mini-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
.mini-metric { padding: 9px; background: #f7f9fa; border-radius: 7px; }
.mini-metric-top { display: flex; justify-content: space-between; gap: 6px; font-size: 11px; font-weight: 800; }
.mini-bar { height: 7px; margin-top: 6px; background: #e3e9ed; border-radius: 99px; overflow: hidden; }
.mini-bar i { display: block; height: 100%; background: var(--metric-color); }
.denominator { margin-top: 10px; color: var(--muted); font-size: 12px; }
.example-controls { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 16px; }
.example-head { display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: start; }
.example-query { margin: 5px 0 12px; font-size: 19px; font-weight: 800; line-height: 1.45; }
.answer-pair { display: flex; flex-wrap: wrap; gap: 8px; }
.answer-chip { padding: 7px 10px; border-radius: 7px; font-size: 13px; font-weight: 800; }
.answer-chip.gold { background: var(--green-soft); color: var(--green); }
.answer-chip.bad { background: var(--red-soft); color: var(--red); }
.excerpt-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
.excerpt { min-height: 150px; padding: 13px; border: 1px solid var(--line); border-radius: 9px; background: #f8fafb; }
.excerpt strong { display: block; margin-bottom: 7px; }
.excerpt p { margin: 0; color: #425d72; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; white-space: pre-wrap; }
.result-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 9px; margin-top: 13px; }
.result-card { padding: 13px; border: 1px solid var(--line); border-radius: 9px; background: white; }
.result-card .answer { min-height: 44px; margin: 9px 0; font-weight: 850; }
.result-card small { color: var(--muted); }
.conclusion-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.conclusion { padding: 17px; border-radius: 10px; border: 1px solid var(--line); }
.conclusion.good { border-top: 5px solid var(--green); background: var(--green-soft); }
.conclusion.warn { border-top: 5px solid var(--amber); background: var(--amber-soft); }
.conclusion.bad { border-top: 5px solid var(--red); background: var(--red-soft); }
.conclusion p { margin: 7px 0 0; font-size: 13px; }
.foot { padding: 24px 0 48px; color: var(--muted); font-size: 12px; }
.source-list { margin: 8px 0 0; padding-left: 20px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
@media (max-width: 900px) {
  .hero-grid, .attack-grid, .conclusion-grid { grid-template-columns: 1fr 1fr; }
  .pipeline { grid-template-columns: 1fr; }
  .stage-card:not(:last-child)::after { content: "↓"; right: auto; left: 50%; top: auto; bottom: -18px; }
  .detector-layout, .detail-layout { grid-template-columns: 1fr; }
  .family-tabs { grid-template-columns: repeat(3, 1fr); }
  .result-strip { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 620px) {
  .shell { width: min(100% - 20px, 1220px); }
  .hero { padding-top: 38px; }
  .hero-grid, .attack-grid, .conclusion-grid, .excerpt-grid { grid-template-columns: 1fr; }
  .section { padding: 19px 15px; }
  .section-head, .example-head { display: block; }
  .section-note { margin-top: 9px; }
  .method-row { grid-template-columns: 1fr; }
  .metric-pair, .mini-metrics { grid-template-columns: 1fr; }
  .funnel-row { grid-template-columns: 115px 1fr; }
  .funnel-rate { display: none; }
  .family-tabs { grid-template-columns: 1fr; }
  .result-strip { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header class="hero">
  <div class="shell">
    <p class="eyebrow">LOGICGUARD · EVIDENCE DASHBOARD</p>
    <h1>Stage43–47：从固定攻击归零，到自适应攻击暴露真实缺口</h1>
    <p class="hero-copy">一页串联 detector、recovery、clean evidence enrichment、second-hop completion 与三类自适应 source 攻击。所有数字来自仓库中冻结的 Stage46/47 artifacts。</p>
    <div class="hero-grid">
      <div class="hero-stat"><strong>0</strong><span>Stage46 防御后固定 LogicPoison ASR</span></div>
      <div class="hero-stat"><strong>3</strong><span>Stage47 自适应攻击族</span></div>
      <div class="hero-stat"><strong>21</strong><span>严格评测有效攻击</span></div>
      <div class="hero-stat"><strong>19</strong><span>恶意答案实际进入未防御 prompt</span></div>
    </div>
  </div>
</header>

<nav class="nav"><div class="shell">
  <a href="#pipeline">防御链</a><a href="#detector">Detector</a><a href="#stage46">Stage46</a>
  <a href="#funnel">攻击漏斗</a><a href="#attacks">三类攻击</a><a href="#examples">实际案例</a><a href="#conclusion">结论</a>
</div></nav>

<main class="shell">
  <section class="section" id="pipeline">
    <div class="section-head"><div><p class="section-kicker">Defense chain</p><h2>Stage43–47 在同一条链上分别做什么</h2></div><p class="section-note">Stage46 是固定 LogicPoison 的回答层基线；Stage47 冻结前述参数后，专门检验知道防御逻辑的攻击者。</p></div>
    <div class="pipeline">
      <article class="stage-card" style="--stage-color:#236aa1"><span class="stage-no">STAGE 43</span><h3>检测 + 恢复</h3><p>标题重合与实体漂移共同判风险；命中后从 trusted clean candidate 中替换。</p></article>
      <article class="stage-card" style="--stage-color:#18785b"><span class="stage-no">STAGE 44</span><h3>Clean 补证</h3><p>保留恢复结果，再用 query BM25 追加 clean evidence 至 top-12。</p></article>
      <article class="stage-card" style="--stage-color:#6a4b92"><span class="stage-no">STAGE 45</span><h3>二跳补全</h3><p>仅在多跳链不完整时，按桥实体追加第二跳候选至 top-14。</p></article>
      <article class="stage-card" style="--stage-color:#ad6b0d"><span class="stage-no">STAGE 46</span><h3>真实回答验证</h3><p>固定 prompt 渲染，运行回答、规则审计和按需 Judge。</p></article>
      <article class="stage-card" style="--stage-color:#b6342b"><span class="stage-no">STAGE 47</span><h3>自适应压力测试</h3><p>低漂移、候选碰撞、自然桥接分别攻击 detector、recovery 与来源覆盖。</p></article>
    </div>
  </section>

  <section class="section" id="detector">
    <div class="section-head"><div><p class="section-kicker">Detector & recovery</p><h2>当前判定逻辑，以及三类攻击卡在哪里</h2></div><p class="section-note">冻结配置：title overlap ≥ 0.80，entity drift ≥ 0.10。两个条件同时成立才判风险。</p></div>
    <div class="detector-layout">
      <div class="logic-flow">
        <div class="logic-node">GraphRAG 已检索 source</div><div class="down-arrow">↓</div>
        <div class="logic-node">能否找到 trusted clean candidate？</div><div class="down-arrow">↓</div>
        <div class="branch">
          <div><div class="branch-label">否</div><div class="logic-node danger">candidate=None<br>当前返回 safe</div><div class="down-arrow">↓</div><div class="logic-node danger">自然桥接直接漏检</div></div>
          <div><div class="branch-label">是</div><div class="logic-node">标题重合 ≥ .80 且实体漂移 ≥ .10？</div><div class="down-arrow">↓</div><div class="branch"><div><div class="branch-label">否</div><div class="logic-node warn">低漂移漏检</div></div><div><div class="branch-label">是</div><div class="logic-node safe">判风险并替换</div><div class="down-arrow">↓</div><div class="logic-node warn">碰撞时可能替换错</div></div></div></div>
        </div>
        <div class="formula">is_risky = (title_overlap ≥ 0.80) AND (entity_drift ≥ 0.10)</div>
      </div>
      <div class="truth-list">
        <article class="truth-item" style="--attack-color:#d17916"><h3>低实体漂移：事实变了，实体集合几乎不变</h3><p>篡改数值、日期、关系或属性，检测器没有足够实体漂移信号。</p><div class="truth-badges"><span class="badge red">检出 0/6</span><span class="badge amber">目标暴露 4/6</span></div></article>
        <article class="truth-item" style="--attack-color:#6a4b92"><h3>候选碰撞：检测正确，但 recovery 身份错</h3><p>标题碰撞错误 clean candidate；攻击 source 被移除，不等于恢复到了正确证据。</p><div class="truth-badges"><span class="badge green">检出 5/5</span><span class="badge red">错误恢复 5/5</span></div></article>
        <article class="truth-item" style="--attack-color:#b6342b"><h3>自然桥接：无 counterpart 被当成安全</h3><p>新 source 语言自然且 query 相关，但 trusted pool 中没有一一对应来源。</p><div class="truth-badges"><span class="badge red">检出 0/10</span><span class="badge red">目标暴露 10/10</span></div></article>
        <div class="callout warning"><strong>最重要的语义修正：</strong>candidate=None 只能说明“无法核验”，不能说明“安全”。</div>
      </div>
    </div>
  </section>

  <section class="section" id="stage46">
    <div class="section-head"><div><p class="section-kicker">Frozen LogicPoison baseline</p><h2>Stage46：固定攻击上，防御确实有效</h2></div><div class="tabs" id="stage46-tabs"></div></div>
    <div id="stage46-chart" class="stage46-chart"></div>
    <div class="callout" style="margin-top:16px"><strong>如何读：</strong>绿色是回答效用，红色是攻击成功率。Stage43 切断污染暴露；Stage44 主要提升可答性；Stage45 只在 MuSiQue 上显示小幅额外效用。</div>
  </section>

  <section class="section" id="funnel">
    <div class="section-head"><div><p class="section-kicker">Strict denominator</p><h2>75 → 35 → 21 → 19：为什么不能把所有尝试都算进 ASR</h2></div><p class="section-note">每一层都施加更严格条件，防止把生成失败、无效目标或未进入 prompt 的攻击误当成防御成功。</p></div>
    <div class="funnel" id="funnel-chart"></div>
    <div class="attack-grid" id="attack-summary"></div>
  </section>

  <section class="section" id="attacks">
    <div class="section-head"><div><p class="section-kicker">Adaptive attack outcome</p><h2>三类攻击穿过 Stage43–45 后发生了什么</h2></div><div class="tabs" id="scope-tabs"></div></div>
    <div class="detail-layout">
      <div class="family-tabs" id="family-tabs"></div>
      <div><div id="attack-detail-title"></div><div class="attack-stage-chart" id="attack-stage-chart"></div><p class="denominator">Targeted ASR 以“恶意目标答案实际进入 prompt”为分母；wrong recovery 以严格评测有效攻击为分母。</p></div>
    </div>
  </section>

  <section class="section" id="examples">
    <div class="section-head"><div><p class="section-kicker">Traceable examples</p><h2>从 source 篡改到最终回答：逐例查看</h2></div><p class="section-note">每类攻击提供 HotpotQA 与 MuSiQue 各一个冻结样例。按钮只切换嵌入页面的数据，不会调用 API。</p></div>
    <div class="example-controls" id="example-controls"></div>
    <div id="example-view"></div>
  </section>

  <section class="section" id="conclusion">
    <div class="section-head"><div><p class="section-kicker">Takeaways</p><h2>一句话看懂当前 LogicGuard</h2></div></div>
    <div class="conclusion-grid">
      <article class="conclusion good"><h3>已经成立</h3><p>在 Stage46 固定 LogicPoison 攻击上，Stage43–45 将两个数据集的最终 ASR 都降到 0，并恢复部分可答性。</p></article>
      <article class="conclusion warn"><h3>只能算缓解</h3><p>Stage44/45 通过加入 clean evidence 稀释部分自适应攻击，但没有可靠识别或移除自然桥接 source。</p></article>
      <article class="conclusion bad"><h3>尚未解决</h3><p>关系/属性一致性、无 counterpart 来源、错误候选恢复，以及完整 corpus poisoning + reindex 仍需 Stage48 验证。</p></article>
    </div>
    <div class="callout warning" style="margin-top:16px"><strong>实验边界：</strong>Stage47 是 post-retrieval source perturbation，没有重新构建攻击后的 GraphRAG index；不能据此宣称对建图、embedding、community 或原始排名变化具备端到端鲁棒性。</div>
  </section>
</main>

<footer class="foot"><div class="shell"><strong>数据来源</strong><ul class="source-list" id="source-list"></ul><p>页面由 <code>tools/generate_stage43_47_visualization.py</code> 生成；无外部 JavaScript、字体或 CDN 依赖。</p></div></footer>

<script>
const DATA = __LOGICGUARD_DATA__;
const LABELS = {
  datasets: {hotpotqa: "HotpotQA", musique: "MuSiQue", all: "两数据集合计"},
  methods: {
    full_query_guard: ["未恢复 Context", "Stage46 baseline"],
    risk_non_oracle_title_entity_bm25: ["Stage43", "检测 + recovery"],
    stage35_query_bm25_append_top12: ["Stage44", "clean top-12 补证"],
    stage38_second_hop_append_top14: ["Stage45", "二跳 top-14"]
  },
  stages: {unprotected:"未防御", stage43_recovery:"Stage43", stage44_top12:"Stage44", stage45_top14:"Stage45"},
  families: {
    low_drift: {name:"低实体漂移", color:"#d17916", short:"事实属性变，实体不变"},
    candidate_collision: {name:"候选碰撞", color:"#6a4b92", short:"检出后诱导错误恢复"},
    natural_bridge: {name:"自然桥接", color:"#b6342b", short:"无 clean counterpart"}
  }
};
const state = {stage46Dataset:"hotpotqa", scope:"all", family:"natural_bridge", example:0};
const pct = value => `${Math.round(value * 100)}%`;
const safeText = value => value === null || value === undefined ? "" : String(value);

function el(tag, attrs={}, children=[]) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key,value]) => {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  });
  (Array.isArray(children) ? children : [children]).forEach(child => {
    if (child !== null && child !== undefined) node.append(child.nodeType ? child : document.createTextNode(child));
  });
  return node;
}

function renderTabs(containerId, entries, current, onSelect) {
  const root = document.getElementById(containerId); root.replaceChildren();
  entries.forEach(([key,label]) => root.append(el("button", {class:`tab ${key===current?"active":""}`, text:label, onclick:()=>onSelect(key)})));
}

function renderStage46() {
  renderTabs("stage46-tabs", [["hotpotqa","HotpotQA"],["musique","MuSiQue"]], state.stage46Dataset, key=>{state.stage46Dataset=key;renderStage46();});
  const root = document.getElementById("stage46-chart"); root.replaceChildren();
  DATA.stage46.filter(row=>row.dataset===state.stage46Dataset).forEach(row=>{
    const [name,desc] = LABELS.methods[row.method];
    const metrics = el("div", {class:"metric-pair"}, [
      metricBar("回答效用", row.utility_rate, "utility"), metricBar("攻击成功率", row.attack_success_rate, "asr")
    ]);
    root.append(el("div", {class:"method-row"}, [el("div", {class:"method-label", html:`<strong>${name}</strong><span>${desc}</span>`}), metrics]));
  });
}

function metricBar(label, value, kind) {
  return el("div", {}, [
    el("div", {class:"metric-title", html:`<span>${label}</span><strong>${pct(value)}</strong>`}),
    el("div", {class:"bar-track"}, el("div", {class:`bar-fill ${kind}`, style:`width:${value*100}%`}))
  ]);
}

function renderFunnel() {
  const f=DATA.funnel, rows=[
    ["攻击尝试","25 query × 3 类",f.attempted,"#236aa1"],
    ["生成有效","满足攻击模板约束",f.generated,"#6a4b92"],
    ["评测有效","错误目标真实且碰撞候选非 gold",f.valid,"#ad6b0d"],
    ["Prompt 暴露","恶意目标答案实际进入未防御 prompt",f.target_exposed,"#b6342b"]
  ];
  const root=document.getElementById("funnel-chart"); root.replaceChildren();
  rows.forEach((row,index)=>root.append(el("div", {class:"funnel-row"}, [
    el("div", {class:"funnel-label", html:`<strong>${row[0]}</strong><span>${row[1]}</span>`}),
    el("div", {class:"funnel-track"}, el("div", {class:"funnel-fill", style:`width:${row[2]/f.attempted*100}%;--funnel-color:${row[3]}`, text:String(row[2])})),
    el("div", {class:"funnel-rate", text:index===0?"基准":`${pct(row[2]/rows[index-1][2])} / 上一层`})
  ])));
  const summaries=document.getElementById("attack-summary"); summaries.replaceChildren();
  Object.keys(LABELS.families).forEach(family=>{
    const meta=LABELS.families[family], base=DATA.stage47.all[family].unprotected, s43=DATA.stage47.all[family].stage43_recovery, s44=DATA.stage47.all[family].stage44_top12;
    const note=family==="low_drift"?"检出机制失效；严格样本较少，ASR 仍需扩样。":family==="candidate_collision"?"回答 ASR 归零，但 recovery integrity 失败。":"当前最大缺口；clean 补证只能有限缓解。";
    summaries.append(el("article", {class:"attack-card", style:`--attack-color:${meta.color}`}, [
      el("h3", {text:meta.name}), el("p", {text:note}),
      el("div", {class:"attack-numbers"}, [numBox(`${base.valid}/${base.attempted}`,"评测有效"),numBox(pct(s43.detection_rate),"Stage43 检出"),numBox(pct(s44.targeted_asr),"Stage44 targeted ASR")])
    ]));
  });
}
function numBox(value,label){return el("div",{class:"attack-number"},[el("strong",{text:value}),el("span",{text:label})]);}

function renderAttackDetails() {
  renderTabs("scope-tabs", [["all","两数据集合计"],["hotpotqa","HotpotQA"],["musique","MuSiQue"]], state.scope, key=>{state.scope=key;renderAttackDetails();});
  const familyRoot=document.getElementById("family-tabs"); familyRoot.replaceChildren();
  Object.entries(LABELS.families).forEach(([key,meta])=>familyRoot.append(el("button",{class:`family-tab ${key===state.family?"active":""}`,style:`--attack-color:${meta.color}`,onclick:()=>{state.family=key;renderAttackDetails();}},[el("strong",{text:meta.name}),el("span",{text:meta.short})])));
  const meta=LABELS.families[state.family], data=DATA.stage47[state.scope][state.family];
  document.getElementById("attack-detail-title").innerHTML=`<h3 style="color:${meta.color};margin-bottom:12px">${LABELS.datasets[state.scope]} · ${meta.name}</h3>`;
  const chart=document.getElementById("attack-stage-chart"); chart.replaceChildren();
  Object.entries(data).forEach(([stage,m])=>{
    chart.append(el("div",{class:"attack-stage-row"},[
      el("div",{class:"attack-stage-head",html:`<strong>${LABELS.stages[stage]}</strong><span class="badge">${m.valid} 条严格有效</span>`}),
      el("div",{class:"mini-metrics"},[
        miniMetric("Targeted ASR",m.targeted_asr,"#b6342b",`${m.targeted_success}/${m.target_exposed}`),
        miniMetric("风险检出",m.detection_rate,"#236aa1",`${m.detections}/${m.valid}`),
        miniMetric("错误候选恢复",m.wrong_recovery_rate,"#6a4b92",`${m.wrong_recoveries}/${m.valid}`)
      ])
    ]));
  });
}
function miniMetric(label,value,color,fraction){return el("div",{class:"mini-metric",style:`--metric-color:${color}`},[el("div",{class:"mini-metric-top",html:`<span>${label}</span><strong>${pct(value)} · ${fraction}</strong>`}),el("div",{class:"mini-bar"},el("i",{style:`width:${value*100}%`}))]);}

function renderExamples() {
  const controls=document.getElementById("example-controls"); controls.replaceChildren();
  DATA.examples.forEach((example,index)=>controls.append(el("button",{class:`tab ${index===state.example?"active":""}`,text:`${LABELS.datasets[example.dataset]} · ${LABELS.families[example.attack_family].name}`,onclick:()=>{state.example=index;renderExamples();}})));
  const e=DATA.examples[state.example], meta=LABELS.families[e.attack_family], root=document.getElementById("example-view"); root.replaceChildren();
  const head=el("div",{class:"example-head"},[
    el("div",{},[el("span",{class:"badge",text:`${LABELS.datasets[e.dataset]} · ${e.query_id}`}),el("div",{class:"example-query",text:e.query}),el("div",{class:"answer-pair"},[el("span",{class:"answer-chip gold",text:`标准答案：${e.gold_answer}`}),el("span",{class:"answer-chip bad",text:`攻击目标：${e.malicious_answer}`})])]),
    el("div",{class:"truth-badges"},[el("span",{class:"badge purple",text:`${meta.name}`}),el("span",{class:"badge",text:`entity drift ${e.entity_drift.toFixed(3)}`})])
  ]);
  const excerpts=el("div",{class:"excerpt-grid"},[excerptBox("原始/候选 source",e.original_excerpt),excerptBox("攻击后 source",e.attacked_excerpt)]);
  const results=el("div",{class:"result-strip"});
  e.results.forEach(r=>{
    const badges=[r.risk_detected?'<span class="badge green">已检出</span>':'<span class="badge red">未检出</span>',r.attack_exposed?'<span class="badge red">攻击仍暴露</span>':'<span class="badge green">攻击源移除</span>'];
    if(r.collision_recovered) badges.push('<span class="badge purple">错误候选恢复</span>');
    results.append(el("article",{class:"result-card"},[el("strong",{text:LABELS.stages[r.defense_stage]}),el("div",{class:"answer",text:r.generated_answer}),el("div",{html:badges.join(" ")}),el("small",{text:`final=${r.final_label} · targeted ASR=${r.targeted_success?"是":"否"}`})]));
  });
  root.append(head,excerpts,results);
}
function excerptBox(title,text){return el("div",{class:"excerpt"},[el("strong",{text:title}),el("p",{text:safeText(text)||"该攻击为新增 source，没有原始 counterpart。"})]);}

function renderSources(){const root=document.getElementById("source-list");DATA.source_files.forEach(path=>root.append(el("li",{text:path})));}
renderStage46(); renderFunnel(); renderAttackDetails(); renderExamples(); renderSources();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
