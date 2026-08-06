"""Review domains — the taxonomy that groups QC evidence by the question it answers.

:mod:`duckbrain.core.qc_guidance` says what each measure *means*. This module
says which **review question** it belongs to, so the dashboard can present one
aspect of a run at a time instead of thirty numbers at once.

Four domains, and they are a strict partition of the guidance registry: every
measure belongs to exactly one, enforced at import. A measure in two domains
would render two ``<details id="guidance-{key}">`` blocks into the same
document, and an in-page anchor would land wherever the browser felt like.

The taxonomy lives here rather than as a field on ``MeasureGuidance`` for two
reasons. The registry is a near-byte-identical port from mmmdata, and keeping it
that way is what makes "mmmdata depends on duckbrain" a deletion rather than a
merge. More decisively, **a domain's content is not only measures**: alignment
on functional data has no MRIQC number at all, and is reviewed entirely from
fMRIPrep's per-run reportlets — which have no key, no direction and no auto_flag,
and so can never be registry entries. A dataclass field cannot express them.
:class:`EvidenceFigure` can.

Typical usage::

    from duckbrain.core.qc_domains import domains_for_modality, measures_for

    for d in domains_for_modality("bold"):
        print(d.label, measures_for("bold", d.key))
"""

from __future__ import annotations

from dataclasses import dataclass, field

from duckbrain.core.qc_guidance import MEASURE_GUIDANCE

#: Where an artifact is written, and therefore what a reviewer is looking at.
#: fMRIPrep writes SDC, coregistration and carpet plots per *run*; segmentation,
#: normalization and surface reconstruction once per *subject*.
VALID_SCOPES = {"run", "subject"}

#: Modalities the taxonomy projects onto. Matches the guidance registry, which
#: documents ``dwi`` even though no duckbrain page offers it as a choice yet.
MODALITIES = ("bold", "T1w", "T2w", "dwi")


@dataclass(frozen=True)
class EvidenceFigure:
    """A tool-produced figure that a domain is reviewed from.

    The visual counterpart to a :class:`~duckbrain.core.qc_guidance.MeasureGuidance`:
    it carries the same ``look_for`` contract, because for some domains looking
    *is* the review and there is no number to flag.

    Parameters
    ----------
    key : str
        Stable identifier, e.g. ``'sdc'``. Unique within a domain.
    label : str
        Human-readable name for the viewer's caption.
    pattern : str
        Filename tail identifying the figure, matched as ``*{pattern}`` inside
        the subject's ``figures/`` directory and then filtered by BIDS entities.
        Matched this way rather than by joining a prefix, because fMRIPrep
        writes entities the run key does not carry — the anatomical figures on a
        real session dataset are ``sub-03_acq-MPR_dseg.svg``, and a prefix join
        would find nothing. Kept as a glob because output space is a project
        choice: ``space-*_T1w.svg`` must match whichever template was used.
    scope : str
        One of :data:`VALID_SCOPES`. ``'run'`` filters on subject, session, task
        and run; ``'subject'`` filters on subject and session only. Session
        matters even for a "subject" figure because fieldmaps are estimated per
        session, and showing another session's is worse than showing none.
    look_for : str
        What the reviewer should check by eye. Same contract, and same voice, as
        ``MeasureGuidance.look_for``.
    absent_means : str, optional
        What it *means* that this figure is missing. For most figures absence
        just means the run was not preprocessed, but for some it is a finding in
        its own right — a missing SDC figure says the run was preprocessed with
        no distortion correction, which is exactly the failure that shipped
        silently once already. Stated here so the viewer reports the absence
        rather than rendering a gap.
    """

    key: str
    label: str
    pattern: str
    scope: str
    look_for: str
    absent_means: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in VALID_SCOPES:
            raise ValueError(
                f"Invalid scope {self.scope!r} for {self.key!r}; "
                f"expected one of {sorted(VALID_SCOPES)}"
            )

    def explain_absence(self) -> str:
        """Why this figure is missing — never the empty string.

        Falls back to the generic reading rather than to nothing, so a viewer
        cannot render a silent gap by trusting a field nobody filled in.
        """
        if self.absent_means:
            return self.absent_means
        return (
            f"No {self.label.lower()} figure was written for this selection. "
            f"fMRIPrep writes it whenever the corresponding step runs, so the "
            f"usual reading is that this run was not preprocessed."
        )


@dataclass(frozen=True)
class ReviewDomain:
    """One aspect of a run, reviewable on its own.

    Parameters
    ----------
    key : str
        Stable identifier used in URLs, section anchors and decision records.
    label : str
        Section and page heading.
    question : str
        The one-line question this domain answers, written so a reviewer who
        knows no IQM can still tell whether they are in the right section.
    measures : tuple of str
        Keys into :data:`~duckbrain.core.qc_guidance.MEASURE_GUIDANCE`. Every
        measure across all domains together partitions that registry.
    evidence : tuple of EvidenceFigure
        Figures this domain is reviewed from.
    not_applicable : dict
        Modality to the sentence explaining why this domain has no measures for
        it. Required whenever the projection is empty: a section that renders
        blank is the silent degradation ``CLAUDE.md`` forbids, and the reader
        cannot tell it apart from a section that failed to load.
    caveat : str, optional
        Something true of the domain as a whole that a reviewer reading only its
        numbers would otherwise assume wrongly.
    """

    key: str
    label: str
    question: str
    measures: tuple[str, ...] = ()
    evidence: tuple[EvidenceFigure, ...] = ()
    not_applicable: dict[str, str] = field(default_factory=dict)
    caveat: str | None = None

    def measures_for(self, modality: str) -> list[str]:
        """This domain's measures documented for *modality*, in registry order."""
        return [k for k in self.measures if modality in MEASURE_GUIDANCE[k].modalities]

    def evidence_for(self, modality: str) -> list[EvidenceFigure]:
        """This domain's figures relevant to *modality*.

        Anatomical figures are written once per subject and are worth seeing
        whichever modality is selected — a failed surface reconstruction is a
        fact about the subject, not about the T1w row. Run-scoped figures are
        BOLD-only, because that is the only modality fMRIPrep writes them for.
        """
        if modality == "bold":
            return list(self.evidence)
        return [e for e in self.evidence if e.scope == "subject"]

    def explain_absence(self, modality: str) -> str:
        """Why this domain is empty for *modality* — never the empty string.

        Falls back to a generic sentence rather than returning nothing, so a
        caller cannot accidentally render a blank section by trusting a key that
        was never filled in.
        """
        stated = self.not_applicable.get(modality)
        if stated:
            return stated
        return (
            f"No {self.label.lower()} measure is documented for {modality} data, "
            f"and no figure covers it."
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DOMAINS: tuple[ReviewDomain, ...] = ()
_BY_KEY: dict[str, ReviewDomain] = {}
_MEASURE_OWNER: dict[str, str] = {}


def _register(domain: ReviewDomain) -> None:
    """Add a domain, rejecting a duplicate key or a measure claimed twice.

    Checked at import rather than only in a test, because the partition is what
    keeps guidance anchors unique in the rendered report — a violation is a
    broken document, not a style problem.
    """
    global DOMAINS
    # Validate everything before mutating anything. A raise part-way through
    # would leave the rejected domain's earlier measures owned by a domain that
    # was never added, which is a worse state than the one being refused.
    if domain.key in _BY_KEY:
        raise ValueError(f"Duplicate review domain {domain.key!r}")
    for m in domain.measures:
        if m not in MEASURE_GUIDANCE:
            raise ValueError(
                f"Domain {domain.key!r} claims {m!r}, which has no guidance entry. "
                f"A domain may only group measures the registry documents."
            )
        if m in _MEASURE_OWNER:
            raise ValueError(
                f"Measure {m!r} is claimed by both {_MEASURE_OWNER[m]!r} and "
                f"{domain.key!r}; domains must partition the registry."
            )
    seen: set[str] = set()
    for e in domain.evidence:
        if e.key in seen:
            raise ValueError(f"Duplicate evidence figure {e.key!r} in domain {domain.key!r}")
        seen.add(e.key)

    _MEASURE_OWNER.update({m: domain.key for m in domain.measures})
    _BY_KEY[domain.key] = domain
    DOMAINS = (*DOMAINS, domain)


_register(
    ReviewDomain(
        key="signal",
        label="Signal & contrast",
        question=(
            "Is there enough signal, and enough contrast between tissues, to measure "
            "anything at all?"
        ),
        measures=(
            "tsnr",
            "snr",
            "snr_total",
            "snr_gm",
            "snr_wm",
            "cnr",
            "cjv",
            "fber",
        ),
        caveat=(
            "Every measure here is a ratio against a noise estimate, and each tool "
            "estimates noise differently. They rank runs within this dataset "
            "reliably; they do not transfer to another scanner or protocol as "
            "absolute numbers."
        ),
    )
)

_register(
    ReviewDomain(
        key="temporal",
        label="Temporal stability",
        question="Did the timeseries hold still, and hold steady, frame to frame?",
        measures=(
            "fd_mean",
            "fd_num",
            "fd_perc",
            "mean_fd",
            "pct_high_motion",
            "dvars_std",
            "dvars_nstd",
            "aqi",
            "aor",
            "gcor",
        ),
        evidence=(
            EvidenceFigure(
                key="carpetplot",
                label="Carpet plot with motion and DVARS traces",
                pattern="desc-carpetplot_bold.svg",
                scope="run",
                look_for=(
                    "Read the traces and the carpet together — that pairing is the "
                    "whole point of the figure. Dark or bright bands running the full "
                    "width of the carpet, lining up with spikes in the FD and DVARS "
                    "traces above it, are real head motion. Banding with no "
                    "corresponding spike is more likely a scanner or reconstruction "
                    "artifact, and a spike with no banding is often a noisy estimate "
                    "rather than a moved head."
                ),
            ),
            EvidenceFigure(
                key="confoundcorr",
                label="Confound correlation matrix",
                pattern="desc-confoundcorr_bold.svg",
                scope="run",
                look_for=(
                    "Confounds highly correlated with each other waste degrees of "
                    "freedom in the model without removing more noise. Strong "
                    "correlation between motion parameters and the global signal is "
                    "the one to notice: regressing both then risks removing the "
                    "effect of interest along with the motion."
                ),
            ),
            EvidenceFigure(
                key="compcorvar",
                label="CompCor variance explained",
                pattern="desc-compcorvar_bold.svg",
                scope="run",
                look_for=(
                    "How many components are needed to reach the variance threshold. "
                    "A run needing far more than its neighbours has structured noise "
                    "the others do not, which is worth understanding before it is "
                    "regressed away."
                ),
            ),
        ),
        not_applicable={
            "T1w": (
                "A structural scan is a single volume, so there is no frame-to-frame "
                "anything to measure. The nearest question — did the participant move "
                "during the acquisition — shows up as ringing and ghosting instead, "
                "and is graded under Artifacts & inhomogeneity as `efc`."
            ),
            "T2w": (
                "A structural scan is a single volume, so there is no frame-to-frame "
                "anything to measure. The nearest question — did the participant move "
                "during the acquisition — shows up as ringing and ghosting instead, "
                "and is graded under Artifacts & inhomogeneity as `efc`."
            ),
        },
    )
)

_register(
    ReviewDomain(
        key="alignment",
        label="Alignment & distortion",
        question=(
            "Is everything where it should be — distortion corrected, BOLD on the "
            "T1w, brain in the template?"
        ),
        measures=("tpm_overlap_gm", "tpm_overlap_wm", "tpm_overlap_csf"),
        evidence=(
            EvidenceFigure(
                key="sdc",
                label="Susceptibility distortion correction, before and after",
                pattern="desc-sdc_bold.svg",
                scope="run",
                look_for=(
                    "The figure alternates between the uncorrected and corrected "
                    "image; watch the frontal and temporal poles, where dropout and "
                    "stretching are worst. Correction should pull those regions back "
                    "toward the anatomy outline. If the two frames look identical, no "
                    "correction was applied — check that the fieldmap was found and "
                    "the BIDS intent fields point at this run."
                ),
                absent_means=(
                    "fMRIPrep writes this only when it found and applied a fieldmap, so "
                    "its absence means this run was preprocessed with **no distortion "
                    "correction**. That is a finding, not a missing picture. Before "
                    "concluding no fieldmap exists, check the BIDS intent fields: the "
                    "fieldmap carries `B0FieldIdentifier`, and the bold and sbref carry "
                    "`B0FieldSource`. duckbrain shipped those inverted once and nothing "
                    "complained — the dataset validated, and fMRIPrep reported no SDC "
                    "and preprocessed uncorrected."
                ),
            ),
            EvidenceFigure(
                key="coreg",
                label="BOLD to T1w coregistration",
                pattern="desc-coreg_bold.svg",
                scope="run",
                look_for=(
                    "Follow the contour overlay around the ventricles and the cortical "
                    "ribbon. Ventricle edges are the most sensitive place to see a "
                    "few millimetres of misalignment; a rotation usually shows as good "
                    "agreement at one end of the brain and drift at the other."
                ),
            ),
            EvidenceFigure(
                key="fmapCoreg",
                label="Fieldmap to BOLD coregistration",
                pattern="desc-fmapCoreg_bold.svg",
                scope="run",
                look_for=(
                    "The fieldmap has to be aligned to the BOLD before it can correct "
                    "it. If this is off, SDC will confidently apply the wrong warp, "
                    "which is worse than applying none — check this figure before "
                    "trusting the SDC one above."
                ),
                absent_means=(
                    "Written only when a fieldmap was applied, so it goes missing "
                    "alongside the distortion-correction figure and for the same "
                    "reason. Read that one's note first."
                ),
            ),
            EvidenceFigure(
                key="rois",
                label="Brain mask and CompCor ROIs",
                pattern="desc-rois_bold.svg",
                scope="run",
                look_for=(
                    "The brain mask should follow the brain without clipping cortex or "
                    "swallowing skull and neck. The CSF and white-matter ROIs feeding "
                    "CompCor must sit inside their tissues: a CSF ROI that has leaked "
                    "into grey matter turns the confound regressors into signal "
                    "regressors."
                ),
            ),
            EvidenceFigure(
                key="pepolar",
                label="Fieldmap estimation (PEPOLAR)",
                pattern="desc-pepolar_fieldmap.svg",
                scope="subject",
                look_for=(
                    "The estimated field should be smooth and anatomically plausible, "
                    "strongest near air–tissue boundaries. Speckle or a sharp "
                    "discontinuity means the estimation failed, and every run it "
                    "serves inherits the error."
                ),
                absent_means=(
                    "No fieldmap was estimated for this session, so no run in it "
                    "received distortion correction. A session with two fieldmap pairs "
                    "shows two of these figures — both are listed, because which pair "
                    "served a given run depends on acquisition time."
                ),
            ),
            EvidenceFigure(
                key="dseg",
                label="Tissue segmentation on the T1w",
                pattern="dseg.svg",
                scope="subject",
                look_for=(
                    "Boundaries should follow the tissue, not cut across it. "
                    "Segmentation failures propagate into coregistration, CompCor and "
                    "surface reconstruction alike, so this figure is worth reading "
                    "before any of the run-level ones."
                ),
            ),
            EvidenceFigure(
                key="norm",
                label="Spatial normalization to the template",
                pattern="space-*_T1w.svg",
                scope="subject",
                look_for=(
                    "The alternating overlay should keep the ventricles, corpus "
                    "callosum and outer cortical boundary in register. Watch for the "
                    "brain being globally too large or small, which is a scaling "
                    "failure rather than a local one."
                ),
            ),
            EvidenceFigure(
                key="reconall",
                label="Surface reconstruction",
                pattern="desc-reconall_T1w.svg",
                scope="subject",
                look_for=(
                    "White and pial surfaces should hug their boundaries all the way "
                    "round. Surfaces cutting through the skull, or bulging into the "
                    "sinuses and eyes, mean the reconstruction failed for that "
                    "subject — only relevant when FreeSurfer was actually run."
                ),
                absent_means=(
                    "FreeSurfer surface reconstruction did not run for this subject. "
                    "Usually that is deliberate — `--fs-no-reconall` — and not a "
                    "failure; check how fMRIPrep was submitted before treating it as "
                    "one."
                ),
            ),
        ),
        caveat=(
            "The `tpm_overlap_*` numbers here measure overlap with template tissue "
            "maps after **MRIQC's own** registration. They say nothing about whether "
            "**fMRIPrep's** normalization worked — that is what the figures are for. "
            "A reviewer who sees the only three numbers in this domain will assume "
            "otherwise, so the distinction is stated rather than left to be inferred."
        ),
        not_applicable={
            "bold": (
                "MRIQC computes no registration measure for functional data, so this "
                "domain carries no numbers here. Alignment is reviewed visually, from "
                "the per-run distortion-correction, coregistration and fieldmap "
                "figures below — that is the section's purpose, not a gap in it."
            ),
            "dwi": (
                "MRIQC computes no registration measure for diffusion data. Alignment "
                "for DWI is reviewed from fMRIPrep's or QSIPrep's own reports, which "
                "duckbrain does not read yet."
            ),
        },
    )
)

_register(
    ReviewDomain(
        key="artifact",
        label="Artifacts & inhomogeneity",
        question=(
            "Is the image corrupted by something other than noise — ghosting, ringing, bias, blur?"
        ),
        measures=(
            "efc",
            "gsr_x",
            "gsr_y",
            "qi_1",
            "qi_2",
            "inu_range",
            "inu_med",
            "wm2max",
            "fwhm_avg",
        ),
        caveat=(
            "MRIQC writes `-1` for FBER and QI1 when an image has no usable "
            "background, which is what a defaced or skull-stripped input looks like. "
            "That is a sentinel, not a catastrophic score, and it will sort to the "
            "extreme of any ranking and can trip the outlier fence on its own."
        ),
    )
)


# ---------------------------------------------------------------------------
# Lookup API
# ---------------------------------------------------------------------------


def get_domain(key: str) -> ReviewDomain:
    """Return the domain with *key*. Raises :class:`KeyError` if there is none.

    This used to be declared ``-> ReviewDomain | None`` and nothing enforced it:
    of the 27 call sites, **zero** checked the result before reading an
    attribute off it. That is the difference between a return type and a shrug.
    The keys are literals written next to the registry — a QC page says
    ``render_domain_page("signal")`` — so an unknown one is a typo in the
    source, never a state a user can reach, and the useful behaviour is to say
    which key was wrong rather than to hand back a ``None`` that becomes
    ``AttributeError: 'NoneType' object has no attribute 'label'`` one line
    later.

    :func:`domain_of` keeps its ``| None``, and that is the contrast worth
    seeing: an undocumented *measure* is a real, expected answer.
    """
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"no QC review domain {key!r}; registered domains are "
            f"{', '.join(repr(d.key) for d in DOMAINS)}"
        ) from None


def domain_of(measure: str) -> ReviewDomain | None:
    """Return the domain owning *measure*, or ``None`` if it is undocumented."""
    owner = _MEASURE_OWNER.get(measure)
    return _BY_KEY[owner] if owner else None


def measures_for(modality: str, domain_key: str) -> list[str]:
    """Return *domain_key*'s measures documented for *modality*, in registry order.

    An empty list is a real answer — pair it with
    :meth:`ReviewDomain.explain_absence` rather than rendering nothing.
    """
    domain = _BY_KEY.get(domain_key)
    return domain.measures_for(modality) if domain else []


def domains_for_modality(modality: str) -> list[ReviewDomain]:
    """Return **every** domain, always, in taxonomy order.

    Deliberately not filtered to the non-empty ones. A domain that does not
    apply to this modality still has something to say about why, and dropping it
    from the list would leave a reviewer unable to tell "nothing to check here"
    from "duckbrain forgot to check it".
    """
    return list(DOMAINS)


def undomained_keys() -> list[str]:
    """Return registry measures no domain claims.

    The partition is enforced at import, so this can only be non-empty when a
    measure has been added to the guidance registry without being placed. Used
    by the test suite to say so with a useful message.
    """
    return [k for k in MEASURE_GUIDANCE if k not in _MEASURE_OWNER]
