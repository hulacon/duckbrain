"""Tests for the task/run mapping + dcm2bids config generation."""

import re

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
from duckbrain.core.dicom_inspect import FieldmapDetection, detect_fieldmaps


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
    entities = sorted(d["custom_entities"] for d in cfg["descriptions"] if d["datatype"] == "fmap")
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
    assert bold["sidecar_changes"]["B0FieldSource"] == "B0map_2"


# ---- B0 identifiers must survive nipype ----
#
# sdcflows names a nipype node after the B0FieldIdentifier it reads, and nipype
# validates node names against this. A group name off the scanner ("2.5mm")
# reached the sidecar verbatim and aborted every fMRIPrep run on divatten_beta
# at workflow-build time: `Node name "out_B0map_2.5mm" is not valid`.
_NIPYPE_NODE_NAME = re.compile(r"^[\w-]+$")


def test_b0_identifier_from_a_real_series_name_is_a_legal_node_name():
    """`se_epi_2.5mm_ap` must not put a period in B0FieldIdentifier.

    Driven from the series descriptions rather than a hand-built
    FieldmapDetection, because the period enters at group *detection* — a test
    that skips that step passes while the pipeline it stands for fails. These
    are the literal series names under
    /projects/lcni/dcm/hulacon/Hutchinson/divatten.
    """
    series = [
        _series(6, "se_epi_2.5mm_ap", "fmap", n=3),
        _series(7, "se_epi_2.5mm_pa", "fmap", n=3),
        _series(9, "div_perFace_perTone_r1", "func", n=200),
    ]
    cfg = generate_config(series, detect_fieldmaps(series))

    fmaps = [d for d in cfg["descriptions"] if d["datatype"] == "fmap"]
    bold = [d for d in cfg["descriptions"] if d["suffix"] == "bold"][0]
    identifiers = {d["sidecar_changes"]["B0FieldIdentifier"] for d in fmaps}

    assert identifiers == {"B0map_25mm"}
    # Both halves of the pair, and the bold that consumes them, or fMRIPrep
    # estimates a field it then applies to nothing.
    assert len(fmaps) == 2
    assert bold["sidecar_changes"]["B0FieldSource"] == "B0map_25mm"

    for value in identifiers | {bold["sidecar_changes"]["B0FieldSource"]}:
        assert _NIPYPE_NODE_NAME.match(f"out_{value}"), f"nipype rejects out_{value}"


def test_b0_identifier_keeps_hyphens_and_underscores():
    """Only *illegal* characters go; the repeat-pair suffix must survive.

    nipype accepts `-` and `_`, and they carry meaning here: `encoding-2` is the
    second pair of a reacquired group, and sub_ses distinguishes subjects.
    Reaching for sanitize_task_label (which enforces BIDS-entity rules, strictly
    alphanumeric) would collapse `encoding-2` onto `encoding` and merge two
    distinct fieldmaps.
    """
    series, fmaps, mapping = _two_pair_session()
    cfg = generate_config(series, fmaps, mapping=mapping, subject="001", session="01")
    written = {
        d["sidecar_changes"]["B0FieldIdentifier"]
        for d in cfg["descriptions"]
        if d["datatype"] == "fmap"
    }
    assert written == {"B0map_encoding_sub001ses01", "B0map_encoding-2_sub001ses01"}
    for value in written:
        assert _NIPYPE_NODE_NAME.match(f"out_{value}")


def test_b0_identifiers_colliding_after_stripping_raise():
    """Two groups differing only in punctuation must fail, not silently merge.

    `2.5mm` and `25mm` both reduce to `B0map_25mm`; fMRIPrep would take the four
    images as one estimator and correct every bold from the wrong pair — output
    that looks processed and is deformed. The rule this repo runs on: a thing
    that cannot do what it says raises.
    """
    series = [
        _series(6, "se_epi_2.5mm_ap", "fmap", n=3),
        _series(7, "se_epi_2.5mm_pa", "fmap", n=3),
        _series(8, "se_epi_25mm_ap", "fmap", n=3),
        _series(9, "se_epi_25mm_pa", "fmap", n=3),
    ]
    fmaps = detect_fieldmaps(series)
    assert set(fmaps.groups) == {"2.5mm", "25mm"}

    with pytest.raises(ValueError, match="reduce to the B0 identifier 'B0map_25mm'"):
        generate_config(series, fmaps)


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
    cfg = generate_config(
        [_series(1, "anat-T1www", "anat", n=200)], FieldmapDetection(strategy="none")
    )
    assert [d["suffix"] for d in cfg["descriptions"] if d["datatype"] == "anat"] == ["T1w"]

    cfg = generate_config(
        [_series(1, "anat-BOGUS", "anat", n=200)], FieldmapDetection(strategy="none")
    )
    assert [d for d in cfg["descriptions"] if d["datatype"] == "anat"] == []


def test_generate_config_single_fmap_pair_unchanged():
    """A lone pair keeps the bare dir- entity (no acq-/run-), preserving prior output."""
    series = [
        _series(6, "se_epi_ap", "fmap", n=3),
        _series(7, "se_epi_pa", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(strategy="series_number", groups={"": {"ap": 6, "pa": 7}})
    cfg = generate_config(series, fmaps)
    entities = sorted(d["custom_entities"] for d in cfg["descriptions"] if d["datatype"] == "fmap")
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
        d["sidecar_changes"]["TaskName"]: d["sidecar_changes"].get("B0FieldSource")
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
        generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("test", "recall")])
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
    # Keyed on (task, run): a binding is per-run, so two runs of one task can
    # legitimately differ and a task-keyed report could not show it.
    assert resolved == {("study", 1): "encoding", ("test", 1): "encoding-2"}
    written = _b0_by_task(generate_config(series, fmaps, mapping=mapping, fmap_rules=rules))
    assert {t: f"B0map_{g}" for (t, _run), g in resolved.items()} == written


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


# ---- sessions with no fieldmaps, and the "none" opt-out ----


def _no_fmap_session():
    series = [_series(1, "t1_mprage", "anat", n=200), _series(9, "study_r1", "func", n=200)]
    mapping = [TaskRunEntry(9, "study_r1", "bold", task="study", run=1)]
    return series, FieldmapDetection(strategy="none"), mapping


def test_no_fieldmaps_writes_no_b0_field_and_no_fmap_descriptions():
    """The plain no-fieldmap session: nothing to correct with, nothing claimed."""
    series, fmaps, mapping = _no_fmap_session()
    cfg = generate_config(series, fmaps, mapping=mapping)
    assert _b0_by_task(cfg) == {"study": None}
    assert [d for d in cfg["descriptions"] if d["datatype"] == "fmap"] == []


def test_binding_a_group_raises_when_the_session_has_no_fieldmaps():
    """The gap the 'were any detected' guard left: a project-wide rule naming a
    group must fail here too, not be skipped along with the whole fieldmap step."""
    series, fmaps, mapping = _no_fmap_session()
    with pytest.raises(ValueError) as exc:
        generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("study", "encoding")])
    msg = str(exc.value)
    assert "does not exist" in msg
    # The available-groups line must not read as naming the 'none' sentinel.
    assert "Groups detected here: none." not in msg


def test_none_opts_a_task_out_of_distortion_correction():
    """'none' is always satisfiable — including where there is nothing to bind."""
    series, fmaps, mapping = _no_fmap_session()
    cfg = generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("study", "none")])
    assert _b0_by_task(cfg) == {"study": None}


def test_none_opts_out_even_when_pairs_are_available():
    """A run that shouldn't be corrected, in a session that could correct it."""
    series, fmaps, mapping = _two_pair_session()
    cfg = generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("test", "none")])
    assert _b0_by_task(cfg) == {"study": "B0map_encoding", "test": None}


def test_none_is_case_insensitive():
    series, fmaps, mapping = _two_pair_session()
    cfg = generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("test", "None")])
    assert _b0_by_task(cfg)["test"] is None


def test_a_real_group_named_none_wins_over_the_sentinel():
    """Far-fetched (it needs a series like se_epi_ap_none), but the data has to
    win over a reserved word or the binding would mean something else entirely."""
    series = [
        _series(5, "se_epi_ap_none", "fmap", n=3),
        _series(6, "se_epi_pa_none", "fmap", n=3),
        _series(9, "study_r1", "func", n=200),
    ]
    fmaps = FieldmapDetection(strategy="series_description", groups={"none": {"ap": 5, "pa": 6}})
    mapping = [TaskRunEntry(9, "study_r1", "bold", task="study", run=1)]
    cfg = generate_config(series, fmaps, mapping=mapping, fmap_rules=[FmapRule("study", "none")])
    assert _b0_by_task(cfg) == {"study": "B0map_none"}


def test_resolve_reports_none_rather_than_omitting_the_task():
    """Opting out is a decision worth seeing in the GUI table, not an absence."""
    series, fmaps, mapping = _two_pair_session()
    resolved = resolve_fmap_assignments(mapping, fmaps, [FmapRule("test", "none")])
    assert resolved == {("study", 1): "encoding", ("test", 1): "none"}


def test_resolve_is_empty_for_an_unbound_session_without_fieldmaps():
    _, fmaps, mapping = _no_fmap_session()
    assert resolve_fmap_assignments(mapping, fmaps) == {}


# ---- diffusion (TODO #19.1) ----


def _dwi(num, desc, reference=False, acq=""):
    s = _series(num, desc, "dwi", n=104 if not reference else 1)
    if reference:
        s.suffix_hint = "sbref"
    s.acq_label = acq
    return s


def _dwi_plan(series):
    """The `(path, id)` of every dwi description, in series order."""
    cfg = generate_config(series, FieldmapDetection(strategy="none"), subject="X", session="01")
    return [
        (d["criteria"]["SeriesNumber"], d["suffix"], d.get("custom_entities", ""), d["id"])
        for d in cfg["descriptions"]
        if d["datatype"] == "dwi"
    ]


def test_a_diffusion_series_with_no_direction_token_still_emits():
    """`_dwi_description` returns a description unconditionally, unlike the anat
    emitter. `dir-` is decoration, not a precondition — a `return None` here would
    drop the commonest single-direction acquisition there is."""
    assert _dwi_plan([_dwi(4, "ep2d_diff_mddw")]) == [(4, "dwi", "", "dwi-dwi")]


def test_four_directions_get_four_distinct_files_and_no_run_entity():
    """The mmmsourcedata fixture's shape: one sequence, four phase encodings.
    Nothing repeats, so nothing is numbered."""
    series = [
        _dwi(n, f"cmrr_diff_3shell_{d}")
        for n, d in ((23, "ap"), (32, "pa"), (41, "rl"), (50, "lr"))
    ]

    assert _dwi_plan(series) == [
        (23, "dwi", "dir-AP", "dwi-dwi-ap"),
        (32, "dwi", "dir-PA", "dwi-dwi-pa"),
        (41, "dwi", "dir-RL", "dwi-dwi-rl"),
        (50, "dwi", "dir-LR", "dwi-dwi-lr"),
    ]


def test_a_diffusion_reference_is_written_as_an_sbref_beside_its_volume_series():
    series = [
        _dwi(22, "cmrr_diff_3shell_ap_SBRef", reference=True),
        _dwi(23, "cmrr_diff_3shell_ap"),
    ]

    assert _dwi_plan(series) == [
        (22, "sbref", "dir-AP", "dwi-sbref-ap"),
        (23, "dwi", "dir-AP", "dwi-dwi-ap"),
    ]


def test_an_nd_twin_puts_acq_before_dir():
    """BIDS fixes the order and dcm2bids writes `custom_entities` through verbatim.
    The ND machinery is classification-agnostic, so diffusion really does arrive
    here carrying an `acq_label` under `nd_duplicates = "both"`."""
    series = [
        _dwi(23, "cmrr_diff_3shell_ap", acq="dis"),
        _dwi(24, "cmrr_diff_3shell_ap_ND", acq="nd"),
    ]

    assert [entities for _, _, entities, _ in _dwi_plan(series)] == [
        "acq-dis_dir-AP",
        "acq-nd_dir-AP",
    ]


def test_a_repeated_direction_is_numbered_and_its_references_follow_their_own_volume():
    """**The unbalanced case, which is the only one that proves anything.**

    Three references, but the middle volume series was aborted and is not in the
    session. Numbering each suffix independently would give the references
    run-1/2/3 and the volumes run-1/2, so `dir-AP_run-2_sbref` would claim to be
    the reference for the *third* acquisition — wrong pairing, no warning. Each
    reference must take the run of the volume series it actually belongs to.
    """
    series = [
        _dwi(1, "cmrr_diff_ap_SBRef", reference=True),
        _dwi(2, "cmrr_diff_ap"),
        _dwi(3, "cmrr_diff_ap_SBRef", reference=True),  # its volume series aborted
        _dwi(5, "cmrr_diff_ap_SBRef", reference=True),
        _dwi(6, "cmrr_diff_ap"),
    ]

    assert _dwi_plan(series) == [
        (1, "sbref", "dir-AP_run-1", "dwi-sbref-ap-run1"),
        (2, "dwi", "dir-AP_run-1", "dwi-dwi-ap-run1"),
        (3, "sbref", "dir-AP", "dwi-sbref-ap"),
        (5, "sbref", "dir-AP_run-2", "dwi-sbref-ap-run2"),
        (6, "dwi", "dir-AP_run-2", "dwi-dwi-ap-run2"),
    ]


def test_the_reference_left_over_is_reported_as_an_orphan_rather_than_renumbered():
    """It keeps unnumbered entities, so it matches no volume series and the plan's
    `orphan-sbref` check names it — the honest outcome for a reference whose
    volume series is not being written."""
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings

    series = [
        _dwi(1, "cmrr_diff_ap_SBRef", reference=True),
        _dwi(2, "cmrr_diff_ap"),
        _dwi(3, "cmrr_diff_ap_SBRef", reference=True),
        _dwi(5, "cmrr_diff_ap_SBRef", reference=True),
        _dwi(6, "cmrr_diff_ap"),
    ]
    detection = FieldmapDetection(strategy="none")
    cfg = generate_config(series, detection, subject="X", session="01")
    plan = plan_conversion(cfg, series, subject="X", session="01")

    orphans = [w for w in plan_warnings(plan, detection) if w.kind == "orphan-sbref"]
    assert [w.series for w in orphans] == [[3]]
    assert "no DWI run is being written" in orphans[0].message


def test_skipping_a_volume_series_leaves_its_reference_an_orphan():
    """The `convert` checkbox became live for diffusion the moment it could emit,
    so unticking one row of a pair is reachable — and is what this reports."""
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings

    series = [_dwi(22, "cmrr_diff_ap_SBRef", reference=True), _dwi(23, "cmrr_diff_ap")]
    detection = FieldmapDetection(strategy="none")
    cfg = generate_config(series, detection, subject="X", session="01", skip=[23])
    plan = plan_conversion(cfg, series, subject="X", session="01")

    assert [f.series_number for f in plan.files] == [22]
    assert [w.kind for w in plan_warnings(plan, detection) if w.kind == "orphan-sbref"] == [
        "orphan-sbref"
    ]


def test_diffusion_carries_no_b0_field_source():
    """Deliberate: `resolve_fmap_assignments` renders the GUI's fieldmap column
    from `role == "bold"` only, so a binding chosen here would be applied silently
    and could not be overridden. See `_dwi_description`."""
    series = [
        _series(5, "se_epi_ap", "fmap", n=3),
        _series(6, "se_epi_pa", "fmap", n=3),
        _dwi(23, "cmrr_diff_3shell_ap"),
    ]
    fmaps = detect_fieldmaps(series)
    cfg = generate_config(series, fmaps, subject="X", session="01")

    (dwi,) = [d for d in cfg["descriptions"] if d["datatype"] == "dwi"]
    assert "sidecar_changes" not in dwi
    # The fieldmap pair itself is untouched by any of this.
    assert fmaps.groups == {"": {"ap": 5, "pa": 6}}


def test_anat_and_diffusion_disambiguate_independently():
    """Two T1w repeats and two same-direction diffusion repeats in one session:
    each datatype numbers within itself and neither leaks into the other."""
    series = [
        _series(1, "mprage", "anat"),
        _series(2, "mprage", "anat"),
        _dwi(3, "cmrr_diff_ap"),
        _dwi(4, "cmrr_diff_ap"),
    ]
    cfg = generate_config(series, FieldmapDetection(strategy="none"), subject="X", session="01")
    entities = {
        d["criteria"]["SeriesNumber"]: d.get("custom_entities", "") for d in cfg["descriptions"]
    }

    assert entities == {1: "run-1", 2: "run-2", 3: "dir-AP_run-1", 4: "dir-AP_run-2"}
