"""Tests for duckbrain.core.qc_guidance — the QC review guidance registry.

These tests guard the contract the dashboard depends on: every column it
renders carries guidance, every entry is complete, and every citation is a
real link rather than a placeholder.

``TestAgainstRealMriqcOutput`` is the one class that could not have been written
in mmmdata's repo without the same fixtures: it pins the registry's metric names
against JSON a real MRIQC run actually emitted, which is the only way a wrong key
name gets caught. A wrong key renders a blank column and says nothing.
"""

import json
import re
from pathlib import Path

import pytest

from duckbrain.core import qc
from duckbrain.core.qc_guidance import (
    MEASURE_GUIDANCE,
    PROCESS_GUIDANCE,
    MeasureGuidance,
    Reference,
    all_references,
    get_guidance,
    guidance_for_keys,
    guidance_for_modality,
    guidance_markdown,
    render_guidance_section,
    render_measure_card,
    render_process_section,
    undocumented_keys,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mriqc"


def _fixture(modality: str) -> dict:
    return json.loads((FIXTURES / f"{modality}.json").read_text())


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


class TestRegistryCoverage:
    def test_every_iqm_duckbrain_surfaces_is_documented(self):
        """No column may reach a reviewer without an explanation."""
        missing = {
            name: undocumented_keys(cols)
            for name, cols in (("bold", qc.BOLD_IQMS), ("anat", qc.ANAT_IQMS))
            if undocumented_keys(cols)
        }
        assert missing == {}, f"IQM columns lacking guidance: {missing}"

    def test_derived_motion_columns_are_documented(self):
        """mean_fd/pct_high_motion are computed by duckbrain, not by MRIQC."""
        assert undocumented_keys(["mean_fd", "pct_high_motion"]) == []

    def test_registry_key_matches_entry_key(self):
        for key, g in MEASURE_GUIDANCE.items():
            assert key == g.key


# ---------------------------------------------------------------------------
# Entry quality
# ---------------------------------------------------------------------------


class TestEntryQuality:
    def test_all_entries_answer_all_three_questions(self):
        """why / look_for / auto_flag are the point of the layer."""
        for key, g in MEASURE_GUIDANCE.items():
            assert g.why.strip(), f"{key} missing 'why'"
            assert g.look_for.strip(), f"{key} missing 'look_for'"
            assert g.auto_flag.strip(), f"{key} missing 'auto_flag'"
            assert g.label.strip(), f"{key} missing label"

    def test_all_entries_carry_at_least_one_reference(self):
        bare = [k for k, g in MEASURE_GUIDANCE.items() if not g.references]
        assert bare == [], f"Measures with no cited source: {bare}"

    def test_all_entries_declare_modalities(self):
        valid = {"bold", "T1w", "T2w", "dwi"}
        for key, g in MEASURE_GUIDANCE.items():
            assert g.modalities, f"{key} declares no modality"
            assert set(g.modalities) <= valid, f"{key} has unknown modality"

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValueError, match="Invalid direction"):
            MeasureGuidance(
                key="x",
                label="X",
                modalities=("bold",),
                direction="sideways",
                why="w",
                look_for="l",
                auto_flag="a",
            )

    def test_invalid_reference_kind_rejected(self):
        with pytest.raises(ValueError, match="Invalid reference kind"):
            Reference(label="L", detail="D", url="https://x", kind="rumour")


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


class TestReferences:
    def test_all_urls_are_resolvable_links(self):
        for r in all_references():
            assert r.url.startswith("https://"), f"{r.label}: {r.url!r}"

    def test_no_placeholder_citations(self):
        for r in all_references():
            assert "example.com" not in r.url
            assert "TODO" not in r.label + r.detail + r.url

    def test_references_are_deduplicated_by_url(self):
        urls = [r.url for r in all_references()]
        assert len(urls) == len(set(urls))

    def test_dois_are_well_formed(self):
        for r in all_references():
            if "doi.org" in r.url:
                assert re.search(r"doi\.org/10\.\d{4,}/", r.url), r.url


# ---------------------------------------------------------------------------
# Lookup API
# ---------------------------------------------------------------------------


class TestLookup:
    def test_get_guidance_hit_and_miss(self):
        assert get_guidance("fd_mean") is not None
        assert get_guidance("not_a_metric") is None

    def test_guidance_for_modality_filters(self):
        bold_keys = {g.key for g in guidance_for_modality("bold")}
        anat_keys = {g.key for g in guidance_for_modality("T1w")}
        assert "tsnr" in bold_keys
        assert "tsnr" not in anat_keys
        assert "cjv" in anat_keys
        assert "cjv" not in bold_keys

    def test_guidance_for_keys_preserves_order_and_skips_unknown(self):
        result = guidance_for_keys(["tsnr", "nope", "fd_mean"])
        assert [g.key for g in result] == ["tsnr", "fd_mean"]

    def test_tooltip_mentions_direction_and_why(self):
        tip = get_guidance("fd_mean").tooltip()
        assert "lower is better" in tip
        assert "Why:" in tip and "Look for:" in tip


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering:
    def test_measure_card_has_anchor_and_sections(self):
        html = render_measure_card(get_guidance("fd_mean"))
        assert 'id="guidance-fd_mean"' in html
        assert "Why it is here" in html
        assert "What to look for" in html
        assert "Flagged automatically" in html

    def test_measure_card_escapes_html(self):
        g = MeasureGuidance(
            key="x",
            label="X",
            modalities=("bold",),
            direction="context",
            why="<script>alert(1)</script>",
            look_for="a & b",
            auto_flag="c",
            references=(Reference(label="L", detail="D", url="https://x.org"),),
        )
        html = render_measure_card(g)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "a &amp; b" in html

    def test_guidance_section_renders_requested_keys_only(self):
        html = render_guidance_section(["tsnr"])
        assert 'id="guidance-tsnr"' in html
        assert 'id="guidance-cjv"' not in html

    def test_process_section_renders_all_notes(self):
        html = render_process_section()
        for note in PROCESS_GUIDANCE:
            assert f'id="guidance-{note.key}"' in html
            assert note.title in html

    def test_markdown_export_covers_registry(self):
        md = guidance_markdown()
        assert md.startswith("# QC review guidance")
        for key in MEASURE_GUIDANCE:
            assert f"`{key}`" in md

    def test_markdown_export_can_be_scoped_to_one_modality(self):
        md = guidance_markdown(modalities=["bold"])
        assert "`tsnr`" in md
        assert "`cjv`" not in md


# ---------------------------------------------------------------------------
# Real MRIQC output
# ---------------------------------------------------------------------------


class TestAgainstRealMriqcOutput:
    """Pin registry metric names to what MRIQC 24.1.0.dev0 actually writes.

    The fixtures are real output with ``bids_meta`` and ``provenance`` stripped,
    so they carry no subject or scanner identifiers — only the numbers and, more
    to the point, the *key names*. Synthetic fixtures cannot catch a wrong key
    name because they are written from the same assumption as the code.
    """

    @pytest.mark.parametrize("modality", ["bold", "T1w", "T2w"])
    def test_registry_names_exist_in_real_output(self, modality):
        """Every documented key for this modality is one MRIQC really emits.

        ``mean_fd`` and ``pct_high_motion`` are excluded because duckbrain
        derives them from fMRIPrep confounds; MRIQC never writes them.
        """
        derived = {"mean_fd", "pct_high_motion"}
        real = set(_fixture(modality))
        documented = {g.key for g in guidance_for_modality(modality)} - derived
        assert documented <= real, f"documented but absent from MRIQC: {documented - real}"

    def test_tissue_overlap_keys_are_tpm_prefixed(self):
        """MRIQC's docs say ``overlap_*_*``; its output says ``tpm_overlap_*``.

        The registry follows the output. Verified against a real 24.1.0.dev0 run
        2026-07-24 — the docs are the stale side.
        """
        real = _fixture("T1w")
        for tissue in ("csf", "gm", "wm"):
            assert f"tpm_overlap_{tissue}" in real
            assert f"overlap_{tissue}" not in real
            assert get_guidance(f"tpm_overlap_{tissue}") is not None

    def test_fd_perc_exists_and_is_cited_at_the_mriqc_default(self):
        """Parkes' 20% rule is only citable if MRIQC counts frames at 0.2 mm.

        Confirmed empirically across all 65 BOLD runs of divatten_beta:
        ``count(FD > 0.2) == fd_num`` in 65/65, and at no other threshold.
        """
        real = _fixture("bold")
        assert "fd_perc" in real and "fd_num" in real
        threshold = get_guidance("fd_perc").literature_threshold
        assert "0.2" in threshold and "20" in threshold

    def test_fd_perc_is_a_percentage_of_all_volumes(self):
        """The denominator is size_t, not the number of FD estimates.

        FD is undefined for the first volume, so the two differ by one frame.
        """
        real = _fixture("bold")
        assert real["fd_perc"] == pytest.approx(100 * real["fd_num"] / real["size_t"], rel=1e-4)

    def test_minus_one_is_a_sentinel_not_a_score(self):
        """MRIQC writes -1 for FBER when the image has no usable background.

        The T2w fixture is a real defaced scan that hit this. Left undefended it
        sorts to the extreme of any ranking and trips the outlier fence, so the
        guidance has to say so or a reviewer reads it as a catastrophic score.
        """
        assert _fixture("T2w")["fber"] == -1
        assert "-1" in get_guidance("fber").caveats


# ---------------------------------------------------------------------------
# Configured thresholds
# ---------------------------------------------------------------------------


class TestQcSettings:
    @pytest.fixture
    def only_shipped_config(self, monkeypatch, tmp_path):
        """Strip the user and project layers so only base.toml is in play."""
        monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)
        monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(tmp_path / "absent.toml"))

    def test_defaults_come_from_shipped_config(self, only_shipped_config):
        settings = qc.qc_settings()
        assert set(settings) == set(qc.DEFAULT_QC_SETTINGS)
        assert all(isinstance(v, float) for v in settings.values())

    def test_project_config_overrides_a_threshold(self, tmp_path):
        code = tmp_path / "code"
        code.mkdir()
        (code / "duckbrain.toml").write_text("[qc]\niqr_multiplier = 3.0\n")
        assert qc.qc_settings(project_dir=tmp_path)["iqr_multiplier"] == 3.0

    def test_unreadable_config_warns_rather_than_defaulting_in_silence(self, monkeypatch):
        """A threshold quietly not the one you configured is the worse failure."""
        import duckbrain.config

        def boom(**kwargs):
            raise RuntimeError("no config here")

        monkeypatch.setattr(duckbrain.config, "load_config", boom)
        with pytest.warns(RuntimeWarning, match="Could not read"):
            assert qc.qc_settings() == qc.DEFAULT_QC_SETTINGS

    def test_non_numeric_threshold_warns_and_keeps_the_default(self, tmp_path):
        code = tmp_path / "code"
        code.mkdir()
        (code / "duckbrain.toml").write_text('[qc]\niqr_multiplier = "wide"\n')
        with pytest.warns(RuntimeWarning, match="not a number"):
            settings = qc.qc_settings(project_dir=tmp_path)
        assert settings["iqr_multiplier"] == qc.DEFAULT_QC_SETTINGS["iqr_multiplier"]

    def test_shipped_defaults_match_base_toml(self, only_shipped_config):
        """The fallback dict and the shipped config must not drift apart."""
        from duckbrain.config import load_config

        shipped = load_config().get("qc", {})
        assert shipped == pytest.approx(qc.DEFAULT_QC_SETTINGS)
