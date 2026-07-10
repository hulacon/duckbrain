"""Project surveyor — completion (not mere presence) across pipeline stages.

The trees below are minimal fakes of a duckbrain project; the point of each test
is that a *crashed / half-finished* stage grades PARTIAL, a finished one COMPLETE,
and that both sessionless and multi-session layouts are handled by the same
tracker globs.
"""

from duckbrain.core.surveyor import (
    BAGEL_COLUMNS,
    STAGES,
    Status,
    discover_units,
    summarize,
    survey_project,
    to_bagel,
    write_bagel,
)


def _paths(root):
    return {
        "bids_dir": str(root),
        "sourcedata_dir": str(root / "sourcedata"),
        "derivatives_dir": str(root / "derivatives"),
    }


def _config(root):
    return {"paths": _paths(root)}


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
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    mq = tmp_path / "derivatives" / "mriqc"
    _touch(mq / "sub-01" / "anat" / "sub-01_T1w.json", content='{"cnr": 1}')
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
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.COMPLETE


def test_nordic_partial_when_dir_but_no_denoised_bold(tmp_path):
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    # NORDIC output dir exists but the denoised bold never landed → crashed/partial.
    (tmp_path / "derivatives" / "nordic" / "sub-01" / "func").mkdir(parents=True)
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.PARTIAL


def test_nordic_missing_when_no_derivative(tmp_path):
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.loc[0, "nordic"] == Status.MISSING


def test_nordic_sessionless_and_multisession_same_tracker(tmp_path):
    # Sessionless output (nordic.py hardcodes an empty ses- dir for these).
    _touch(tmp_path / "sub-01" / "func" / "sub-01_task-x_bold.nii.gz")
    _touch(tmp_path / "derivatives" / "nordic" / "sub-01" / "ses-" / "func" / "sub-01_task-x_bold.nii.gz")
    # Multi-session output.
    _touch(tmp_path / "sub-02" / "ses-01" / "func" / "sub-02_ses-01_task-x_bold.nii.gz")
    _touch(tmp_path / "derivatives" / "nordic" / "sub-02" / "ses-01" / "func" / "sub-02_ses-01_task-x_bold.nii.gz")
    df = survey_project(_config(tmp_path))
    assert df.set_index("subject").loc["01", "nordic"] == Status.COMPLETE
    assert df.set_index("subject").loc["02", "nordic"] == Status.COMPLETE


# ---- matrix + summary -------------------------------------------------------

def test_survey_columns_and_empty_project(tmp_path):
    (tmp_path / "sourcedata").mkdir()
    df = survey_project(_config(tmp_path))
    assert list(df.columns) == ["subject", "session", *STAGES]
    assert len(df) == 0


# ---- Nipoppy bagel export ---------------------------------------------------

def _config_with_versions(root):
    return {
        "paths": _paths(root),
        "containers": {"fmriprep_version": "24.1.1", "mriqc_version": "24.0.2"},
    }


def test_to_bagel_schema_and_status_mapping(tmp_path):
    # sub-01 fmriprep complete; func present but no report → not complete elsewhere.
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")
    _touch(fp / "sub-01" / "func" / "sub-01_task-rest_desc-preproc_bold.nii.gz")
    cfg = _config_with_versions(tmp_path)
    bagel = to_bagel(survey_project(cfg), cfg)
    assert list(bagel.columns) == BAGEL_COLUMNS
    # Two processing pipelines per unit by default (fmriprep, mriqc).
    assert set(bagel["pipeline_name"]) == {"fmriprep", "mriqc"}
    fmri = bagel[bagel.pipeline_name == "fmriprep"].iloc[0]
    assert fmri["status"] == "SUCCESS"
    assert fmri["pipeline_version"] == "24.1.1"
    assert fmri["bids_participant_id"] == "sub-01"
    mriqc = bagel[bagel.pipeline_name == "mriqc"].iloc[0]
    assert mriqc["status"] == "UNAVAILABLE"  # no mriqc outputs


def test_to_bagel_incomplete_status(tmp_path):
    _bids_anat_func(tmp_path)
    fp = tmp_path / "derivatives" / "fmriprep"
    _touch(fp / "sub-01.html")
    _touch(fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz")  # func missing
    cfg = _config_with_versions(tmp_path)
    bagel = to_bagel(survey_project(cfg), cfg)
    fmri = bagel[bagel.pipeline_name == "fmriprep"].iloc[0]
    assert fmri["status"] == "INCOMPLETE"


def test_to_bagel_session_ids(tmp_path):
    _bids_anat_func(tmp_path, ses="01")
    cfg = _config_with_versions(tmp_path)
    bagel = to_bagel(survey_project(cfg), cfg)
    row = bagel.iloc[0]
    assert row["session_id"] == "01"
    assert row["bids_session_id"] == "ses-01"


def test_write_bagel_to_derivatives(tmp_path):
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    cfg = _config_with_versions(tmp_path)
    out = write_bagel(cfg)
    assert out == tmp_path / "derivatives" / "processing_status.tsv"
    assert out.exists()
    header = out.read_text().splitlines()[0].split("\t")
    assert header == BAGEL_COLUMNS


def test_summarize_counts(tmp_path):
    _touch(tmp_path / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sourcedata" / "sub-02" / "dicom" / "0001.dcm")
    _touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")  # sub-01 converted
    df = survey_project(_config(tmp_path))
    summary = summarize(df)
    assert summary["ingested"][Status.COMPLETE.value] == 2
    assert summary["converted"][Status.COMPLETE.value] == 1
    assert summary["converted"][Status.MISSING.value] == 1
