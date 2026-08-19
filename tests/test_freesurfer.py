"""External FreeSurfer recon helpers — the version gate and the path scheme.

What must hold: ``recon_complete`` refuses everything except a finished recon
from the pinned release (the done-marker alone also matches fMRIPrep's own
FreeSurfer-7 recon at the identical path — Trap 1 of
``docs/pipeline-extras.md`` §9); the staging dir is dot-prefixed and
per-subject; and container-crossing paths are respelled off ``/gpfs``
(Trap 2).
"""

from pathlib import Path

from duckbrain.core.freesurfer import (
    build_stamp,
    container_visible,
    fs_bin_dir,
    fs_version,
    import_subjects_dir,
    recon_complete,
    staging_subjects_dir,
    stamp_version,
    subject_import_dir,
    t1w_inputs,
    t2w_inputs,
    use_external_fs,
)

FS8_STAMP = "freesurfer-linux-rocky8_x86_64-8.2.0-20260314-d932c45"
FS7_STAMP = "freesurfer-linux-centos7_x86_64-7.3.2-20220804-6354275"

# What FS8's recon-all actually writes on each exit path (read from the
# script's own source, and hit live by pilot jobs 46353636/46358868): success
# is a rich record with END_TIME; failure is the single line "1" — and the
# done file exists in BOTH cases.
DONE_SUCCESS = "------------------------------\nSUBJECT sub-x\nSTART_TIME t0\nEND_TIME t1\n"
DONE_FAILURE = "1\n"

ARTIFACTS = ("surf/lh.white", "surf/rh.white", "surf/lh.pial", "surf/rh.pial", "mri/aparc+aseg.mgz")


def _cfg(**fs):
    return {"freesurfer": fs}


def _recon(
    subject_dir: Path,
    stamp: str = FS8_STAMP,
    done: str | None = DONE_SUCCESS,
    error: bool = False,
    artifacts: bool = True,
) -> Path:
    scripts = subject_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "build-stamp.txt").write_text(stamp + "\n")
    if done is not None:
        (scripts / "recon-all.done").write_text(done)
    if error:
        (scripts / "recon-all.error").write_text("------------------------------\n")
    if artifacts:
        for rel in ARTIFACTS:
            p = subject_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
    return subject_dir


# ---- config readers ----------------------------------------------------------


def test_toggle_and_version_default_off_and_empty():
    assert use_external_fs({}) is False
    assert fs_version({}) == ""
    assert use_external_fs(_cfg(use_external=True)) is True
    assert fs_version(_cfg(version="8.2.0")) == "8.2.0"


def test_fs_bin_dir_is_pinned_not_path():
    cfg = _cfg(version="8.2.0", install_root="/packages/freesurfer")
    assert fs_bin_dir(cfg) == Path("/packages/freesurfer/8.2.0/bin")


# ---- path scheme ---------------------------------------------------------------


def test_import_dir_is_fmriprep_default_subjects_dir():
    # fMRIPrep's fs_subjects_dir default under --output-layout bids: the recon
    # is found with no flag at all. If this moves, the no-flag design is void.
    assert import_subjects_dir("/d") == Path("/d/fmriprep/sourcedata/freesurfer")
    assert subject_import_dir("/d", "04") == Path("/d/fmriprep/sourcedata/freesurfer/sub-04")


def test_staging_dir_is_dot_prefixed_and_per_subject():
    a, b = (staging_subjects_dir("/d", s) for s in ("04", "05"))
    assert a != b  # shared staging would re-create the fsaverage copy race
    assert a.name == "sub-04" and a.parent.name.startswith(".")
    # Invisible to the surveyor: Path.glob's * does not match dot-entries, so an
    # in-flight recon can never flip the stage cell by existing.
    assert not str(a.relative_to(import_subjects_dir("/d"))).startswith("sub-")


# ---- the version gate ----------------------------------------------------------


def test_stamp_version_parses_both_release_lines():
    assert stamp_version(FS8_STAMP) == "8.2.0"
    assert stamp_version(FS7_STAMP) == "7.3.2"
    assert stamp_version("") == ""
    assert stamp_version("not-a-stamp") == ""


def test_recon_complete_requires_done_and_matching_stamp(tmp_path):
    cfg = _cfg(version="8.2.0")
    assert recon_complete(cfg, _recon(tmp_path / "a")) is True
    # The FS7 recon fMRIPrep's own bundled FreeSurfer writes at the same path:
    # done-marker present, wrong stamp. Grading it complete is Trap 1.
    assert recon_complete(cfg, _recon(tmp_path / "b", stamp=FS7_STAMP)) is False
    # Crashed FS8 run: right stamp, no done-marker at all.
    assert recon_complete(cfg, _recon(tmp_path / "c", done=None)) is False
    # Empty or absent dir.
    assert recon_complete(cfg, tmp_path / "nothing") is False


def test_recon_complete_rejects_every_failed_run_shape(tmp_path):
    """FS8 writes recon-all.done on FAILURE too — the error path's is the bare
    line "1", beside a recon-all.error. Pilot job 46358868 imported an
    OOM-killed stub past the existence-only check; none of these shapes may
    ever grade complete again."""
    cfg = _cfg(version="8.2.0")
    # The exact stub the OOM left: failure-format done + error file + no
    # surfaces (a real failed run has all three, but each alone must refuse).
    assert (
        recon_complete(cfg, _recon(tmp_path / "a", done=DONE_FAILURE, error=True, artifacts=False))
        is False
    )
    assert recon_complete(cfg, _recon(tmp_path / "b", done=DONE_FAILURE)) is False
    assert recon_complete(cfg, _recon(tmp_path / "c", error=True)) is False
    assert recon_complete(cfg, _recon(tmp_path / "d", artifacts=False)) is False
    # Unrecognized done format fails closed, not open.
    assert recon_complete(cfg, _recon(tmp_path / "e", done="something new\n")) is False


def test_build_stamp_reads_first_line_or_empty(tmp_path):
    assert build_stamp(_recon(tmp_path / "a")) == FS8_STAMP
    assert build_stamp(tmp_path / "nothing") == ""


# ---- input discovery -------------------------------------------------------------


def test_t1w_inputs_are_subject_wide_across_sessions(tmp_path):
    # Subject-level on purpose: the recon matches fMRIPrep 25's default
    # subject-level anatomical reference, which merges every session's T1w.
    for ses in ("01", "02"):
        anat = tmp_path / "sub-04" / f"ses-{ses}" / "anat"
        anat.mkdir(parents=True)
        (anat / f"sub-04_ses-{ses}_T1w.nii.gz").write_bytes(b"x")
    (tmp_path / "sub-04" / "ses-02" / "anat" / "sub-04_ses-02_T2w.nii.gz").write_bytes(b"x")
    # Another subject's anat must never leak in.
    other = tmp_path / "sub-05" / "ses-01" / "anat"
    other.mkdir(parents=True)
    (other / "sub-05_ses-01_T1w.nii.gz").write_bytes(b"x")

    t1s = t1w_inputs(tmp_path, "04")
    assert [p.name for p in t1s] == ["sub-04_ses-01_T1w.nii.gz", "sub-04_ses-02_T1w.nii.gz"]
    assert [p.name for p in t2w_inputs(tmp_path, "04")] == ["sub-04_ses-02_T2w.nii.gz"]


# ---- container path respelling --------------------------------------------------


def test_container_visible_respells_gpfs_only():
    # /projects is a symlink to /gpfs/projects on the host and the only one of
    # the two that exists inside a container (§9 Trap 2).
    assert container_visible("/gpfs/projects/hulacon/x") == "/projects/hulacon/x"
    assert container_visible("/projects/hulacon/x") == "/projects/hulacon/x"
    assert container_visible("/home/u/x") == "/home/u/x"
    assert container_visible(Path("/gpfs/projects/a")) == "/projects/a"
