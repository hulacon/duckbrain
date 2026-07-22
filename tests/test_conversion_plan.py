"""Tests for the conversion plan — what a dcm2bids config will actually produce.

These deliberately drive the *real* pipeline (`detect_fieldmaps` →
`generate_config` → `plan_conversion`) rather than hand-writing config dicts.
The module's whole reason to exist is that it must not drift from what dcm2bids
consumes, so a test that fed it a synthetic config would be testing the wrong
thing.
"""

from duckbrain.core.conversion_plan import plan_conversion, plan_warnings
from duckbrain.core.dcm2bids_config import (
    TaskRunEntry,
    build_task_run_mapping,
    generate_config,
)
from duckbrain.core.dicom_inspect import (
    SeriesInfo,
    classify_series,
    detect_fieldmaps,
)


def _series(num, desc, cls=None, n=300):
    s = SeriesInfo(series_number=num, description=desc, path=None, file_count=n)
    if cls is not None:
        s.classification = cls
    return s


def _bold(num, task, run, n=300):
    """A run the classifier reads as func from its description alone.

    A study-specific name like ``div_perFace_r1`` only becomes func via its
    SBRef sibling (``_recover_func_from_sbref``), so tests that don't care about
    that path spell the bold token out rather than relying on it.
    """
    return _series(num, f"cmrr_mbep2d_bold_task-{task}_run-{run}", n=n)


def _plan(series, subject="001", session="01", mapping=None):
    """Run the real chain end to end and return (plan, fieldmaps)."""
    classify_series(series)
    fieldmaps = detect_fieldmaps(series)
    if mapping is None:
        mapping = build_task_run_mapping(series)
    config = generate_config(series, fieldmaps, subject=subject, session=session, mapping=mapping)
    return plan_conversion(config, series, subject=subject, session=session), fieldmaps


# ---- filenames ----


def test_plan_renders_bids_paths():
    series = [
        _series(2, "t1w_mprage"),
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    plan, _ = _plan(series)

    paths = {f.series_number: f.path for f in plan.files}
    assert paths[2] == "sub-001/ses-01/anat/sub-001_ses-01_T1w.nii.gz"
    assert paths[9] == ("sub-001/ses-01/func/sub-001_ses-01_task-divPerFace_run-1_bold.nii.gz")
    assert paths[8] == ("sub-001/ses-01/func/sub-001_ses-01_task-divPerFace_run-1_sbref.nii.gz")


def test_plan_omits_ses_entity_when_sessionless():
    series = [_series(2, "t1w_mprage"), _bold(9, "perFace", 1)]
    plan, _ = _plan(series, session="")

    paths = {f.series_number: f.path for f in plan.files}
    assert paths[2] == "sub-001/anat/sub-001_T1w.nii.gz"
    assert paths[9] == "sub-001/func/sub-001_task-perFace_run-1_bold.nii.gz"


# ---- the fieldmap relation ----


def test_bold_carries_its_fieldmap_group():
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _bold(9, "perFace", 1),
    ]
    plan, _ = _plan(series)

    bold = next(f for f in plan.files if f.is_bold)
    # The lone unnamed pair keeps the historical empty group key.
    assert bold.fmap_group == ""
    assert [f.series_number for f in plan.bolds_for_group("")] == [9]


def test_sbref_is_bound_to_the_same_pair_as_its_bold():
    """An SBRef takes its BOLD's fieldmap, and the plan must say so.

    fMRIPrep builds the BOLD reference from the SBRef when one is present, so an
    SBRef the plan reports as unbound is the one image in the chain nothing
    corrects. ``corrected_by`` is the accessor the GUI's "which pair corrects
    which run" view reads; it must include SBRefs, while ``bolds_for_group``
    stays the narrower "which runs" answer.
    """
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    plan, _ = _plan(series)

    sbref = next(f for f in plan.files if f.suffix == "sbref")
    bold = next(f for f in plan.files if f.is_bold)
    assert sbref.fmap_group == bold.fmap_group == ""
    assert [f.series_number for f in plan.corrected_by("")] == [9, 8]
    assert [f.series_number for f in plan.bolds_for_group("")] == [9]


def test_unbound_sbref_reported_with_its_unbound_bold():
    """No fieldmaps at all: both halves read as uncorrected, not just the bold."""
    series = [
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    plan, _ = _plan(series)

    assert {f.series_number for f in plan.corrected_by(None)} == {8, 9}


def test_two_pairs_bind_to_distinct_groups():
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _bold(9, "taskA", 1),
        _series(19, "se_epi_ap"),
        _series(21, "se_epi_pa"),
    ]
    plan, fieldmaps = _plan(series)

    assert set(fieldmaps.groups) == {"1", "2"}
    # Unbound tasks go to the first complete pair — the documented default.
    assert next(f for f in plan.files if f.is_bold).fmap_group == "1"

    fmaps = {f.series_number: f.fmap_group for f in plan.files if f.datatype == "fmap"}
    assert fmaps == {3: "1", 4: "1", 19: "2", 21: "2"}
    # And the extra entity that keeps the two pairs off the same filename.
    assert "run-1" in next(f for f in plan.files if f.series_number == 3).entities
    assert "run-2" in next(f for f in plan.files if f.series_number == 19).entities


def test_group_name_containing_underscore_is_recovered_exactly():
    """`B0map_foo_bar_sub001ses01` must not be split on underscores."""
    series = [
        _series(3, "se_epi_ap_foo_bar"),
        _series(4, "se_epi_pa_foo_bar"),
        _bold(9, "perFace", 1),
    ]
    plan, fieldmaps = _plan(series)

    assert "foo_bar" in fieldmaps.groups
    assert next(f for f in plan.files if f.is_bold).fmap_group == "foo_bar"


# ---- series nothing claims ----


def test_scout_is_an_expected_drop_but_an_unmatched_anat_is_not():
    series = [
        _series(1, "AAhead_scout", n=3),
        _series(2, "anat-BOGUS"),  # ReproIn anat, suffix outside the BIDS vocabulary
        _bold(9, "perFace", 1),
    ]
    plan, _ = _plan(series)

    dropped = {d.series_number: d for d in plan.dropped}
    assert dropped[1].expected is True
    assert dropped[2].expected is False
    assert 9 not in dropped

    kinds = [(w.kind, w.severity) for w in plan_warnings(plan)]
    assert ("dropped", "warning") in kinds  # the anat
    assert ("dropped", "info") in kinds  # the scout


# ---- preflight ----


def test_collision_is_an_error_naming_both_series():
    series = [_bold(9, "taskA", 1), _bold(19, "taskA", 2)]
    # A plausible mis-edit: both rows given the same task and run.
    mapping = [
        TaskRunEntry(9, series[0].description, "bold", "taskA", 1),
        TaskRunEntry(19, series[1].description, "bold", "taskA", 1),
    ]
    plan, fieldmaps = _plan(series, mapping=mapping)

    collisions = [w for w in plan_warnings(plan, fieldmaps) if w.kind == "collision"]
    assert len(collisions) == 1
    assert collisions[0].severity == "error"
    assert collisions[0].series == [9, 19]


def test_half_pair_is_flagged_and_leaves_the_bold_uncorrected():
    series = [_series(3, "se_epi_ap"), _bold(9, "perFace", 1)]
    plan, fieldmaps = _plan(series)

    # The half of this test the name always promised and never checked, which is
    # why TODO #17.3 survived: the bold WAS bound to the half pair, and only the
    # warnings were asserted.
    assert next(f for f in plan.files if f.is_bold).fmap_group is None

    warnings = plan_warnings(plan, fieldmaps)
    assert any(w.kind == "half-pair" and w.series == [3] for w in warnings)
    # No complete pair exists, so "uncorrected" would be noise, not a finding.
    assert not any(w.kind == "uncorrected" for w in warnings)


def test_uncorrected_bold_reported_only_when_a_usable_pair_exists():
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _bold(9, "perFace", 1),
    ]
    plan, fieldmaps = _plan(series)
    assert not any(w.kind == "uncorrected" for w in plan_warnings(plan, fieldmaps))

    # Opt the run out, as the binding table's "none" does.
    for f in plan.files:
        if f.is_bold:
            f.fmap_group = None
    uncorrected = [w for w in plan_warnings(plan, fieldmaps) if w.kind == "uncorrected"]
    assert len(uncorrected) == 1
    assert uncorrected[0].severity == "info"
    assert uncorrected[0].series == [9]


def test_clean_session_yields_no_error_or_warning():
    series = [
        _series(1, "AAhead_scout", n=3),
        _series(2, "t1w_mprage"),
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    plan, fieldmaps = _plan(series)

    severities = {w.severity for w in plan_warnings(plan, fieldmaps)}
    assert severities <= {"info"}


def test_by_series_keeps_every_planned_file():
    series = [_series(8, "div_perFace_r1_SBRef", n=1), _series(9, "div_perFace_r1")]
    plan, _ = _plan(series)

    assert set(plan.by_series) == {8, 9}
    assert all(len(v) == 1 for v in plan.by_series.values())


# ---- reading a hand-edited config back into the table ----


def test_read_config_into_table_recovers_task_run_and_group():
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _bold(9, "perFace", 1),
    ]
    classify_series(series)
    fieldmaps = detect_fieldmaps(series)
    config = generate_config(
        series,
        fieldmaps,
        subject="001",
        session="01",
        mapping=build_task_run_mapping(series),
    )

    from duckbrain.core.conversion_plan import read_config_into_table

    got = read_config_into_table(config, series)
    assert got.task_by_series[9] == "perFace"
    assert got.run_by_series[9] == 1
    assert got.group_by_series[9] == ""  # the lone unnamed pair
    assert got.unrepresentable == []


def test_read_config_into_table_reports_what_it_cannot_represent():
    """The point of the import: loss is reported, never silent."""
    series = [_bold(9, "perFace", 1)]
    classify_series(series)
    config = {
        "dupMethod": "dup",  # a dcm2bids option with no column
        "descriptions": [
            {
                "id": "func-bold-perFace",
                "datatype": "func",
                "suffix": "bold",
                "criteria": {"SeriesNumber": 9, "EchoTime": 0.03},
                "custom_entities": "task-perFace_run-1",
                "sidecar_changes": {"TaskName": "perFace", "EchoTime": 0.03},
                "IntendedFor": ["x"],
            },
            {
                "id": "orphan",
                "datatype": "anat",
                "suffix": "T1w",
                "criteria": {"SeriesDescription": "*"},
            },
        ],
    }

    from duckbrain.core.conversion_plan import read_config_into_table

    got = read_config_into_table(config, series)
    joined = " | ".join(got.unrepresentable)
    assert "dupMethod" in joined
    assert "EchoTime" in joined
    assert "IntendedFor" in joined
    assert "does not match on SeriesNumber" in joined
    # …and the parts it *can* represent still come through.
    assert got.task_by_series[9] == "perFace"
    assert got.run_by_series[9] == 1


# ---- BIDS fieldmap intent: which side carries which key ----
# These pin a direction that was inverted in shipped code and produced no error
# anywhere — fMRIPrep simply reported "Susceptibility distortion correction:
# None" and preprocessed uncorrected. Per BIDS: the fieldmap is computed from
# scans sharing a B0FieldIdentifier and applied to scans sharing a B0FieldSource.


def _sidecars(series, subject="001", session="01"):
    classify_series(series)
    fieldmaps = detect_fieldmaps(series)
    cfg = generate_config(
        series,
        fieldmaps,
        subject=subject,
        session=session,
        mapping=build_task_run_mapping(series),
    )
    return {d["id"]: d.get("sidecar_changes") or {} for d in cfg["descriptions"]}


def test_fieldmap_declares_the_identifier_and_the_bold_declares_the_source():
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _bold(9, "perFace", 1),
    ]
    cars = _sidecars(series)

    fmap_ap = cars["fmap-epi-ap"]
    bold = cars["func-bold-perFace-run1"]

    # The fieldmap is an *input to* the estimation: it identifies the B0 field.
    assert fmap_ap["B0FieldIdentifier"] == "B0map__sub001ses01"
    assert "B0FieldSource" not in fmap_ap
    # The BOLD is a *consumer of* that estimation: it points at the source.
    assert bold["B0FieldSource"] == "B0map__sub001ses01"
    assert "B0FieldIdentifier" not in bold


def test_sbref_is_corrected_by_the_same_pair_as_its_bold():
    """fMRIPrep builds the BOLD reference from the SBRef when one exists, so an
    unassociated SBRef leaves that reference uncorrected."""
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    cars = _sidecars(series)

    bold = cars["func-bold-divPerFace-run1"]
    sbref = cars["func-sbref-divPerFace-run1"]
    assert sbref["B0FieldSource"] == bold["B0FieldSource"]


def test_sbref_carries_no_binding_when_the_session_has_no_fieldmaps():
    series = [
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    cars = _sidecars(series)
    assert "B0FieldSource" not in cars["func-sbref-divPerFace-run1"]


def test_plan_reads_the_sbref_binding_back():
    series = [
        _series(3, "se_epi_ap"),
        _series(4, "se_epi_pa"),
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    plan, _ = _plan(series)
    by_series = {num: files[0] for num, files in plan.by_series.items()}
    assert by_series[8].fmap_group == by_series[9].fmap_group == ""


def test_a_half_fieldmap_pair_binds_nothing_even_when_it_is_the_only_one():
    """No complete pair means no binding — not a binding to the half pair.

    `_assign_fmap_group` fell back to `list(fieldmaps.groups)` when no group was
    complete, so an aborted lone AP got bound after all (TODO #17.3). That
    contradicted the Fieldmap Detection panel, hard-errored the per-session page
    on a binding it had made itself, and let the bulk path submit a run pointed at
    a field that cannot be estimated.
    """
    series = [
        _series(3, "se_epi_ap"),  # AP only — the scan was aborted
        _series(8, "div_perFace_r1_SBRef", n=1),
        _series(9, "div_perFace_r1"),
    ]
    plan, fieldmaps = _plan(series)

    assert not [g for g, d in fieldmaps.groups.items() if "ap" in d and "pa" in d]
    assert {f.fmap_group for f in plan.files if f.datatype == "func"} == {None}
    assert {f.series_number for f in plan.corrected_by(None)} == {8, 9}


def test_a_complete_pair_still_wins_when_a_half_pair_is_also_present():
    """The fix must not stop a real pair from binding when both kinds exist."""
    series = [
        _series(3, "se_epi_ap_good"),
        _series(4, "se_epi_pa_good"),
        _series(5, "se_epi_ap_aborted"),  # half pair, must not be chosen
        _bold(9, "perFace", 1),
    ]
    plan, _ = _plan(series)

    assert next(f for f in plan.files if f.is_bold).fmap_group == "good"
