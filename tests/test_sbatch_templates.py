"""sbatch template rendering — session handling and shared-FS log paths."""

import pytest

from duckbrain.slurm.templates import render_sbatch, build_context

BASE_PATHS = {
    "work_dir": "/tmp",
    "log_dir": "/projects/study/logs",
    "bids_dir": "/projects/study",
    "derivatives_dir": "/projects/study/derivatives",
}


def _cfg():
    return {
        "paths": dict(BASE_PATHS),
        "slurm": {},
        "containers": {},
        "fmriprep": {"nprocs": 8, "mem_gb": 32},
        "nordic": {},
    }


def _dcm2bids(session):
    ctx = build_context(
        _cfg(), "dcm2bids", subject="04", session=session,
        dicom_dir="/projects/study/sourcedata/sub-04/dicom",
        config_json="/projects/study/sourcedata/sub-04/dcm2bids_config.json",
        config_json_dir="/projects/study/sourcedata/sub-04",
        container_path="/c/dcm2bids.sif", force=False,
    )
    return render_sbatch("dcm2bids", ctx)


def test_dcm2bids_omits_session_flag_when_single_session():
    # Regression: an empty -s value makes dcm2bids exit 2 (argparse error).
    script = _dcm2bids("")
    assert " -s " not in script
    assert "\n  -s" not in script
    assert "--job-name=dcm2bids_04\n" in script


def test_dcm2bids_includes_session_flag_when_multi_session():
    script = _dcm2bids("01")
    assert "-s 01" in script
    assert "--job-name=dcm2bids_04_01" in script


@pytest.mark.parametrize(
    "step,ctx_extra",
    [
        ("dcm2bids", dict(subject="04", session="", dicom_dir="/d", config_json="/c.json",
                          config_json_dir="/", container_path="/x.sif", force=False)),
        ("fmriprep", dict(subject="04", session="", bids_dir="/b", output_dir="/o",
                          container_path="/x", fs_license="/l", fs_license_dir="/",
                          output_spaces=["func"], filter_file="", anat_only=False, derivatives="")),
        ("mriqc", dict(subject="04", session="", container_path="/x", mem_gb=8)),
    ],
)
def test_logs_go_to_shared_log_dir_not_tmp(step, ctx_extra):
    ctx = build_context(_cfg(), step, **ctx_extra)
    script = render_sbatch(step, ctx)
    out_line = next(l for l in script.splitlines() if "--output" in l)
    assert "/projects/study/logs/" in out_line
    assert "/tmp/logs" not in out_line


def _fmriprep(**extra):
    kwargs = dict(
        subject="04", session="",
        bids_dir="/b", output_dir="/projects/study/derivatives/fmriprep",
        container_path="/x", fs_license="/l", fs_license_dir="/",
        output_spaces=["func"], filter_file="", anat_only=False, derivatives="",
    )
    kwargs.update(extra)
    return render_sbatch("fmriprep", build_context(_cfg(), "fmriprep", **kwargs))


def test_fmriprep_creates_output_dir_before_bind():
    # Regression: Singularity requires the bind source to pre-exist, so the
    # output dir must be mkdir'd before `singularity run`.
    script = _fmriprep()
    lines = script.splitlines()
    mkdir_i = next(i for i, l in enumerate(lines)
                   if "mkdir" in l and "/projects/study/derivatives/fmriprep" in l)
    run_i = next(i for i, l in enumerate(lines) if l.startswith("singularity run"))
    assert mkdir_i < run_i


def test_fmriprep_templateflow_home_is_per_job():
    # Regression: a shared node-local TemplateFlow home races when two jobs land
    # on the same node. It must live under the per-job WORK_DIR.
    script = _fmriprep()
    tf_line = next(l for l in script.splitlines() if "TEMPLATEFLOW_HOME=" in l)
    assert "$WORK_DIR/templateflow" in tf_line


def test_fmriprep_custom_flags_appended():
    script = _fmriprep(extra_flags="--fs-no-reconall --dummy-scans 2")
    assert "--fs-no-reconall --dummy-scans 2" in script


def test_fmriprep_no_custom_flags_when_absent():
    # StrictUndefined must not trip when extra_flags is omitted entirely.
    script = _fmriprep()
    assert "--skip-bids-validation --notrack" in script


def _binds(script, path):
    return [l for l in script.splitlines() if l.strip().startswith(f"-B {path}:")]


def test_fmriprep_anat_reuse_does_not_rebind_output_dir():
    # Regression: --derivatives points at the output dir itself, which line 30
    # already binds read-write. Binding it again read-only made Singularity warn
    # ("destination is already in the mount point list") and drop one of the two;
    # had it dropped the read-write bind, fMRIPrep could not write its outputs.
    out = "/projects/study/derivatives/fmriprep"
    script = _fmriprep(derivatives=out)
    assert len(_binds(script, out)) == 1
    assert ":ro" not in _binds(script, out)[0]
    assert f"--derivatives {out}" in script  # the flag itself still goes out


def test_fmriprep_binds_derivatives_when_distinct_from_output():
    # A genuinely separate derivatives tree still needs its own read-only bind.
    script = _fmriprep(derivatives="/projects/study/derivatives/anat_only")
    binds = _binds(script, "/projects/study/derivatives/anat_only")
    assert len(binds) == 1
    assert binds[0].endswith(":ro \\")
