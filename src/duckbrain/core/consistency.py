"""Provenance consistency checker — flag self-contradictory pipeline state.

Phase B of the provenance work (TODO ★). Phase A made every run self-describing
(the durable submission log records tool/version/container/input-variant) and put
duckbrain-produced derivatives in the same on-disk ``dataset_description.json``
``GeneratedBy`` format that fMRIPrep/MRIQC write themselves. This module reads
that provenance back and flags where it disagrees with itself or with config.

**Source-of-truth ordering (design decision, 2026-07-16).** On-disk provenance is
*authoritative*; the submission log is an *overlay*. On-disk describes any
derivative regardless of who produced it — so an externally-run fMRIPrep folds in
as a first-class citizen and is never flagged merely for lacking a log row. The
log adds only what on-disk structurally cannot: ``dataset_description.json`` is a
single dataset-level file overwritten by whichever run finished last, so it can't
represent *mixed* provenance across subjects in one derivative dir. That is the
one thing the log-overlay checks catch.

The checks, and which source each rests on:

* **Config vs provenance** (on-disk) — ``use_nordic`` on but fMRIPrep's
  ``DatasetLinks.raw`` isn't the NORDIC tree, or vice-versa.
* **Version drift** (on-disk) — a derivative's ``GeneratedBy`` version differs
  from the version config now pins (config bumped without re-running).
* **Mixed input variant / version** (log overlay) — some subjects launched raw,
  some NORDIC (or under different tool versions) into the same derivative.
* **Staleness** (mtime) — a derivative older than an input it derives from
  (e.g. NORDIC re-run after fMRIPrep) → "stale, re-run".
* **Presence** (matrix) — fMRIPrep present but NORDIC missing in a NORDIC project.

Everything degrades quietly: unreadable/absent provenance yields no issue rather
than a false alarm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .pipeline import read_submissions
from .surveyor import survey_project


@dataclass(frozen=True)
class ConsistencyIssue:
    """One flagged inconsistency, ready to render as a ⚠️ in the cockpit.

    ``check`` is a stable category slug; ``subject`` is ``""`` for project-level
    issues. ``message`` is the user-facing explanation.
    """

    check: str
    message: str
    severity: str = "warning"
    subject: str = ""
    stage: str = ""


# ---- on-disk provenance readers ---------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@dataclass(frozen=True)
class DerivativeProvenance:
    """What a derivative's ``dataset_description.json`` says about its origin."""

    exists: bool
    generated_by: list  # list of {Name, Version, ...}
    raw_link: str       # DatasetLinks.raw, "" if absent

    def tool_version(self, tool: str) -> str:
        """Version recorded for *tool* in GeneratedBy (case-insensitive), or ""."""
        for entry in self.generated_by:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("Name", "")).lower() == tool.lower():
                return str(entry.get("Version", ""))
        return ""


def read_derivative_provenance(config: dict, pipeline: str) -> DerivativeProvenance:
    """Read ``<derivatives>/<pipeline>/dataset_description.json`` provenance.

    Absent/unreadable → ``exists=False`` with empty fields. Works for any
    derivative — duckbrain-produced or tool-written — since Phase A unified the
    on-disk format.
    """
    root = Path(config["paths"]["derivatives_dir"]) / pipeline
    desc = _read_json(root / "dataset_description.json")
    if not desc:
        return DerivativeProvenance(exists=root.is_dir(), generated_by=[], raw_link="")
    links = desc.get("DatasetLinks", {})
    raw = str(links.get("raw", "")) if isinstance(links, dict) else ""
    gb = desc.get("GeneratedBy", [])
    if not isinstance(gb, list):
        gb = []
    return DerivativeProvenance(exists=True, generated_by=gb, raw_link=raw)


def _links_to_nordic(raw_link: str) -> bool:
    """True if a ``DatasetLinks.raw`` value points at a NORDIC-denoised tree."""
    r = raw_link.rstrip("/")
    return r.endswith("nordic/bids_format") or "/nordic/" in r or r.endswith("/nordic")


def _use_nordic(config: dict) -> bool:
    return bool(config.get("nordic", {}).get("use_nordic", False))


def _newest_mtime(root: Path, pattern: str) -> float | None:
    """Newest mtime among files matching *pattern* under *root*, or None."""
    newest: float | None = None
    try:
        for p in root.glob(pattern):
            if p.is_file():
                m = p.stat().st_mtime
                if newest is None or m > newest:
                    newest = m
    except (OSError, ValueError):
        return None
    return newest


# ---- individual checks ------------------------------------------------------

def _check_config_vs_provenance(config: dict) -> list[ConsistencyIssue]:
    prov = read_derivative_provenance(config, "fmriprep")
    if not prov.exists or not prov.raw_link:
        return []
    on_nordic = _links_to_nordic(prov.raw_link)
    want_nordic = _use_nordic(config)
    if want_nordic and not on_nordic:
        return [ConsistencyIssue(
            "config-vs-provenance", stage="fmriprep",
            message=(
                "Project config has use_nordic on, but the fMRIPrep derivative "
                f"was generated from raw data (DatasetLinks.raw = {prov.raw_link}). "
                "Re-run fMRIPrep on the NORDIC tree, or turn use_nordic off."),
        )]
    if not want_nordic and on_nordic:
        return [ConsistencyIssue(
            "config-vs-provenance", stage="fmriprep",
            message=(
                "Project config has use_nordic off, but the fMRIPrep derivative "
                f"was generated from a NORDIC tree (DatasetLinks.raw = {prov.raw_link}). "
                "Turn use_nordic on, or re-run fMRIPrep on raw data."),
        )]
    return []


def _check_version_drift(config: dict) -> list[ConsistencyIssue]:
    versions = config.get("containers", {})
    issues: list[ConsistencyIssue] = []
    for pipeline, tool, vkey in (
        ("fmriprep", "fMRIPrep", "fmriprep_version"),
        ("mriqc", "MRIQC", "mriqc_version"),
    ):
        expected = str(versions.get(vkey, ""))
        if not expected:
            continue
        prov = read_derivative_provenance(config, pipeline)
        on_disk = prov.tool_version(tool)
        if on_disk and on_disk != expected:
            issues.append(ConsistencyIssue(
                "version-drift", stage=pipeline,
                message=(
                    f"Config pins {tool} {expected}, but the existing derivative "
                    f"was generated by {tool} {on_disk}. Re-run to match, or the "
                    "derivative is stale relative to the pinned version."),
            ))
    return issues


def _latest_per_subject(config: dict, stage: str) -> dict[str, dict]:
    """Latest submission-log row per subject for *stage* (a re-run supersedes)."""
    subs = read_submissions(config)
    if subs.empty or "stage" not in subs.columns:
        return {}
    stage_rows = subs[subs["stage"] == stage]
    latest: dict[str, dict] = {}
    for _, row in stage_rows.iterrows():  # log is oldest-first, so last write wins
        latest[str(row.get("subject", ""))] = row.to_dict()
    return latest


def _check_mixed_provenance(config: dict) -> list[ConsistencyIssue]:
    """Log-overlay check: subjects launched under different variants/versions.

    On-disk ``dataset_description.json`` is dataset-level, so this mixing is
    invisible there — only duckbrain's own per-run record catches it.
    """
    latest = _latest_per_subject(config, "fmriprep")
    if not latest:
        return []
    issues: list[ConsistencyIssue] = []

    variants: dict[str, list[str]] = {}
    for sub, row in latest.items():
        v = str(row.get("input_variant", "")).strip()
        if v:
            variants.setdefault(v, []).append(sub)
    if len(variants) > 1:
        desc = "; ".join(f"{v}: {', '.join(sorted(s))}" for v, s in sorted(variants.items()))
        issues.append(ConsistencyIssue(
            "mixed-provenance", stage="fmriprep",
            message=(
                "fMRIPrep was run over different input variants across subjects "
                f"in the same derivative ({desc}). Mixed provenance — re-run so "
                "all subjects share one variant."),
        ))

    tool_versions: dict[str, list[str]] = {}
    for sub, row in latest.items():
        tv = str(row.get("tool_version", "")).strip()
        if tv:
            tool_versions.setdefault(tv, []).append(sub)
    if len(tool_versions) > 1:
        desc = "; ".join(f"{v}: {', '.join(sorted(s))}" for v, s in sorted(tool_versions.items()))
        issues.append(ConsistencyIssue(
            "mixed-version", stage="fmriprep",
            message=(
                "fMRIPrep was run under different tool versions across subjects "
                f"in the same derivative ({desc}). Re-run so all subjects share "
                "one version."),
        ))
    return issues


def _check_staleness(config: dict) -> list[ConsistencyIssue]:
    """Heuristic: NORDIC re-run after fMRIPrep leaves fMRIPrep stale (mtime)."""
    if not _use_nordic(config):
        return []
    deriv = Path(config["paths"]["derivatives_dir"])
    nordic_new = _newest_mtime(deriv / "nordic", "sub-*/**/func/*_bold.nii.gz")
    fmriprep_old = _newest_mtime(deriv / "fmriprep", "sub-*/**/func/*_desc-preproc_bold.nii.gz")
    if nordic_new is not None and fmriprep_old is not None and nordic_new > fmriprep_old:
        return [ConsistencyIssue(
            "staleness", stage="fmriprep",
            message=(
                "NORDIC output is newer than the fMRIPrep derivative that should "
                "consume it — NORDIC was likely re-run after fMRIPrep. fMRIPrep is "
                "stale; re-run it on the updated NORDIC data."),
        )]
    return []


def _check_presence(config: dict) -> list[ConsistencyIssue]:
    """In a NORDIC project, fMRIPrep present but its NORDIC input missing."""
    if not _use_nordic(config):
        return []
    matrix = survey_project(config)
    issues: list[ConsistencyIssue] = []
    for _, r in matrix.iterrows():
        fp, nd = r.get("fmriprep", "missing"), r.get("nordic", "missing")
        if fp in ("complete", "partial") and nd == "missing":
            sub, ses = r["subject"], r["session"]
            unit = f"sub-{sub}" + (f"/ses-{ses}" if ses else "")
            issues.append(ConsistencyIssue(
                "presence", subject=sub, stage="nordic",
                message=(
                    f"{unit}: fMRIPrep output exists but its NORDIC input is "
                    "missing, though the project is configured for NORDIC. The "
                    "fMRIPrep run may not reflect the intended denoised input."),
            ))
    return issues


# ---- public API -------------------------------------------------------------

def check_consistency(config: dict) -> list[ConsistencyIssue]:
    """Run all provenance-consistency checks; return the flagged issues.

    Empty list means nothing inconsistent was found. Ordering is stable
    (config-vs-provenance, version drift, mixed provenance, staleness, presence)
    so the cockpit renders deterministically.
    """
    issues: list[ConsistencyIssue] = []
    for check in (
        _check_config_vs_provenance,
        _check_version_drift,
        _check_mixed_provenance,
        _check_staleness,
        _check_presence,
    ):
        try:
            issues.extend(check(config))
        except Exception:
            # A single check blowing up must not sink the whole panel.
            continue
    return issues
