"""DICOM sorter — metadata is untrusted input, and the default action is a move.

This module had no tests at all while being the only destructive filesystem code
in the repo: it builds destination paths out of PatientName / StudyDescription /
SeriesDescription, and once the GUI's dry-run box is unticked it *moves* (via
``os.renames``, which also prunes emptied source directories upward).

None of the cases below need a malicious DICOM. Site and scanner conventions put
carets, slashes and spaces in these fields as a matter of course; the review that
prompted these tests (DB-007) found the path built from them unchecked.
"""

import os
from pathlib import Path

import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from duckbrain.core.dicom_sorter import (
    UnsafeSortPaths,
    safe_component,
    sort_dicoms,
)


def _write_dicom(path, *, patient="Sub01", study="", series_desc="mprage",
                 series_num=2, date="20260722", time="120000"):
    """A minimal but genuinely readable DICOM file at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = Dataset()
    ds.PatientName = patient
    ds.StudyDate = date
    ds.StudyTime = time
    ds.SeriesNumber = series_num
    ds.SeriesDescription = series_desc
    if study:
        ds.StudyDescription = study
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.file_meta.MediaStorageSOPInstanceUID = "1.2.3.4"
    ds.save_as(path, enforce_file_format=True)
    return path


# ---- the sanitizer ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("mprage", "mprage"),
    ("t1 mprage", "t1_mprage"),
    ("../../etc", ".._.._etc".strip("._")),   # separators go; no traversal survives
    ("/absolute/path", "absolute_path"),
    ("back\\slash", "back_slash"),
    ("quote'inject", "quote_inject"),
    ("dollar$sign", "dollar_sign"),
    ("BOLD-task+rest.v2", "BOLD-task+rest.v2"),   # readable characters survive
])
def test_safe_component_strips_what_would_change_the_path(raw, expected):
    out = safe_component(raw, "fallback")
    assert out == expected
    assert "/" not in out and "\\" not in out
    assert out not in (".", "..")


@pytest.mark.parametrize("raw", ["", "   ", "..", ".", "///", "___"])
def test_safe_component_falls_back_when_nothing_survives(raw):
    """An empty component would silently collapse a level of the hierarchy."""
    assert safe_component(raw, "Unknown") == "Unknown"


def test_safe_component_keeps_unicode_out_of_paths():
    out = safe_component("Müller^Anna", "Unknown")
    assert out.isascii()
    assert "^" not in out


# ---- containment ------------------------------------------------------------

def test_traversal_in_patient_name_stays_inside_the_output_root(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm", patient="../../escape")

    result = sort_dicoms(src, out, copy=True)

    assert result.sorted_files == 1
    written = list(out.rglob("*.dcm"))
    assert len(written) == 1
    assert written[0].is_relative_to(out)
    assert not (tmp_path.parent / "escape").exists()


def test_absolute_looking_study_part_does_not_reset_the_join(tmp_path):
    """`output_dir.joinpath(*parts)` with an absolute part discards output_dir
    entirely — StudyDescription splits on ^, so it reached joinpath as parts."""
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm", study="STUDY^/tmp/hijacked")

    sort_dicoms(src, out, include_study_dir=True, copy=True)

    written = list(out.rglob("*.dcm"))
    assert len(written) == 1
    assert written[0].is_relative_to(out)


def test_every_destination_stays_under_the_output_root(tmp_path):
    """The invariant, over a spread of hostile-looking metadata."""
    src, out = tmp_path / "in", tmp_path / "out"
    for i, name in enumerate(["..", "../..", "/etc/passwd", "a/b/c", "."]):
        _write_dicom(src / f"{i:04d}.dcm", patient=name, series_desc=name)

    sort_dicoms(src, out, copy=True)

    for p in out.rglob("*"):
        assert Path(os.path.normpath(p)).is_relative_to(out)


# ---- overlapping roots ------------------------------------------------------

def test_output_nested_under_input_is_refused(tmp_path):
    """With the default move this rearranges the source tree into itself, and
    sorted output can be rediscovered as new input."""
    src = tmp_path / "in"
    _write_dicom(src / "0001.dcm")
    with pytest.raises(UnsafeSortPaths):
        sort_dicoms(src, src / "sorted")


def test_input_nested_under_output_is_refused(tmp_path):
    out = tmp_path / "out"
    src = out / "raw"
    _write_dicom(src / "0001.dcm")
    with pytest.raises(UnsafeSortPaths):
        sort_dicoms(src, out)


def test_identical_roots_are_refused(tmp_path):
    _write_dicom(tmp_path / "0001.dcm")
    with pytest.raises(UnsafeSortPaths):
        sort_dicoms(tmp_path, tmp_path)


# ---- symlinks ---------------------------------------------------------------

def test_a_symlink_loop_does_not_hang_the_walk(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm")
    (src / "loop").symlink_to(src, target_is_directory=True)

    result = sort_dicoms(src, out, copy=True)   # must terminate

    assert result.sorted_files == 1


def test_a_symlink_out_of_the_tree_is_not_followed(tmp_path):
    src, out, elsewhere = tmp_path / "in", tmp_path / "out", tmp_path / "elsewhere"
    _write_dicom(src / "0001.dcm")
    _write_dicom(elsewhere / "9999.dcm")
    (src / "link").symlink_to(elsewhere, target_is_directory=True)

    result = sort_dicoms(src, out, copy=True)

    assert result.sorted_files == 1
    assert (elsewhere / "9999.dcm").exists()


# ---- the ordinary path, so the hardening didn't break sorting ---------------

def test_files_land_in_the_expected_lcni_layout(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm", patient="Sub01", series_num=2,
                 series_desc="t1_mprage", date="20260722", time="120000")

    sort_dicoms(src, out, copy=True)

    assert (out / "Sub01_20260722_120000" / "Series_02_t1_mprage" / "0001.dcm").exists()


def test_study_dir_grouping_expands_the_caret_separator(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm", study="hulacon^divatten")

    sort_dicoms(src, out, include_study_dir=True, copy=True)

    assert list((out / "hulacon" / "divatten").rglob("*.dcm"))


def test_move_is_a_move_and_copy_is_a_copy(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm")
    sort_dicoms(src, out, copy=True)
    assert (src / "0001.dcm").exists()

    src2, out2 = tmp_path / "in2", tmp_path / "out2"
    _write_dicom(src2 / "0001.dcm")
    sort_dicoms(src2, out2, copy=False)
    assert not (src2 / "0001.dcm").exists()
    assert list(out2.rglob("*.dcm"))


def test_dry_run_writes_nothing(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm")

    result = sort_dicoms(src, out, dry_run=True)

    assert result.sorted_files == 1
    assert not out.exists()
    assert (src / "0001.dcm").exists()


def test_duplicates_are_skipped_unless_overwrite(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm")
    sort_dicoms(src, out, copy=True)

    second = sort_dicoms(src, out, copy=True)
    assert second.duplicates == 1
    assert second.sorted_files == 0

    third = sort_dicoms(src, out, copy=True, overwrite=True)
    assert third.sorted_files == 1


def test_non_dicom_files_are_skipped_not_failed(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _write_dicom(src / "0001.dcm")
    (src / "notes.txt").write_text("not a dicom")

    result = sort_dicoms(src, out, copy=True)

    assert result.sorted_files == 1
    assert result.skipped_files == 1
    assert result.failed_files == 0
