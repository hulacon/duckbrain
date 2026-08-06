"""QC metrics loading, outlier detection, and decision tracking."""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import pandas as pd

if TYPE_CHECKING:
    from ..config import Config

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
        parts = parse_entities(json_path.stem)
        if "sub" not in parts:
            continue
        seen_files.add(json_path.name)
        data.update(parts)
        data["_source_file"] = json_path.name
        rows.append(data)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def parse_entities(stem: str) -> dict[str, str]:
    """Extract BIDS entities from a filename stem.

    Public because ``core.qc_evidence`` matches fMRIPrep figures on entities and
    needs the same reading of a filename that the IQM loader uses. A third copy
    would be the one that drifts.
    """
    entities: dict[str, str] = {}
    for part in stem.split("_"):
        if "-" in part:
            key, val = part.split("-", 1)
            entities[key] = val
    return entities


# ---- Outlier Detection ----

BOLD_IQMS = ["fd_mean", "fd_perc", "tsnr", "dvars_std", "efc", "fber"]
ANAT_IQMS = ["cnr", "cjv", "efc", "fber", "snr_total", "qi_1", "wm2max"]


def cohort_position(
    values: pd.Series | Sequence[float | None], value: float | None
) -> float | None:
    """Where *value* sits among *values*, as a fraction from 0 (lowest) to 1.

    The guidance layer's central claim is that IQMs carry site, scanner and
    protocol batch effects, so the honest comparison is within a dataset rather
    than against a fixed cutoff. A raw number cannot express that on its own —
    ``tsnr = 41`` means nothing without knowing that every other run here is
    higher. This is that comparison, in the one number a reader can scan.

    Deliberately **not** a verdict: it says where a run sits, not whether the
    position is acceptable. A perfectly good dataset still has a lowest run.

    Returns ``None`` when there is nothing to compare against — a single run, or
    a metric no run reported — rather than a misleading 0.0 or 0.5.
    """
    if value is None:
        return None
    series = pd.Series(list(values), dtype="float64").dropna()
    if len(series) < 2:
        return None
    return float((series <= value).sum() - 1) / float(len(series) - 1)


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
            # A row is the filename's entities plus four numbers, so it is
            # widened here rather than in `parse_entities`, whose values really
            # are all strings and whose other caller reads them as such.
            row: dict[str, Any] = dict(
                parse_entities(tsv_path.stem.replace("_desc-confounds_timeseries", ""))
            )
            row["mean_fd"] = fd.mean()
            row["max_fd"] = fd.max()
            row["pct_high_motion"] = (fd > fd_threshold).mean() * 100
            row["n_volumes"] = len(fd)
            rows.append(row)
        except Exception:
            continue

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---- QC Decisions ----


#: One append-only entry in a run's decision file: ``decision``, ``reviewer``,
#: ``automated``, an optional ``domain``, a timestamp, free-text notes.
#:
#: ``dict[str, Any]`` and not a ``TypedDict``, deliberately. These are read off
#: disk in **two** on-disk schemas (see :func:`_history_of`), the older of which
#: duckbrain no longer writes and is never rewritten, and every key is absent
#: from some file that exists today — which is why every reader here goes
#: through ``.get()`` and an ``isinstance``. A TypedDict describing that would
#: have to declare all six keys optional, i.e. say nothing, while reading as a
#: guarantee to the next person.
DecisionEntry = dict[str, Any]


class DomainRecord(TypedDict):
    """One domain of a run, assembled from its entries by :func:`_domains_of`."""

    latest: DecisionEntry
    history: list[DecisionEntry]
    signed_off: bool


class DecisionRecord(DomainRecord):
    """One run's decisions, assembled by :func:`load_decisions`.

    Subclasses :class:`DomainRecord` rather than repeating its three keys,
    because a domain record really is the run-level record minus the domain
    breakdown — a caller reads one from the other without learning a second
    convention, and stating it as inheritance is what keeps that true.

    Unlike :data:`DecisionEntry` this **is** a TypedDict: nothing on disk has
    this shape. It is built here, in one place, with all four keys always set.
    """

    domains: dict[str, DomainRecord]


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

#: What a reviewer may record about **one aspect** of a run — signal, temporal
#: stability, alignment, artifacts. ``concerns`` records that a look happened and
#: something wants following up, which ``pending`` cannot express.
#:
#: These words are deliberately **disjoint** from :data:`VALID_DECISIONS`, and
#: :func:`save_decision` enforces the separation in both directions. The reason is
#: structural, not stylistic: domain entries live in the same append-only list as
#: verdicts, and ``latest`` is read straight into a run's badge. If the two
#: vocabularies overlapped, noting "SDC looks off" on the alignment domain would
#: flip the run's verdict — the shape of the bug where typing a reason used to
#: record an ``investigate`` nobody made, with the arrow reversed.
VALID_DOMAIN_STATES = frozenset({"reviewed", "concerns", "pending"})

#: Domain states that mean a person actually looked.
SIGNED_OFF_DOMAIN_STATES = frozenset({"reviewed", "concerns"})


def is_signed_off(record: DecisionEntry | None) -> bool:
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
    domain: str | None = None,
) -> Path:
    """Append a QC decision for a run, or a review note for one of its domains.

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
        One of :data:`VALID_DECISIONS` for a run verdict, or one of
        :data:`VALID_DOMAIN_STATES` when *domain* is given. Automated writers may
        record only ``pending``, and should put their suggestion in
        *recommendation*.
    domain : str, optional
        A review domain key (``'signal'``, ``'temporal'``, ``'alignment'``,
        ``'artifact'``). When given, this entry records that one aspect of the run
        was reviewed and is **not** a verdict on the run — it never becomes the
        run's ``latest``, and never changes its badge or its sign-off count.
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
    # Which vocabulary applies, and — as importantly — which one must be refused.
    # Rejecting the *other* vocabulary in each direction is what makes the two
    # kinds of entry impossible to confuse once they share a file.
    if domain is None:
        allowed, signed_off_values, kind = VALID_DECISIONS, SIGNED_OFF_DECISIONS, "decision"
        forbidden, other = VALID_DOMAIN_STATES, "a domain review state"
    else:
        allowed, signed_off_values, kind = (
            VALID_DOMAIN_STATES,
            SIGNED_OFF_DOMAIN_STATES,
            "domain state",
        )
        forbidden, other = VALID_DECISIONS, "a run verdict"

    if decision in (forbidden - allowed):
        raise ValueError(
            f"{decision!r} is {other} and cannot be recorded "
            f"{'for a domain' if domain else 'as a run verdict'}; "
            f"expected one of {sorted(allowed)}."
        )
    if decision not in allowed:
        raise ValueError(f"Invalid {kind} {decision!r}; expected one of {sorted(allowed)}")
    if recommendation is not None and recommendation not in allowed:
        raise ValueError(
            f"Invalid recommendation {recommendation!r}; expected one of {sorted(allowed)}"
        )

    reviewer_id = (reviewer or "").strip()
    if automated:
        if decision in signed_off_values:
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
    if domain is not None:
        # Only ever set, never defaulted to None: an entry with no ``domain`` key
        # is a run verdict, and every record written before domains existed must
        # keep reading as exactly that.
        entry["domain"] = domain
    history.append(entry)

    decisions_dir.mkdir(parents=True, exist_ok=True)
    with open(decision_file, "w") as f:
        json.dump({"run_key": run_key, "decisions": history}, f, indent=2)

    return decision_file


#: Where duckbrain's QC output lives inside its own derivatives directory.
QC_SUBDIR = "qc"
DECISIONS_SUBDIR = "decisions"

#: Directories decisions were written to before everything duckbrain authors was
#: gathered under ``derivatives/duckbrain``. Read, never written, never moved —
#: mmmdata still writes here, and a project converted by either tool has to stay
#: readable by both.
LEGACY_DECISION_DIRS = ("preprocessing_qc",)


def decisions_dir(config: Config) -> Path:
    """Where a decision is written. One place, always the current one."""
    paths = config.get("paths", {})
    root = paths.get("duckbrain_dir") or (Path(paths["derivatives_dir"]) / "duckbrain")
    return Path(root) / QC_SUBDIR / DECISIONS_SUBDIR


def decision_search_dirs(config: Config) -> list[Path]:
    """Everywhere decisions may be read from, oldest location first.

    Order is the point rather than a detail: :func:`load_decisions` appends each
    root's entries after the previous root's, so the current location's entries
    land last and a run reviewed in both places reads with its newest verdict
    current. It also means no file has to be moved — the same treatment
    :func:`_history_of` gives the two on-disk *schemas*, applied to the two
    on-disk *locations*.
    """
    derivatives = Path(config.get("paths", {}).get("derivatives_dir", ""))
    legacy = [derivatives / name for name in LEGACY_DECISION_DIRS]
    return [*legacy, decisions_dir(config)]


def _history_of(data: dict[str, Any]) -> list[DecisionEntry]:
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


def load_decisions(
    decisions_dir: str | Path | Iterable[str | Path],
) -> dict[str, DecisionRecord]:
    """Load all QC decisions, in either on-disk schema and any known location.

    Searched recursively, so both duckbrain's flat directory and mmmdata's
    ``sub-XX/`` nesting are found.

    Parameters
    ----------
    decisions_dir : path or iterable of paths
        One directory, or several to merge — see :func:`decision_search_dirs`.
        When a run has entries under more than one root, their histories are
        concatenated in the order the roots are given, so the last root's
        entries are the most recent. Within a file, order is left alone: it is
        append-only, and position is what carries "current".

    Returns
    -------
    dict
        ``{run_key: {"latest": ..., "history": [...], "signed_off": bool,
        "domains": {key: {"latest": ..., "history": [...], "signed_off": bool}}}}``.

        ``latest`` is the most recent entry **carrying no domain** — the run's own
        verdict. That qualification is the whole safety property: domain notes
        share the file, so reading ``history[-1]`` would let the last thing said
        about alignment become the run's verdict and flip its badge. ``signed_off``
        says whether that verdict is a call a named person made, which is not the
        same question as whether a decision exists.

        ``domains`` is empty for every record written before domains existed,
        because those entries carry no ``domain`` key — so a legacy file reads
        byte-identically to how it always did.
    """
    if isinstance(decisions_dir, (str, Path)):
        roots = [Path(decisions_dir)]
    else:
        roots = [Path(d) for d in decisions_dir]

    merged: dict[str, list[DecisionEntry]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for json_path in sorted(root.rglob("*_decision.json")):
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
            merged.setdefault(run_key, []).extend(history)

    decisions: dict[str, DecisionRecord] = {}
    for run_key, history in merged.items():
        verdicts = [e for e in history if not e.get("domain")]
        latest = verdicts[-1] if verdicts else {}
        decisions[run_key] = {
            "latest": latest,
            "history": history,
            "signed_off": is_signed_off(latest),
            "domains": _domains_of(history),
        }

    return decisions


def _domains_of(history: list[DecisionEntry]) -> dict[str, DomainRecord]:
    """Group a record's domain entries by domain, newest last.

    Same shape as the run-level record, so a caller reads one from the other
    without learning a second convention.
    """
    grouped: dict[str, list[DecisionEntry]] = {}
    for entry in history:
        key = entry.get("domain")
        if key:
            grouped.setdefault(key, []).append(entry)
    return {
        key: {
            "latest": entries[-1],
            "history": entries,
            "signed_off": is_domain_signed_off(entries[-1]),
        }
        for key, entries in grouped.items()
    }


def is_domain_signed_off(record: DecisionEntry | None) -> bool:
    """True when a named person recorded a look at this domain.

    The domain counterpart of :func:`is_signed_off`, and it answers the same
    question about a smaller claim: someone identifiable reviewed this aspect.
    ``concerns`` counts — it means they looked and found something, which is more
    review than ``reviewed``, not less.
    """
    if not record:
        return False
    if record.get("automated"):
        return False
    if record.get("decision") not in SIGNED_OFF_DOMAIN_STATES:
        return False
    reviewer = str(record.get("reviewer") or "").strip().lower()
    return bool(reviewer) and reviewer not in AUTOMATED_REVIEWERS


def domain_progress(record: DecisionRecord | None, domain_keys: Iterable[str]) -> tuple[int, int]:
    """How many of *domain_keys* a person has reviewed, and how many there are.

    For **display only**. A run whose four domains are all reviewed has not
    thereby been given a verdict, and duckbrain must never derive one: the domains
    do not partition the question a verdict answers — none of them covers task
    timing, stimulus delivery, or a participant asleep with their eyes open.
    "Reviewed every domain" and "this run is usable" are different claims, and
    turning the first into the second manufactures a sign-off nobody made.
    """
    domains = record.get("domains") or {} if record else {}
    keys = list(domain_keys)
    return sum(1 for k in keys if (d := domains.get(k)) and d.get("signed_off")), len(keys)


def decision_counts(decisions: dict[str, DecisionRecord]) -> dict[str, int]:
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
