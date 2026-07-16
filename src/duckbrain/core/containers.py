"""Read build provenance out of a Singularity/Apptainer image.

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
            capture_output=True, text=True, timeout=_INSPECT_TIMEOUT_S, check=False,
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
