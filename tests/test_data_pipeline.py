from pathlib import Path

from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.prepare import (
    DataPreparationConfig,
    build_samples,
    load_normalized_samples,
    make_debug_subset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_ROOT = PROJECT_ROOT / "data" / "logicpoison_official" / "clean"
CONFIG_PATH = PROJECT_ROOT / "configs" / "data.yaml"


def test_load_raw_dataset_keeps_ids_aligned() -> None:
    dataset = load_raw_dataset(DatasetPaths.from_root(RAW_DATA_ROOT, "2wikimultihopqa"))

    assert dataset.name == "2wikimultihopqa"
    assert len(dataset.queries) == 500
    assert len(dataset.answers) == 500
    assert len(dataset.corpus) == 6119
    assert set(dataset.queries) == set(dataset.answers)
    assert set(dataset.queries) == set(dataset.qrels)

    all_support_ids = {doc_id for doc_ids in dataset.qrels.values() for doc_id in doc_ids}
    assert all_support_ids <= set(dataset.corpus)


def test_build_samples_embeds_support_documents() -> None:
    dataset = load_raw_dataset(DatasetPaths.from_root(RAW_DATA_ROOT, "2wikimultihopqa"))

    samples = build_samples(dataset)
    first = samples[0]

    assert len(samples) == 500
    assert first.query_id == "a457e11c0bdb11eba7f7acde48001122"
    assert first.query == "Who is the mother of the director of film Atomised (Film)?"
    assert first.answer == "Gisela Elsner"
    assert first.support_doc_ids == ["639", "638"]
    assert [doc.doc_id for doc in first.support_docs] == ["639", "638"]
    assert all(doc.title for doc in first.support_docs)
    assert all(doc.text for doc in first.support_docs)


def test_make_debug_subset_is_deterministic_and_size_limited() -> None:
    dataset = load_raw_dataset(DatasetPaths.from_root(RAW_DATA_ROOT, "2wikimultihopqa"))
    samples = build_samples(dataset)

    subset_a = make_debug_subset(samples, size=50)
    subset_b = make_debug_subset(samples, size=50)

    assert len(subset_a) == 50
    assert [sample.query_id for sample in subset_a] == [sample.query_id for sample in subset_b]
    assert subset_a[0].query_id == samples[0].query_id
    assert subset_a[-1].query_id == samples[49].query_id


def test_project_data_config_targets_all_available_datasets() -> None:
    config = DataPreparationConfig.from_yaml(CONFIG_PATH)

    assert config.raw_data_root == RAW_DATA_ROOT
    assert config.processed_data_root == PROJECT_ROOT / "data" / "processed"
    assert config.report_root == PROJECT_ROOT / "outputs" / "reports"
    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]
    assert config.debug_size == 50


def test_load_normalized_samples_reads_generated_jsonl() -> None:
    path = PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "debug_50.jsonl"

    samples = load_normalized_samples(path)

    assert len(samples) == 50
    assert samples[0].query_id == "a457e11c0bdb11eba7f7acde48001122"
    assert samples[0].support_docs[0].doc_id == "639"
