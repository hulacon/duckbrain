"""BIDS validation — run the validator that already ships inside the dcm2bids container.

**Why duckbrain invokes the validator rather than using dcm2bids' own
``--bids_validate``.** Ingestion symlinks each session's DICOMs into the tree at
``sourcedata/sub-XX/[ses-YY/]dicom``, and bids-validator 1.14.6 follows that
symlink. Its ``getFilesFromFs`` recurses into a symlinked directory using the
**target** path against an unchanged ``rootPath``, so every file's
``relativePath`` escapes the dataset — the reported paths are literally
``./../../gpfs/projects/…/dicom/*.dcm``. The ignore test then runs against that
escaped path, and the validator's *default* ignore list — which already contains
``/sourcedata``, ``/derivatives`` and ``/code`` — cannot match it.

So **no ``.bidsignore`` entry can fix this**: the default ignore is already
stronger than any entry duckbrain could write, and it still does not fire. That
is why ``config._BIDSIGNORE_ENTRIES`` has no ``sourcedata/`` line and must not
gain one. The only knob is the CLI flag ``--ignoreSymlinks``, and dcm2bids offers
no way to pass it — ``dcm2bids_gen.py`` calls ``run_shell_command(['bids-validator',
bids_dir])`` over a ``Popen`` wrapper that returns stdout and never inspects the
return code, so the flag could not have failed a job even had it produced a
usable answer.

Measured on real projects before this module existed: on ``dwi_eyeball`` the old
invocation indexed 2605 files / 6.06 GB and reported 2540 ``NOT_INCLUDED``
errors; with ``--ignoreSymlinks`` it indexes 66 files / 2.11 GB, reports zero,
and takes 0.98 s. On ``divatten_beta_v2``, whose derivatives are 147 GB, 293
files in 3.5 s.

**A clean run is not an all-clear.** The validator checks that data is well
*formed* — structure and naming — not that it means what was intended. Run
against a tree whose ``B0FieldIdentifier``/``B0FieldSource`` were inverted, it
reported zero fieldmap issues while fMRIPrep silently skipped distortion
correction. That gap is what ``TODO #16`` exists for, and the cockpit panel says
so where someone reading a clean result will see it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .containers import isolation_flags

#: Generous: the measured runs are seconds, but a dataset with a very large
#: derivatives tree still has to be walked, and a timeout that fires is reported
#: as "could not run" rather than as a clean dataset.
VALIDATOR_TIMEOUT_S = 300

#: How many file paths one issue carries into the GUI. The flood this module
#: exists to fix was 2540 paths in a log; repeating them in an expander would be
#: the same can't-see-the-signal failure one layer up. The full count is kept.
_MAX_FILES_PER_ISSUE = 10


@dataclass(frozen=True)
class ValidationIssue:
    """One finding, collapsed across the files it applies to.

    ``severity`` uses the ``"error"``/``"warning"`` vocabulary shared with
    :class:`~duckbrain.core.consistency.ConsistencyIssue`, so a reader does not
    have to learn a second one. ``n_files`` is the **full** count; ``files`` holds
    at most :data:`_MAX_FILES_PER_ISSUE` of them.
    """

    code: str
    severity: str
    reason: str
    n_files: int = 0
    files: tuple[str, ...] = ()
    help_url: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of one validator run, including the case where it could not run."""

    bids_dir: str
    ran_at: datetime
    duration_s: float = 0.0
    unavailable_reason: str = ""
    issues: tuple[ValidationIssue, ...] = ()
    summary: dict = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        """False when the validator never executed — never confuse this with clean."""
        return not self.unavailable_reason

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity != "error")

    def headline(self) -> str:
        """One phrase for an expander label, folding the state into the title."""
        if not self.ran:
            return "could not run"
        stamp = self.ran_at.strftime("%H:%M:%S")
        if not self.issues:
            return f"clean ({stamp})"
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error{'s' if len(self.errors) != 1 else ''}")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning{'s' if len(self.warnings) != 1 else ''}")
        return f"{', '.join(parts)} ({stamp})"


def validator_command(
    container: str | Path,
    bids_dir: str | Path,
    *,
    json_output: bool = False,
) -> list[str]:
    """The argv that runs bids-validator over *bids_dir* inside *container*.

    ``exec``, not ``run``: the dcm2bids image's runscript **is** dcm2bids, so
    ``singularity run <sif> bids-validator …`` would hand those tokens to dcm2bids
    as arguments and never reach the validator.

    ``--ignoreSymlinks`` is the whole point — see the module docstring. It stops
    symlinked *directories* being descended; a symlinked file is still reported
    with its correct in-dataset path, and duckbrain creates none inside the BIDS
    root anyway (NORDIC staging hardlinks or copies).

    ``singularity`` is hard-coded, matching :mod:`duckbrain.core.fsaverage` and
    every sbatch template. :mod:`duckbrain.core.dcm2niix_probe` instead prefers
    ``apptainer`` via ``shutil.which``; the two dialects are a real inconsistency,
    and this one is chosen here because the sbatch template renders these exact
    tokens and a test asserts the two argvs are identical. Resolution that could
    differ between the login node and a compute node would break that.

    *json_output* is the one divergence between the two call sites: the sbatch
    omits it (a human reads the SLURM log), the GUI passes it.
    """
    bids_dir = str(bids_dir)
    cmd = [
        "singularity",
        "exec",
        *isolation_flags(),
        "-B",
        f"{bids_dir}:{bids_dir}",
        str(container),
        "bids-validator",
        "--ignoreSymlinks",
    ]
    if json_output:
        cmd.append("--json")
    cmd.append(bids_dir)
    return cmd


def validator_unavailable_reason(container: str | Path | None, bids_dir: str | Path | None) -> str:
    """Why the validator cannot run here, or ``""`` when it can.

    A check that cannot run must say so rather than pass — the contract
    :func:`~duckbrain.core.dcm2niix_probe.probe_unavailable_reason` states. An
    empty issue list from a run that never happened would render as a clean
    dataset, which is the silently-wrong-answer class CLAUDE.md forbids.
    """
    if not bids_dir:
        return "no BIDS directory is configured"
    if not Path(bids_dir).is_dir():
        return f"BIDS directory not found: {bids_dir}"
    if not container:
        return "no dcm2bids container is configured"
    if not Path(container).exists():
        return f"container image not found: {container}"
    if not shutil.which("singularity"):
        return "singularity is not on PATH"
    return ""


def parse_validator_output(payload: str) -> tuple[tuple[ValidationIssue, ...], dict]:
    """Read ``bids-validator --json`` output into issues and its summary.

    Tolerant of leading noise on stdout (the container emits a Node warning about
    directory handles), so it scans for the first ``{`` rather than parsing the
    whole stream. Errors first, then warnings, each in the validator's own order.
    """
    data = _first_json_object(payload)
    issues_by_severity = data.get("issues") or {}
    out: list[ValidationIssue] = []
    for key, severity in (("errors", "error"), ("warnings", "warning")):
        for raw in issues_by_severity.get(key) or []:
            out.append(_issue(raw, severity))
    return tuple(out), (data.get("summary") or {})


def _first_json_object(payload: str) -> dict:
    start = payload.find("{")
    if start < 0:
        return {}
    try:
        data = json.loads(payload[start:])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _issue(raw: dict, severity: str) -> ValidationIssue:
    entries = raw.get("files") or []
    paths = []
    for entry in entries:
        # A dataset-level finding carries `files: [null]`, or an entry with no
        # `file` key at all — DATASET_DESCRIPTION_JSON_MISSING is about a file
        # that by definition isn't there.
        location = (entry or {}).get("file") or {}
        path = location.get("relativePath") or location.get("name") or ""
        if path:
            paths.append(path)
    return ValidationIssue(
        code=str(raw.get("key") or raw.get("code") or "UNKNOWN"),
        severity=severity,
        reason=str(raw.get("reason") or "").strip(),
        n_files=len(entries),
        files=tuple(paths[:_MAX_FILES_PER_ISSUE]),
        help_url=str(raw.get("helpUrl") or ""),
    )


def validate_bids(config: dict, *, timeout_s: int = VALIDATOR_TIMEOUT_S) -> ValidationResult:
    """Run the validator over the project's BIDS root and read its findings back.

    **Deliberately not memoised**, unlike :mod:`duckbrain.core.fsaverage`, which
    caches against a container image — immutable, so a cached answer cannot go
    wrong. A BIDS tree changes underneath you, and a cache keyed on its path would
    serve a stale "clean" after a bad conversion. Freshness comes instead from
    this being a user-triggered action whose ``ran_at`` is rendered, so a past
    measurement reads as a past measurement.
    """
    from .pipeline import resolve_container

    bids_dir = (config.get("paths") or {}).get("bids_dir", "")
    try:
        container = resolve_container(config, "converted")
    except Exception:
        container = None

    reason = validator_unavailable_reason(container, bids_dir)
    if reason:
        return ValidationResult(
            bids_dir=str(bids_dir), ran_at=datetime.now(), unavailable_reason=reason
        )

    cmd = validator_command(container, bids_dir, json_output=True)
    started = time.monotonic()
    try:
        proc = _run_validator(cmd, timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        return ValidationResult(
            bids_dir=str(bids_dir),
            ran_at=datetime.now(),
            duration_s=time.monotonic() - started,
            unavailable_reason=f"could not run bids-validator: {exc}",
        )
    duration = time.monotonic() - started

    # The validator exits 1 whenever it found errors, so the status says nothing
    # about whether it *worked*. Read the JSON; only an unparseable stream means
    # the run failed.
    issues, summary = parse_validator_output(proc.stdout or "")
    if not summary and not issues and not _first_json_object(proc.stdout or ""):
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return ValidationResult(
            bids_dir=str(bids_dir),
            ran_at=datetime.now(),
            duration_s=duration,
            unavailable_reason=f"bids-validator produced no readable report: {tail}",
        )

    return ValidationResult(
        bids_dir=str(bids_dir),
        ran_at=datetime.now(),
        duration_s=duration,
        issues=issues,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# The one container call, isolated so everything above can be tested without one
# ---------------------------------------------------------------------------


def _run_validator(cmd: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout_s)
