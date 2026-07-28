"""Tests for duckbrain.core.qc_evidence — finding fMRIPrep's figures per run.

The fixture trees here are modelled on two real datasets, because the two
disagree in exactly the way that breaks a naive implementation:

* ``divatten_beta_v2`` is sessionless, and its anatomical figures are plain —
  ``sub-010_dseg.svg``.
* ``mmmdata`` has seven sessions, and its anatomical figures carry an
  acquisition entity the run key never mentions — ``sub-03_acq-MPR_dseg.svg`` —
  while ``figures/`` still sits at the *subject* level, with the session in the
  filename.

Joining a run key to a pattern works on the first and finds nothing on the
second. That is why matching is by entity, and it is what these tests pin.
"""

from pathlib import Path

import pytest

from duckbrain.core import qc_evidence as ev
from duckbrain.core.qc_domains import EvidenceFigure, get_domain

# An SVG shaped like fMRIPrep's animated reportlets: the before/after flicker is
# a CSS animation carried *inside* the file, which is what makes serving one
# figure on its own possible at all.
ANIMATED_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<style>@keyframes flicker { 0% {opacity:1} 50% {opacity:0} 100% {opacity:1} }
.f { animation: flicker 2s infinite; }</style>
<rect class="f" width="10" height="10"/></svg>
"""


def _tree(root: Path, subject: str, names: list[str]) -> Path:
    """Create ``<root>/<subject>/figures/`` holding *names*."""
    figures = root / subject / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for name in names:
        (figures / name).write_text(ANIMATED_SVG)
    return root


@pytest.fixture
def sessionless(tmp_path):
    """divatten_beta_v2's shape: no sessions, plain anatomical figures."""
    return _tree(
        tmp_path / "fmriprep",
        "sub-010",
        [
            "sub-010_task-rest_run-1_desc-sdc_bold.svg",
            "sub-010_task-rest_run-1_desc-coreg_bold.svg",
            "sub-010_task-rest_run-2_desc-coreg_bold.svg",
            "sub-010_task-other_run-1_desc-coreg_bold.svg",
            "sub-010_dseg.svg",
            "sub-010_space-MNI152NLin2009cAsym_T1w.svg",
            "sub-010_fmapid-B0map25mm_desc-pepolar_fieldmap.svg",
        ],
    )


@pytest.fixture
def sessioned(tmp_path):
    """mmmdata's shape: sessions in the filename, acq- on the anatomicals."""
    return _tree(
        tmp_path / "fmriprep",
        "sub-03",
        [
            "sub-03_ses-02_task-prf_run-01_desc-sdc_bold.svg",
            "sub-03_ses-02_task-prf_run-01_desc-coreg_bold.svg",
            "sub-03_ses-03_task-prf_run-01_desc-coreg_bold.svg",
            "sub-03_acq-MPR_dseg.svg",
            "sub-03_acq-MPR_desc-preproc_dseg.svg",
            "sub-03_ses-02_run-01_fmapid-first_desc-pepolar_fieldmap.svg",
            "sub-03_ses-02_run-02_fmapid-second_desc-pepolar_fieldmap.svg",
            "sub-03_ses-03_run-01_fmapid-other_desc-pepolar_fieldmap.svg",
        ],
    )


def _fig(key):
    return next(e for e in get_domain("alignment").evidence if e.key == key)


# ---------------------------------------------------------------------------
# Where the figures live
# ---------------------------------------------------------------------------


class TestFiguresDir:
    def test_figures_sit_at_the_subject_level_even_with_sessions(self, tmp_path):
        """fMRIPrep puts the session in the filename, never in the path.

        Assuming a ``ses-XX/figures`` level would find nothing for every session
        project, which is the whole population this would matter for.
        """
        assert ev.figures_dir(tmp_path, "sub-03") == tmp_path / "sub-03" / "figures"

    def test_a_bare_subject_label_is_accepted(self, tmp_path):
        assert ev.figures_dir(tmp_path, "03") == tmp_path / "sub-03" / "figures"


# ---------------------------------------------------------------------------
# Run-scoped matching
# ---------------------------------------------------------------------------


class TestRunScopedFigures:
    def test_a_run_figure_is_found_for_its_own_run(self, sessionless):
        hit = ev.find_figure(sessionless, _fig("sdc"), "sub-010_task-rest_run-1_bold")
        assert hit.found
        assert hit.paths[0].name == "sub-010_task-rest_run-1_desc-sdc_bold.svg"

    def test_another_runs_figure_is_not_offered(self, sessionless):
        """run-2's coregistration must not appear while reviewing run-1."""
        hit = ev.find_figure(sessionless, _fig("coreg"), "sub-010_task-rest_run-1_bold")
        assert [p.name for p in hit.paths] == ["sub-010_task-rest_run-1_desc-coreg_bold.svg"]

    def test_another_tasks_figure_is_not_offered(self, sessionless):
        hit = ev.find_figure(sessionless, _fig("coreg"), "sub-010_task-rest_run-1_bold")
        assert not any("task-other" in p.name for p in hit.paths)

    def test_session_entities_are_honoured(self, sessioned):
        hit = ev.find_figure(sessioned, _fig("coreg"), "sub-03_ses-02_task-prf_run-01_bold")
        assert [p.name for p in hit.paths] == ["sub-03_ses-02_task-prf_run-01_desc-coreg_bold.svg"]

    def test_a_session_figure_is_not_offered_to_a_sessionless_selection(self, sessioned):
        """The entity the file carries and the key lacks must disqualify it."""
        hit = ev.find_figure(sessioned, _fig("coreg"), "sub-03_task-prf_run-01_bold")
        assert not hit.found


# ---------------------------------------------------------------------------
# Subject-scoped matching — the case a prefix join gets wrong
# ---------------------------------------------------------------------------


class TestSubjectScopedFigures:
    def test_an_anatomical_figure_with_an_extra_entity_is_still_found(self, sessioned):
        """``sub-03_acq-MPR_dseg.svg`` — a prefix join finds nothing here.

        This is the case that made entity matching necessary rather than
        merely tidier.
        """
        hit = ev.find_figure(sessioned, _fig("dseg"), "sub-03_ses-02_task-prf_run-01_bold")
        assert {p.name for p in hit.paths} == {
            "sub-03_acq-MPR_dseg.svg",
            "sub-03_acq-MPR_desc-preproc_dseg.svg",
        }

    def test_a_subject_figure_is_offered_whatever_the_run(self, sessioned):
        """It has no session or task, so it applies to every selection."""
        for run_key in ("sub-03_ses-02_task-prf_run-01_bold", "sub-03_ses-03_task-x_bold"):
            assert ev.find_figure(sessioned, _fig("dseg"), run_key).found

    def test_a_fieldmap_from_another_session_is_not_offered(self, sessioned):
        """Fieldmaps are estimated per session and their figures carry ``ses``.

        Matching on subject alone would offer ses-03's fieldmap while reviewing
        ses-02 — a figure describing a different acquisition entirely.
        """
        hit = ev.find_figure(sessioned, _fig("pepolar"), "sub-03_ses-02_task-prf_run-01_bold")
        assert {p.name for p in hit.paths} == {
            "sub-03_ses-02_run-01_fmapid-first_desc-pepolar_fieldmap.svg",
            "sub-03_ses-02_run-02_fmapid-second_desc-pepolar_fieldmap.svg",
        }

    def test_a_fieldmaps_own_run_index_does_not_have_to_match_the_bolds(self, sessioned):
        """``run-02`` on a fieldmap counts fieldmaps, not BOLD runs.

        Comparing the two would reject every fieldmap for run-01 of a task, which
        is why ``run`` is excluded from subject-scoped matching.
        """
        hit = ev.find_figure(sessioned, _fig("pepolar"), "sub-03_ses-02_task-prf_run-01_bold")
        assert any("run-02" in p.name for p in hit.paths)

    def test_both_fieldmap_pairs_in_a_session_are_returned(self, sessioned):
        """A session with two pairs has two estimation figures, and both matter."""
        hit = ev.find_figure(sessioned, _fig("pepolar"), "sub-03_ses-02_task-prf_run-01_bold")
        assert len(hit.paths) == 2


# ---------------------------------------------------------------------------
# Absence is a result, not a gap
# ---------------------------------------------------------------------------


class TestAbsence:
    def test_a_missing_figure_yields_a_hit_that_explains_itself(self, sessionless):
        """Absent SDC is a finding: the run was preprocessed without correction."""
        hit = ev.find_figure(sessionless, _fig("sdc"), "sub-010_task-rest_run-2_bold")
        assert not hit.found
        assert "no distortion" in hit.explain_absence().lower()

    def test_collect_keeps_the_place_of_an_absent_figure(self, sessionless):
        """A shorter list is indistinguishable from a complete one."""
        hits = ev.collect(sessionless, get_domain("alignment"), "sub-010_task-rest_run-2_bold")
        declared = get_domain("alignment").evidence_for("bold")
        assert len(hits) == len(declared)
        assert [h.figure.key for h in hits] == [f.key for f in declared]

    def test_every_absence_is_explained(self, sessionless):
        """No figure may report its absence as the empty string."""
        for hit in ev.collect(sessionless, get_domain("alignment"), "sub-999_task-x_bold"):
            assert hit.explain_absence().strip()

    def test_a_missing_figures_directory_does_not_raise(self, tmp_path):
        hit = ev.find_figure(tmp_path / "nope", _fig("sdc"), "sub-010_task-rest_bold")
        assert not hit.found

    def test_a_derivatives_path_that_is_a_file_does_not_raise(self, tmp_path):
        """pathlib yields nothing rather than raising, so absence handles it.

        Pinned because the code relies on that behaviour instead of guarding for
        it — a guard would be unreachable, and unreachable guards rot.
        """
        not_a_dir = tmp_path / "fmriprep"
        not_a_dir.write_text("this is a file")
        assert not ev.find_figure(not_a_dir, _fig("sdc"), "sub-010_task-rest_bold").found
        assert ev.runs_with_figures(not_a_dir, "sub-010") == []

    def test_a_run_key_with_no_subject_yields_nothing_rather_than_raising(self, sessionless):
        assert not ev.find_figure(sessionless, _fig("sdc"), "task-rest_run-1_bold").found


# ---------------------------------------------------------------------------
# What the viewer is handed
# ---------------------------------------------------------------------------


class TestServedContent:
    def test_the_animation_survives_being_served_on_its_own(self, sessionless):
        """The SDC flicker is CSS inside the SVG, and must stay there.

        Serving one figure instead of the whole 80 MB report is only viable
        because the animation does not depend on the enclosing document. A
        plausible future size optimisation is to strip SVG styles; this fails
        loudly if anything starts rewriting the bytes on the way out.
        """
        hit = ev.find_figure(sessionless, _fig("sdc"), "sub-010_task-rest_run-1_bold")
        served = hit.paths[0].read_text()
        assert "@keyframes" in served and "animation:" in served

    def test_the_cost_is_knowable_before_it_is_spent(self, sessionless):
        """The viewer names the megabytes before loading them."""
        hit = ev.find_figure(sessionless, _fig("dseg"), "sub-010_task-rest_run-1_bold")
        assert hit.total_bytes == len(ANIMATED_SVG.encode())

    def test_total_bytes_survives_a_file_vanishing(self, sessionless):
        hit = ev.find_figure(sessionless, _fig("dseg"), "sub-010_task-rest_run-1_bold")
        hit.paths[0].unlink()
        assert hit.total_bytes == 0


class TestLabels:
    def test_a_lone_figure_needs_no_label(self, sessionless):
        hit = ev.find_figure(sessionless, _fig("sdc"), "sub-010_task-rest_run-1_bold")
        assert hit.label_for(hit.paths[0]) == ""

    def test_the_label_omits_the_figures_own_identity(self, sessionless):
        """Labelling the SDC figure ``desc-sdc`` says nothing."""
        hit = ev.find_figure(sessionless, _fig("pepolar"), "sub-010_task-rest_run-1_bold")
        assert "desc-pepolar" not in hit.label_for(hit.paths[0])
        assert "fmapid-B0map25mm" in hit.label_for(hit.paths[0])

    def test_the_label_distinguishes_two_anatomical_acquisitions(self, sessioned):
        hit = ev.find_figure(sessioned, _fig("dseg"), "sub-03_ses-02_task-prf_run-01_bold")
        labels = {hit.label_for(p) for p in hit.paths}
        assert labels == {"acq-MPR", "acq-MPR · desc-preproc"}

    def test_the_label_omits_what_the_selection_already_fixes(self, sessioned):
        """No point repeating the subject and session the reviewer chose."""
        hit = ev.find_figure(sessioned, _fig("coreg"), "sub-03_ses-02_task-prf_run-01_bold")
        assert "sub-03" not in hit.label_for(hit.paths[0])
        assert "ses-02" not in hit.label_for(hit.paths[0])


class TestRunDiscovery:
    def test_runs_are_read_from_the_figures_themselves(self, sessionless):
        """So the viewer works where fMRIPrep ran and MRIQC did not."""
        assert ev.runs_with_figures(sessionless, "sub-010") == [
            "sub-010_task-other_run-1_bold",
            "sub-010_task-rest_run-1_bold",
            "sub-010_task-rest_run-2_bold",
        ]

    def test_session_entities_are_carried_into_the_key(self, sessioned):
        assert ev.runs_with_figures(sessioned, "sub-03") == [
            "sub-03_ses-02_task-prf_run-01_bold",
            "sub-03_ses-03_task-prf_run-01_bold",
        ]

    def test_a_figure_with_no_task_is_not_mistaken_for_a_run(self, sessionless):
        """An anatomical or summary figure is not a run, and must not become one."""
        (sessionless / "sub-010" / "figures" / "sub-010_bold.svg").write_text(ANIMATED_SVG)
        assert all("task-" in key for key in ev.runs_with_figures(sessionless, "sub-010"))

    def test_an_absent_subject_yields_no_runs(self, sessionless):
        assert ev.runs_with_figures(sessionless, "sub-999") == []


class TestCollect:
    def test_anat_modalities_get_only_subject_scoped_figures(self, sessionless):
        hits = ev.collect(sessionless, get_domain("alignment"), "sub-010_T1w", modality="T1w")
        assert all(h.figure.scope == "subject" for h in hits)

    def test_a_domain_with_no_figures_collects_nothing(self, sessionless):
        assert ev.collect(sessionless, get_domain("signal"), "sub-010_task-rest_bold") == []

    def test_an_unknown_pattern_is_simply_absent(self, sessionless):
        made_up = EvidenceFigure(
            key="nope",
            label="Not a real figure",
            pattern="desc-nothing_bold.svg",
            scope="run",
            look_for="x" * 100,
        )
        assert not ev.find_figure(sessionless, made_up, "sub-010_task-rest_run-1_bold").found
