"""Tests for the BIDS-schema filename check (``docs/conversion-legibility.md`` phase 10).

Only shapes that can never *become* legal are asserted as nonconforming — the
schema evolves with the installed ``bidsschematools`` (new suffixes and
entities arrive), so a test pinning something merely-not-yet-legal would go red
on a routine dependency bump with nothing in this repo having changed.
"""

from duckbrain.core.bids_schema import bids_version, conforms


def test_paths_duckbrain_composes_conform():
    for path in [
        "sub-001/ses-01/anat/sub-001_ses-01_T1w.nii.gz",
        "sub-001/anat/sub-001_T1w.nii.gz",  # sessionless projects
        "sub-001/ses-01/func/sub-001_ses-01_task-divPerFace_run-1_bold.nii.gz",
        "sub-001/ses-01/func/sub-001_ses-01_task-divPerFace_run-1_sbref.nii.gz",
        "sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-1_epi.nii.gz",
        "sub-001/ses-01/fmap/sub-001_ses-01_acq-gre_magnitude1.nii.gz",
        "sub-001/ses-01/fmap/sub-001_ses-01_acq-gre_phasediff.nii.gz",
        "sub-001/ses-01/dwi/sub-001_ses-01_acq-3shell_dir-AP_run-1_dwi.nii.gz",
        "sub-001/ses-01/dwi/sub-001_ses-01_acq-3shell_dir-AP_run-1_sbref.nii.gz",
    ]:
        assert conforms(path), path


def test_malformed_names_do_not_conform():
    for path in [
        # A suffix is case-sensitive in every BIDS release there has ever been.
        "sub-001/ses-01/anat/sub-001_ses-01_T1W.nii.gz",
        # task- is REQUIRED for bold and always has been.
        "sub-001/ses-01/func/sub-001_ses-01_run-1_bold.nii.gz",
        # Entity values are alphanumeric in every release.
        "sub-001/ses-01/func/sub-001_ses-01_task-div!_run-1_bold.nii.gz",
        # The datatype directory is part of the pattern.
        "sub-001/ses-01/anat/sub-001_ses-01_task-div_run-1_bold.nii.gz",
        # A path with no subject root cannot be a BIDS data file.
        "func/task-div_run-1_bold.nii.gz",
    ]:
        assert not conforms(path), path


def test_bids_version_reads_off_the_schema():
    # "1.10.1"-shaped, whatever the installed schema is — the value lands in a
    # user-facing message, so it must be a version, not an empty string.
    assert bids_version()[0].isdigit()
