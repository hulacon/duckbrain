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


# ---- the project's ND choice must reach the non-interactive path ----


def _nd_session(root):
    """A session holding both reconstructions of one mprage."""
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    for number, name, image_type in (
        (1009, "mprage_p2_ND_defaced", ["DERIVED", "SECONDARY", "M", "ND", "NORM"]),
        (1010, "mprage_p2_defaced", ["DERIVED", "SECONDARY", "M", "NORM", "DIS3D", "DIS2D"]),
    ):
        directory = root / f"Series_{number}_{name}"
        directory.mkdir(parents=True)
        for index in range(2):
            ds = Dataset()
            ds.file_meta = FileMetaDataset()
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
            ds.file_meta.MediaStorageSOPInstanceUID = f"1.2.3.{number}.{index}"
            ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
            ds.SOPInstanceUID = f"1.2.3.{number}.{index}"
            ds.Modality = "MR"
            ds.ImageType = image_type
            ds.MRAcquisitionType = "3D"
            ds.ScanningSequence = ["GR", "IR"]
            ds.SequenceName = "*tfl3d1_16ns"
            ds.SeriesDescription = name
            ds.EchoNumbers = 1
            pydicom.dcmwrite(directory / f"{index:04d}.dcm", ds, enforce_file_format=True)
    return root


def test_the_bulk_path_honours_the_project_nd_choice(tmp_path):
    """`generate_session_config` is what bulk and every cockpit convert run.

    A control that lived only on the Conversion page would leave this path on the
    default, so the session a user reviewed and the session bulk converted would
    hold different images — with nothing saying so.
    """
    from duckbrain.core.conversion import generate_session_config
    from duckbrain.core.dicom_inspect import nd_policy_from_config

    dicom_dir = _nd_session(tmp_path / "dicom")
    project = {"conversion": {"nd_duplicates": "both"}}

    config = generate_session_config(
        dicom_dir, "01", "", nd_duplicates=nd_policy_from_config(project)
    )
    entities = sorted(d.get("custom_entities", "") for d in config["descriptions"])
    assert entities == ["acq-dis", "acq-nd"]

    default = generate_session_config(dicom_dir, "01", "")
    assert [d["criteria"]["SeriesNumber"] for d in default["descriptions"]] == [1010]


# ---- the plan-time phase-encoding check reaches this path too ----------------
#
# It skipped `plan_warnings` entirely once already and submitted the collisions
# the Conversion page refused (2026-07-24). Same trap one layer down: a probe
# wired only into the page would leave bulk checking less than the reviewed path.
#
# Every test here pins `shutil.which` and stubs `probe_session`. Left to the
# machine they would shell out to whatever apptainer and dcm2niix are installed,
# which is a property of the box and not a test — see
# `memory/local-tests-are-not-ci-tests`.


def _pepolar_session(root):
    """An AP/PA pair and a bold, as real directories the probe could be handed."""
    from duckbrain.core.dicom_inspect import SeriesInfo

    out = []
    for num, desc in ((5, "se_epi_fieldmap_ap"), (6, "se_epi_fieldmap_pa"), (9, "food_bold")):
        d = root / f"Series_{num:02d}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
        out.append(SeriesInfo(series_number=num, description=desc, path=d, file_count=3))
    return out


def _pin_probe(monkeypatch, tmp_path, directions):
    """A resolvable image, a container runtime on PATH, and a scripted dcm2niix."""
    from duckbrain.core import dcm2niix_probe
    from duckbrain.core.dcm2niix_probe import ProbeResult, SeriesProbe

    sif = tmp_path / "dcm2bids-3.2.0.sif"
    sif.write_bytes(b"")
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name == "apptainer" else None
    )
    monkeypatch.setattr(
        dcm2niix_probe,
        "probe_session",
        lambda dirs, container=None, **kw: ProbeResult(
            probes={
                f"Series_{n}": SeriesProbe(series_number=n, phase_encoding_direction=d)
                for n, d in directions.items()
            }
        ),
    )
    return sif


def test_the_bulk_path_refuses_a_pepolar_pair_that_cannot_estimate_a_field(tmp_path, monkeypatch):
    """Both halves encoded the same way: fMRIPrep mis-corrects rather than skips.

    The page renders this as a blocking error; before the probe reached here,
    bulk submitted it.
    """
    import pytest

    from duckbrain.core.conversion import generate_session_config

    series = _pepolar_session(tmp_path / "dicom")
    sif = _pin_probe(monkeypatch, tmp_path, {5: "j-", 6: "j-"})

    with pytest.raises(ValueError, match="opposing"):
        generate_session_config(tmp_path / "dicom", "01", "", series_list=series, container=sif)


def test_a_gradient_echo_session_still_converts_when_probed(tmp_path, monkeypatch):
    """The pe-collinear fix pinned where it would have hurt most.

    A GRE magnitude and its phasediff share a direction by construction. Read as
    a pepolar pair that estimates nothing, they raise here — refusing to convert
    32 of the LCNI corpus's fieldmap sessions, with no UI to explain why.
    """
    from duckbrain.core.conversion import generate_session_config
    from test_series_classification import _gre_session

    series = _gre_session()
    sif = _pin_probe(monkeypatch, tmp_path, {5: "i", 6: "i"})

    config = generate_session_config(
        tmp_path / "dicom", "CC052", "1", series_list=series, container=sif
    )
    assert config["descriptions"]


def test_the_bulk_path_does_not_probe_when_no_container_is_named(tmp_path, monkeypatch):
    """`container=None` means don't probe, not "probe with whatever is on PATH".

    That contract is what keeps the rest of this suite — and the page's config
    drift comparison, which compares configs and not warnings — off the
    developer's dcm2niix.
    """
    from duckbrain.core import dcm2niix_probe
    from duckbrain.core.conversion import generate_session_config

    def _boom(*a, **kw):
        raise AssertionError("probe_session must not be called without a container")

    monkeypatch.setattr(dcm2niix_probe, "probe_session", _boom)
    series = _pepolar_session(tmp_path / "dicom")

    assert generate_session_config(tmp_path / "dicom", "01", "", series_list=series)


def test_a_probe_that_cannot_run_warns_rather_than_refusing(tmp_path, monkeypatch):
    """Submission and conversion happen on different machines.

    The login node running this may have no container runtime while the compute
    node running dcm2bids does, so refusing would block a study that converts
    perfectly well. Nothing here claims the check ran.
    """
    import pytest

    from duckbrain.core.conversion import generate_session_config

    monkeypatch.setattr("shutil.which", lambda _: None)
    series = _pepolar_session(tmp_path / "dicom")

    with pytest.warns(UserWarning, match="Phase-encoding checks skipped"):
        config = generate_session_config(
            tmp_path / "dicom", "01", "", series_list=series, container=tmp_path / "missing.sif"
        )
    assert config["descriptions"]


def test_a_probe_that_ran_and_failed_warns_the_same_way(tmp_path, monkeypatch):
    """The other way the checks don't happen, and it used to be silent here.

    A dcm2niix that exits non-zero returned the same empty map as a session with
    nothing to probe, so a bulk convert of 95 sessions lost the phase-encoding
    checks without a word. The refuse-vs-warn decision above is
    unchanged: this still converts, it just says what it didn't check.
    """
    import pytest

    from duckbrain.core import dcm2niix_probe
    from duckbrain.core.conversion import generate_session_config
    from duckbrain.core.dcm2niix_probe import ProbeResult

    series = _pepolar_session(tmp_path / "dicom")
    sif = _pin_probe(monkeypatch, tmp_path, {})
    monkeypatch.setattr(
        dcm2niix_probe,
        "probe_session",
        lambda dirs, container=None, **kw: ProbeResult(failure="dcm2niix exited 1"),
    )

    with pytest.warns(UserWarning, match="dcm2niix exited 1"):
        config = generate_session_config(
            tmp_path / "dicom", "01", "", series_list=series, container=sif
        )
    assert config["descriptions"]
