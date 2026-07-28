"""Tests for duckbrain.core.qc_domains — the review-domain taxonomy.

Two contracts matter here, and both are things a reviewer would never see fail
directly.

The first is the **partition**: every guidance entry belongs to exactly one
domain. Violating it renders duplicate ``id="guidance-{key}"`` blocks into the
exported report, and an in-page anchor then lands wherever the browser decides.
The registry enforces this at import, so these tests mostly assert that the
enforcement is real rather than re-checking it.

The second is that **an empty projection still says something**. Two of the
sixteen (domain, modality) pairs have no measures at all — temporal on
structural data, alignment on functional — and per ``CLAUDE.md`` a section that
renders blank is the silent degradation the project forbids. A blank section and
a section that failed to load are indistinguishable to the reader.
"""

from collections import Counter

import pytest

from duckbrain.core import qc_domains
from duckbrain.core.qc_domains import (
    DOMAINS,
    MODALITIES,
    EvidenceFigure,
    ReviewDomain,
    domain_of,
    domains_for_modality,
    get_domain,
    measures_for,
    undomained_keys,
)
from duckbrain.core.qc_guidance import MEASURE_GUIDANCE

# ---------------------------------------------------------------------------
# The partition
# ---------------------------------------------------------------------------


class TestPartition:
    def test_every_documented_measure_belongs_to_a_domain(self):
        """A measure with no domain would vanish from a domain-organised page."""
        assert undomained_keys() == []

    def test_no_measure_is_claimed_twice(self):
        """Duplicate ownership means duplicate guidance anchors in the report."""
        owned = Counter(m for d in DOMAINS for m in d.measures)
        assert [m for m, n in owned.items() if n > 1] == []

    def test_the_domains_cover_the_registry_exactly(self):
        assert {m for d in DOMAINS for m in d.measures} == set(MEASURE_GUIDANCE)

    def test_a_domain_may_not_claim_an_undocumented_measure(self):
        """Registration is the check, not construction — a typo'd key is caught."""
        bad = ReviewDomain(key="x", label="X", question="?", measures=("not_a_measure",))
        with pytest.raises(ValueError, match="no guidance entry"):
            qc_domains._register(bad)

    def test_registering_a_measure_twice_raises(self):
        dup = ReviewDomain(key="dup", label="Dup", question="?", measures=("tsnr",))
        with pytest.raises(ValueError, match="partition"):
            qc_domains._register(dup)

    def test_registering_a_duplicate_domain_key_raises(self):
        with pytest.raises(ValueError, match="Duplicate review domain"):
            qc_domains._register(ReviewDomain(key="signal", label="Again", question="?"))

    def test_registering_a_duplicate_evidence_key_raises(self):
        fig = EvidenceFigure(key="same", label="Same", pattern="x.svg", scope="run", look_for="...")
        with pytest.raises(ValueError, match="Duplicate evidence figure"):
            qc_domains._register(
                ReviewDomain(key="figs", label="Figs", question="?", evidence=(fig, fig))
            )

    def test_a_rejected_registration_leaves_the_taxonomy_untouched(self):
        """A raise mid-registration must not half-add a domain for later tests.

        The evidence case is the one that caught a real bug: measures used to be
        recorded as owned before the figures were validated, so a domain refused
        for a duplicate figure left its measures claimed by a domain that was
        never added — and the next legitimate claimant would then be rejected.
        """
        before = tuple(qc_domains.DOMAINS)
        fig = EvidenceFigure(key="same", label="Same", pattern="x.svg", scope="run", look_for="...")
        for bad in (
            ReviewDomain(key="x", label="X", question="?", measures=("not_a_measure",)),
            ReviewDomain(key="dup", label="Dup", question="?", measures=("tsnr",)),
            ReviewDomain(key="signal", label="Again", question="?"),
            ReviewDomain(key="figs", label="Figs", question="?", evidence=(fig, fig)),
            ReviewDomain(
                key="both", label="Both", question="?", measures=("efc",), evidence=(fig, fig)
            ),
        ):
            with pytest.raises(ValueError):
                qc_domains._register(bad)
        assert qc_domains.DOMAINS == before
        assert undomained_keys() == []
        assert domain_of("efc").key == "artifact"


# ---------------------------------------------------------------------------
# Entry quality
# ---------------------------------------------------------------------------


class TestEntryQuality:
    def test_there_are_four_domains_in_a_stable_order(self):
        assert [d.key for d in DOMAINS] == ["signal", "temporal", "alignment", "artifact"]

    @pytest.mark.parametrize("domain", DOMAINS, ids=lambda d: d.key)
    def test_every_domain_states_its_question(self, domain):
        """The question is what lets a reviewer who knows no IQM navigate."""
        assert domain.question.strip()
        assert domain.question.rstrip().endswith("?")

    @pytest.mark.parametrize("domain", DOMAINS, ids=lambda d: d.key)
    def test_every_domain_has_a_label_and_key(self, domain):
        assert domain.key and domain.key.islower()
        assert domain.label.strip()

    @pytest.mark.parametrize(
        "fig",
        [e for d in DOMAINS for e in d.evidence],
        ids=lambda e: e.key,
    )
    def test_every_evidence_figure_says_what_to_look_for(self, fig):
        """A figure with no look_for is a picture with no review attached."""
        assert len(fig.look_for.split()) >= 20, f"{fig.key} look_for is too thin to act on"
        assert fig.pattern.endswith((".svg", ".html"))

    def test_an_invalid_evidence_scope_raises(self):
        with pytest.raises(ValueError, match="Invalid scope"):
            EvidenceFigure(key="x", label="X", pattern="x.svg", scope="session", look_for="...")

    def test_alignment_states_what_its_numbers_do_not_mean(self):
        """tpm_overlap_* grades MRIQC's registration, not fMRIPrep's."""
        caveat = get_domain("alignment").caveat
        assert "MRIQC" in caveat and "fMRIPrep" in caveat


# ---------------------------------------------------------------------------
# Projection onto a modality — and the empty cases
# ---------------------------------------------------------------------------


class TestModalityProjection:
    def test_bold_measures_land_where_expected(self):
        assert measures_for("bold", "signal") == ["tsnr", "snr", "fber"]
        assert measures_for("bold", "temporal") == [
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
        ]
        assert measures_for("bold", "artifact") == ["efc", "gsr_x", "gsr_y", "fwhm_avg"]

    def test_anat_measures_land_where_expected(self):
        assert measures_for("T1w", "signal") == [
            "snr_total",
            "snr_gm",
            "snr_wm",
            "cnr",
            "cjv",
            "fber",
        ]
        assert measures_for("T1w", "alignment") == [
            "tpm_overlap_gm",
            "tpm_overlap_wm",
            "tpm_overlap_csf",
        ]

    def test_a_measure_resolves_back_to_its_domain(self):
        assert domain_of("tsnr").key == "signal"
        assert domain_of("mean_fd").key == "temporal"
        assert domain_of("tpm_overlap_gm").key == "alignment"
        assert domain_of("gsr_x").key == "artifact"
        assert domain_of("not_a_measure") is None

    def test_projection_preserves_registry_order(self):
        """The glossary follows column order, so ordering is a contract."""
        for modality in MODALITIES:
            for domain in DOMAINS:
                got = domain.measures_for(modality)
                assert got == [m for m in domain.measures if m in got]

    @pytest.mark.parametrize(
        "modality,domain_key",
        [("T1w", "temporal"), ("T2w", "temporal"), ("bold", "alignment"), ("dwi", "alignment")],
    )
    def test_an_empty_projection_explains_itself(self, modality, domain_key):
        """The silent-degradation rule, as an assertion.

        These four pairs are the ones with no measures. Each must state why in a
        sentence a reviewer can act on, not render blank.
        """
        assert measures_for(modality, domain_key) == []
        why = get_domain(domain_key).explain_absence(modality)
        assert len(why.split()) >= 15, f"{domain_key}/{modality} absence is unexplained"

    def test_absence_is_never_blank_even_for_an_unlisted_modality(self):
        """A caller cannot render nothing by trusting a key nobody filled in."""
        assert get_domain("signal").explain_absence("dwi").strip()

    def test_temporal_on_anat_points_at_where_motion_did_go(self):
        """Empty is not the end of the answer — efc is the anatomical proxy."""
        assert "efc" in get_domain("temporal").explain_absence("T1w")

    def test_every_domain_is_listed_for_every_modality(self):
        """Filtering out inapplicable domains would hide that they were considered."""
        for modality in MODALITIES:
            assert [d.key for d in domains_for_modality(modality)] == [d.key for d in DOMAINS]


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_alignment_carries_the_figures_it_is_reviewed_from(self):
        """Alignment on BOLD has no numbers, so the figures are the whole domain."""
        keys = [e.key for e in get_domain("alignment").evidence_for("bold")]
        assert {"sdc", "coreg", "fmapCoreg"} <= set(keys)

    def test_anat_modalities_see_only_subject_scoped_figures(self):
        """Run-scoped reportlets are BOLD-only; fMRIPrep writes no others."""
        for fig in get_domain("alignment").evidence_for("T1w"):
            assert fig.scope == "subject"

    def test_subject_figures_survive_the_modality_switch(self):
        """A failed surface reconstruction is a fact about the subject."""
        keys = [e.key for e in get_domain("alignment").evidence_for("T1w")]
        assert {"dseg", "norm", "reconall"} <= set(keys)

    def test_the_normalization_figure_does_not_hardcode_a_template(self):
        """Output space is a project choice; the pattern must glob it."""
        norm = next(e for e in get_domain("alignment").evidence if e.key == "norm")
        assert "*" in norm.pattern and "MNI" not in norm.pattern

    def test_carpetplot_belongs_to_temporal(self):
        """FD, DVARS and the carpet are read together or not at all."""
        assert "carpetplot" in [e.key for e in get_domain("temporal").evidence]
