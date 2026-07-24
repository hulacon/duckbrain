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


# ---- compare_dcm2bids_configs ----


def _cfg(*descriptions):
    return {"descriptions": list(descriptions)}


def test_identical_configs_have_no_drift():
    from duckbrain.core.conversion import compare_dcm2bids_configs

    cfg = _cfg({"id": "fmap-epi-ap", "sidecar_changes": {"B0FieldIdentifier": "B0map_25mm"}})
    drift = compare_dcm2bids_configs(cfg, _cfg(*cfg["descriptions"]))
    assert not drift
    assert drift.describe() == []


def test_drift_names_the_nested_field_that_moved():
    """A diff that says "sidecar_changes differs" makes the reader open both
    files; naming the key is the whole value of reporting it."""
    from duckbrain.core.conversion import compare_dcm2bids_configs

    drift = compare_dcm2bids_configs(
        _cfg({"id": "fmap-epi-ap", "sidecar_changes": {"B0FieldIdentifier": "B0map_2.5mm"}}),
        _cfg({"id": "fmap-epi-ap", "sidecar_changes": {"B0FieldIdentifier": "B0map_25mm"}}),
    )
    assert drift
    assert drift.changed == {"fmap-epi-ap": ["sidecar_changes.B0FieldIdentifier"]}
    assert "sidecar_changes.B0FieldIdentifier" in drift.describe()[0]


def test_drift_reports_added_and_removed_descriptions():
    from duckbrain.core.conversion import compare_dcm2bids_configs

    drift = compare_dcm2bids_configs(
        _cfg({"id": "func-bold-rest"}, {"id": "gone"}),
        _cfg({"id": "func-bold-rest"}, {"id": "new"}),
    )
    assert drift.removed == ["gone"]
    assert drift.added == ["new"]
    assert not drift.changed


def test_a_key_added_on_only_one_side_counts_as_drift():
    """Absent and present-but-empty are different plans, and the one that
    matters here (a bold that lost its B0FieldSource) is exactly this shape."""
    from duckbrain.core.conversion import compare_dcm2bids_configs

    drift = compare_dcm2bids_configs(
        _cfg({"id": "func-bold-rest", "sidecar_changes": {"B0FieldSource": "B0map_25mm"}}),
        _cfg({"id": "func-bold-rest"}),
    )
    assert drift.changed == {"func-bold-rest": ["sidecar_changes.B0FieldSource"]}


def test_describe_states_its_own_cap():
    """A truncated list that just stops reads as a complete one."""
    from duckbrain.core.conversion import compare_dcm2bids_configs

    saved = _cfg(
        *({"id": f"bold-{i}", "sidecar_changes": {"B0FieldSource": "old"}} for i in range(12))
    )
    fresh = _cfg(
        *({"id": f"bold-{i}", "sidecar_changes": {"B0FieldSource": "new"}} for i in range(12))
    )
    drift = compare_dcm2bids_configs(saved, fresh)

    assert len(drift.describe()) == 12
    capped = drift.describe(limit=8)
    assert len(capped) == 9
    assert "and 4 more" in capped[-1]
