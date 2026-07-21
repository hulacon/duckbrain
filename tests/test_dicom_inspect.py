"""Tests for duckbrain DICOM inspection module."""

import pytest
from pathlib import Path

from duckbrain.core.dicom_inspect import (
    list_series,
    classify_series,
    detect_fieldmaps,
    extract_task_label,
    get_bold_series,
)


@pytest.fixture
def mock_dicom_session(tmp_path):
    """Create a mock DICOM session directory with various series."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    series = [
        ("Series_01_AAhead_scout", 3),
        ("Series_02_ABCD_T1w_MPR_vNav", 176),
        ("Series_03_ABCD_T2w_SPC_vNav", 176),
        ("Series_04_se_epi_ap_encoding", 3),
        ("Series_05_se_epi_pa_encoding", 3),
        ("Series_06_cmrr_mbep2d_bold_task-encoding_run-1_SBRef", 1),
        ("Series_07_cmrr_mbep2d_bold_task-encoding_run-1", 300),
        ("Series_08_cmrr_mbep2d_bold_task-encoding_run-2_SBRef", 1),
        ("Series_09_cmrr_mbep2d_bold_task-encoding_run-2", 300),
        ("Series_10_cmrr_mbep2d_bold_task-rest", 200),
        ("Series_11_PhysioLog", 1),
        ("Series_12_se_epi_ap_retrieval", 3),
        ("Series_13_se_epi_pa_retrieval", 3),
        ("Series_14_cmrr_mbep2d_bold_task-retrieval_run-1", 250),
    ]

    for name, file_count in series:
        d = session_dir / name
        d.mkdir()
        for i in range(file_count):
            (d / f"file_{i:04d}.dcm").touch()

    return session_dir


def test_list_series(mock_dicom_session):
    series = list_series(mock_dicom_session)
    assert len(series) == 14
    assert series[0].series_number == 1
    assert series[0].description == "AAhead_scout"
    assert series[-1].series_number == 14


def test_classify_series(mock_dicom_session):
    series = list_series(mock_dicom_session)
    classify_series(series)

    classifications = {s.description: s.classification for s in series}
    assert classifications["AAhead_scout"] == "scout"
    assert classifications["ABCD_T1w_MPR_vNav"] == "anat"
    assert classifications["ABCD_T2w_SPC_vNav"] == "anat"
    assert classifications["se_epi_ap_encoding"] == "fmap"
    assert classifications["cmrr_mbep2d_bold_task-encoding_run-1"] == "func"
    assert classifications["cmrr_mbep2d_bold_task-encoding_run-1_SBRef"] == "sbref"
    assert classifications["PhysioLog"] == "physio"


@pytest.fixture
def descriptive_naming_session(tmp_path):
    """A session whose BOLD runs use study-specific names with no 'bold'/'task-'
    marker, but each has a matching _SBRef sibling (DIVATTEN-style)."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    series = [
        ("Series_1_AAHead_Scout_64ch-head-coil", 128),
        ("Series_5_mprage_p2_64ch", 176),
        ("Series_6_se_epi_2.5mm_ap", 1),
        ("Series_7_se_epi_2.5mm_pa", 1),
        ("Series_8_div_perFace_perTone_r1_SBRef", 1),
        ("Series_9_div_perFace_perTone_r1", 332),
        ("Series_10_single_retScene_r2_SBRef", 1),
        ("Series_11_single_retScene_r2", 332),
    ]
    for name, file_count in series:
        d = session_dir / name
        d.mkdir()
        for i in range(file_count):
            (d / f"file_{i:04d}.dcm").touch()
    return session_dir


def test_classify_recovers_func_via_sbref(descriptive_naming_session):
    series = classify_series(list_series(descriptive_naming_session))
    by_desc = {s.description: s.classification for s in series}

    # Runs with no 'bold'/'task-' marker but a matching _SBRef -> func
    assert by_desc["div_perFace_perTone_r1"] == "func"
    assert by_desc["single_retScene_r2"] == "func"
    # SBRefs, anat, fmap, scout unchanged
    assert by_desc["div_perFace_perTone_r1_SBRef"] == "sbref"
    assert by_desc["mprage_p2_64ch"] == "anat"
    assert by_desc["se_epi_2.5mm_ap"] == "fmap"
    assert by_desc["AAHead_Scout_64ch-head-coil"] == "scout"

    bolds = get_bold_series(series, min_volumes=20)
    assert {b.description for b in bolds} == {
        "div_perFace_perTone_r1",
        "single_retScene_r2",
    }


def test_classify_no_sbref_leaves_unknown(tmp_path):
    """Without SBRef siblings, unrecognized series stay 'unknown' (no blind
    volume-count promotion that could mislabel DWI/ASL as func)."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    for name, n in [("Series_1_diff_mb3_98dir", 98), ("Series_2_mprage", 176)]:
        d = session_dir / name
        d.mkdir()
        (d / "f.dcm").touch()
    series = classify_series(list_series(session_dir))
    by_desc = {s.description: s.classification for s in series}
    assert by_desc["diff_mb3_98dir"] == "unknown"
    assert by_desc["mprage"] == "anat"


@pytest.fixture
def mmm_localizer_session(tmp_path):
    """MMM origin-study naming: functional *localizer* tasks (not scanner
    localizers) with SBRef + PhysioLog siblings, plus a real AAHead scout."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    series = [
        ("Series_01_AAhead_scout", 3),
        ("Series_02_AAhead_scout_MPR_sag", 3),
        ("Series_05_se_epi_ap", 3),
        ("Series_07_localizer_prf_run1_SBRef", 1),
        ("Series_08_localizer_prf_run1", 300),
        ("Series_10_localizer_prf_run1_PhysioLog", 1),
        ("Series_35_localizer_tone_SBRef", 1),
        ("Series_36_localizer_tone", 200),
        ("Series_38_localizer_tone_PhysioLog", 1),
    ]
    for name, n in series:
        d = session_dir / name
        d.mkdir()
        for i in range(n):
            (d / f"f_{i:04d}.dcm").touch()
    return session_dir


def test_functional_localizer_not_scout(mmm_localizer_session):
    series = classify_series(list_series(mmm_localizer_session))
    by_desc = {s.description: s.classification for s in series}

    # Functional localizer runs -> func (rescued by SBRef pairing), not scout
    assert by_desc["localizer_prf_run1"] == "func"
    assert by_desc["localizer_tone"] == "func"
    # Their SBRef / PhysioLog siblings keep their definitive class, not scout
    assert by_desc["localizer_prf_run1_SBRef"] == "sbref"
    assert by_desc["localizer_prf_run1_PhysioLog"] == "physio"
    # The *actual* scanner scout is still scout
    assert by_desc["AAhead_scout"] == "scout"
    assert by_desc["AAhead_scout_MPR_sag"] == "scout"
    assert by_desc["se_epi_ap"] == "fmap"

    bolds = get_bold_series(series, min_volumes=20)
    assert {b.description for b in bolds} == {"localizer_prf_run1", "localizer_tone"}


def test_standalone_localizer_and_scout_are_scout(tmp_path):
    session_dir = tmp_path / "s"
    session_dir.mkdir()
    for name in ["Series_1_localizer", "Series_2_scout", "Series_3_AAHead_Scout_64ch"]:
        (session_dir / name).mkdir()
        (session_dir / name / "f.dcm").touch()
    series = classify_series(list_series(session_dir))
    assert all(s.classification == "scout" for s in series), {
        s.description: s.classification for s in series
    }


def test_detect_fieldmaps(mock_dicom_session):
    series = list_series(mock_dicom_session)
    classify_series(series)
    fmaps = detect_fieldmaps(series)

    assert fmaps.strategy == "series_description"
    assert "encoding" in fmaps.groups
    assert "retrieval" in fmaps.groups
    assert fmaps.groups["encoding"]["ap"] == 4
    assert fmaps.groups["encoding"]["pa"] == 5
    assert fmaps.groups["retrieval"]["ap"] == 12
    assert fmaps.groups["retrieval"]["pa"] == 13


def _fmap_series(pairs):
    """Build classified fmap SeriesInfo from (series_number, description) tuples."""
    from duckbrain.core.dicom_inspect import SeriesInfo

    out = []
    for num, desc in pairs:
        s = SeriesInfo(series_number=num, description=desc, path=None, file_count=3)
        s.classification = "fmap"
        out.append(s)
    return out


def test_detect_fieldmaps_single_unnamed_pair_unchanged():
    """A lone unnamed AP/PA pair keeps the historical empty-name group and adds
    no distinguishing entity."""
    series = _fmap_series([(6, "se_epi_ap"), (7, "se_epi_pa")])
    fmaps = detect_fieldmaps(series)
    assert list(fmaps.groups) == [""]
    assert fmaps.groups[""] == {"ap": 6, "pa": 7}
    assert fmaps.group_entities == {}
    assert not any("Duplicate" in w for w in fmaps.warnings)


def test_detect_fieldmaps_multiple_unnamed_pairs_split_by_order():
    """Two reacquired plain AP/PA pairs become two run-numbered groups instead of
    collapsing into one 'Duplicate AP' warning."""
    series = _fmap_series(
        [(6, "se_epi_ap"), (7, "se_epi_pa"), (20, "se_epi_ap"), (21, "se_epi_pa")]
    )
    fmaps = detect_fieldmaps(series)
    assert fmaps.groups == {"1": {"ap": 6, "pa": 7}, "2": {"ap": 20, "pa": 21}}
    assert fmaps.group_entities == {"1": "run-1", "2": "run-2"}
    assert not any("Duplicate" in w for w in fmaps.warnings)


def test_detect_fieldmaps_named_pairs_get_acq_entities():
    """Two named pairs each get an acq- entity so their dir-AP files stay distinct."""
    series = _fmap_series(
        [
            (4, "se_epi_ap_encoding"),
            (5, "se_epi_pa_encoding"),
            (12, "se_epi_ap_retrieval"),
            (13, "se_epi_pa_retrieval"),
        ]
    )
    fmaps = detect_fieldmaps(series)
    assert fmaps.group_entities == {"encoding": "acq-encoding", "retrieval": "acq-retrieval"}


def test_detect_fieldmaps_reacquired_named_pair_is_kept():
    """A named group reshot mid-session yields one pair per acquisition.

    Modeled on MMM_005_sess19 in /projects/lcni/dcm/hulacon/mmmdata, which shoots
    se_epi_*_encoding three times and retrieval once. This used to warn
    "Duplicate AP in group 'encoding'" and keep only the last pair — two thirds
    of the fieldmaps were silently discarded.
    """
    series = _fmap_series(
        [
            (5, "se_epi_ap_encoding"),
            (7, "se_epi_pa_encoding"),
            (21, "se_epi_ap_encoding"),
            (23, "se_epi_pa_encoding"),
            (33, "se_epi_ap_encoding"),
            (35, "se_epi_pa_encoding"),
            (45, "se_epi_ap_retrieval"),
            (47, "se_epi_pa_retrieval"),
        ]
    )
    fmaps = detect_fieldmaps(series)
    assert fmaps.groups == {
        "encoding": {"ap": 5, "pa": 7},
        "encoding-2": {"ap": 21, "pa": 23},
        "encoding-3": {"ap": 33, "pa": 35},
        "retrieval": {"ap": 45, "pa": 47},
    }
    assert fmaps.group_entities == {
        "encoding": "acq-encoding_run-1",
        "encoding-2": "acq-encoding_run-2",
        "encoding-3": "acq-encoding_run-3",
        "retrieval": "acq-retrieval",
    }
    assert not any("Duplicate" in w for w in fmaps.warnings)


def test_detect_fieldmaps_aborted_ap_leaves_an_incomplete_group():
    """A repeated opening AP (an aborted scan) is reported, not folded away.

    Modeled on MMM_003_sess18: se_epi_ap, se_epi_ap, se_epi_pa, then a later pair.
    """
    series = _fmap_series(
        [
            (5, "se_epi_ap"),
            (6, "se_epi_ap"),
            (7, "se_epi_pa"),
            (12, "se_epi_ap"),
            (14, "se_epi_pa"),
        ]
    )
    fmaps = detect_fieldmaps(series)
    assert fmaps.groups == {"1": {"ap": 5}, "2": {"ap": 6, "pa": 7}, "3": {"ap": 12, "pa": 14}}
    assert any("missing PA" in w for w in fmaps.warnings)


def test_detect_fieldmaps_none(tmp_path):
    session_dir = tmp_path / "no_fmaps"
    session_dir.mkdir()
    (session_dir / "Series_01_T1w").mkdir()
    (session_dir / "Series_01_T1w" / "file.dcm").touch()

    series = list_series(session_dir)
    classify_series(series)
    fmaps = detect_fieldmaps(series)
    assert fmaps.strategy == "none"


def test_extract_task_label():
    assert extract_task_label("cmrr_mbep2d_bold_task-encoding_run-1") == "encoding"
    assert extract_task_label("task_rest_bold") == "rest"
    assert extract_task_label("cmrr_mbep2d_bold_task-retrieval_run-2") == "retrieval"


def test_get_bold_series(mock_dicom_session):
    series = list_series(mock_dicom_session)
    classify_series(series)
    bolds = get_bold_series(series, min_volumes=20)

    # Should exclude SBRef, PhysioLog, scout, and low-volume series
    # Includes: encoding run-1 (300), encoding run-2 (300), rest (200), retrieval run-1 (250)
    assert len(bolds) == 4

    # Higher threshold excludes rest (200 < 250)
    bolds_high = get_bold_series(series, min_volumes=250)
    assert len(bolds_high) == 3  # encoding run-1, encoding run-2, retrieval run-1
