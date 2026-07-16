"""Read version provenance out of a git-checkout toolbox (NORDIC).

The container stages identify their code by the image they run (see
``core.containers``). NORDIC has no container — it is a MATLAB toolbox the user
checks out from git — so it needs the same idea against a different artifact.
A git checkout carries an exact identity, and it is the *only* honest one here:

* upstream's in-file marker (``% VERSION 4/22/2021``) is years stale;
* its newest release tag (``v1.1``, 2021) sits 24 commits behind a HEAD from
  2025 — upstream commits to ``main`` without cutting releases.

So the commit is the version. ``git describe --tags --always --dirty`` renders it
readably (``v1.0.2-24-g0861968``) and, crucially, marks a **locally-edited**
toolbox ``-dirty`` — results a hand-tweaked ``NIFTI_NORDIC.m`` produced are not
reproducible, and that belongs in the provenance record.

This matters more than for containers, on two counts. A container image is
effectively immutable once pulled; a git checkout is *designed* to be updated in
place — and duckbrain's own toolbox lives on a group-writable shared path, where
any lab member's ``git pull`` silently changes denoising for every project
pointing at it. And since NORDIC's licence forbids redistribution (so every user
must fetch their own copy), users drift to different commits independently:
recording what ran is the only way to know.

Everything degrades to ``""``: no git on PATH, a toolbox that isn't a checkout
(a plain unpacked copy is legitimate), an unreadable path, or a timeout must
never raise into a caller. Uncached — these are fast local git reads, and caching
would risk serving a stale ``-dirty`` after an edit.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_GIT_TIMEOUT_S = 15


def _is_checkout(repo: str | Path) -> bool:
    """True only for a real, configured directory path.

    Guards the empty path explicitly: ``Path("")`` is ``.``, so an unconfigured
    ``nordic_toolbox_dir`` would otherwise resolve to the *current directory* and
    happily describe whatever repo duckbrain is running from — recording
    duckbrain's own version as the toolbox's. Silently wrong provenance is worse
    than none, so an unset path must yield "".
    """
    if not repo or not str(repo).strip():
        return False
    return Path(repo).is_dir()


def _git(repo: str | Path, *args: str) -> str:
    """Run a read-only git command in *repo*; "" on any failure."""
    exe = shutil.which("git")
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe, "-C", str(repo), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def describe(repo: str | Path) -> str:
    """Readable exact version of the checkout, e.g. ``v1.0.2-24-g0861968``.

    ``--always`` falls back to a bare sha when no tag is reachable; ``--dirty``
    marks uncommitted local edits. ``""`` if *repo* isn't a git checkout.
    """
    if not _is_checkout(repo):
        return ""
    return _git(repo, "describe", "--tags", "--always", "--dirty")


def _normalize_remote(url: str) -> str:
    """``https://github.com/Owner/Repo.git`` / ``git@github.com:Owner/Repo.git``
    → ``Owner/Repo``. Returns the input unchanged if it doesn't look like a
    hosted remote, so an unusual remote still records *something*.
    """
    u = url.strip()
    if not u:
        return ""
    if u.endswith(".git"):
        u = u[: -len(".git")]
    if "://" in u:            # https://host/Owner/Repo
        u = u.split("://", 1)[1]
        u = u.split("/", 1)[1] if "/" in u else u
    elif ":" in u and "@" in u:  # git@host:Owner/Repo
        u = u.split(":", 1)[1]
    return u.strip("/")


def source_ref(repo: str | Path) -> str:
    """Build provenance of the checkout: ``Owner/Repo@sha``, or ``""``.

    The git analogue of a container's ``deffile.from`` (``nipreps/mriqc:24.0.2``)
    — an identity that survives the checkout being renamed or moved, and that is
    comparable *across users*, who each hold their own clone at their own commit.
    Falls back to the bare sha when the checkout has no ``origin`` remote.
    """
    if not _is_checkout(repo):
        return ""
    sha = _git(repo, "rev-parse", "--short", "HEAD")
    if not sha:
        return ""
    remote = _normalize_remote(_git(repo, "config", "--get", "remote.origin.url"))
    return f"{remote}@{sha}" if remote else sha


def code_url(repo: str | Path) -> str:
    """Browsable URL for the exact commit, for BIDS ``GeneratedBy[].CodeURL``.

    ``""`` unless the remote is an https host we can build a tree URL for —
    guessing a URL scheme for an arbitrary host would be worse than saying
    nothing.
    """
    if not _is_checkout(repo):
        return ""
    url = _git(repo, "config", "--get", "remote.origin.url").strip()
    sha = _git(repo, "rev-parse", "HEAD")
    if not url or not sha:
        return ""
    slug = _normalize_remote(url)
    if not slug or "/" not in slug:
        return ""
    host = "github.com"
    if "://" in url:
        host = url.split("://", 1)[1].split("/", 1)[0]
    elif "@" in url and ":" in url:
        host = url.split("@", 1)[1].split(":", 1)[0]
    if host != "github.com":
        return ""
    return f"https://{host}/{slug}/tree/{sha}"
