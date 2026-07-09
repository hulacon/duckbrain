"""participants.tsv generation, including empty and single-session sourcedata."""

import csv

from duckbrain.core.bids_metadata import (
    generate_participants_from_sourcedata,
    write_participants_tsv,
)


def _rows(tsv_path):
    with open(tsv_path) as f:
        return list(csv.DictReader(f, dialect="excel-tab"))


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
