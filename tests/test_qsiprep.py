"""QSIPrep — the three things it must refuse, and the merge its grader must absorb.

Every assertion here is against a rule stated in ``docs/pipeline-extras.md`` §1 or
in ``core/qsiprep.py``'s module docstring, and each names the failure it prevents:
a silently-clobbered anat, a guessed voxel size, a permanently-PARTIAL cell, and a
session that runs but never gets a report.
"""

import pytest

from duckbrain.core.pipeline import PipelineError, advance_one
from duckbrain.core.qsiprep import (
    SESSIONLESS_REFERENCE,
    SESSIONWISE,
    QsiprepConfigError,
    anatomical_reference,
    get_container_path,
    get_dwi_runs,
    has_dwi,
    output_resolution,
)
from duckbrain.core.surveyor import Status, run_progress, survey_project
from duckbrain.slurm.templates import build_context, render_sbatch


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _project(tmp_path, *, resolution=2.0, anat_ref=None, dwi=("dir-AP_run-1", "dir-PA_run-1")):
    """A minimal project with one DWI-bearing session, plus a licence and image."""
    for name in dwi:
        _touch(tmp_path / "sub-01" / "ses-01" / "dwi" / f"sub-01_ses-01_{name}_dwi.nii.gz")
    _touch(tmp_path / "containers" / "qsiprep-26.0.0.sif")
    _touch(tmp_path / "license.txt")
    qsiprep = {}
    if resolution is not None:
        qsiprep["output_resolution"] = resolution
    if anat_ref is not None:
        qsiprep["anatomical_reference"] = anat_ref
    return {
        "paths": {
            "bids_dir": str(tmp_path),
            "sourcedata_dir": str(tmp_path / "sourcedata"),
            "derivatives_dir": str(tmp_path / "derivatives"),
            "log_dir": str(tmp_path / "logs"),
            "work_dir": str(tmp_path / "scratch"),
            "containers_dir": str(tmp_path / "containers"),
            "fs_license": str(tmp_path / "license.txt"),
        },
        "containers": {"qsiprep_version": "26.0.0"},
        "qsiprep": qsiprep,
        "slurm": {},
        "nordic": {},
    }


def _export(config, subject="01", session="01", **params):
    """Render the job duckbrain would submit, without submitting it."""
    path = advance_one(config, "qsiprep", subject, session, export_only=True, **params)
    return open(path).read()


# ---- run discovery ----------------------------------------------------------


def test_a_diffusion_sbref_is_not_a_run(tmp_path):
    """``dwi/`` holds an ``_sbref`` beside the runs on scanners that write one —
    mmmsourcedata is the fixture that has them, and the LCNI corpus has none.
    Counting it would invent a shortfall QSIPrep can never make up: it is a
    reference image, not something the tool produces a preprocessed twin of."""
    _touch(tmp_path / "sub-01" / "dwi" / "sub-01_dir-AP_dwi.nii.gz")
    _touch(tmp_path / "sub-01" / "dwi" / "sub-01_dir-AP_sbref.nii.gz")
    assert [p.name for p in get_dwi_runs(tmp_path, "01", "")] == ["sub-01_dir-AP_dwi.nii.gz"]


def test_a_unit_without_diffusion_has_none(tmp_path):
    _touch(tmp_path / "sub-01" / "ses-01" / "func" / "sub-01_ses-01_task-rest_bold.nii.gz")
    assert get_dwi_runs(tmp_path, "01", "01") == []
    assert not has_dwi(tmp_path, "01", "01")


# ---- Trap 3: --output-resolution has no defensible default ------------------


def test_an_unset_output_resolution_refuses_to_launch(tmp_path):
    """The clearest case in the whole stage of CLAUDE.md's rule that a
    silently-degrading option is worse than one that fails. ``--output-resolution``
    is a single interpolation and a study-level scientific choice: a wrong value
    yields data that looks entirely usable and is wrongly sampled, with nothing
    downstream to notice. A 2.0 default would be a guess dressed as a setting."""
    config = _project(tmp_path, resolution=None)
    assert output_resolution(config) is None
    with pytest.raises(PipelineError, match="output_resolution"):
        _export(config)


def test_a_non_numeric_output_resolution_refuses_rather_than_rendering(tmp_path):
    """The GUI hands this through as free text, so ``"two"`` must not reach the
    container as a literal argument for QSIPrep to reject three hours later —
    and both sources must fail with the sentence that names the key, not with a
    bare ``could not convert string to float``."""
    with pytest.raises(PipelineError, match="must be a number of millimetres"):
        _export(_project(tmp_path), output_resolution="two")
    # ...and the same from the config path, where it also must not read back as
    # "not set": the owner had written the key, just not a number.
    with pytest.raises(QsiprepConfigError, match="must be a number of millimetres"):
        output_resolution({"qsiprep": {"output_resolution": "two"}})


def test_the_configured_resolution_reaches_the_command(tmp_path):
    assert "--output-resolution 1.7" in _export(_project(tmp_path, resolution=1.7))


# ---- Trap 2: per-session jobs clobber each other's anat ---------------------


def test_a_session_scoped_unit_is_forced_sessionwise(tmp_path):
    """duckbrain's unit is (subject, session), and every other value for
    ``--subject-anatomical-reference`` builds ONE ACPC reference per subject and
    writes it at the subject level — ``sub-XX/anat/`` and ``sub-XX.html``. Launch
    two sessions under it and the second silently overwrites the first, last
    writer wins, nothing said."""
    assert anatomical_reference({"qsiprep": {}}, "01") == SESSIONWISE
    assert "--subject-anatomical-reference sessionwise" in _export(_project(tmp_path))


def test_pinning_another_anatomical_reference_is_refused_not_honoured(tmp_path):
    """Refused rather than allowed to clobber: the run would look like it worked."""
    with pytest.raises(QsiprepConfigError, match="sessionwise"):
        anatomical_reference({"qsiprep": {"anatomical_reference": "unbiased"}}, "01")
    with pytest.raises(PipelineError, match="sessionwise"):
        _export(_project(tmp_path, anat_ref="unbiased"))


def test_a_sessionless_unit_gets_first_lex_so_it_gets_a_report(tmp_path):
    """The opposite answer, for a reason read out of QSIPrep 26.0.0's source
    rather than its docs. ``parser.py`` puts a subject with no sessions in the
    processing group ``[subject, []]``; ``reports/core.py`` then takes the
    sessionwise branch, which loops over that empty session list — so **no HTML
    report is written at all**. Every other reference value writes one. With no
    sessions the four choices are otherwise indistinguishable, which is what makes
    overriding a configured value here safe rather than a silent change."""
    assert anatomical_reference({"qsiprep": {}}, "") == SESSIONLESS_REFERENCE
    # Even a project that pinned sessionwise: the override is about the report,
    # not about honouring a preference that has nothing to distinguish it.
    assert anatomical_reference({"qsiprep": {"anatomical_reference": SESSIONWISE}}, "") == (
        SESSIONLESS_REFERENCE
    )
    _touch(tmp_path / "sub-02" / "dwi" / "sub-02_dir-AP_dwi.nii.gz")
    script = _export(_project(tmp_path), subject="02", session="")
    assert f"--subject-anatomical-reference {SESSIONLESS_REFERENCE}" in script
    assert "--session-id" not in script


# ---- the command itself -----------------------------------------------------


def test_the_session_is_passed_natively_with_no_bids_filter_file(tmp_path):
    """``--session-id`` is native to QSIPrep, which strips the ``ses-`` prefix
    itself. ``fmriprep.write_session_filter`` exists only because fMRIPrep must
    leave anat *unfiltered*; QSIPrep answers the same concern with
    ``--subject-anatomical-reference``. Porting the filter would be work that
    buys nothing and one more file to leave stale on shared FS."""
    script = _export(_project(tmp_path))
    assert "--session-id 01" in script
    assert "--bids-filter-file" not in script
    assert not list((tmp_path / "logs").glob("bids_filter_*.json"))


def test_the_freesurfer_licence_is_bound_and_named(tmp_path):
    """QSIPrep needs it for SynthStrip/SynthSeg — which is why this template is
    modelled on fmriprep.sbatch.j2 rather than the thinner mriqc one."""
    script = _export(_project(tmp_path))
    licence = tmp_path / "license.txt"
    assert f"--fs-license-file {licence}" in script
    # The flag alone is not enough: named but not bound, the path does not exist
    # inside the container and the run fails on a file the script clearly points at.
    assert f"-B {tmp_path}:{tmp_path}:ro" in script


def test_a_missing_freesurfer_licence_refuses_to_launch(tmp_path):
    config = _project(tmp_path)
    (tmp_path / "license.txt").unlink()
    config["paths"]["fs_license"] = str(tmp_path / "license.txt")
    with pytest.raises(PipelineError, match="[Ll]icense"):
        _export(config)


def test_a_unit_with_no_diffusion_refuses_to_launch(tmp_path):
    """Reaching the queue would spend a walltime slot to have QSIPrep discover
    the same thing and exit — and the board already reads n/a for such a unit, so
    a launch that succeeded would contradict it."""
    config = _project(tmp_path)
    _touch(tmp_path / "sub-09" / "ses-01" / "func" / "sub-09_ses-01_task-rest_bold.nii.gz")
    with pytest.raises(PipelineError, match="No diffusion data"):
        _export(config, subject="09")


def test_output_dir_is_the_stage_dir_itself(tmp_path):
    """QSIPrep's DerivativesDataSink sets ``out_path_base = ''`` and writes
    straight into what it is given, so duckbrain's one-dir-per-stage convention
    holds by naming ``<derivatives>/qsiprep`` here. The ``<out>/qsiprep/…`` in the
    published docs is stale — worth pinning before someone "fixes" a path that is
    already right."""
    script = _export(_project(tmp_path))
    assert f"OUTPUT_DIR={tmp_path}/derivatives/qsiprep\n" in script


def test_neither_resource_number_is_spelled_twice(tmp_path):
    """One allocation, one set of flags: ``--nprocs`` reads the same cpus as
    ``--cpus-per-task`` and ``--mem-mb`` is derived from ``--mem``. Two
    independently-set numbers on one script is the bug both rules exist to
    prevent (see config.tool_mem_gb)."""
    script = _export(_project(tmp_path), nprocs=6, mem_gb=40)
    assert "#SBATCH --cpus-per-task=6" in script
    assert "--nprocs 6" in script
    assert "#SBATCH --mem=40G" in script
    assert f"--mem-mb {(40 - 8) * 1024}" in script


def test_custom_flags_are_appended_unquoted(tmp_path):
    """``extra_flags`` is a shell fragment the operator supplies and must
    word-split — ``--dwi-denoise-window 5`` is two arguments."""
    script = _export(_project(tmp_path), extra_flags="--dwi-denoise-window 5")
    assert "--dwi-denoise-window 5" in script


def test_the_container_resolves_through_the_pinned_version(tmp_path):
    config = _project(tmp_path)
    assert get_container_path(config).name == "qsiprep-26.0.0.sif"


def test_a_missing_image_still_resolves_to_the_name_it_looked_for(tmp_path):
    """So the "container not found" message names what was expected rather than
    an empty path — the same fallback the other tool modules make."""
    config = _project(tmp_path)
    (tmp_path / "containers" / "qsiprep-26.0.0.sif").unlink()
    assert get_container_path(config).name == "qsiprep-26.0.0.sif"


# ---- Trap 1: merging breaks the surveyor's grader ---------------------------


def _survey(config, subject="01", session="01"):
    matrix = survey_project(config)
    row = matrix[(matrix["subject"] == subject) & (matrix["session"] == session)]
    return row.iloc[0]["qsiprep"]


def _finished(tmp_path, *outputs, report=True):
    root = tmp_path / "derivatives" / "qsiprep"
    for name in outputs:
        _touch(root / "sub-01" / "ses-01" / "dwi" / name)
    if report:
        _touch(root / "sub-01" / "ses-01" / "sub-01_ses-01.html")


def test_a_merged_output_covers_every_run_it_merged(tmp_path):
    """The grader change this stage needs. QSIPrep concatenates DWI scans sharing
    a warped space before head-motion correction, dropping the entity that
    distinguished them — so two ``dir-`` inputs become one output. Superset
    semantics (``expected <= found``) is right for every other duckbrain stage
    because all of them are one-output-per-input; here it is false *forever*, and
    a completely successful run would grade PARTIAL, which ``stage_runnable``
    reads as "not done" and the cockpit answers by inviting a re-run that produces
    exactly the same result."""
    config = _project(tmp_path)
    _finished(tmp_path, "sub-01_ses-01_space-ACPC_desc-preproc_dwi.nii.gz")
    assert _survey(config) == Status.COMPLETE.value


def test_a_contradicting_entity_covers_nothing(tmp_path):
    """Coarser is covered, *different* is not: an output claiming ``dir-AP``
    cannot stand in for a ``dir-PA`` run. Without that half the widening would
    accept any output at all for any input."""
    config = _project(tmp_path)
    _finished(tmp_path, "sub-01_ses-01_dir-AP_space-ACPC_desc-preproc_dwi.nii.gz")
    assert _survey(config) == Status.PARTIAL.value


def test_an_unmerged_run_per_input_still_grades_complete(tmp_path):
    """Exact identity is the special case of the widening, not a separate path —
    ``--separate-all-dwis``, or an acquisition QSIPrep declines to merge, must
    grade the same as a merged one."""
    config = _project(tmp_path)
    _finished(
        tmp_path,
        "sub-01_ses-01_dir-AP_run-1_space-ACPC_desc-preproc_dwi.nii.gz",
        "sub-01_ses-01_dir-PA_run-1_space-ACPC_desc-preproc_dwi.nii.gz",
    )
    assert _survey(config) == Status.COMPLETE.value


def test_images_without_the_report_are_still_partial(tmp_path):
    """The images land while the workflow is still running. The report is the
    only per-unit artifact QSIPrep writes at the end, so it is what separates
    "finished" from "got most of the way"."""
    config = _project(tmp_path)
    _finished(tmp_path, "sub-01_ses-01_space-ACPC_desc-preproc_dwi.nii.gz", report=False)
    assert _survey(config) == Status.PARTIAL.value


def test_a_started_run_with_nothing_written_is_partial_not_missing(tmp_path):
    config = _project(tmp_path)
    (tmp_path / "derivatives" / "qsiprep" / "sub-01" / "ses-01").mkdir(parents=True)
    assert _survey(config) == Status.PARTIAL.value


def test_no_derivative_at_all_is_missing(tmp_path):
    assert _survey(_project(tmp_path)) == Status.MISSING.value


# ---- NA is per-unit data here, not a project-level config question ----------


def test_a_session_without_diffusion_grades_na(tmp_path):
    """Different in shape from NORDIC's NA, which is a project-level toggle:
    one session can have diffusion and the next not — which is exactly what
    mmmdata looks like, 6 diffusion sessions out of 88. Graded MISSING instead,
    those 82 rows present permanent unfinished work: the rollup reads 6/88, the
    cockpit offers a one-click "run all", and "every stage complete" is
    unreachable (``#17.4``'s lesson)."""
    config = _project(tmp_path)
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    assert _survey(config, session="02") == Status.NA.value


def test_an_na_unit_is_never_runnable(tmp_path):
    """The half that matters: NA has to reach ``stage_runnable`` as "nothing to
    do at all", or the board still offers the button."""
    from duckbrain.core.pipeline import stage_runnable

    config = _project(tmp_path)
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    matrix = survey_project(config)
    row = matrix[matrix["session"] == "02"].iloc[0]
    assert not stage_runnable(row, "qsiprep", config)


# ---- the n/N beside a partial cell -----------------------------------------


def test_run_progress_counts_through_the_merge(tmp_path):
    """A PARTIAL cell with no number is its own silent degrade. Counted by
    identity instead of coverage it would read ``0/2`` beside a COMPLETE cell for
    a perfectly merged run — the grade and the count must not be able to
    disagree."""
    config = _project(tmp_path)
    _finished(tmp_path, "sub-01_ses-01_space-ACPC_desc-preproc_dwi.nii.gz")
    assert run_progress(config, "qsiprep", "01", "01") == (2, 2)


def test_run_progress_is_none_where_there_is_no_diffusion(tmp_path):
    config = _project(tmp_path)
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    assert run_progress(config, "qsiprep", "01", "02") is None


# ---- provenance -------------------------------------------------------------


def test_the_launch_records_qsiprep_and_its_pinned_version(tmp_path):
    """The submission log is the only provenance channel for a tool-produced
    derivative (``core/consistency.py``'s module docstring), so the stage has to
    appear in ``_STAGE_TOOL`` or every QSIPrep run is anonymous."""
    from duckbrain.core.pipeline import run_provenance

    prov = run_provenance(_project(tmp_path), "qsiprep")
    assert prov["tool"] == "qsiprep"
    assert prov["tool_version"] == "26.0.0"
    assert prov["runtime"] == "qsiprep-26.0.0.sif"
    # Raw BIDS, always: unlike fMRIPrep there is no NORDIC-denoised variant to
    # route through — NORDIC denoises BOLD.
    assert prov["input_variant"] == "raw"


def test_the_project_section_reaches_the_template_context(tmp_path):
    """``build_context`` carries a hardcoded list of config sub-dicts, so a new
    ``[qsiprep]`` section is invisible to templates until it is added there."""
    ctx = build_context(_project(tmp_path), "qsiprep", subject="01", session="01")
    assert ctx["qsiprep"]["output_resolution"] == 2.0


def test_the_template_renders_from_the_context_alone(tmp_path):
    """StrictUndefined means a missing context key raises at render rather than
    emitting an empty flag — this is the smoke test that the builder supplies
    every name the template reads."""
    config = _project(tmp_path)
    ctx = build_context(
        config,
        "qsiprep",
        subject="01",
        session="01",
        bids_dir=str(tmp_path),
        output_dir=str(tmp_path / "derivatives" / "qsiprep"),
        container_path="/x.sif",
        fs_license="/l/license.txt",
        fs_license_dir="/l",
        output_resolution=2.0,
        anatomical_reference=SESSIONWISE,
        mem_gb=40,
    )
    assert "QSIPrep" in render_sbatch("qsiprep", ctx)
