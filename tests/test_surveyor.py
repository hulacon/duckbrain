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
    fmriprep_variants,
    stage_columns,
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
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-confounds_timeseries.tsv")
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


def test_fmriprep_complete_with_split_session_reports(tmp_path):
    """`--aggregate-session-reports` (default 4) splits the report once a subject
    exceeds that many sessions: fMRIPrep writes `sub-XX_anat.html` + per-session
    func reports and no combined `sub-XX.html`. Requiring the combined name alone
    graded mmmdata's 29-session raw arm PARTIAL on a *full* run count."""
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01_anat.html")  # no sub-01.html — the split shape
    _touch(fp / "sub-01_ses-01_func.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-preproc_bold.nii.gz")
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-confounds_timeseries.tsv")
    assert survey_project(_config(tmp_path)).loc[0, "fmriprep"] == Status.COMPLETE


def test_fmriprep_partial_when_neither_report_shape_is_present(tmp_path):
    """Widening to two report shapes must not widen to none: an anat image with
    no report at all is still an unfinished workflow."""
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-preproc_bold.nii.gz")
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-confounds_timeseries.tsv")
    assert survey_project(_config(tmp_path)).loc[0, "fmriprep"] == Status.PARTIAL


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
    _touch(
        fp / "sub-01" / "ses-01" / "func" / "sub-01_ses-01_task-rest_desc-confounds_timeseries.tsv"
    )
    df = survey_project(_config(tmp_path))
    row = df[df.session == "01"].iloc[0]
    assert row["fmriprep"] == Status.COMPLETE


def test_fmriprep_complete_when_anat_lives_in_another_session(tmp_path):
    # Longitudinal shape: the anatomical is acquired in ses-01 and shared, so
    # fMRIPrep writes it to sub-01/ses-01/anat/ and ses-02 has func output only.
    # A session-scoped anat glob pinned ses-02 at PARTIAL with nothing missing.
    _bids_anat_func(tmp_path, ses="01")
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_desc-preproc_T1w.nii.gz")
    _touch(fp / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_desc-preproc_bold.nii.gz")
    _touch(
        fp / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_desc-confounds_timeseries.tsv"
    )
    df = survey_project(_config(tmp_path))
    assert df[df.session == "02"].iloc[0]["fmriprep"] == Status.COMPLETE


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
    _touch(
        tmp_path
        / "derivatives"
        / "nordic"
        / "sub-01"
        / "ses-"
        / "func"
        / "sub-01_task-x_bold.nii.gz"
    )
    # Multi-session output.
    _touch(tmp_path / "sub-02" / "ses-01" / "func" / "sub-02_ses-01_task-x_bold.nii.gz")
    _touch(
        tmp_path
        / "derivatives"
        / "nordic"
        / "sub-02"
        / "ses-01"
        / "func"
        / "sub-02_ses-01_task-x_bold.nii.gz"
    )
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
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")  # converted
    config = _config(tmp_path)
    row = survey_project(config).loc[0]

    assert row["nordic"] == Status.NA
    assert not stage_runnable(row, "nordic", config)
    # ...and with use_nordic on, the same unit IS runnable — the gate is the
    # project setting, not a blanket refusal.
    on = _nordic_config(tmp_path)
    assert stage_runnable(survey_project(on).loc[0], "nordic", on)


# ---- TODO #41.2: an external-BIDS project doesn't ingest, ever ---------------


def _external_config(root):
    cfg = _config(root)
    cfg["project"] = {"external_bids": True}
    return cfg


def test_ingested_is_na_for_an_external_bids_project(tmp_path):
    """#17.4's failure mode, second instance: a declared-external project has no
    DICOMs to ingest, so grading `ingested` MISSING read "Ingested 0/N" forever,
    matched every row to the only-unfinished filter, and made all-complete
    unreachable."""
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    df = survey_project(_external_config(tmp_path))
    assert df.loc[0, "ingested"] == Status.NA
    # `converted` deliberately keeps grading (presence-as-COMPLETE): downstream
    # stages gate on it via stage_runnable's dependency check.
    assert df.loc[0, "converted"] == Status.COMPLETE


def test_external_project_downstream_stays_runnable(tmp_path):
    from duckbrain.core.pipeline import stage_runnable

    _bids_anat_func(tmp_path)
    config = _external_config(tmp_path)
    row = survey_project(config).loc[0]
    assert row["ingested"] == Status.NA
    assert stage_runnable(row, "fmriprep", config)
    assert stage_runnable(row, "mriqc", config)


def test_undeclared_project_still_bills_ingestion(tmp_path):
    """The flag is the only signal — an empty sourcedata alone must not flip a
    project to external, because it is equally true of one that hasn't started."""
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "ingested"] == Status.MISSING


# ---- TODO #41.4: uncompressed NIfTI is data too ------------------------------


def test_converted_sees_uncompressed_nifti(tmp_path):
    """A bare-.nii tree (heudiconv/dcm2niix commonly emit uncompressed) graded
    MISSING with a .nii.gz-only glob, gating every downstream stage off."""
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii")
    df = survey_project(_external_config(tmp_path))
    assert df.loc[0, "converted"] == Status.COMPLETE


def test_uncompressed_bold_counts_as_an_expected_run(tmp_path):
    """get_bold_runs is the run-count source of truth, so `.nii` support there
    reaches the surveyor: an fMRIPrep tree missing the run's output grades
    PARTIAL rather than the run being invisible."""
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii")
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-rest_bold.nii")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    df = survey_project(_external_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.PARTIAL


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
    assert (
        _entity_key(
            "sub-01_ses-02_task-rest_run-1_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        == raw
    )
    # ...and two genuinely different runs must not collapse.
    assert _entity_key("sub-01_task-rest_run-2_bold.nii.gz") != raw


def test_nordic_partial_when_only_some_runs_denoised(tmp_path):
    """The headline case. NORDIC denoises one BOLD per array task and skips any
    run whose output exists, so a partial array is the expected failure — and it
    graded COMPLETE off the one run that landed."""
    _seed_bold_runs(tmp_path, "sub-01", 4)
    _touch(
        tmp_path
        / "derivatives"
        / "nordic"
        / "sub-01"
        / "func"
        / "sub-01_task-rest_run-1_bold.nii.gz"
    )

    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.PARTIAL


def test_nordic_complete_when_every_run_denoised(tmp_path):
    _seed_bold_runs(tmp_path, "sub-01", 4)
    for i in range(1, 5):
        _touch(
            tmp_path
            / "derivatives"
            / "nordic"
            / "sub-01"
            / "func"
            / f"sub-01_task-rest_run-{i}_bold.nii.gz"
        )

    df = survey_project(_nordic_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.COMPLETE


def test_fmriprep_partial_when_one_run_is_missing(tmp_path):
    _seed_bold_runs(tmp_path, "sub-01", 3)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    for i in (1, 2):
        _touch(
            fp
            / "sub-01"
            / "func"
            / f"sub-01_task-rest_run-{i}_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
        )

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
            _touch(
                fp
                / "sub-01"
                / "func"
                / f"sub-01_task-rest_run-{i}_space-{space}_desc-preproc_bold.nii.gz"
            )
        # One confounds file per run, whatever the number of spaces — fMRIPrep
        # writes it once, in no space at all.
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-confounds_timeseries.tsv")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.COMPLETE


def test_fmriprep_expectation_follows_the_nordic_tree(tmp_path):
    """With use_nordic, fMRIPrep reads the assembled tree — grade it on that.

    Expecting runs NORDIC never produced would pin fMRIPrep at PARTIAL forever
    for work it was never given. The shortfall still surfaces once, at NORDIC.
    """
    _seed_bold_runs(tmp_path, "sub-01", 4)  # raw has 4
    nordic = tmp_path / "derivatives" / "nordic"
    for i in (1, 2, 3):  # NORDIC produced 3
        _touch(nordic / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_bold.nii.gz")
        _touch(nordic / "bids_format" / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_bold.nii.gz")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    for i in (1, 2, 3):  # ...and fMRIPrep did all 3
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-preproc_bold.nii.gz")
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-confounds_timeseries.tsv")

    row = survey_project(_nordic_config(tmp_path)).loc[0]
    assert row["fmriprep"] == Status.COMPLETE
    assert row["nordic"] == Status.PARTIAL  # reported once, where it happened


def test_fmriprep_anat_only_unit_needs_no_func(tmp_path):
    """An empty expected set is no requirement, not an unmet one.

    Untouched by the confounds requirement by construction, and that is the
    property keeping it from breaking longitudinal anat reuse: a unit with no
    BOLD owes no confounds either.
    """
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "fmriprep"] == Status.COMPLETE


def _fmriprep_anat(root, sub="01"):
    """The subject-level markers, so only the func requirement is under test."""
    fp = root / "derivatives" / "fmriprep"
    _touch(fp / f"sub-{sub}.html")
    _touch(fp / f"sub-{sub}" / "anat" / f"sub-{sub}_desc-preproc_T1w.nii.gz")
    return fp


def test_fmriprep_with_preproc_bold_but_no_confounds_is_partial(tmp_path):
    """The hole this closes, at the shape `divatten_beta_v2` produced.

    Preprocessed images for every run and not one confounds TSV: the board read
    COMPLETE while the QC dashboard had no fMRIPrep input at all and said
    nothing about why.
    """
    _seed_bold_runs(tmp_path, "sub-01", 3)
    fp = _fmriprep_anat(tmp_path)
    for i in (1, 2, 3):
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-preproc_bold.nii.gz")

    assert survey_project(_config(tmp_path)).loc[0, "fmriprep"] == Status.PARTIAL


def test_fmriprep_with_confounds_but_no_preproc_bold_is_partial(tmp_path):
    """The other half of the intersection: either file alone is half a run."""
    _seed_bold_runs(tmp_path, "sub-01", 3)
    fp = _fmriprep_anat(tmp_path)
    for i in (1, 2, 3):
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-confounds_timeseries.tsv")

    assert survey_project(_config(tmp_path)).loc[0, "fmriprep"] == Status.PARTIAL


def test_fmriprep_confounds_for_only_some_runs_is_partial(tmp_path):
    """Per run, not per subject — the granularity the rest of DB-002 is at."""
    _seed_bold_runs(tmp_path, "sub-01", 3)
    fp = _fmriprep_anat(tmp_path)
    for i in (1, 2, 3):
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-preproc_bold.nii.gz")
    for i in (1, 2):
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-confounds_timeseries.tsv")

    assert survey_project(_config(tmp_path)).loc[0, "fmriprep"] == Status.PARTIAL


def test_an_empty_confounds_file_does_not_count(tmp_path):
    """A truncated write is not an output; `_found_keys` requires a size."""
    _seed_bold_runs(tmp_path, "sub-01", 1)
    fp = _fmriprep_anat(tmp_path)
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_run-1_desc-preproc_bold.nii.gz")
    (fp / "sub-01" / "func" / "sub-01_task-rest_run-1_desc-confounds_timeseries.tsv").write_text("")

    assert survey_project(_config(tmp_path)).loc[0, "fmriprep"] == Status.PARTIAL


def test_a_confounds_tsv_keys_to_the_same_run_as_its_bold(tmp_path):
    """The fact the whole confounds requirement rests on.

    If `_entity_key` split these two apart, every run would look like two runs
    and no unit could ever grade complete.
    """
    from duckbrain.core.surveyor import _entity_key

    assert _entity_key("sub-01_task-rest_run-1_desc-confounds_timeseries.tsv") == _entity_key(
        "sub-01_task-rest_run-1_bold.nii.gz"
    )


def test_run_progress_counts_a_run_with_no_confounds_as_unfinished(tmp_path):
    """The number and the colour come from one comparison, so both must move."""
    from duckbrain.core.surveyor import run_progress

    _seed_bold_runs(tmp_path, "sub-01", 3)
    fp = _fmriprep_anat(tmp_path)
    for i in (1, 2, 3):
        _touch(fp / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_desc-preproc_bold.nii.gz")

    config = _config(tmp_path)
    assert survey_project(config).loc[0, "fmriprep"] == Status.PARTIAL
    assert run_progress(config, "fmriprep", "01", "") == (0, 3)


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


# ---- mriqc, longitudinal: the expectation is the session's own images --------
#
# The mmmduck beta report (2026-08-11): anat acquired once in ses-01, every
# later session func-only. The tracker required a session-scoped T1w json
# unconditionally, so each fully-QC'd func session sat at PARTIAL forever —
# beside a run counter reading 9/9, because the counter only counted BOLDs.
# MRIQC rates each image where it lies (no cross-session anat merge as in
# fMRIPrep), so the fix is to expect only what the session's BIDS tree holds.


def test_mriqc_key_keeps_the_suffix_and_rejects_unrated_files():
    """A T1w and a T2w differ only in suffix, so the suffix must be part of the
    key — and MRIQC's non-IQM jsons (``_timeseries``) must not count as found."""
    from duckbrain.core.surveyor import _mriqc_key

    assert _mriqc_key("sub-01_run-1_T1w.json") == "sub-01_run-1:T1w"
    assert _mriqc_key("sub-01_run-1_T2w.json") == "sub-01_run-1:T2w"
    assert _mriqc_key("sub-01_task-rest_bold.nii.gz") == "sub-01_task-rest:bold"
    assert _mriqc_key("sub-01_task-rest_timeseries.json") is None
    assert _mriqc_key("sub-01_inv-1_MP2RAGE.nii.gz") is None


def test_mriqc_complete_when_anat_lives_in_another_session(tmp_path):
    """The headline mmmduck case: a func-only session with every bold json
    present owes no anat json and grades COMPLETE."""
    _seed_bold_runs(tmp_path, "sub-01/ses-01", 1)
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T1w.json")
    _touch(mq / "sub-01" / "ses-01" / "func" / "sub-01_ses-01_task-rest_run-1_bold.json")
    _touch(mq / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.json")

    df = survey_project(_config(tmp_path))
    assert df[df.session == "02"].iloc[0]["mriqc"] == Status.COMPLETE


def test_mriqc_missing_when_only_a_sibling_session_has_output(tmp_path):
    """The other half of the mmmduck report: a subject-scoped flat glob made a
    never-ran session read PARTIAL once its subject had any output at all, so
    'never ran' and 'mis-graded' were the same colour and the rollup could
    explain neither."""
    _seed_bold_runs(tmp_path, "sub-01/ses-01", 1)
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T1w.json")
    _touch(mq / "sub-01" / "ses-01" / "func" / "sub-01_ses-01_task-rest_run-1_bold.json")

    df = survey_project(_config(tmp_path))
    assert df[df.session == "02"].iloc[0]["mriqc"] == Status.MISSING


def test_mriqc_flat_layout_does_not_credit_a_sibling_sessions_jsons(tmp_path):
    """Same property in the flat layout, where only the filename prefix scopes a
    json to its session."""
    _seed_bold_runs(tmp_path, "sub-01/ses-01", 1)
    _touch(tmp_path / "sub-01" / "ses-02" / "func" / "sub-01_ses-02_task-rest_bold.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01_ses-01_T1w.json")
    _touch(mq / "sub-01_ses-01_task-rest_run-1_bold.json")

    df = survey_project(_config(tmp_path))
    assert df[df.session == "01"].iloc[0]["mriqc"] == Status.COMPLETE
    assert df[df.session == "02"].iloc[0]["mriqc"] == Status.MISSING


def test_a_listing_keeps_the_names_it_cannot_type(tmp_path, monkeypatch):
    """An entry whose type can't be read must not empty the whole listing.

    `_flat_listing` asks each entry whether it is a directory — a stat, which
    can fail on an entry the caller has no permission to follow. Letting that
    reach the loop's own handler would return an empty listing for the root:
    indistinguishable from "MRIQC has written nothing here", so every unit
    would grade MISSING because one sibling was unreadable. The name is still
    good even when the type is not, and the names are what the flat layout is
    matched on.
    """
    import duckbrain.core.surveyor as S

    mq = tmp_path / "derivatives" / "mriqc"
    _seed_bold_runs(tmp_path, "sub-01/ses-01", 1)
    _touch(tmp_path / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T1w.nii.gz")
    _touch(mq / "sub-01_ses-01_T1w.json")
    _touch(mq / "sub-01_ses-01_task-rest_run-1_bold.json")

    class _Untypable:
        def __init__(self, name):
            self.name = name

        def is_dir(self):
            raise PermissionError(self.name)

    class _Blinded:
        def __init__(self, entries):
            self._entries = entries

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(self._entries)

    real = S.os.scandir

    def blinding(path):
        with real(path) as entries:
            names = [e.name for e in entries]
        if str(path) == str(mq):
            return _Blinded([_Untypable(n) for n in names])
        return real(path)

    S._FLAT_LISTINGS.clear()
    monkeypatch.setattr(S.os, "scandir", blinding)

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.COMPLETE


class TestFlatLayoutIsScannedOnce:
    """`#42.5`: MRIQC's flat layout puts every unit's files at the derivative
    root, so finding one unit's means matching a filename prefix — and
    ``root.glob("sub-01_ses-02_*.json")`` is a full scandir of that root every
    time. Twice per unit (the json search and the subtree probe), i.e. O(N²) in
    units: ~400 scans of a directory holding thousands of files, per survey, at
    100 subjects × 2 sessions, inside a fragment that refreshes every 30 s.
    """

    @staticmethod
    def _flat_project(tmp_path, n_subjects=4):
        mq = tmp_path / "derivatives" / "mriqc"
        for i in range(1, n_subjects + 1):
            sub = f"sub-{i:02d}"
            _seed_bold_runs(tmp_path, f"{sub}/ses-01", 1)
            _touch(tmp_path / sub / "ses-01" / "anat" / f"{sub}_ses-01_T1w.nii.gz")
            _touch(mq / f"{sub}_ses-01_T1w.json")
            _touch(mq / f"{sub}_ses-01_task-rest_run-1_bold.json")
        return mq

    def _count_scans(self, monkeypatch, root):
        import duckbrain.core.surveyor as S

        scans = []
        real = S.os.scandir

        def counting(path):
            if str(path) == str(root):
                scans.append(str(path))
            return real(path)

        monkeypatch.setattr(S.os, "scandir", counting)
        S._FLAT_LISTINGS.clear()
        return scans

    def test_the_root_is_listed_once_for_the_whole_survey(self, tmp_path, monkeypatch):
        mq = self._flat_project(tmp_path)
        scans = self._count_scans(monkeypatch, mq)

        df = survey_project(_config(tmp_path))

        assert (df["mriqc"] == Status.COMPLETE).all()
        assert len(scans) == 1, f"listed the flat root {len(scans)} times for 4 units"

    def _count_root_globs(self, monkeypatch, root):
        from pathlib import Path

        globs = []
        real = Path.glob

        def counting(self, pattern, *args, **kwargs):
            if str(self) == str(root):
                globs.append(pattern)
            return real(self, pattern, *args, **kwargs)

        monkeypatch.setattr(Path, "glob", counting)
        return globs

    def test_the_flat_root_is_never_globbed_at_all(self, tmp_path, monkeypatch):
        """The version-independent half of the assertion above.

        What a glob of the root *costs* is a pathlib implementation detail:
        3.11 resolved a literal leading component by statting the named child,
        3.12 removed that path and listed the parent like any other component,
        and 3.13 put a literal fast path back. So the sibling test's scan count
        was 1 on 3.11 and 9 on 3.12 for the same code — green for a reason that
        had nothing to do with the code being right, which is how two of the
        three scans survived `#42.5` unnoticed.

        Counting *calls* instead of scans holds on every version: the two
        remaining callers ask the cached listing which layout this root is, and
        a flat root's answer means neither of them globs it.
        """
        mq = self._flat_project(tmp_path)
        import duckbrain.core.surveyor as S

        S._FLAT_LISTINGS.clear()
        globs = self._count_root_globs(monkeypatch, mq)

        df = survey_project(_config(tmp_path))

        assert (df["mriqc"] == Status.COMPLETE).all()
        assert globs == [], f"globbed the flat root {len(globs)} times: {globs}"

    def test_a_json_written_after_the_listing_is_still_found(self, tmp_path, monkeypatch):
        """The cache is keyed on the directory's mtime, which POSIX moves when an
        entry appears — so the next survey re-lists rather than repeating the
        answer it gave before MRIQC finished."""
        mq = self._flat_project(tmp_path, n_subjects=1)
        _seed_bold_runs(tmp_path, "sub-02/ses-01", 1)
        _touch(tmp_path / "sub-02" / "ses-01" / "anat" / "sub-02_ses-01_T1w.nii.gz")
        self._count_scans(monkeypatch, mq)

        first = survey_project(_config(tmp_path))
        assert first[first.subject == "02"].iloc[0]["mriqc"] == Status.MISSING

        _touch(mq / "sub-02_ses-01_T1w.json")
        _touch(mq / "sub-02_ses-01_task-rest_run-1_bold.json")

        second = survey_project(_config(tmp_path))
        assert second[second.subject == "02"].iloc[0]["mriqc"] == Status.COMPLETE

    def test_a_json_created_empty_and_filled_later_is_found_when_it_is_filled(
        self, tmp_path, monkeypatch
    ):
        """MRIQC creates a json and then writes it, and filling a file does not
        move its directory's mtime. So the listing caches *names* only and every
        caller stats what it is about to believe in — the alternative caches
        "empty" and never revisits it."""
        mq = self._flat_project(tmp_path, n_subjects=1)
        _seed_bold_runs(tmp_path, "sub-02/ses-01", 1)
        self._count_scans(monkeypatch, mq)
        _touch(mq / "sub-02_ses-01_T1w.json")
        (mq / "sub-02_ses-01_task-rest_run-1_bold.json").write_text("")

        # PARTIAL: the T1w json counts, the empty bold json does not — an empty
        # file is not evidence a stage produced anything (`_is_evidence`). The
        # point here is what happens next, once it has content.
        first = survey_project(_config(tmp_path))
        assert first[first.subject == "02"].iloc[0]["mriqc"] == Status.PARTIAL

        (mq / "sub-02_ses-01_task-rest_run-1_bold.json").write_text("{}")

        second = survey_project(_config(tmp_path))
        assert second[second.subject == "02"].iloc[0]["mriqc"] == Status.COMPLETE


def test_mriqc_partial_when_anat_iqm_missing_in_an_anat_bearing_session(tmp_path):
    """The narrowed expectation must not un-catch the real failure the old anat
    requirement existed for: a session that *does* hold a T1w still owes its
    json, however finished its BOLDs look."""
    _seed_bold_runs(tmp_path, "sub-01", 1)
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "func" / "sub-01_task-rest_run-1_bold.json")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.PARTIAL


def test_mriqc_partial_when_a_t2w_iqm_is_missing(tmp_path):
    """MRIQC rates T2w as well, per image: a T1w json must not stand in for the
    T2w sharing its entities."""
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T2w.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "anat" / "sub-01_T1w.json")

    df = survey_project(_config(tmp_path))
    assert df.loc[0, "mriqc"] == Status.PARTIAL

    _touch(mq / "sub-01" / "anat" / "sub-01_T2w.json")
    assert survey_project(_config(tmp_path)).loc[0, "mriqc"] == Status.COMPLETE


def test_mriqc_run_progress_counts_every_rated_image(tmp_path):
    """The number beside the cell comes from the same comparison as its colour —
    bold-only counting is how 9/9 ended up beside PARTIAL."""
    from duckbrain.core.surveyor import run_progress

    _seed_bold_runs(tmp_path, "sub-01", 2)  # 2 BOLDs + the seeded T1w = 3 images
    mq = tmp_path / "derivatives" / "mriqc"
    for i in (1, 2):
        _touch(mq / "sub-01" / "func" / f"sub-01_task-rest_run-{i}_bold.json")

    config = _config(tmp_path)
    assert survey_project(config).loc[0, "mriqc"] == Status.PARTIAL
    assert run_progress(config, "mriqc", "01", "") == (2, 3)


def _write_dcm2bids_config(root, ss, n_bold, n_anat=1):
    import json

    descriptions = [{"datatype": "anat", "suffix": "T1w"} for _ in range(n_anat)]
    descriptions += [{"datatype": "func", "suffix": "bold"} for _ in range(n_bold)]
    path = root / "sourcedata" / ss / "dcm2bids_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"descriptions": descriptions}))


def test_converted_partial_when_fewer_niftis_than_the_reviewed_config(tmp_path):
    _write_dcm2bids_config(tmp_path, "sub-01", n_bold=4)
    _seed_bold_runs(tmp_path, "sub-01", 2)  # only 2 of the 4 landed

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
        _touch(
            tmp_path
            / "derivatives"
            / "nordic"
            / "sub-01"
            / "func"
            / f"sub-01_task-rest_run-{i}_bold.nii.gz"
        )

    config = _nordic_config(tmp_path)
    assert survey_project(config).loc[0, "nordic"] == Status.PARTIAL
    assert run_progress(config, "nordic", "01", "") == (2, 4)
    # Stages without a per-run correspondence have no number to give.
    assert run_progress(config, "converted", "01", "") is None


# ---- freesurfer (external recon): subject-level, version-gated ----------------

FS8_STAMP = "freesurfer-linux-ubuntu22.04_x86_64-8.2.0-20250101-abcdef0"
FS7_STAMP = "freesurfer-linux-centos7_x86_64-7.3.2-20220804-6354275"


def _fs_config(root):
    cfg = _config(root)
    cfg["freesurfer"] = {"use_external": True, "version": "8.2.0"}
    return cfg


def _fs_recon(root, subject="01", stamp=FS8_STAMP, complete=True):
    subj = root / "derivatives" / "fmriprep" / "sourcedata" / "freesurfer" / f"sub-{subject}"
    _touch(subj / "scripts" / "build-stamp.txt", stamp)
    if complete:
        _touch(subj / "scripts" / "recon-all.done", "------------------------------\nEND_TIME t1\n")
        for rel in (
            "surf/lh.white",
            "surf/rh.white",
            "surf/lh.pial",
            "surf/rh.pial",
            "mri/aparc+aseg.mgz",
        ):
            _touch(subj / rel)
    else:
        _touch(subj / "scripts" / "recon-all.done", "1\n")
        _touch(subj / "scripts" / "recon-all.error")


def test_freesurfer_is_na_without_use_external(tmp_path):
    """Opt-in, same rule and reason as NORDIC (#17.4): without use_external
    nothing imports the recon, so offering it would spend recon-all hours on a
    derivative fMRIPrep never reads."""
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    assert survey_project(_config(tmp_path)).loc[0, "freesurfer"] == Status.NA


def test_freesurfer_missing_partial_complete(tmp_path):
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    cfg = _fs_config(tmp_path)
    assert survey_project(cfg).loc[0, "freesurfer"] == Status.MISSING
    # A done-marker with the WRONG build-stamp — fMRIPrep's own FS7 recon at
    # the identical path — must not grade COMPLETE (§9 Trap 1, surveyor form).
    _fs_recon(tmp_path, stamp=FS7_STAMP)
    assert survey_project(cfg).loc[0, "freesurfer"] == Status.PARTIAL
    _fs_recon(tmp_path, stamp=FS8_STAMP)
    assert survey_project(cfg).loc[0, "freesurfer"] == Status.COMPLETE


def test_freesurfer_grades_subject_wide_across_sessions(tmp_path):
    """recon-all consumes every session's T1w at once, so all of a subject's
    rows carry one answer — `_fmriprep_status`'s anat widening, same reason."""
    for ses in ("01", "02"):
        _touch(tmp_path / "sourcedata" / "sub-01" / f"ses-{ses}" / "dicom" / "0001.dcm")
    cfg = _fs_config(tmp_path)
    _fs_recon(tmp_path)
    df = survey_project(cfg)
    assert list(df["freesurfer"]) == [Status.COMPLETE, Status.COMPLETE]


def test_freesurfer_staging_dir_never_flips_the_cell(tmp_path):
    """An in-flight recon lives in the dot-prefixed staging dir and must read
    MISSING (plus a running job overlay), not PARTIAL — the cell flips only on
    an imported, complete recon."""
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    cfg = _fs_config(tmp_path)
    staging = (
        tmp_path
        / "derivatives"
        / "fmriprep"
        / "sourcedata"
        / "freesurfer"
        / ".recon-staging"
        / "sub-01"
        / "sub-01"
        / "scripts"
    )
    _touch(staging / "build-stamp.txt", FS8_STAMP)
    assert survey_project(cfg).loc[0, "freesurfer"] == Status.MISSING


# ---- #5b Case 2: more than one fMRIPrep tree over one BIDS root -------------
#
# mmmdata carries `derivatives/fmriprep` and `derivatives/fmriprep_nordic`, 535 G
# each. `_fmriprep_status` hardcoded the first, so duckbrain graded one and could
# not say the other was there. These pin the fix: the extra tree is discovered by
# name, graded by the same tracker, drawn beside the stage it varies, and never
# launchable.


def _fmriprep_tree(root, name="fmriprep", sub="01", func=True):
    """A finished fMRIPrep output tree; ``func=False`` leaves it anat-only."""
    fp = root / "derivatives" / name
    _touch(fp / f"sub-{sub}.html")
    _touch(fp / f"sub-{sub}" / "anat" / f"sub-{sub}_desc-preproc_T1w.nii.gz")
    if func:
        _touch(fp / f"sub-{sub}" / "func" / f"sub-{sub}_task-rest_desc-preproc_bold.nii.gz")
        _touch(fp / f"sub-{sub}" / "func" / f"sub-{sub}_task-rest_desc-confounds_timeseries.tsv")
    return fp


def test_no_variant_column_when_there_is_only_one_fmriprep_tree(tmp_path):
    """The column is additive: every project duckbrain produced itself has one
    fMRIPrep tree and must see exactly the stages it always saw."""
    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    config = _config(tmp_path)
    assert fmriprep_variants(config["paths"]) == ()
    assert stage_columns(config) == STAGES
    assert list(survey_project(config).columns) == ["subject", "session", *STAGES]


def test_variant_tree_gets_its_own_column_beside_fmriprep(tmp_path):
    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _fmriprep_tree(tmp_path, "fmriprep_nordic")
    config = _config(tmp_path)
    assert fmriprep_variants(config["paths"]) == ("fmriprep_nordic",)
    cols = list(survey_project(config).columns)
    # Beside what it varies, not appended after qsiprep — board column order
    # mirrors pipeline order.
    assert cols[cols.index("fmriprep") + 1] == "fmriprep_nordic"
    assert cols[cols.index("fmriprep_nordic") + 1] == "mriqc"


def test_variant_is_graded_independently_of_the_canonical_tree(tmp_path):
    """The point of the item: a second tree that is half-finished must be
    distinguishable from a finished one *and* from one that isn't there."""
    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _fmriprep_tree(tmp_path, "fmriprep_nordic", func=False)
    row = survey_project(_config(tmp_path)).loc[0]
    assert row["fmriprep"] == Status.COMPLETE
    assert row["fmriprep_nordic"] == Status.PARTIAL


def test_variant_name_is_read_off_disk_not_guessed(tmp_path):
    """`#5b` guessed `fmriprep-nordic`; mmmdata wrote `fmriprep_nordic`. Both
    separators are accepted and no spelling is imposed on a tree duckbrain did
    not produce."""
    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _fmriprep_tree(tmp_path, "fmriprep-nordic")
    _fmriprep_tree(tmp_path, "fmriprep_denoised")
    assert fmriprep_variants(_paths(tmp_path)) == ("fmriprep-nordic", "fmriprep_denoised")


def test_scratch_and_unseparated_dirs_are_not_variants(tmp_path):
    """A work dir holds no subjects, and `fmriprep25_pilot` is a different version
    of the tool rather than a variant of this tree — neither is an output tree, so
    neither earns a column."""
    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _touch(tmp_path / "derivatives" / "fmriprep_work" / "fmriprep_wf" / "node.pklz")
    _fmriprep_tree(tmp_path, "fmriprep25_pilot")
    assert fmriprep_variants(_paths(tmp_path)) == ()


def test_run_progress_counts_the_variant_tree(tmp_path):
    """A PARTIAL cell with no number is its own silent degrade — the variant cell
    must carry a count like every other fMRIPrep cell."""
    from duckbrain.core.surveyor import run_progress

    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _fmriprep_tree(tmp_path, "fmriprep_nordic", func=False)
    config = _config(tmp_path)
    assert run_progress(config, "fmriprep", "01", "") == (1, 1)
    assert run_progress(config, "fmriprep_nordic", "01", "") == (0, 1)


def test_summarize_counts_the_variant_column(tmp_path):
    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _fmriprep_tree(tmp_path, "fmriprep_nordic", func=False)
    summary = summarize(survey_project(_config(tmp_path)))
    assert summary["fmriprep"][Status.COMPLETE.value] == 1
    assert summary["fmriprep_nordic"][Status.PARTIAL.value] == 1


def test_summarize_ignores_the_slurm_overlay_columns(tmp_path):
    """`pipeline_matrix` adds `<stage>_job` columns holding SLURM state, not a
    Status. Summarizing by matrix column rather than by STAGES must not turn them
    into phantom stages."""
    _bids_anat_func(tmp_path)
    matrix = survey_project(_config(tmp_path))
    matrix["fmriprep_job"] = ["running"] * len(matrix)
    summary = summarize(matrix)
    assert "fmriprep_job" not in summary
    assert "fmriprep" in summary


def test_variant_is_reported_never_launched(tmp_path):
    """`#5b`: do not branch the pipeline. A variant is a status column and nothing
    more — no STAGE_SPECS entry, so the cockpit cannot offer to run it and no
    second submission path exists to keep in step with the first."""
    from duckbrain.core.pipeline import SLURM_STAGES, stage_runnable

    _bids_anat_func(tmp_path)
    _fmriprep_tree(tmp_path)
    _fmriprep_tree(tmp_path, "fmriprep_nordic", func=False)
    config = _config(tmp_path)
    row = survey_project(config).loc[0]
    assert "fmriprep_nordic" not in SLURM_STAGES
    assert not stage_runnable(row, "fmriprep_nordic", config)
