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

**Which source serves which stage.** It follows from what duckbrain authors:

* derivatives duckbrain **produces** (NORDIC) → provenance lives *in the data*
  (per-file sidecars, then the dataset-level stamp). The sidecars are the only
  source correct at NORDIC's real granularity: the sbatch skips already-denoised
  runs, so one subject's files can legitimately differ (a partial array failure
  re-launched after a toolbox bump leaves survivors on the old toolbox), and the
  log's one-row-per-subject view would misreport all of them.
* derivatives **tools** produce (fMRIPrep/MRIQC) → the submission log, because
  they author their own outputs and overwrite their own ``dataset_description``,
  leaving duckbrain no channel inside the data at all.

The checks, and which source each rests on:

* **Config vs provenance** (on-disk) — ``use_nordic`` on but fMRIPrep's
  ``DatasetLinks.raw`` isn't the NORDIC tree, or vice-versa.
* **Container drift** (on-disk, log fallback) — config resolves a different
  container than the one that produced the derivative (pin bumped, no re-run).
  Compares container *identity*, never version strings — a pinned ``*_version``
  is a container tag, while ``GeneratedBy.Version`` is the tool's self-reported
  version, and the two legitimately differ.
* **Toolbox drift** (on-disk, log fallback) — NORDIC's equivalent, against the
  git checkout it runs from rather than an image. Here comparing versions *is*
  sound: both sides are ``git describe`` of the same repo.
* **MATLAB drift** (on-disk, log fallback) — NORDIC's *second* axis. A container
  stage has one (the image is both runtime and code); NORDIC's runtime (MATLAB)
  and code (the toolbox) move independently, so the runtime needs its own check.
* **duckbrain drift** (on-disk) — duckbrain's own release line moved. Held to a
  *lower* standard than the above, deliberately: a tool's version **is** the
  computation, whereas duckbrain's is the recipe-writer. Raised at ``note``
  severity, only for the stages where duckbrain authors the recipe, and only on a
  release-line change so rapid development stays quiet.
* **Mixed input variant / version / runtime** (log overlay) — some subjects
  launched raw, some NORDIC (or under different tool versions or runtimes) into
  the same derivative.
* **Staleness** (mtime) — a derivative older than an input it derives from
  (e.g. NORDIC re-run after fMRIPrep) → "stale, re-run".
* **Presence** (matrix) — fMRIPrep present but NORDIC missing in a NORDIC project.

Everything degrades quietly: unreadable/absent provenance yields no issue rather
than a false alarm.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .bids_metadata import duckbrain_version
from .containers import container_build_tag
from .pipeline import (
    matlab_module,
    nordic_toolbox_dir,
    read_submissions,
    resolve_container,
)
from .surveyor import survey_project
from .toolbox import describe


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
    return read_provenance_at(Path(config["paths"]["derivatives_dir"]) / pipeline)


def read_provenance_at(root: str | Path) -> DerivativeProvenance:
    """Read the ``dataset_description.json`` provenance of any dataset *root*.

    Same reader for a derivative or the raw BIDS root — the latter is where
    duckbrain stamps itself for the conversion it performed.
    """
    root = Path(root)
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

    return _single("runtime"), _single("code_source")


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
    (e.g. runs logged before ``code_source`` was recorded), and stays silent when
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


def _check_toolbox_drift(config: dict) -> list[ConsistencyIssue]:
    """The NORDIC toolbox checkout has moved since it produced the derivative.

    NORDIC's analogue of ``container-drift``, kept separate because its artifact
    is a git checkout, not an image. Unlike the container case, comparing
    *versions* is sound here: both sides are ``git describe`` of the same repo —
    one namespace, so equality means what it looks like.

    This is the drift most likely to actually happen. A container image is
    effectively immutable once pulled, but the toolbox is a git checkout on a
    group-writable shared path: any lab member's ``git pull`` silently changes
    denoising for every project pointing at it, with no path or config change to
    notice. A ``-dirty`` marker likewise surfaces a hand-edited toolbox.
    """
    if not read_derivative_provenance(config, "nordic").exists:
        return []
    recorded = _recorded_toolbox(config)
    current = describe(nordic_toolbox_dir(config))
    if not recorded or not current or recorded == current:
        return []
    return [ConsistencyIssue(
        "toolbox-drift", stage="nordic",
        message=(
            f"The NORDIC toolbox is now at `{current}`, but the existing NORDIC "
            f"derivative was produced with `{recorded}`. The checkout moved (a "
            "`git pull`, or a local edit if marked -dirty) — the derivative no "
            "longer reflects the toolbox that would run today. Re-run NORDIC, or "
            "check out the recorded version."),
    )]


def _release_line(version: str) -> str:
    """The part of *version* whose change implies a change in behavior, or "".

    duckbrain is developed in rapid increments and every derivative records the
    exact commit, so comparing full versions would flag constantly and mean
    nothing. Semver says only a major bump breaks — and pre-1.0, that role falls
    to *minor* (``0.1`` → ``0.2`` may break, ``0.1.0`` → ``0.1.4`` may not). So
    ``v0.1.0``, ``v0.1.0-3-gabc1234`` and ``v0.1.4-dirty`` all reduce to ``0.1``:
    iteration within a release line is invisible, a new line is not.

    An unparseable version — a bare sha from an untagged checkout — yields "",
    meaning unknowable. Never a guess.
    """
    m = re.match(r"v?(\d+)\.(\d+)", version.strip())
    if not m:
        return ""
    major, minor = int(m.group(1)), int(m.group(2))
    return f"{major}.{minor}" if major == 0 else str(major)


# Stages where duckbrain *authors the recipe*, so its own version bears on the
# output. Everywhere else it merely launches a container with flags — duckbrain
# v0.1.0 and v0.9.0 passing identical flags to one fMRIPrep image produce
# identical results, and flagging that would be noise with no signal under it.
_DUCKBRAIN_RECIPE_STAGES = {
    "converted": (
        "duckbrain generates the dcm2bids config — which series become T1w/bold, "
        "task names, fieldmap pairing — so a release-line change can alter the "
        "BIDS layout itself"),
    "nordic": (
        "duckbrain supplies NORDIC's MATLAB entrypoint and sbatch recipe, so a "
        "release-line change can alter what NORDIC actually does"),
}


def _check_duckbrain_drift(config: dict) -> list[ConsistencyIssue]:
    """duckbrain's own release line has moved since it produced an output.

    Deliberately *not* held to the same standard as fMRIPrep/NORDIC drift, on two
    counts. First, it is a different kind of fact: a tool's version **is** the
    computation, whereas duckbrain's is the recipe-writer — so this is raised at
    ``note`` severity, not ``warning``. Second, it is limited to the stages where
    duckbrain actually writes the recipe (``_DUCKBRAIN_RECIPE_STAGES``); for
    fMRIPrep/MRIQC duckbrain is a launcher and its version says nothing about the
    data.

    Only the *release line* is compared, so rapid development between releases
    stays silent. Dataset-level by nature: duckbrain stamps the dataset root, not
    each subject, so mixed duckbrain versions *within* one dataset are invisible
    here — accepted deliberately rather than add a log column for a question
    ("which duckbrain converted sub-07") that metadata management doesn't ask.
    """
    current = _release_line(duckbrain_version())
    if not current:
        return []
    roots = {
        "converted": Path(config["paths"]["bids_dir"]),
        "nordic": Path(config["paths"]["derivatives_dir"]) / "nordic",
    }
    issues: list[ConsistencyIssue] = []
    for stage, why in _DUCKBRAIN_RECIPE_STAGES.items():
        prov = read_provenance_at(roots[stage])
        if not prov.exists:
            continue
        recorded = _release_line(prov.tool_version("duckbrain"))
        if not recorded or recorded == current:
            continue
        issues.append(ConsistencyIssue(
            "duckbrain-drift", severity="note", stage=stage,
            message=(
                f"This output was produced by duckbrain {recorded}.x; duckbrain is "
                f"now {current}.x. Not a problem in itself — but {why}. Worth "
                "noting for provenance; re-run only if you want the current "
                "behavior."),
        ))
    return issues


def _check_matlab_drift(config: dict) -> list[ConsistencyIssue]:
    """The MATLAB module changed since it produced the NORDIC derivative.

    NORDIC's *second* version axis. A container stage has only one — the image is
    both runtime and code — but NORDIC's runtime (MATLAB) and code (the toolbox
    checkout) move independently, so a `matlab_module` bump is invisible to
    ``toolbox-drift`` and needs its own check.
    """
    if not read_derivative_provenance(config, "nordic").exists:
        return []
    recorded = _recorded_runtime(config, "nordic")
    current = matlab_module(config)
    if not recorded or not current or recorded == current:
        return []
    return [ConsistencyIssue(
        "matlab-drift", stage="nordic",
        message=(
            f"NORDIC now runs under `{current}`, but the existing derivative was "
            f"produced under `{recorded}`. The MATLAB module changed without a "
            "re-run — the derivative reflects a different runtime than the one "
            "that would run today."),
    )]


# ---- NORDIC sidecars: per-file provenance -----------------------------------
#
# The source rule this codebase follows:
#
#   derivatives duckbrain *produces* (nordic)    → provenance lives IN the data
#   derivatives *tools* produce (fmriprep/mriqc) → the log, the only channel we have
#
# duckbrain writes NORDIC's outputs, so it stamps each one (``write_nordic_sidecars``)
# — and those sidecars are the only source correct at NORDIC's real granularity.
# The sbatch skips already-denoised runs, so one subject's files can genuinely carry
# *different* provenance (a partial array failure re-launched after a toolbox bump
# leaves survivors on the old toolbox). The log records one row per submission, so
# its latest-per-subject view would report the new toolbox for all of them.


def read_nordic_sidecars(config: dict) -> list[dict]:
    """Per-file provenance from every NORDIC output sidecar.

    Each entry is the sidecar's ``Duckbrain`` object plus a ``subject`` key.
    Sidecars without one (produced before duckbrain wrote them, or by other
    means) are skipped — unknowable, not evidence.
    """
    root = Path(config["paths"]["derivatives_dir"]) / "nordic"
    found: list[dict] = []
    try:
        paths = sorted(root.glob("sub-*/**/func/*_bold.json"))
    except (OSError, ValueError):
        return []
    for path in paths:
        prov = _read_json(path).get("Duckbrain")
        if not isinstance(prov, dict) or not prov:
            continue
        subject = path.name.split("_", 1)[0].removeprefix("sub-")
        found.append({**prov, "subject": subject})
    return found


def _sidecar_groups(config: dict, field: str) -> dict[str, list[str]]:
    """Subjects grouped by their sidecars' *field* value, blanks ignored.

    A subject appears under two values when its own files disagree — which is
    real, and precisely what the log cannot express.
    """
    groups: dict[str, set[str]] = {}
    for prov in read_nordic_sidecars(config):
        value = str(prov.get(field, "")).strip()
        if value:
            groups.setdefault(value, set()).add(prov["subject"])
    return {v: sorted(subs) for v, subs in groups.items()}


def _sidecar_consensus(config: dict, field: str) -> str | None:
    """The one *field* value all NORDIC sidecars agree on.

    ``""`` when they disagree — mixing is ``_check_mixed_provenance``'s business,
    not drift's. ``None`` when no sidecar records the field at all, so the caller
    can fall back rather than read silence as agreement.
    """
    groups = _sidecar_groups(config, field)
    if not groups:
        return None
    return next(iter(groups)) if len(groups) == 1 else ""


def _recorded_runtime(config: dict, stage: str) -> str:
    """Runtime recorded for *stage*'s derivative, or "" if unknown.

    Sidecars first — they are per-file, so the most specific truth we hold. Then
    the dataset-level ``GeneratedBy`` entry ``_runtime_generated_by`` writes (a
    non-container runtime has no dedicated BIDS field, so MATLAB gets its own
    entry).
    """
    consensus = _sidecar_consensus(config, "Runtime")
    if consensus is not None:
        return consensus
    for entry in read_derivative_provenance(config, stage).generated_by:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name", ""))
        if name and name.lower() == "matlab":
            version = str(entry.get("Version", ""))
            return f"{name}/{version}" if version else name
    return ""


def _recorded_toolbox(config: dict) -> str:
    """``git describe`` recorded for the NORDIC derivative, or "" if unknown.

    Sidecars first (per-file, so the most specific), then the dataset-level
    ``GeneratedBy`` — which the *last* launch overwrites, so it cannot represent a
    part-re-run derivative. Unknowable → "", never a guess: a NORDIC tree produced
    before duckbrain recorded this, or by other means, is not evidence of drift.
    """
    consensus = _sidecar_consensus(config, "ToolVersion")
    if consensus is not None:
        return consensus
    return read_derivative_provenance(config, "nordic").tool_version("nordic")


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


def _mixed_issue(check: str, stage: str, label: str, what: str,
                 groups: dict[str, list[str]]) -> list[ConsistencyIssue]:
    if len(groups) < 2:
        return []
    return [ConsistencyIssue(
        check, stage=stage,
        message=(
            f"{label} was run under different {what} within the same derivative "
            f"({_describe_groups(groups)}). Re-run so it is uniform."),
    )]


def _check_mixed_provenance(config: dict) -> list[ConsistencyIssue]:
    """Subjects (or files) produced under different variants/versions/runtimes.

    ``dataset_description.json`` is dataset-level and overwritten by whichever run
    finished last, so mixing is invisible there. The source used per stage follows
    the rule above: duckbrain writes NORDIC's files, so their sidecars are read;
    fMRIPrep's outputs are its own, so the submission log is the only channel.
    """
    issues: list[ConsistencyIssue] = []

    # fMRIPrep — log overlay (duckbrain cannot write into fMRIPrep's outputs).
    latest = _latest_per_subject(config, "fmriprep")
    if latest:
        issues += _mixed_issue(
            "mixed-provenance", "fmriprep", "fMRIPrep", "input variants across subjects",
            _group_subjects_by(latest, "input_variant"))
        issues += _mixed_issue(
            "mixed-version", "fmriprep", "fMRIPrep", "tool versions across subjects",
            _group_subjects_by(latest, "tool_version"))
        issues += _mixed_issue(
            "mixed-runtime", "fmriprep", "fMRIPrep", "runtimes across subjects",
            _group_subjects_by(latest, "runtime"))

    # NORDIC — its own sidecars, the only source correct per *file*. A subject
    # listed under two values means its own runs disagree (a part re-run), which
    # the log's one-row-per-subject view cannot express. Input variant is not
    # checked: NORDIC always consumes raw.
    issues += _mixed_issue(
        "mixed-version", "nordic", "NORDIC", "toolbox versions",
        _sidecar_groups(config, "ToolVersion"))
    issues += _mixed_issue(
        "mixed-runtime", "nordic", "NORDIC", "runtimes",
        _sidecar_groups(config, "Runtime"))
    return issues


def _group_subjects_by(latest: dict[str, dict], column: str) -> dict[str, list[str]]:
    """Subjects grouped by their recorded *column* value, ignoring blanks.

    Blanks are "unknown", not a distinct value — otherwise a derivative half of
    whose runs predate a provenance field would read as mixed.
    """
    groups: dict[str, list[str]] = {}
    for subject, row in latest.items():
        value = str(row.get(column, "")).strip()
        if value:
            groups.setdefault(value, []).append(subject)
    return groups


def _describe_groups(groups: dict[str, list[str]]) -> str:
    return "; ".join(f"{v}: {', '.join(sorted(s))}" for v, s in sorted(groups.items()))


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
        _check_toolbox_drift,
        _check_matlab_drift,
        _check_duckbrain_drift,
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
