"""Tests for duckbrain.core.qc_dwi — diffusion QC reviewed per session."""

import json

import pandas as pd
import pytest

from duckbrain.core import qc_dwi, qc_report


def _mriqc_run(root, sub, ses, direction, **iqms):
    """Write one MRIQC diffusion IQM JSON, with plausible defaults."""
    values = {
        "ndc": 0.95,
        "snr_cc_shell0": 8.0,
        "snr_cc_shell1_best": 8.0,
        "snr_cc_shell1_worst": 7.0,
        "snr_cc_shell2_best": 4.0,
        "snr_cc_shell2_worst": 2.0,
        "efc_shell01": 0.52,
        "efc_shell02": 0.53,
        "fber_shell01": 20000.0,
        "fber_shell02": 1000.0,
        "fa_nans": 0.0,
        "fa_degenerate": 0.0,
        "fd_mean": 15.0,
        "fd_perc": 93.0,
    }
    values.update(iqms)
    ses_part = f"_ses-{ses}" if ses else ""
    directory = root / f"sub-{sub}" / (f"ses-{ses}" if ses else "") / "dwi"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"sub-{sub}{ses_part}_dir-{direction}_dwi.json"
    path.write_text(json.dumps(values))


def _qsiprep_output(root, sub, ses, **measures):
    """Write one QSIPrep desc-image_qc.tsv row."""
    values = {
        "raw_neighbor_corr": 0.90,
        "t1_neighbor_corr": 0.96,
        "raw_num_bad_slices": 0.0,
        "CNR0_mean": 30.0,
        "CNR1_mean": 1.1,
        "CNR2_mean": 1.9,
        "mean_fd": 0.3,
        "max_rel_translation": 0.8,
        "max_rel_rotation": 0.003,
        "t1_dice_distance": 0.02,
    }
    values.update(measures)
    directory = root / f"sub-{sub}" / f"ses-{ses}" / "dwi"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"sub-{sub}_ses-{ses}_space-ACPC_desc-image_qc.tsv"
    pd.DataFrame([values]).to_csv(path, sep="\t", index=False)


@pytest.fixture
def trees(tmp_path):
    mriqc, qsiprep = tmp_path / "mriqc", tmp_path / "qsiprep"
    mriqc.mkdir()
    qsiprep.mkdir()
    return mriqc, qsiprep


class TestSessionRows:
    def test_four_runs_become_one_row_keyed_to_the_session(self, trees):
        mriqc, qsiprep = trees
        for d in ("AP", "PA", "LR", "RL"):
            _mriqc_run(mriqc, "01", "01", d)
        df = qc_dwi.load_session_metrics(mriqc, qsiprep)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["pe_dirs"] == "AP+LR+PA+RL"
        assert row["n_mriqc_runs"] == 4
        # The decision key is the session: no dir- entity, and it is the key
        # every run of the session would have produced on its own.
        assert qc_report.build_run_key(row, qc_dwi.MODALITY) == "sub-01_ses-01_dwi"

    def test_each_measure_takes_the_worst_run_and_the_worst_shell(self, trees):
        mriqc, qsiprep = trees
        _mriqc_run(mriqc, "01", "01", "AP", ndc=0.95, efc_shell02=0.60, snr_cc_shell2_worst=1.5)
        _mriqc_run(mriqc, "01", "01", "PA", ndc=0.40, fber_shell02=500.0)
        row = qc_dwi.load_session_metrics(mriqc, qsiprep).iloc[0]
        assert row["ndc_min"] == pytest.approx(0.40)
        assert row["efc_max"] == pytest.approx(0.60)
        assert row["fber_min"] == pytest.approx(500.0)
        # b0 SNR is kept apart from the diffusion-weighted shells.
        assert row["snr_b0_min"] == pytest.approx(8.0)
        assert row["snr_dwi_min"] == pytest.approx(1.5)

    def test_qsiprep_measures_join_the_same_session_row(self, trees):
        mriqc, qsiprep = trees
        _mriqc_run(mriqc, "01", "01", "AP")
        _mriqc_run(mriqc, "01", "01", "PA")
        _qsiprep_output(qsiprep, "01", "01", CNR1_mean=1.1, CNR2_mean=0.7)
        row = qc_dwi.load_session_metrics(mriqc, qsiprep).iloc[0]
        assert row["n_qsiprep_outputs"] == 1
        assert row["raw_neighbor_corr"] == pytest.approx(0.90)
        # CNR0 is the b0 volumes' and is excluded from the diffusion minimum.
        assert row["cnr_dwi_min"] == pytest.approx(0.7)
        # QSIPrep's mean_fd is renamed so it cannot be read as fMRIPrep's.
        assert row["eddy_mean_fd"] == pytest.approx(0.3)
        assert "mean_fd" not in row.index

    def test_a_missing_source_leaves_blanks_rather_than_dropping_the_session(self, trees):
        mriqc, qsiprep = trees
        _mriqc_run(mriqc, "01", "01", "AP")
        _qsiprep_output(qsiprep, "02", "01")
        df = qc_dwi.load_session_metrics(mriqc, qsiprep).set_index("sub")
        assert pd.isna(df.loc["01", "raw_neighbor_corr"])
        assert pd.isna(df.loc["02", "ndc_min"])
        assert df.loc["02", "pe_dirs"] == ""

    def test_mriqc_diffusion_motion_is_not_surfaced(self):
        # MRIQC's diffusion FD registers across shells and reports contrast as
        # displacement; see the module docstring.
        assert not [k for k in qc_dwi.MEASURE_KEYS if k.startswith("fd_")]

    def test_a_sessionless_project_keys_without_an_empty_session(self, trees):
        mriqc, qsiprep = trees
        _mriqc_run(mriqc, "01", "", "AP")
        df = qc_dwi.load_session_metrics(mriqc, qsiprep)
        assert "ses" not in df.columns
        assert qc_report.build_run_key(df.iloc[0], qc_dwi.MODALITY) == "sub-01_dwi"

    def test_no_output_at_all_is_an_empty_table(self, trees):
        assert qc_dwi.load_session_metrics(*trees).empty


def _sessions(rows):
    return pd.DataFrame(
        [{"sub": s, "ses": ses, "pe_dirs": pe, "ndc_min": ndc} for s, ses, pe, ndc in rows]
    )


class TestFlagOutliers:
    def test_two_collapsed_sessions_of_six_are_both_flagged(self):
        # The IQR fence misses this: the two collapsed values widen the
        # quartiles until neither is outside them. The MAD rule does not move.
        df = _sessions(
            [
                ("01", "01", "AP+PA", 0.95),
                ("02", "01", "AP+PA", 0.946),
                ("03", "01", "AP+PA", 0.94),
                ("04", "01", "AP+PA", 0.93),
                ("05", "01", "AP+PA", 0.34),
                ("06", "01", "AP+PA", 0.42),
            ]
        )
        flagged = qc_dwi.flag_outliers(df, ["ndc_min"]).set_index("sub")
        assert flagged["is_outlier"].to_dict() == {
            "01": False,
            "02": False,
            "03": False,
            "04": False,
            "05": True,
            "06": True,
        }

    def test_a_drop_within_one_participant_is_flagged(self):
        df = _sessions(
            [
                ("01", "01", "AP+PA", 0.95),
                ("01", "02", "AP+PA", 0.83),
                ("02", "01", "AP+PA", 0.83),
            ]
        )
        flagged = qc_dwi.flag_outliers(df, ["ndc_min"])
        assert flagged["ndc_min_outlier"].tolist() == [False, True, False]

    def test_sessions_are_only_compared_within_their_protocol(self):
        # The two-direction session would sit far below the four-direction
        # batch, but it has no batch of its own to be judged against.
        df = _sessions(
            [
                ("01", "01", "AP+LR+PA+RL", 0.95),
                ("02", "01", "AP+LR+PA+RL", 0.95),
                ("03", "01", "AP+LR+PA+RL", 0.94),
                ("01", "02", "AP+PA", 0.60),
            ]
        )
        flagged = qc_dwi.flag_outliers(df, ["ndc_min"])
        assert not flagged["is_outlier"].any()

    def test_other_measures_keep_the_iqr_fence(self):
        df = _sessions([(f"{i:02d}", "01", "AP+PA", 0.95) for i in range(1, 7)])
        df["efc_max"] = [0.50, 0.51, 0.50, 0.52, 0.51, 0.90]
        flagged = qc_dwi.flag_outliers(df, ["ndc_min", "efc_max"])
        assert flagged["efc_max_outlier"].tolist() == [False] * 5 + [True]
        assert not flagged["ndc_min_outlier"].any()

    def test_an_empty_table_passes_through(self):
        assert qc_dwi.flag_outliers(pd.DataFrame(), ["ndc_min"]).empty
