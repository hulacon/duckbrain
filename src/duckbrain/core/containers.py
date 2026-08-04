"""Running a container, and reading build provenance out of its image.

Two things live here because both are about the container as an object rather
than about any one tool: the flags **every** invocation must carry
(:data:`ISOLATION_FLAGS`), and the labels an image records about how it was
built.

duckbrain identifies a container by its *filename* (``get_container_path`` builds
``<tool>-<pin>.simg`` from the ``[containers]`` pin). That is convention, not
fact: a filename can be renamed, or the image rebuilt in place, and nothing about
the name would change. The image itself carries the truth — Apptainer records the
Docker tag it was bootstrapped from in its labels:

    org.label-schema.usage.singularity.deffile.from: nipreps/mriqc:24.0.2

That is *build provenance*: it cannot drift from what was actually built, so it is
a stronger container identity than the filename, and stronger than the tool's own
self-reported version (which is upstream packaging metadata duckbrain neither
controls nor can reconcile — ``nipreps/mriqc:24.0.2`` self-reports
``24.1.0.dev0+gd5b13cb5.d20240826``; see ``consistency._check_container_drift``).

``apptainer inspect`` reads only the SIF header, not the image payload, so this
costs ~20–50 ms even for a 5 GB image (measured on Talapas, 2026-07-16). Results
are cached per (path, mtime, size) anyway, since the consistency panel re-runs on
every cockpit render.

Everything degrades to ``""``/``{}``: no apptainer on PATH, an unreadable image, a
timeout, or a container built without labels must never raise into a caller.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

# ---- Isolating a container from the host it runs on -------------------------
#
# **Spelled here and nowhere else.** Nine call sites run a container — five
# Python command builders and four lines across three sbatch templates — and a
# flag that has to be on all nine is a flag that will be missing from the tenth.
# `tests/test_container_isolation.py` fails if any of them spells its own.
#
# `--cleanenv` alone is not isolation, which is the part that cost a real MRIQC
# run. It clears environment *variables*; it does not unmount `$HOME`, and it
# does not stop CPython adding the user's site-packages to `sys.path`. Apptainer
# binds `$HOME` by default, so inside the container
# `site.ENABLE_USER_SITE` is True and `~/.local/lib/pythonX.Y/site-packages` is
# on the path **ahead of** the image's own. Anyone who has ever run
# `pip install --user` on the cluster is therefore running the container's
# pipeline against some of the host's libraries.
#
# Measured on Talapas 2026-08-04, and it is not a near miss: the MRIQC 24.0.2
# image is Python 3.11.8 and the fMRIPrep 24.1.1 image is Python 3.11.9, so a
# single `~/.local/lib/python3.11/site-packages` shadows both. A user with
# NumPy 2.x there had it override the image's 1.26.4, and MRIQC died building its
# workflow because transforms3d calls something NumPy 2.0 removed.
#
# `PYTHONNOUSERSITE=1` closes exactly that and nothing else. `--no-home` also
# works and was rejected: it takes `$HOME` away wholesale, and nipype's config,
# matplotlib's cache and the FreeSurfer licence all live there — trading this bug
# for a different one. Passed via `--env` rather than an `APPTAINERENV_`/
# `SINGULARITYENV_` prefix because apptainer now warns that the singularity
# spelling is deprecated and the prefix form has to pick one.
#
# The failure this does *not* prevent is worth naming: a crash is the lucky
# outcome. A host package close enough to import but not to behave would have
# changed results silently, which is the shape of every bug this codebase keeps
# finding.
#
# `--env` needs Singularity >= 3.6 / any Apptainer. An older runtime fails loudly
# on the unknown flag, which is the intended direction — see the "silently
# degrading option" rule in CLAUDE.md.
ISOLATION_FLAGS: tuple[str, ...] = ("--cleanenv", "--env", "PYTHONNOUSERSITE=1")


def isolation_flags() -> list[str]:
    """:data:`ISOLATION_FLAGS` as a fresh list, for building an argv."""
    return list(ISOLATION_FLAGS)


def isolation_flags_sh() -> str:
    """:data:`ISOLATION_FLAGS` as shell text, for an sbatch template.

    Deliberately *not* run through the ``| sh`` quoting filter by its callers:
    this is several arguments, and quoting would collapse it into one. Same
    exception `extra_flags` carries, and for the same reason. It is safe because
    every part is a literal defined above — nothing here comes from config.
    """
    return " ".join(ISOLATION_FLAGS)


# The Apptainer label recording the source the image was bootstrapped from.
_DEFFILE_FROM = "org.label-schema.usage.singularity.deffile.from"
_DEFFILE_BOOTSTRAP = "org.label-schema.usage.singularity.deffile.bootstrap"

_INSPECT_TIMEOUT_S = 30


@lru_cache(maxsize=64)
def _inspect_labels_cached(path: str, mtime: float, size: int) -> tuple:
    """Run ``apptainer inspect`` and parse ``key: value`` labels.

    Keyed on (path, mtime, size) so a rebuilt image at the same path re-inspects
    rather than serving a stale identity — the exact case build provenance exists
    to catch. Returns a tuple of pairs (hashable, so lru_cache accepts it).
    """
    exe = shutil.which("apptainer") or shutil.which("singularity")
    if not exe:
        return ()
    try:
        proc = subprocess.run(
            [exe, "inspect", path],
            capture_output=True,
            text=True,
            timeout=_INSPECT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if proc.returncode != 0:
        return ()
    labels = []
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            labels.append((key.strip(), value.strip()))
    return tuple(labels)


def inspect_labels(container: str | Path) -> dict[str, str]:
    """Labels recorded in *container*, or ``{}`` if unreadable/unavailable."""
    p = Path(container)
    try:
        st = p.stat()
    except OSError:
        return {}
    return dict(_inspect_labels_cached(str(p), st.st_mtime, st.st_size))


def container_build_tag(container: str | Path) -> str:
    """The source *container* was built from, e.g. ``nipreps/mriqc:24.0.2``.

    Returns ``""`` when the image records no bootstrap source — an image built
    from a local def file rather than a registry, or one with no labels at all.
    Callers must treat ``""`` as "unknown", never as a mismatch.
    """
    labels = inspect_labels(container)
    return labels.get(_DEFFILE_FROM, "")


def container_uri(container: str | Path) -> str:
    """Build tag as a BIDS ``GeneratedBy[].Container.URI``, or ``""``.

    Prefixes the bootstrap scheme the image records (``docker`` in practice), so
    the value round-trips as a pullable reference.
    """
    tag = container_build_tag(container)
    if not tag:
        return ""
    scheme = inspect_labels(container).get(_DEFFILE_BOOTSTRAP, "docker") or "docker"
    return f"{scheme}://{tag}"
