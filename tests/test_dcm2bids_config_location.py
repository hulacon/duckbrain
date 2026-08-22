"""Where a session's reviewed ``dcm2bids_config.json`` is read from and written to.

The config's home has to be *writable*; the DICOMs it describes need only be
readable. dcm2bids never writes it — the sbatch template mounts its directory
``:ro`` and passes the file to ``-c`` — so duckbrain is the only writer, and it
was writing beside DICOMs that a shared tree may not let it touch.
"""

import json
import os

import pytest

from duckbrain.core.conversion import (
    dcm2bids_config_dir,
    dcm2bids_config_write_path,
    resolve_dcm2bids_config_path,
    save_dcm2bids_config,
)


def _paths(tmp_path, override=None):
    paths = {"sourcedata_dir": str(tmp_path / "sourcedata")}
    if override is not None:
        paths["dcm2bids_config_dir"] = str(override)
    return paths


def _write(root, subject, session, payload=None):
    p = root / f"sub-{subject}" / f"ses-{session}" / "dcm2bids_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload or {"descriptions": []}))
    return p


# ---- default is unchanged --------------------------------------------------


def test_unset_override_means_sourcedata(tmp_path):
    """An unset key must change nothing for every existing project."""
    paths = _paths(tmp_path)
    assert dcm2bids_config_dir(paths) == tmp_path / "sourcedata"
    assert dcm2bids_config_write_path(paths, "06", "01") == (
        tmp_path / "sourcedata" / "sub-06" / "ses-01" / "dcm2bids_config.json"
    )


def test_empty_override_means_sourcedata(tmp_path):
    """`dcm2bids_config_dir = ""` is how base.toml ships it, not a real setting."""
    assert dcm2bids_config_dir(_paths(tmp_path, "")) == tmp_path / "sourcedata"


# ---- the override ----------------------------------------------------------


def test_override_wins_for_reads_and_writes(tmp_path):
    cfgdir = tmp_path / "configs"
    paths = _paths(tmp_path, cfgdir)
    expected = cfgdir / "sub-06" / "ses-01" / "dcm2bids_config.json"
    assert dcm2bids_config_write_path(paths, "06", "01") == expected
    _write(cfgdir, "06", "01")
    assert resolve_dcm2bids_config_path(paths, "06", "01") == expected


def test_reads_fall_back_to_sourcedata(tmp_path):
    """Setting the override must not hide reviews already saved beside DICOMs.

    Without this, pointing a project at a new config dir silently re-opens every
    skip decision it had reviewed — the exact loss the override exists to avoid.
    """
    cfgdir = tmp_path / "configs"
    paths = _paths(tmp_path, cfgdir)
    legacy = _write(tmp_path / "sourcedata", "06", "01")
    assert resolve_dcm2bids_config_path(paths, "06", "01") == legacy


def test_override_beats_legacy_when_both_exist(tmp_path):
    """A migrated review is the newer one, so it must win."""
    cfgdir = tmp_path / "configs"
    paths = _paths(tmp_path, cfgdir)
    _write(tmp_path / "sourcedata", "06", "01", {"descriptions": [{"datatype": "anat"}]})
    new = _write(cfgdir, "06", "01", {"descriptions": [{"datatype": "func"}]})
    assert resolve_dcm2bids_config_path(paths, "06", "01") == new


def test_writes_never_target_the_legacy_fallback(tmp_path):
    """Saving must migrate to the writable home, not back to where it was read.

    A project sets the override *because* the legacy location is unwritable, so
    a save that followed the read path would fail on exactly those projects.
    """
    cfgdir = tmp_path / "configs"
    paths = _paths(tmp_path, cfgdir)
    legacy = _write(tmp_path / "sourcedata", "06", "01")
    assert resolve_dcm2bids_config_path(paths, "06", "01") == legacy
    assert dcm2bids_config_write_path(paths, "06", "01").parent.parent.parent == cfgdir


def test_missing_everywhere_resolves_to_the_writable_home(tmp_path):
    """The generate-and-save branch must land somewhere writable."""
    cfgdir = tmp_path / "configs"
    paths = _paths(tmp_path, cfgdir)
    resolved = resolve_dcm2bids_config_path(paths, "06", "01")
    assert resolved == dcm2bids_config_write_path(paths, "06", "01")


def test_sessionless_project(tmp_path):
    """`sub_ses_relpath` drops ses- for single-session studies; both agree."""
    cfgdir = tmp_path / "configs"
    paths = _paths(tmp_path, cfgdir)
    assert dcm2bids_config_write_path(paths, "06", "").parent == cfgdir / "sub-06"


# ---- the error that started this ------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the write bit")
def test_unwritable_destination_names_the_fix(tmp_path):
    """The traceback alone never says which key to set, so the message must."""
    locked = tmp_path / "locked"
    (locked / "sub-06" / "ses-01").mkdir(parents=True)
    locked.chmod(0o555)
    (locked / "sub-06").chmod(0o555)
    (locked / "sub-06" / "ses-01").chmod(0o555)
    try:
        target = locked / "sub-06" / "ses-01" / "dcm2bids_config.json"
        with pytest.raises(PermissionError) as exc:
            save_dcm2bids_config({"descriptions": []}, target)
        msg = str(exc.value)
        assert "dcm2bids_config_dir" in msg
        assert str(target) in msg
    finally:
        for d in (locked / "sub-06" / "ses-01", locked / "sub-06", locked):
            d.chmod(0o755)
