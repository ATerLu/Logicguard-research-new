from pathlib import Path

from logicguard.experiments.run_multidataset import MultiDatasetExperimentConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "multidataset_full_500.yaml"
RAW_DATA_ROOT = PROJECT_ROOT.parent / "external_repos" / "logicPoison" / "datasets"


def test_multidataset_config_targets_all_logicpoison_benchmarks() -> None:
    config = MultiDatasetExperimentConfig.from_yaml(CONFIG_PATH)

    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]
    assert config.raw_data_root == RAW_DATA_ROOT
    assert config.processed_data_root == PROJECT_ROOT / "data" / "processed"
    assert config.run_name == "full_500"
    assert config.top_k == 10


def test_multidataset_config_derives_dataset_specific_runner_configs() -> None:
    config = MultiDatasetExperimentConfig.from_yaml(CONFIG_PATH)

    baseline = config.baseline_config("hotpotqa")
    entity_swap = config.entity_swap_config("hotpotqa")
    bridge = config.bridge_injection_config("hotpotqa")
    threshold_scan = config.threshold_scan_config("hotpotqa")

    assert baseline.dataset == "hotpotqa"
    assert baseline.sample_path == PROJECT_ROOT / "data" / "processed" / "hotpotqa" / "samples.jsonl"
    assert baseline.output_paths().trace_path == PROJECT_ROOT / "outputs" / "baseline" / "hotpotqa" / "full_500_traces.jsonl"

    assert entity_swap.dataset == "hotpotqa"
    assert entity_swap.output_root == PROJECT_ROOT / "outputs" / "attacks" / "entity_swap_full_500"
    assert entity_swap.baseline_outputs().trace_path.name == "poisoned_full_500_traces.jsonl"

    assert bridge.dataset == "hotpotqa"
    assert bridge.output_root == PROJECT_ROOT / "outputs" / "attacks" / "bridge_injection_full_500"
    assert bridge.baseline_outputs().trace_path.name == "bridge_poisoned_full_500_traces.jsonl"

    assert threshold_scan.dataset == "hotpotqa"
    assert (
        threshold_scan.reference_corpus_path
        == PROJECT_ROOT.parent / "external_repos" / "logicPoison" / "datasets" / "hotpotqa" / "corpus.jsonl"
    )
    assert (
        threshold_scan.report_path
        == PROJECT_ROOT / "outputs" / "reports" / "logicguard_threshold_scan_hotpotqa_full_500.md"
    )

