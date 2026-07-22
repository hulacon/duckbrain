"""The TODO #14 detector: fieldmap metadata that resolves to nothing.

duckbrain shipped `B0FieldIdentifier` on BOLDs and `B0FieldSource` on fieldmaps,
exactly backwards, and every tool involved was happy — the dataset validated,
dcm2bids succeeded, fMRIPrep exited 0 having silently skipped susceptibility
distortion correction. The code is fixed; this pins the check that would have
caught it, and the wider class it belongs to.

The class matters more than the original bug. Inversion is only one way to reach
fieldmap metadata nothing can act on; a *dangling* source — naming an identifier
no fieldmap declares — produces the identical silent outcome, and is how a
hand-edited or partially-assembled tree fails.
"""

import json

from duckbrain.core.consistency import _check_fmap_intent, check_consistency


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _unit(
    root,
    sub="001",
    ses=None,
    group="B0map_2.5mm",
    fmap_key="B0FieldIdentifier",
    func_key="B0FieldSource",
    with_fmap=True,
):
    """A conversion-shaped unit: an AP/PA pair plus a BOLD and its SBRef."""
    unit = root / f"sub-{sub}" / (f"ses-{ses}" if ses else "")
    if with_fmap:
        for d in ("AP", "PA"):
            _write(unit / "fmap" / f"sub-{sub}_dir-{d}_epi.json", {fmap_key: group})
    for suffix in ("bold", "sbref"):
        _write(unit / "func" / f"sub-{sub}_task-rest_{suffix}.json", {func_key: group})
    return unit


def _config(root, derivatives=None):
    paths = {"bids_dir": str(root)}
    if derivatives:
        paths["derivatives_dir"] = str(derivatives)
    return {"paths": paths}


# ---- the correct dataset is silent ----


def test_correctly_converted_dataset_is_silent(tmp_path):
    _unit(tmp_path)
    assert _check_fmap_intent(_config(tmp_path)) == []


def test_sessioned_layout_is_silent_and_finds_the_subject(tmp_path):
    _unit(tmp_path, ses="01")
    assert _check_fmap_intent(_config(tmp_path)) == []


def test_a_project_with_no_fieldmaps_is_not_nagged(tmp_path):
    """No fieldmaps is a legitimate study design, not a finding."""
    _unit(tmp_path, with_fmap=False, func_key="ignored")
    _write(tmp_path / "sub-001" / "func" / "sub-001_task-rest_bold.json", {})
    assert _check_fmap_intent(_config(tmp_path)) == []


# ---- the shipped bug ----


def test_inverted_intent_is_flagged(tmp_path):
    """The exact shape duckbrain shipped: keys on the wrong side."""
    _unit(tmp_path, fmap_key="B0FieldSource", func_key="B0FieldIdentifier")
    issues = _check_fmap_intent(_config(tmp_path))

    assert [i.check for i in issues] == ["fmap-intent"]
    assert issues[0].subject == "001"
    assert issues[0].stage == "converted"
    message = issues[0].message
    assert "inverted" in message
    assert "sub-001_dir-AP_epi.json" in message
    assert "sub-001_task-rest_bold.json" in message
    assert "sub-001_task-rest_sbref.json" in message


def test_inversion_is_reported_not_repaired(tmp_path):
    """Report-never-repair: the sidecars are left exactly as found."""
    _unit(tmp_path, fmap_key="B0FieldSource", func_key="B0FieldIdentifier")
    sidecar = tmp_path / "sub-001" / "fmap" / "sub-001_dir-AP_epi.json"
    before = sidecar.read_text()

    _check_fmap_intent(_config(tmp_path))

    assert sidecar.read_text() == before


# ---- the wider class ----


def test_a_dangling_source_is_flagged(tmp_path):
    """Both keys on the right side, but they don't meet — SDC still won't run."""
    _unit(tmp_path)
    _write(
        tmp_path / "sub-001" / "func" / "sub-001_task-rest_bold.json",
        {"B0FieldSource": "B0map_typo"},
    )
    issues = _check_fmap_intent(_config(tmp_path))

    assert len(issues) == 1
    assert "no fieldmap here declares" in issues[0].message
    assert "B0map_2.5mm" in issues[0].message  # what *is* declared, to compare against


def test_a_bold_with_no_source_is_flagged_when_fieldmaps_exist(tmp_path):
    _unit(tmp_path)
    _write(tmp_path / "sub-001" / "func" / "sub-001_task-rest_sbref.json", {})
    issues = _check_fmap_intent(_config(tmp_path))

    assert len(issues) == 1
    assert "carry no `B0FieldSource`" in issues[0].message
    assert "SBRef" in issues[0].message  # why an unbound SBRef is not a minor case


def test_a_fieldmap_with_no_identifier_is_flagged(tmp_path):
    """Nothing can reference it, so the field is never estimated."""
    _unit(tmp_path)
    _write(tmp_path / "sub-001" / "fmap" / "sub-001_dir-AP_epi.json", {})
    issues = _check_fmap_intent(_config(tmp_path))

    assert len(issues) == 1
    assert "no `B0FieldIdentifier`" in issues[0].message


def test_list_valued_keys_resolve(tmp_path):
    """BIDS allows str or list; a list that meets the fieldmap is correct."""
    _unit(tmp_path)
    _write(
        tmp_path / "sub-001" / "func" / "sub-001_task-rest_bold.json",
        {"B0FieldSource": ["B0map_2.5mm", "B0map_other"]},
    )
    assert _check_fmap_intent(_config(tmp_path)) == []


# ---- the NORDIC tree fMRIPrep actually reads ----


def test_the_nordic_fmriprep_input_tree_is_checked_too(tmp_path):
    """`nordic/bids_input` is assembled, not converted — it can go stale alone."""
    bids = tmp_path / "bids"
    derivatives = tmp_path / "derivatives"
    _unit(bids)  # raw BIDS is correct...
    staged = derivatives / "nordic" / "bids_input"
    _unit(staged, fmap_key="B0FieldSource", func_key="B0FieldIdentifier")  # ...staged is not

    issues = _check_fmap_intent(_config(bids, derivatives=derivatives))

    assert len(issues) == 1
    assert "NORDIC fMRIPrep input" in issues[0].message


def test_findings_name_which_tree_they_came_from(tmp_path):
    bids = tmp_path / "bids"
    _unit(bids, fmap_key="B0FieldSource", func_key="B0FieldIdentifier")
    issues = _check_fmap_intent(_config(bids, derivatives=tmp_path / "derivatives"))

    assert len(issues) == 1
    assert "raw BIDS" in issues[0].message


# ---- wired into the panel the cockpit renders ----


def test_the_check_runs_as_part_of_check_consistency(tmp_path):
    _unit(tmp_path, fmap_key="B0FieldSource", func_key="B0FieldIdentifier")
    checks = {i.check for i in check_consistency(_config(tmp_path))}
    assert "fmap-intent" in checks


def test_findings_render_as_warnings_not_notes(tmp_path):
    """The cockpit shows anything but `note` as a warning; this must not be muted."""
    _unit(tmp_path, fmap_key="B0FieldSource", func_key="B0FieldIdentifier")
    issues = _check_fmap_intent(_config(tmp_path))
    assert all(i.severity != "note" for i in issues)
