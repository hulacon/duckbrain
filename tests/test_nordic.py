"""NORDIC helpers — sessionless path handling.

Both ``nordic_output_dir`` and ``build_nordic_bids_input`` used to hardcode
``ses-{session}``, so sessionless (single-session) data wrote a malformed
``ses-/func`` path (TODO #5b). These lock in that the ``ses-`` level is omitted
when there is no session and present when there is.
"""

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

def _seed_raw_and_nordic(root, ss):
    """Create a minimal raw BIDS + NORDIC derivative tree under *root* for *ss*.

    *ss* is the ``sub-XX[/ses-YY]`` fragment. Returns the derivatives dir.
    """
    bids = Path(root)
    raw_func = bids / ss / "func"
    raw_fmap = bids / ss / "fmap"
    raw_anat = bids / ss / "anat"
    raw_func.mkdir(parents=True)
    raw_fmap.mkdir(parents=True)
    raw_anat.mkdir(parents=True)
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
    (written,) = write_nordic_sidecars(bids, deriv, "01",
                                       provenance={"Tool": "nordic", "Runtime": ""})
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
        "bids:raw:sub-01/ses-02/func/sub-01_ses-02_task-x_bold.nii.gz"]


def test_no_bolds_writes_nothing(tmp_path):
    bids, deriv = tmp_path / "bids", tmp_path / "derivatives"
    (bids / "sub-01").mkdir(parents=True)
    assert write_nordic_sidecars(bids, deriv, "01", provenance=_PROV) == []
