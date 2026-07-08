"""Tests for the task/run mapping + dcm2bids config generation."""

from duckbrain.core.dicom_inspect import (
    SeriesInfo,
    parse_task_run,
    extract_task_label,
)
from duckbrain.core.dcm2bids_config import (
    build_task_run_mapping,
    generate_config,
    TaskRunEntry,
)
from duckbrain.core.dicom_inspect import FieldmapDetection


def _series(num, desc, cls, n=300):
    s = SeriesInfo(series_number=num, description=desc, path=None, file_count=n)
    s.classification = cls
    return s


# ---- parsing ----

def test_parse_task_run_heuristic():
    assert parse_task_run("div_retScene_perTone_r1") == ("divRetScenePerTone", 1)
    assert parse_task_run("single_perFace_r2") == ("singlePerFace", 2)
    assert parse_task_run("cmrr_mbep2d_bold_task-encoding_run-1") == ("encoding", 1)
    # no run token -> run is None (caller assigns by repetition)
    assert parse_task_run("cmrr_mbep2d_bold_task-rest") == ("rest", None)


def test_parse_task_run_template():
    # glob-like template overrides the heuristic
    task, run = parse_task_run("attention_run3", template="{task}_run{run}")
    assert task == "attention"
    assert run == 3


def test_extract_task_label_backward_compat():
    assert extract_task_label("cmrr_mbep2d_bold_task-encoding_run-1") == "encoding"
    assert extract_task_label("task_rest_bold") == "rest"


# ---- mapping ----

def test_build_mapping_run_from_name():
    series = [
        _series(9, "div_perFace_perTone_r1", "func"),
        _series(21, "div_perFace_perTone_r2", "func"),
        _series(8, "div_perFace_perTone_r1_SBRef", "sbref", n=1),
        _series(20, "div_perFace_perTone_r2_SBRef", "sbref", n=1),
    ]
    mapping = build_task_run_mapping(series)
    by_series = {e.series_number: e for e in mapping}

    assert by_series[9].task == "divPerFacePerTone" and by_series[9].run == 1
    assert by_series[21].run == 2
    # SBRef inherits its bold run's task/run
    assert by_series[8].task == "divPerFacePerTone" and by_series[8].run == 1
    assert by_series[20].run == 2


def test_build_mapping_run_by_repetition():
    """No run token in the names -> run derived by repetition order."""
    series = [
        _series(5, "attention", "func"),
        _series(9, "attention", "func"),
        _series(13, "rest", "func"),
    ]
    mapping = build_task_run_mapping(series)
    runs = [(e.task, e.run) for e in mapping]
    assert runs == [("attention", 1), ("attention", 2), ("rest", 1)]


# ---- config generation ----

def test_generate_config_emits_run_entity():
    series = [
        _series(9, "div_retScene_perTone_r1", "func"),
        _series(23, "div_retScene_perTone_r2", "func"),
    ]
    cfg = generate_config(series, FieldmapDetection(strategy="none"))
    entities = sorted(d["custom_entities"] for d in cfg["descriptions"])
    assert entities == [
        "task-divRetScenePerTone_run-1",
        "task-divRetScenePerTone_run-2",
    ]
    # ids are unique per run
    ids = [d["id"] for d in cfg["descriptions"]]
    assert len(ids) == len(set(ids))


def test_bold_and_sbref_criteria_use_series_number():
    """Criteria must key on SeriesNumber so a bold's description wildcard can't
    also swallow its SBRef (dcm2bids 'Several Pairing' -> both skipped)."""
    series = [
        _series(9, "div_perFace_perTone_r1", "func"),
        _series(8, "div_perFace_perTone_r1_SBRef", "sbref", n=1),
    ]
    cfg = generate_config(series, FieldmapDetection(strategy="none"))
    crit = {d["suffix"]: d["criteria"] for d in cfg["descriptions"]}
    assert crit["bold"] == {"SeriesNumber": 9}
    assert crit["sbref"] == {"SeriesNumber": 8}
    # No SeriesDescription wildcard that could match across acquisitions
    assert all("SeriesDescription" not in d["criteria"] for d in cfg["descriptions"])


def test_generate_config_honors_edited_mapping():
    series = [_series(9, "div_retScene_perTone_r1", "func")]
    edited = [TaskRunEntry(9, "div_retScene_perTone_r1", "bold", task="attn", run=5)]
    cfg = generate_config(series, FieldmapDetection(strategy="none"), mapping=edited)
    d = cfg["descriptions"][0]
    assert d["custom_entities"] == "task-attn_run-5"
    assert d["sidecar_changes"]["TaskName"] == "attn"
