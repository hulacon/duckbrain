"""participants.tsv + dataset_description provenance generation."""

import csv
import json

from duckbrain import __version__
from duckbrain.core.bids_metadata import (
    generate_participants_from_sourcedata,
    write_dataset_description,
    write_derivative_description,
    write_participants_tsv,
)


def _rows(tsv_path):
    with open(tsv_path) as f:
        return list(csv.DictReader(f, dialect="excel-tab"))


def _json(path):
    with open(path) as f:
        return json.load(f)


# ---- dataset_description provenance -----------------------------------------

def test_write_dataset_description_versions_duckbrain_from_its_checkout(tmp_path):
    """duckbrain is distributed by git clone and served from a working copy, so
    users sit on arbitrary commits: stamp the actual checkout, not a
    hand-maintained __version__ that would go stale between releases — the very
    failure this codebase diagnoses upstream in NORDIC."""
    desc = _json(write_dataset_description(tmp_path / "bids", name="study"))
    (entry,) = desc["GeneratedBy"]
    assert entry["Name"] == "duckbrain"
    assert entry["Version"]  # a git describe here, or __version__ off a checkout


def test_duckbrain_version_falls_back_to_the_package_off_a_checkout(monkeypatch, tmp_path):
    """Installed from a wheel there is no git to ask, and the packaged version
    *is* the truth."""
    import duckbrain.core.bids_metadata as M
    monkeypatch.setattr(M, "_duckbrain_repo", lambda: tmp_path / "not-a-checkout")
    desc = _json(write_dataset_description(tmp_path / "bids", name="study"))
    assert desc["GeneratedBy"] == [{"Name": "duckbrain", "Version": __version__}]


def test_write_dataset_description_custom_generated_by(tmp_path):
    gen = [{"Name": "dcm2bids", "Version": "3.2.0"}]
    desc = _json(write_dataset_description(tmp_path / "bids", generated_by=gen))
    assert desc["GeneratedBy"] == gen


def test_write_derivative_description_records_tool_and_source(tmp_path):
    deriv = tmp_path / "derivatives" / "nordic"
    desc = _json(write_derivative_description(
        deriv, "nordic", tool="nordic", tool_version="",
        container="", source_dataset="/proj/bids",
    ))
    assert desc["DatasetType"] == "derivative"
    names = [g["Name"] for g in desc["GeneratedBy"]]
    assert names == ["duckbrain", "nordic"]
    assert desc["DatasetLinks"]["raw"] == "/proj/bids"
    assert desc["SourceDatasets"] == [{"URL": "/proj/bids"}]


def test_write_derivative_description_embeds_version_and_container(tmp_path):
    desc = _json(write_derivative_description(
        tmp_path / "d", "fmriprep-like", tool="fmriprep",
        tool_version="24.1.1", container="fmriprep-24.1.1.sif",
    ))
    tool_entry = next(g for g in desc["GeneratedBy"] if g["Name"] == "fmriprep")
    assert tool_entry["Version"] == "24.1.1"
    assert tool_entry["Container"]["Tag"] == "fmriprep-24.1.1.sif"
    # No source given → no link fields at all.
    assert "DatasetLinks" not in desc


def test_write_participants_empty_still_creates_file(tmp_path):
    # Regression: an empty participant list must still produce a real (header-
    # only) file at the returned path — the GUI reads it back immediately.
    tsv = write_participants_tsv(tmp_path, [])
    assert tsv.exists()
    assert tsv.read_text().strip() == "participant_id\tsex\tage"
    assert _rows(tsv) == []


def test_generate_from_empty_sourcedata(tmp_path):
    src = tmp_path / "sourcedata"
    src.mkdir()
    tsv = generate_participants_from_sourcedata(src, tmp_path)
    assert tsv.exists()
    assert _rows(tsv) == []


def test_generate_single_session_layout(tmp_path):
    # sub-XX/dicom (no ses- level) must be discovered.
    src = tmp_path / "sourcedata"
    for sub in ("sub-001", "sub-002"):
        (src / sub / "dicom").mkdir(parents=True)
    tsv = generate_participants_from_sourcedata(src, tmp_path)
    assert [r["participant_id"] for r in _rows(tsv)] == ["sub-001", "sub-002"]


def test_write_participants_append_dedupes(tmp_path):
    write_participants_tsv(tmp_path, [{"participant_id": "sub-001", "sex": "M", "age": 20}])
    write_participants_tsv(
        tmp_path,
        [
            {"participant_id": "sub-001", "sex": "M", "age": 20},  # dup
            {"participant_id": "sub-002", "sex": "F", "age": 21},
        ],
    )
    ids = [r["participant_id"] for r in _rows(tmp_path / "participants.tsv")]
    assert ids == ["sub-001", "sub-002"]
