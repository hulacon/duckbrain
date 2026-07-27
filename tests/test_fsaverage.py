"""The fMRIPrep ``fsaverage`` pre-flight — TODO #21.

What these pin is that duckbrain refuses to submit a batch it cannot protect,
and that "complete" is decided against the container's manifest rather than
against the FreeSurfer-7 sentinel fMRIPrep itself checks. The tree this bug was
found on *has* that sentinel and is still 53 files short, so a sentinel check
would have called it healthy — which is exactly how it stayed broken.

The container calls are stubbed. What they do is a `singularity exec` away and
cannot run in CI; what decides whether to make them is here.
"""

from pathlib import Path

import pytest

import duckbrain.core.fsaverage as FS
from duckbrain.core.fsaverage import (
    FsaverageError,
    SpaceState,
    ensure,
    plan_repairs,
    read_installed,
    required_spaces,
    subjects_dir,
)

#: Stand-in for the container's fsaverage: what a complete install looks like.
MANIFEST = {
    "fsaverage": {"label/lh.BA1_exvivo.label", "label/rh.BA1_exvivo.label", "mri/orig.mgz"},
    "fsaverage6": {"surf/lh.white", "surf/rh.white"},
}


@pytest.fixture(autouse=True)
def _clean_cache():
    FS.reset_cache()
    yield
    FS.reset_cache()


def _install(root: Path, space: str, files) -> None:
    for rel in files:
        path = root / space / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")


class TestRequiredSpaces:
    def test_fsaverage_is_required_even_when_no_surface_space_was_asked_for(self):
        """niworkflows appends it unconditionally, which is why a project that
        never wanted a surface space is still exposed to the race."""
        assert required_spaces(["MNI152NLin2009cAsym:res-2", "func"]) == ["fsaverage"]

    def test_surface_spaces_are_collected_and_deduped(self):
        got = required_spaces(["fsaverage6", "MNI152NLin2009cAsym:res-2", "fsaverage6", "func"])
        assert got == ["fsaverage", "fsaverage6"]

    def test_resolution_modifiers_are_stripped(self):
        assert "fsaverage5" in required_spaces(["fsaverage5:den-10k"])

    def test_a_space_string_is_accepted(self):
        assert required_spaces("fsaverage6 func") == ["fsaverage", "fsaverage6"]

    def test_no_reconall_means_nothing_is_needed(self):
        """No recon-all, no copy, no race — and so nothing to install."""
        assert required_spaces(["fsaverage6"], extra_flags="--fs-no-reconall") == []


class TestPlanRepairs:
    def test_a_complete_tree_needs_nothing(self, tmp_path):
        _install(tmp_path, "fsaverage", MANIFEST["fsaverage"])
        states = plan_repairs(MANIFEST, read_installed(tmp_path, ["fsaverage"]), ["fsaverage"])
        assert [s.state for s in states] == ["complete"]
        assert not states[0].needs_repair

    def test_an_absent_tree_is_missing_not_incomplete(self, tmp_path):
        states = plan_repairs(MANIFEST, read_installed(tmp_path, ["fsaverage"]), ["fsaverage"])
        assert states[0].state == "missing"

    def test_the_divatten_beta_v2_shape_is_caught(self, tmp_path):
        """The real failure: everything present except the lh labels, and the
        FreeSurfer-7 sentinel among what survived. fMRIPrep calls this healthy."""
        _install(tmp_path, "fsaverage", MANIFEST["fsaverage"] - {"label/lh.BA1_exvivo.label"})
        states = plan_repairs(MANIFEST, read_installed(tmp_path, ["fsaverage"]), ["fsaverage"])
        assert states[0].state == "incomplete"
        assert states[0].missing == ("label/lh.BA1_exvivo.label",)
        assert "lh.BA1_exvivo" in states[0].describe()

    def test_extra_files_on_disk_are_not_a_defect(self, tmp_path):
        _install(tmp_path, "fsaverage", MANIFEST["fsaverage"] | {"label/lh.something.new"})
        states = plan_repairs(MANIFEST, read_installed(tmp_path, ["fsaverage"]), ["fsaverage"])
        assert states[0].state == "complete"

    def test_a_space_the_container_lacks_is_an_error_not_a_repair(self):
        with pytest.raises(FsaverageError, match="carries no 'fsaverage7'"):
            plan_repairs(MANIFEST, {}, ["fsaverage7"])


class TestEnsure:
    """``ensure`` is the whole contract: verify, repair if needed, re-verify."""

    def _stub(self, monkeypatch, tmp_path, installs):
        """Stub the container calls; ``installs`` records what got installed."""
        monkeypatch.setattr(FS, "container_manifest", lambda c, spaces: MANIFEST)

        def fake_install(container, root, spaces):
            installs.append(list(spaces))
            for space in spaces:
                _install(root, space, MANIFEST[space])
            return {s: len(MANIFEST[s]) for s in spaces}

        monkeypatch.setattr(FS, "install", fake_install)

    def test_installs_what_is_missing(self, monkeypatch, tmp_path):
        installs = []
        self._stub(monkeypatch, tmp_path, installs)
        report = ensure("cont.simg", tmp_path, ["fsaverage6", "func"])
        assert installs == [["fsaverage", "fsaverage6"]]
        assert report.did_work
        assert "Installed FreeSurfer templates" in report.summary()
        assert (subjects_dir(tmp_path) / "fsaverage" / "mri/orig.mgz").is_file()

    def test_repairs_an_incomplete_tree(self, monkeypatch, tmp_path):
        installs = []
        self._stub(monkeypatch, tmp_path, installs)
        root = subjects_dir(tmp_path)
        _install(root, "fsaverage", MANIFEST["fsaverage"] - {"label/lh.BA1_exvivo.label"})
        ensure("cont.simg", tmp_path, ["func"])
        assert installs == [["fsaverage"]]
        assert (root / "fsaverage" / "label/lh.BA1_exvivo.label").is_file()

    def test_a_complete_tree_is_left_alone(self, monkeypatch, tmp_path):
        """fMRIPrep only skips the rmtree when the tree is already there, so the
        no-op path is the one that actually protects a run."""
        installs = []
        self._stub(monkeypatch, tmp_path, installs)
        _install(subjects_dir(tmp_path), "fsaverage", MANIFEST["fsaverage"])
        report = ensure("cont.simg", tmp_path, ["func"])
        assert installs == []
        assert not report.did_work
        assert "already complete" in report.summary()

    def test_a_bulk_submission_launches_the_container_once(self, monkeypatch, tmp_path):
        """37 subjects must not mean 37 container launches. Asserted at the
        `singularity exec` boundary, not at ``container_manifest``, because the
        launch is the cost — everything above it is a directory walk."""
        import json as _json

        launches = []
        image = tmp_path / "cont.simg"
        image.write_text("not really an image")

        class _Proc:
            returncode = 0
            stderr = ""
            stdout = _json.dumps({k: sorted(v) for k, v in MANIFEST.items()})

        monkeypatch.setattr(
            FS,
            "_run_in_container",
            lambda c, script, args, binds: launches.append(1) or _Proc(),
        )
        _install(subjects_dir(tmp_path), "fsaverage", MANIFEST["fsaverage"])
        for _ in range(37):
            assert not ensure(image, tmp_path, ["func"]).did_work
        assert len(launches) == 1

    def test_no_reconall_skips_everything(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            FS, "container_manifest", lambda c, s: pytest.fail("should not inspect the container")
        )
        assert ensure("cont.simg", tmp_path, ["fsaverage6"], extra_flags="--fs-no-reconall") is None

    def test_an_install_that_did_not_take_raises(self, monkeypatch, tmp_path):
        """The re-verify exists because this is the one path that can still leave
        a project poisoned. A silent partial install is the original bug."""
        monkeypatch.setattr(FS, "container_manifest", lambda c, spaces: MANIFEST)
        monkeypatch.setattr(FS, "install", lambda c, root, spaces: {})  # copies nothing
        with pytest.raises(FsaverageError, match="still incomplete"):
            ensure("cont.simg", tmp_path, ["func"])

    def test_a_failed_verification_is_not_cached_as_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(FS, "container_manifest", lambda c, spaces: MANIFEST)
        monkeypatch.setattr(FS, "install", lambda c, root, spaces: {})
        with pytest.raises(FsaverageError):
            ensure("cont.simg", tmp_path, ["func"])
        with pytest.raises(FsaverageError):
            ensure("cont.simg", tmp_path, ["func"])


class TestUnreachableContainer:
    def test_an_unreadable_container_refuses_rather_than_shrugs(self, tmp_path):
        """Submitting blind is the failure this module exists to prevent, so a
        pre-flight that cannot run has to stop the submission."""
        with pytest.raises(FsaverageError, match="not readable"):
            ensure(tmp_path / "no-such.simg", tmp_path, ["func"])


class TestPipelineWiring:
    def test_advance_one_turns_a_preflight_failure_into_a_pipeline_error(
        self, monkeypatch, tmp_path
    ):
        """The GUI catches PipelineError; an FsaverageError would escape as a
        traceback and the submission would look like a crash rather than a stop."""
        import duckbrain.core.pipeline as P

        monkeypatch.setattr(
            FS, "ensure", lambda *a, **k: (_ for _ in ()).throw(FsaverageError("boom"))
        )
        with pytest.raises(P.PipelineError, match="boom"):
            P._fsaverage_preflight(
                {
                    "paths": {"derivatives_dir": str(tmp_path), "containers_dir": str(tmp_path)},
                    "containers": {"fmriprep_version": "24.1.1"},
                },
                "fmriprep",
                {},
            )

    def test_other_stages_are_untouched(self, monkeypatch):
        import duckbrain.core.pipeline as P

        monkeypatch.setattr(
            FS, "ensure", lambda *a, **k: pytest.fail("only fMRIPrep needs fsaverage")
        )
        for stage in ("converted", "nordic", "mriqc"):
            P._fsaverage_preflight({}, stage, {})


def test_cleanup_staging_removes_a_killed_installs_leftovers(tmp_path):
    root = subjects_dir(tmp_path)
    staging = root / f"{FS._STAGING_PREFIX}fsaverage"
    staging.mkdir(parents=True)
    (staging / "half.mgz").write_text("x")
    assert FS.cleanup_staging(tmp_path) == [staging]
    assert not staging.exists()


def test_space_state_describes_each_state():
    assert "complete" in SpaceState("fsaverage", "complete").describe()
    assert "not installed" in SpaceState("fsaverage", "missing").describe()
    assert "2 file(s) missing" in SpaceState("fsaverage", "incomplete", ("a", "b")).describe()
