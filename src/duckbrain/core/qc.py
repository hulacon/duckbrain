"""QC metrics loading, outlier detection, and decision tracking."""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd


# ---- QC settings ----

#: Used only when the config cannot be read. Kept in step with ``[qc]`` in
#: ``config/base.toml``; that file is the place to change a threshold.
DEFAULT_QC_SETTINGS: dict[str, float] = {
    "fd_threshold": 0.5,
    "investigate_threshold": 0.5,
    "iqr_multiplier": 1.5,
}


def qc_settings(project_dir: str | Path | None = None) -> dict[str, float]:
    """Return the ``[qc]`` thresholds, resolved through the layered config.

    A project overrides a threshold in its own ``code/duckbrain.toml``; the
    shipped values in ``config/base.toml`` apply otherwise.

    If the config cannot be read at all, :data:`DEFAULT_QC_SETTINGS` is used and
    a warning is emitted rather than failing silently — a threshold that is
    quietly not the one you configured is worse than a noisy one. mmmdata shipped
    exactly that bug: a package-level import made ``load_config`` raise wherever
    an optional dependency was absent, stranding every threshold on its fallback
    with nothing said.

    Parameters
    ----------
    project_dir : path, optional
        Active project directory, passed through to ``load_config``.

    Returns
    -------
    dict
        Keys ``fd_threshold``, ``investigate_threshold``, ``iqr_multiplier``.
    """
    settings = dict(DEFAULT_QC_SETTINGS)

    # Imported here, not at module scope: this module is imported by the GUI at
    # a point where a missing/unreadable config must degrade to a warning rather
    # than an ImportError at collection time.
    try:
        from duckbrain.config import load_config

        qc_section = load_config(project_dir=project_dir).get("qc", {})
    except Exception as exc:
        warnings.warn(
            f"Could not read [qc] settings from config ({exc}); falling back to {settings}.",
            RuntimeWarning,
            stacklevel=2,
        )
        return settings

    for key in settings:
        if key in qc_section:
            try:
                settings[key] = float(qc_section[key])
            except (TypeError, ValueError):
                warnings.warn(
                    f"[qc] {key}={qc_section[key]!r} is not a number; using {settings[key]}.",
                    RuntimeWarning,
                    stacklevel=2,
                )
    return settings


# ---- MRIQC Metrics ----


def load_mriqc_metrics(mriqc_dir: str | Path, modality: str = "bold") -> pd.DataFrame:
    """Load MRIQC IQM metrics into a DataFrame.

    Parameters
    ----------
    mriqc_dir : path
        MRIQC derivatives directory.
    modality : str
        "bold", "T1w", or "T2w".

    Returns
    -------
    pd.DataFrame
        One row per run/image with all IQMs.
    """
    mriqc_dir = Path(mriqc_dir)
    rows = []

    # Recursive, because MRIQC's depth follows the dataset, not a fixed shape:
    # sub-XX/ses-YY/<datatype>/ when the study has sessions, sub-XX/<datatype>/
    # when it does not, and flat at the root for some versions. A fixed list of
    # globs previously required the ses- level and so matched *nothing* on a
    # sessionless project — the page then reported no metrics and advised
    # running MRIQC, which had already run. Found 2026-07-24 against
    # divatten_beta, which is sessionless.
    #
    # The suffix does the filtering: `*_bold.json` cannot match MRIQC's
    # companion `*_timeseries.json`, so only IQM files are read.
    seen_files = set()
    for json_path in sorted(mriqc_dir.rglob(f"*_{modality}.json")):
        if json_path.name in seen_files:
            continue
        try:
            with open(json_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        # Extract subject/session/task/run from filename
        parts = _parse_bids_filename(json_path.stem)
        if "sub" not in parts:
            continue
        seen_files.add(json_path.name)
        data.update(parts)
        data["_source_file"] = json_path.name
        rows.append(data)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def _parse_bids_filename(stem: str) -> dict:
    """Extract BIDS entities from a filename stem."""
    entities = {}
    for part in stem.split("_"):
        if "-" in part:
            key, val = part.split("-", 1)
            entities[key] = val
    return entities


# ---- Outlier Detection ----

BOLD_IQMS = ["fd_mean", "fd_perc", "tsnr", "dvars_std", "efc", "fber"]
ANAT_IQMS = ["cnr", "cjv", "efc", "fber", "snr_total", "qi_1", "wm2max"]


def detect_outliers(
    metrics_df: pd.DataFrame,
    iqm_columns: list[str] | None = None,
    iqr_multiplier: float = 1.5,
    scope: str = "global",
) -> pd.DataFrame:
    """Flag outlier runs based on IQR method.

    Parameters
    ----------
    metrics_df : pd.DataFrame
        MRIQC metrics table.
    iqm_columns : list[str], optional
        Which IQMs to check. Defaults to BOLD_IQMS.
    iqr_multiplier : float
        IQR multiplier for outlier threshold.
    scope : str
        "global" (across all subjects) or "within_subject".

    Returns
    -------
    pd.DataFrame
        Copy of input with added *_outlier boolean columns and is_outlier summary.
    """
    if iqm_columns is None:
        iqm_columns = BOLD_IQMS

    df = metrics_df.copy()

    # Only use columns that exist in the data
    available_cols = [c for c in iqm_columns if c in df.columns]
    if not available_cols:
        df["is_outlier"] = False
        return df

    for col in available_cols:
        if scope == "within_subject" and "sub" in df.columns:
            df[f"{col}_outlier"] = df.groupby("sub")[col].transform(
                lambda x: _iqr_outlier(x, iqr_multiplier)
            )
        else:
            df[f"{col}_outlier"] = _iqr_outlier(df[col], iqr_multiplier)

    outlier_cols = [f"{c}_outlier" for c in available_cols]
    df["is_outlier"] = df[outlier_cols].any(axis=1)

    return df


def _iqr_outlier(series: pd.Series, multiplier: float) -> pd.Series:
    """Flag values outside IQR * multiplier."""
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    return (series < lower) | (series > upper)


# ---- Motion Summary ----


def summarize_motion(
    confounds_dir: str | Path,
    fd_threshold: float = 0.5,
) -> pd.DataFrame:
    """Summarize framewise displacement from fMRIPrep confounds files.

    Parameters
    ----------
    confounds_dir : path
        fMRIPrep output directory (will search for confounds TSVs).
    fd_threshold : float
        Threshold for high-motion frames.

    Returns
    -------
    pd.DataFrame
        One row per run with mean_fd, max_fd, pct_high_motion.
    """
    confounds_dir = Path(confounds_dir)
    rows = []

    for tsv_path in sorted(confounds_dir.rglob("*_desc-confounds_timeseries.tsv")):
        try:
            df = pd.read_csv(tsv_path, sep="\t")
            if "framewise_displacement" not in df.columns:
                continue

            fd = df["framewise_displacement"].dropna()
            parts = _parse_bids_filename(tsv_path.stem.replace("_desc-confounds_timeseries", ""))
            parts["mean_fd"] = fd.mean()
            parts["max_fd"] = fd.max()
            parts["pct_high_motion"] = (fd > fd_threshold).mean() * 100
            parts["n_volumes"] = len(fd)
            rows.append(parts)
        except Exception:
            continue

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---- QC Decisions ----


def save_decision(
    decisions_dir: str | Path,
    run_key: str,
    decision: str,
    reason: str = "",
    reviewer: str = "",
) -> Path:
    """Save a QC decision for a run.

    Parameters
    ----------
    decisions_dir : path
        Directory for decision JSON files.
    run_key : str
        BIDS run identifier (e.g., "sub-01_ses-02_task-rest_run-1_bold").
    decision : str
        One of: "keep", "exclude", "investigate".
    reason : str
        Optional reason for the decision.
    reviewer : str
        Who made the decision.

    Returns
    -------
    Path
        Path to the written decision file.
    """
    if decision not in ("keep", "exclude", "investigate"):
        raise ValueError(f"Invalid decision: {decision}. Must be keep/exclude/investigate.")

    decisions_dir = Path(decisions_dir)
    decision_file = decisions_dir / f"{run_key}_decision.json"

    # Load existing history if present
    history = []
    if decision_file.exists():
        with open(decision_file) as f:
            existing = json.load(f)
        history = existing.get("history", [])
        # Add previous latest to history
        if "latest" in existing:
            history.append(existing["latest"])

    latest = {
        "decision": decision,
        "reason": reason,
        "reviewer": reviewer,
        "timestamp": datetime.now().isoformat(),
    }

    decisions_dir.mkdir(parents=True, exist_ok=True)
    with open(decision_file, "w") as f:
        json.dump({"latest": latest, "history": history}, f, indent=2)

    return decision_file


def load_decisions(decisions_dir: str | Path) -> dict:
    """Load all QC decisions.

    Returns
    -------
    dict
        {run_key: {"latest": {...}, "history": [...]}}
    """
    decisions_dir = Path(decisions_dir)
    decisions = {}

    if not decisions_dir.is_dir():
        return decisions

    for json_path in sorted(decisions_dir.glob("*_decision.json")):
        run_key = json_path.stem.replace("_decision", "")
        try:
            with open(json_path) as f:
                decisions[run_key] = json.load(f)
        except (json.JSONDecodeError, KeyError):
            continue

    return decisions
