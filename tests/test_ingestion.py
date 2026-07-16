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


def test_discover_sessions_no_session_label(tmp_path):
    """DIVATTEN-style folders (PROJECT_SUBID_DATE_TIME, no session label) parse
    to a clean BIDS subject id with the project prefix dropped."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    for name in ["DIVATTEN_001_20220408_100353", "DIVATTEN_017_20221104_142112"]:
        (dcm_dir / name).mkdir()
        (dcm_dir / name / "Series_01_mprage").mkdir()
        (dcm_dir / name / "Series_01_mprage" / "f.dcm").touch()

    sessions = discover_sessions(dcm_dir)
    subs = {s.folder_name: (s.parsed_subject, s.parsed_session) for s in sessions}
    assert subs["DIVATTEN_001_20220408_100353"] == ("001", "")
    assert subs["DIVATTEN_017_20221104_142112"] == ("017", "")
    # No underscores/invalid chars leak into the BIDS subject label
    assert all("_" not in s.parsed_subject for s in sessions)


def test_auto_number_no_session_label(tmp_path):
    """DIVATTEN: one session per subject -> 'auto' omits the ses- entity."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    for name in ["DIVATTEN_001_20220408_100353", "DIVATTEN_002_20220425_100250"]:
        (dcm_dir / name).mkdir()
    sessions = discover_sessions(dcm_dir)
    mappings = auto_number_sessions(sessions)  # default "auto"
    assert {m.bids_subject for m in mappings} == {"001", "002"}
    assert all(m.bids_session == "" for m in mappings)  # single-session -> no ses-
    # Forcing sessions on still numbers them
    forced = auto_number_sessions(sessions, use_sessions=True)
    assert all(m.bids_session == "01" for m in forced)


def test_discover_sessions_gs_session_style(tmp_path):
    """mmmdata/LCNI 'G##_S##' folders: S## is recognized as the session and the
    paired G## token as the subject (the parser previously needed a 'ses' prefix)."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    for name in ["MMM_G01_S01_20250301_120000", "MMM_G01_S02_20250315_140000"]:
        (dcm_dir / name).mkdir()
        (dcm_dir / name / "Series_01_mprage").mkdir()

    sessions = discover_sessions(dcm_dir)
    parsed = {s.folder_name: (s.parsed_subject, s.parsed_session) for s in sessions}
    assert parsed["MMM_G01_S01_20250301_120000"] == ("G01", "S01")
    assert parsed["MMM_G01_S02_20250315_140000"] == ("G01", "S02")


def test_bare_s_token_not_treated_as_session(tmp_path):
    """A bare 'S01'/'s01' subject id (no paired G## token) must NOT be read as a
    session — it stays the subject, matching the 'ses'-prefix safeguard."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    (dcm_dir / "STUDY_S01_20250301_120000").mkdir()
    sessions = discover_sessions(dcm_dir)
    assert len(sessions) == 1
    assert sessions[0].parsed_subject == "S01"
    assert sessions[0].parsed_session == ""


def test_discover_sessions_excludes_phantom_and_test_folders(tmp_path):
    """Phantom/QA/test/demo and whitespace-containing folders are skipped by
    default; real subject folders are kept."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    for name in [
        "DIVATTEN_001_20220408_100353",  # real subject -> kept
        "DIVATTEN_phantom_20220408_090000",  # phantom -> skipped
        "QA_daily_20220408_080000",  # QA -> skipped
        "test_scan_20220408_070000",  # test -> skipped
        "DEMO_20220408_060000",  # demo -> skipped
        "some scratch folder",  # whitespace -> skipped
    ]:
        (dcm_dir / name).mkdir()

    sessions = discover_sessions(dcm_dir)
    assert [s.folder_name for s in sessions] == ["DIVATTEN_001_20220408_100353"]

    # Opt-in returns the folders that still parse (whitespace/no-date ones drop out)
    all_folders = {s.folder_name for s in discover_sessions(dcm_dir, include_excluded=True)}
    assert "DIVATTEN_phantom_20220408_090000" in all_folders
    assert "DIVATTEN_001_20220408_100353" in all_folders


def test_marker_prefix_with_numeric_subject_is_kept(tmp_path):
    """A study that legitimately uses a marker word as its project prefix (e.g.
    'TEST_01') resolves to a numeric subject and is kept; only marker folders
    with a non-numeric identity ('TEST_phantom') are dropped."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    (dcm_dir / "TEST_01_20250301_120000").mkdir()
    (dcm_dir / "TEST_phantom_20250301_130000").mkdir()
    sessions = discover_sessions(dcm_dir)
    assert [s.parsed_subject for s in sessions] == ["01"]


def test_substring_not_mistaken_for_excluded_token(tmp_path):
    """A project whose name merely contains an excluded word as a substring
    (e.g. 'Detest') is not filtered — only whole tokens match."""
    dcm_dir = tmp_path / "dcm"
    dcm_dir.mkdir()
    (dcm_dir / "Detest_001_20250301_120000").mkdir()
    sessions = discover_sessions(dcm_dir)
    assert len(sessions) == 1
    assert sessions[0].parsed_subject == "001"


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


def test_ingest_and_list_no_session(mock_dcm_source, mock_sourcedata):
    """Empty bids_session -> dicom/ directly under sub-XX (no ses- level), and
    list_ingested_sessions reports session=''."""
    sessions = discover_sessions(mock_dcm_source)
    mapping = BidsMapping(folder_name=sessions[0].folder_name, bids_subject="01", bids_session="")
    target = ingest_session(sessions[0], mapping, mock_sourcedata, method="symlink")
    assert target == mock_sourcedata / "sub-01" / "dicom"
    assert target.exists()

    listed = list_ingested_sessions(mock_sourcedata)
    assert len(listed) == 1
    assert listed[0]["subject"] == "01"
    assert listed[0]["session"] == ""
    assert listed[0]["has_dicom"] is True


def test_build_dcm_source_path():
    from duckbrain.core.ingestion import build_dcm_source_path

    # Preferred: a single explicit directory
    assert build_dcm_source_path({"dcm_source": {"dir": "/projects/lcni/dcm/g/PI/study"}}) == Path(
        "/projects/lcni/dcm/g/PI/study"
    )
    # Legacy base/group/project still composes
    assert build_dcm_source_path(
        {"dcm_source": {"base_dir": "/b", "group": "g", "project": "PI/study"}}
    ) == Path("/b/g/PI/study")
    # dir wins over legacy fields when both present
    assert build_dcm_source_path(
        {"dcm_source": {"dir": "/x", "group": "g", "project": "p"}}
    ) == Path("/x")
    # Neither -> clear error
    with pytest.raises(ValueError):
        build_dcm_source_path({"dcm_source": {}})


def test_build_dcm2bids_command_omits_session():
    from duckbrain.core.conversion import build_dcm2bids_command

    with_ses = build_dcm2bids_command("01", "02", "/d", "/b", "/c.json", "/img.sif")
    assert "-s" in with_ses and "02" in with_ses
    no_ses = build_dcm2bids_command("01", "", "/d", "/b", "/c.json", "/img.sif")
    assert "-s" not in no_ses


def test_build_dcm2bids_command_resolves_symlink_dicom(tmp_path):
    """The -d arg and its bind use the resolved DICOM target, not the symlink,
    so containerized dcm2bids reads the real directory regardless of Singularity
    symlink-following behavior."""
    from duckbrain.core.conversion import build_dcm2bids_command

    real = tmp_path / "export" / "SESSION"
    real.mkdir(parents=True)
    link = tmp_path / "sourcedata" / "sub-01" / "dicom"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)

    cmd = build_dcm2bids_command("01", "", link, tmp_path / "bids", tmp_path / "c.json", "/img.sif")
    d_arg = cmd[cmd.index("-d") + 1]
    assert d_arg == str(real.resolve())
    # the bind source (before the ':') is the resolved real dir, not the symlink
    binds = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-B"]
    assert any(b.split(":")[0] == str(real.resolve()) for b in binds)
    assert not any(str(link) in b for b in binds)


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
