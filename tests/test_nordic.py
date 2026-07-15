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
    raw_func.mkdir(parents=True)
    raw_fmap.mkdir(parents=True)
    # Raw BOLD (should be skipped — NORDIC version wins) + a sidecar + an event.
    (raw_func / "sub-04_task-x_bold.nii.gz").write_bytes(b"raw")
    (raw_func / "sub-04_task-x_bold.json").write_text("{}")
    (raw_func / "sub-04_task-x_events.tsv").write_text("onset\n")
    (raw_fmap / "sub-04_dir-AP_epi.nii.gz").write_bytes(b"fmap")

    deriv = bids / "derivatives"
    nordic_func = deriv / "nordic" / ss / "func"
    nordic_func.mkdir(parents=True)
    (nordic_func / "sub-04_task-x_bold.nii.gz").write_bytes(b"denoised")
    return deriv


def test_build_bids_input_sessionless(tmp_path):
    ss = "sub-04"
    deriv = _seed_raw_and_nordic(tmp_path, ss)

    out = build_nordic_bids_input(tmp_path, "04", "", deriv / "nordic")

    # No malformed ses- level anywhere.
    assert out == deriv / "nordic" / "bids_input" / "sub-04"
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


def test_build_bids_input_multisession(tmp_path):
    ss = "sub-04/ses-05"
    deriv = _seed_raw_and_nordic(tmp_path, ss)

    out = build_nordic_bids_input(tmp_path, "04", "05", deriv / "nordic")

    assert out == deriv / "nordic" / "bids_input" / "sub-04" / "ses-05"
    assert (out / "func" / "sub-04_task-x_bold.nii.gz").read_bytes() == b"denoised"
    assert (out / "fmap" / "sub-04_dir-AP_epi.nii.gz").exists()
