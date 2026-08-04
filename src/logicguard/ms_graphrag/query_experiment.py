"""Run official Microsoft GraphRAG query methods on prepared workspaces."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.prepare import load_normalized_samples

QueryMethod = str


@dataclass(frozen=True, slots=True)
class GraphRagCliResult:
    """Raw result returned by one `graphrag query` CLI invocation."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool


@dataclass(frozen=True, slots=True)
class GraphRagQueryRow:
    """One auditable official GraphRAG query result."""

    dataset: str
    corpus_state: str
    method: str
    query_id: str
    query: str
    expected_answer: str
    workspace_root: Path
    data_dir: Path
    command: list[str]
    returncode: int
    success: bool
    answer_emitted: bool
    expected_answer_present: bool
    timed_out: bool
    elapsed_seconds: float
    stdout: str
    stderr: str
    response_preview: str

    def to_json_dict(self) -> dict[str, object]:
        """Convert the row to a JSON-serializable dictionary."""

        return {
            "dataset": self.dataset,
            "corpus_state": self.corpus_state,
            "method": self.method,
            "query_id": self.query_id,
            "query": self.query,
            "expected_answer": self.expected_answer,
            "workspace_root": str(self.workspace_root),
            "data_dir": str(self.data_dir),
            "command": self.command,
            "returncode": self.returncode,
            "success": self.success,
            "answer_emitted": self.answer_emitted,
            "expected_answer_present": self.expected_answer_present,
            "timed_out": self.timed_out,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "response_preview": self.response_preview,
        }


@dataclass(frozen=True, slots=True)
class MsGraphRagQueryExperimentConfig:
    """Configuration for official Microsoft GraphRAG query experiments.

    Older configs can still provide `clean_workspace_root` and
    `poisoned_workspace_root`. Newer defense experiments should prefer
    `workspace_roots`, whose keys become condition names such as `guarded` and
    `recovered`.
    """

    dataset: str
    sample_path: Path
    output_path: Path
    report_path: Path
    graphrag_cli: Path
    clean_workspace_root: Path | None = None
    poisoned_workspace_root: Path | None = None
    workspace_roots: dict[str, Path] = field(default_factory=dict)
    methods: tuple[QueryMethod, ...] = ("basic", "local", "global")
    max_queries: int = 1
    community_level: int = 2
    response_type: str = "Single Sentence"
    timeout_seconds: int = 180

    @classmethod
    def from_yaml(cls, path: Path) -> "MsGraphRagQueryExperimentConfig":
        """Load YAML configuration with project-relative paths."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        workspace_roots = {
            str(name): resolve_project_path(str(raw_path))
            for name, raw_path in payload.get("workspace_roots", {}).items()
        }

        clean_root = payload.get("clean_workspace_root")
        poisoned_root = payload.get("poisoned_workspace_root")

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve_project_path(payload["sample_path"]),
            output_path=resolve_project_path(payload["output_path"]),
            report_path=resolve_project_path(payload["report_path"]),
            graphrag_cli=resolve_project_path(payload["graphrag_cli"]),
            clean_workspace_root=resolve_project_path(str(clean_root))
            if clean_root
            else None,
            poisoned_workspace_root=resolve_project_path(str(poisoned_root))
            if poisoned_root
            else None,
            workspace_roots=workspace_roots,
            methods=tuple(
                str(method)
                for method in payload.get("methods", ["basic", "local", "global"])
            ),
            max_queries=int(payload.get("max_queries", 1)),
            community_level=int(payload.get("community_level", 2)),
            response_type=str(payload.get("response_type", "Single Sentence")),
            timeout_seconds=int(payload.get("timeout_seconds", 180)),
        )

    def condition_workspace_roots(self) -> dict[str, Path]:
        """Return the condition-to-workspace mapping for this experiment."""

        if self.workspace_roots:
            return dict(self.workspace_roots)
        if (
            self.clean_workspace_root is not None
            and self.poisoned_workspace_root is not None
        ):
            return {
                "clean": self.clean_workspace_root,
                "poisoned": self.poisoned_workspace_root,
            }
        raise ValueError(
            "Provide either workspace_roots or both clean_workspace_root and poisoned_workspace_root"
        )


CliRunner = Callable[..., GraphRagCliResult]


def run_from_config(
    config: MsGraphRagQueryExperimentConfig,
    runner: CliRunner | None = None,
) -> list[GraphRagQueryRow]:
    """Run configured official GraphRAG queries and write JSONL/report outputs."""

    if config.max_queries < 1:
        raise ValueError("max_queries must be positive")
    runner = runner or run_graphrag_cli_query
    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    workspaces = config.condition_workspace_roots()

    rows: list[GraphRagQueryRow] = []
    for corpus_state, workspace_root in workspaces.items():
        data_dir = workspace_root / "output"
        for sample in samples:
            for method in config.methods:
                cli_result = runner(
                    workspace_root=workspace_root,
                    data_dir=data_dir,
                    method=method,
                    query=sample.query,
                    config=config,
                )
                response_preview = extract_response_preview(cli_result.stdout)
                rows.append(
                    GraphRagQueryRow(
                        dataset=config.dataset,
                        corpus_state=corpus_state,
                        method=method,
                        query_id=sample.query_id,
                        query=sample.query,
                        expected_answer=sample.answer,
                        workspace_root=workspace_root,
                        data_dir=data_dir,
                        command=cli_result.command,
                        returncode=cli_result.returncode,
                        success=cli_result.returncode == 0 and not cli_result.timed_out,
                        answer_emitted=bool(response_preview),
                        expected_answer_present=_contains_expected_answer(
                            response_preview, sample.answer
                        ),
                        timed_out=cli_result.timed_out,
                        elapsed_seconds=cli_result.elapsed_seconds,
                        stdout=cli_result.stdout,
                        stderr=cli_result.stderr,
                        response_preview=response_preview,
                    )
                )

    write_query_rows(config.output_path, rows)
    write_query_report(config.report_path, rows, config)
    return rows


def run_graphrag_cli_query(
    *,
    workspace_root: Path,
    data_dir: Path,
    method: str,
    query: str,
    config: MsGraphRagQueryExperimentConfig,
) -> GraphRagCliResult:
    """Call the official Microsoft GraphRAG CLI for one query."""

    command = [
        str(config.graphrag_cli),
        "query",
        "--root",
        str(workspace_root),
        "--method",
        method,
        "--data",
        str(data_dir),
        "--community-level",
        str(config.community_level),
        "--response-type",
        config.response_type,
        query,
    ]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.timeout_seconds,
            check=False,
        )
        return GraphRagCliResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_seconds=time.perf_counter() - start,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_timeout_stream(exc.stdout)
        stderr = _decode_timeout_stream(exc.stderr)
        return GraphRagCliResult(
            command=command,
            returncode=124,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=time.perf_counter() - start,
            timed_out=True,
        )


def extract_response_preview(stdout: str, max_lines: int = 8) -> str:
    """Extract a compact preview from CLI stdout for reports."""

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def write_query_rows(path: Path, rows: list[GraphRagQueryRow]) -> None:
    """Write query rows as JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")


def write_query_report(
    path: Path,
    rows: list[GraphRagQueryRow],
    config: MsGraphRagQueryExperimentConfig,
) -> None:
    """Write a Chinese summary report for official GraphRAG query runs."""

    path.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple[str, str], list[GraphRagQueryRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.corpus_state, row.method)].append(row)

    table_lines = [
        "| 语料状态 | 查询方法 | 调用数 | CLI成功数 | 有答案输出数 | 命中期望答案数 | 超时数 | 平均耗时(秒) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (corpus_state, method), group_rows in sorted(grouped.items()):
        success_count = sum(1 for row in group_rows if row.success)
        emitted_count = sum(1 for row in group_rows if row.answer_emitted)
        expected_count = sum(1 for row in group_rows if row.expected_answer_present)
        timeout_count = sum(1 for row in group_rows if row.timed_out)
        avg_seconds = sum(row.elapsed_seconds for row in group_rows) / len(group_rows)
        table_lines.append(
            f"| {corpus_state} | {method} | {len(group_rows)} | {success_count} | "
            f"{emitted_count} | {expected_count} | {timeout_count} | {avg_seconds:.2f} |"
        )

    sample_lines: list[str] = []
    for row in rows[: min(16, len(rows))]:
        preview = row.response_preview or row.stderr or "(无输出)"
        sample_lines.extend(
            [
                f"### {row.corpus_state} / {row.method} / {row.query_id}",
                "",
                f"- 问题：`{row.query}`",
                f"- 期望答案：`{row.expected_answer}`",
                f"- CLI成功：`{row.success}`，返回码：`{row.returncode}`，耗时：`{row.elapsed_seconds:.2f}` 秒",
                f"- 是否命中期望答案：`{row.expected_answer_present}`",
                "",
                "```text",
                preview,
                "```",
                "",
            ]
        )

    observation_lines = _build_observation_lines(rows)

    content = "\n".join(
        [
            "# Microsoft GraphRAG 官方 query 级实验报告",
            "",
            "## 实验目的",
            "",
            "本实验直接调用官方 `graphrag query` CLI，在已经完成索引的 Microsoft GraphRAG workspace 上比较不同语料状态的问答结果。"
            "它用于检验污染证据是否会传导到官方查询链路，以及 LogicGuard 的证据屏蔽或恢复策略能否改变最终回答。",
            "",
            "## 配置摘要",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 样本数：`{config.max_queries}`",
            f"- 查询方法：`{', '.join(config.methods)}`",
            f"- community_level：`{config.community_level}`",
            f"- response_type：`{config.response_type}`",
            "",
            "## 指标说明",
            "",
            "- `CLI成功数`：官方 GraphRAG CLI 返回码为 0 且未超时的调用数量。",
            "- `有答案输出数`：CLI stdout 中提取到非空回答片段的调用数量。",
            "- `命中期望答案数`：回答片段中是否直接包含数据集 gold answer，用于近似衡量答案恢复情况。",
            "- `超时数`：单次查询超过配置的 timeout_seconds，被记为无法稳定完成。",
            "- `平均耗时(秒)`：同一语料状态和查询方法下的平均墙钟时间。",
            "",
            "## 调用结果",
            "",
            *table_lines,
            "",
            "## 输出样例",
            "",
            *sample_lines,
            "## 当前解释",
            "",
            "- `basic` 查询主要验证官方 GraphRAG 对文本向量索引的基础问答能力。",
            "- `local` 查询依赖实体、关系、文本单元和 community reports，是本阶段防御实验的核心入口。",
            "- `global` 查询依赖 community reports，适合观察污染是否影响社区摘要层面的全局回答。",
            "- `guarded` 条件用于模拟 LogicGuard 屏蔽可疑证据后的官方查询结果；它更可能减少错误答案，但也可能因为证据不足而无法答出 gold answer。",
            "- `recovered` 条件用于模拟将可疑证据恢复为 clean 版本后的查询结果；如果命中期望答案，说明恢复链路有潜力把官方 GraphRAG 拉回正确证据路径。",
            "",
            "## 结果观察",
            "",
            *observation_lines,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _decode_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _contains_expected_answer(response: str, expected_answer: str) -> bool:
    """Return whether the response text contains the normalized expected answer."""

    normalized_response = " ".join(response.casefold().split())
    normalized_answer = " ".join(expected_answer.casefold().split())
    return bool(normalized_answer) and normalized_answer in normalized_response


def _build_observation_lines(rows: list[GraphRagQueryRow]) -> list[str]:
    """Build concise Chinese observations from official query rows."""

    lines: list[str] = []
    corpus_states = sorted({row.corpus_state for row in rows})
    for corpus_state in corpus_states:
        subset = [row for row in rows if row.corpus_state == corpus_state]
        expected_count = sum(1 for row in subset if row.expected_answer_present)
        emitted_count = sum(1 for row in subset if row.answer_emitted)
        success_count = sum(1 for row in subset if row.success)
        lines.append(
            f"- `{corpus_state}`：{len(subset)} 次查询中 {success_count} 次 CLI 成功，"
            f"{emitted_count} 次产生回答输出，{expected_count} 次包含期望答案。"
        )

    if any(
        row.corpus_state == "poisoned"
        and row.answer_emitted
        and not row.expected_answer_present
        for row in rows
    ):
        lines.append(
            "- `poisoned` 条件下出现有回答但未命中期望答案，说明污染证据已经能影响官方 GraphRAG 查询层。"
        )
    if any(
        row.corpus_state == "guarded"
        and row.answer_emitted
        and not row.expected_answer_present
        for row in rows
    ):
        lines.append(
            "- `guarded` 条件未命中期望答案时，不能简单理解为防御失败；它可能表示屏蔽后证据不足，需要结合是否避免了污染答案来判断。"
        )
    if any(
        row.corpus_state == "recovered" and row.expected_answer_present for row in rows
    ):
        lines.append(
            "- `recovered` 条件命中期望答案，说明将可疑证据恢复为 clean 版本后，官方查询链路具备回到正确答案的能力。"
        )

    unstable_global = [
        row
        for row in rows
        if row.method == "global" and row.answer_emitted and not row.success
    ]
    if unstable_global:
        lines.append(
            "- 存在 global 查询已经产生答案但 CLI 返回码非 0 的情况，应记录为“有输出但进程退出不稳定”，不能简单视为无答案。"
        )

    return lines or ["- 本轮查询没有产生可比较结果。"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run official Microsoft GraphRAG query methods."
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/ms_graphrag_query_stage10.yaml")
    )
    args = parser.parse_args()
    rows = run_from_config(MsGraphRagQueryExperimentConfig.from_yaml(args.config))
    for row in rows:
        status = "ok" if row.success else "failed"
        print(
            f"{row.dataset}/{row.corpus_state}/{row.method}/{row.query_id}: "
            f"{status}, returncode={row.returncode}, elapsed={row.elapsed_seconds:.2f}s"
        )


if __name__ == "__main__":
    main()
