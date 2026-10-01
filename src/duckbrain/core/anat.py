"""Which T1w images the anatomical stages read — one answer for FreeSurfer and fMRIPrep.

A raw tree can hold one acquisition under more than one ``rec-`` label. The case
that reached us was an FSL ``robustfov`` crop written beside the uncropped
original as ``*_rec-robustfov_T1w``. Both anatomical consumers otherwise take
every ``*_T1w`` they find, and treat the pair as two separate scans:

* the ``freesurfer`` stage hands each to ``recon-all`` as its own ``-i``, and
  recon-all stops within seconds with "inputs have mismatched dimensions!" (the
  crop has fewer slices) — a failed job, and the reason only shows up in its log;
* fMRIPrep conforms its inputs before merging them, so it does not stop. It
  builds the subject's anatomical reference by averaging the scan with its own
  crop, and nothing in its output says so.

So a project declares the label it wants in ``[anat] t1w_rec``, and both stages
read only that: :func:`select_t1ws` for the recon's inputs, and the same label
as a ``reconstruction`` entry in fMRIPrep's BIDS filter. With nothing declared,
a subject whose T1ws include one acquisition under two labels is **refused at
launch**, because averaging the two is never what anyone meant and guessing which
one they did mean is not ours to do. A declared label that matches none of a
subject's T1ws is refused too, rather than falling back to all of them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config

_REC = re.compile(r"_rec-([a-zA-Z0-9]+)(?=_)")


class AnatSelectionError(ValueError):
    """The subject's T1ws cannot be narrowed to one image per acquisition."""


def t1w_rec(config: Config) -> str:
    """The ``rec-`` label the project's anatomical stages read, or ``""`` for all.

    Accepts the label with or without its ``rec-`` prefix, since the filename is
    where users will have copied it from.
    """
    label = str(config.get("anat", {}).get("t1w_rec") or "").strip()
    return label.removeprefix("rec-")


def rec_label(path: str | Path) -> str:
    """The ``rec-`` label in *path*'s filename, or ``""`` when it has none."""
    m = _REC.search(Path(path).name)
    return m.group(1) if m else ""


def _same_acquisition(path: Path) -> tuple[str, str]:
    """*path* with its ``rec-`` entity and extension removed — equal for two
    reconstructions of one acquisition, distinct across sessions and runs."""
    name = _REC.sub("", path.name)
    return str(path.parent), name.removesuffix(".gz").removesuffix(".nii")


def select_t1ws(config: Config, t1ws: list[Path], subject: str) -> list[Path]:
    """The T1ws a stage should read for *subject*, out of every one on disk.

    Raises :class:`AnatSelectionError` when a declared label matches none of
    them, or when none is declared and one acquisition appears under several
    labels. Otherwise returns *t1ws* unchanged (no label) or narrowed to the
    declared label.
    """
    label = t1w_rec(config)
    if label:
        chosen = [p for p in t1ws if rec_label(p) == label]
        if not chosen:
            found = ", ".join(p.name for p in t1ws) or "none"
            raise AnatSelectionError(
                f"[anat] t1w_rec is {label!r}, but sub-{subject} has no rec-{label} T1w "
                f"(T1ws found: {found}). Fix the label, or add the missing image."
            )
        return chosen

    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for p in t1ws:
        groups[_same_acquisition(p)].append(p)
    clashes = [g for g in groups.values() if len(g) > 1]
    if clashes:
        names = "; ".join(" and ".join(p.name for p in g) for g in clashes)
        labels = sorted({rec_label(p) for g in clashes for p in g} - {""})
        raise AnatSelectionError(
            f"sub-{subject} has the same T1w under more than one rec- label ({names}). "
            "Both would be read as separate scans: recon-all stops on their mismatched "
            "dimensions, and fMRIPrep averages the scan with itself. Choose one with "
            "[anat] t1w_rec in code/duckbrain.toml "
            f"(labels here: {', '.join(labels)}); to use the un-labelled originals, "
            "move the rec- copies out of the BIDS tree instead."
        )
    return t1ws
