"""Declared series types — the project-level tier above the header and the name.

Covers TODO #13.1. The feature is one unlocked column plus a great deal of care
about what a declaration is allowed to say, so most of what is worth pinning here
is the *refusals*: a declaration that quietly reverted to the guess it was
written to correct would be the silently-degrading control CLAUDE.md forbids, and
the naive version of this feature has exactly that shape.
"""

import pytest

from duckbrain.config import (
    load_config,
    save_project_config,
    save_project_series_types,
    scaffold_project,
)
from duckbrain.core.dcm2bids_config import anat_suffix_for, generate_config
from duckbrain.core.dicom_header import SeriesHeader
from duckbrain.core.dicom_inspect import FieldmapDetection, SeriesInfo, classify_series
from duckbrain.core.series_types import (
    DECLARABLE_TYPES,
    TypeRule,
    format_type_token,
    parse_type_token,
    token_datatype,
    type_rules_from_config,
    type_rules_to_config_section,
)


def _series(number, description, **kw):
    return SeriesInfo(
        series_number=number,
        description=description,
        path=f"/tmp/Series_{number}_{description}",
        file_count=kw.pop("file_count", 10),
        **kw,
    )


# ---- the vocabulary ---------------------------------------------------------


def test_every_declarable_type_parses_and_round_trips():
    """The dropdown's options and the parser cannot disagree — same tuple."""
    for token in DECLARABLE_TYPES:
        datatype, suffix = parse_type_token(token)
        assert datatype and suffix
        assert format_type_token(datatype, suffix if datatype == "anat" else "") == token


def test_a_datatype_whose_suffix_is_fixed_needs_no_second_half():
    assert parse_type_token("func") == ("func", "bold")
    assert parse_type_token("sbref") == ("sbref", "sbref")
    assert parse_type_token("func/bold") == ("func", "bold")


def test_an_anat_declaration_must_name_its_suffix():
    """The whole reason this is a module and not one unlocked column.

    `_anat_description` picks the suffix from the *name* vocabulary and returns
    None when nothing fires, so a bare `anat` on a study-specific name writes no
    file and says nothing — the failure the control exists to prevent.
    """
    with pytest.raises(ValueError, match="anat/T1w"):
        parse_type_token("anat")
    with pytest.raises(ValueError):
        parse_type_token("anat/PROTON")


@pytest.mark.parametrize("token", ["fmap", "fmap/epi", "scout", "physio", "unknown", ""])
def test_a_type_a_label_alone_cannot_make_emit_is_refused(token):
    """fmap needs a *pair*, and the rest are not-converting.

    Each is offered by the Conversion page's dropdown only because a Selectbox
    cell cannot render a value absent from its options — picking one is refused
    by name rather than accepted and ignored.
    """
    with pytest.raises(ValueError):
        parse_type_token(token)


def test_diffusion_is_declarable_with_a_fixed_suffix():
    """`#19.1` gave `dwi` an emission path, so the refusal it used to carry went."""
    assert parse_type_token("dwi") == ("dwi", "dwi")
    assert "dwi" in DECLARABLE_TYPES


def test_declaring_a_diffusion_reference_is_refused_because_the_sibling_rule_does_it():
    """There is no `dwi/sbref` token, and the reason is mechanical rather than taste.

    `_recover_dwi_sbref_from_sibling` runs *after* the project tier and reads its
    bases from `classification == "dwi"`, declarations included — so naming the
    volume series is what recovers the reference, and a second token would have
    nothing left to say.
    """
    with pytest.raises(ValueError, match="always written"):
        parse_type_token("dwi/sbref")


def test_declaring_the_volume_series_recovers_its_reference_sibling():
    """The claim the refusal above rests on, checked rather than asserted."""
    volume, reference = _series(1, "study_diffusion"), _series(2, "study_diffusion_SBRef")
    classify_series([volume, reference], type_rules=[TypeRule("study_diffusion", "dwi", "dwi")])

    assert (volume.classification, volume.classified_by) == ("dwi", "project")
    assert (reference.classification, reference.suffix_hint) == ("dwi", "sbref")
    assert reference.classified_by == "sibling"


def test_declaring_a_func_series_as_an_sbref_file_is_refused():
    """A func series is written as `bold`; claiming otherwise is not a declaration."""
    with pytest.raises(ValueError, match="always written"):
        parse_type_token("func/sbref")


def test_token_datatype_is_tolerant_where_the_parser_is_strict():
    """Every read of the Type column goes through it, and most cells are inferred."""
    assert token_datatype("anat/T1w") == "anat"
    assert token_datatype("scout") == "scout"
    assert token_datatype("") == ""


# ---- the config section -----------------------------------------------------


def test_declarations_round_trip_through_the_config_section():
    rules = [TypeRule("food_r1", "func", "bold"), TypeRule("MPRAGE_x", "anat", "T2w")]
    section = type_rules_to_config_section(rules)
    assert type_rules_from_config({"series_types": section}) == rules


def test_an_unreadable_declaration_raises_rather_than_falling_back():
    """Unlike [task_mapping], where a skipped rule falls back to a stated heuristic.

    A skipped declaration falls back to the very misclassification it was written
    to correct, and nothing downstream could notice.
    """
    config = {"series_types": {"rule": [{"description": "food_r1", "type": "banana"}]}}
    with pytest.raises(ValueError, match="food_r1"):
        type_rules_from_config(config)


def test_a_rule_naming_nothing_is_dropped():
    config = {"series_types": {"rule": [{"description": "  ", "type": "func"}]}}
    assert type_rules_from_config(config) == []


def test_no_section_means_no_declarations():
    assert type_rules_from_config({}) == []


def test_saving_declarations_touches_only_its_own_section(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"project": {"name": "keep-me"}})
    save_project_series_types(str(proj), [TypeRule("food_r1", "func", "bold")])
    config = load_config(project_dir=str(proj))
    assert type_rules_from_config(config) == [TypeRule("food_r1", "func", "bold")]
    assert config["project"]["name"] == "keep-me"  # other sections survive

    save_project_series_types(str(proj), [])
    assert type_rules_from_config(load_config(project_dir=str(proj))) == []


# ---- the classification tier ------------------------------------------------


def test_a_declaration_outranks_the_name():
    series = [_series(9, "food_r1")]
    classify_series(series)
    assert series[0].classification == "unknown"

    classify_series(series, type_rules=[TypeRule("food_r1", "func", "bold")])
    assert series[0].classification == "func"
    assert series[0].classified_by == "project"
    assert series[0].declared_suffix == "bold"


def test_a_declaration_outranks_the_header():
    """The header is a fact about the acquisition; the declaration is the study
    correcting how duckbrain *read* it, so it has to win or the tier is inert."""
    header = SeriesHeader(
        modality="MR", mr_acquisition_type="2D", is_epi=True, is_spin_echo=True, volumes=3
    )
    series = [_series(3, "se_epi_ap", header=header)]
    classify_series(series)
    assert series[0].classification == "fmap"

    classify_series(series, type_rules=[TypeRule("se_epi_ap", "func", "bold")])
    assert series[0].classification == "func"
    assert series[0].classified_by == "project"


def test_the_sbref_promotion_does_not_overrule_a_declaration():
    """`_recover_func_from_sbref` exists to rescue an uninformative *name* — which
    is the same inference a declaration is overruling."""
    series = [_series(9, "food_r1"), _series(10, "food_r1_SBRef")]
    classify_series(series, type_rules=[TypeRule("food_r1", "anat", "T1w")])
    assert series[0].classification == "anat"
    assert series[0].declared_suffix == "T1w"


def test_a_declaration_is_matched_case_and_whitespace_insensitively():
    series = [_series(9, "Food_R1")]
    classify_series(series, type_rules=[TypeRule("  food_r1  ", "func", "bold")])
    assert series[0].classification == "func"


def test_reclassifying_without_rules_clears_the_declared_suffix():
    """The Conversion page classifies one list twice (the ND radio), so a stale
    declaration must not survive into a pass that no longer carries it."""
    series = [_series(9, "food_r1")]
    classify_series(series, type_rules=[TypeRule("food_r1", "anat", "T1w")])
    classify_series(series)
    assert series[0].declared_suffix == ""
    assert series[0].classified_by == "name"


# ---- emission ---------------------------------------------------------------


def _anat_files(series):
    config = generate_config(series, FieldmapDetection(strategy="none"), subject="001")
    return {d["suffix"] for d in config["descriptions"] if d["datatype"] == "anat"}


def test_an_anat_the_name_says_nothing_about_converts_only_once_declared():
    """The bug the feature exists to prevent, from both sides.

    Relabelling `food_r1` as an anatomical without naming the suffix writes no
    file and reports nothing; the declaration is what makes it emit.
    """
    undeclared = [_series(9, "food_r1", classification="anat")]
    assert _anat_files(undeclared) == set()

    declared = [_series(9, "food_r1")]
    classify_series(declared, type_rules=[TypeRule("food_r1", "anat", "T1w")])
    assert _anat_files(declared) == {"T1w"}


def test_a_declared_suffix_beats_the_name_vocabulary_not_just_the_gap():
    """`suffix_hint` is consulted *last*, so it could only rescue a dropped series
    — never relabel one the name already named. A declaration must do both, or
    correcting a misread `t1`-in-the-name is impossible."""
    series = [_series(2, "t1w_mprage")]
    classify_series(series)
    assert _anat_files(series) == {"T1w"}

    classify_series(series, type_rules=[TypeRule("t1w_mprage", "anat", "T2w")])
    assert _anat_files(series) == {"T2w"}


def test_anat_suffix_for_reports_what_the_emitter_will_write():
    """The Type column's seed is derived from the emitter, not from a second copy
    of its vocabulary, so the cell cannot promise a suffix the file won't carry."""
    named = _series(2, "t1w_mprage", classification="anat")
    assert anat_suffix_for(named) == "T1w"

    silent = _series(9, "food_r1", classification="anat")
    assert anat_suffix_for(silent) == ""

    declared = _series(9, "food_r1", classification="anat", declared_suffix="FLAIR")
    assert anat_suffix_for(declared) == "FLAIR"

    assert anat_suffix_for(_series(9, "food_r1", classification="func")) == ""


def test_a_declared_func_series_converts_as_a_bold_run():
    series = [_series(9, "food_r1")]
    classify_series(series, type_rules=[TypeRule("food_r1", "func", "bold")])
    config = generate_config(series, FieldmapDetection(strategy="none"), subject="001")
    bold = [d for d in config["descriptions"] if d["suffix"] == "bold"]
    assert len(bold) == 1
    assert bold[0]["criteria"]["SeriesNumber"] == 9
