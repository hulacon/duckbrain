"""Find the fMRIPrep figures a review domain is looked at through.

:mod:`duckbrain.core.qc_domains` declares *which* figures answer a domain's
question. This module finds them on disk for one selection, and says so out loud
when they are not there.

**Why this exists rather than serving fMRIPrep's own report.** That report is
per subject and carries every figure at once: 80 MB for a subject on
``divatten_beta_v2``, against 1.1 MB for the one distortion-correction figure a
reviewer looking at alignment actually wants. Serving figures individually is a
70x reduction, and it is what lets a domain page show only its own evidence.
The SDC animation survives the move — each SVG carries its own ``<style>`` with
``@keyframes``, so the before/after flicker does not depend on the enclosing
report. That is pinned by a test, because a plausible future size optimisation
is to strip SVG styles, and it would kill the flicker silently.

**Matching is by entity, not by string prefix.** Joining the run key to a
pattern looks simpler and does not survive real data: fMRIPrep writes entities
the run key does not carry, so the anatomical figures on a session dataset are
``sub-03_acq-MPR_dseg.svg`` and a prefix join finds nothing. Instead every
candidate is globbed by the figure's filename tail and then filtered on the BIDS
entities both sides carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from duckbrain.core.qc import parse_entities
from duckbrain.core.qc_domains import EvidenceFigure, ReviewDomain

#: Entities that must agree for a run-scoped figure to describe this run.
RUN_ENTITIES = ("sub", "ses", "task", "run")

#: Entities that must agree for a subject-scoped figure. Session is included on
#: purpose: fieldmaps are estimated per session and their figures carry ``ses``,
#: so matching on subject alone would offer another session's fieldmap as if it
#: were this one's. Task and run are excluded because a fieldmap's own ``run``
#: index counts fieldmaps, not BOLD runs, and comparing them would reject every
#: figure.
SUBJECT_ENTITIES = ("sub", "ses")


@dataclass(frozen=True)
class EvidenceHit:
    """What was found on disk for one declared figure.

    Carries the absence as a first-class result rather than an empty list the
    caller has to notice, because a missing figure is sometimes the finding —
    no distortion-correction figure means the run was preprocessed without
    distortion correction.
    """

    figure: EvidenceFigure
    paths: tuple[Path, ...] = ()
    run_key: str = ""

    @property
    def found(self) -> bool:
        return bool(self.paths)

    def label_for(self, path: Path) -> str:
        """What tells *path* apart from the others found for this figure.

        Only the entities that are genuinely distinguishing: not the ones the
        selection already fixes, and not the ones the figure's own pattern
        names. Labelling a distortion-correction figure ``desc-sdc`` says
        nothing — labelling two segmentation figures ``acq-MPR`` and
        ``acq-MPR · desc-preproc`` is the whole point.
        """
        target = parse_entities(self.run_key)
        own = set(parse_entities(self.figure.pattern.replace("*", "")))
        extra = {
            k: v
            for k, v in parse_entities(path.stem).items()
            if target.get(k) != v and k not in own
        }
        return " · ".join(f"{k}-{v}" for k, v in extra.items())

    @property
    def total_bytes(self) -> int:
        """Size of what showing this would load, for naming the cost first."""
        total = 0
        for p in self.paths:
            try:
                total += p.stat().st_size
            except OSError:
                continue
        return total

    def explain_absence(self) -> str:
        """Why nothing was found — never the empty string, never called blind."""
        return self.figure.explain_absence()


def figures_dir(fmriprep_dir: Path | str, subject: str) -> Path:
    """Return the directory holding *subject*'s figures.

    Always ``<fmriprep>/<sub>/figures``, at the subject level, even on a dataset
    with sessions — fMRIPrep puts the session in the *filename*, not the path.
    Verified against a 7-session dataset; assuming otherwise would find nothing
    for every session project.
    """
    subject = subject if subject.startswith("sub-") else f"sub-{subject}"
    return Path(fmriprep_dir) / subject / "figures"


def _matches(candidate: dict, target: dict, keys: tuple[str, ...]) -> bool:
    """True when every listed entity the *candidate* carries agrees with *target*.

    Entities the candidate does not carry are not checked, so a subject-level
    figure with no ``ses`` matches any session. An entity the candidate carries
    and the target lacks fails, which is what keeps a session dataset's figures
    from being offered for a sessionless selection.
    """
    return all(candidate[k] == target.get(k) for k in keys if k in candidate)


def find_figure(fmriprep_dir: Path | str, figure: EvidenceFigure, run_key: str) -> EvidenceHit:
    """Find every file matching *figure* for the selection named by *run_key*.

    Returns **all** matches rather than one. A subject can legitimately have
    several: two fieldmap pairs in a session yield two estimation figures, and a
    multi-acquisition anatomical yields one segmentation figure per acquisition.
    Picking one and hiding the rest would be the silent choice; the viewer shows
    them and labels what distinguishes them.
    """
    target = parse_entities(run_key)
    subject = target.get("sub")
    if not subject:
        return EvidenceHit(figure=figure, run_key=run_key)

    directory = figures_dir(fmriprep_dir, subject)
    keys = RUN_ENTITIES if figure.scope == "run" else SUBJECT_ENTITIES
    # No guard around the glob: pathlib yields nothing for a directory that is
    # missing, unreadable, or not a directory at all, rather than raising. A
    # missing tree therefore arrives at the same "absent" result as a missing
    # figure, which is the answer the caller wants either way.
    candidates = sorted(directory.glob(f"*{figure.pattern}"))
    hits = tuple(p for p in candidates if _matches(parse_entities(p.stem), target, keys))
    return EvidenceHit(figure=figure, paths=hits, run_key=run_key)


def collect(
    fmriprep_dir: Path | str,
    domain: ReviewDomain,
    run_key: str,
    modality: str = "bold",
) -> list[EvidenceHit]:
    """Every figure *domain* is reviewed through, for this selection.

    One entry per declared figure, present or not — an absent figure keeps its
    place in the list so the viewer reports it rather than rendering a shorter
    list the reviewer cannot tell from a complete one.
    """
    return [find_figure(fmriprep_dir, figure, run_key) for figure in domain.evidence_for(modality)]


def subjects_with_figures(fmriprep_dir: Path | str) -> list[str]:
    """Subjects fMRIPrep has written a figures directory for."""
    root = Path(fmriprep_dir)
    return sorted(p.name for p in root.glob("sub-*") if (p / "figures").is_dir())


def all_runs_with_figures(fmriprep_dir: Path | str, modality: str = "bold") -> list[str]:
    """Every run key fMRIPrep wrote figures for, across every subject.

    The fallback run list for a project where fMRIPrep ran and MRIQC did not.
    Without it the visual review would be unreachable on exactly the projects
    that have the derivative to review — the failure this page has shipped twice.
    """
    return sorted(
        key
        for subject in subjects_with_figures(fmriprep_dir)
        for key in runs_with_figures(fmriprep_dir, subject, modality)
    )


def runs_with_figures(fmriprep_dir: Path | str, subject: str, modality: str = "bold") -> list[str]:
    """Run keys fMRIPrep wrote per-run figures for, read from the figures themselves.

    Derived from the derivative rather than from MRIQC's metrics on purpose, so
    the viewer still works on a project where fMRIPrep ran and MRIQC did not —
    the same reason the panel sits above the page's MRIQC gate. Keys are built
    by :func:`~duckbrain.core.qc_report.build_run_key`, so they match the keys
    decisions are filed under rather than merely resembling them.
    """
    from duckbrain.core.qc_report import build_run_key

    directory = figures_dir(fmriprep_dir, subject)
    keys: set[str] = set()
    for path in sorted(directory.glob(f"*_{modality}.svg")):
        entities = parse_entities(path.stem)
        if "task" not in entities:
            continue
        keys.add(build_run_key(entities, modality))
    return sorted(keys)
