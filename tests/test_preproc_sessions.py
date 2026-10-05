"""Optional-session handling across fMRIPrep / NORDIC preprocessing."""

import json
from pathlib import Path

import pytest

from duckbrain.core.fmriprep import (
    build_fmriprep_command,
    session_tracking_args,
    tracks_sessions,
    write_session_filter,
)
from duckbrain.core.nordic import get_bold_runs


def test_write_session_filter_restricts_functional_only(tmp_path):
    # Anatomicals (t1w/t2w) must stay unfiltered so a shared, single-session
    # anatomical is still found when processing a different func session.
    p = write_session_filter(tmp_path / "f.json", "02")
    data = json.loads(p.read_text())
    assert set(data) == {"bold", "sbref", "fmap"}
    assert "t1w" not in data and "t2w" not in data
    assert all(v == {"session": "02"} for v in data.values())


def _base_cmd_kwargs(tmp_path):
    return dict(
        bids_dir=tmp_path / "bids",
        output_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        subject="001",
        container_path=tmp_path / "fmriprep.sif",
        fs_license=tmp_path / "license.txt",
    )


def test_fmriprep_command_single_session_has_no_filter(tmp_path):
    cmd = build_fmriprep_command(**_base_cmd_kwargs(tmp_path))  # session=None
    assert "--bids-filter-file" not in cmd


def test_fmriprep_command_multi_session_adds_filter(tmp_path):
    cmd = build_fmriprep_command(session="01", **_base_cmd_kwargs(tmp_path))
    assert "--bids-filter-file" in cmd
    filter_path = Path(cmd[cmd.index("--bids-filter-file") + 1])
    assert json.loads(filter_path.read_text())["bold"] == {"session": "01"}


def test_fmriprep_command_turns_session_tracking_off(tmp_path):
    cmd = build_fmriprep_command(session="01", **_base_cmd_kwargs(tmp_path))
    assert cmd.count("--no-track-sessions") == 1
    old = build_fmriprep_command(
        session="01", fmriprep_version="24.1.1", **_base_cmd_kwargs(tmp_path)
    )
    assert "--no-track-sessions" not in old


@pytest.mark.parametrize(
    ("version", "tracks"),
    [
        ("25.2.5", True),
        ("25.2.0", True),
        ("26.0.0", True),
        ("25.1.4", False),
        ("24.1.1", False),
        ("latest", True),
        ("", True),
    ],
)
def test_tracks_sessions_from_the_pin(version, tracks):
    assert tracks_sessions(version) is tracks


def test_session_tracking_flag_is_not_repeated():
    assert session_tracking_args("25.2.5", "--no-track-sessions") == []
    assert session_tracking_args("25.2.5", "--use-syn-sdc") == ["--no-track-sessions"]


def test_get_bold_runs_no_session_layout(tmp_path):
    func = tmp_path / "sub-001" / "func"
    func.mkdir(parents=True)
    for r in (1, 2):
        (func / f"sub-001_task-x_run-{r}_bold.nii.gz").touch()
    assert len(get_bold_runs(tmp_path, "001", "")) == 2


def test_get_bold_runs_session_layout(tmp_path):
    func = tmp_path / "sub-001" / "ses-01" / "func"
    func.mkdir(parents=True)
    (func / "sub-001_ses-01_task-x_bold.nii.gz").touch()
    assert len(get_bold_runs(tmp_path, "001", "01")) == 1
    # asking for the no-session layout must NOT pick up the ses- files
    assert get_bold_runs(tmp_path, "001", "") == []
