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
