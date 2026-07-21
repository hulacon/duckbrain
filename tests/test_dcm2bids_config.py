"""Tests for the task/run mapping + dcm2bids config generation."""

from duckbrain.core.dicom_inspect import (
    SeriesInfo,
    parse_task_run,
    extract_task_label,
)
import pytest

from duckbrain.core.dcm2bids_config import (
    build_task_run_mapping,
    generate_config,
    FmapRule,
    TaskRunEntry,
    fmap_rules_from_config,
    fmap_rules_to_config_section,
    resolve_fmap_assignments,
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


def test_generate_config_reproin_anat_label_sets_the_suffix():
    """A ReproIn anat- label names its BIDS suffix, including ones the vocabulary
    heuristic doesn't know — which used to drop the series silently."""
    series = [
        _series(1, "anat-T1w", "anat", n=200),
        _series(2, "anat-PDw", "anat", n=200),
    ]
    cfg = generate_config(series, FieldmapDetection(strategy="none"))
    anat = [d for d in cfg["descriptions"] if d["datatype"] == "anat"]
    assert sorted(d["suffix"] for d in anat) == ["PDw", "T1w"]


def test_generate_config_reproin_unknown_anat_label_is_not_passed_through():
    """An unrecognized anat- label never becomes the BIDS suffix verbatim.

    A console typo falls back to the vocabulary heuristic — `anat-T1www` still
    recovers as T1w — and a label with nothing to recover from is left
    unconverted rather than writing an invalid suffix into the dataset.
    """
    cfg = generate_config([_series(1, "anat-T1www", "anat", n=200)], FieldmapDetection(strategy="none"))
    assert [d["suffix"] for d in cfg["descriptions"] if d["datatype"] == "anat"] == ["T1w"]

    cfg = generate_config([_series(1, "anat-BOGUS", "anat", n=200)], FieldmapDetection(strategy="none"))
    assert [d for d in cfg["descriptions"] if d["datatype"] == "anat"] == []


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


# ---- project-wide fieldmap bindings ([fmap_mapping]) ----

def _two_pair_session():
    """Two complete 'encoding' pairs plus two bolds whose names match neither."""
    series = [
        _series(9, "se_epi_ap_encoding", "fmap", n=3),
        _series(11, "se_epi_pa_encoding", "fmap", n=3),
        _series(20, "study_r1", "func", n=200),
        _series(30, "test_r1", "func", n=200),
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
    mapping = [
        TaskRunEntry(20, "study_r1", "bold", task="study", run=1),
        TaskRunEntry(30, "test_r1", "bold", task="test", run=1),
    ]
    return series, fmaps, mapping


def _b0_by_task(cfg):
    return {
        d["sidecar_changes"]["TaskName"]: d["sidecar_changes"].get("B0FieldIdentifier")
        for d in cfg["descriptions"]
        if d["suffix"] == "bold"
    }


def test_without_rules_every_task_takes_the_first_pair():
    """The documented no-temporal-proximity default — the baseline a rule corrects."""
    series, fmaps, mapping = _two_pair_session()
    assert _b0_by_task(generate_config(series, fmaps, mapping=mapping)) == {
        "study": "B0map_encoding",
        "test": "B0map_encoding",
    }


def test_fmap_rule_binds_a_task_to_the_later_pair():
    """A run acquired after a re-shot fieldmap can be pointed at that second pair."""
    series, fmaps, mapping = _two_pair_session()
    cfg = generate_config(
        series, fmaps, mapping=mapping, fmap_rules=[FmapRule("test", "encoding-2")]
    )
    # Only the named task moves; the other keeps the automatic binding.
    assert _b0_by_task(cfg) == {
        "study": "B0map_encoding",
        "test": "B0map_encoding-2",
    }


def test_fmap_rule_beats_the_name_match():
    """A rule states, the prefix heuristic infers — explicit wins."""
    series, fmaps, _ = _two_pair_session()
    series = [s for s in series if s.series_number != 30]  # one bold is enough here
    mapping = [TaskRunEntry(20, "study_r1", "bold", task="encoding", run=1)]
    # Bare, the task name prefix-matches group "encoding".
    assert _b0_by_task(generate_config(series, fmaps, mapping=mapping)) == {
        "encoding": "B0map_encoding"
    }
    cfg = generate_config(
        series, fmaps, mapping=mapping, fmap_rules=[FmapRule("encoding", "encoding-2")]
    )
    assert _b0_by_task(cfg) == {"encoding": "B0map_encoding-2"}


def test_fmap_rule_task_is_matched_after_sanitizing():
    """A rule written with an underscore still binds the label that ships."""
    series, fmaps, _ = _two_pair_session()
    series = [s for s in series if s.series_number != 30]  # one bold is enough here
    mapping = [TaskRunEntry(20, "study_r1", "bold", task="free_recall", run=1)]
    cfg = generate_config(
        series, fmaps, mapping=mapping, fmap_rules=[FmapRule("free_recall", "encoding-2")]
    )
    assert _b0_by_task(cfg) == {"freeRecall": "B0map_encoding-2"}


def test_fmap_rule_naming_a_missing_group_raises():
    """Silently falling back would give the run a fieldmap the project didn't ask
    for — the one outcome an explicit binding exists to prevent."""
    series, fmaps, mapping = _two_pair_session()
    with pytest.raises(ValueError) as exc:
        generate_config(
            series, fmaps, mapping=mapping, fmap_rules=[FmapRule("test", "recall")]
        )
    msg = str(exc.value)
    assert "recall" in msg and "does not exist" in msg
    # The message has to name what *is* available or it isn't actionable.
    assert "encoding-2" in msg


def test_fmap_rule_naming_a_half_pair_raises():
    """Binding to a lone AP would hand fMRIPrep a correction it cannot run."""
    series = [
        _series(5, "se_epi_ap", "fmap", n=3),
        _series(6, "se_epi_ap", "fmap", n=3),
        _series(7, "se_epi_pa", "fmap", n=3),
        _series(9, "study_r1", "func", n=200),
    ]
    fmaps = FieldmapDetection(
        strategy="series_number",
        groups={"1": {"ap": 5}, "2": {"ap": 6, "pa": 7}},
        group_entities={"1": "run-1", "2": "run-2"},
    )
    mapping = [TaskRunEntry(9, "study_r1", "bold", task="study", run=1)]
    with pytest.raises(ValueError) as exc:
        generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("study", "1")])
    assert "only one phase-encoding direction" in str(exc.value)


def test_resolve_fmap_assignments_matches_what_is_written():
    """The GUI's binding display is generated by the same call the config is, so
    it cannot drift from the B0FieldIdentifier that actually ships."""
    series, fmaps, mapping = _two_pair_session()
    rules = [FmapRule("test", "encoding-2")]
    resolved = resolve_fmap_assignments(mapping, fmaps, rules)
    assert resolved == {"study": "encoding", "test": "encoding-2"}
    written = _b0_by_task(generate_config(series, fmaps, mapping=mapping, fmap_rules=rules))
    assert {t: f"B0map_{g}" for t, g in resolved.items()} == written


def test_resolve_fmap_assignments_empty_without_fieldmaps():
    _, _, mapping = _two_pair_session()
    assert resolve_fmap_assignments(mapping, FieldmapDetection(strategy="none")) == {}


def test_fmap_rules_config_round_trip():
    rules = [FmapRule("study", "encoding"), FmapRule("test", "encoding-2")]
    section = fmap_rules_to_config_section(rules)
    assert fmap_rules_from_config({"fmap_mapping": section}) == rules


def test_fmap_rules_from_config_tolerates_junk():
    """A hand-edited section must never sink config loading."""
    assert fmap_rules_from_config({}) == []
    assert fmap_rules_from_config({"fmap_mapping": {}}) == []
    section = {"rule": [{"task": "a"}, {"group": "g"}, {"task": " x ", "group": " g "}]}
    assert fmap_rules_from_config({"fmap_mapping": section}) == [FmapRule("x", "g")]
