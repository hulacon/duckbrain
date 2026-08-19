"""sbatch template rendering — session handling and shared-FS log paths."""

import pytest

from duckbrain.slurm.templates import build_context, render_sbatch

BASE_PATHS = {
    "work_dir": "/tmp",
    "log_dir": "/projects/study/logs",
    "bids_dir": "/projects/study",
    "derivatives_dir": "/projects/study/derivatives",
}


def _cfg():
    return {
        "paths": dict(BASE_PATHS, nordic_toolbox_dir="/projects/study/NORDIC"),
        "slurm": {},
        "containers": {},
        "fmriprep": {"nprocs": 8, "mem_gb": 32},
        "nordic": {"matlab_module": "matlab/R2024a", "excluded_nodes": ""},
    }


# A minimal valid context per template, for tests that vary one toggle at a time.
_TEMPLATE_DEFAULTS = {
    "dcm2bids": dict(
        subject="04",
        session="01",
        dicom_dir="/d",
        config_json="/c.json",
        config_json_dir="/",
        container_path="/x.sif",
        force=False,
    ),
    "fmriprep": dict(
        subject="04",
        session="01",
        bids_dir="/b",
        output_dir="/projects/study/derivatives/fmriprep",
        container_path="/x.sif",
        fs_license="/l",
        fs_license_dir="/",
        output_spaces=["func"],
        filter_file="",
        anat_only=False,
        derivatives="",
        mem_gb=40,
    ),
    "mriqc": dict(subject="04", session="01", container_path="/x.sif", mem_gb=8),
    "nordic_denoise": dict(subject="04", session="01", bold_count=2, scripts_dir="/s"),
    "nordic_bids_input": dict(subject="04", session="01", python_cmd="/usr/bin/python3"),
    "freesurfer_recon": dict(
        subject="04",
        session="",
        fs_bin_dir="/packages/freesurfer/8.2.0/bin",
        fs_version="8.2.0",
        fs_license_file="/l",
        subjects_dir="/projects/study/derivatives/fmriprep/sourcedata/freesurfer/.recon-staging/sub-04",
        import_dir="/projects/study/derivatives/fmriprep/sourcedata/freesurfer",
        t1w_files=["/projects/study/sub-04/ses-01/anat/sub-04_ses-01_T1w.nii.gz"],
        t2w_file="",
    ),
}


def _dcm2bids(session, force=False):
    ctx = build_context(
        _cfg(),
        "dcm2bids",
        subject="04",
        session=session,
        dicom_dir="/projects/study/sourcedata/sub-04/dicom",
        config_json="/projects/study/sourcedata/sub-04/dcm2bids_config.json",
        config_json_dir="/projects/study/sourcedata/sub-04",
        container_path="/c/dcm2bids.sif",
        force=force,
    )
    return render_sbatch("dcm2bids", ctx)


def test_dcm2bids_force_passes_clobber_so_it_overwrites_bids_output():
    """force has to carry --clobber, not just --force_dcm2bids.

    The two flags clobber different things: --force_dcm2bids overwrites the
    temporary dcm2niix output, --clobber overwrites the BIDS output. dcm2bids
    skips any destination file that already exists unless --clobber is given, so
    with only the first flag a reconvert re-ran dcm2niix, wrote nothing, and
    exited 0 — the checkbox said "Force overwrite existing BIDS output" and
    overwrote none of it.
    """
    script = _dcm2bids("", force=True)
    assert "--clobber" in script, (
        "without --clobber dcm2bids skips existing outputs and the reconvert is a no-op"
    )
    assert "--force_dcm2bids" in script


def test_dcm2bids_without_force_clobbers_nothing():
    script = _dcm2bids("", force=False)
    assert "--clobber" not in script
    assert "--force_dcm2bids" not in script


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
        (
            "dcm2bids",
            dict(
                subject="04",
                session="",
                dicom_dir="/d",
                config_json="/c.json",
                config_json_dir="/",
                container_path="/x.sif",
                force=False,
            ),
        ),
        (
            "fmriprep",
            dict(
                subject="04",
                session="",
                bids_dir="/b",
                output_dir="/o",
                container_path="/x",
                fs_license="/l",
                fs_license_dir="/",
                output_spaces=["func"],
                filter_file="",
                anat_only=False,
                derivatives="",
                mem_gb=40,
            ),
        ),
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
        subject="04",
        session="",
        bids_dir="/b",
        output_dir="/projects/study/derivatives/fmriprep",
        container_path="/x",
        fs_license="/l",
        fs_license_dir="/",
        output_spaces=["func"],
        filter_file="",
        anat_only=False,
        derivatives="",
        mem_gb=40,
    )
    kwargs.update(extra)
    return render_sbatch("fmriprep", build_context(_cfg(), "fmriprep", **kwargs))


def test_fmriprep_creates_output_dir_before_bind():
    # Regression: Singularity requires the bind source to pre-exist, so the
    # output dir must be mkdir'd before `singularity run`.
    script = _fmriprep()
    lines = script.splitlines()
    mkdir_i = next(
        i
        for i, line in enumerate(lines)
        if "mkdir" in line and "/projects/study/derivatives/fmriprep" in line
    )
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
        _nasty_cfg(),
        "dcm2bids",
        subject="04",
        session="01",
        dicom_dir=f"{NASTY}/sourcedata/sub-04/dicom",
        config_json=f"{NASTY}/cfg.json",
        config_json_dir=NASTY,
        container_path=f"{NASTY}/dcm2bids.sif",
        force=False,
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
        _nasty_cfg(),
        "fmriprep",
        subject="04",
        session="01",
        bids_dir=f"{NASTY}/bids",
        output_dir=f"{NASTY}/out",
        container_path=f"{NASTY}/fmriprep.sif",
        fs_license=f"{NASTY}/license.txt",
        fs_license_dir=NASTY,
        output_spaces=["MNI152NLin2009cAsym:res-2", "func"],
        filter_file=f"{NASTY}/filter.json",
        anat_only=False,
        derivatives="",
        mem_gb=40,
    )
    argv = _singularity_argv(render_sbatch("fmriprep", ctx))

    assert f"{NASTY}/bids" in argv
    assert f"{NASTY}/out" in argv
    assert f"{NASTY}/license.txt" in argv
    assert f"{NASTY}/filter.json" in argv
    assert argv[argv.index("--output-spaces") + 1] == "MNI152NLin2009cAsym:res-2"


def test_mriqc_survives_a_path_with_spaces_and_metacharacters():
    ctx = build_context(
        _nasty_cfg(),
        "mriqc",
        subject="04",
        session="01",
        container_path=f"{NASTY}/mriqc.sif",
        mem_gb=8,
    )
    argv = _singularity_argv(render_sbatch("mriqc", ctx))
    assert f"{NASTY}/bids" in argv


def _flag_lines_outside_a_command(script):
    """Logical lines that begin with a flag, i.e. flags that fell out of a command.

    Splices the backslash continuations the way bash does, so what comes back is
    the list of commands the shell would actually run.
    """
    spliced = script.replace("\\\n", " ").splitlines()
    return [line.strip() for line in spliced if line.strip().startswith("-")]


@pytest.mark.parametrize(
    "step,extra",
    [
        # Both toggles that gate a comment-adjacent branch, in both positions.
        ("dcm2bids", dict(force=True)),
        ("dcm2bids", dict(force=False)),
        ("dcm2bids", dict(force=True, bids_validate=False)),
        ("fmriprep", dict(derivatives="/projects/study/derivatives/fmriprep")),
        ("fmriprep", dict(derivatives="/projects/study/derivatives/anat", anat_only=True)),
        ("fmriprep", dict(derivatives="", extra_flags="--use-syn-sdc")),
        ("fmriprep", dict(derivatives="/d", extra_flags="--use-syn-sdc")),
        ("mriqc", {}),
        ("nordic_denoise", {}),
        ("nordic_bids_input", {}),
        # Both sides of the recon template's T2 branch, which sits mid-command.
        ("freesurfer_recon", {}),
        ("freesurfer_recon", dict(t2w_file="/projects/study/sub-04/anat/sub-04_T2w.nii.gz")),
    ],
)
def test_no_comment_breaks_a_line_continuation(step, extra):
    """A flag can never be a command, so a flag starting a line means the command
    above it ended early.

    A Jinja comment renders to nothing but still emits its own trailing newline.
    Parked between two continued lines that blank line terminates the command at
    the backslash above it, and every flag after it becomes a separate command
    that bash reports as "not found". It cost fMRIPrep `--skip-bids-validation
    --notrack` on exactly the anat-reuse job — the comment sat inside the
    `derivatives` branch, so ses-01 was fine and ses-02+ failed BIDS validation —
    and cost dcm2bids `--bids_validate --force_dcm2bids --clobber` on every job.

    Keep template comments above `singularity run`, never inside it.
    """
    ctx = build_context(_cfg(), step, **dict(_TEMPLATE_DEFAULTS[step], **extra))
    assert _flag_lines_outside_a_command(render_sbatch(step, ctx)) == []


@pytest.mark.parametrize(
    "step,extra",
    [
        (
            "dcm2bids",
            dict(
                subject="04",
                session="01",
                dicom_dir=NASTY,
                config_json=f"{NASTY}/c.json",
                config_json_dir=NASTY,
                container_path=f"{NASTY}/x.sif",
                force=False,
            ),
        ),
        (
            "fmriprep",
            dict(
                subject="04",
                session="01",
                bids_dir=NASTY,
                output_dir=NASTY,
                container_path=NASTY,
                fs_license=NASTY,
                fs_license_dir=NASTY,
                output_spaces=["func"],
                filter_file="",
                anat_only=False,
                derivatives="",
                mem_gb=40,
            ),
        ),
        ("mriqc", dict(subject="04", session="01", container_path=NASTY, mem_gb=8)),
        ("nordic_denoise", dict(subject="04", session="01", bold_count=2, scripts_dir=NASTY)),
        ("nordic_bids_input", dict(subject="04", session="01", python_cmd="/usr/bin/python3")),
        (
            "freesurfer_recon",
            dict(
                subject="04",
                session="",
                fs_bin_dir="/packages/freesurfer/8.2.0/bin",
                fs_version="8.2.0",
                fs_license_file=NASTY,
                subjects_dir=f"{NASTY}/.recon-staging/sub-04",
                import_dir=NASTY,
                t1w_files=[f"{NASTY}/sub-04_T1w.nii.gz"],
                t2w_file=f"{NASTY}/sub-04_T2w.nii.gz",
            ),
        ),
    ],
)
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
    script = render_sbatch(
        "nordic_bids_input",
        build_context(
            _nasty_cfg(),
            "nordic_bids_input",
            subject="04",
            session="01",
            python_cmd="/usr/bin/python3",
        ),
    )

    assert f"bids_dir='{NASTY}/bids'" not in script
    assert 'os.environ["DUCKBRAIN_BIDS_DIR"]' in script
    # The path appears exactly once, in a quoted export.
    export = next(
        line for line in script.splitlines() if line.startswith("export DUCKBRAIN_BIDS_DIR")
    )
    assert shlex.split(export)[1] == f"DUCKBRAIN_BIDS_DIR={NASTY}/bids"


def test_nordic_denoise_does_not_interpolate_into_the_matlab_literal():
    script = render_sbatch(
        "nordic_denoise",
        build_context(
            _nasty_cfg(),
            "nordic_denoise",
            subject="04",
            session="01",
            bold_count=2,
            scripts_dir=NASTY,
        ),
    )

    assert f"addpath('{NASTY}/NORDIC')" not in script
    assert "getenv('DUCKBRAIN_NORDIC_TOOLBOX')" in script


def test_extra_flags_stays_an_unquoted_shell_fragment():
    """The one deliberately trusted field: quoting it would collapse several
    flags into a single argument."""
    ctx = build_context(
        _nasty_cfg(),
        "fmriprep",
        subject="04",
        session="",
        bids_dir="/b",
        output_dir="/o",
        container_path="/x",
        fs_license="/l",
        fs_license_dir="/",
        output_spaces=["func"],
        filter_file="",
        anat_only=False,
        derivatives="",
        mem_gb=40,
        extra_flags="--use-syn-sdc --fd-spike-threshold 0.5",
    )
    argv = _singularity_argv(render_sbatch("fmriprep", ctx))
    assert "--use-syn-sdc" in argv
    assert argv[argv.index("--fd-spike-threshold") + 1] == "0.5"


def test_mriqc_reads_raw_bids_even_when_the_project_uses_nordic():
    """MRIQC grades the acquisition, not fMRIPrep's input — see
    ``pipeline.effective_dependencies`` for why that asymmetry is deliberate.

    Unpinned until now: the only MRIQC/NORDIC assertion anywhere was on the
    *dependency*, so a change to the input path would have gone unnoticed. The
    template hardcodes ``paths.bids_dir``, which is the behaviour worth holding —
    pointing MRIQC at denoised data would make its noise IQMs describe the
    denoiser rather than the scan.
    """
    cfg = _cfg()
    cfg["nordic"] = {"use_nordic": True}
    ctx = build_context(cfg, "mriqc", subject="04", session="", container_path="/x", mem_gb=8)
    script = render_sbatch("mriqc", ctx)

    assert "bids_format" not in script
    # The positional BIDS root MRIQC is handed, and the bind that backs it.
    assert '/projects/study "$OUTPUT_DIR" participant' in script
    assert "-B /projects/study:/projects/study:ro" in script


# --- node-local scratch: qualified per project, and cleared when it is done ---
#
# `work_dir` is node-local (/tmp) and every study's subject labels restart at 01,
# so the bare `/tmp/sub-<label>` these templates used to build was one nipype
# cache shared by every project with that label that landed on the same node —
# and nipype serves a cache hit indistinguishably from a computation. Nothing
# removed it either, so it grew until an eviction nobody asked for took it.

import os
import stat
import subprocess
from pathlib import Path

from duckbrain.config import unit_work_dir

SBATCH_TEMPLATES = ["dcm2bids", "fmriprep", "mriqc", "nordic_denoise", "nordic_bids_input"]


def test_no_template_builds_a_scratch_path_out_of_paths_work_dir():
    """The derivation lives in one place (``config.unit_work_dir``, reached via
    ``build_context``), so a template cannot reintroduce the unqualified path.

    A text sweep and not a rendering assertion on purpose: the bug was two
    templates independently spelling ``paths.work_dir ~ "/sub-"``, and a new
    template spelling it a third time is exactly what no per-template test would
    catch.
    """
    from duckbrain.slurm.templates import _get_templates_dir

    for path in sorted(_get_templates_dir().glob("*.sbatch.j2")):
        assert "paths.work_dir" not in path.read_text(), path.name


def _work_dir_line(script):
    return next(line for line in script.splitlines() if line.startswith("WORK_DIR="))


def test_two_projects_sharing_a_subject_label_get_different_scratch():
    """The collision this item exists for: sub-010 in two studies, one node."""
    a, b = _cfg(), _cfg()
    a["paths"]["bids_dir"] = "/projects/hulacon/bhutch/divatten_beta_v2"
    b["paths"]["bids_dir"] = "/projects/hulacon/shared/mmmduck"
    kw = dict(subject="010", session="01", container_path="/x", mem_gb=8)
    first = _work_dir_line(render_sbatch("mriqc", build_context(a, "mriqc", **kw)))
    second = _work_dir_line(render_sbatch("mriqc", build_context(b, "mriqc", **kw)))
    assert first != second
    # ...and each is still recognisable as its project on the node.
    assert "divatten_beta_v2" in first and "mmmduck" in second


def test_scratch_is_stable_across_attempts_of_the_same_unit():
    """Stable per (project, step, unit), never per attempt — a re-run after a
    walltime kill resumes from the cache the killed attempt left behind, which is
    the only reason the tree is worth keeping instead of always wiping it."""
    kw = dict(subject="04", session="01", container_path="/x", mem_gb=8)
    one = _work_dir_line(render_sbatch("mriqc", build_context(_cfg(), "mriqc", **kw)))
    two = _work_dir_line(render_sbatch("mriqc", build_context(_cfg(), "mriqc", **kw)))
    assert one == two


def test_each_step_and_unit_gets_its_own_scratch():
    cfg = _cfg()
    seen = {
        unit_work_dir(cfg, step, subject, session)
        for step in ("fmriprep", "mriqc")
        for subject, session in (("04", "01"), ("04", "02"), ("05", "01"))
    }
    assert len(seen) == 6


def test_a_nordic_fmriprep_run_shares_scratch_with_its_raw_twin():
    """``_build_fmriprep`` hands the template a *derivative* as ``bids_dir`` when
    ``use_nordic`` is on. The scratch qualifier reads the project directory from
    config instead, so flipping the toggle does not silently give one unit two
    caches (nor point two projects' NORDIC runs at one)."""
    cfg = _cfg()
    common = dict(
        subject="04",
        session="01",
        output_dir="/projects/study/derivatives/fmriprep",
        container_path="/x",
        fs_license="/l",
        fs_license_dir="/",
        output_spaces=["func"],
        filter_file="",
        anat_only=False,
        derivatives="",
        mem_gb=40,
    )
    raw = build_context(cfg, "fmriprep", bids_dir="/projects/study", **common)
    nordic = build_context(
        cfg, "fmriprep", bids_dir="/projects/study/derivatives/nordic/bids_format", **common
    )
    assert raw["work_dir"] == nordic["work_dir"]


def _run_rendered(script, tmp_path, *, exit_code=0, crash=None):
    """Execute a rendered sbatch with `singularity` stubbed out.

    Returns the WORK_DIR the script chose, so the caller can ask whether it
    survived. The stub, not the test, writes any crash file — it has to land
    *after* the attempt stamp, the way a real crash does.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "singularity"
    body = "#!/bin/bash\n"
    if crash:
        body += f'mkdir -p "$(dirname {crash})" && touch {crash}\n'
    body += f"exit {exit_code}\n"
    stub.write_text(body)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    path = tmp_path / "job.sh"
    path.write_text(script)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    proc = subprocess.run(["bash", str(path)], env=env, capture_output=True, text=True)
    assert proc.returncode == exit_code, proc.stderr
    return _work_dir_line(script).split("=", 1)[1].strip("'")


#: The two nipype stages that keep a work dir. Both are exercised, because the
#: cleanup guard is duplicated in both templates and a shell conjunction that
#: drifts in one of them fails silently in the direction of never cleaning up.
NIPYPE_STAGES = ["fmriprep", "mriqc"]


def _stage_script(tmp_path, stage):
    """A rendered script for *stage*, with every path it touches under tmp_path.

    Returns ``(script, derivative_root)`` — the derivative is where the crash
    record goes, since that is where the tool writes it.
    """
    cfg = _cfg()
    cfg["paths"]["work_dir"] = str(tmp_path / "scratch")
    cfg["paths"]["derivatives_dir"] = str(tmp_path / "derivatives")
    out = f"{tmp_path}/derivatives/{stage}"
    extra = dict(subject="04", session="01", container_path="/x", mem_gb=8)
    if stage == "fmriprep":
        extra.update(
            bids_dir="/b",
            output_dir=out,
            fs_license="/l",
            fs_license_dir="/",
            output_spaces=["func"],
            filter_file="",
            anat_only=False,
            derivatives="",
        )
    return render_sbatch(stage, build_context(cfg, stage, **extra)), out


@pytest.mark.parametrize("stage", NIPYPE_STAGES)
def test_a_finished_run_clears_its_own_scratch(tmp_path, stage):
    """Nothing else ever removed it. It is node-local, nothing downstream reads
    it (the FreeSurfer tree lives under the output dir), and it grew until some
    eviction nobody asked for took it."""
    script, _ = _stage_script(tmp_path, stage)
    work = _run_rendered(script, tmp_path)
    assert not Path(work).exists()


@pytest.mark.parametrize("stage", NIPYPE_STAGES)
def test_a_failed_run_keeps_its_scratch_for_the_next_attempt(tmp_path, stage):
    script, _ = _stage_script(tmp_path, stage)
    work = _run_rendered(script, tmp_path, exit_code=1)
    assert Path(work).is_dir()


@pytest.mark.parametrize("stage", NIPYPE_STAGES)
def test_a_crash_record_keeps_the_scratch_even_though_the_job_exited_zero(tmp_path, stage):
    """The reason cleanup is not keyed on the exit code. A nipype tool runs some
    nodes on the master thread, where a crash never reaches the not-run report —
    the workflow prints success, the process returns 0, and the crash file it
    wrote is the only artifact that disagrees (``consistency._check_tool_crashes``
    has the full mechanism). Wiping the work dir on exit 0 would be trusting
    exactly the signal that lies."""
    script, out = _stage_script(tmp_path, stage)
    work = _run_rendered(script, tmp_path, exit_code=0, crash=f"{out}/logs/crash-x.txt")
    assert Path(work).is_dir()


@pytest.mark.parametrize("stage", NIPYPE_STAGES)
def test_a_superseded_crash_record_does_not_block_cleanup(tmp_path, stage):
    """A crash file outlives the attempt that wrote it — it lives in the
    derivative, not the work dir, so an in-place re-run inherits the last one.
    Same staleness problem ``consistency._is_current_crash`` has, answered here
    with -newer against a stamp this attempt touched: only a crash from THIS run
    keeps the tree. Without it the first crash a project ever recorded would
    switch cleanup off for good."""
    script, out = _stage_script(tmp_path, stage)
    stale = Path(out) / "logs" / "crash-old.txt"
    stale.parent.mkdir(parents=True)
    stale.touch()
    os.utime(stale, (0, 0))
    work = _run_rendered(script, tmp_path)
    assert not Path(work).exists()


# ---- freesurfer_recon: stage-then-import, version-gated -----------------------


def _recon_script(**extra):
    ctx = build_context(
        _cfg(), "freesurfer", **dict(_TEMPLATE_DEFAULTS["freesurfer_recon"], **extra)
    )
    return render_sbatch("freesurfer_recon", ctx)


def test_recon_job_name_carries_no_session():
    # Subject-level stage: the name must match what advance_one submits
    # (freesurfer_<sub>) or the cockpit's live-state join goes blind.
    assert "#SBATCH --job-name=freesurfer_04\n" in _recon_script()


def test_recon_inputs_one_i_flag_per_t1w_and_optional_t2():
    script = _recon_script(
        t1w_files=["/p/a_T1w.nii.gz", "/p/b_T1w.nii.gz"], t2w_file="/p/c_T2w.nii.gz"
    )
    assert script.count("-i '") == 0  # sh filter only quotes when needed
    assert script.count("-i /p/a_T1w.nii.gz") == 1
    assert script.count("-i /p/b_T1w.nii.gz") == 1
    assert "-T2 /p/c_T2w.nii.gz -T2pial" in script
    assert "-T2 " not in _recon_script()  # no T2w → no flag at all


def test_recon_verifies_before_importing_and_never_imports_unverified():
    """The import rename must be unreachable except through recon_ok — the
    done-marker AND the pinned version's build-stamp. An exit-0 recon-all that
    left no done-marker (or a FreeSurfer 7 tree at the final path) must end the
    job, not reach `mv`."""
    script = _recon_script()
    assert 'recon_ok "$STAGED"' in script
    assert 'recon_ok "$FINAL"' in script
    assert 'grep -qF -- "-8.2.0"' in script
    # mv appears once, after the verification gates.
    assert script.count('mv "$STAGED" "$FINAL"') == 1
    assert script.index("recon_ok()") < script.index('mv "$STAGED" "$FINAL"')


def test_recon_runs_under_staging_never_the_import_dir():
    script = _recon_script()
    assert 'export SUBJECTS_DIR="$SUBJECTS_DIR_STAGING"' in script
    # recon-all is invoked from the pinned install, not bare PATH.
    assert "/packages/freesurfer/8.2.0/bin/recon-all" in script
