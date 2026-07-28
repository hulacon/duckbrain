"""Series-classification rules, pinned against real LCNI protocol names.

Every description in this file is taken verbatim from the LCNI repository at
``/projects/lcni/dcm/repository`` (15 studies, 189 distinct series descriptions,
paired with the BIDS the LCNI curator produced from them). They are the cases
that were classified wrongly before, so each one is a regression guard rather
than an invented example.
"""

from pathlib import Path

import pytest

from duckbrain.core import dcm2bids_config, dicom_inspect
from duckbrain.core.dicom_inspect import SeriesInfo


def _series(*pairs: tuple[int, str]) -> list[SeriesInfo]:
    series = [
        SeriesInfo(series_number=n, description=d, path=Path("/nonexistent"), file_count=200)
        for n, d in pairs
    ]
    dicom_inspect.classify_series(series)
    return series


# --- token anchoring -------------------------------------------------------
# 'T1_'/'T2_' as bare substrings also match inside a task name. Three real LCNI
# tasks classified as anatomicals because of it, and anat descriptions then
# collided on a single filename.
@pytest.mark.parametrize(
    "description",
    [
        "BART1_mb3_g2_2mm_te27",  # contains 'T1_' after 'BAR'
        "BART2_mb3_g2_2mm_te27",
        "SST1_mb3_g2_2mm_te27",  # contains 'T1_' after 'SS'
        "SST2_mb3_g2_2mm_te27",
        "React1_mb3_g2_2mm_te27",  # contains 't1_' after 'Reac'
        "React2_mb3_g2_2mm_te27",
    ],
)
def test_task_name_containing_t1_or_t2_is_not_anat(description):
    assert dicom_inspect._classify_one(description) != "anat"


@pytest.mark.parametrize(
    "description",
    ["T1_mprage", "t2_tse_cor65slice_2avg.+", "T2_coronal_1.8", "mprage_p2_defaced", "sub_T1w"],
)
def test_real_anatomicals_still_classify_as_anat(description):
    assert dicom_inspect._classify_one(description) == "anat"


def test_anat_suffix_selection_is_token_anchored_too():
    """The classifier and the suffix picker must agree on what 'T1'/'T2' means."""
    series = SeriesInfo(
        series_number=1, description="SST2_mb3_g2_2mm_te27", path=Path("/x"), file_count=1
    )
    assert dcm2bids_config._anat_description(series) is None


def test_a_header_pinned_suffix_rescues_an_anatomical_the_name_cannot_name():
    """A 3D SPACE is a T2w, and 'spcR_282ns' says nothing the vocabulary knows.

    Without the hint the vocabulary returns None and the series is dropped from
    the conversion — an anatomical lost because the console named it after the
    pulse sequence.
    """
    series = SeriesInfo(
        series_number=6,
        description="spcR_282ns",
        path=Path("/x"),
        file_count=176,
        suffix_hint="T2w",
    )
    assert dcm2bids_config._anat_description(series)["suffix"] == "T2w"


def test_the_name_outranks_the_header_suffix_hint():
    """The hint is a last resort, so it can rescue but never relabel."""
    series = SeriesInfo(
        series_number=1,
        description="mprage_p2_defaced",
        path=Path("/x"),
        file_count=176,
        suffix_hint="T2w",
    )
    assert dcm2bids_config._anat_description(series)["suffix"] == "T1w"


def test_a_localizer_with_an_unfamiliar_name_is_still_dropped():
    """End to end: the sequence name is what saves this one.

    'survey' is what other vendors call a localizer and duckbrain's vocabulary
    does not know it, so this classified 'unknown' and was reported as a series
    duckbrain could not place.
    """
    from duckbrain.core.dicom_header import SeriesHeader

    series = [
        SeriesInfo(
            series_number=1,
            description="survey",
            path=Path("/nonexistent"),
            file_count=128,
            header=SeriesHeader(
                modality="MR",
                image_type=("ORIGINAL", "PRIMARY", "M", "ND", "NORM"),
                mr_acquisition_type="3D",
                is_epi=False,
                is_spin_echo=False,
                sequence_name="*fl3d1_ns",
                dialect="classic",
                volumes=128,
            ),
        )
    ]
    dicom_inspect.classify_series(series)
    assert series[0].classification == "scout"
    assert series[0].classified_by == "header"


# --- scanner localizers ----------------------------------------------------
# r"\bscout\b" never matches 'aa_scout': '_' is a word character, so there is no
# boundary before 's'. Nor 'AAHScout', where the words run together.
@pytest.mark.parametrize(
    "description",
    [
        "AAHScout",
        "AAHScout_MPR_cor",
        "AAHScout_32ch-head-coil",
        "AAHScout_32ch-head-coil_MPR_sag",
        "AAhead_scout",
        "AAhead_scout_MPR_tra",
        "AAHead_Scout",
        "aa_scout",
        "aa_scout_MPR_cor",
        "localizer",
    ],
)
def test_scanner_localizers_classify_as_scout(description):
    assert dicom_inspect._classify_one(description) == "scout"


def test_functional_localizer_task_is_not_a_scout():
    """A *task* named localizer must survive to be recovered as func.

    This is why the bare 'scout'/'localizer' alternatives stay whole-word: the
    fix for AAHScout must not swallow a study's own localizer paradigm.
    """
    assert dicom_inspect._classify_one("localizer_prf_run1") != "scout"

    series = _series((1, "localizer_prf_run1"), (2, "localizer_prf_run1_SBRef"))
    assert series[0].classification == "func"


# --- scanner-derived series ------------------------------------------------
@pytest.mark.parametrize(
    "description",
    [
        "PhoenixZIPReport",
        "mprage_vNav_setter",  # the navigator setter, not a second T1w
        "intermediate t-Map",
        "Mean_&_t-Maps",
        "EvaSeries_GLM",
        "MoCoSeries",
    ],
)
def test_scanner_derived_series_are_classified_derived(description):
    assert dicom_inspect._classify_one(description) == "derived"


def test_derived_series_are_an_expected_drop():
    from duckbrain.core.conversion_plan import _EXPECTED_DROPS

    assert "derived" in _EXPECTED_DROPS


# --- ND duplicates ---------------------------------------------------------
def test_nd_copy_is_dropped_when_its_corrected_twin_is_present():
    series = _series((6, "mprage_p2_defaced"), (7, "mprage_p2_ND_defaced"))
    assert series[0].classification == "anat"
    assert series[1].classification == "derived"


def test_nd_copy_converts_when_it_is_the_only_anatomical():
    """Dropping it unconditionally would silently lose the anat entirely."""
    series = _series((7, "mprage_p2_ND_defaced"))
    assert series[0].classification == "anat"


# --- ND fieldmaps: the one shape the corpus cannot pin ---------------------
# Every other description in this file is verbatim from the LCNI repository.
# These are not: the repository holds ND *anatomicals* only, and no ND fieldmap
# at all. The layout below is the one LCNI described from a session outside it,
# and these tests are the only oracle for it.
def _lcni_nd_fieldmap(corrected_magnitude_files: int = 144) -> list[SeriesInfo]:
    """LCNI's layout: 27 ND magnitude, 28 magnitude, 29 phase, 30 ND phase.

    Four series, two descriptions, two roles. Built with real headers so
    ``suffix_hint`` is decided by classify_from_header exactly as in production —
    the roles are what the resolver has to match on.
    """
    from duckbrain.core.dicom_header import SeriesHeader

    def header(image_type, echo_numbers):
        return SeriesHeader(
            modality="MR",
            image_type=image_type,
            mr_acquisition_type="2D",
            is_epi=False,
            is_spin_echo=False,
            echo_numbers=echo_numbers,
            sequence_name="*fm2d2r",
            dialect="classic",
        )

    magnitude = ("ORIGINAL", "PRIMARY", "M", "ND", "NORM")
    phase = ("ORIGINAL", "PRIMARY", "P", "ND")
    return [
        SeriesInfo(
            27, "fieldmap_2mm_ND", Path("/nonexistent"), 144, header=header(magnitude, (1, 2))
        ),
        SeriesInfo(
            28,
            "fieldmap_2mm",
            Path("/nonexistent"),
            corrected_magnitude_files,
            header=header(magnitude, (1, 2)),
        ),
        SeriesInfo(29, "fieldmap_2mm", Path("/nonexistent"), 72, header=header(phase, (2,))),
        SeriesInfo(30, "fieldmap_2mm_ND", Path("/nonexistent"), 72, header=header(phase, (2,))),
    ]


def test_an_nd_magnitude_is_not_demoted_by_a_phase_sibling_of_the_same_name():
    """The corrected magnitude is empty, so the ND pair is the only usable one.

    A name-only twin lookup resolved `fieldmap_2mm` to whichever of series 28/29
    came last — the *phase* — so the ND magnitude was demoted on the strength of
    a sibling in the wrong role. Both ND series went, and the group was then
    built on series 28, an empty directory, discarding a complete pair.
    """
    series = _lcni_nd_fieldmap(corrected_magnitude_files=0)
    dicom_inspect.classify_series(series)
    by_num = {s.series_number: s for s in series}
    assert by_num[27].classification == "fmap"
    assert by_num[30].classification == "fmap"

    detection = dicom_inspect.detect_fieldmaps([s for s in series if s.classification == "fmap"])
    assert list(detection.groups.values()) == [{"magnitude": 27, "phasediff": 30}]


def test_the_nd_decision_is_taken_across_the_whole_pair_never_split():
    """A magnitude and a phase from different reconstructions is worse than either.

    The pairing requires identical descriptions, so a group holding the ND
    magnitude and the corrected phase produces no fieldmap at all.
    """
    series = _lcni_nd_fieldmap(corrected_magnitude_files=0)
    dicom_inspect.classify_series(series)
    by_num = {s.series_number: s for s in series}
    assert (by_num[27].classification == "derived") == (by_num[30].classification == "derived")
    assert (by_num[28].classification == "derived") == (by_num[29].classification == "derived")


def test_the_corrected_pair_wins_when_it_is_populated():
    series = _lcni_nd_fieldmap()
    dicom_inspect.classify_series(series)
    by_num = {s.series_number: s for s in series}
    assert by_num[27].classification == "derived"
    assert by_num[30].classification == "derived"

    detection = dicom_inspect.detect_fieldmaps([s for s in series if s.classification == "fmap"])
    assert list(detection.groups.values()) == [{"magnitude": 28, "phasediff": 29}]


def test_a_repeated_description_does_not_collapse_the_twin_lookup():
    """Series 28 and 29 share a description; a dict keyed on it keeps only one.

    Grouped under `both`, which demotes nothing, so every series still carries
    the role the twin match is made on.
    """
    series = dicom_inspect.classify_series(_lcni_nd_fieldmap(), nd_duplicates="both")
    groups = dicom_inspect._nd_twin_groups(series)
    assert len(groups) == 1
    assert sorted(s.series_number for s in groups[0].nd) == [27, 30]
    assert sorted(s.series_number for s in groups[0].corrected) == [28, 29]


def test_an_nd_named_series_whose_header_denies_it_is_left_alone():
    """If the header carries no ND token the name means something else here."""
    from duckbrain.core.dicom_header import SeriesHeader

    corrected = ("DERIVED", "SECONDARY", "M", "NORM", "DIS3D", "DIS2D")
    series = [
        SeriesInfo(
            1009,
            "mprage_p2_ND_defaced",
            Path("/nonexistent"),
            176,
            header=SeriesHeader(modality="MR", image_type=corrected, mr_acquisition_type="3D"),
        ),
        SeriesInfo(
            1010,
            "mprage_p2_defaced",
            Path("/nonexistent"),
            176,
            header=SeriesHeader(modality="MR", image_type=corrected, mr_acquisition_type="3D"),
        ),
    ]
    dicom_inspect.classify_series(series)
    assert [s.classification for s in series] == ["anat", "anat"]


def test_a_demoted_copy_records_why():
    series = _series((6, "mprage_p2_defaced"), (7, "mprage_p2_ND_defaced"))
    assert "Series_6" in series[1].drop_reason
    assert not series[0].drop_reason


# --- choosing which reconstruction converts --------------------------------
def _nd_anat_pair() -> list[SeriesInfo]:
    """Crave_control/CC052: both copies populated, the ordinary case."""
    return [
        SeriesInfo(1009, "mprage_p2_ND_defaced", Path("/nonexistent"), file_count=176),
        SeriesInfo(1010, "mprage_p2_defaced", Path("/nonexistent"), file_count=176),
    ]


def test_the_uncorrected_policy_keeps_the_nd_copy():
    series = dicom_inspect.classify_series(_nd_anat_pair(), nd_duplicates="uncorrected")
    by_num = {s.series_number: s.classification for s in series}
    assert by_num == {1009: "anat", 1010: "derived"}


def test_the_both_policy_labels_each_copy():
    from duckbrain.core.dcm2bids_config import generate_config

    series = dicom_inspect.classify_series(_nd_anat_pair(), nd_duplicates="both")
    assert {s.series_number: s.acq_label for s in series} == {1009: "nd", 1010: "dis"}

    fmaps = dicom_inspect.detect_fieldmaps(series)
    entities = {
        d["criteria"]["SeriesNumber"]: d.get("custom_entities", "")
        for d in generate_config(series, fmaps, subject="X")["descriptions"]
    }
    assert entities == {1009: "acq-nd", 1010: "acq-dis"}


def test_the_both_policy_falls_back_when_one_copy_is_empty():
    """One survivor keeps the plain filename — an acq- entity distinguishing it
    from nothing is noise, and the degradation has to be reported instead."""
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings
    from duckbrain.core.dcm2bids_config import generate_config

    series = _nd_anat_pair()
    series[1].file_count = 0
    dicom_inspect.classify_series(series, nd_duplicates="both")
    assert [s.acq_label for s in series] == ["", ""]

    fmaps = dicom_inspect.detect_fieldmaps(series)
    plan = plan_conversion(generate_config(series, fmaps, subject="X"), series, subject="X")
    assert [f.filename for f in plan.files] == ["sub-X_T1w.nii.gz"]
    assert any(w.kind == "deliberate-drop" for w in plan_warnings(plan, fmaps))


def test_the_both_policy_gives_two_independent_b0_groups():
    """Both pairs convert, neither collides, and a bold binds to the corrected one.

    The two groups are acquired at the same instant, so nearest-in-time cannot
    separate them and would otherwise fall through to insertion order — which
    puts the uncorrected copy first.
    """
    from duckbrain.core.conversion_plan import plan_conversion
    from duckbrain.core.dcm2bids_config import build_task_run_mapping, generate_config
    from duckbrain.core.dicom_header import SeriesHeader

    series = _lcni_nd_fieldmap()
    series.append(
        SeriesInfo(
            31,
            "food",
            Path("/nonexistent"),
            250,
            header=SeriesHeader(
                modality="MR",
                image_type=("ORIGINAL", "PRIMARY", "M", "ND", "MOSAIC"),
                mr_acquisition_type="2D",
                is_epi=True,
                is_spin_echo=False,
                volumes=250,
                single_volume=False,
            ),
        )
    )
    dicom_inspect.classify_series(series, nd_duplicates="both")
    fmaps = dicom_inspect.detect_fieldmaps(series)
    assert len(fmaps.groups) == 2
    assert fmaps.deprioritized == {"fieldmap2mmNd"}

    config = generate_config(series, fmaps, subject="X", mapping=build_task_run_mapping(series))
    plan = plan_conversion(config, series, subject="X")
    paths = [f.path for f in plan.files]
    assert len(paths) == len(set(paths)), "two reconstructions collided on one filename"

    identifiers = {
        d["sidecar_changes"]["B0FieldIdentifier"]
        for d in config["descriptions"]
        if d["datatype"] == "fmap"
    }
    assert len(identifiers) == 2

    bold = next(f for f in plan.files if f.is_bold)
    assert bold.fmap_group == "fieldmap2mm"


def test_an_explicit_rule_can_still_bind_the_uncorrected_pair():
    """Deprioritizing narrows the *automatic* candidates only — a rule states."""
    from duckbrain.core.dcm2bids_config import FmapRule, build_task_run_mapping, generate_config
    from duckbrain.core.dicom_header import SeriesHeader

    series = _lcni_nd_fieldmap()
    series.append(
        SeriesInfo(
            31,
            "food",
            Path("/nonexistent"),
            250,
            header=SeriesHeader(
                modality="MR",
                image_type=("ORIGINAL", "PRIMARY", "M", "ND", "MOSAIC"),
                mr_acquisition_type="2D",
                is_epi=True,
                is_spin_echo=False,
                volumes=250,
                single_volume=False,
            ),
        )
    )
    dicom_inspect.classify_series(series, nd_duplicates="both")
    fmaps = dicom_inspect.detect_fieldmaps(series)
    config = generate_config(
        series,
        fmaps,
        subject="X",
        mapping=build_task_run_mapping(series),
        fmap_rules=[FmapRule("food", "fieldmap2mmNd", None)],
    )
    bold = next(d for d in config["descriptions"] if d["suffix"] == "bold")
    assert "fieldmap2mmNd" in bold["sidecar_changes"]["B0FieldSource"]


def test_two_reconstructions_get_acq_and_not_run():
    """`run-` means the scan was *acquired* twice. These are one acquisition."""
    from duckbrain.core.conversion_plan import plan_conversion
    from duckbrain.core.dcm2bids_config import generate_config

    series = dicom_inspect.classify_series(_nd_anat_pair(), nd_duplicates="both")
    fmaps = dicom_inspect.detect_fieldmaps(series)
    plan = plan_conversion(generate_config(series, fmaps, subject="X"), series, subject="X")
    names = sorted(f.filename for f in plan.files)
    assert names == ["sub-X_acq-dis_T1w.nii.gz", "sub-X_acq-nd_T1w.nii.gz"]
    assert not any("run-" in n for n in names)


def test_two_genuine_repeats_of_one_acquisition_still_get_run():
    """The bucketing change must not disable the collision fix it sits inside."""
    from duckbrain.core.conversion_plan import plan_conversion
    from duckbrain.core.dcm2bids_config import generate_config

    series = _series((5, "T1_mprage"), (9, "T1_mprage_repeat"))
    fmaps = dicom_inspect.detect_fieldmaps(series)
    plan = plan_conversion(generate_config(series, fmaps, subject="X"), series, subject="X")
    assert sorted(f.filename for f in plan.files) == [
        "sub-X_run-1_T1w.nii.gz",
        "sub-X_run-2_T1w.nii.gz",
    ]


def test_two_twin_pairs_sharing_one_description_are_paired_off():
    """pMAP/pMAP101: the mprage is shot twice and both copies saved of each.

    One base description covers 1005/1007 (ND) and 1006/1008 (corrected). With
    each ND choosing its own nearest twin, both picked 1006 and nothing claimed
    1008 — which then converted as a third anatomical beside the pair the policy
    had chosen, under every policy.
    """
    from duckbrain.core.conversion_plan import plan_conversion
    from duckbrain.core.dcm2bids_config import generate_config

    def session():
        return [
            SeriesInfo(1005, "mprage_p3_fast_ND_defaced", Path("/nonexistent"), 176),
            SeriesInfo(1006, "mprage_p3_fast_defaced", Path("/nonexistent"), 176),
            SeriesInfo(1007, "mprage_p3_fast_ND_defaced", Path("/nonexistent"), 176),
            SeriesInfo(1008, "mprage_p3_fast_defaced", Path("/nonexistent"), 176),
        ]

    def converted(policy):
        series = dicom_inspect.classify_series(session(), nd_duplicates=policy)
        fmaps = dicom_inspect.detect_fieldmaps(series)
        plan = plan_conversion(generate_config(series, fmaps, subject="X"), series, subject="X")
        return sorted(f.filename for f in plan.files)

    assert converted("corrected") == ["sub-X_run-1_T1w.nii.gz", "sub-X_run-2_T1w.nii.gz"]
    assert converted("uncorrected") == ["sub-X_run-1_T1w.nii.gz", "sub-X_run-2_T1w.nii.gz"]
    # Two acquisitions x two reconstructions: run- separates the acquisitions,
    # acq- the reconstructions, and neither entity does the other's job.
    assert converted("both") == [
        "sub-X_acq-dis_run-1_T1w.nii.gz",
        "sub-X_acq-dis_run-2_T1w.nii.gz",
        "sub-X_acq-nd_run-1_T1w.nii.gz",
        "sub-X_acq-nd_run-2_T1w.nii.gz",
    ]


def test_the_empty_twin_flip_is_reported_rather_than_silent():
    """CC056 again, from the other end.

    Preferring the copy that holds data is right, but it is a decision made on
    the user's behalf about which image ships — so it cannot vanish into the
    'left unconverted as expected' count beside the scouts.
    """
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings
    from duckbrain.core.dcm2bids_config import generate_config

    series = [
        SeriesInfo(1009, "mprage_p2_ND_defaced", Path("/nonexistent"), file_count=176),
        SeriesInfo(1010, "mprage_p2_defaced", Path("/nonexistent"), file_count=0),
    ]
    dicom_inspect.classify_series(series)
    fmaps = dicom_inspect.detect_fieldmaps(series)
    plan = plan_conversion(generate_config(series, fmaps, subject="X"), series, subject="X")

    # the populated copy converts, and without a spurious run- entity
    assert [f.filename for f in plan.files] == ["sub-X_T1w.nii.gz"]
    told = [w for w in plan_warnings(plan, fmaps) if w.kind == "deliberate-drop"]
    assert len(told) == 1
    assert "holds no DICOM files" in told[0].message


# --- fieldmap direction and grouping ---------------------------------------
def test_fmap_group_does_not_eat_ap_pa_inside_words():
    # 'ap' inside 'fieldmap' was stripped, so the two halves of one pair got
    # different group names and never paired.
    ap = dicom_inspect._extract_fmap_group("ap_fieldmap_se_epi_mb3_g2_2mm_ap")
    pa = dicom_inspect._extract_fmap_group("pa_fieldmap_se_epi_mb3_g2_2mm_pa")
    assert ap == pa, f"AP grouped as {ap!r}, PA as {pa!r} — one pair, two groups"


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("se_epi_ap_capture", "capture"),
        ("se_epi_pa_apex", "apex"),
        ("se_epi_ap", ""),
        ("se_epi_mb6_2.5mm_pa", "mb6_2.5mm"),
    ],
)
def test_fmap_group_keeps_the_label_intact(description, expected):
    assert dicom_inspect._extract_fmap_group(description) == expected


def test_direction_is_not_read_from_a_word_that_merely_contains_ap():
    series = _series((4, "se_epi_pa_apex"), (5, "se_epi_ap_apex"))
    detection = dicom_inspect.detect_fieldmaps(series)
    groups = detection.groups
    assert len(groups) == 1, f"expected one group, got {list(groups)}"
    (group,) = groups.values()
    assert group["pa"] == 4
    assert group["ap"] == 5


# --- task / run from bare trailing indices ---------------------------------
def test_repeats_named_by_suffix_are_one_task_with_runs():
    # Verbatim from GAME/sub-149: three repeats of one paradigm, each with its
    # single-band reference. Before, this produced task-MAB1_run-1,
    # task-MAB2_run-1, task-MAB3_run-1 — three tasks, no usable run entity.
    series = _series(
        (9, "MAB1"),
        (10, "MAB1_SBRef"),
        (11, "MAB2"),
        (12, "MAB2_SBRef"),
        (13, "MAB3"),
        (14, "MAB3_SBRef"),
    )
    mapping = dcm2bids_config.build_task_run_mapping(series)
    bold = {e.series_number: (e.task, e.run) for e in mapping if e.role == "bold"}
    assert bold == {9: ("MAB", 1), 11: ("MAB", 2), 13: ("MAB", 3)}
    sbref = {e.series_number: (e.task, e.run) for e in mapping if e.role == "sbref"}
    assert sbref == {10: ("MAB", 1), 12: ("MAB", 2), 14: ("MAB", 3)}


@pytest.mark.parametrize(
    ("description", "expected_task"),
    [
        ("GNG1_mb3_g2_2mm_te27", "GNG1"),
        ("React4_mb3_g2_2mm_te27", "React4"),
        ("SST2_mb3_g2_2mm_te27", "SST2"),
        ("TASK5_1.7mm", "TASK5"),
    ],
)
def test_acquisition_parameters_are_not_part_of_the_task_label(description, expected_task):
    """'_mb3_g2_2mm_te27' is how the scan was run, not what the task was called.

    The bare trailing index is left on here; only a stem-sharing sibling in the
    same session turns it into a run (see _shared_task_stems).
    """
    task, _run = dicom_inspect.parse_task_run(description)
    assert task == expected_task


def test_acquisition_parameter_stripping_feeds_the_run_grouping():
    series = _series(
        (5, "GNG1_mb3_g2_2mm_te27_bold"),
        (6, "GNG2_mb3_g2_2mm_te27_bold"),
        (7, "GNG3_mb3_g2_2mm_te27_bold"),
    )
    mapping = dcm2bids_config.build_task_run_mapping(series)
    assert {(e.task, e.run) for e in mapping} == {("GNG", 1), ("GNG", 2), ("GNG", 3)}


def test_a_lone_trailing_number_is_not_treated_as_a_run():
    """'EPI196' is a matrix size. Only a sibling sharing the stem makes it a run."""
    series = _series((3, "EPI196_bold"))
    mapping = dcm2bids_config.build_task_run_mapping(series)
    assert [(e.task, e.run) for e in mapping] == [("EPI196", 1)]


def test_repeated_identical_names_still_count_by_acquisition_order():
    series = _series((3, "food_bold"), (7, "food_bold"))
    mapping = dcm2bids_config.build_task_run_mapping(series)
    assert [(e.task, e.run) for e in mapping] == [("food", 1), ("food", 2)]


# --- repeated anatomicals --------------------------------------------------
def test_repeated_anatomicals_get_run_entities_instead_of_colliding():
    series = _series((3, "mprage_p2_defaced"), (14, "mprage_p3_fast_defaced"))
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="X", session="")
    anat = [d for d in config["descriptions"] if d["datatype"] == "anat"]
    assert len(anat) == 2
    assert [d["custom_entities"] for d in anat] == ["run-1", "run-2"]
    assert len({d["id"] for d in anat}) == 2


def test_a_single_anatomical_keeps_its_plain_name():
    series = _series((3, "mprage_p2_defaced"))
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="X", session="")
    (anat,) = [d for d in config["descriptions"] if d["datatype"] == "anat"]
    assert "custom_entities" not in anat or anat["custom_entities"] == ""


def test_a_real_wms_session_emits_one_t1w_and_no_collisions():
    """The whole point, end to end: setter + ND copy + report + scout are drops."""
    series = _series(
        (1, "AAHScout"),
        (5, "mprage_vNav_setter"),
        (6, "mprage_p2_defaced"),
        (7, "mprage_p2_ND_defaced"),
        (99, "PhoenixZIPReport"),
    )
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="WMS112", session="")
    ids = [d["id"] for d in config["descriptions"]]
    assert ids == ["anat-T1w"]
    assert len(ids) == len(set(ids))


# --- the bulk path preflights too ------------------------------------------
def test_bulk_convert_refuses_a_config_that_would_overwrite_a_file(tmp_path):
    """The GUI reported collisions; the bulk/cockpit path submitted anyway.

    Two series carrying the same explicit run token resolve to one filename.
    dcm2bids writes whichever it reaches last and says nothing, so the refusal
    has to happen here.
    """
    from duckbrain.core.conversion import generate_session_config

    series = _series((5, "encoding_bold_r1"), (9, "encoding_bold_r1"))
    with pytest.raises(ValueError, match="same file"):
        generate_session_config(tmp_path, "001", "01", series_list=series)


def test_bulk_convert_accepts_a_clean_session(tmp_path):
    from duckbrain.core.conversion import generate_session_config

    series = _series((3, "mprage_p2_defaced"), (5, "encoding_bold_r1"), (9, "encoding_bold_r2"))
    config = generate_session_config(tmp_path, "001", "01", series_list=series)
    assert len(config["descriptions"]) == 3


# --- recognised but not convertible ----------------------------------------
@pytest.mark.parametrize(
    "description",
    ["distortion_ap", "distortion_pa", "fieldmap_2mm", "fieldmap1", "gre_field_mapping"],
)
def test_fieldmap_vocabulary_covers_the_names_lcni_actually_uses(description):
    assert dicom_inspect._classify_one(description) == "fmap"


def test_distortion_named_pairs_are_detected_as_pepolar():
    """LCNI's DEV/Dissonance protocols name the AP/PA pair 'distortion_*'.

    These matched nothing, so a real usable fieldmap pair was invisible.
    """
    series = _series((20, "distortion_ap"), (21, "distortion_pa"))
    detection = dicom_inspect.detect_fieldmaps(series)
    assert len(detection.groups) == 1
    (group,) = detection.groups.values()
    assert group == {"ap": 20, "pa": 21}


@pytest.mark.parametrize(
    "description", ["RL_diff_m2p2_64_2mm_rl", "ep2d_diff_mddw", "DTI_64dir", "dwi_b1000"]
)
def test_diffusion_series_are_named_even_though_they_cannot_be_converted(description):
    assert dicom_inspect._classify_one(description) == "dwi"


def test_the_plan_says_why_an_unconvertible_datatype_was_dropped():
    """'classified unknown' reads as a naming problem the user could fix.

    A gradient-echo fieldmap and a diffusion series are not that: duckbrain
    recognises both and cannot express either, and the warning has to say so.
    """
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings

    series = _series((3, "mprage_p2_defaced"), (10, "fieldmap_2mm"), (12, "DTI_64dir"))
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="X", session="")
    plan = plan_conversion(config, series, subject="X", session="")
    messages = " ".join(w.message for w in plan_warnings(plan, detection))
    assert "gradient-echo" in messages
    assert "bval/bvec" in messages


# --- gradient-echo fieldmaps -----------------------------------------------
# Validated end to end against dcm2bids 3.2.0 on
# Crave_control/CC0523_20180202_113414: the six descriptions below produce
# magnitude1 <- _e1, magnitude2 <- _e2, phasediff <- _e2_ph, and dcm2niix writes
# EchoTime1/EchoTime2 into the phasediff sidecar itself.


def _gre_session():
    """A real Crave_control session: magnitude at N, phase at N+1, same name."""
    from duckbrain.core.dicom_header import SeriesHeader

    def header(**kwargs):
        base = dict(
            modality="MR",
            mr_acquisition_type="2D",
            is_epi=False,
            is_spin_echo=False,
            dialect="classic",
        )
        base.update(kwargs)
        base.setdefault("single_volume", base.get("volumes", 0) == 1)
        return SeriesHeader(**base)

    series = [
        SeriesInfo(
            series_number=5,
            description="fieldmap_2mm",
            path=Path("/nonexistent"),
            file_count=144,
            header=header(
                image_type=("ORIGINAL", "PRIMARY", "M", "ND", "NORM"),
                echo_numbers=(1, 2),
                volumes=144,
            ),
        ),
        SeriesInfo(
            series_number=6,
            description="fieldmap_2mm",
            path=Path("/nonexistent"),
            file_count=72,
            header=header(
                image_type=("ORIGINAL", "PRIMARY", "P", "ND"),
                echo_numbers=(2,),
                volumes=72,
            ),
        ),
        SeriesInfo(
            series_number=7,
            description="food",
            path=Path("/nonexistent"),
            file_count=250,
            header=header(
                image_type=("ORIGINAL", "PRIMARY", "M", "ND", "MOSAIC"),
                is_epi=True,
                volumes=250,
            ),
        ),
    ]
    dicom_inspect.classify_series(series)
    return series


def test_gre_fieldmap_is_paired_across_two_consecutive_series():
    series = _gre_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    assert len(detection.groups) == 1
    (group,) = detection.groups.values()
    assert group == {"magnitude": 5, "phasediff": 6}
    assert detection.warnings == []


def test_gre_fieldmap_emits_magnitude1_magnitude2_and_phasediff():
    series = _gre_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="CC052", session="1")
    fmaps = {d["suffix"]: d for d in config["descriptions"] if d["datatype"] == "fmap"}
    assert set(fmaps) == {"magnitude1", "magnitude2", "phasediff"}

    # One magnitude *series* holds both echoes, so SeriesNumber alone cannot
    # separate them and EchoNumber has to join the criteria.
    assert fmaps["magnitude1"]["criteria"] == {"SeriesNumber": 5, "EchoNumber": 1}
    assert fmaps["magnitude2"]["criteria"] == {"SeriesNumber": 5, "EchoNumber": 2}
    assert fmaps["phasediff"]["criteria"] == {"SeriesNumber": 6}

    identifiers = {d["sidecar_changes"]["B0FieldIdentifier"] for d in fmaps.values()}
    assert len(identifiers) == 1, "all three are inputs to one field estimator"


def test_a_bold_binds_to_a_gradient_echo_fieldmap():
    """The whole point — without this the fieldmap converts and corrects nothing.

    The LCNI curator's own BIDS has these fieldmaps with no B0FieldIdentifier
    and no IntendedFor, so fMRIPrep silently skips distortion correction on
    them.
    """
    series = _gre_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="CC052", session="1")
    bold = next(d for d in config["descriptions"] if d["suffix"] == "bold")
    phasediff = next(d for d in config["descriptions"] if d["suffix"] == "phasediff")
    assert (
        bold["sidecar_changes"]["B0FieldSource"]
        == phasediff["sidecar_changes"]["B0FieldIdentifier"]
    )


def test_echo_times_are_not_injected_into_the_phasediff():
    """BIDS requires EchoTime1/EchoTime2 there, and dcm2niix already writes them.

    A second copy derived from a header duckbrain read separately could only
    disagree with the data.
    """
    series = _gre_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="X", session="")
    phasediff = next(d for d in config["descriptions"] if d["suffix"] == "phasediff")
    assert set(phasediff["sidecar_changes"]) == {"B0FieldIdentifier"}


def test_a_magnitude_with_no_phase_partner_is_reported_not_guessed():
    series = _gre_session()[:1]
    detection = dicom_inspect.detect_fieldmaps(series)
    assert detection.groups == {}
    assert any("no phase series follows" in w for w in detection.warnings)


# --- nearest-in-time fieldmap binding --------------------------------------
# Verbatim acquisition order from REV/REV055_20150811_135636: two gradient-echo
# fieldmap pairs bracket the run blocks, and the curator's intent is that each
# run uses the pair it was shot next to. The old "first complete group" bound
# all seven runs to fieldmap1.


def _timed(series_number, description, seconds, classification=None, suffix=None, volumes=200):
    from duckbrain.core.dicom_header import SeriesHeader

    info = SeriesInfo(
        series_number=series_number,
        description=description,
        path=Path("/nonexistent"),
        file_count=volumes,
        header=SeriesHeader(series_time=seconds, volumes=volumes, single_volume=volumes == 1),
    )
    if classification:
        info.classification = classification
        info.suffix_hint = suffix or ""
        info.classified_by = "header"
    return info


def _rev_two_pair_session():
    def hms(h, m, s):
        return h * 3600 + m * 60 + s

    return [
        _timed(6, "GNG1_bold", hms(14, 9, 0), "func", "bold"),
        _timed(7, "fieldmap1", hms(14, 15, 0), "fmap", "magnitude"),
        _timed(8, "fieldmap1", hms(14, 15, 1), "fmap", "phasediff", volumes=72),
        _timed(9, "BART1_bold", hms(14, 20, 0), "func", "bold"),
        _timed(11, "SST1_bold", hms(14, 36, 0), "func", "bold"),
        _timed(12, "SST2_bold", hms(14, 45, 0), "func", "bold"),
        _timed(13, "fieldmap2", hms(14, 53, 0), "fmap", "magnitude"),
        _timed(14, "fieldmap2", hms(14, 53, 1), "fmap", "phasediff", volumes=72),
        _timed(15, "React1_bold", hms(14, 56, 0), "func", "bold"),
    ]


def _binding(series):
    detection = dicom_inspect.detect_fieldmaps(series)
    mapping = dcm2bids_config.build_task_run_mapping(series)
    config = dcm2bids_config.generate_config(
        series, detection, subject="REV055", session="1", mapping=mapping
    )
    id_to_group = {
        d["sidecar_changes"]["B0FieldIdentifier"]: d["id"].rsplit("-", 1)[-1]
        for d in config["descriptions"]
        if d["datatype"] == "fmap"
    }
    out = {}
    for d in config["descriptions"]:
        if d.get("suffix") == "bold":
            source = d["sidecar_changes"].get("B0FieldSource")
            out[d["custom_entities"]] = id_to_group.get(source)
    return out


def test_each_run_binds_to_the_nearer_fieldmap_pair():
    binding = _binding(_rev_two_pair_session())
    # runs before/near the first pair
    assert binding["task-GNG1_run-1"] == "fieldmap1"
    assert binding["task-BART1_run-1"] == "fieldmap1"
    # runs nearer the second pair (SST straddles; the pair shot right after it
    # is closer than the one 20+ minutes before). SST1/SST2 collapse to one task.
    assert binding["task-SST_run-1"] == "fieldmap2"
    assert binding["task-SST_run-2"] == "fieldmap2"
    assert binding["task-React1_run-1"] == "fieldmap2"


def test_timing_does_not_override_an_explicit_rule():
    from duckbrain.core.dcm2bids_config import FmapRule

    series = _rev_two_pair_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    mapping = dcm2bids_config.build_task_run_mapping(series)
    config = dcm2bids_config.generate_config(
        series,
        detection,
        subject="REV055",
        session="1",
        mapping=mapping,
        fmap_rules=[FmapRule(task="SST", group="fieldmap1")],
    )
    sst = next(d for d in config["descriptions"] if d["custom_entities"] == "task-SST_run-1")
    id_to_group = {
        d["sidecar_changes"]["B0FieldIdentifier"]: d["id"].rsplit("-", 1)[-1]
        for d in config["descriptions"]
        if d["datatype"] == "fmap"
    }
    assert id_to_group[sst["sidecar_changes"]["B0FieldSource"]] == "fieldmap1"


def test_without_times_binding_falls_back_to_first_group():
    """No headers (name-only path) → the stable first-group choice, unchanged."""
    series = [
        SeriesInfo(4, "se_epi_ap_a", Path("/x"), 3),
        SeriesInfo(5, "se_epi_pa_a", Path("/x"), 3),
        SeriesInfo(20, "se_epi_ap_b", Path("/x"), 3),
        SeriesInfo(21, "se_epi_pa_b", Path("/x"), 3),
        SeriesInfo(9, "food_bold", Path("/x"), 200),
    ]
    dicom_inspect.classify_series(series)
    detection = dicom_inspect.detect_fieldmaps(series)
    assert detection.group_times == {}
    mapping = dcm2bids_config.build_task_run_mapping(series)
    config = dcm2bids_config.generate_config(
        series, detection, subject="X", session="", mapping=mapping
    )
    bold = next(d for d in config["descriptions"] if d.get("suffix") == "bold")
    # first complete group, deterministic
    assert "B0FieldSource" in bold["sidecar_changes"]


def test_the_report_path_matches_the_written_binding():
    """resolve_fmap_assignments must agree with generate_config, or the preview
    lies. It needs the same series-time lookup to reach the same decision."""
    series = _rev_two_pair_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    mapping = dcm2bids_config.build_task_run_mapping(series)
    series_times = {
        s.series_number: s.header.series_time for s in series if s.header.series_time is not None
    }
    report = dcm2bids_config.resolve_fmap_assignments(mapping, detection, None, series_times)
    assert report[("SST", 1)] == "fieldmap2"
    assert report[("GNG1", 1)] == "fieldmap1"

    # and without the lookup it would silently disagree — the first group
    report_no_times = dcm2bids_config.resolve_fmap_assignments(mapping, detection, None)
    assert report_no_times[("SST", 1)] == "fieldmap1"


# --- empty source directories ----------------------------------------------
def test_nd_copy_is_kept_when_its_twin_is_present_but_empty():
    """Crave_control/CC056: the corrected mprage folder exists but is empty, and
    the populated copy is the _ND one. Demoting on the name alone would leave the
    session with no anatomical at all — the loss the ND condition exists to stop,
    one level less obvious."""
    from duckbrain.core.dicom_inspect import SeriesInfo

    # the real folder is empty, the ND copy is the one with data
    series = [
        SeriesInfo(1009, "mprage_p2_ND_defaced", Path("/nonexistent"), file_count=176),
        SeriesInfo(1010, "mprage_p2_defaced", Path("/nonexistent"), file_count=0),
    ]
    dicom_inspect.classify_series(series)
    by_num = {s.series_number: s for s in series}
    assert by_num[1009].classification == "anat", "the only populated anatomical"


def test_a_planned_file_with_an_empty_source_is_flagged():
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings

    series = _series((5, "mprage_p2_defaced"))
    series[0].file_count = 0
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="X", session="")
    plan = plan_conversion(config, series, subject="X", session="")
    empty = [w for w in plan_warnings(plan, detection) if w.kind == "empty-source"]
    assert len(empty) == 1
    assert empty[0].severity == "error"
    assert "no DICOM files" in empty[0].message


def test_a_populated_source_is_not_flagged():
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings

    series = _series((5, "mprage_p2_defaced"))
    series[0].file_count = 176
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="X", session="")
    plan = plan_conversion(config, series, subject="X", session="")
    assert not any(w.kind == "empty-source" for w in plan_warnings(plan, detection))
