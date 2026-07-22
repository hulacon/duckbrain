"""Project surveyor — completion (not mere presence) across pipeline stages.

The trees below are minimal fakes of a duckbrain project; the point of each test
is that a *crashed / half-finished* stage grades PARTIAL, a finished one COMPLETE,
and that both sessionless and multi-session layouts are handled by the same
tracker globs.
"""

from duckbrain.core.surveyor import (
    STAGES,
    Status,
    discover_units,
    summarize,
    survey_project,
)


def _paths(root):
    return {
        "bids_dir": str(root),
        "sourcedata_dir": str(root / "sourcedata"),
        "derivatives_dir": str(root / "derivatives"),
    }


def _config(root, use_nordic=False):
    """A loaded-config stand-in. NORDIC is opt-in per project, so the surveyor
    grades it n/a unless a project asks for it — the nordic tracker tests below
    turn it on to exercise the tracker itself."""
    return {"paths": _paths(root), "nordic": {"use_nordic": use_nordic}}


def _nordic_config(root):
    return _config(root, use_nordic=True)


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---- discovery --------------------------------------------------------------

def test_discover_units_unions_sourcedata_and_bids(tmp_path):
    (tmp_path / "sourcedata" / "sub-01" / "dicom").mkdir(parents=True)
    (tmp_path / "sub-02" / "anat").mkdir(parents=True)  # BIDS-only, never ingested
    units = discover_units(_paths(tmp_path))
    assert ("01", "") in units
    assert ("02", "") in units


def test_discover_units_multisession(tmp_path):
    for ses in ("ses-01", "ses-02"):
        (tmp_path / "sub-01" / ses / "anat").mkdir(parents=True)
    units = discover_units(_paths(tmp_path))
    assert units == [("01", "01"), ("01", "02")]


# ---- ingested ---------------------------------------------------------------

def test_ingested_complete_when_dicom_nonempty(tmp_path):
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "ingested"] == Status.COMPLETE


def test_ingested_missing_when_dicom_empty(tmp_path):
    (tmp_path / "sourcedata" / "sub-01" / "dicom").mkdir(parents=True)
    df = survey_project(_config(tmp_path))
    row = df[df.subject == "01"].iloc[0]
    assert row["ingested"] == Status.MISSING


# ---- converted --------------------------------------------------------------

def test_converted_complete_with_nifti(tmp_path):
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "converted"] == Status.COMPLETE


def test_converted_partial_when_tmp_scratch_but_no_nifti(tmp_path):
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sourcedata" / "tmp_dcm2bids" / "sub-01" / "junk.json")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "converted"] == Status.PARTIAL


# ---- fmriprep: the core presence-vs-completion case -------------------------

def _bids_anat_func(root, sub="01", ses=""):
    ss = f"sub-{sub}" + (f"/ses-{ses}" if ses else "")
    tok = f"sub-{sub}" + (f"_ses-{ses}" if ses else "")
    _touch(root / ss / "anat" / f"{tok}_T1w.nii.gz")
    _touch(root / ss / "func" / f"{tok}_task-rest_bold.nii.gz")


def test_fmriprep_complete(tmp_path):
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-preproc_bold.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.COMPLETE


def test_fmriprep_partial_when_func_missing(tmp_path):
    # Report + anat present but func never finished — a crashed run that presence
    # checks would call "done". This is the whole reason the surveyor exists.
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.PARTIAL


def test_fmriprep_partial_when_dir_but_no_report(tmp_path):
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")  # no .html
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.PARTIAL


def test_fmriprep_missing_when_no_derivative(tmp_path):
    _bids_anat_func(tmp_path)
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.MISSING


def test_fmriprep_anat_only_complete_without_func(tmp_path):
    # BIDS has no func for this subject → func output not required.
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.COMPLETE


def test_fmriprep_sessionless_and_multisession_same_tracker(tmp_path):
    # Multi-session: func output nests under ses-01; the sessionless glob token
    # must still match via wildcards (the Nipoppy prototype's ses- bug).
    _bids_anat_func(tmp_path, ses="01")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_desc-preproc_T1w.nii.gz")
    _touch(fp / "sub-01" / "ses-01" / "func" / "sub-01_ses-01_task-rest_desc-preproc_bold.nii.gz")
    df = survey_project(_config(tmp_path))
    row = df[df.session == "01"].iloc[0]
    assert row["fmriprep"] == Status.COMPLETE


# ---- mriqc ------------------------------------------------------------------

def test_mriqc_complete_with_iqm_json(tmp_path):
    # Anat-only subject (no func in BIDS): the anat IQM json alone is complete.
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "anat" / "sub-01_T1w.json", content='{"cnr": 1}')
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.COMPLETE


def test_mriqc_partial_when_func_iqm_missing(tmp_path):
    # Regression (2026-07-10): func synthstrip OOM-killed after the anat json
    # landed. BIDS has func, so an anat-only MRIQC output is a crashed/partial
    # run, not complete.
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "anat" / "sub-01_T1w.json", content='{"cnr": 1}')
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.PARTIAL


def test_mriqc_complete_with_anat_and_func_iqm(tmp_path):
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "anat" / "sub-01_T1w.json", content='{"cnr": 1}')
    _touch(mq / "sub-01" / "func" / "sub-01_task-x_bold.json", content='{"fd": 1}')
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.COMPLETE


def test_mriqc_missing(tmp_path):
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.MISSING


# ---- nordic -----------------------------------------------------------------

def test_nordic_complete_with_denoised_bold(tmp_path):
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    nd = tmp_path / "derivatives" / "nordic" / "sub-01" / "func"
    _touch(nd / "sub-01_task-x_bold.nii.gz")
    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.COMPLETE


def test_nordic_partial_when_dir_but_no_denoised_bold(tmp_path):
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    # NORDIC output dir exists but the denoised bold never landed → crashed/partial.
    (tmp_path / "derivatives" / "nordic" / "sub-01" / "func").mkdir(parents=True)
    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.PARTIAL


def test_nordic_missing_when_no_derivative(tmp_path):
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.MISSING


def test_nordic_sessionless_and_multisession_same_tracker(tmp_path):
    # Sessionless output (nordic.py hardcodes an empty ses- dir for these).
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    _touch(tmp_path / "derivatives" / "nordic" / "sub-01" / "ses-" / "func" / "sub-01_task-x_bold.nii.gz")
    # Multi-session output.
    _touch(tmp_path / "sub-02" / "ses-01" / "func" / "sub-02_ses-01_task-x_bold.nii.gz")
    _touch(tmp_path / "derivatives" / "nordic" / "sub-02" / "ses-01" / "func" / "sub-02_ses-01_task-x_bold.nii.gz")
    df = survey_project(_nordic_config(tmp_path))
    assert df.set_index("subject").loc["01", "nordic"] == Status.COMPLETE
    assert df.set_index("subject").loc["02", "nordic"] == Status.COMPLETE


# ---- matrix + summary -------------------------------------------------------

def test_survey_columns_and_empty_project(tmp_path):
    (tmp_path / "sourcedata").mkdir()
    df = survey_project(_config(tmp_path))
    assert list(df.columns) == ["subject", "session", *STAGES]
    assert len(df) == 0


def test_summarize_counts(tmp_path):
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sourcedata" / "sub-02" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")  # sub-01 converted
    df = survey_project(_config(tmp_path))
    summary = summarize(df)
    assert summary["ingested"][Status.COMPLETE.value] == 2
    assert summary["converted"][Status.COMPLETE.value] == 1
    assert summary["converted"][Status.MISSING.value] == 1


# ---- TODO #17.4: a stage that doesn't apply is n/a, not unfinished ------------

def test_nordic_is_na_without_use_nordic(tmp_path):
    """NORDIC is opt-in. Grading it MISSING made every non-NORDIC project look
    like it had N units of outstanding work, and offered a one-click bulk run
    for a derivative fMRIPrep would never read."""
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.NA


def test_na_unit_is_not_runnable_and_counts_as_done(tmp_path):
    from duckbrain.core.pipeline import stage_runnable

    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")   # converted
    config = _config(tmp_path)
    row = survey_project(config).loc[0]

    assert row["nordic"] == Status.NA
    assert not stage_runnable(row, "nordic", config)
    # ...and with use_nordic on, the same unit IS runnable — the gate is the
    # project setting, not a blanket refusal.
    on = _nordic_config(tmp_path)
    assert stage_runnable(survey_project(on).loc[0], "nordic", on)


# ---- DB-002: completion counts runs, it doesn't just find one ----------------
#
# Every tracker graded COMPLETE off a single wildcard match, so a unit with four
# BOLD runs where one succeeded read green at every stage — and green unlocks
# downstream work (`stage_runnable`) and suppresses a real sacct failure
# (`survey_live`), so the wrong answer propagated instead of merely displaying.

def _seed_bold_runs(root, ss, n, task="rest"):
    """*n* raw BOLD runs (+ the anat every stage keys off) for one unit.

    Filenames carry the full entity prefix (``sub-01_ses-01_…``), because that is
    what BIDS requires and what the derivative filenames these are compared
    against will have.
    """
    prefix = "_".join(ss.split("/"))
    _touch(root / ss / "anat" / f"{prefix}_T1w.nii.gz")
    for i in range(1, n + 1):
        _touch(root / ss / "func" / f"{prefix}_task-{task}_run-{i}_bold.nii.gz")


def test_entity_key_strips_derivative_entities():
    """Two representations of one acquisition must key the same, or every
    output space would read as a separate missing run."""
    from duckbrain.core.surveyor import _entity_key

    raw = _entity_key("sub-01_ses-02_task-rest_run-1_bold.nii.gz")
    assert raw == "sub-01_ses-02_task-rest_run-1"
    assert _entity_key(
        "sub-01_ses-02_task-rest_run-1_space-MNI152NLin2009cAsym_res-2"
        "_desc-preproc_bold.nii.gz"
    ) == raw
    # ...and two genuinely different runs must not collapse.
    assert _entity_key("sub-01_task-rest_run-2_bold.nii.gz") != raw


def test_nordic_partial_when_only_some_runs_denoised(tmp_path):
    """The headline case. NORDIC denoises one BOLD per array task and skips any
    run whose output exists, so a partial array is the expected failure — and it
    graded COMPLETE off the one run that landed."""
    _seed_bold_runs(tmp_path, "sub-01", 4)
    _touch(tmp_path / "derivatives" / "nordic" / "sub-01" / "func"
           / "sub-01_task-rest_run-1_bold.nii.gz")

    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.PARTIAL


def test_nordic_complete_when_every_run_denoised(tmp_path):
    _seed_bold_runs(tmp_path, "sub-01", 4)
    for i in range(1, 5):
        _touch(tmp_path / "derivatives" / "nordic" / "sub-01" / "func"
               / f"sub-01_task-rest_run-{i}_bold.nii.gz")

    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.COMPLETE


def test_fmriprep_partial_when_one_run_is_missing(tmp_path):
    _seed_bold_runs(tmp_path, "sub-01", 3)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    for i in (1, 2):
        _touch(fp / "sub-01" / "func"
               / f"sub-01_task-rest_run-{i}_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.PARTIAL


def test_fmriprep_complete_with_several_output_spaces_per_run(tmp_path):
    """Superset, not equality: more outputs than expected is still finished."""
    _seed_bold_runs(tmp_path, "sub-01", 2)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    for i in (1, 2):
        for space in ("MNI152NLin2009cAsym_res-2", "fsaverage6", "func"):
            _touch(fp / "sub-01" / "func"
                   / f"sub-01_task-rest_run-{i}_space-{space}_desc-preproc_bold.nii.gz")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.COMPLETE


def test_fmriprep_expectation_follows_the_nordic_tree(tmp_path):
    """With use_nordic, fMRIPrep reads the assembled tree — grade it on that.

    Expecting runs NORDIC never produced would pin fMRIPrep at PARTIAL forever
    for work it was never given. The shortfall still surfaces once, at NORDIC.
    """
    _seed_bold_runs(tmp_path, "sub-01", 4)          # raw has 4
    nordic = tmp_path / "derivatives" / "nordic"
    for i in (1, 2, 3):                              # NORDIC produced 3
        _touch(nordic / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_bold.nii.gz")
        _touch(nordic / "bids_format" / "sub-01" / "func"
               / f"sub-01_task-rest_run-{i}_bold.nii.gz")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    for i in (1, 2, 3):                              # ...and fMRIPrep did all 3
        _touch(fp / "sub-01" / "func"
               / f"sub-01_task-rest_run-{i}_desc-preproc_bold.nii.gz")

    row = survey_project(_nordic_config(tmp_path)).loc[0]
    assert row["fmriprep"] == Status.COMPLETE
    assert row["nordic"] == Status.PARTIAL   # reported once, where it happened


def test_fmriprep_anat_only_unit_needs_no_func(tmp_path):
    """An empty expected set is no requirement, not an unmet one."""
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.COMPLETE


def test_mriqc_partial_when_one_runs_iqm_is_missing(tmp_path):
    """The 2026-07-10 OOM, one granularity down: the func node died after two
    of three jsons had landed."""
    _seed_bold_runs(tmp_path, "sub-01", 3)
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01_T1w.json")
    for i in (1, 2):
        _touch(mq / f"sub-01_task-rest_run-{i}_bold.json")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.PARTIAL


def test_mriqc_complete_in_the_nested_layout(tmp_path):
    _seed_bold_runs(tmp_path, "sub-01/ses-01", 2)
    mq = tmp_path / "derivatives" / "mriqc" / "sub-01" / "ses-01"
    _touch(mq / "anat" / "sub-01_ses-01_T1w.json")
    for i in (1, 2):
        _touch(mq / "func" / f"sub-01_ses-01_task-rest_run-{i}_bold.json")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.COMPLETE


def _write_dcm2bids_config(root, ss, n_bold, n_anat=1):
    import json

    descriptions = [{"datatype": "anat", "suffix": "T1w"} for _ in range(n_anat)]
    descriptions += [{"datatype": "func", "suffix": "bold"} for _ in range(n_bold)]
    path = root / "sourcedata" / ss / "dcm2bids_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"descriptions": descriptions}))


def test_converted_partial_when_fewer_niftis_than_the_reviewed_config(tmp_path):
    _write_dcm2bids_config(tmp_path, "sub-01", n_bold=4)
    _seed_bold_runs(tmp_path, "sub-01", 2)   # only 2 of the 4 landed

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "converted"] == Status.PARTIAL


def test_converted_complete_when_every_description_produced_a_file(tmp_path):
    _write_dcm2bids_config(tmp_path, "sub-01", n_bold=3)
    _seed_bold_runs(tmp_path, "sub-01", 3)

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "converted"] == Status.COMPLETE


def test_converted_falls_back_to_presence_without_a_reviewed_config(tmp_path):
    """External BIDS duckbrain never converted. Presence is the only honest
    claim; grading it PARTIAL would be a worse lie than the old rule."""
    _seed_bold_runs(tmp_path, "sub-01", 2)

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "converted"] == Status.COMPLETE


def test_run_progress_counts_what_the_status_says(tmp_path):
    """The number in a partial cell must come from the same comparison as its
    colour, or the cell and its explanation drift apart."""
    from duckbrain.core.surveyor import run_progress

    _seed_bold_runs(tmp_path, "sub-01", 4)
    for i in (1, 2):
        _touch(tmp_path / "derivatives" / "nordic" / "sub-01" / "func"
               / f"sub-01_task-rest_run-{i}_bold.nii.gz")

    config = _nordic_config(tmp_path)
    assert survey_project(config).loc[0, "nordic"] == Status.PARTIAL
    assert run_progress(config, "nordic", "01", "") == (2, 4)
    # Stages without a per-run correspondence have no number to give.
    assert run_progress(config, "converted", "01", "") is None
