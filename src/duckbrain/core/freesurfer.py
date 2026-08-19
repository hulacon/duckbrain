"""External FreeSurfer recon — a producer stage upstream of fMRIPrep.

Runs the system FreeSurfer's ``recon-all`` (8.x on Talapas) as its own SLURM
stage, so fMRIPrep imports that reconstruction instead of building one with the
FreeSurfer bundled in its container (7.3.2 as of fMRIPrep 25.2). Asked for by
LCNI, whose pipeline already works this way; the design record and the two traps
are ``docs/pipeline-extras.md`` §9.

Three properties of the design, each load-bearing:

* **The recon lands where fMRIPrep already looks.** With the default
  ``--output-layout bids``, fMRIPrep's ``fs_subjects_dir`` defaults to
  ``<derivatives>/fmriprep/sourcedata/freesurfer`` — so a completed recon at
  :func:`subject_import_dir` is found with no ``--fs-subjects-dir`` flag at all.
  The one flag that IS required is ``--fs-no-resume``: without it, fMRIPrep
  judges any recon it dislikes *resumable* and quietly finishes it with its own
  bundled FreeSurfer — a partly-FS7 surface while you believe you got FS8, the
  silently-degrading-option rule verbatim. ``pipeline._build_fmriprep`` refuses
  to submit an external-recon project without a complete, version-matched recon
  in place, and adds the flag itself.

* **recon-all never writes into the shared subjects dir.** That directory is
  the one every concurrent fMRIPrep job installs ``fsaverage`` into — the
  ``#21`` race, closed by seeding (``core/fsaverage.py``); an in-progress recon
  would be a second writer, and recon-all also drops its *own* FreeSurfer-8
  ``fsaverage`` into whatever ``SUBJECTS_DIR`` it runs under, which must not
  displace the seeded FreeSurfer-7 tree fMRIPrep's manifest check expects. So
  the sbatch recons under :func:`staging_subjects_dir` — a dot-prefixed
  directory the surveyor's globs never match — and only a recon that finished
  (``scripts/recon-all.done`` present, exit 0) is renamed into place. Same
  GPFS filesystem, so the rename is atomic: the import dir either holds a
  complete recon or none.

* **Version identity comes from the recon itself, not the directory's
  existence.** fMRIPrep's own recon writes to the *identical* path, so "a
  subject dir exists" cannot distinguish an FS8 recon from a leftover FS7 one.
  The gate is ``scripts/build-stamp.txt`` — written by recon-all, naming the
  exact build — checked against the pinned ``[freesurfer] version`` by both the
  surveyor tracker and the fMRIPrep builder. A mismatched recon is refused with
  the fix stated, never silently imported and never silently deleted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from .ingestion import nii_glob

if TYPE_CHECKING:
    from ..config import Config


def fs_config(config: Config) -> dict[str, object]:
    """The ``[freesurfer]`` section, or ``{}``."""
    section = config.get("freesurfer", {})
    return section if isinstance(section, dict) else {}


def use_external_fs(config: Config) -> bool:
    """Whether this project runs the external-recon stage feeding fMRIPrep."""
    return bool(fs_config(config).get("use_external", False))


def fs_version(config: Config) -> str:
    """Pinned FreeSurfer version for the external recon, e.g. ``8.2.0``."""
    return str(fs_config(config).get("version", "") or "")


def fs_bin_dir(config: Config) -> Path:
    """``bin/`` of the pinned system FreeSurfer install.

    Talapas installs each FreeSurfer as an Apptainer image fronted by thin bash
    wrappers in ``<install_root>/<version>/bin`` — so ``recon-all`` is a plain
    host command, but a container underneath, and must never be invoked from
    *inside* another container. Resolved from the pin rather than trusting
    whatever ``recon-all`` is first on ``PATH``, which tracks the site default
    and can move under us.
    """
    root = str(fs_config(config).get("install_root", "/packages/freesurfer") or "")
    return Path(root) / fs_version(config) / "bin"


def import_subjects_dir(derivatives_dir: str | Path) -> Path:
    """The shared subjects dir fMRIPrep reads with no flag (its default)."""
    return Path(derivatives_dir) / "fmriprep" / "sourcedata" / "freesurfer"


def subject_import_dir(derivatives_dir: str | Path, subject: str) -> Path:
    """Where sub-*subject*'s completed recon must sit for fMRIPrep to find it."""
    return import_subjects_dir(derivatives_dir) / f"sub-{subject}"


def staging_subjects_dir(derivatives_dir: str | Path, subject: str) -> Path:
    """Per-subject ``SUBJECTS_DIR`` the recon actually runs under.

    Dot-prefixed so no surveyor glob ever matches into it, *per-subject* so two
    concurrent recons never share a staging dir (recon-all copies fsaverage into
    its ``SUBJECTS_DIR``, and a shared staging root would re-create the ``#21``
    copy race one level down). On the same filesystem as the import dir so the
    final rename is atomic.
    """
    return import_subjects_dir(derivatives_dir) / ".recon-staging" / f"sub-{subject}"


def recon_done_file(subject_dir: str | Path) -> Path:
    """recon-all's run marker inside one subject's recon.

    NOT a success marker on its own. FreeSurfer 8's recon-all writes this file
    on **both** exit paths — the success block fills it with a rich record
    (``SUBJECT``/``START_TIME``/``END_TIME``/…), the error path writes the
    single line ``1`` (``bin/recon-all``, the ``echo "1" > $DoneFile`` arm) —
    and the pilot proved it: an OOM-killed run left a stub recon carrying both
    this file and ``recon-all.error``, and the first import gate waved it
    through (fs8_pilot job 46353636/46358868, 2026-08-19). Success is
    :func:`done_marks_success` + no error file + the artifacts, never bare
    existence.
    """
    return Path(subject_dir) / "scripts" / "recon-all.done"


def recon_error_file(subject_dir: str | Path) -> Path:
    """recon-all's error marker. Both markers are ``rm -f``-ed at the start of
    every run (same source, the ``rm -f $DoneFile`` / ``rm -f $ErrorFile``
    pair), so a stale error can never linger past a later successful re-run."""
    return Path(subject_dir) / "scripts" / "recon-all.error"


def done_marks_success(subject_dir: str | Path) -> bool:
    """Whether the done file carries the success-path record.

    The success block always writes an ``END_TIME`` line; the error path
    writes only ``1``. Checked positively for the success format rather than
    negatively against the sentinel, so an unrecognized future format fails
    closed.
    """
    try:
        text = recon_done_file(subject_dir).read_text()
    except OSError:
        return False
    return any(line.startswith("END_TIME") for line in text.splitlines())


#: The recon artifacts fMRIPrep's import actually consumes — the
#: ``--fs-no-resume`` contract makes their presence *our* responsibility
#: ("The user is responsible for ensuring that all necessary files are
#: present"). A marker-only gate is one semantics change away from importing
#: a stub; these cannot be argued with.
_REQUIRED_ARTIFACTS = (
    "surf/lh.white",
    "surf/rh.white",
    "surf/lh.pial",
    "surf/rh.pial",
    "mri/aparc+aseg.mgz",
)


def build_stamp(subject_dir: str | Path) -> str:
    """First line of ``scripts/build-stamp.txt``, or ``""``.

    recon-all writes it into every recon it produces, naming the exact build
    (e.g. ``freesurfer-linux-ubuntu22.04_x86_64-8.2.0-...``) — the one on-disk
    fact that distinguishes an FS8 recon from an FS7 one at the same path.
    """
    try:
        text = (Path(subject_dir) / "scripts" / "build-stamp.txt").read_text()
    except OSError:
        return ""
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def stamp_version(stamp: str) -> str:
    """The ``X.Y.Z`` version embedded in a build stamp, or ``""``."""
    m = re.search(r"-v?(\d+\.\d+\.\d+(?:[^-\s]*)?)", stamp)
    return m.group(1) if m else ""


def recon_complete(config: Config, subject_dir: str | Path) -> bool:
    """Whether *subject_dir* holds a finished recon from the pinned FreeSurfer.

    Four requirements, each carrying real weight:

    * the done file in its **success format** (:func:`done_marks_success`) —
      bare existence also matches every failed FS8 run;
    * **no** ``recon-all.error`` — written by the failure path, cleared at the
      start of every run, so it is exactly "the last run failed";
    * the build stamp matching the exact ``[freesurfer] version`` pin —
      ``recon-all.done`` alone also matches fMRIPrep's own FS7 recon at the
      identical path, and after a pin bump an existing recon deliberately
      stops grading complete (same posture as the fMRIPrep drift check; the
      launch-gate message states the two ways out);
    * the surfaces and segmentation fMRIPrep's import consumes
      (``_REQUIRED_ARTIFACTS``) — the ``--fs-no-resume`` contract puts their
      presence on us, and no marker semantics can fake them.
    """
    subject_dir = Path(subject_dir)
    if not done_marks_success(subject_dir):
        return False
    if recon_error_file(subject_dir).exists():
        return False
    if stamp_version(build_stamp(subject_dir)) != fs_version(config):
        return False
    return all((subject_dir / rel).is_file() for rel in _REQUIRED_ARTIFACTS)


def container_visible(path: str | Path) -> str:
    """*path* respelled so it resolves inside Talapas's Apptainer containers.

    ``recon-all`` here is a bash wrapper that ``apptainer exec``s into the
    FreeSurfer image, and every path handed to it crosses that boundary with
    only the site's default binds (``/projects``, ``/tmp``, ``/scratch``,
    ``$HOME``) — no explicit ``-B`` saves it, unlike duckbrain's own templates.
    On Talapas ``/projects`` is a symlink to ``/gpfs/projects``: the short form
    resolves on the host *and* inside any container, the ``/gpfs/`` form only on
    the host (verified 2026-07-24, ``docs/pipeline-extras.md`` §9 Trap 2). So
    the recon sbatch spells every path through this — a no-op for paths already
    on a bound root.
    """
    text = str(path)
    prefix = "/gpfs/projects/"
    return "/projects/" + text[len(prefix) :] if text.startswith(prefix) else text


def t1w_inputs(bids_dir: str | Path, subject: str) -> list[Path]:
    """All of sub-*subject*'s T1w images, across sessions, sorted.

    Subject-wide on purpose: the stage matches fMRIPrep 25's default
    *subject-level* anatomical reference, which merges every session's T1w into
    one anatomical. Raw BIDS always — NORDIC denoises func only, so
    ``use_nordic`` never redirects this. A ``sessionwise`` variant is a
    re-preprocessing-campaign design question, not a latent option here.
    """
    return nii_glob(bids_dir, f"sub-{subject}/**/anat/sub-{subject}*_T1w")


def t2w_inputs(bids_dir: str | Path, subject: str) -> list[Path]:
    """All of sub-*subject*'s T2w images, across sessions, sorted."""
    return nii_glob(bids_dir, f"sub-{subject}/**/anat/sub-{subject}*_T2w")
