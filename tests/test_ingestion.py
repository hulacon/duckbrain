"""Tests for duckbrain ingestion module."""

import pytest
from pathlib import Path

from duckbrain.core.ingestion import (
    auto_number_sessions,
    discover_sessions,
    ingest_session,
    list_ingested_sessions,
    BidsMapping,
    SessionInfo,
)


@pytest.fixture
def mock_dcm_source(tmp_path):
    """Create a mock LCNI DICOM source directory."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()

    # Create session folders
    for name in [
        "MMM_003_sess05_20250301_120000",
        "MMM_003_sess06_20250315_140000",
        "MMM_004_sess01_20250320_100000",
    ]:
        sess_dir = dcm_dir / name
        sess_dir.mkdir()
        # Create some Series directories
        for i in range(1, 6):
            series_dir = sess_dir / f"Series_{i:02d}_description_{i}"
            series_dir.mkdir()
            # Add a dummy file
            (series_dir / f"file_{i}.dcm").touch()

    return dcm_dir


@pytest.fixture
def mock_sourcedata(tmp_path):
    """Create a mock sourcedata directory."""
    sd = tmp_path / "sourcedata"
    sd.mkdir()
    return sd


def test_discover_sessions(mock_dcm_source):
    sessions = discover_sessions(mock_dcm_source)
    assert len(sessions) == 3
    assert sessions[0].parsed_subject == "003"
    assert sessions[0].parsed_session == "sess05"
    assert sessions[0].date == "20250301"
    assert sessions[0].series_count == 5


def test_discover_sessions_sorted_by_date(mock_dcm_source):
    sessions = discover_sessions(mock_dcm_source)
    dates = [s.date for s in sessions]
    assert dates == sorted(dates)


def test_discover_sessions_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    sessions = discover_sessions(empty)
    assert sessions == []


def test_discover_sessions_nonexistent_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_sessions(tmp_path / "nonexistent")


def test_ingest_session_symlink(mock_dcm_source, mock_sourcedata):
    sessions = discover_sessions(mock_dcm_source)
    mapping = BidsMapping(
        folder_name=sessions[0].folder_name,
        bids_subject="03",
        bids_session="05",
    )

    target = ingest_session(sessions[0], mapping, mock_sourcedata, method="symlink")
    assert target.exists()
    assert target.is_symlink()
    assert target == mock_sourcedata / "sub-03" / "ses-05" / "dicom"


def test_ingest_session_copy(mock_dcm_source, mock_sourcedata):
    sessions = discover_sessions(mock_dcm_source)
    mapping = BidsMapping(
        folder_name=sessions[0].folder_name,
        bids_subject="03",
        bids_session="05",
    )

    target = ingest_session(sessions[0], mapping, mock_sourcedata, method="copy")
    assert target.exists()
    assert not target.is_symlink()
    assert target.is_dir()


def test_ingest_session_idempotent(mock_dcm_source, mock_sourcedata):
    sessions = discover_sessions(mock_dcm_source)
    mapping = BidsMapping(
        folder_name=sessions[0].folder_name,
        bids_subject="03",
        bids_session="05",
    )

    target1 = ingest_session(sessions[0], mapping, mock_sourcedata)
    target2 = ingest_session(sessions[0], mapping, mock_sourcedata)
    assert target1 == target2


def test_list_ingested_sessions(mock_sourcedata):
    # Create some ingested sessions
    for sub, ses in [("03", "05"), ("03", "06"), ("04", "01")]:
        d = mock_sourcedata / f"sub-{sub}" / f"ses-{ses}" / "dicom"
        d.mkdir(parents=True)

    result = list_ingested_sessions(mock_sourcedata)
    assert len(result) == 3
    assert result[0]["subject"] == "03"
    assert result[0]["session"] == "05"
    assert result[0]["has_dicom"] is True


def test_auto_number_sessions(mock_dcm_source):
    sessions = discover_sessions(mock_dcm_source)
    mappings = auto_number_sessions(sessions)

    # Subject 003 has 2 sessions, subject 004 has 1
    assert len(mappings) == 3

    sub003 = [m for m in mappings if m.bids_subject == "003"]
    sub004 = [m for m in mappings if m.bids_subject == "004"]

    assert len(sub003) == 2
    assert len(sub004) == 1

    # Sessions numbered chronologically within each subject
    sub003.sort(key=lambda m: m.bids_session)
    assert sub003[0].bids_session == "01"  # sess05 (earlier date)
    assert sub003[1].bids_session == "02"  # sess06 (later date)
    assert sub004[0].bids_session == "01"
