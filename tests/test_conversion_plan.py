"""Tests for the conversion plan — what a dcm2bids config will actually produce.

These deliberately drive the *real* pipeline (`detect_fieldmaps` →
`generate_config` → `plan_conversion`) rather than hand-writing config dicts.
The module's whole reason to exist is that it must not drift from what dcm2bids
consumes, so a test that fed it a synthetic config would be testing the wrong
thing.
"""

from duckbrain.core.conversion_plan import (
    plan_conversion,
    plan_warnings,
    read_config_into_table,
)
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


def test_the_import_reports_a_datatype_it_will_not_carry_over():
    """The Type column is seeded by classify_series, which the import runs
    downstream of — so a config that converts a series as something else loses
    that on regeneration. Reported, because the banner says the JSON loaded."""
    series = [_bold(9, "perFace", 1)]
    classify_series(series)
    config = {
        "descriptions": [
            {
                "id": "anat-T1w",
                "datatype": "anat",
                "suffix": "T1w",
                "criteria": {"SeriesNumber": 9},
            }
        ]
    }

    from duckbrain.core.conversion_plan import read_config_into_table

    joined = " | ".join(read_config_into_table(config, series).unrepresentable)
    assert "as `anat`" in joined and "reads it as `func`" in joined
    assert "Type" in joined  # names the control that makes it stick


def test_an_sbref_description_is_not_reported_as_a_disagreement():
    """dcm2bids spells the sbref classification `func` + suffix `sbref`, so a
    naive datatype comparison would flag every SBRef in every config."""
    series = [
        _bold(9, "perFace", 1),
        _series(10, "cmrr_mbep2d_bold_task-perFace_run-1_SBRef", n=1),
    ]
    classify_series(series)
    config = {
        "descriptions": [
            {
                "id": "func-sbref-perFace",
                "datatype": "func",
                "suffix": "sbref",
                "criteria": {"SeriesNumber": 10},
                "custom_entities": "task-perFace_run-1",
            }
        ]
    }

    from duckbrain.core.conversion_plan import read_config_into_table

    assert read_config_into_table(config, series).unrepresentable == []


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


# ---- gradient-echo fieldmaps (TODO #19.6) ----------------------------------
# LCNI flagged that older fieldmaps are gradient double-echo rather than
# spin-echo. Two defects fell out of checking it against the repository corpus,
# and both are pinned here. The fixture mirrors REV/REV055_20150811_135636,
# which shoots two GRE pairs around the run blocks.


def _gre_pair(magnitude_num, phase_num, description):
    """One gradient-echo fieldmap pair, classified as the header reader would."""
    from duckbrain.core.dicom_header import SeriesHeader

    def one(num, image_type, echoes, volumes):
        s = SeriesInfo(
            series_number=num,
            description=description,
            path=None,
            file_count=volumes,
            header=SeriesHeader(
                modality="MR",
                mr_acquisition_type="2D",
                is_epi=False,
                is_spin_echo=False,
                dialect="classic",
                image_type=image_type,
                echo_numbers=echoes,
                volumes=volumes,
                single_volume=False,
            ),
        )
        return s

    return [
        one(magnitude_num, ("ORIGINAL", "PRIMARY", "M", "ND", "NORM"), (1, 2), 144),
        one(phase_num, ("ORIGINAL", "PRIMARY", "P", "ND"), (2,), 72),
    ]


def test_a_complete_gre_pair_is_not_reported_as_a_half_pair():
    """The half-pair check tested ap/pa membership instead of is_complete_group.

    A ``{magnitude, phasediff}`` group has neither, so every gradient-echo
    session was told its fieldmap "can't correct anything and isn't offered for
    binding" — while the runs were in fact bound to it.
    """
    series = [*_gre_pair(5, 6, "fieldmap_2mm"), _bold(9, "food", 1)]
    plan, fieldmaps = _plan(series)
    warnings = plan_warnings(plan, fieldmaps)
    assert [w for w in fieldmaps.groups.values() if "magnitude" in w], "fixture sanity"
    assert not [w for w in warnings if w.kind == "half-pair"]


def test_a_gre_pair_missing_its_phase_half_is_still_flagged():
    """The fix must not silence the real case it was there for."""
    series = [_gre_pair(5, 6, "fieldmap_2mm")[0], _bold(9, "food", 1)]
    plan, fieldmaps = _plan(series)
    # No group forms at all without a phase partner, so detect_fieldmaps warns;
    # what matters is that a group holding only one half never reads as usable.
    from duckbrain.core.dicom_inspect import is_complete_group

    assert all(not is_complete_group(m) for m in fieldmaps.groups.values())


def test_two_gre_pairs_get_distinct_filenames():
    """Both pairs collided on sub-X_ses-Y_phasediff, so the session refused.

    group_entities was populated only on the spin-echo path, so two gradient-echo
    pairs wrote identical names. The collision check caught it as an error —
    nothing was lost — but the session could not convert at all.
    """
    series = [
        *_gre_pair(7, 8, "fieldmap1"),
        _bold(9, "BART", 1),
        *_gre_pair(13, 14, "fieldmap2"),
        _bold(15, "React", 1),
    ]
    plan, fieldmaps = _plan(series, subject="REV055", session="1")

    assert len(fieldmaps.groups) == 2, "both pairs are found"
    assert len(set(fieldmaps.group_entities.values())) == 2, "and told apart"

    collisions = [w for w in plan_warnings(plan, fieldmaps) if w.kind == "collision"]
    assert not collisions, [w.message for w in collisions]

    fmap_files = sorted(f.path for f in plan.files if "/fmap/" in f.path)
    assert len(fmap_files) == len(set(fmap_files)), fmap_files


def test_a_lone_gre_pair_keeps_the_bare_filename():
    """The entity is only warranted when something would collide."""
    series = [*_gre_pair(5, 6, "fieldmap_2mm"), _bold(9, "food", 1)]
    plan, fieldmaps = _plan(series, subject="CC052", session="1")
    assert fieldmaps.group_entities == {}
    names = {f.path.rsplit("/", 1)[-1] for f in plan.files if "/fmap/" in f.path}
    assert names == {
        "sub-CC052_ses-1_magnitude1.nii.gz",
        "sub-CC052_ses-1_magnitude2.nii.gz",
        "sub-CC052_ses-1_phasediff.nii.gz",
    }


def test_two_gre_pairs_sharing_one_name_get_legal_entity_values():
    """A BIDS entity value is alphanumeric — the disambiguator must not leak in.

    ``_detect_gre_fieldmaps`` suffixes a repeated group name with ``-2`` to keep
    the namespace unique. Spelling that straight into ``acq-`` would emit
    ``acq-greFieldMapping-2``, which re-parses as a second entity. A repeat is
    what ``run-`` is for.
    """
    series = [
        *_gre_pair(5, 6, "gre_field_mapping"),
        _bold(7, "food", 1),
        *_gre_pair(9, 10, "gre_field_mapping"),
    ]
    plan, fieldmaps = _plan(series, subject="X", session="1")

    values = list(fieldmaps.group_entities.values())
    assert len(set(values)) == 2, values
    for entity in values:
        for token in entity.split("_"):
            key, _, value = token.partition("-")
            assert value.isalnum(), f"{token} is not a legal BIDS entity"
            assert key in ("acq", "run"), token

    fmap_files = sorted(f.path for f in plan.files if "/fmap/" in f.path)
    assert len(fmap_files) == len(set(fmap_files)), fmap_files
    assert not [w for w in plan_warnings(plan, fieldmaps) if w.severity == "error"]


def test_an_unpaired_gre_half_is_told_what_is_missing_not_that_gre_is_unsupported():
    """The hint fires on any dropped fmap, and gradient-echo is supported now.

    It used to say duckbrain "can only express the spin-echo AP/PA pair", which
    stopped being true at `#19.6` — so a session whose fieldmap merely lost a
    half was told to give up on a flavour duckbrain would have converted.
    """
    magnitude, _phase = _gre_pair(5, 6, "gre_field_mapping")
    plan, fieldmaps = _plan([magnitude, _bold(7, "food", 1)], subject="X", session="1")

    dropped = [w for w in plan_warnings(plan, fieldmaps) if w.kind == "dropped"]
    assert len(dropped) == 1
    message = dropped[0].message
    assert "both halves" in message
    assert "can only express" not in message


# ---- skipping a series (the `convert` column) ----------------------------
# The config's native spelling of "not converted" is *no description*, so these
# assert on absence from the plan rather than on any skip-specific state. That is
# the property that makes the skip survive a save/reload with nothing extra
# stored: the JSON dcm2bids consumes already says it.


def _plan_with_skip(series, skip, subject="001", session="01"):
    classify_series(series)
    fieldmaps = detect_fieldmaps(series)
    mapping = build_task_run_mapping(series)
    config = generate_config(
        series, fieldmaps, subject=subject, session=session, mapping=mapping, skip=skip
    )
    return plan_conversion(config, series, subject=subject, session=session), fieldmaps, config


def test_a_skipped_series_produces_no_file():
    series = [_series(2, "t1w_mprage"), _bold(9, "food", 1), _bold(10, "food", 2)]
    plan, _fieldmaps, _config = _plan_with_skip(series, skip={10})

    assert 10 not in plan.by_series
    assert [d.series_number for d in plan.dropped] == [10]
    assert {9, 2} <= set(plan.by_series)


def test_skipping_reads_back_off_the_config_with_nothing_else_stored():
    """Round trip: the table can rebuild the skip from the JSON alone."""
    series = [_series(2, "t1w_mprage"), _bold(9, "food", 1), _bold(10, "food", 2)]
    _plan, _fieldmaps, config = _plan_with_skip(series, skip={10})

    assert read_config_into_table(config, series).skipped_series == {10}


def test_an_unskipped_session_reads_back_as_skipping_nothing():
    series = [_series(2, "t1w_mprage"), _bold(9, "food", 1)]
    _plan, _fieldmaps, config = _plan_with_skip(series, skip=set())

    assert read_config_into_table(config, series).skipped_series == set()


def test_a_scout_is_not_reported_as_skipped():
    """It was never convertible, so unticking it would be a control doing nothing.

    `skipped_series` seeds the checkbox column, so including a scout here would
    put it in the skip set on the next render and have the plan announce a
    deliberate drop for a series duckbrain has no emission path for.
    """
    series = [_series(1, "AAHead_Scout"), _series(2, "t1w_mprage")]
    _plan, _fieldmaps, config = _plan_with_skip(series, skip=set())

    assert read_config_into_table(config, series).skipped_series == set()


def test_skipping_one_fieldmap_half_removes_the_whole_pair():
    """A field is estimated from both halves, so half a pair is not half a fieldmap.

    Emitting the survivor would write a `fmap/` file nothing can be estimated
    from — the silently-degrading shape, and worse than refusing.
    """
    series = [_series(3, "se_epi_ap"), _series(4, "se_epi_pa"), _bold(9, "food", 1)]
    plan, _fieldmaps, _config = _plan_with_skip(series, skip={3})

    assert not [f for f in plan.files if f.datatype == "fmap"]
    assert {3, 4} == {d.series_number for d in plan.dropped}


def test_a_run_whose_fieldmap_was_skipped_is_written_without_correction():
    """Not silently: it loses B0FieldSource, and the plan says the run is uncorrected."""
    series = [_series(3, "se_epi_ap"), _series(4, "se_epi_pa"), _bold(9, "food", 1)]
    plan, fieldmaps, _config = _plan_with_skip(series, skip={3})

    bold = plan.by_series[9][0]
    assert bold.fmap_group is None
    # `fieldmaps` is the unfiltered detection — the pair still exists on disk, so
    # the "you have a usable pair and this run isn't using it" note must fire.
    assert any(w.kind == "uncorrected" for w in plan_warnings(plan, fieldmaps))


def test_a_deliberate_skip_is_a_note_not_a_warning():
    """The warning it would otherwise raise means 'nothing claimed this' — a bug.

    A skipped run is indistinguishable from an anat whose suffix vocabulary
    didn't match unless the reason travels with it, and that warning exists to
    catch the second one.
    """
    series = [_series(2, "t1w_mprage"), _bold(9, "food", 1), _bold(10, "food", 2)]
    plan, fieldmaps, _config = _plan_with_skip(series, skip={10})
    for s in series:
        if s.series_number == 10:
            s.drop_reason = "you unticked `convert` for it on this page"
    plan = plan_conversion(
        generate_config(
            series,
            fieldmaps,
            subject="001",
            session="01",
            mapping=build_task_run_mapping(series),
            skip={10},
        ),
        series,
        subject="001",
        session="01",
    )

    findings = plan_warnings(plan, fieldmaps)
    assert not [w for w in findings if w.kind == "dropped" and w.severity == "warning"]
    told = [w for w in findings if w.kind == "deliberate-drop"]
    assert len(told) == 1 and told[0].series == [10]


def test_skipping_a_bold_and_not_its_sbref_is_reported():
    """The two are separate rows, so the half-edit is one click away.

    An SBRef alone references nothing — fMRIPrep has no run to attach it to and
    it sits in func/ looking like data.
    """
    series = [
        _bold(9, "food", 1),
        _series(8, "cmrr_mbep2d_bold_task-food_run-1_SBRef", n=1),
    ]
    plan, fieldmaps, _config = _plan_with_skip(series, skip={9})

    orphans = [w for w in plan_warnings(plan, fieldmaps) if w.kind == "orphan-sbref"]
    assert len(orphans) == 1 and orphans[0].series == [8]


def test_a_bold_kept_with_its_sbref_is_not_reported_as_an_orphan():
    series = [
        _bold(9, "food", 1),
        _series(8, "cmrr_mbep2d_bold_task-food_run-1_SBRef", n=1),
    ]
    plan, fieldmaps, _config = _plan_with_skip(series, skip=set())

    assert not [w for w in plan_warnings(plan, fieldmaps) if w.kind == "orphan-sbref"]
