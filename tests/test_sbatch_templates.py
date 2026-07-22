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
    out_line = next(line for line in script.splitlines() if "--output" in line)
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
    mkdir_i = next(i for i, line in enumerate(lines)
                   if "mkdir" in line and "/projects/study/derivatives/fmriprep" in line)
    run_i = next(i for i, line in enumerate(lines) if line.startswith("singularity run"))
    assert mkdir_i < run_i


def test_fmriprep_templateflow_home_is_per_job():
    # Regression: a shared node-local TemplateFlow home races when two jobs land
    # on the same node. It must live under the per-job WORK_DIR.
    script = _fmriprep()
    tf_line = next(line for line in script.splitlines() if "TEMPLATEFLOW_HOME=" in line)
    assert "$WORK_DIR/templateflow" in tf_line


def test_fmriprep_custom_flags_appended():
    script = _fmriprep(extra_flags="--fs-no-reconall --dummy-scans 2")
    assert "--fs-no-reconall --dummy-scans 2" in script


def test_fmriprep_no_custom_flags_when_absent():
    # StrictUndefined must not trip when extra_flags is omitted entirely.
    script = _fmriprep()
    assert "--skip-bids-validation --notrack" in script


def _binds(script, path):
    return [line for line in script.splitlines() if line.strip().startswith(f"-B {path}:")]


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


# ---- DB-011: paths are shell arguments, and users pick the paths -------------
#
# Not hypothetical: /projects/lcni/dcm/hulacon/Hutchinson/New Program is a real
# LCNI export with a space in its name, one Setup form away from a rendered
# sbatch. Unquoted it becomes two arguments and the job fails obscurely.

import shlex

#: A path exercising everything bash treats specially, plus a space.
NASTY = "/projects/My Study (v2)/it's here/$HOME`x`/data*"


def _nasty_cfg():
    return {
        "paths": {
            "work_dir": f"{NASTY}/work",
            "log_dir": f"{NASTY}/logs",
            "bids_dir": f"{NASTY}/bids",
            "derivatives_dir": f"{NASTY}/derivatives",
            "nordic_toolbox_dir": f"{NASTY}/NORDIC",
        },
        "slurm": {},
        "containers": {},
        "fmriprep": {"nprocs": 8, "mem_gb": 32},
        "nordic": {"matlab_module": "matlab/R2024a", "excluded_nodes": ""},
    }


def _singularity_argv(script):
    """argv of the singularity invocation, as bash would split it."""
    joined = script.replace("\\\n", " ")
    line = next(line for line in joined.splitlines() if line.startswith("singularity run"))
    return shlex.split(line)


def test_dcm2bids_survives_a_path_with_spaces_and_metacharacters():
    ctx = build_context(
        _nasty_cfg(), "dcm2bids", subject="04", session="01",
        dicom_dir=f"{NASTY}/sourcedata/sub-04/dicom",
        config_json=f"{NASTY}/cfg.json", config_json_dir=NASTY,
        container_path=f"{NASTY}/dcm2bids.sif", force=False,
    )
    argv = _singularity_argv(render_sbatch("dcm2bids", ctx))

    # Each path is exactly ONE argument, with its metacharacters intact.
    assert f"{NASTY}/sourcedata/sub-04/dicom" in argv
    assert f"{NASTY}/bids" in argv
    assert f"{NASTY}/cfg.json" in argv
    # A bind spec is one argument, not three.
    assert f"{NASTY}/bids:{NASTY}/bids" in argv


def test_fmriprep_survives_a_path_with_spaces_and_metacharacters():
    ctx = build_context(
        _nasty_cfg(), "fmriprep", subject="04", session="01",
        bids_dir=f"{NASTY}/bids", output_dir=f"{NASTY}/out",
        container_path=f"{NASTY}/fmriprep.sif",
        fs_license=f"{NASTY}/license.txt", fs_license_dir=NASTY,
        output_spaces=["MNI152NLin2009cAsym:res-2", "func"],
        filter_file=f"{NASTY}/filter.json", anat_only=False, derivatives="",
    )
    argv = _singularity_argv(render_sbatch("fmriprep", ctx))

    assert f"{NASTY}/bids" in argv
    assert f"{NASTY}/out" in argv
    assert f"{NASTY}/license.txt" in argv
    assert f"{NASTY}/filter.json" in argv
    assert argv[argv.index("--output-spaces") + 1] == "MNI152NLin2009cAsym:res-2"


def test_mriqc_survives_a_path_with_spaces_and_metacharacters():
    ctx = build_context(_nasty_cfg(), "mriqc", subject="04", session="01",
                        container_path=f"{NASTY}/mriqc.sif", mem_gb=8)
    argv = _singularity_argv(render_sbatch("mriqc", ctx))
    assert f"{NASTY}/bids" in argv


@pytest.mark.parametrize("step,extra", [
    ("dcm2bids", dict(subject="04", session="01", dicom_dir=NASTY,
                      config_json=f"{NASTY}/c.json", config_json_dir=NASTY,
                      container_path=f"{NASTY}/x.sif", force=False)),
    ("fmriprep", dict(subject="04", session="01", bids_dir=NASTY, output_dir=NASTY,
                      container_path=NASTY, fs_license=NASTY, fs_license_dir=NASTY,
                      output_spaces=["func"], filter_file="", anat_only=False,
                      derivatives="")),
    ("mriqc", dict(subject="04", session="01", container_path=NASTY, mem_gb=8)),
    ("nordic_denoise", dict(subject="04", session="01", bold_count=2,
                            scripts_dir=NASTY)),
    ("nordic_bids_input", dict(subject="04", session="01", python_cmd="/usr/bin/python3")),
])
def test_rendered_scripts_are_parseable_shell(step, extra):
    """Every shell command line must tokenize.

    An apostrophe in a path leaves an unbalanced quote, and bash then fails on a
    line unrelated to the one at fault. `#SBATCH` directives are excluded on
    purpose: Slurm parses those, not bash, so metacharacters there are fine and
    quoting them would put literal quotes in the value.
    """
    script = render_sbatch(step, build_context(_nasty_cfg(), step, **extra))
    # Tokenize the remainder whole rather than line by line: a quoted heredoc-ish
    # block (the Python snippet in nordic_bids_input) legitimately spans lines.
    body = "\n".join(
        line for line in script.replace("\\\n", " ").splitlines() if not line.startswith("#")
    )
    shlex.split(body, comments=False)


def test_nordic_bids_input_does_not_interpolate_into_the_python_literal():
    """It rendered into a bash-double-quoted string holding Python single-quoted
    literals — two layers, so an apostrophe broke out of the Python string and a
    $ was expanded by bash before Python saw it. Values go via the environment."""
    script = render_sbatch("nordic_bids_input", build_context(
        _nasty_cfg(), "nordic_bids_input", subject="04", session="01",
        python_cmd="/usr/bin/python3"))

    assert f"bids_dir='{NASTY}/bids'" not in script
    assert 'os.environ["DUCKBRAIN_BIDS_DIR"]' in script
    # The path appears exactly once, in a quoted export.
    export = next(line for line in script.splitlines() if line.startswith("export DUCKBRAIN_BIDS_DIR"))
    assert shlex.split(export)[1] == f"DUCKBRAIN_BIDS_DIR={NASTY}/bids"


def test_nordic_denoise_does_not_interpolate_into_the_matlab_literal():
    script = render_sbatch("nordic_denoise", build_context(
        _nasty_cfg(), "nordic_denoise", subject="04", session="01",
        bold_count=2, scripts_dir=NASTY))

    assert f"addpath('{NASTY}/NORDIC')" not in script
    assert "getenv('DUCKBRAIN_NORDIC_TOOLBOX')" in script


def test_extra_flags_stays_an_unquoted_shell_fragment():
    """The one deliberately trusted field: quoting it would collapse several
    flags into a single argument."""
    ctx = build_context(
        _nasty_cfg(), "fmriprep", subject="04", session="",
        bids_dir="/b", output_dir="/o", container_path="/x", fs_license="/l",
        fs_license_dir="/", output_spaces=["func"], filter_file="",
        anat_only=False, derivatives="",
        extra_flags="--use-syn-sdc --fd-spike-threshold 0.5",
    )
    argv = _singularity_argv(render_sbatch("fmriprep", ctx))
    assert "--use-syn-sdc" in argv
    assert argv[argv.index("--fd-spike-threshold") + 1] == "0.5"
