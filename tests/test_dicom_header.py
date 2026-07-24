"""Header-based series classification.

The rules are measured against the LCNI repository at
``/projects/lcni/dcm/repository``: over the 112 sessions there that have a
canonical BIDS counterpart, they reproduce the curator's datatype choice for
every series that was converted. The fixtures below are synthesised from the
header values actually observed there, including the two MR dialects — 36% of
that corpus is Siemens ``syngo MR XA30`` enhanced-MR, where the classic fields
this used to depend on do not exist.
"""

from pathlib import Path

import pytest

from duckbrain.core.dicom_header import SeriesHeader, classify_from_header
from duckbrain.core.dicom_inspect import SeriesInfo, classify_series


def classic(**kwargs) -> SeriesHeader:
    """A classic-dialect header, defaulting to the fields Siemens VE/VB writes."""
    base = dict(
        modality="MR",
        image_type=("ORIGINAL", "PRIMARY", "M", "ND"),
        mr_acquisition_type="2D",
        is_epi=True,
        is_spin_echo=False,
        dialect="classic",
        volumes=200,
    )
    base.update(kwargs)
    return SeriesHeader(**base)


def enhanced(**kwargs) -> SeriesHeader:
    """An enhanced-dialect (XA30) header. No ScanningSequence, no EchoNumbers."""
    base = dict(
        modality="MR",
        image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE", "MAGNITUDE"),
        mr_acquisition_type="2D",
        is_epi=True,
        is_spin_echo=False,
        dialect="enhanced",
        volumes=200,
    )
    base.update(kwargs)
    return SeriesHeader(**base)


# --- the case that motivated all of this -----------------------------------
@pytest.mark.parametrize("dialect", [classic, enhanced])
def test_a_bold_run_is_recognised_whatever_the_operator_called_it(dialect):
    """'food', 'Whack', 'WMS_R1', 'EPI196' are all ordinary BOLD runs.

    No vocabulary can recover that from the name, and every one of them
    classified 'unknown' and converted to nothing.
    """
    assert classify_from_header(dialect()) == ("func", "bold")


@pytest.mark.parametrize("dialect", [classic, enhanced])
def test_single_band_reference_is_told_apart_by_volume_count_alone(dialect):
    """Nothing in the header distinguishes an SBRef from its parent BOLD.

    Same ImageType, TR, flip angle, sequence. The volume count is the only
    separator and it is exact across the corpus: sbref 1, bold many.
    """
    assert classify_from_header(dialect(volumes=1)) == ("sbref", "")
    assert classify_from_header(dialect(volumes=2))[0] == "func"


@pytest.mark.parametrize("dialect", [classic, enhanced])
def test_spin_echo_epi_is_a_fieldmap_not_a_bold_run(dialect):
    """Both are EPI; the readout is what separates them."""
    assert classify_from_header(dialect(is_spin_echo=True, volumes=3)) == ("fmap", "epi")


def test_enhanced_dialect_is_not_read_with_classic_rules():
    """An XA30 series carries no ScanningSequence/EchoNumbers at the top level.

    A rule keyed on those does not misfire on these series — it sees nothing at
    all, which is worse, because the series then silently falls through to the
    name heuristics that motivated this module.
    """
    header = enhanced()
    assert header.dialect == "enhanced"
    assert header.echo_numbers == ()
    assert classify_from_header(header) == ("func", "bold")


# --- gradient-echo fieldmaps -----------------------------------------------
def test_gre_fieldmap_phase_and_magnitude_are_told_apart():
    magnitude = classic(
        is_epi=False,
        is_spin_echo=False,
        image_type=("ORIGINAL", "PRIMARY", "M", "ND", "NORM"),
        echo_numbers=(1, 2),
        volumes=144,
    )
    phase = classic(
        is_epi=False,
        is_spin_echo=False,
        image_type=("ORIGINAL", "PRIMARY", "P", "ND"),
        echo_numbers=(2,),
        volumes=72,
    )
    assert classify_from_header(magnitude) == ("fmap", "magnitude")
    assert classify_from_header(phase) == ("fmap", "phasediff")


# --- anatomicals, scouts, and the navigator setter -------------------------
def test_defaced_anatomical_is_recognised():
    header = classic(
        mr_acquisition_type="3D",
        is_epi=False,
        is_spin_echo=False,
        image_type=("DERIVED", "SECONDARY", "M", "ND"),
        volumes=176,
    )
    assert classify_from_header(header) == ("anat", "")


def test_a_3d_original_series_is_left_to_the_name_heuristics():
    """The vNav setter and the scout are both 3D ORIGINAL — but so is an
    undefaced T1w, so this rule may promote and must never demote."""
    header = classic(
        mr_acquisition_type="3D",
        is_epi=False,
        is_spin_echo=False,
        image_type=("ORIGINAL", "PRIMARY", "M", "NONE"),
        volumes=192,
    )
    assert classify_from_header(header) == ("", "")


def test_an_undefaced_mprage_still_classifies_by_name():
    series = [
        SeriesInfo(
            series_number=3,
            description="t1_mprage_sag_p2_iso",
            path=Path("/nonexistent"),
            file_count=176,
            header=classic(
                mr_acquisition_type="3D",
                is_epi=False,
                is_spin_echo=False,
                image_type=("ORIGINAL", "PRIMARY", "M", "ND"),
                volumes=176,
            ),
        )
    ]
    classify_series(series)
    assert series[0].classification == "anat"
    assert series[0].classified_by == "name"


def test_turbo_spin_echo_is_a_t2w():
    header = classic(is_epi=False, is_spin_echo=True, volumes=30)
    assert classify_from_header(header) == ("anat", "T2w")


# --- things that are never source data -------------------------------------
@pytest.mark.parametrize(
    "image_type",
    [
        ("DERIVED", "PRIMARY", "MPR", "ND"),  # scout reformat
        ("DERIVED", "SECONDARY", "CSA REPORT"),  # PhoenixZIPReport
        ("ORIGINAL", "PRIMARY", "RAWDATA", "PHYSIO"),
        ("DERIVED", "PRIMARY", "TTEST"),
        ("DERIVED", "PRIMARY", "GLM"),
    ],
)
def test_scanner_derived_series_are_dropped(image_type):
    assert classify_from_header(classic(image_type=image_type))[0] == "derived"


def test_a_defaced_anatomical_is_not_mistaken_for_a_derived_series():
    """DERIVED\\SECONDARY is what defacing produces, and all 112 anatomicals in
    the corpus carry it. Only DERIVED\\PRIMARY means scanner-derived."""
    header = classic(
        mr_acquisition_type="3D",
        is_epi=False,
        is_spin_echo=False,
        image_type=("DERIVED", "SECONDARY", "M", "ND"),
    )
    assert not header.is_derived
    assert classify_from_header(header) == ("anat", "")


def test_non_mr_modality_is_dropped():
    assert classify_from_header(classic(modality="SR"))[0] == "derived"


def test_diffusion_is_named():
    assert (
        classify_from_header(classic(image_type=("ORIGINAL", "PRIMARY", "DIFFUSION")))[0] == "dwi"
    )


# --- absence is not evidence -----------------------------------------------
def test_an_unreadable_or_empty_series_falls_back_to_the_name():
    assert classify_from_header(None) == ("", "")
    assert classify_from_header(SeriesHeader(unreadable=True, volumes=3)) == ("", "")

    series = [
        SeriesInfo(
            series_number=3,
            description="mprage_p2_defaced",
            path=Path("/nonexistent"),
            file_count=0,
            header=None,
        )
    ]
    classify_series(series)
    assert series[0].classification == "anat"
    assert series[0].classified_by == "name"


def test_the_sbref_rescue_cannot_outrank_the_header():
    """The SBRef signal exists to rescue a name that said nothing.

    It must not relabel a series the scanner already described — otherwise an
    anatomical that happens to share a stem with a functional reference gets
    promoted to func.
    """
    series = [
        SeriesInfo(
            series_number=3,
            description="encoding",
            path=Path("/nonexistent"),
            file_count=176,
            header=classic(
                mr_acquisition_type="3D",
                is_epi=False,
                is_spin_echo=False,
                image_type=("DERIVED", "SECONDARY", "M", "ND"),
            ),
        ),
        SeriesInfo(
            series_number=4,
            description="encoding_SBRef",
            path=Path("/nonexistent"),
            file_count=1,
            header=classic(volumes=1),
        ),
    ]
    classify_series(series)
    assert series[0].classification == "anat"
    assert series[1].classification == "sbref"


# --- reading real DICOM files ----------------------------------------------
# The tests above exercise the rules; these exercise the tag navigation, which
# is where the two dialects actually diverge.


def _write_classic(directory: Path, count: int, **overrides) -> None:
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
        ds.file_meta.MediaStorageSOPInstanceUID = f"1.2.3.4.{index}"
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
        ds.SOPInstanceUID = f"1.2.3.4.{index}"
        ds.Modality = "MR"
        ds.ImageType = list(overrides.get("image_type", ["ORIGINAL", "PRIMARY", "M", "ND"]))
        ds.MRAcquisitionType = overrides.get("mr_acquisition_type", "2D")
        ds.ScanningSequence = overrides.get("scanning_sequence", ["EP"])
        ds.SequenceName = overrides.get("sequence_name", "epfid2d1_116")
        ds.SeriesDescription = overrides.get("description", "whatever")
        echoes = overrides.get("echo_numbers", [1] * count)
        ds.EchoNumbers = echoes[index % len(echoes)]
        pydicom.dcmwrite(directory / f"{index:04d}.dcm", ds, enforce_file_format=True)


def _write_enhanced(directory: Path, count: int, **overrides) -> None:
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4.1"
        ds.file_meta.MediaStorageSOPInstanceUID = f"1.2.3.4.{index}"
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4.1"
        ds.SOPInstanceUID = f"1.2.3.4.{index}"
        ds.Modality = "MR"
        ds.ImageType = list(
            overrides.get("image_type", ["ORIGINAL", "PRIMARY", "FMRI", "NONE", "MAGNITUDE"])
        )
        ds.MRAcquisitionType = overrides.get("mr_acquisition_type", "2D")
        ds.EchoPlanarPulseSequence = overrides.get("epi", "YES")
        timing = Dataset()
        timing.RFEchoTrainLength = overrides.get("echo_train", 0)
        shared = Dataset()
        shared.MRTimingAndRelatedParametersSequence = [timing]
        ds.SharedFunctionalGroupsSequence = [shared]
        pydicom.dcmwrite(directory / f"{index:04d}.dcm", ds, enforce_file_format=True)


def test_reads_a_classic_bold_series(tmp_path):
    from duckbrain.core.dicom_header import read_series_header

    _write_classic(tmp_path / "Series_9_food", 20)
    header = read_series_header(tmp_path / "Series_9_food")
    assert header.dialect == "classic"
    assert header.is_epi is True
    assert header.is_spin_echo is False
    assert header.volumes == 20
    assert classify_from_header(header) == ("func", "bold")


def test_reads_a_classic_spin_echo_fieldmap(tmp_path):
    from duckbrain.core.dicom_header import read_series_header

    _write_classic(tmp_path / "Series_20_distortion_ap", 3, sequence_name="epse2d1_116")
    header = read_series_header(tmp_path / "Series_20_distortion_ap")
    assert header.is_spin_echo is True
    assert classify_from_header(header) == ("fmap", "epi")


def test_reads_an_enhanced_bold_series(tmp_path):
    """The XA30 path: no ScanningSequence, no SequenceName, no EchoNumbers."""
    from duckbrain.core.dicom_header import read_series_header

    _write_enhanced(tmp_path / "Series_9_MAB1", 20)
    header = read_series_header(tmp_path / "Series_9_MAB1")
    assert header.dialect == "enhanced"
    assert header.is_epi is True
    assert header.is_spin_echo is False
    assert classify_from_header(header) == ("func", "bold")


def test_reads_an_enhanced_spin_echo_fieldmap(tmp_path):
    from duckbrain.core.dicom_header import read_series_header

    _write_enhanced(tmp_path / "Series_4_dir_AP", 3, echo_train=1)
    header = read_series_header(tmp_path / "Series_4_dir_AP")
    assert header.is_spin_echo is True
    assert classify_from_header(header) == ("fmap", "epi")


def test_multi_echo_magnitude_needs_more_than_the_first_file(tmp_path):
    """A gradient-echo fieldmap interleaves two echoes across the series.

    Reading only file 0 reports EchoNumbers=1 and the series looks single-echo,
    which is the difference between magnitude1+magnitude2 and nothing.
    """
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_5_fieldmap_2mm"
    _write_classic(
        directory,
        8,
        scanning_sequence=["GR"],
        sequence_name="*fm2d2r",
        image_type=["ORIGINAL", "PRIMARY", "M", "ND", "NORM"],
        echo_numbers=[1, 1, 1, 1, 2, 2, 2, 2],
    )
    header = read_series_header(directory)
    assert header.echo_numbers == (1, 2)
    assert classify_from_header(header) == ("fmap", "magnitude")


def test_an_empty_series_directory_reads_as_no_header(tmp_path):
    """0.43% of the corpus. A name-only converter reports finding the T1w here
    and then produces no file."""
    from duckbrain.core.dicom_header import read_series_header

    (tmp_path / "Series_1010_mprage_p2_defaced").mkdir()
    assert read_series_header(tmp_path / "Series_1010_mprage_p2_defaced") is None


def test_a_non_dicom_file_does_not_crash_the_reader(tmp_path):
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_1_junk"
    directory.mkdir()
    (directory / "notes.txt").write_text("not a dicom")
    header = read_series_header(directory)
    assert header is None or header.unreadable
