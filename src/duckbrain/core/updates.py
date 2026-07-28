"""Whether this checkout is behind duckbrain's latest published release.

duckbrain is distributed by ``git clone`` and the GUI serves whatever is checked
out, so a user can sit on one commit indefinitely with nothing to tell them a fix
has landed. That is not cosmetic. The inverted ``B0FieldIdentifier`` /
``B0FieldSource`` bug (pinned since by ``tests/test_fmap_intent.py``) produced
datasets that validate, convert cleanly and are silently uncorrected — there is no
symptom a user on a pre-fix checkout could have noticed. Correctness fixes have to
reach people who are not reading the commit log, and a line in the GUI is the only
channel that finds them where they already are.

The comparison is against **published releases, not ``origin/main``**. Users are
*expected* to sit between releases — the maintainer's own checkout always does, and
``core.bids_metadata`` stamps ``git describe`` rather than ``__version__`` for
exactly that reason — so "behind main" would fire for nearly everyone nearly always
and be tuned out within a week. A release is also the only version that comes with
a changelog entry to read, which is what makes the notice actionable rather than
just true. The cost is a coupling worth stating: pushing the tag is not enough,
publishing the GitHub Release is what turns this notice on (``docs/releasing.md``).

Everything degrades to *no answer*. A compute node need not have outbound HTTPS;
git may be absent; a shallow or zip-extracted copy has no tags; a fork's remote is
not ours to compare against. So the return is ``None`` — meaning "could not tell" —
and never a claim that the checkout is current. This is an unreliable convenience
sitting in the render path of every page: it must not raise, must not block for
long, and must stay silent unless it is *sure* something newer exists.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

# Reusing ``toolbox``'s internals rather than re-rolling them: its ``_git`` already
# encodes the swallow-everything contract this module needs (no git on PATH, not a
# checkout, timeout — all ""), and remote-URL normalisation is fiddly enough that a
# second copy would drift from the one provenance depends on.
from .toolbox import _git, _normalize_remote

# Short enough that a node with no route out costs a noticeable pause once rather
# than a hang. Callers are expected to cache; see the GUI wrapper.
_HTTP_TIMEOUT_S = 3.0

_API = "https://api.github.com/repos/{slug}/releases/latest"

# Set to any non-empty value to suppress the check entirely. Wanted by two callers
# that are not the GUI user: the test suite, which must never depend on GitHub
# being reachable or un-rate-limited, and an air-gapped node where the timeout is
# paid for nothing. Opting out yields ``None``, which is already "could not tell".
OPT_OUT_ENV = "DUCKBRAIN_NO_UPDATE_CHECK"


def _repo() -> Path:
    """duckbrain's own checkout root."""
    from .bids_metadata import _duckbrain_repo

    return _duckbrain_repo()


def _parse(tag: str) -> tuple[int, ...] | None:
    """``v0.2.1`` → ``(0, 2, 1)``; ``None`` if it isn't a plain semver tag.

    Anything with a pre-release or build suffix is refused rather than guessed at:
    ordering those correctly is a spec of its own, and getting it wrong here means
    nagging a user who is already current.
    """
    core = tag.strip().lstrip("vV")
    if not core or any(c in core for c in "-+"):
        return None
    parts = core.split(".")
    if not 1 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts) + (0,) * (3 - len(parts))


def current_tag(repo: str | Path | None = None) -> str:
    """Nearest release tag reachable from HEAD, e.g. ``v0.2.0``; ``""`` if none.

    ``--abbrev=0`` deliberately drops the ``-N-g<sha>`` suffix that provenance
    wants: the question here is which *release line* the checkout sits on, and a
    checkout three commits past ``v0.2.0`` is not behind ``v0.2.0``.
    """
    return _git(repo or _repo(), "describe", "--tags", "--abbrev=0")


def repo_slug(repo: str | Path | None = None) -> str:
    """``Owner/Repo`` from the checkout's own ``origin``; ``""`` if there isn't one.

    Read from the remote rather than hard-coded so a fork is checked against the
    fork. Telling someone their fork is behind *our* releases would be both wrong
    and unfixable from their side.
    """
    return _normalize_remote(_git(repo or _repo(), "config", "--get", "remote.origin.url"))


def latest_release(slug: str, timeout: float = _HTTP_TIMEOUT_S) -> tuple[str, str] | None:
    """``(tag, html_url)`` of *slug*'s latest published release, or ``None``.

    ``releases/latest`` is the right endpoint over ``tags``: it skips drafts and
    pre-releases for free, and it 404s until a release is actually published —
    which is the coupling this module wants, not a gap in it.

    Unauthenticated, so it is subject to GitHub's by-IP rate limit. A 403 is
    indistinguishable here from any other failure and is treated the same way:
    say nothing.
    """
    if not slug or "/" not in slug:
        return None
    req = urllib.request.Request(
        _API.format(slug=slug),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "duckbrain"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    # Valid JSON is not necessarily an *object*: ``null`` and a bare list both
    # decode cleanly and then blow up on ``.get``, which — in the render path of
    # every page — would blank the GUI over a check nobody asked for.
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "")
    if not tag:
        return None
    url = str(payload.get("html_url") or f"https://github.com/{slug}/releases/tag/{tag}")
    return tag, url


def update_available(repo: str | Path | None = None) -> tuple[str, str] | None:
    """``(tag, url)`` of a newer published release than this checkout, else ``None``.

    ``None`` covers both "current" and "could not tell", on purpose — no caller
    should be able to render "you are up to date" off a check that may simply have
    failed to reach the network.
    """
    if os.environ.get(OPT_OUT_ENV, "").strip():
        return None
    root = repo or _repo()
    here = _parse(current_tag(root))
    if here is None:
        return None
    found = latest_release(repo_slug(root))
    if found is None:
        return None
    tag, url = found
    there = _parse(tag)
    if there is None or there <= here:
        return None
    return tag, url
