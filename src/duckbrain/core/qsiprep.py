"""QSIPrep orchestration — the diffusion branch.

An **orthogonal** stage: a whole separate modality running parallel to the BOLD
pipeline, sharing only BIDS. It reads raw ``dwi/`` and writes
``<derivatives>/qsiprep``. Design record: ``docs/pipeline-extras.md`` §1, which
is where the three traps below are argued at length.

**"Why doesn't qsiprep reuse the anat like fMRIPrep does?"** — the first question
a reader has, so it is answered here rather than left to be re-derived. Two
independent reasons, and the second is the stronger: QSIPrep has no anat-reuse
flag at all (no ``--derivatives``, no ``--anat-derivatives``, no
``--fs-subjects-dir``), *and* its anatomical is LPS+ and AC-PC realigned where
fMRIPrep's is RAS+ in the original orientation. Sharing anat derivatives between
the two is not merely unsupported, it is wrong. So the stage's ``depends_on`` is
the plain string ``"converted"`` and the dependency graph stays as simple as it
is today.

Three things this module exists to refuse rather than guess (``CLAUDE.md``: a
silently-degrading option is worse than one that fails):

* ``--output-resolution`` is required by QSIPrep and has no default. It is the
  isotropic mm everything is resampled to, in a single interpolation, and a
  wrong value produces data that looks entirely usable and is wrongly sampled —
  a study-level scientific choice, not a tuning knob. Shipped commented out (the
  ``[expected]`` precedent) and raised on rather than defaulted.
* ``--subject-anatomical-reference`` defaults to ``first-lex``, which builds the
  subject's ACPC anatomical reference from one session and writes it at the
  *subject* level. duckbrain's unit is ``(subject, session)``, so two sessions
  launched under that default silently overwrite each other's anat and report,
  last writer wins. ``sessionwise`` is the default here and anything else is
  refused for a session-scoped unit.
* ``--separate-all-dwis`` is deliberately **not** forced to keep duckbrain's
  status column 1:1 with its inputs. That would trade preprocessing quality —
  less data for head-motion correction — for the convenience of a grader. The
  surveyor absorbs the merge instead (``surveyor._covers``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config

#: What ``--subject-anatomical-reference`` must be for a session-scoped unit.
#: See the module docstring's second bullet — the alternatives write one
#: session's anat over another's at the subject level.
SESSIONWISE = "sessionwise"

#: ...and what a **sessionless** unit must get instead, which is the opposite
#: answer for a reason read out of QSIPrep 26.0.0's own source rather than its
#: docs. ``parser.py`` puts a subject with no sessions in the processing group
#: ``[subject, []]`` and warns; ``reports/core.py`` then takes the sessionwise
#: branch, which loops over that empty session list — so **no HTML report is
#: written at all**. Every other reference value takes the branch that does write
#: one. Since a dataset with no sessions has nothing to combine across, the four
#: choices are otherwise indistinguishable there, which is what makes overriding
#: a configured value safe here and not a silent behaviour change.
SESSIONLESS_REFERENCE = "first-lex"


#: Where each pinned image keeps the ``qsiprep`` package. A bind-mounted patch
#: must land exactly on the file it replaces, so this is read out of the image
#: once per version and pinned, never derived. See ``patches/qsiprep/README.md``.
QSIPREP_PACKAGE_DIRS = {
    "26.0.0": "/app/.pixi/envs/qsiprep/lib/python3.10/site-packages/qsiprep",
}

#: The files ``patch_grouping`` mounts, per pinned version, relative to the
#: package. All serve one layout — opposing-PE pairs on two axes, merged with
#: ``--distortion-group-merge concat``: ``grouping.py`` keeps the second pair from
#: being dropped, and the rest backport upstream's repair of the merge that follows.
QSIPREP_PATCH_FILES = {
    "26.0.0": (
        "utils/grouping.py",
        "workflows/base.py",
        "workflows/dwi/finalize.py",
        "workflows/dwi/distortion_group_merge.py",
        "interfaces/dwi_merge.py",
        "interfaces/reports.py",
    ),
}


class QsiprepConfigError(ValueError):
    """A ``[qsiprep]`` setting cannot do what it says.

    Raised rather than degraded, per ``CLAUDE.md``: a flag that quietly does
    something else costs a run nobody knows to distrust. ``core.pipeline``
    re-raises it as a ``PipelineError`` so the GUI shows the message.
    """


def get_container_path(config: Config) -> Path:
    """Path to the QSIPrep Singularity image named by ``[containers]``.

    Same resolution order as the other tool modules: the pinned
    ``<tool>-<version>`` spellings first, then an unversioned fallback for a
    hand-placed image. Returns the canonical name when nothing exists, so the
    caller's "container not found" message names what it looked for.
    """
    containers_dir = Path(config["paths"]["containers_dir"])
    version = config["containers"]["qsiprep_version"]
    for pattern in [
        f"qsiprep-{version}.sif",
        f"qsiprep-{version}.simg",
        f"qsiprep_{version}.sif",
        "qsiprep.sif",
        "qsiprep.simg",
    ]:
        path = containers_dir / pattern
        if path.exists():
            return path
    return containers_dir / f"qsiprep-{version}.sif"


def get_dwi_runs(bids_dir: str | Path, subject: str, session: str) -> list[Path]:
    """Diffusion NIfTIs for one unit — the run-count source of truth for this stage.

    ``*_dwi`` only: a ``_sbref`` in the same directory is a reference image, not
    a run, and counting it would invent a shortfall QSIPrep can never make up.
    Both NIfTI spellings, via ``ingestion.nii_glob``, for the same reason
    ``get_bold_runs`` takes both — an adopted uncompressed tree must count.

    Shared by the surveyor's expectation and by :func:`has_dwi`, so "this unit
    has diffusion" and "this is how many runs it owes" cannot disagree.
    """
    from .ingestion import nii_glob, sub_ses_relpath

    dwi_dir = Path(bids_dir) / sub_ses_relpath(subject, session) / "dwi"
    if not dwi_dir.is_dir():
        return []
    return nii_glob(dwi_dir, "*_dwi")


def has_dwi(bids_dir: str | Path, subject: str, session: str) -> bool:
    """Whether this unit has diffusion data at all.

    The stage's applicability is **per-unit data**, not a project-level config
    question like NORDIC's ``use_nordic``: one session can have DWI and the next
    not. Without that distinction the rollup, the bulk "run all" and the
    all-complete message are each poisoned by rows that will never have anything
    to run (``TODO.md`` ``#17.4``, whose lesson this is).
    """
    return bool(get_dwi_runs(bids_dir, subject, session))


def output_resolution(config: Config) -> float | None:
    """The configured ``--output-resolution`` in mm, or ``None`` when **unset**.

    ``None`` is the shipped state and is what the launcher raises on. Returning
    it rather than a number is the whole point: see the module docstring.

    "Unset" and "set to something that is not a number" are kept apart, and a
    caller must be able to tell them apart from the answer alone — the same
    distinction :class:`~duckbrain.core.dcm2niix_probe.ProbeResult` draws
    elsewhere in ``core/``, between a probe that read nothing and one that could
    not look. Collapsing both to
    ``None`` made a project that had written ``output_resolution = "two"`` read
    back as one that had never declared it, and the launcher then told its owner
    to set a key they had already set.

    Raises
    ------
    QsiprepConfigError
        The key is present and does not parse as a number of millimetres.
    """
    value = config.get("qsiprep", {}).get("output_resolution")
    if value in (None, ""):
        return None
    return parse_output_resolution(value)


def parse_output_resolution(value: object) -> float:
    """One millimetre value, or :class:`QsiprepConfigError` naming what was wrong.

    Separate from :func:`output_resolution` because the GUI supplies this as free
    text and the config supplies it as TOML — two sources, and both have to fail
    with the same sentence naming the key, or one of them fails with a bare
    ``could not convert string to float: 'two'`` instead.
    """
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise QsiprepConfigError(
            f"[qsiprep] output_resolution must be a number of millimetres, not {value!r}."
        ) from exc


def _patches_dir() -> Path:
    """Locate ``patches/qsiprep/`` the way ``slurm.templates`` locates its templates."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "patches" / "qsiprep"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise FileNotFoundError("Cannot find patches/qsiprep/ directory")


def grouping_patch_binds(config: Config) -> list[str]:
    """Bind specs that mount duckbrain's patched files over the image's, or ``[]``.

    Opt-in through ``[qsiprep] patch_grouping = true``. The patches exist because
    QSIPrep 26.0.0 gives both eddy groups of a session with opposing-PE pairs on
    two axes (AP/PA and LR/RL) the same name, and one of them is then dropped
    without an error; and because once both groups survive, 26.0.0 cannot merge
    them (``concat`` raises in ``MergeDWIs``) and skips their bias correction —
    ``patches/qsiprep/README.md`` has the account. A project without that
    acquisition never needs them, and one that has it must say so.

    A patch is a copy of one file from one release, so it is keyed on the pinned
    ``qsiprep_version``: a version with no patch is **refused**, because mounting
    26.0.0's file into another release would run that release with one module
    silently swapped for an older one.

    Raises
    ------
    QsiprepConfigError
        ``patch_grouping`` is not a boolean, or no patch exists for the pinned
        version.
    """
    enabled = config.get("qsiprep", {}).get("patch_grouping", False)
    if not isinstance(enabled, bool):
        raise QsiprepConfigError(
            f"[qsiprep] patch_grouping must be true or false, not {enabled!r}."
        )
    if not enabled:
        return []
    version = str(config.get("containers", {}).get("qsiprep_version", ""))
    package_dir = QSIPREP_PACKAGE_DIRS.get(version)
    files = QSIPREP_PATCH_FILES.get(version, ())
    patches = [_patches_dir() / version / "qsiprep" / f for f in files]
    missing = [str(p) for p in patches if not p.is_file()]
    if package_dir is None or not files or missing:
        raise QsiprepConfigError(
            f"[qsiprep] patch_grouping is set, but duckbrain has no grouping patch for "
            f"QSIPrep {version!r} (missing: {', '.join(missing) or 'no pinned patch set'}). "
            "Check whether that release still collides eddy-group names and still "
            "fails the merge; port what it still needs, pin its package path in "
            "QSIPREP_PACKAGE_DIRS and its files in QSIPREP_PATCH_FILES, and if it "
            "needs neither, unset the key."
        )
    return [f"{p}:{package_dir}/{f}:ro" for p, f in zip(patches, files, strict=True)]


def anatomical_reference(config: Config, session: str) -> str:
    """The ``--subject-anatomical-reference`` this unit must run with.

    ``sessionwise`` for a session-scoped unit, because duckbrain's unit is
    ``(subject, session)`` and every other value builds one ACPC anatomical
    reference for the whole subject and writes it at the *subject* level — so
    launching two sessions has the second silently overwrite the first's anat
    and report, last writer wins, nothing said. A project that pins something
    else is **refused** rather than allowed to clobber.

    :data:`SESSIONLESS_REFERENCE` for a sessionless one, for the report reason
    recorded on that constant. A configured value is overridden there rather
    than refused: with no sessions the choices are otherwise equivalent, so
    there is nothing to warn anyone about.

    Raises
    ------
    QsiprepConfigError
        A session-scoped unit in a project pinning anything but ``sessionwise``.
    """
    configured = str(config.get("qsiprep", {}).get("anatomical_reference") or SESSIONWISE)
    if not session:
        return SESSIONLESS_REFERENCE
    if configured != SESSIONWISE:
        raise QsiprepConfigError(
            f"[qsiprep] anatomical_reference is {configured!r}, but duckbrain launches "
            f"QSIPrep one session at a time. Only {SESSIONWISE!r} keeps each session's "
            "anatomical reference and report under sub-XX/ses-YY/ — under any other "
            "value the second session launched overwrites the first's at the subject "
            "level and says nothing."
        )
    return SESSIONWISE
