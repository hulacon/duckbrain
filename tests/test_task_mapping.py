"""Tests for the project-wide task mapping (define once, inherit per subject).

Layering under test: heuristic -> project-wide rules -> per-session edits. Rules
fix the *task* label only; run numbers stay positional and per-session. Per-session
edits are already the `mapping=` override covered in test_dcm2bids_config.py.
"""

from duckbrain.core.dicom_inspect import SeriesInfo, FieldmapDetection
from duckbrain.core.dcm2bids_config import (
    TaskRule,
    TaskRunEntry,
    build_task_run_mapping,
    generate_config,
    task_rules_from_mapping,
    task_rules_from_config,
    task_rules_to_config_section,
)


def _series(num, desc, cls, n=300):
    s = SeriesInfo(series_number=num, description=desc, path=None, file_count=n)
    s.classification = cls
    return s


# ---- rules override the heuristic's task ----

def test_rule_overrides_heuristic_task():
    # Heuristic would parse "MB4_rest" -> task "MB4Rest"; a rule renames it.
    series = [_series(9, "MB4_rest", "func")]
    rules = [TaskRule(description="MB4_rest", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    assert mapping[0].task == "rest"


def test_rule_match_is_case_and_whitespace_insensitive():
    series = [_series(9, "  Faces_Run1  ", "func")]
    rules = [TaskRule(description="faces_run1", task="faces")]
    mapping = build_task_run_mapping(series, rules=rules)
    assert mapping[0].task == "faces"
    # run still comes from the name token, not the rule
    assert mapping[0].run == 1


def test_rule_preserves_name_run_token():
    # A rule renames the task but the run token in the name is still honored.
    series = [_series(9, "cmrr_bold_task-x_run-3", "func")]
    rules = [TaskRule(description="cmrr_bold_task-x_run-3", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    assert (mapping[0].task, mapping[0].run) == ("rest", 3)


def test_rule_leaves_run_to_autocount_when_name_has_none():
    series = [
        _series(5, "restingBOLD", "func"),
        _series(9, "restingBOLD", "func"),
    ]
    rules = [TaskRule(description="restingBOLD", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    # both renamed to 'rest', runs stay positional 1,2 (no collision)
    assert [(e.task, e.run) for e in mapping] == [("rest", 1), ("rest", 2)]


def test_unmatched_series_falls_back_to_heuristic():
    series = [
        _series(5, "MB4_rest", "func"),
        _series(9, "cmrr_mbep2d_bold_task-encoding_run-1", "func"),
    ]
    rules = [TaskRule(description="MB4_rest", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    by_series = {e.series_number: e for e in mapping}
    assert by_series[5].task == "rest"           # from rule
    assert by_series[9].task == "encoding"        # from heuristic


def test_sbref_inherits_rule_via_its_bold():
    series = [
        _series(9, "MB4_rest", "func"),
        _series(8, "MB4_rest_SBRef", "sbref", n=1),
    ]
    rules = [TaskRule(description="MB4_rest", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    by_series = {e.series_number: e for e in mapping}
    # sbref inherits its bold's task (renamed) and run (autocount -> 1)
    assert (by_series[8].task, by_series[8].run) == ("rest", 1)


def test_sbref_without_bold_still_matches_rule_on_its_base():
    # A lone SBRef (no matching BOLD) still honors a rule on its base description.
    series = [_series(8, "MB4_rest_SBRef", "sbref", n=1)]
    rules = [TaskRule(description="MB4_rest", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    assert mapping[0].task == "rest"


def test_no_rules_is_identical_to_heuristic():
    series = [_series(5, "attention", "func"), _series(9, "attention", "func")]
    assert build_task_run_mapping(series, rules=None) == build_task_run_mapping(series)
    assert build_task_run_mapping(series, rules=[]) == build_task_run_mapping(series)


# ---- the "define once, inherit across subjects" promise ----

def test_same_rules_apply_across_subjects_with_different_series_numbers():
    """Two subjects, same protocol (same descriptions) but different SeriesNumbers,
    resolve to the same task under one rule set — the point of a project map."""
    rules = [TaskRule(description="MB4_rest", task="rest")]
    sub_a = [_series(9, "MB4_rest", "func")]
    sub_b = [_series(14, "MB4_rest", "func")]   # different acquisition order
    a = build_task_run_mapping(sub_a, rules=rules)
    b = build_task_run_mapping(sub_b, rules=rules)
    assert a[0].task == b[0].task == "rest"


def test_repeated_task_never_collides_on_run_across_subjects():
    """Regression: a rule must not pin run. Two subjects each acquiring the same
    task twice must both get distinct run-1/run-2, not a shared fixed run."""
    rules = task_rules_from_mapping(
        [  # a reviewed subject where both repeats were renamed to 'rest'
            TaskRunEntry(9, "MB4_rest", "bold", "rest", 1),
            TaskRunEntry(21, "MB4_rest", "bold", "rest", 2),
        ]
    )
    sub2 = [_series(14, "MB4_rest", "func"), _series(30, "MB4_rest", "func")]
    m2 = build_task_run_mapping(sub2, rules=rules)
    assert [(e.task, e.run) for e in m2] == [("rest", 1), ("rest", 2)]


def test_rules_flow_through_generate_config_entities():
    series = [_series(9, "MB4_rest", "func"), _series(21, "MB4_rest", "func")]
    rules = [TaskRule(description="MB4_rest", task="rest")]
    mapping = build_task_run_mapping(series, rules=rules)
    cfg = generate_config(series, FieldmapDetection(strategy="none"), mapping=mapping)
    entities = sorted(d["custom_entities"] for d in cfg["descriptions"])
    assert entities == ["task-rest_run-1", "task-rest_run-2"]


# ---- collapse a reviewed session back into rules ----

def test_task_rules_from_mapping_keeps_bold_skips_sbref():
    entries = [
        TaskRunEntry(9, "MB4_rest", "bold", "rest", 1),
        TaskRunEntry(8, "MB4_rest_SBRef", "sbref", "rest", 1),
        TaskRunEntry(11, "faces", "bold", "faces", None),
    ]
    rules = task_rules_from_mapping(entries)
    got = {(r.description, r.task) for r in rules}
    assert got == {("MB4_rest", "rest"), ("faces", "faces")}


def test_task_rules_from_mapping_dedupes_last_wins():
    entries = [
        TaskRunEntry(9, "rest", "bold", "restOLD", 1),
        TaskRunEntry(21, "rest", "bold", "rest", 2),
    ]
    rules = task_rules_from_mapping(entries)
    assert len(rules) == 1
    assert rules[0].task == "rest"


# ---- (de)serialization round-trip ----

def test_rules_config_roundtrip():
    rules = [TaskRule("MB4_rest", "rest"), TaskRule("faces_run1", "faces")]
    section = task_rules_to_config_section(rules)
    assert section["rule"] == [
        {"description": "MB4_rest", "task": "rest"},
        {"description": "faces_run1", "task": "faces"},
    ]
    back = task_rules_from_config({"task_mapping": section})
    assert [(r.description, r.task) for r in back] == [
        ("MB4_rest", "rest"),
        ("faces_run1", "faces"),
    ]


def test_task_rules_from_config_tolerates_malformed_rows():
    section = {
        "rule": [
            {"description": "ok", "task": "t"},
            {"description": "", "task": "skipme"},      # no description
            {"description": "notask"},                   # no task
            {"description": "legacy", "task": "l", "run": 2},  # legacy run ignored
        ]
    }
    rules = task_rules_from_config({"task_mapping": section})
    got = {(r.description, r.task) for r in rules}
    assert got == {("ok", "t"), ("legacy", "l")}


def test_task_rules_from_config_empty_when_section_absent():
    assert task_rules_from_config({}) == []
    assert task_rules_from_config({"task_mapping": {}}) == []


# ---- persistence preserves other project settings ----

def test_save_project_task_map_preserves_other_keys(tmp_path):
    # Read the project file directly (not load_config) to stay isolated from the
    # developer's real user config / env.
    from duckbrain.config import (
        save_project_config,
        save_project_task_map,
        _load_toml,
        project_config_path,
    )

    save_project_config(tmp_path, {"project": {"name": "study"}, "slurm": {"account": "lab"}})
    save_project_task_map(tmp_path, [TaskRule("MB4_rest", "rest")])

    data = _load_toml(project_config_path(tmp_path))
    assert data["project"]["name"] == "study"          # untouched
    assert data["slurm"]["account"] == "lab"           # untouched
    rules = task_rules_from_config(data)
    assert [(r.description, r.task) for r in rules] == [("MB4_rest", "rest")]


def test_save_project_task_map_empty_removes_section(tmp_path):
    from duckbrain.config import (
        save_project_task_map,
        _load_toml,
        project_config_path,
    )

    save_project_task_map(tmp_path, [TaskRule("MB4_rest", "rest")])
    save_project_task_map(tmp_path, [])   # clear
    data = _load_toml(project_config_path(tmp_path))
    assert "task_mapping" not in data
    assert task_rules_from_config(data) == []
