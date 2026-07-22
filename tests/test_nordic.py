"""NORDIC helpers — sessionless path handling.

Both ``nordic_output_dir`` and ``build_nordic_bids_input`` used to hardcode
``ses-{session}``, so sessionless (single-session) data wrote a malformed
``ses-/func`` path (TODO #5b). These lock in that the ``ses-`` level is omitted
when there is no session and present when there is.
"""

import os
import shutil
from pathlib import Path

from duckbrain.core.nordic import build_nordic_bids_input, nordic_output_dir


# ---- nordic_output_dir ------------------------------------------------------


def test_nordic_output_dir_sessionless(tmp_path):
    out = nordic_output_dir(tmp_path / "derivatives", "04")
    assert out == tmp_path / "derivatives" / "nordic" / "sub-04" / "func"
    # No empty ses- level.
    assert "ses-" not in str(out)


def test_nordic_output_dir_multisession(tmp_path):
    out = nordic_output_dir(tmp_path / "derivatives", "03", "05")
    assert out == tmp_path / "derivatives" / "nordic" / "sub-03" / "ses-05" / "func"


# ---- build_nordic_bids_input ------------------------------------------------


def _seed_raw_and_nordic(root, ss, anat_ss=None):
    """Create a minimal raw BIDS + NORDIC derivative tree under *root* for *ss*.

    *ss* is the ``sub-XX[/ses-YY]`` fragment. *anat_ss* puts the anatomy under a
    different fragment — the shared-anat layout, where the T1w is acquired once
    and every other session has none of its own. Defaults to *ss*, which was the
    only shape these tests covered and the reason the bug went unnoticed.

    Returns the derivatives dir.
    """
    bids = Path(root)
    raw_func = bids / ss / "func"
    raw_fmap = bids / ss / "fmap"
    raw_anat = bids / (anat_ss if anat_ss is not None else ss) / "anat"
    raw_func.mkdir(parents=True)
    raw_fmap.mkdir(parents=True)
    raw_anat.mkdir(parents=True, exist_ok=True)
    # Raw BOLD (should be skipped — NORDIC version wins) + a sidecar + an event.
    (raw_func / "sub-04_task-x_bold.nii.gz").write_bytes(b"raw")
    (raw_func / "sub-04_task-x_bold.json").write_text("{}")
    (raw_func / "sub-04_task-x_events.tsv").write_text("onset\n")
    (raw_fmap / "sub-04_dir-AP_epi.nii.gz").write_bytes(b"fmap")
    (raw_anat / "sub-04_T1w.nii.gz").write_bytes(b"anat")
    (raw_anat / "sub-04_T1w.json").write_text("{}")
    # Dataset root files (only some present — copying must skip the absent README).
    (bids / "dataset_description.json").write_text('{"Name":"x","BIDSVersion":"1.8.0"}')
    (bids / "participants.tsv").write_text("participant_id\nsub-04\n")

    deriv = bids / "derivatives"
    nordic_func = deriv / "nordic" / ss / "func"
    nordic_func.mkdir(parents=True)
    (nordic_func / "sub-04_task-x_bold.nii.gz").write_bytes(b"denoised")
    return deriv


def test_build_bids_input_sessionless(tmp_path):
    ss = "sub-04"
    deriv = _seed_raw_and_nordic(tmp_path, ss)

    out = build_nordic_bids_input(tmp_path, "04", "", deriv / "nordic")

    # Tree lives under bids_format/, no malformed ses- level anywhere.
    tree_root = deriv / "nordic" / "bids_format"
    assert out == tree_root / "sub-04"
    assert "ses-" not in str(out)

    func = out / "func"
    # NORDIC bold is hardlinked (same inode as the denoised source).
    denoised = deriv / "nordic" / ss / "func" / "sub-04_task-x_bold.nii.gz"
    assert (func / "sub-04_task-x_bold.nii.gz").read_bytes() == b"denoised"
    assert (func / "sub-04_task-x_bold.nii.gz").stat().st_ino == denoised.stat().st_ino
    # Sidecars/events copied from raw BIDS.
    assert (func / "sub-04_task-x_bold.json").exists()
    assert (func / "sub-04_task-x_events.tsv").exists()
    # Fieldmap copied.
    assert (out / "fmap" / "sub-04_dir-AP_epi.nii.gz").exists()
    # Anat included: nifti hardlinked, sidecar copied.
    raw_t1 = tmp_path / ss / "anat" / "sub-04_T1w.nii.gz"
    assert (out / "anat" / "sub-04_T1w.nii.gz").stat().st_ino == raw_t1.stat().st_ino
    assert (out / "anat" / "sub-04_T1w.json").exists()
    # Dataset root files copied once, at the tree root (present ones only).
    assert (tree_root / "dataset_description.json").exists()
    assert (tree_root / "participants.tsv").exists()
    assert not (tree_root / "README").exists()


def test_build_bids_input_multisession(tmp_path):
    ss = "sub-04/ses-05"
    deriv = _seed_raw_and_nordic(tmp_path, ss)

    out = build_nordic_bids_input(tmp_path, "04", "05", deriv / "nordic")

    assert out == deriv / "nordic" / "bids_format" / "sub-04" / "ses-05"
    assert (out / "func" / "sub-04_task-x_bold.nii.gz").read_bytes() == b"denoised"
    assert (out / "fmap" / "sub-04_dir-AP_epi.nii.gz").exists()
    assert (out / "anat" / "sub-04_T1w.nii.gz").exists()
    assert (deriv / "nordic" / "bids_format" / "dataset_description.json").exists()


# ---- derivative sidecars (per-file provenance) ------------------------------
#
# NORDIC's MATLAB job emits bare NIfTIs and no sidecar, so the derivative cannot
# describe itself. dataset_description.json is dataset-level and the submission
# log doesn't travel with the data — only sidecars keep a copied or archived
# output self-describing.

import json

from duckbrain.core.nordic import write_nordic_sidecars

_PROV = {
    "Version": "v0.1.0-1-gabc1234",
    "Tool": "nordic",
    "ToolVersion": "v1.0.2-24-g0861968",
    "Runtime": "matlab/R2024a",
    "CodeSource": "SteenMoeller/NORDIC_Raw@0861968",
    "InputVariant": "",
}


def _raw_bold(bids, sub, name, sidecar=None):
    func = bids / f"sub-{sub}" / "func"
    func.mkdir(parents=True, exist_ok=True)
    (func / f"{name}.nii.gz").write_text("nii")
    if sidecar is not None:
        (func / f"{name}.json").write_text(json.dumps(sidecar))
    return func / f"{name}.nii.gz"


def test_sidecar_carries_sources_and_namespaced_provenance(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    _raw_bold(bids, "01", "sub-01_task-x_bold", sidecar={"RepetitionTime": 1.0})
    (written,) = write_nordic_sidecars(bids, deriv, "01", provenance=_PROV)

    side = json.loads(written.read_text())
    # Self-contained: derivatives do not inherit raw metadata, and denoising does
    # not change the acquisition.
    assert side["RepetitionTime"] == 1.0
    # BIDS-spec'd per-file provenance, resolvable via DatasetLinks.raw.
    assert side["Sources"] == ["bids:raw:sub-01/func/sub-01_task-x_bold.nii.gz"]
    assert side["Duckbrain"]["ToolVersion"] == "v1.0.2-24-g0861968"
    assert side["Duckbrain"]["Runtime"] == "matlab/R2024a"


def test_sidecar_does_not_use_bep028_reserved_keys(tmp_path):
    """BEP028 claims sidecar GeneratedBy/SidecarGeneratedBy for URI *references*
    into a prov record — the opposite of what the same key means in
    dataset_description.json. Ours must not squat on them."""
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    _raw_bold(bids, "01", "sub-01_task-x_bold", sidecar={})
    (written,) = write_nordic_sidecars(bids, deriv, "01", provenance=_PROV)
    side = json.loads(written.read_text())
    assert "GeneratedBy" not in side
    assert "SidecarGeneratedBy" not in side


def test_empty_provenance_fields_are_omitted(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    _raw_bold(bids, "01", "sub-01_task-x_bold", sidecar={})
    (written,) = write_nordic_sidecars(
        bids, deriv, "01", provenance={"Tool": "nordic", "Runtime": ""}
    )
    assert json.loads(written.read_text())["Duckbrain"] == {"Tool": "nordic"}


def test_existing_output_is_not_restamped(tmp_path):
    """The sbatch skips a BOLD whose output exists. Restamping it would claim the
    current toolbox produced a file an older one actually made."""
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    _raw_bold(bids, "01", "sub-01_task-x_run-1_bold", sidecar={})
    _raw_bold(bids, "01", "sub-01_task-x_run-2_bold", sidecar={})
    out = nordic_output_dir(deriv, "01")
    out.mkdir(parents=True)
    (out / "sub-01_task-x_run-1_bold.nii.gz").write_text("already denoised")

    written = write_nordic_sidecars(bids, deriv, "01", provenance=_PROV)
    assert [p.name for p in written] == ["sub-01_task-x_run-2_bold.json"]
    assert not (out / "sub-01_task-x_run-1_bold.json").exists()


def test_missing_raw_sidecar_still_yields_provenance(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    _raw_bold(bids, "01", "sub-01_task-x_bold")  # no raw .json
    (written,) = write_nordic_sidecars(bids, deriv, "01", provenance=_PROV)
    side = json.loads(written.read_text())
    assert side["Duckbrain"]["Tool"] == "nordic"
    assert side["Sources"]


def test_unreadable_raw_sidecar_degrades_to_provenance_only(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    bold = _raw_bold(bids, "01", "sub-01_task-x_bold")
    (bold.parent / "sub-01_task-x_bold.json").write_text("{ not json")
    (written,) = write_nordic_sidecars(bids, deriv, "01", provenance=_PROV)
    assert json.loads(written.read_text())["Duckbrain"]["Tool"] == "nordic"


def test_sessionless_and_multisession_paths(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    func = bids / "sub-01" / "ses-02" / "func"
    func.mkdir(parents=True)
    (func / "sub-01_ses-02_task-x_bold.nii.gz").write_text("nii")
    (written,) = write_nordic_sidecars(bids, deriv, "01", "02", provenance=_PROV)
    assert written.parent == nordic_output_dir(deriv, "01", "02")
    assert json.loads(written.read_text())["Sources"] == [
        "bids:raw:sub-01/ses-02/func/sub-01_ses-02_task-x_bold.nii.gz"
    ]


def test_no_bolds_writes_nothing(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    (bids / "sub-01").mkdir(parents=True)
    assert write_nordic_sidecars(bids, deriv, "01", provenance=_PROV) == []


# ---- DB-004: shared anat, staleness, and concurrent builds -------------------


def _build(root, subject, session, deriv):
    return build_nordic_bids_input(root, subject, session, deriv / "nordic")


def test_bids_input_takes_anat_from_another_session(tmp_path):
    """The headline case: anat acquired once, in a session with no BOLD.

    `fmriprep._SESSION_FILTER_SUFFIXES` leaves anat unfiltered precisely because
    of this layout, so with use_nordic the filter said "any session's anat" and
    pointed at a tree assembled with none — a hard fMRIPrep failure with every
    piece working as written.
    """
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04/ses-02", anat_ss="sub-04/ses-01")

    out = _build(tmp_path, "04", "02", deriv)

    tree = deriv / "nordic" / "bids_format"
    staged = tree / "sub-04" / "ses-01" / "anat" / "sub-04_T1w.nii.gz"
    assert staged.exists(), "anat from another session must reach the staged tree"
    raw = tmp_path / "sub-04" / "ses-01" / "anat" / "sub-04_T1w.nii.gz"
    assert staged.stat().st_ino == raw.stat().st_ino  # hardlinked, not copied
    assert (out / "func" / "sub-04_task-x_bold.nii.gz").exists()


def test_bids_input_takes_subject_level_anat(tmp_path):
    """`sub-XX/anat` with no session level is rare but legal, and was also lost."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04/ses-02", anat_ss="sub-04")

    _build(tmp_path, "04", "02", deriv)

    tree = deriv / "nordic" / "bids_format"
    assert (tree / "sub-04" / "anat" / "sub-04_T1w.nii.gz").exists()


def test_bids_input_includes_every_sessions_anat(tmp_path):
    """fMRIPrep sees all of them and picks; that is what a non-NORDIC run does."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04/ses-01")
    other = tmp_path / "sub-04" / "ses-02" / "anat"
    other.mkdir(parents=True)
    (other / "sub-04_ses-02_T1w.nii.gz").write_bytes(b"anat2")

    _build(tmp_path, "04", "01", deriv)

    tree = deriv / "nordic" / "bids_format" / "sub-04"
    assert (tree / "ses-01" / "anat" / "sub-04_T1w.nii.gz").exists()
    assert (tree / "ses-02" / "anat" / "sub-04_ses-02_T1w.nii.gz").exists()


def test_bids_input_without_any_anat_makes_no_anat_dir(tmp_path):
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    shutil.rmtree(tmp_path / "sub-04" / "anat")

    out = _build(tmp_path, "04", "", deriv)

    assert not (out / "anat").exists()


def test_bids_input_prunes_a_file_whose_source_was_removed(tmp_path):
    """A removed run must leave the tree fMRIPrep reads, or it processes a run
    the dataset no longer has."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    out = _build(tmp_path, "04", "", deriv)
    assert (out / "func" / "sub-04_task-x_events.tsv").exists()

    (tmp_path / "sub-04" / "func" / "sub-04_task-x_events.tsv").unlink()
    _build(tmp_path, "04", "", deriv)

    assert not (out / "func" / "sub-04_task-x_events.tsv").exists()
    assert (out / "func" / "sub-04_task-x_bold.json").exists()  # the rest stays


def test_prune_leaves_another_units_files_alone(tmp_path):
    """Two units share one bids_format root; neither may prune the other."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04/ses-01")
    _seed_raw_and_nordic(tmp_path, "sub-04/ses-02", anat_ss="sub-04/ses-01")

    out1 = _build(tmp_path, "04", "01", deriv)
    out2 = _build(tmp_path, "04", "02", deriv)
    _build(tmp_path, "04", "01", deriv)  # rebuild the first

    assert (out2 / "func" / "sub-04_task-x_bold.nii.gz").exists()
    assert (out1 / "func" / "sub-04_task-x_bold.nii.gz").exists()


def test_prune_never_touches_dataset_root_files(tmp_path):
    """Shared and additive — pruning there is one unit deleting the dataset."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    _build(tmp_path, "04", "", deriv)
    tree = deriv / "nordic" / "bids_format"
    (tree / "README").write_text("hand-added")

    _build(tmp_path, "04", "", deriv)

    assert (tree / "dataset_description.json").exists()
    assert (tree / "README").exists()


def test_bids_input_refreshes_a_changed_sidecar(tmp_path):
    """The Conversion page edits fieldmap intent into raw sidecars. Treating
    presence as equivalence served the stale B0FieldSource to fMRIPrep forever."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    out = _build(tmp_path, "04", "", deriv)
    assert (out / "func" / "sub-04_task-x_bold.json").read_text() == "{}"

    raw_json = tmp_path / "sub-04" / "func" / "sub-04_task-x_bold.json"
    raw_json.write_text('{"B0FieldSource": "B0map_2.5mm"}')
    os.utime(raw_json, (10**9, 10**9))  # unambiguously newer than the staged copy

    _build(tmp_path, "04", "", deriv)

    assert "B0FieldSource" in (out / "func" / "sub-04_task-x_bold.json").read_text()


def test_bids_input_relinks_a_regenerated_nordic_bold(tmp_path):
    """A re-denoised run is a new inode; the stale hardlink has to be replaced."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    out = _build(tmp_path, "04", "", deriv)

    src = deriv / "nordic" / "sub-04" / "func" / "sub-04_task-x_bold.nii.gz"
    src.unlink()
    src.write_bytes(b"denoised-v2")

    _build(tmp_path, "04", "", deriv)

    staged = out / "func" / "sub-04_task-x_bold.nii.gz"
    assert staged.read_bytes() == b"denoised-v2"
    assert staged.stat().st_ino == src.stat().st_ino


def test_bids_input_survives_a_preexisting_destination(tmp_path):
    """os.link on an existing dest raised FileExistsError and killed the job."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    tree = deriv / "nordic" / "bids_format"
    dest = tree / "sub-04" / "anat" / "sub-04_T1w.nii.gz"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale")

    out = _build(tmp_path, "04", "", deriv)

    raw = tmp_path / "sub-04" / "anat" / "sub-04_T1w.nii.gz"
    assert (out / "anat" / "sub-04_T1w.nii.gz").stat().st_ino == raw.stat().st_ino


def test_bids_input_survives_a_racing_link(tmp_path, monkeypatch):
    """nordic_bids_input.sbatch.j2 runs one job per unit into one shared root, so
    two jobs genuinely race for the same anat file."""
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    real_link = os.link
    calls = {"n": 0}

    def flaky_link(src, dst, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileExistsError("another job got there first")
        return real_link(src, dst, **kw)

    monkeypatch.setattr(os, "link", flaky_link)
    out = _build(tmp_path, "04", "", deriv)

    assert (out / "func" / "sub-04_task-x_bold.nii.gz").exists()


def test_bids_input_falls_back_to_copy_when_hardlinks_are_unsupported(tmp_path):
    """EXDEV when derivatives sit on another filesystem; EPERM on some GPFS/NFS.
    Costs disk, not correctness — it used to be an uncaught crash."""
    import errno
    from unittest.mock import patch

    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    with patch.object(os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
        out = _build(tmp_path, "04", "", deriv)

    staged = out / "func" / "sub-04_task-x_bold.nii.gz"
    src = deriv / "nordic" / "sub-04" / "func" / "sub-04_task-x_bold.nii.gz"
    assert staged.read_bytes() == b"denoised"
    assert staged.stat().st_ino != src.stat().st_ino


def test_concurrent_unit_builds_share_one_root(tmp_path):
    """Four sessions of one subject, built at once into the same bids_format."""
    from concurrent.futures import ThreadPoolExecutor

    sessions = ["01", "02", "03", "04"]
    deriv = None
    for i, ses in enumerate(sessions):
        d = _seed_raw_and_nordic(
            tmp_path, f"sub-04/ses-{ses}", anat_ss="sub-04/ses-01" if i else None
        )
        deriv = deriv or d

    with ThreadPoolExecutor(4) as pool:
        outs = list(pool.map(lambda s: _build(tmp_path, "04", s, deriv), sessions))

    for out in outs:
        assert (out / "func" / "sub-04_task-x_bold.nii.gz").exists()
    tree = deriv / "nordic" / "bids_format"
    assert (tree / "sub-04" / "ses-01" / "anat" / "sub-04_T1w.nii.gz").exists()


def test_bids_input_leaves_no_temp_files(tmp_path):
    deriv = _seed_raw_and_nordic(tmp_path, "sub-04")
    _build(tmp_path, "04", "", deriv)

    tree = deriv / "nordic" / "bids_format"
    assert not [p for p in tree.rglob(".duckbrain-tmp-*")]
