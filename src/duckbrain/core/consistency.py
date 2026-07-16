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

**The log is job tracking, the files are the record (2026-07-16).** The two track
related but distinct things: the log records *submissions* — including in-flight,
cancelled, and since-deleted runs — while the filesystem records what was actually
produced. For provenance the files arbitrate, so every log-overlay check reads the
log through ``_latest_per_subject``, which drops rows with no output on disk.

The checks, and which source each rests on:

* **Config vs provenance** (on-disk) — ``use_nordic`` on but fMRIPrep's
  ``DatasetLinks.raw`` isn't the NORDIC tree, or vice-versa.
* **Container drift** (on-disk, log fallback) — config resolves a different
  container than the one that produced the derivative (pin bumped, no re-run).
  Compares container *identity*, never version strings — a pinned ``*_version``
  is a container tag, while ``GeneratedBy.Version`` is the tool's self-reported
  version, and the two legitimately differ.
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

from .containers import container_build_tag
from .pipeline import read_submissions, resolve_container
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

    def _tool_entry(self, tool: str) -> dict:
        for entry in self.generated_by:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("Name", "")).lower() == tool.lower():
                return entry
        return {}

    def tool_version(self, tool: str) -> str:
        """Version *tool* self-reports in GeneratedBy (case-insensitive), or "".

        Informational only: this is the tool's own version string, which lives in
        a different namespace from the container tag config pins. Do not compare
        the two — see ``_check_container_drift``.
        """
        return str(self._tool_entry(tool).get("Version", ""))

    def _container(self, tool: str) -> dict:
        container = self._tool_entry(tool).get("Container", {})
        return container if isinstance(container, dict) else {}

    def tool_container(self, tool: str) -> str:
        """Container tag (the image filename) recorded for *tool*, or "".

        Only duckbrain-written descriptions carry ``Container`` (see
        ``bids_metadata.write_derivative_description``). fMRIPrep/MRIQC overwrite
        the description with their own, which records no container — hence the
        log overlay fallback in ``_check_container_drift``.
        """
        return str(self._container(tool).get("Tag", ""))

    def tool_container_uri(self, tool: str) -> str:
        """Container build source recorded for *tool* (``docker://…``), or "".

        The image's own build provenance, stronger than the filename in ``Tag``.
        """
        return str(self._container(tool).get("URI", ""))


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


def _configured_container(config: dict, stage: str) -> tuple[str, str]:
    """What config currently points at for *stage*: ``(filename, build_tag)``.

    Resolved via ``pipeline.resolve_container`` — the same resolution the builder
    and ``run_provenance`` use — so a comparison against recorded provenance is
    like-for-like. ``build_tag`` is the image's own record of what it was built
    from, ``""`` when unreadable.
    """
    try:
        path = resolve_container(config, stage)
        if not path:
            return "", ""
        return Path(path).name, container_build_tag(path)
    except Exception:
        return "", ""


def _recorded_container(config: dict, stage: str, tool: str) -> tuple[str, str]:
    """What produced the derivative: ``(filename, build_tag)``, "" where unknown.

    On-disk provenance is authoritative (``GeneratedBy[].Container`` — ``Tag`` is
    the filename, ``URI`` the build source); the submission log is the overlay,
    consulted only when on-disk records no container — the norm, since
    fMRIPrep/MRIQC overwrite the description with their own and omit it. An
    externally-produced derivative has neither and correctly yields ``("", "")``.
    """
    prov = read_derivative_provenance(config, stage)
    on_disk_name = prov.tool_container(tool)
    if on_disk_name:
        return on_disk_name, _uri_to_build_tag(prov.tool_container_uri(tool))

    latest = _latest_per_subject(config, stage)

    def _single(column: str) -> str:
        # Mixing across subjects is _check_mixed_provenance's business, not ours.
        values = {
            str(row.get(column, "")).strip()
            for row in latest.values()
            if str(row.get(column, "")).strip()
        }
        return values.pop() if len(values) == 1 else ""

    return _single("container"), _single("container_source")


def _uri_to_build_tag(uri: str) -> str:
    """``docker://nipreps/mriqc:24.0.2`` → ``nipreps/mriqc:24.0.2``."""
    return uri.split("://", 1)[1] if "://" in uri else uri


def _check_container_drift(config: dict) -> list[ConsistencyIssue]:
    """Config now points at a different container than the one that produced the
    derivative — i.e. the pin was bumped without re-running.

    Compares **container identity**, never version strings. The pinned
    ``*_version`` is a container *tag* (it builds ``<tool>-<tag>.simg``), whereas
    a tool's ``GeneratedBy.Version`` is its own self-reported version — different
    namespaces that need not agree. Confirmed on real data 2026-07-16:
    ``mriqc-24.0.2.simg`` is built from ``nipreps/mriqc:24.0.2`` (so the filename
    is *right*) yet self-reports ``24.1.0.dev0+gd5b13cb5.d20240826``, an upstream
    packaging artifact. Comparing those flagged a correctly-configured project.

    Prefers **build provenance** (the Docker tag the image records being built
    from) over the filename when both sides know it: the filename is a
    convention, so it misses an image rebuilt in place and cries wolf over one
    merely renamed. Falls back to the filename when build tags are unavailable
    (e.g. runs logged before ``container_source`` existed), and stays silent when
    neither side is knowable.
    """
    issues: list[ConsistencyIssue] = []
    for stage, tool in (("fmriprep", "fMRIPrep"), ("mriqc", "MRIQC")):
        if not read_derivative_provenance(config, stage).exists:
            continue
        rec_name, rec_tag = _recorded_container(config, stage, tool)
        cfg_name, cfg_tag = _configured_container(config, stage)

        if rec_tag and cfg_tag:
            drifted, was, now, basis = rec_tag != cfg_tag, rec_tag, cfg_tag, "built from"
        elif rec_name and cfg_name:
            drifted, was, now, basis = rec_name != cfg_name, rec_name, cfg_name, "container"
        else:
            continue

        if drifted:
            issues.append(ConsistencyIssue(
                "container-drift", stage=stage,
                message=(
                    f"Config now resolves {tool} to {basis} `{now}`, but the "
                    f"existing derivative was produced with `{was}`. The pin was "
                    "bumped (or the image rebuilt) without re-running — re-run to "
                    "match, or the derivative is stale relative to the pin."),
            ))
    return issues


def _subjects_with_output(config: dict, stage: str) -> set[str]:
    """Subjects that actually have *stage* output on disk (complete or partial)."""
    matrix = survey_project(config)
    if matrix.empty or stage not in matrix.columns:
        return set()
    done = matrix[matrix[stage].isin(("complete", "partial"))]
    return {str(s) for s in done["subject"]}


def _latest_per_subject(config: dict, stage: str) -> dict[str, dict]:
    """Latest submission-log row per subject for *stage*, reconciled against disk.

    The log and the filesystem track two related but distinct things: the log
    records *submissions* (job tracking, including in-flight work), while the
    files record what was actually *produced*. For provenance — a claim about
    what a derivative is made of — the files are the arbiter. So rows whose
    output isn't on disk are dropped: a cancelled or deleted run, or one still
    in flight, must not contribute provenance for a subject the derivative
    doesn't contain.

    Within what survives, the log is still the overlay that on-disk can't
    replace: it alone says *how* each subject was produced. A re-run supersedes
    its predecessor (the log is oldest-first, so the last write wins).
    """
    subs = read_submissions(config)
    if subs.empty or "stage" not in subs.columns:
        return {}
    on_disk = _subjects_with_output(config, stage)
    stage_rows = subs[subs["stage"] == stage]
    latest: dict[str, dict] = {}
    for _, row in stage_rows.iterrows():
        subject = str(row.get("subject", ""))
        if subject in on_disk:
            latest[subject] = row.to_dict()
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
        _check_container_drift,
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
