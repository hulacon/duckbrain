"""Helpers backing bulk BIDS conversion."""

import os

from duckbrain.core.conversion import (
    resolve_dicom_dir,
    session_bids_exists,
)


def test_session_bids_exists_detects_nifti(tmp_path):
    bids = tmp_path
    # single-session layout: sub-01/func/*.nii.gz
    (bids / "sub-01" / "func").mkdir(parents=True)
    (bids / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz").touch()
    assert session_bids_exists(bids, "01", "") is True
    # sub-02 dir exists but has no nifti → not converted
    (bids / "sub-02" / "anat").mkdir(parents=True)
    assert session_bids_exists(bids, "02", "") is False
    # sub-03 absent entirely
    assert session_bids_exists(bids, "03", "") is False


def test_session_bids_exists_multi_session(tmp_path):
    bids = tmp_path
    (bids / "sub-01" / "ses-02" / "func").mkdir(parents=True)
    (bids / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_bold.nii.gz").touch()
    assert session_bids_exists(bids, "01", "02") is True
    # a different session of the same subject is independent
    assert session_bids_exists(bids, "01", "01") is False


def test_resolve_dicom_dir_follows_symlink(tmp_path):
    real = tmp_path / "export" / "SUBJ_20220101"
    real.mkdir(parents=True)
    src = tmp_path / "sourcedata"
    (src / "sub-01").mkdir(parents=True)
    link = src / "sub-01" / "dicom"
    os.symlink(real, link)
    assert resolve_dicom_dir(src, "01", "") == real.resolve()


def test_resolve_dicom_dir_plain_dir(tmp_path):
    src = tmp_path / "sourcedata"
    d = src / "sub-01" / "dicom"
    d.mkdir(parents=True)
    assert resolve_dicom_dir(src, "01", "") == d
