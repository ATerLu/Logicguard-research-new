import json
from pathlib import Path

import pytest

from logicguard.core.io import append_jsonl
from logicguard.core.run_state import (
    FunnelCounts,
    load_checkpoint_rows,
    prepare_run_manifest,
    stable_case_key,
)


def test_funnel_counts_reject_denominator_inflation() -> None:
    FunnelCounts(75, 35, 21, 19, 19, 10).validate()

    with pytest.raises(ValueError, match="funnel ordering"):
        FunnelCounts(75, 35, 21, 22, 19, 10).validate()


def test_manifest_rejects_changed_parameters_before_resume(tmp_path: Path) -> None:
    source = tmp_path / "input.jsonl"
    source.write_text('{"query_id":"q1"}\n', encoding="utf-8")
    manifest_path = tmp_path / "run_manifest.json"
    checkpoint_path = tmp_path / "checkpoint.jsonl"
    first = prepare_run_manifest(
        path=manifest_path,
        experiment="toy",
        config_payload={"temperature": 0.0},
        inputs=[source],
        expected_count=1,
        checkpoint_path=checkpoint_path,
    )
    append_jsonl(
        checkpoint_path,
        {
            "run_fingerprint": first["fingerprint"],
            "case_key": stable_case_key(
                dataset="toy",
                query_id="q1",
                attack_family="natural_bridge",
                defense_stage="unprotected",
                model="toy-model",
            ),
        },
    )

    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        prepare_run_manifest(
            path=manifest_path,
            experiment="toy",
            config_payload={"temperature": 0.2},
            inputs=[source],
            expected_count=1,
            checkpoint_path=checkpoint_path,
        )


def test_checkpoint_loader_ignores_only_a_truncated_tail(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps({"run_fingerprint": "fp", "case_key": "first"})
        + "\n"
        + '{"run_fingerprint":"fp"',
        encoding="utf-8",
    )

    rows = load_checkpoint_rows(checkpoint, fingerprint="fp")

    assert [row["case_key"] for row in rows] == ["first"]
