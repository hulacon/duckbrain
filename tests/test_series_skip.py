"""The project-level series skip — ``[series_skip]``, keyed on description.

Covers TODO #13.1 (the skip half; the editable ``Type`` half lives in
test_series_types.py). The feature is one config section plus one resolution
point, so what is worth pinning is where the naive versions go wrong: a skip
that misses the non-GUI path, a skipped fieldmap half that leaves its partner
behind, a scout earning a "deliberate drop" note for a conversion that was
never going to happen, and a malformed section that quietly converts the very
series the study excluded.
"""

import pytest

from duckbrain.config import (
    load_config,
    save_project_config,
    save_project_series_skip,
    scaffold_project,
)
from duckbrain.core.conversion import generate_session_config
from duckbrain.core.conversion_plan import plan_conversion, plan_warnings
from duckbrain.core.dicom_inspect import SeriesInfo, detect_fieldmaps
from duckbrain.core.series_skip import (
    SKIP_REASON,
    apply_project_skip,
    skip_descriptions_from_config,
    skip_to_config_section,
)


def _series(number, description, **kw):
    return SeriesInfo(
        series_number=number,
        description=description,
        path=f"/tmp/Series_{number}_{description}",
        file_count=kw.pop("file_count", 10),
        **kw,
    )


# One anat, a complete pepolar pair, a bold, and a scout — the minimum that
# exercises the anat-only motivation, the whole-pair rule, and the non-emitting
# fall-through.
def _session():
    return [
        _series(1, "AAhead_scout"),
        _series(2, "t1w_mprage"),
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _series(9, "cmrr_bold_task-food_run-1"),
    ]


def _generated(skip_descriptions=None, skip=None, fmap_rules=None):
    return generate_session_config(
        "unused-because-series-list-is-given",
        "001",
        "01",
        series_list=_session(),
        skip=skip,
        skip_descriptions=skip_descriptions,
        fmap_rules=fmap_rules,
    )


def _emitted_series_numbers(config):
    return {
        d["criteria"]["SeriesNumber"]
        for d in config["descriptions"]
        if "SeriesNumber" in d.get("criteria", {})
    }


# ---- the section -------------------------------------------------------------


def test_the_skip_list_round_trips_through_the_config_section():
    descs = ["fieldmap1_AP", "fieldmap1_PA"]
    section = skip_to_config_section(descs)
    assert skip_descriptions_from_config({"series_skip": section}) == descs
    # The writer normalizes too, so a duplicate or blank never reaches the TOML.
    assert skip_to_config_section(["a", " A ", "", "b"]) == {"descriptions": ["a", "b"]}


def test_no_section_means_no_skips():
    assert skip_descriptions_from_config({}) == []


def test_blank_entries_drop_and_duplicates_collapse_case_insensitively():
    config = {"series_skip": {"descriptions": ["  ", "Food_r1", "food_R1", "b"]}}
    assert skip_descriptions_from_config(config) == ["Food_r1", "b"]


@pytest.mark.parametrize("bad", ["food_r1", 7, [3], [{"description": "x"}]])
def test_a_malformed_section_raises_rather_than_converting_anyway(bad):
    """The fallback for an unreadable skip is converting the series the study
    excluded — the silently-degrading shape CLAUDE.md forbids, so it refuses.
    Same asymmetry type_rules_from_config makes, for the same reason."""
    with pytest.raises(ValueError, match="series_skip"):
        skip_descriptions_from_config({"series_skip": {"descriptions": bad}})


def test_saving_the_skip_list_touches_only_its_own_section(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"project": {"name": "keep-me"}})
    save_project_series_skip(str(proj), ["fieldmap1_AP"])
    config = load_config(project_dir=str(proj))
    assert skip_descriptions_from_config(config) == ["fieldmap1_AP"]
    assert config["project"]["name"] == "keep-me"  # other sections survive

    # An empty list removes the section — the way back that doesn't involve TOML.
    save_project_series_skip(str(proj), [])
    assert skip_descriptions_from_config(load_config(project_dir=str(proj))) == []


# ---- resolution --------------------------------------------------------------


def test_a_skip_matches_case_and_whitespace_insensitively():
    from duckbrain.core.dicom_inspect import classify_series

    series = _session()
    classify_series(series)
    assert apply_project_skip(series, ["  CMRR_Bold_Task-Food_Run-1 "]) == {9}
    assert apply_project_skip(series, []) == set()  # nothing declared, nothing touched


def test_a_skip_resolves_only_series_that_would_otherwise_emit():
    """A scout matching a skipped description must not earn a 'deliberate drop'
    note for a conversion that was never going to happen."""
    from duckbrain.core.dicom_inspect import classify_series

    series = _session()
    classify_series(series)
    assert apply_project_skip(series, ["AAhead_scout"]) == set()
    assert series[0].drop_reason == ""


def test_a_resolved_skip_carries_the_project_reason_into_the_plan():
    """Without the reason, a project-skipped run reads as 'matches no
    description' — the warning that means a bug, aimed at a decision."""
    from duckbrain.core.dicom_inspect import classify_series

    series = _session()
    classify_series(series)
    apply_project_skip(series, ["cmrr_bold_task-food_run-1"])
    assert series[4].drop_reason == SKIP_REASON

    config = _generated(skip_descriptions=["cmrr_bold_task-food_run-1"])
    plan = plan_conversion(config, series, subject="001", session="01")
    warnings = plan_warnings(plan, detect_fieldmaps(series))
    notes = [w for w in warnings if w.kind == "deliberate-drop" and 9 in w.series]
    assert len(notes) == 1 and SKIP_REASON in notes[0].message
    assert not [w for w in warnings if w.kind == "dropped" and w.severity == "warning"]


# ---- the non-GUI path, which is the part with the decision in it -------------


def test_generate_session_config_applies_the_project_skip():
    """#13.1's own note: the skip is applied *inside* the function, next to
    type_rules, because a description resolves to numbers only per session."""
    config = _generated(skip_descriptions=["cmrr_bold_task-food_run-1"])
    assert 9 not in _emitted_series_numbers(config)
    assert 2 in _emitted_series_numbers(config)  # the anat is untouched


def test_the_project_skip_merges_with_the_per_session_one():
    config = _generated(skip_descriptions=["cmrr_bold_task-food_run-1"], skip={2})
    assert _emitted_series_numbers(config).isdisjoint({2, 9})


def test_skipping_one_fieldmap_half_takes_the_whole_pair_and_unbinds_the_bold():
    """Riding the existing skip mechanism is what buys this: half a pair is not
    half a fieldmap, and the surviving half must not be written either."""
    config = _generated(skip_descriptions=["se_epi_ap"])
    emitted = _emitted_series_numbers(config)
    assert emitted.isdisjoint({3, 4})
    bold = next(d for d in config["descriptions"] if d["criteria"]["SeriesNumber"] == 9)
    assert "B0FieldSource" not in (bold.get("sidecar_changes") or {})


def test_the_anat_only_study_is_one_list():
    """The motivating case: five of the LCNI corpus's fifteen studies curate
    anat only, ~336 unticks on WMS alone. Here it is as one declaration."""
    config = _generated(skip_descriptions=["cmrr_bold_task-food_run-1", "se_epi_ap", "se_epi_pa"])
    assert _emitted_series_numbers(config) == {2}


def test_a_project_binding_to_a_skipped_pair_fails_loudly():
    """The project asked for a binding the project's own skip removed — two
    config sections in contradiction, which must be an error, not a silent
    fall-through to uncorrected."""
    from duckbrain.core.dcm2bids_config import FmapRule
    from duckbrain.core.dicom_inspect import classify_series

    series = _session()
    classify_series(series)
    group = next(iter(detect_fieldmaps(series).groups))
    with pytest.raises(ValueError, match="does not exist in this session"):
        _generated(
            skip_descriptions=["se_epi_ap"],
            fmap_rules=[FmapRule(task="food", group=group)],
        )
