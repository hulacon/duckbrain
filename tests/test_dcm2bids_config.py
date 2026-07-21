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


def test_generate_config_multiple_unnamed_fmap_pairs_no_collision():
    """Two reacquired AP/PA pairs must produce distinct fmap filenames (run-1 vs
    run-2) and unique dcm2bids ids, not two colliding dir-AP entries."""
    series = [
        _series(6, "se_epi_ap", "fmap", n=3),
        _series(7, "se_epi_pa", "fmap", n=3),
        _series(20, "se_epi_ap", "fmap", n=3),
        _series(21, "se_epi_pa", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(
        strategy="series_number",
        groups={"1": {"ap": 6, "pa": 7}, "2": {"ap": 20, "pa": 21}},
        group_entities={"1": "run-1", "2": "run-2"},
    )
    cfg = generate_config(series, fmaps)
    fmap_desc = [d for d in cfg["descriptions"] if d["datatype"] == "fmap"]
    entities = sorted(d["custom_entities"] for d in fmap_desc)
    assert entities == ["dir-AP_run-1", "dir-AP_run-2", "dir-PA_run-1", "dir-PA_run-2"]
    ids = [d["id"] for d in fmap_desc]
    assert len(ids) == len(set(ids))  # unique ids


def test_generate_config_named_fmap_pairs_use_acq_entities():
    """Named pairs place acq- before dir- (BIDS entity order) and stay distinct."""
    series = [
        _series(4, "se_epi_ap_encoding", "fmap", n=3),
        _series(5, "se_epi_pa_encoding", "fmap", n=3),
        _series(12, "se_epi_ap_retrieval", "fmap", n=3),
        _series(13, "se_epi_pa_retrieval", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(
        strategy="series_description",
        groups={"encoding": {"ap": 4, "pa": 5}, "retrieval": {"ap": 12, "pa": 13}},
        group_entities={"encoding": "acq-encoding", "retrieval": "acq-retrieval"},
    )
    cfg = generate_config(series, fmaps)
    entities = sorted(
        d["custom_entities"] for d in cfg["descriptions"] if d["datatype"] == "fmap"
    )
    assert entities == [
        "acq-encoding_dir-AP",
        "acq-encoding_dir-PA",
        "acq-retrieval_dir-AP",
        "acq-retrieval_dir-PA",
    ]


def test_generate_config_reacquired_named_pair_orders_acq_dir_run():
    """A named group reshot in one session carries both acq- and run-, in BIDS
    entity order: acq- before dir-, run- after."""
    series = [
        _series(9, "se_epi_ap_encoding", "fmap", n=3),
        _series(11, "se_epi_pa_encoding", "fmap", n=3),
        _series(48, "se_epi_ap_encoding", "fmap", n=3),
        _series(50, "se_epi_pa_encoding", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(
        strategy="series_description",
        groups={"encoding": {"ap": 9, "pa": 11}, "encoding-2": {"ap": 48, "pa": 50}},
        group_entities={
            "encoding": "acq-encoding_run-1",
            "encoding-2": "acq-encoding_run-2",
        },
    )
    cfg = generate_config(series, fmaps)
    fmap_desc = [d for d in cfg["descriptions"] if d["datatype"] == "fmap"]
    assert sorted(d["custom_entities"] for d in fmap_desc) == [
        "acq-encoding_dir-AP_run-1",
        "acq-encoding_dir-AP_run-2",
        "acq-encoding_dir-PA_run-1",
        "acq-encoding_dir-PA_run-2",
    ]
    ids = [d["id"] for d in fmap_desc]
    assert len(ids) == len(set(ids))


def test_generate_config_bold_skips_incomplete_fmap_group():
    """A bold links to a group holding both directions, never to a lone aborted AP.

    The half-group sorts first, so the naive "first group" default would hand
    fMRIPrep a distortion correction it cannot run.
    """
    series = [
        _series(5, "se_epi_ap", "fmap", n=3),
        _series(6, "se_epi_ap", "fmap", n=3),
        _series(7, "se_epi_pa", "fmap", n=3),
        _series(9, "cued_recall_encoding_run1", "func", n=200),
    ]
    fmaps = FieldmapDetection(
        strategy="series_number",
        groups={"1": {"ap": 5}, "2": {"ap": 6, "pa": 7}},
        group_entities={"1": "run-1", "2": "run-2"},
    )
    cfg = generate_config(series, fmaps)
    bold = [d for d in cfg["descriptions"] if d["suffix"] == "bold"][0]
    assert bold["sidecar_changes"]["B0FieldIdentifier"] == "B0map_2"


def test_generate_config_single_fmap_pair_unchanged():
    """A lone pair keeps the bare dir- entity (no acq-/run-), preserving prior output."""
    series = [
        _series(6, "se_epi_ap", "fmap", n=3),
        _series(7, "se_epi_pa", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(strategy="series_number", groups={"": {"ap": 6, "pa": 7}})
    cfg = generate_config(series, fmaps)
    entities = sorted(
        d["custom_entities"] for d in cfg["descriptions"] if d["datatype"] == "fmap"
    )
    assert entities == ["dir-AP", "dir-PA"]


def test_generate_config_honors_edited_mapping():
    series = [_series(9, "div_retScene_perTone_r1", "func")]
    edited = [TaskRunEntry(9, "div_retScene_perTone_r1", "bold", task="attn", run=5)]
    cfg = generate_config(series, FieldmapDetection(strategy="none"), mapping=edited)
    d = cfg["descriptions"][0]
    assert d["custom_entities"] == "task-attn_run-5"
    assert d["sidecar_changes"]["TaskName"] == "attn"
