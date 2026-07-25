"""QC metrics loading, outlier detection, and decision tracking."""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
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


#: Every value a decision record may carry. ``pending`` is the state of a run no
#: human has signed off on, and it is the only thing an automated writer may
#: record — so a machine's suggestion can never be mistaken for a judgement.
VALID_DECISIONS = frozenset({"keep", "exclude", "investigate", "pending"})

#: The values that represent an actual human call.
SIGNED_OFF_DECISIONS = frozenset({"keep", "exclude", "investigate"})

#: Reviewer strings that name automation rather than a person. Records written
#: before the ``automated`` flag existed are classified by this, which is what
#: lets legacy files be read correctly without rewriting anything on disk.
AUTOMATED_REVIEWERS = frozenset({"auto-stub", "auto", "automated", ""})


def is_signed_off(record: dict | None) -> bool:
    """True when *record* is a decision an identifiable person actually made.

    Three things must hold: the record exists, its decision is a real call
    rather than ``pending``, and it is attributable to a named human.

    This is the whole point of the vocabulary. duckbrain wrote decisions for
    months with ``reviewer`` defaulting to ``""`` and the page never passing one,
    so **every decision it has ever recorded is anonymous**. Those cannot be
    attributed after the fact — nobody knows who made them — so they read as
    unattributed here rather than being promoted to sign-offs they never were.
    """
    if not record:
        return False
    if record.get("automated"):
        return False
    if record.get("decision") not in SIGNED_OFF_DECISIONS:
        return False
    reviewer = str(record.get("reviewer") or "").strip().lower()
    return bool(reviewer) and reviewer not in AUTOMATED_REVIEWERS


def save_decision(
    decisions_dir: str | Path,
    run_key: str,
    decision: str,
    reason: str = "",
    reviewer: str = "",
    automated: bool = False,
    recommendation: str | None = None,
) -> Path:
    """Append a QC decision for a run.

    Records are append-only: the file holds the full history, and the last entry
    is the current one. Written as ``{"run_key": ..., "decisions": [...]}``,
    which is the shape mmmdata already writes — so the two tools converge on one
    format with no file needing conversion, and duckbrain can read the 609
    records mmmdata has accumulated.

    Parameters
    ----------
    decisions_dir : path
        Directory for decision JSON files.
    run_key : str
        BIDS run identifier (e.g. ``sub-01_ses-02_task-rest_run-1_bold``).
    decision : str
        One of :data:`VALID_DECISIONS`. Automated writers may record only
        ``pending``, and should put their suggestion in *recommendation*.
    reason : str
        Free-text explanation, saved with the decision.
    reviewer : str
        Who made the call. Required — and required to name a person — unless
        *automated* is set.
    automated : bool
        True when tooling wrote this rather than a person.
    recommendation : str, optional
        What automation would suggest. Advisory; it never gates anything.

    Raises
    ------
    ValueError
        If the decision is not in the vocabulary, if a human sign-off carries no
        identifiable reviewer, or if an automated writer claims a verdict only a
        human may make. Refusing is the point: a decision recorded without an
        attributable author is indistinguishable later from one nobody made.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"Invalid decision {decision!r}; expected one of {sorted(VALID_DECISIONS)}"
        )
    if recommendation is not None and recommendation not in VALID_DECISIONS:
        raise ValueError(
            f"Invalid recommendation {recommendation!r}; expected one of {sorted(VALID_DECISIONS)}"
        )

    reviewer_id = (reviewer or "").strip()
    if automated:
        if decision in SIGNED_OFF_DECISIONS:
            raise ValueError(
                f"Automated writers may only record 'pending', not {decision!r}. "
                f"Pass the suggestion as recommendation= instead."
            )
    elif not reviewer_id or reviewer_id.lower() in AUTOMATED_REVIEWERS:
        raise ValueError(
            f"A human sign-off requires an identifiable reviewer; got {reviewer!r}. "
            f"Pass automated=True for tooling-written records."
        )

    decisions_dir = Path(decisions_dir)
    decision_file = decisions_dir / f"{run_key}_decision.json"

    history = []
    if decision_file.exists():
        try:
            with open(decision_file) as f:
                history = _history_of(json.load(f))
        except (OSError, json.JSONDecodeError):
            history = []

    entry = {
        "decision": decision,
        "reason": reason,
        "reviewer": reviewer,
        "automated": bool(automated),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if recommendation is not None:
        entry["recommendation"] = recommendation
    history.append(entry)

    decisions_dir.mkdir(parents=True, exist_ok=True)
    with open(decision_file, "w") as f:
        json.dump({"run_key": run_key, "decisions": history}, f, indent=2)

    return decision_file


def _history_of(data: dict) -> list[dict]:
    """Return a record's entries oldest-first, from either on-disk schema.

    Two shapes exist and neither reader understood the other:

    * ``{"run_key": ..., "decisions": [...]}`` — what mmmdata writes and what
      duckbrain writes now. Append-only; the last entry is current.
    * ``{"latest": {...}, "history": [...]}`` — what duckbrain used to write,
      keeping the current entry outside the list.

    Both are accepted so no file on disk has to be converted, and so nothing
    goes unread. Reading is the only compatibility that is owed: an old record
    is never rewritten, because rewriting it would restamp a decision with a
    provenance it does not have.
    """
    if isinstance(data.get("decisions"), list):
        return [e for e in data["decisions"] if isinstance(e, dict)]
    history = [e for e in data.get("history", []) if isinstance(e, dict)]
    if isinstance(data.get("latest"), dict):
        history.append(data["latest"])
    return history


def load_decisions(decisions_dir: str | Path) -> dict:
    """Load all QC decisions, in either on-disk schema and either layout.

    Searched recursively, so both duckbrain's flat directory and mmmdata's
    ``sub-XX/`` nesting are found.

    Returns
    -------
    dict
        ``{run_key: {"latest": {...}, "history": [...], "signed_off": bool}}``.
        ``latest`` is the most recent entry; ``signed_off`` says whether it is a
        call a named person made, which is not the same question as whether a
        decision exists.
    """
    decisions_dir = Path(decisions_dir)
    decisions: dict[str, dict] = {}

    if not decisions_dir.is_dir():
        return decisions

    for json_path in sorted(decisions_dir.rglob("*_decision.json")):
        try:
            with open(json_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        history = _history_of(data)
        if not history:
            continue
        run_key = data.get("run_key") or json_path.stem.replace("_decision", "")
        decisions[run_key] = {
            "latest": history[-1],
            "history": history,
            "signed_off": is_signed_off(history[-1]),
        }

    return decisions


def decision_counts(decisions: dict) -> dict[str, int]:
    """Break a decision set down by how much authority each record carries.

    Reported separately rather than summed, because "has a decision" and "was
    reviewed" are different claims and only the second justifies acting on the
    data.

    The two non-sign-off buckets say different things and must not be merged:
    ``automated`` is a record whose author is known to be a machine, while
    ``unattributed`` is one whose author cannot be identified at all. Only the
    second is a provenance gap someone could still close by re-reviewing.

    A record predating the ``automated`` flag is classified by reviewer name, so
    mmmdata's 609 ``auto-stub`` entries count as automated rather than being
    misreported as decisions by an unknown person.
    """
    counts = {"signed_off": 0, "unattributed": 0, "automated": 0, "pending": 0}
    for record in decisions.values():
        latest = record.get("latest") or {}
        reviewer = str(latest.get("reviewer") or "").strip().lower()
        if is_signed_off(latest):
            counts["signed_off"] += 1
        elif latest.get("automated") or (reviewer and reviewer in AUTOMATED_REVIEWERS):
            counts["automated"] += 1
        elif latest.get("decision") in SIGNED_OFF_DECISIONS:
            counts["unattributed"] += 1
        else:
            counts["pending"] += 1
    return counts
