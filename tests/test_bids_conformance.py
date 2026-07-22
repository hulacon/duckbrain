"""Trusting the DICOM header over the filename, and letting dcm2bids validate.

Two changes with one theme. duckbrain used to force `PhaseEncodingDirection`
from the `_ap`/`_pa` token in a series name, overwriting the value dcm2niix
derives from the DICOM header — the same "trust the filename over the data"
error as the inverted B0 fields. The header now wins, and a disagreement is
*reported* rather than overwritten, because a name/header mismatch says
something real about the acquisition.
"""

import json

from duckbrain.core.consistency import _check_fmap_pe_direction
from duckbrain.core.dcm2bids_config import generate_config
from duckbrain.core.dicom_inspect import FieldmapDetection, SeriesInfo


def _series(num, desc, cls, n=300):
    s = SeriesInfo(series_number=num, description=desc, path=None, file_count=n)
    s.classification = cls
    return s


# ---- duckbrain no longer writes PhaseEncodingDirection ----


def test_fmap_descriptions_do_not_overwrite_phase_encoding_direction():
    series = [
        _series(3, "se_epi_ap", "fmap", n=3),
        _series(4, "se_epi_pa", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(strategy="series_description", groups={"": {"ap": 3, "pa": 4}})
    cfg = generate_config(series, fmaps, subject="001")

    fmap_descs = [d for d in cfg["descriptions"] if d["datatype"] == "fmap"]
    assert fmap_descs, "expected fmap descriptions"
    for d in fmap_descs:
        changes = d["sidecar_changes"]
        # The association is still stated...
        assert changes["B0FieldIdentifier"] == "B0map_"
        # ...but the header value is left exactly as dcm2niix derived it.
        assert "PhaseEncodingDirection" not in changes


# ---- and a name/header disagreement is reported instead ----


def _fmap_sidecar(root, name, ped):
    d = root / "sub-001" / "fmap"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"PhaseEncodingDirection": ped}))


def _config(root):
    return {"paths": {"bids_dir": str(root)}}


def test_matching_direction_is_silent(tmp_path):
    _fmap_sidecar(tmp_path, "sub-001_dir-AP_epi.json", "j-")
    _fmap_sidecar(tmp_path, "sub-001_dir-PA_epi.json", "j")
    assert _check_fmap_pe_direction(_config(tmp_path)) == []


def test_mismatch_is_flagged_against_the_label_not_the_header(tmp_path):
    """A series named AP whose header says PA: the label is the suspect one."""
    _fmap_sidecar(tmp_path, "sub-001_dir-AP_epi.json", "j")
    issues = _check_fmap_pe_direction(_config(tmp_path))

    assert len(issues) == 1
    assert issues[0].check == "fmap-pe-direction"
    assert issues[0].subject == "001"
    assert "header is authoritative" in issues[0].message


def test_a_sidecar_without_the_field_is_not_a_finding(tmp_path):
    """Absent metadata degrades quietly rather than raising a false alarm."""
    d = tmp_path / "sub-001" / "fmap"
    d.mkdir(parents=True)
    (d / "sub-001_dir-AP_epi.json").write_text("{}")
    assert _check_fmap_pe_direction(_config(tmp_path)) == []


def test_missing_bids_dir_is_not_a_finding(tmp_path):
    assert _check_fmap_pe_direction({"paths": {"bids_dir": str(tmp_path / "nope")}}) == []


def test_unknown_dir_entity_is_ignored(tmp_path):
    """Only the directions duckbrain emits are checked; LR/RL aren't its business."""
    _fmap_sidecar(tmp_path, "sub-001_dir-LR_epi.json", "i")
    assert _check_fmap_pe_direction(_config(tmp_path)) == []


# ---- dcm2bids runs the validator itself ----


def test_dcm2bids_template_requests_validation_by_default(tmp_path):
    """The validator ships inside the dcm2bids container, so this is free."""
    from duckbrain.config import load_config, scaffold_project
    from duckbrain.slurm.templates import build_context, render_sbatch

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    cfg = load_config(project_dir=str(proj))

    def render(cfg):
        ctx = build_context(
            cfg,
            "dcm2bids",
            subject="001",
            session="01",
            dicom_dir="/d",
            config_json="/c.json",
            config_json_dir="/",
            container_path="/x.sif",
            force=False,
        )
        return render_sbatch("dcm2bids", ctx)

    assert "--bids_validate" in render(cfg)

    cfg["conversion"] = {"bids_validate": False}
    assert "--bids_validate" not in render(cfg)
