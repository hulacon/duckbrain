"""Provenance consistency checker (Phase B).

On-disk provenance is authoritative; the submission log is an overlay that only
adds cross-subject mixing. These lock in each check and, importantly, that
externally-produced derivatives (with on-disk provenance but no log rows) are
never flagged just for lacking a log row.
"""

import json
from pathlib import Path

from duckbrain.core.bids_metadata import write_derivative_description
from duckbrain.core.consistency import (
    ConsistencyIssue,
    _check_tool_crashes,
    check_consistency,
    read_derivative_provenance,
)
from duckbrain.core.pipeline import record_submission


def _config(root, use_nordic=False, containers=None, containers_dir=None):
    cfg = {
        "paths": {
            "bids_dir": str(root),
            "sourcedata_dir": str(root / "sourcedata"),
            "derivatives_dir": str(root / "derivatives"),
            "log_dir": str(root / "code" / "logs"),
            "work_dir": "/tmp",
        }
    }
    if containers_dir:
        cfg["paths"]["containers_dir"] = containers_dir
    if use_nordic:
        cfg["nordic"] = {"use_nordic": True}
    if containers:
        cfg["containers"] = containers
    return cfg


def _containers(root, *images):
    """A containers dir holding *images*, so get_container_path resolves them."""
    d = root / "containers"
    d.mkdir(parents=True, exist_ok=True)
    for image in images:
        (d / image).write_text("img")
    return str(d)


def _fmriprep_unit(root, sub):
    """Make sub-*sub* read as having real fMRIPrep output on disk.

    Anat-only (no func in the BIDS unit), which is what the fMRIPrep tracker
    needs to grade the unit complete — the same shape the presence test uses.
    """
    fp = root / "derivatives" / "fmriprep"
    (fp / f"sub-{sub}" / "anat").mkdir(parents=True, exist_ok=True)
    (fp / f"sub-{sub}.html").write_text("report")
    (fp / f"sub-{sub}" / "anat" / f"sub-{sub}_desc-preproc_T1w.nii.gz").write_text("x")
    (root / f"sub-{sub}" / "anat").mkdir(parents=True, exist_ok=True)


def _fmriprep_desc(root, *, raw_link=None, version="24.1.1"):
    """Write a fMRIPrep-style dataset_description.json (as fMRIPrep itself would)."""
    deriv = root / "derivatives" / "fmriprep"
    deriv.mkdir(parents=True, exist_ok=True)
    desc = {
        "Name": "fMRIPrep - fMRI PREProcessing workflow",
        "BIDSVersion": "1.9.0",
        "DatasetType": "derivative",
        "GeneratedBy": [{"Name": "fMRIPrep", "Version": version}],
    }
    if raw_link is not None:
        desc["DatasetLinks"] = {"raw": raw_link}
    (deriv / "dataset_description.json").write_text(json.dumps(desc))
    return deriv


def _codes(issues):
    return {i.check for i in issues}


#: The crash file fMRIPrep actually wrote, quoted from the run this check exists
#: for (``divatten_beta_v2/code/logs/fmriprep_45644650.out``, job 45644650). A
#: real filename cannot go quietly stale against a nipype naming change — it
#: fails.
_REAL_CRASH = (
    "crash-20260724-183435-bhutch-fsdir_run_20260724_183340_a02a9236_291e_4c02"
    "_97ed_1c0f99b79f69-34611e80-f519-41e5-b8b0-d6cca3ff6564.txt"
)
#: The submission that produced it, and the re-run three days later that
#: superseded it — both still in that project's ``submissions.tsv``.
_CRASHED_RUN = "2026-07-24T18:33:05"
_RERUN = "2026-07-27T13:24:58"


def _crash(root, stage="fmriprep", name=_REAL_CRASH, where="logs"):
    """Put a nipype crash dump inside *stage*'s derivative, as the tool would."""
    d = root / "derivatives" / stage / where if where else root / "derivatives" / stage
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("Traceback (most recent call last): ...")
    return d / name


def _submitted(root, stage="fmriprep", when=_CRASHED_RUN):
    """One submissions.tsv row for *stage*, stamped *when*.

    Written directly rather than through ``record_submission``, which stamps the
    current time — the timestamp is the thing under test here.
    """
    log = root / "code" / "logs"
    log.mkdir(parents=True, exist_ok=True)
    path = log / "submissions.tsv"
    header = "" if path.exists() else "timestamp\tsubject\tsession\tstage\tjob_id\n"
    with path.open("a") as fh:
        fh.write(header + f"{when}\t010\t\t{stage}\t45644650\n")
    return path


# ---- reader -----------------------------------------------------------------


def test_read_derivative_provenance_parses_generatedby_and_link(tmp_path):
    _fmriprep_desc(tmp_path, raw_link="/proj/derivatives/nordic/bids_format")
    prov = read_derivative_provenance(_config(tmp_path), "fmriprep")
    assert prov.exists
    assert prov.tool_version("fMRIPrep") == "24.1.1"
    assert prov.tool_version("fmriprep") == "24.1.1"  # case-insensitive
    assert prov.raw_link.endswith("nordic/bids_format")


def test_read_derivative_provenance_absent(tmp_path):
    prov = read_derivative_provenance(_config(tmp_path), "fmriprep")
    assert not prov.exists
    assert prov.generated_by == []


# ---- config vs provenance ---------------------------------------------------


def test_use_nordic_but_fmriprep_from_raw_flags(tmp_path):
    _fmriprep_desc(tmp_path, raw_link=str(tmp_path))  # raw = project root, not nordic
    issues = check_consistency(_config(tmp_path, use_nordic=True))
    assert "config-vs-provenance" in _codes(issues)


def test_not_use_nordic_but_fmriprep_from_nordic_flags(tmp_path):
    _fmriprep_desc(tmp_path, raw_link=str(tmp_path / "derivatives" / "nordic" / "bids_format"))
    issues = check_consistency(_config(tmp_path, use_nordic=False))
    assert "config-vs-provenance" in _codes(issues)


def test_use_nordic_and_fmriprep_from_nordic_is_clean(tmp_path):
    _fmriprep_desc(tmp_path, raw_link=str(tmp_path / "derivatives" / "nordic" / "bids_format"))
    issues = check_consistency(_config(tmp_path, use_nordic=True))
    assert "config-vs-provenance" not in _codes(issues)


def test_external_fmriprep_without_link_not_flagged(tmp_path):
    # An externally-run fMRIPrep with provenance but no DatasetLinks and no log
    # rows must not trip config-vs-provenance or mixed-provenance.
    _fmriprep_desc(tmp_path, raw_link=None)
    issues = check_consistency(_config(tmp_path, use_nordic=False))
    assert issues == []


# ---- container drift --------------------------------------------------------


def test_container_drift_flagged_when_pin_bumped_without_rerun(tmp_path):
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "25.0.0"},
        containers_dir=_containers(tmp_path, "fmriprep-25.0.0.simg"),
    )
    record_submission(
        cfg, "fmriprep", "01", "", "J1", tool="fmriprep", runtime="fmriprep-24.1.1.simg"
    )
    assert "container-drift" in _codes(check_consistency(cfg))


def test_matching_container_is_clean(tmp_path):
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    record_submission(
        cfg, "fmriprep", "01", "", "J1", tool="fmriprep", runtime="fmriprep-24.1.1.simg"
    )
    assert "container-drift" not in _codes(check_consistency(cfg))


def test_container_tag_differing_from_self_reported_version_is_clean(tmp_path):
    """Regression (real data, 2026-07-16): a container tag and the tool's own
    version legitimately differ — ``mriqc-24.0.2.simg`` self-reports
    ``24.1.0.dev0+gd5b13cb5.d20240826``. That must not read as drift.
    """
    _fmriprep_desc(tmp_path, version="24.1.0.dev0+gd5b13cb5.d20240826")
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.0.2"},
        containers_dir=_containers(tmp_path, "fmriprep-24.0.2.simg"),
    )
    record_submission(
        cfg, "fmriprep", "01", "", "J1", tool="fmriprep", runtime="fmriprep-24.0.2.simg"
    )
    assert "container-drift" not in _codes(check_consistency(cfg))


def test_on_disk_container_tag_beats_log_overlay(tmp_path):
    """On-disk provenance is authoritative: a duckbrain-stamped Container.Tag
    decides, even when the log's container disagrees."""
    deriv = tmp_path / "derivatives" / "fmriprep"
    write_derivative_description(
        deriv,
        "fmriprep",
        tool="fMRIPrep",
        tool_version="24.1.1",
        container="fmriprep-24.1.1.simg",
    )
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    # Log claims a different container; on-disk agrees with config, so: clean.
    record_submission(
        cfg, "fmriprep", "01", "", "J1", tool="fmriprep", runtime="fmriprep-99.9.9.simg"
    )
    assert "container-drift" not in _codes(check_consistency(cfg))


def _build_tags(monkeypatch, mapping):
    """Stub the images' recorded build provenance: {filename: docker tag}."""
    import duckbrain.core.consistency as CO

    monkeypatch.setattr(CO, "container_build_tag", lambda p: mapping.get(Path(p).name, ""))


def test_same_filename_rebuilt_from_a_different_image_is_drift(monkeypatch, tmp_path):
    """Build provenance catches what the filename cannot: the image at
    `fmriprep-24.1.1.simg` was rebuilt in place from a different source."""
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    _build_tags(monkeypatch, {"fmriprep-24.1.1.simg": "nipreps/fmriprep:24.1.1"})
    record_submission(
        cfg,
        "fmriprep",
        "01",
        "",
        "J1",
        tool="fmriprep",
        runtime="fmriprep-24.1.1.simg",
        code_source="nipreps/fmriprep:23.0.0",
    )  # what actually ran
    assert "container-drift" in _codes(check_consistency(cfg))


def test_renamed_container_with_same_build_source_is_clean(monkeypatch, tmp_path):
    """The mirror case: filenames differ, but it is the same image — the
    filename would cry wolf, build provenance knows better."""
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    _build_tags(monkeypatch, {"fmriprep-24.1.1.simg": "nipreps/fmriprep:24.1.1"})
    record_submission(
        cfg,
        "fmriprep",
        "01",
        "",
        "J1",
        tool="fmriprep",
        runtime="fmriprep-24.1.1-copy.simg",
        code_source="nipreps/fmriprep:24.1.1",
    )
    assert "container-drift" not in _codes(check_consistency(cfg))


def test_falls_back_to_filename_when_build_tag_unknown(monkeypatch, tmp_path):
    """Pre-container_source log rows still get filename-level drift detection."""
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "25.0.0"},
        containers_dir=_containers(tmp_path, "fmriprep-25.0.0.simg"),
    )
    _build_tags(monkeypatch, {})  # no image records provenance
    record_submission(
        cfg, "fmriprep", "01", "", "J1", tool="fmriprep", runtime="fmriprep-24.1.1.simg"
    )  # legacy row: no source
    assert "container-drift" in _codes(check_consistency(cfg))


def test_on_disk_container_uri_is_read_as_build_provenance(monkeypatch, tmp_path):
    """A duckbrain-stamped Container.URI is authoritative build provenance."""
    deriv = tmp_path / "derivatives" / "fmriprep"
    write_derivative_description(
        deriv,
        "fmriprep",
        tool="fMRIPrep",
        tool_version="24.1.1",
        container="fmriprep-24.1.1.simg",
        container_uri="docker://nipreps/fmriprep:23.0.0",
    )
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    _build_tags(monkeypatch, {"fmriprep-24.1.1.simg": "nipreps/fmriprep:24.1.1"})
    # Filenames match, but the stamped build source does not: drift.
    assert "container-drift" in _codes(check_consistency(cfg))


def test_external_derivative_without_recorded_container_never_flagged(tmp_path):
    """No Container.Tag and no log rows — an externally-produced derivative.
    Unknowable provenance must degrade to silence, not a warning."""
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "25.0.0"},
        containers_dir=_containers(tmp_path, "fmriprep-25.0.0.simg"),
    )
    assert "container-drift" not in _codes(check_consistency(cfg))


# ---- toolbox drift (NORDIC) -------------------------------------------------
#
# NORDIC's analogue of container-drift, against a git checkout rather than an
# image — and the drift most likely to happen for real: the toolbox lives on a
# group-writable shared path, so any lab member's `git pull` silently changes
# denoising for every project pointing at it.


def _nordic_deriv(root, *, version=""):
    """A NORDIC derivative as duckbrain stamps it."""
    deriv = root / "derivatives" / "nordic"
    write_derivative_description(deriv, "nordic", tool="nordic", tool_version=version)
    return deriv


def _toolbox(monkeypatch, current):
    import duckbrain.core.consistency as CO

    monkeypatch.setattr(CO, "describe", lambda repo: current)


def _nordic_sidecar(root, sub, run, **prov):
    """A NORDIC output plus the per-file sidecar duckbrain stamps beside it."""
    d = root / "derivatives" / "nordic" / f"sub-{sub}" / "func"
    d.mkdir(parents=True, exist_ok=True)
    name = f"sub-{sub}_task-x_run-{run}_bold"
    (d / f"{name}.nii.gz").write_text("nii")
    (d / f"{name}.json").write_text(json.dumps({"Duckbrain": prov}))
    return d / f"{name}.json"


def _nordic_unit(root, sub):
    """Make sub-*sub* read as having real NORDIC output on disk."""
    nd = root / "derivatives" / "nordic" / f"sub-{sub}" / "func"
    nd.mkdir(parents=True, exist_ok=True)
    (nd / f"sub-{sub}_task-x_bold.nii.gz").write_text("x")
    bids = root / f"sub-{sub}" / "func"
    bids.mkdir(parents=True, exist_ok=True)
    (bids / f"sub-{sub}_task-x_bold.nii.gz").write_text("x")


def test_toolbox_moved_since_the_derivative_was_produced_is_drift(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(tmp_path / "NORDIC_Raw")
    _nordic_deriv(tmp_path, version="v1.0.2-24-g0861968")
    _toolbox(monkeypatch, "v1.0.2-31-gabcdef1")  # someone ran `git pull`
    issues = check_consistency(cfg)
    assert "toolbox-drift" in _codes(issues)
    assert any("0861968" in i.message for i in issues if i.check == "toolbox-drift")


def test_unchanged_toolbox_is_clean(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(tmp_path / "NORDIC_Raw")
    _nordic_deriv(tmp_path, version="v1.0.2-24-g0861968")
    _toolbox(monkeypatch, "v1.0.2-24-g0861968")
    assert "toolbox-drift" not in _codes(check_consistency(cfg))


def test_toolbox_edited_locally_since_the_run_is_drift(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(tmp_path / "NORDIC_Raw")
    _nordic_deriv(tmp_path, version="v1.0.2-24-g0861968")
    _toolbox(monkeypatch, "v1.0.2-24-g0861968-dirty")  # hand-edited NIFTI_NORDIC.m
    assert "toolbox-drift" in _codes(check_consistency(cfg))


def test_toolbox_drift_reads_sidecars_when_the_dataset_stamp_is_silent(monkeypatch, tmp_path):
    """duckbrain writes NORDIC's files, so their own sidecars are the source —
    not the submission log."""
    cfg = _nordic_cfg(tmp_path)
    _nordic_sidecar(tmp_path, "01", 1, ToolVersion="v1.0.2-24-g0861968")
    _toolbox(monkeypatch, "v1.0.2-31-gabcdef1")
    assert "toolbox-drift" in _codes(check_consistency(cfg))


def test_sidecars_outrank_the_dataset_level_stamp(monkeypatch, tmp_path):
    """dataset_description is overwritten by whichever run finished last, so it
    cannot represent a part-re-run derivative. The per-file sidecar wins."""
    cfg = _nordic_cfg(tmp_path)
    _nordic_deriv(tmp_path, version="v9.9.9-gstale")  # dataset-level, stale
    _nordic_sidecar(tmp_path, "01", 1, ToolVersion="v1.0.2-24-g0861968")
    _toolbox(monkeypatch, "v1.0.2-24-g0861968")  # matches the sidecar
    assert "toolbox-drift" not in _codes(check_consistency(cfg))


def test_unknowable_toolbox_version_is_never_drift(monkeypatch, tmp_path):
    """No recorded version (an externally-produced NORDIC tree, or a toolbox held
    as a plain unpacked copy) must not read as drift."""
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(tmp_path / "NORDIC_Raw")
    _nordic_deriv(tmp_path, version="")  # nothing recorded
    _toolbox(monkeypatch, "v1.0.2-31-gabcdef1")
    assert "toolbox-drift" not in _codes(check_consistency(cfg))

    _nordic_deriv(tmp_path, version="v1.0.2-24-g0861968")
    _toolbox(monkeypatch, "")  # toolbox not a checkout / not configured
    assert "toolbox-drift" not in _codes(check_consistency(cfg))


def test_no_nordic_derivative_means_no_toolbox_check(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(tmp_path / "NORDIC_Raw")
    _toolbox(monkeypatch, "v1.0.2-31-gabcdef1")
    assert "toolbox-drift" not in _codes(check_consistency(cfg))


# ---- MATLAB drift (NORDIC's second axis) ------------------------------------
#
# A container stage has one version axis — the image is both runtime and code.
# NORDIC's runtime (MATLAB) and code (the toolbox checkout) move independently,
# so a matlab_module bump is invisible to toolbox-drift.


def _nordic_cfg(root, matlab="matlab/R2024a"):
    cfg = _config(root)
    cfg["paths"]["nordic_toolbox_dir"] = str(root / "NORDIC_Raw")
    cfg.setdefault("nordic", {})["matlab_module"] = matlab
    return cfg


def test_matlab_module_changed_since_the_run_is_drift(monkeypatch, tmp_path):
    cfg = _nordic_cfg(tmp_path, matlab="matlab/R2025a")
    write_derivative_description(
        tmp_path / "derivatives" / "nordic",
        "nordic",
        tool="nordic",
        tool_version="v1.0.2-24-g0861968",
        runtime="matlab/R2024a",
    )
    _toolbox(monkeypatch, "v1.0.2-24-g0861968")  # toolbox itself unchanged
    issues = check_consistency(cfg)
    assert "matlab-drift" in _codes(issues)
    assert "toolbox-drift" not in _codes(issues)  # the axes are independent


def test_unchanged_matlab_module_is_clean(monkeypatch, tmp_path):
    cfg = _nordic_cfg(tmp_path, matlab="matlab/R2024a")
    write_derivative_description(
        tmp_path / "derivatives" / "nordic",
        "nordic",
        tool="nordic",
        tool_version="v1.0.2-24-g0861968",
        runtime="matlab/R2024a",
    )
    _toolbox(monkeypatch, "v1.0.2-24-g0861968")
    assert "matlab-drift" not in _codes(check_consistency(cfg))


def test_matlab_drift_reads_sidecars(monkeypatch, tmp_path):
    cfg = _nordic_cfg(tmp_path, matlab="matlab/R2025a")
    _nordic_deriv(tmp_path)  # dataset stamp carries no runtime
    _nordic_sidecar(tmp_path, "01", 1, Runtime="matlab/R2024a")
    _toolbox(monkeypatch, "")
    assert "matlab-drift" in _codes(check_consistency(cfg))


def test_unknowable_matlab_runtime_is_never_drift(monkeypatch, tmp_path):
    cfg = _nordic_cfg(tmp_path, matlab="matlab/R2025a")
    _nordic_deriv(tmp_path)  # nothing recorded about the runtime
    _toolbox(monkeypatch, "")
    assert "matlab-drift" not in _codes(check_consistency(cfg))


# ---- duckbrain drift (note severity, recipe stages only) --------------------
#
# duckbrain's version is a different kind of fact from fMRIPrep's: a tool's
# version IS the computation, duckbrain's is the recipe-writer. So it is flagged
# only where duckbrain authors the recipe, only on a release-line change, and
# only as a note.


def _duckbrain(monkeypatch, version):
    import duckbrain.core.consistency as CO

    monkeypatch.setattr(CO, "duckbrain_version", lambda: version)


def _stamp_duckbrain(root, version):
    """A dataset root stamped by a given duckbrain, as write_dataset_description does."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "x",
                "BIDSVersion": "1.9.0",
                "GeneratedBy": [{"Name": "duckbrain", "Version": version}],
            }
        )
    )


def test_release_line_change_is_noted_for_conversion(monkeypatch, tmp_path):
    _stamp_duckbrain(tmp_path, "v0.1.0")  # BIDS root: what converted it
    _duckbrain(monkeypatch, "v0.3.0-2-gabcdef1")  # duckbrain now
    issues = [i for i in check_consistency(_config(tmp_path)) if i.check == "duckbrain-drift"]
    assert issues and issues[0].stage == "converted"
    assert issues[0].severity == "note"  # not a warning


def test_development_within_a_release_line_is_silent(monkeypatch, tmp_path):
    """The whole point: rapid iteration between releases must not flag."""
    _stamp_duckbrain(tmp_path, "v0.1.0")
    _duckbrain(monkeypatch, "v0.1.0-47-gabcdef1-dirty")  # 47 commits on, still 0.1.x
    assert "duckbrain-drift" not in _codes(check_consistency(_config(tmp_path)))


def test_patch_releases_do_not_flag(monkeypatch, tmp_path):
    _stamp_duckbrain(tmp_path, "v0.1.0")
    _duckbrain(monkeypatch, "v0.1.9")
    assert "duckbrain-drift" not in _codes(check_consistency(_config(tmp_path)))


def test_minor_is_the_release_line_before_1_0(monkeypatch, tmp_path):
    """Pre-1.0, minor carries the breaking signal (0.1 -> 0.2 may break)."""
    _stamp_duckbrain(tmp_path, "v0.1.0")
    _duckbrain(monkeypatch, "v0.2.0")
    assert "duckbrain-drift" in _codes(check_consistency(_config(tmp_path)))


def test_minor_is_not_the_release_line_after_1_0(monkeypatch, tmp_path):
    """Post-1.0 semver: only major breaks, so 1.2 -> 1.7 is not drift."""
    _stamp_duckbrain(tmp_path, "v1.2.0")
    _duckbrain(monkeypatch, "v1.7.3")
    assert "duckbrain-drift" not in _codes(check_consistency(_config(tmp_path)))

    _duckbrain(monkeypatch, "v2.0.0")
    assert "duckbrain-drift" in _codes(check_consistency(_config(tmp_path)))


def test_duckbrain_drift_is_noted_for_nordic(monkeypatch, tmp_path):
    cfg = _nordic_cfg(tmp_path)
    _stamp_duckbrain(tmp_path / "derivatives" / "nordic", "v0.1.0")
    _duckbrain(monkeypatch, "v0.4.0")
    _toolbox(monkeypatch, "")
    issues = [i for i in check_consistency(cfg) if i.check == "duckbrain-drift"]
    assert [i.stage for i in issues] == ["nordic"]


def test_duckbrain_drift_not_raised_for_launcher_stages(monkeypatch, tmp_path):
    """fMRIPrep/MRIQC: duckbrain only passes flags to a container, so its own
    version says nothing about the output — flagging it would be pure noise."""
    _fmriprep_desc(tmp_path)  # a real fMRIPrep derivative...
    _fmriprep_unit(tmp_path, "01")
    _duckbrain(monkeypatch, "v9.0.0")  # ...and a wildly different duckbrain
    issues = [i for i in check_consistency(_config(tmp_path)) if i.check == "duckbrain-drift"]
    assert [i.stage for i in issues] == []


def test_untagged_duckbrain_checkout_is_never_drift(monkeypatch, tmp_path):
    """A bare sha (no reachable tag) is unknowable, not a mismatch."""
    _stamp_duckbrain(tmp_path, "v0.1.0")
    _duckbrain(monkeypatch, "abc1234")
    assert "duckbrain-drift" not in _codes(check_consistency(_config(tmp_path)))

    _stamp_duckbrain(tmp_path, "abc1234")  # and the mirror: unknowable recorded
    _duckbrain(monkeypatch, "v0.1.0")
    assert "duckbrain-drift" not in _codes(check_consistency(_config(tmp_path)))


# ---- mixed provenance / version (log overlay) -------------------------------


def test_mixed_input_variant_across_subjects_flagged(tmp_path):
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    _fmriprep_unit(tmp_path, "02")
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" in _codes(check_consistency(cfg))


def test_latest_run_supersedes_so_uniform_rerun_is_clean(tmp_path):
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    _fmriprep_unit(tmp_path, "02")
    # sub-01 first ran raw, then re-ran nordic; sub-02 ran nordic. Latest is
    # uniformly nordic, so no mixing.
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "01", "", "J2", tool="fmriprep", input_variant="nordic")
    record_submission(cfg, "fmriprep", "02", "", "J3", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" not in _codes(check_consistency(cfg))


def test_mixed_tool_version_across_subjects_flagged(tmp_path):
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    _fmriprep_unit(tmp_path, "02")
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", tool_version="24.1.1")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", tool_version="25.0.0")
    assert "mixed-version" in _codes(check_consistency(cfg))


def test_mixed_toolbox_versions_across_nordic_subjects_flagged(tmp_path):
    """Mixing is not fMRIPrep-only — and for NORDIC the sidecars are the source."""
    cfg = _nordic_cfg(tmp_path)
    _nordic_sidecar(tmp_path, "01", 1, ToolVersion="v1.0.2-24-g0861968")
    _nordic_sidecar(tmp_path, "02", 1, ToolVersion="v1.0.2-31-gabcdef1")
    issues = check_consistency(cfg)
    assert "mixed-version" in _codes(issues)
    assert any(i.stage == "nordic" for i in issues if i.check == "mixed-version")


def test_mixed_toolbox_versions_WITHIN_one_subject_flagged(tmp_path):
    """The case only sidecars can catch, and the reason for the swap.

    The sbatch skips already-denoised runs, so a partial array failure re-launched
    after a toolbox bump leaves survivors on the old toolbox. The log records one
    row per submission, so latest-per-subject would report the new toolbox for all
    13 files. Per-file sidecars report the truth.
    """
    cfg = _nordic_cfg(tmp_path)
    _nordic_sidecar(tmp_path, "01", 1, ToolVersion="v1.0.2-24-g0861968")  # survivor
    _nordic_sidecar(tmp_path, "01", 2, ToolVersion="v1.0.2-31-gabcdef1")  # re-denoised
    issues = [i for i in check_consistency(cfg) if i.check == "mixed-version"]
    assert issues
    # The same subject appears under both versions — that IS the signal.
    assert issues[0].message.count("01") == 2


def test_mixed_matlab_runtimes_across_nordic_subjects_flagged(tmp_path):
    cfg = _nordic_cfg(tmp_path)
    _nordic_sidecar(tmp_path, "01", 1, Runtime="matlab/R2024a")
    _nordic_sidecar(tmp_path, "02", 1, Runtime="matlab/R2025a")
    assert "mixed-runtime" in _codes(check_consistency(cfg))


def test_uniform_nordic_provenance_is_clean(tmp_path):
    cfg = _nordic_cfg(tmp_path)
    for sub in ("01", "02"):
        _nordic_sidecar(tmp_path, sub, 1, ToolVersion="v1.0.2-24-g0861968", Runtime="matlab/R2024a")
    codes = _codes(check_consistency(cfg))
    assert "mixed-version" not in codes and "mixed-runtime" not in codes


def test_blank_provenance_is_unknown_not_a_distinct_value(tmp_path):
    """A derivative half of whose files predate a provenance field must not read
    as mixed — blank is unknown, not a value."""
    cfg = _nordic_cfg(tmp_path)
    _nordic_sidecar(tmp_path, "01", 1, Runtime="")
    _nordic_sidecar(tmp_path, "02", 1, Runtime="matlab/R2024a")
    assert "mixed-runtime" not in _codes(check_consistency(cfg))


def test_sidecars_without_provenance_are_ignored(tmp_path):
    """A NORDIC output duckbrain didn't stamp is unknowable, not evidence."""
    cfg = _nordic_cfg(tmp_path)
    d = tmp_path / "derivatives" / "nordic" / "sub-01" / "func"
    d.mkdir(parents=True)
    (d / "sub-01_task-x_bold.nii.gz").write_text("nii")
    (d / "sub-01_task-x_bold.json").write_text(json.dumps({"RepetitionTime": 1.0}))
    _nordic_sidecar(tmp_path, "02", 1, ToolVersion="v1.0.2-24-g0861968")
    assert "mixed-version" not in _codes(check_consistency(cfg))


def test_submission_without_output_on_disk_contributes_no_provenance(tmp_path):
    """The log tracks submissions; the files record what was produced. A run that
    was cancelled (or deleted, or is still in flight) leaves a log row but no
    output — it must not claim provenance for a subject the derivative lacks.

    Real case (2026-07-16): divatten_gui_beta's only fMRIPrep log row is sub-008,
    a NORDIC-chained run that was cancelled and its partial output removed.
    """
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")  # only sub-01 actually has output
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" not in _codes(check_consistency(cfg))


# ---- staleness --------------------------------------------------------------


def _bold_pair(tmp_path, subject, fmriprep_mtime, nordic_mtime):
    """One subject's fMRIPrep and NORDIC bold, each at a chosen mtime (None = absent)."""
    import os

    deriv = tmp_path / "derivatives"
    if fmriprep_mtime is not None:
        fp = deriv / "fmriprep" / f"sub-{subject}" / "func"
        fp.mkdir(parents=True)
        fp_bold = fp / f"sub-{subject}_task-x_desc-preproc_bold.nii.gz"
        fp_bold.write_text("x")
        os.utime(fp_bold, (fmriprep_mtime, fmriprep_mtime))
    if nordic_mtime is not None:
        nd = deriv / "nordic" / f"sub-{subject}" / "func"
        nd.mkdir(parents=True)
        nd_bold = nd / f"sub-{subject}_task-x_bold.nii.gz"
        nd_bold.write_text("x")
        os.utime(nd_bold, (nordic_mtime, nordic_mtime))


def test_nordic_newer_than_fmriprep_flags_staleness(tmp_path):
    cfg = _config(tmp_path, use_nordic=True)
    _bold_pair(tmp_path, "01", fmriprep_mtime=1000, nordic_mtime=2000)
    issues = [i for i in check_consistency(cfg) if i.check == "staleness"]
    assert len(issues) == 1
    assert issues[0].subject == "01"
    assert "sub-01" in issues[0].message


def test_a_new_subjects_nordic_run_does_not_smear_staleness(tmp_path):
    """The check's first live firing, pinned (#40): a NORDIC run for a subject
    fMRIPrep has never touched must not flag the finished subjects.

    The project-wide comparison took the newest NORDIC mtime (the new subject)
    against the newest fMRIPrep mtime (a finished one) and prescribed re-running
    five subjects whose inputs never changed. A subject with NORDIC and no
    fMRIPrep is not stale — it is not run yet, which the cockpit already shows.
    """
    cfg = _config(tmp_path, use_nordic=True)
    _bold_pair(tmp_path, "01", fmriprep_mtime=2000, nordic_mtime=1000)  # finished, in order
    _bold_pair(tmp_path, "20", fmriprep_mtime=None, nordic_mtime=3000)  # new, not run yet
    assert "staleness" not in _codes(check_consistency(cfg))


def test_only_the_genuinely_stale_subject_is_flagged_and_named(tmp_path):
    cfg = _config(tmp_path, use_nordic=True)
    _bold_pair(tmp_path, "01", fmriprep_mtime=2000, nordic_mtime=1000)  # in order
    _bold_pair(tmp_path, "02", fmriprep_mtime=1000, nordic_mtime=2000)  # stale
    issues = [i for i in check_consistency(cfg) if i.check == "staleness"]
    assert [i.subject for i in issues] == ["02"]
    assert "sub-02" in issues[0].message


def test_a_nordic_subject_dir_without_bold_output_is_not_stale(tmp_path):
    """An empty or partial NORDIC subject tree contributes no mtime evidence."""
    cfg = _config(tmp_path, use_nordic=True)
    _bold_pair(tmp_path, "01", fmriprep_mtime=1000, nordic_mtime=None)
    (tmp_path / "derivatives" / "nordic" / "sub-01" / "func").mkdir(parents=True)
    assert "staleness" not in _codes(check_consistency(cfg))


# ---- presence ---------------------------------------------------------------


def test_presence_fmriprep_without_nordic_in_nordic_project(tmp_path):
    cfg = _config(tmp_path, use_nordic=True)
    # A complete-looking fMRIPrep unit, no NORDIC output, no func in BIDS so the
    # fMRIPrep tracker is satisfied by the anat+html markers.
    fp = tmp_path / "derivatives" / "fmriprep"
    (fp / "sub-01" / "anat").mkdir(parents=True)
    (fp / "sub-01.html").write_text("report")
    (fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz").write_text("x")
    (tmp_path / "sub-01" / "anat").mkdir(parents=True)  # BIDS unit exists, anat-only
    issues = check_consistency(cfg)
    assert "presence" in _codes(issues)
    assert any(i.subject == "01" for i in issues if i.check == "presence")


# ---- tool crash records -----------------------------------------------------
#
# The failure these pin: an fMRIPrep run whose FreeSurfer-directory node raised,
# had everything downstream of it pruned, and still printed "finished
# successfully" and exited 0 (job 45644650, 2026-07-24). The crash file is the
# only artifact that disagrees with the exit code.


def test_a_crash_file_is_reported_even_though_the_job_exited_zero(tmp_path):
    _crash(tmp_path)
    _submitted(tmp_path)
    issues = [i for i in check_consistency(_config(tmp_path)) if i.check == "tool-crash"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].stage == "fmriprep"
    assert _REAL_CRASH in issues[0].message


def test_the_message_says_the_exit_code_does_not_carry_this(tmp_path):
    """The durable lesson has to be in the text, not only the filename."""
    _crash(tmp_path)
    _submitted(tmp_path)
    (issue,) = [i for i in check_consistency(_config(tmp_path)) if i.check == "tool-crash"]
    assert "exit code does not carry this" in issue.message


def test_a_crash_from_a_superseded_run_is_silent(tmp_path):
    """The headline staleness case, on the real pair of timestamps.

    The crash is stamped 2026-07-24; the project was re-run successfully on
    2026-07-27. A check that kept reporting it would be switched off inside a
    week.
    """
    _crash(tmp_path)
    _submitted(tmp_path, when=_RERUN)
    assert "tool-crash" not in _codes(check_consistency(_config(tmp_path)))


def test_a_crash_after_the_last_submission_is_reported(tmp_path):
    """The real case: submitted 18:33:05, crashed 18:34:35, 90 seconds later."""
    _crash(tmp_path)
    _submitted(tmp_path, when=_CRASHED_RUN)
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_a_crash_within_the_clock_grace_of_its_submission_is_reported(tmp_path):
    """Two clocks, so the comparison is biased toward reporting, not silence.

    The login node writes the submission row; the compute node writes the crash
    file. A crash stamped a minute *before* its own submission is skew, not a
    leftover.
    """
    _crash(tmp_path, name="crash-20260724-183205-bhutch-fsdir_run-abc.txt")
    _submitted(tmp_path, when=_CRASHED_RUN)
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_no_submission_log_at_all_still_reports(tmp_path):
    """An externally-run derivative is not thereby exempt.

    Nothing duckbrain launched means nothing that could have superseded the
    crash, so the only honest reading is that it is current.
    """
    _crash(tmp_path)
    (issue,) = [i for i in check_consistency(_config(tmp_path)) if i.check == "tool-crash"]
    assert "no fmriprep submission logged" in issue.message


def test_a_stage_with_no_submissions_of_its_own_is_not_shielded_by_another(tmp_path):
    _crash(tmp_path, stage="fmriprep")
    _submitted(tmp_path, stage="mriqc", when=_RERUN)
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_an_unparsable_crash_filename_is_reported_not_assumed_stale(tmp_path):
    """A file whose age we cannot establish is not a file that is old."""
    _crash(tmp_path, name="crash-not-a-date-xyz.txt")
    _submitted(tmp_path, when=_RERUN)
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_a_crash_stamp_that_is_not_a_real_date_is_reported(tmp_path):
    """Digits in the right shape are not a date: month 13 parses as unknown."""
    _crash(tmp_path, name="crash-20261345-996699-bhutch-node-uuid.txt")
    _submitted(tmp_path, when=_RERUN)
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_an_unparsable_submission_timestamp_is_no_cutoff(tmp_path):
    _crash(tmp_path)
    _submitted(tmp_path, when="the day before yesterday")
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_mriqc_crash_files_are_read_the_same_way(tmp_path):
    _crash(tmp_path, stage="mriqc")
    _submitted(tmp_path, stage="mriqc")
    (issue,) = [i for i in check_consistency(_config(tmp_path)) if i.check == "tool-crash"]
    assert issue.stage == "mriqc"
    assert "MRIQC" in issue.message


def test_a_crash_at_the_derivative_root_is_found(tmp_path):
    """nipype's own default location, kept as a second guess."""
    _crash(tmp_path, where="")
    _submitted(tmp_path)
    assert "tool-crash" in _codes(check_consistency(_config(tmp_path)))


def test_several_crashes_report_as_one_issue(tmp_path):
    for stamp in ("183435", "184501", "190212"):
        _crash(tmp_path, name=f"crash-20260724-{stamp}-bhutch-node-uuid.txt")
    _submitted(tmp_path)
    (issue,) = [i for i in check_consistency(_config(tmp_path)) if i.check == "tool-crash"]
    assert "3 crashed node(s)" in issue.message
    assert "+1 more" in issue.message


def test_a_crash_is_not_attributed_to_a_subject(tmp_path):
    """Pins the refusal, so nobody "improves" it into a wrong attribution.

    The node that caused this — ``fsdir_run_…`` — is project-level and carries no
    subject at all.
    """
    _crash(tmp_path)
    _submitted(tmp_path)
    (issue,) = [i for i in check_consistency(_config(tmp_path)) if i.check == "tool-crash"]
    assert issue.subject == ""


def test_an_unreadable_crash_directory_reports_nothing_rather_than_raising(tmp_path, monkeypatch):
    """Called directly: the panel's own try/except would hide a raise in here."""
    _crash(tmp_path)
    _submitted(tmp_path)

    def boom(self, pattern):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "glob", boom)
    assert _check_tool_crashes(_config(tmp_path)) == []


def test_a_derivative_with_no_crash_files_reports_nothing(tmp_path):
    (tmp_path / "derivatives" / "fmriprep" / "logs").mkdir(parents=True)
    _submitted(tmp_path)
    assert "tool-crash" not in _codes(check_consistency(_config(tmp_path)))


def test_no_derivatives_path_configured_reports_nothing(tmp_path):
    cfg = _config(tmp_path)
    cfg["paths"]["derivatives_dir"] = ""
    assert "tool-crash" not in _codes(check_consistency(cfg))


# ---- reading a sidecar that isn't an object ---------------------------------


def test_valid_json_that_is_not_an_object_reads_as_unreadable(tmp_path):
    """``null`` / ``[]`` / a bare string are all valid JSON and none is a sidecar.

    ``_read_json`` absorbs an unreadable file into ``{}`` on purpose, so every
    caller can do ``.get()`` without guarding. But it absorbed only *parse*
    failures, and these three parse fine — so they returned None/list/str from a
    function declared ``-> dict`` and the caller raised AttributeError out of a
    checker whose entire job is to survive bad files. Found by mypy's
    ``warn_return_any``; the truncated-file case below is the one
    that always worked, kept here so the pair reads as one contract.
    """
    from duckbrain.core.consistency import _read_json

    for text in ("null", "[]", '"a string"', "3", ""):
        p = tmp_path / "sidecar.json"
        p.write_text(text)
        assert _read_json(p) == {}, f"{text!r} should read as unreadable"

    p = tmp_path / "sidecar.json"
    p.write_text('{"EchoTime": 0.03}')
    assert _read_json(p) == {"EchoTime": 0.03}


# ---- clean project ----------------------------------------------------------


def test_clean_project_has_no_issues(tmp_path):
    assert check_consistency(_config(tmp_path)) == []


def test_consistency_issue_is_frozen_dataclass():
    i = ConsistencyIssue("presence", "msg", subject="01")
    assert i.severity == "warning"
    assert (i.check, i.subject) == ("presence", "01")


# ---- fs8-fmriprep-pairing ------------------------------------------------------


def _pairing(root, fmriprep_version, use_external=True):
    cfg = _config(root, containers={"fmriprep_version": fmriprep_version})
    if use_external:
        cfg["freesurfer"] = {"use_external": True}
    return [i for i in check_consistency(cfg) if i.check == "fs8-fmriprep-pairing"]


def test_fs8_with_pre25_fmriprep_warns_before_compute_is_spent(tmp_path):
    """Config-vs-config on purpose: the audience is a user who inherited a
    project config or is new to the pipeline, and the warning has to land
    before the hours are spent, not after. The only validated pairing for an
    imported FS8 recon is fMRIPrep 25.x."""
    issues = _pairing(tmp_path, "24.1.1")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].stage == "fmriprep"
    assert "24.1.1" in issues[0].message
    assert "25.2.5" in issues[0].message  # the fix is stated, not implied


def test_fs8_with_fmriprep_25_or_later_is_silent(tmp_path):
    assert _pairing(tmp_path, "25.2.5") == []
    assert _pairing(tmp_path, "26.0.0") == []


def test_fs8_pairing_never_fires_without_use_external(tmp_path):
    # A pre-25 pin alone is legitimate (existing derivatives live on 24.1.1);
    # only the combination is the untested corner.
    assert _pairing(tmp_path, "24.1.1", use_external=False) == []


def test_fs8_pairing_unparseable_version_is_unknowable_not_wrong(tmp_path):
    assert _pairing(tmp_path, "latest") == []
    assert _pairing(tmp_path, "") == []
