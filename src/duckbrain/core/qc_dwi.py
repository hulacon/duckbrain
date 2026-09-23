"""Diffusion QC: one review row per session, from MRIQC's runs and QSIPrep's session.

Every other modality on the QC pages is reviewed per *run*, because that is the
unit both MRIQC and fMRIPrep write. Diffusion is reviewed per **session**,
because that is the unit the data is analysed in: QSIPrep concatenates a
session's diffusion runs — opposing phase-encoding directions included — into
one preprocessed series and writes one ``desc-image_qc.tsv`` for it. A verdict
on one ``dir-`` run would be a verdict on something no analysis ever reads.

MRIQC still runs per file, so its numbers arrive per direction and have to be
brought up to the session. This module does that explicitly, **by taking the
worst run** for each measure (the lowest value of a higher-is-better measure,
the highest of a lower-is-better one). A mean would let one bad direction hide
behind three good ones, which is the one failure a session verdict exists to
catch. The per-run values stay available through :func:`mriqc_runs` so the
reviewer can see which direction a session's number came from.

Per-shell measures are reduced the same way before the runs are: MRIQC writes
``efc_shell01`` … ``efc_shellNN`` with as many shells as the protocol has, so a
registry of fixed measure names can only carry them as "worst shell". The
per-shell values are in :func:`mriqc_runs` too.

Why the session key needs no new entity
---------------------------------------
:func:`~duckbrain.core.qc_report.build_run_key` keys on ``sub``, ``ses``,
``task`` and ``run``. A diffusion file carries ``dir-`` and none of task or run,
so every run of a session already keys to ``sub-XX_ses-YY_dwi`` — the session.
Until this module existed that was an accident, and the four MRIQC rows of a
session would have been filed under one key with nothing reconciling them. It is
now the intended key, produced from one row per session built here, and pinned
by a test.

What is deliberately *not* surfaced
-----------------------------------
MRIQC's diffusion ``fd_*`` measures. MRIQC estimates diffusion motion by
registering volumes across shells, where contrast differences between b-values
read as displacement: on a real multi-shell dataset every run reported a mean
FD of several millimetres and over 90% of volumes "high motion". Motion for
diffusion comes from QSIPrep's eddy-based estimates instead.

Why outliers are judged within a protocol
-----------------------------------------
Neighbouring-volume correlation depends on the acquisition — b-values, how
densely directions are sampled, acquisition order, and (for QSIPrep's ``raw_``
value, computed on the concatenated uncorrected series) how many
phase-encoding directions were merged. Sessions with different sets of ``dir-``
runs are therefore compared only among themselves: :func:`flag_outliers` groups
on ``pe_dirs`` before applying any fence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from duckbrain.core import qc

#: The modality name used throughout the QC pages and decision keys.
MODALITY = "dwi"

MRIQC_SOURCE = "MRIQC"
QSIPREP_SOURCE = "QSIPrep"

#: QSIPrep's per-output QC table. One per preprocessed series.
IMAGE_QC_GLOB = "*_desc-image_qc.tsv"

#: The within-subject rule from Yeh et al. (2019): a scan whose neighbouring-DWI
#: correlation falls more than this far below the same participant's other scan
#: of the same protocol is flagged. The one published NDC rule that is not
#: relative to a cohort, and the one that suits a dataset scanning each
#: participant more than once.
NDC_WITHIN_SUBJECT_DROP = 0.1

#: DSI Studio's batch rule for NDC: flag a scan below
#: ``median - NDC_MAD_FENCE * 1.4826 * MAD`` of its batch (``cmd/qc.cpp``). The
#: IQR fence is not used for NDC because it fails in exactly the case that
#: matters most on a small dataset: when two of six sessions collapse, the
#: collapsed values widen the quartiles until neither is outside them. The median
#: and MAD are not moved by a minority.
NDC_MAD_FENCE = 3.0

#: The session columns that are neighbouring-DWI correlations, and so take the
#: NDC rules rather than the IQR fence.
NDC_MEASURES = ("raw_neighbor_corr", "t1_neighbor_corr", "ndc_min")


@dataclass(frozen=True)
class SessionMeasure:
    """How one session-level measure is built from its source columns.

    Parameters
    ----------
    key : str
        Column name in the session table, and the guidance-registry key.
    source : str
        :data:`MRIQC_SOURCE` or :data:`QSIPREP_SOURCE`.
    pattern : str
        Regular expression matched in full against the source's column names.
        Every matching column, in every run or output of the session, is reduced
        into the one value.
    reduce : str
        ``"min"`` or ``"max"`` — whichever picks the *worst* value, given which
        direction is better for this measure.
    """

    key: str
    source: str
    pattern: str
    reduce: str

    def __post_init__(self) -> None:
        if self.reduce not in ("min", "max"):
            raise ValueError(f"reduce must be 'min' or 'max', not {self.reduce!r}")

    def columns_in(self, columns: list[str]) -> list[str]:
        """The source columns this measure is built from, in their given order."""
        rx = re.compile(self.pattern)
        return [c for c in columns if rx.fullmatch(c)]


SESSION_MEASURES: tuple[SessionMeasure, ...] = (
    # QSIPrep: already one value per session output, so the reduction only
    # matters if a session was split into more than one output.
    SessionMeasure("raw_neighbor_corr", QSIPREP_SOURCE, r"raw_neighbor_corr", "min"),
    SessionMeasure("t1_neighbor_corr", QSIPREP_SOURCE, r"t1_neighbor_corr", "min"),
    SessionMeasure("raw_num_bad_slices", QSIPREP_SOURCE, r"raw_num_bad_slices", "max"),
    SessionMeasure("cnr_dwi_min", QSIPREP_SOURCE, r"CNR[1-9]\d*_mean", "min"),
    SessionMeasure("eddy_mean_fd", QSIPREP_SOURCE, r"mean_fd", "max"),
    SessionMeasure("max_rel_translation", QSIPREP_SOURCE, r"max_rel_translation", "max"),
    SessionMeasure("max_rel_rotation", QSIPREP_SOURCE, r"max_rel_rotation", "max"),
    SessionMeasure("t1_dice_distance", QSIPREP_SOURCE, r"t1_dice_distance", "max"),
    # MRIQC: one row per dir- run, reduced to the worst run.
    SessionMeasure("ndc_min", MRIQC_SOURCE, r"ndc", "min"),
    SessionMeasure("snr_b0_min", MRIQC_SOURCE, r"snr_cc_shell0", "min"),
    SessionMeasure("snr_dwi_min", MRIQC_SOURCE, r"snr_cc_shell[1-9]\d*_worst", "min"),
    SessionMeasure("efc_max", MRIQC_SOURCE, r"efc_shell\d+", "max"),
    SessionMeasure("fber_min", MRIQC_SOURCE, r"fber_shell\d+", "min"),
    SessionMeasure("fa_nans_max", MRIQC_SOURCE, r"fa_nans", "max"),
    SessionMeasure("fa_degenerate_max", MRIQC_SOURCE, r"fa_degenerate", "max"),
)

MEASURE_KEYS: tuple[str, ...] = tuple(m.key for m in SESSION_MEASURES)

#: Session identity columns every row carries, whatever its sources.
IDENTITY_COLUMNS = ("sub", "ses", "pe_dirs", "n_mriqc_runs", "n_qsiprep_outputs")


def _session_of(entities: dict[str, str]) -> tuple[str, str]:
    return entities.get("sub", ""), entities.get("ses", "")


def mriqc_runs(mriqc_dir: str | Path) -> pd.DataFrame:
    """MRIQC's diffusion IQMs, one row per ``dir-`` run, as MRIQC wrote them.

    The per-run evidence behind a session's MRIQC measures — shown beside the
    session row so a reviewer can see which direction the worst value came from.
    """
    df = qc.load_mriqc_metrics(mriqc_dir, MODALITY)
    if df.empty:
        return df
    for col in ("ses", "dir"):
        if col not in df.columns:
            df[col] = ""
    df["ses"] = df["ses"].fillna("")
    df["dir"] = df["dir"].fillna("")
    return df.sort_values(["sub", "ses", "dir"]).reset_index(drop=True)


def qsiprep_outputs(qsiprep_dir: str | Path) -> pd.DataFrame:
    """QSIPrep's ``desc-image_qc.tsv`` rows, one per preprocessed series.

    Entities are read from the filename rather than from the table's own
    ``subject_id``/``session_id`` columns, so a sessionless project and a session
    project are read the same way the MRIQC loader reads them.
    """
    root = Path(qsiprep_dir)
    frames = []
    for path in sorted(root.rglob(IMAGE_QC_GLOB)):
        try:
            table = pd.read_csv(path, sep="\t")
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
            continue
        entities = qc.parse_entities(path.name.removesuffix(".tsv"))
        if "sub" not in entities or table.empty:
            continue
        table = table.assign(
            sub=entities["sub"], ses=entities.get("ses", ""), _source_file=path.name
        )
        frames.append(table)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _reduce(frame: pd.DataFrame, measure: SessionMeasure) -> float | None:
    cols = measure.columns_in(list(frame.columns))
    if not cols:
        return None
    values = pd.to_numeric(frame[cols].stack(), errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.min() if measure.reduce == "min" else values.max())


def load_session_metrics(mriqc_dir: str | Path, qsiprep_dir: str | Path) -> pd.DataFrame:
    """One row per diffusion session, combining whichever of the two sources exist.

    A session appears if either tool wrote anything for it; a measure whose
    source has not run for that session is left empty rather than dropped, so
    the table says "no QSIPrep yet" instead of silently narrowing.

    Returns
    -------
    pd.DataFrame
        :data:`IDENTITY_COLUMNS` plus one column per :data:`SESSION_MEASURES`
        key. ``pe_dirs`` is the session's ``dir-`` labels joined with ``+``
        (from MRIQC's runs; empty when only QSIPrep has run), and is what
        :func:`flag_outliers` stratifies on. Empty when neither tool has output.
    """
    runs = mriqc_runs(mriqc_dir)
    outputs = qsiprep_outputs(qsiprep_dir)

    sessions: set[tuple[str, str]] = set()
    for frame in (runs, outputs):
        if not frame.empty:
            sessions.update(zip(frame["sub"].astype(str), frame["ses"].astype(str), strict=True))

    rows = []
    for sub, ses in sorted(sessions):
        mine = {
            MRIQC_SOURCE: _select(runs, sub, ses),
            QSIPREP_SOURCE: _select(outputs, sub, ses),
        }
        mriqc = mine[MRIQC_SOURCE]
        dirs = sorted({d for d in mriqc["dir"] if d}) if not mriqc.empty else []
        row: dict[str, object] = {
            "sub": sub,
            "ses": ses,
            "pe_dirs": "+".join(dirs),
            "n_mriqc_runs": len(mriqc),
            "n_qsiprep_outputs": len(mine[QSIPREP_SOURCE]),
        }
        for m in SESSION_MEASURES:
            source = mine[m.source]
            row[m.key] = _reduce(source, m) if not source.empty else None
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if not df["ses"].astype(bool).any():
        # A sessionless project: drop the column so the run key has no empty
        # ``ses-`` part, exactly as a sessionless MRIQC row would.
        df = df.drop(columns="ses")
    return df


def _select(frame: pd.DataFrame, sub: str, ses: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    mask = (frame["sub"].astype(str) == sub) & (frame["ses"].astype(str) == ses)
    return frame[mask]


def _mad_low(values: pd.Series, fence: float = NDC_MAD_FENCE) -> pd.Series:
    """True where a value sits below ``median - fence * 1.4826 * MAD``.

    One-sided: a scan cannot be too *well* correlated with its neighbours. A
    batch with no spread (MAD of zero) flags nothing rather than everything.
    """
    present = values.dropna()
    if len(present) < 3:
        return pd.Series(False, index=values.index)
    median = present.median()
    mad = (present - median).abs().median()
    if mad == 0:
        return pd.Series(False, index=values.index)
    return (values < median - fence * 1.4826 * mad).fillna(False)


def _within_subject_drop(df: pd.DataFrame, col: str, keys: list[str]) -> pd.Series:
    """True where *col* is more than :data:`NDC_WITHIN_SUBJECT_DROP` below the
    same participant's best session of the same protocol."""
    best = df.groupby(keys)[col].transform("max")
    count = df.groupby(keys)[col].transform("count")
    return ((count > 1) & (best - df[col] > NDC_WITHIN_SUBJECT_DROP)).fillna(False)


def flag_outliers(
    df: pd.DataFrame, measures: list[str], iqr_multiplier: float = 1.5
) -> pd.DataFrame:
    """Flag sessions, judging each only against sessions of the same protocol.

    Everything is applied within each ``pe_dirs`` group, never across groups.

    * **NDC columns** (:data:`NDC_MEASURES`) take two rules, either of which
      flags: DSI Studio's batch rule (:data:`NDC_MAD_FENCE`), and the
      within-subject rule of Yeh et al. (2019), :data:`NDC_WITHIN_SUBJECT_DROP`
      below the same participant's best session. A participant with one session
      of a protocol has nothing to compare against and is not flagged by the
      second.
    * **Every other measure** takes the IQR fence of
      :func:`duckbrain.core.qc.detect_outliers`, as every other modality does.

    Returns a copy with ``<measure>_outlier`` columns and ``is_outlier``, the
    same shape ``detect_outliers`` gives every other modality.
    """
    if df.empty:
        return df.assign(is_outlier=pd.Series(dtype=bool))
    ndc_cols = [m for m in measures if m in NDC_MEASURES and m in df.columns]
    fenced = [m for m in measures if m not in NDC_MEASURES]
    group_col = "pe_dirs" if "pe_dirs" in df.columns else None
    groups = [part for _, part in df.groupby(group_col, sort=False)] if group_col else [df]

    parts = []
    for part in groups:
        out = qc.detect_outliers(part, iqm_columns=fenced, iqr_multiplier=iqr_multiplier)
        for col in ndc_cols:
            out[f"{col}_outlier"] = _mad_low(out[col]) | _within_subject_drop(out, col, ["sub"])
        parts.append(out)
    flagged = pd.concat(parts).loc[df.index]
    outlier_cols = [c for c in flagged.columns if c.endswith("_outlier")]
    flagged["is_outlier"] = flagged[outlier_cols].any(axis=1) if outlier_cols else False
    return flagged
