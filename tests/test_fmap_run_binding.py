"""Run-level fieldmap bindings — the case a task-keyed rule cannot express.

A fieldmap re-shot *within* one task means the runs before and after it want
different pairs. `FmapRule` is keyed on task, so it had no way to say that; it
now takes an optional `run`, with `run=None` keeping its old meaning (every run)
so existing `[fmap_mapping]` sections load unchanged.

See docs/conversion-legibility.md, "The granularity decision".
"""

import pytest

from duckbrain.core.dcm2bids_config import (
    FmapRule,
    TaskRunEntry,
    fmap_rules_from_config,
    fmap_rules_to_config_section,
    generate_config,
    resolve_fmap_assignments,
)
from duckbrain.core.dicom_inspect import FieldmapDetection, SeriesInfo


def _series(num, desc, cls, n=300):
    s = SeriesInfo(series_number=num, description=desc, path=None, file_count=n)
    s.classification = cls
    return s


def _reshot_mid_task():
    """One task, three runs, with a second pair shot between run 1 and run 2.

    The concrete shape the decision was made on: runs 2 and 3 were acquired after
    the re-shoot, so they want pair 2 while run 1 keeps pair 1.
    """
    series = [
        _series(9, "se_epi_ap_encoding", "fmap", n=3),
        _series(11, "se_epi_pa_encoding", "fmap", n=3),
        _series(20, "encode_r1", "func", n=200),
        _series(30, "se_epi_ap_encoding", "fmap", n=3),
        _series(32, "se_epi_pa_encoding", "fmap", n=3),
        _series(40, "encode_r2", "func", n=200),
        _series(50, "encode_r3", "func", n=200),
    ]
    fmaps = FieldmapDetection(
        strategy="series_description",
        groups={"encoding": {"ap": 9, "pa": 11}, "encoding-2": {"ap": 30, "pa": 32}},
        group_entities={
            "encoding": "acq-encoding_run-1",
            "encoding-2": "acq-encoding_run-2",
        },
    )
    mapping = [
        TaskRunEntry(20, "encode_r1", "bold", task="encode", run=1),
        TaskRunEntry(40, "encode_r2", "bold", task="encode", run=2),
        TaskRunEntry(50, "encode_r3", "bold", task="encode", run=3),
    ]
    return series, fmaps, mapping


def _b0_by_entities(cfg):
    return {
        d["custom_entities"]: d["sidecar_changes"].get("B0FieldSource")
        for d in cfg["descriptions"]
        if d["suffix"] == "bold"
    }


# ---- the case that motivated this ----


def test_runs_of_one_task_can_take_different_pairs():
    series, fmaps, mapping = _reshot_mid_task()
    rules = [
        FmapRule("encode", "encoding-2", run=2),
        FmapRule("encode", "encoding-2", run=3),
    ]
    assert _b0_by_entities(generate_config(series, fmaps, mapping=mapping, fmap_rules=rules)) == {
        "task-encode_run-1": "B0map_encoding",
        "task-encode_run-2": "B0map_encoding-2",
        "task-encode_run-3": "B0map_encoding-2",
    }


def test_a_run_rule_beats_the_task_wide_rule():
    """Specific beats general: 'this task uses pair 1, except run 3'."""
    series, fmaps, mapping = _reshot_mid_task()
    rules = [FmapRule("encode", "encoding"), FmapRule("encode", "encoding-2", run=3)]
    assert _b0_by_entities(generate_config(series, fmaps, mapping=mapping, fmap_rules=rules)) == {
        "task-encode_run-1": "B0map_encoding",
        "task-encode_run-2": "B0map_encoding",
        "task-encode_run-3": "B0map_encoding-2",
    }


def test_one_run_can_opt_out_while_its_siblings_stay_corrected():
    series, fmaps, mapping = _reshot_mid_task()
    rules = [FmapRule("encode", "none", run=2)]
    written = _b0_by_entities(generate_config(series, fmaps, mapping=mapping, fmap_rules=rules))
    assert written["task-encode_run-2"] is None
    assert written["task-encode_run-1"] == "B0map_encoding"


def test_resolve_reports_the_per_run_binding():
    series, fmaps, mapping = _reshot_mid_task()
    rules = [FmapRule("encode", "encoding-2", run=3)]
    assert resolve_fmap_assignments(mapping, fmaps, rules) == {
        ("encode", 1): "encoding",
        ("encode", 2): "encoding",
        ("encode", 3): "encoding-2",
    }


def test_an_unsatisfiable_run_rule_names_the_run_it_came_from():
    series, fmaps, mapping = _reshot_mid_task()
    with pytest.raises(ValueError, match=r"task 'encode' run 2"):
        generate_config(
            series,
            fmaps,
            mapping=mapping,
            fmap_rules=[FmapRule("encode", "nosuchgroup", run=2)],
        )


# ---- nothing older changes ----


def test_a_task_wide_rule_still_binds_every_run():
    """run=None keeps its old meaning, so pre-existing configs are unaffected."""
    series, fmaps, mapping = _reshot_mid_task()
    rules = [FmapRule("encode", "encoding-2")]
    written = _b0_by_entities(generate_config(series, fmaps, mapping=mapping, fmap_rules=rules))
    assert set(written.values()) == {"B0map_encoding-2"}


def test_config_rows_without_a_run_still_load():
    """An [fmap_mapping] written before run-level bindings existed."""
    section = {"rule": [{"task": "encode", "group": "encoding-2"}]}
    assert fmap_rules_from_config({"fmap_mapping": section}) == [
        FmapRule("encode", "encoding-2", None)
    ]


def test_run_survives_a_config_round_trip():
    rules = [FmapRule("encode", "encoding"), FmapRule("encode", "encoding-2", run=3)]
    section = fmap_rules_to_config_section(rules)
    # The task-wide rule keeps the two-key row it has always had.
    assert section["rule"][0] == {"task": "encode", "group": "encoding"}
    assert section["rule"][1] == {"task": "encode", "group": "encoding-2", "run": 3}
    assert fmap_rules_from_config({"fmap_mapping": section}) == rules


@pytest.mark.parametrize("bad", ["", None, "not-a-number"])
def test_an_unparseable_run_falls_back_to_task_wide(bad):
    section = {"rule": [{"task": "encode", "group": "encoding", "run": bad}]}
    assert fmap_rules_from_config({"fmap_mapping": section})[0].run is None


# ---- keeping the saved project config readable ----


def test_collapse_keeps_one_rule_when_every_run_agrees():
    from duckbrain.core.dcm2bids_config import collapse_fmap_rules

    per_run = [
        FmapRule("encode", "encoding", run=1),
        FmapRule("encode", "encoding", run=2),
        FmapRule("encode", "encoding", run=3),
    ]
    assert collapse_fmap_rules(per_run) == [FmapRule("encode", "encoding", None)]


def test_collapse_keeps_per_run_rows_only_where_they_differ():
    from duckbrain.core.dcm2bids_config import collapse_fmap_rules

    rules = [
        FmapRule("encode", "encoding", run=1),
        FmapRule("encode", "encoding-2", run=2),
        FmapRule("rest", "encoding", run=1),
    ]
    assert collapse_fmap_rules(rules) == [
        FmapRule("encode", "encoding", 1),
        FmapRule("encode", "encoding-2", 2),
        FmapRule("rest", "encoding", None),
    ]
