"""Install FreeSurfer's ``fsaverage*`` templates before any fMRIPrep job starts.

fMRIPrep copies ``fsaverage``, plus any ``fsaverageN`` in ``--output-spaces``,
from the container into the shared ``sourcedata/freesurfer`` SUBJECTS_DIR at the
start of *every* run. Concurrent jobs therefore race over one directory, and the
race destroys it. From ``niworkflows.interfaces.bids.BIDSFreeSurferDir``::

    if space == 'fsaverage' and dest.exists() and minimum_fs_version == "7.0.0":
        label = dest / 'label' / 'rh.FG1.mpm.vpnl.label'   # new in FS7
        if not label.exists():
            shutil.rmtree(dest)          # <-- a copy still in progress

fMRIPrep always passes ``minimum_fs_version='7.0.0'``, so the branch is always
armed. Job A creates ``fsaverage/`` and begins streaming 312 files in. Job B
arrives inside that window, sees the directory, does not find the FreeSurfer-7
sentinel (A has not written it yet), concludes the tree is a stale FreeSurfer-6
copy, and deletes it out from under A. Both then write into the same path.
Nothing raises, so nothing reaches any log.

Measured on Talapas GPFS against the 24.1.1 image: a clean ``fsaverage``
copytree is 312 files / 261 MB in **1.83 s**, sentinel at **+0.39 s**. Arrive
before +0.39 s and you destroy the tree; arrive between +0.39 s and +1.83 s and
you skip both the ``rmtree`` *and* the copy and start ``recon-all`` against a
tree that is only partly there. Either way the damage is silent until
``recon-all``'s BA_exvivo stage — three hours later, in the run that found this.

**Staggering submissions is not the fix and this module is not one.** The window
is ~2 s, but the quantity to stagger against is the spread in *when jobs reach
the copy*, which is fMRIPrep's workflow-build time — 61 s in the observed run,
and dependent on BIDS indexing, node load and container cold-start. Two jobs a
minute apart can still collide, and the variance cannot be bounded. Installing
the templates once, before anything is submitted, closes the window instead of
narrowing it: every job then finds the directory present *and* the sentinel
present, so it takes neither the ``rmtree`` nor the copy branch.
``overwrite_fsaverage`` defaults to False and fMRIPrep never sets it, so a
complete tree is left alone.

**Completeness is checked against the container's own manifest, not a sentinel.**
The tree this was found on *contains* ``rh.FG1.mpm.vpnl.label`` and is still 53
files short — which is why fMRIPrep's own self-repair can never fire on it, and
why every future run reuses the broken copy. A checker that asked the same
question fMRIPrep asks would agree the tree was fine.

See ``TODO.md`` ``#21``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: Where fMRIPrep keeps its shared SUBJECTS_DIR, relative to the derivatives
#: root. fMRIPrep's default; duckbrain never passes ``--fs-subjects-dir``.
SUBJECTS_SUBDIR = "fmriprep/sourcedata/freesurfer"

#: Copied by niworkflows on every run whether or not it is an output space, so
#: it is required even when ``--output-spaces`` names no surface space at all.
ALWAYS_REQUIRED = "fsaverage"

#: Flag that turns recon-all off, and with it the whole copy. Nothing needs
#: installing for such a run.
NO_RECONALL_FLAG = "--fs-no-reconall"

#: Prefix for the staging directory a repair copies into before renaming it into
#: place. Leading dot so a half-written tree can never be mistaken for a space.
_STAGING_PREFIX = ".duckbrain-staging-"


class FsaverageError(RuntimeError):
    """The templates could not be verified or installed."""


@dataclass(frozen=True)
class SpaceState:
    """What is on disk for one ``fsaverage*`` space, against the container."""

    space: str
    state: str  # "complete" | "missing" | "incomplete"
    missing: tuple[str, ...] = field(default=())

    @property
    def needs_repair(self) -> bool:
        return self.state != "complete"

    def describe(self) -> str:
        if self.state == "complete":
            return f"{self.space}: complete"
        if self.state == "missing":
            return f"{self.space}: not installed"
        return (
            f"{self.space}: incomplete — {len(self.missing)} file(s) missing, "
            f"e.g. {self.missing[0]}"
        )


def required_spaces(output_spaces, extra_flags: str = "") -> list[str]:
    """Which ``fsaverage*`` templates a run with these settings will copy.

    ``fsaverage`` is always included when recon-all runs, even if no surface
    space was asked for — niworkflows appends it unconditionally, which is
    exactly why a project that never requested a surface space is still exposed.
    """
    if NO_RECONALL_FLAG in (extra_flags or ""):
        return []
    if isinstance(output_spaces, str):
        output_spaces = output_spaces.split()
    spaces = {
        s.split(":", 1)[0]
        for s in (output_spaces or [])
        if s.split(":", 1)[0].startswith("fsaverage")
    }
    spaces.add(ALWAYS_REQUIRED)
    return sorted(spaces)


def subjects_dir(derivatives_dir: str | Path) -> Path:
    """The shared SUBJECTS_DIR every fMRIPrep job in this project will write to."""
    return Path(derivatives_dir) / SUBJECTS_SUBDIR


def plan_repairs(
    manifest: dict[str, set[str]], installed: dict[str, set[str]], spaces: list[str]
) -> list[SpaceState]:
    """Compare what is on disk against the container's manifest. Pure.

    A space is complete only when every file the container carries is present.
    Extra files on disk are ignored: a project may hold real subject directories
    beside the templates, and the templates themselves gain files across
    FreeSurfer versions in ways that are not ours to police.
    """
    states = []
    for space in spaces:
        source = manifest.get(space)
        if not source:
            raise FsaverageError(
                f"The container carries no {space!r} template, so a run asking for "
                f"it cannot work. Check --output-spaces."
            )
        have = installed.get(space)
        if have is None:
            states.append(SpaceState(space, "missing"))
            continue
        gap = sorted(source - have)
        states.append(SpaceState(space, "incomplete" if gap else "complete", tuple(gap)))
    return states


def read_installed(root: Path, spaces: list[str]) -> dict[str, set[str]]:
    """File sets already present under *root*, one entry per space that exists."""
    installed = {}
    for space in spaces:
        path = root / space
        if not path.is_dir():
            continue
        installed[space] = {
            str(p.relative_to(path)) for p in path.rglob("*") if p.is_file() or p.is_symlink()
        }
    return installed


# ---------------------------------------------------------------------------
# The two container calls, isolated so everything above can be tested without one
# ---------------------------------------------------------------------------


def _run_in_container(container: str | Path, script: str, args: list[str], binds: list[str]):
    cmd = ["singularity", "exec", "--cleanenv"]
    for b in binds:
        cmd.extend(["-B", b])
    cmd.extend([str(container), "python", "-c", script, *args])
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FsaverageError(
            f"Could not run the fMRIPrep container to check FreeSurfer templates: {exc}. "
            f"duckbrain will not submit concurrent jobs it cannot protect — see TODO #21."
        ) from exc


_MANIFEST_SCRIPT = """
import json, os, sys
from pathlib import Path
root = Path(os.environ["FREESURFER_HOME"]) / "subjects"
out = {}
for space in sys.argv[1:]:
    d = root / space
    if d.is_dir():
        out[space] = sorted(
            str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() or p.is_symlink()
        )
print(json.dumps(out))
"""


@lru_cache(maxsize=8)
def _manifest_cached(container: str, mtime: float, size: int, spaces: tuple[str, ...]):
    """Keyed on container identity so a swapped image is re-read, not remembered."""
    proc = _run_in_container(container, _MANIFEST_SCRIPT, list(spaces), binds=[])
    if proc.returncode != 0:
        raise FsaverageError(
            f"Could not list FreeSurfer templates inside {container}: "
            f"{(proc.stderr or '').strip()[-400:]}"
        )
    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise FsaverageError(f"Unreadable template listing from {container}: {exc}") from exc
    return {space: set(files) for space, files in raw.items()}


def container_manifest(container: str | Path, spaces: list[str]) -> dict[str, set[str]]:
    """File sets the container carries for each requested space."""
    container = Path(container)
    try:
        stat = container.stat()
    except OSError as exc:
        raise FsaverageError(f"fMRIPrep container not readable: {container} ({exc})") from exc
    return _manifest_cached(str(container), stat.st_mtime, stat.st_size, tuple(spaces))


_INSTALL_SCRIPT = """
import json, os, shutil, sys
from pathlib import Path
root = Path(os.environ["FREESURFER_HOME"]) / "subjects"
dest_root = Path(sys.argv[1])
staging_prefix = sys.argv[2]
report = {}
for space in sys.argv[3:]:
    src = root / space
    staging = dest_root / (staging_prefix + space)
    dest = dest_root / space
    if staging.exists():
        shutil.rmtree(staging)
    # Copy into staging, then swap. A job that looks while this runs sees either
    # the old tree or the new one, never a tree being written into.
    shutil.copytree(src, staging, copy_function=shutil.copy)
    n = sum(1 for p in staging.rglob("*") if p.is_file() or p.is_symlink())
    if dest.exists():
        doomed = dest_root / (staging_prefix + "old-" + space)
        if doomed.exists():
            shutil.rmtree(doomed)
        os.rename(dest, doomed)
        shutil.rmtree(doomed)
    os.rename(staging, dest)
    report[space] = n
print(json.dumps(report))
"""


def install(container: str | Path, root: Path, spaces: list[str]) -> dict[str, int]:
    """Copy *spaces* out of the container into *root*, staged then renamed."""
    root.mkdir(parents=True, exist_ok=True)
    proc = _run_in_container(
        container,
        _INSTALL_SCRIPT,
        [str(root), _STAGING_PREFIX, *spaces],
        binds=[f"{root}:{root}"],
    )
    if proc.returncode != 0:
        raise FsaverageError(
            f"Failed to install FreeSurfer templates into {root}: "
            f"{(proc.stderr or '').strip()[-400:]}"
        )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise FsaverageError(f"Unreadable install report: {exc}") from exc


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreflightReport:
    """What the pre-flight found and what it did about it."""

    root: Path
    before: tuple[SpaceState, ...]
    repaired: tuple[str, ...]
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def did_work(self) -> bool:
        return bool(self.repaired)

    def summary(self) -> str:
        if not self.repaired:
            names = ", ".join(s.space for s in self.before)
            return f"FreeSurfer templates already complete ({names})."
        bits = [f"{s} ({self.counts.get(s, '?')} files)" for s in self.repaired]
        return f"Installed FreeSurfer templates into {self.root}: {', '.join(bits)}."


def reset_cache() -> None:
    """Forget the container manifest. For tests, and after swapping an image."""
    _manifest_cached.cache_clear()


def ensure(
    container: str | Path,
    derivatives_dir: str | Path,
    output_spaces,
    *,
    extra_flags: str = "",
) -> PreflightReport | None:
    """Guarantee every ``fsaverage*`` fMRIPrep will want is installed and whole.

    Returns None only when the run needs no templates at all
    (``--fs-no-reconall``). Raises :class:`FsaverageError` rather than letting a
    caller submit — jobs that race over a half-installed tree fail three hours
    later, silently, and poison the directory for every later run.

    Cheap to call per subject, which is why the caller does not have to decide
    when to: the container is inspected at most once per process (the manifest is
    cached on image identity) and each further call is a walk of a few hundred
    files. Deliberately *not* memoised on "already verified" — that would save
    almost nothing over the manifest cache while making duckbrain blind to a tree
    that changed underneath it between two submissions.
    """
    spaces = required_spaces(output_spaces, extra_flags)
    if not spaces:
        return None

    root = subjects_dir(derivatives_dir)
    manifest = container_manifest(container, spaces)
    states = plan_repairs(manifest, read_installed(root, spaces), spaces)

    broken = [s.space for s in states if s.needs_repair]
    counts = install(container, root, broken) if broken else {}

    if broken:
        # Re-read rather than trust the copy: this is the one place that can still
        # leave a project poisoned, and it costs a directory walk to be sure.
        after = plan_repairs(manifest, read_installed(root, spaces), spaces)
        still = [s for s in after if s.needs_repair]
        if still:
            raise FsaverageError(
                "FreeSurfer templates are still incomplete after installing them: "
                + "; ".join(s.describe() for s in still)
            )

    return PreflightReport(root, tuple(states), tuple(broken), counts)


def cleanup_staging(derivatives_dir: str | Path) -> list[Path]:
    """Remove staging directories a killed install may have left behind."""
    root = subjects_dir(derivatives_dir)
    removed = []
    if not root.is_dir():
        return removed
    for path in root.glob(f"{_STAGING_PREFIX}*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path)
    return removed


__all__ = [
    "FsaverageError",
    "PreflightReport",
    "SpaceState",
    "cleanup_staging",
    "container_manifest",
    "ensure",
    "install",
    "plan_repairs",
    "read_installed",
    "required_spaces",
    "reset_cache",
    "subjects_dir",
]
