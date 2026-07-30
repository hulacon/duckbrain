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
    base.setdefault("single_volume", base["volumes"] == 1)
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
    base.setdefault("single_volume", base["volumes"] == 1)
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


# --- the diffusion reference, and the one sibling that may outrank a header ---
#
# Headers below are the values actually read from
# /projects/hulacon/shared/mmmsourcedata/sub-06/ses-01, which is the only fixture
# on this filesystem with diffusion SBRefs at all — the LCNI corpus has zero
# across all 2139 series directories, which is why this shape needs unit tests
# rather than a corpus run.


def _diffusion_session() -> list[SeriesInfo]:
    """A CMRR multi-shell block: reference then volumes, per direction."""
    return [
        SeriesInfo(
            series_number=5,
            description="se_epi_ap_encoding",
            path=Path("/nonexistent"),
            file_count=3,
            header=classic(is_spin_echo=True, volumes=3),
        ),
        SeriesInfo(
            series_number=20,
            description="cmrr_diff_3shell_ap_SBRef",
            path=Path("/nonexistent"),
            file_count=1,
            # No DIFFUSION token — this is the whole problem.
            header=classic(
                image_type=("ORIGINAL", "PRIMARY", "M", "NONE"),
                is_spin_echo=True,
                volumes=1,
            ),
        ),
        SeriesInfo(
            series_number=21,
            description="cmrr_diff_3shell_ap",
            path=Path("/nonexistent"),
            file_count=104,
            header=classic(
                image_type=("ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"),
                is_spin_echo=True,
                volumes=104,
            ),
        ),
    ]


def test_a_diffusion_reference_is_not_a_pepolar_fieldmap_half():
    """It is a single-volume spin-echo EPI, which is also the fieldmap definition.

    Everything the header offers is identical to the real ``se_epi_ap_encoding``
    beside it — ``is_epi``, ``is_spin_echo``, ``mr_acquisition_type``, volume
    count — so the series' own header cannot settle it and the branch returns
    ``fmap``. The base sibling can: it carries ``DIFFUSION``.
    """
    ap_sbref, ap = _diffusion_session()[1], _diffusion_session()[2]
    assert classify_from_header(ap_sbref.header) == ("fmap", "epi"), (
        "the header alone still says fieldmap; the fix is not in this tier"
    )
    assert classify_from_header(ap.header) == ("dwi", "")

    series = _diffusion_session()
    classify_series(series)
    assert [s.classification for s in series] == ["fmap", "dwi", "dwi"]
    assert series[1].suffix_hint == "sbref"
    assert series[1].classified_by == "sibling"


def test_the_real_fieldmap_beside_it_is_left_alone():
    """The demotion is keyed on the sibling, not on 'looks like a reference'.

    ``se_epi_ap_encoding`` has no ``_SBRef`` suffix and no diffusion sibling, so
    nothing about this pass may touch it — it is the pair the functional runs
    should have been binding to all along.
    """
    series = _diffusion_session()
    classify_series(series)
    assert (series[0].classification, series[0].suffix_hint) == ("fmap", "epi")
    assert series[0].classified_by == "header"


def test_a_functional_reference_keeps_its_own_header_verdict():
    """A sibling only speaks for the series that actually references it.

    ``Resting_baseline_SBRef`` sits in the same session as the diffusion block
    and must stay ``sbref``: its own base sibling is the BOLD run, not a
    diffusion series, so the demotion has nothing to key on.
    """
    series = _diffusion_session() + [
        SeriesInfo(
            series_number=58,
            description="Resting_baseline_SBRef",
            path=Path("/nonexistent"),
            file_count=1,
            header=classic(image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"), volumes=1),
        ),
        SeriesInfo(
            series_number=59,
            description="Resting_baseline",
            path=Path("/nonexistent"),
            file_count=390,
            header=classic(image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"), volumes=390),
        ),
    ]
    classify_series(series)
    by_number = {s.series_number: s for s in series}
    assert by_number[58].classification == "sbref"
    assert by_number[59].classification == "func"


def test_the_spurious_pair_the_diffusion_references_used_to_form():
    """The end-to-end failure: two directions of one diffusion block pair up.

    ``detect_fieldmaps`` was not at fault — given two single-volume spin-echo
    EPIs named ``..._ap_SBRef`` and ``..._pa_SBRef`` it strips the direction
    token, finds one base holding both directions, and correctly calls it a
    complete pair. On the five ``ses-01`` sessions of the fixture, the resting
    run and its reference bound to *that* pair and nothing bound to the real
    ``encoding`` one, so fMRIPrep would have estimated the field from two
    diffusion references and applied it to a functional run.
    """
    from duckbrain.core.dicom_inspect import detect_fieldmaps

    series = _diffusion_session() + [
        SeriesInfo(
            series_number=7,
            description="se_epi_pa_encoding",
            path=Path("/nonexistent"),
            file_count=3,
            header=classic(is_spin_echo=True, volumes=3),
        ),
        SeriesInfo(
            series_number=29,
            description="cmrr_diff_3shell_pa_SBRef",
            path=Path("/nonexistent"),
            file_count=1,
            header=classic(
                image_type=("ORIGINAL", "PRIMARY", "M", "NONE"),
                is_spin_echo=True,
                volumes=1,
            ),
        ),
        SeriesInfo(
            series_number=30,
            description="cmrr_diff_3shell_pa",
            path=Path("/nonexistent"),
            file_count=104,
            header=classic(
                image_type=("ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"),
                is_spin_echo=True,
                volumes=104,
            ),
        ),
    ]
    detection = detect_fieldmaps(classify_series(series))
    assert detection.groups == {"encoding": {"ap": 5, "pa": 7}}


def test_a_project_declaration_still_outranks_the_diffusion_sibling():
    """The tier order is unchanged: a declaration is the study saying what it is."""
    from duckbrain.core.series_types import TypeRule

    series = _diffusion_session()
    classify_series(series, type_rules=[TypeRule("cmrr_diff_3shell_ap_SBRef", "func", "sbref")])
    assert series[1].classification == "func"
    assert series[1].classified_by == "project"


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
        ds.ImageType = list(
            overrides.get("image_type", ["ORIGINAL", "PRIMARY", "M", "ND", "MOSAIC"])
        )
        ds.MRAcquisitionType = overrides.get("mr_acquisition_type", "2D")
        ds.ScanningSequence = overrides.get("scanning_sequence", ["EP"])
        ds.SequenceName = overrides.get("sequence_name", "epfid2d1_116")
        ds.SeriesDescription = overrides.get("description", "whatever")
        if "acquisition_time" in overrides:
            ds.AcquisitionTime = overrides["acquisition_time"]
        echoes = overrides.get("echo_numbers", [1] * count)
        ds.EchoNumbers = echoes[index % len(echoes)]
        positions = overrides.get("positions")
        if positions is not None:
            ds.ImagePositionPatient = [0.0, 0.0, float(positions[index % len(positions)])]
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
        ds.PulseSequenceName = overrides.get("sequence_name", "epfid2d1_116")
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


def test_a_classic_turbo_spin_echo_reads_as_spin_echo(tmp_path):
    """'*tse2d1_18' does not start 'epse', but ScanningSequence says 'SE'.

    Until both witnesses were consulted this read as gradient echo, so the T2w
    rule was unreachable in the classic dialect and these series classified only
    because their *name* happened to contain 't2'.
    """
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_11_survey_cor"
    _write_classic(
        directory,
        30,
        sequence_name="*tse2d1_18",
        scanning_sequence=["SE"],
        image_type=["ORIGINAL", "PRIMARY", "M", "NORM", "DIS2D"],
    )
    header = read_series_header(directory)
    assert header.is_spin_echo is True
    assert classify_from_header(header) == ("anat", "T2w")


def test_a_pepolar_fieldmap_is_spin_echo_without_se_in_its_scanning_sequence(tmp_path):
    """The other half of the union, and the reason it cannot be simplified away.

    Siemens reports ScanningSequence ('EP',) for the spin-echo pepolar fieldmap —
    no 'SE' anywhere in it. Only the sequence name sees this one.
    """
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_20_se_epi_fieldmap_ap"
    _write_classic(directory, 3, sequence_name="epse2d1_104", scanning_sequence=["EP"])
    header = read_series_header(directory)
    assert header.is_spin_echo is True
    assert classify_from_header(header) == ("fmap", "epi")


@pytest.mark.parametrize(
    ("sequence_name", "scanning_sequence"),
    [
        ("epfid2d1_104", ["EP"]),  # BOLD
        ("*fl3d1_ns", ["GR"]),  # scout
        ("*tfl3d1_16ns", ["GR", "IR"]),  # mprage
        ("*fm2d2r", ["GR"]),  # gradient-echo fieldmap
        ("ep_b0", ["EP"]),  # diffusion
    ],
)
def test_gradient_echo_families_are_not_spin_echo(tmp_path, sequence_name, scanning_sequence):
    """Every family measured in the corpus that must stay false under the union."""
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_3_whatever"
    _write_classic(directory, 4, sequence_name=sequence_name, scanning_sequence=scanning_sequence)
    assert read_series_header(directory).is_spin_echo is False


def test_a_dual_echo_turbo_spin_echo_is_not_a_gre_fieldmap_magnitude(tmp_path):
    """A PD+T2 turbo spin echo is an ordinary Siemens protocol.

    Read as gradient echo it reached the gradient-echo fieldmap branch, where
    two echo numbers are the whole test for a magnitude — so a perfectly good
    anatomical converted as half a fieldmap.
    """
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_12_pd_t2_tse"
    _write_classic(
        directory,
        8,
        sequence_name="*tse2d1_18",
        scanning_sequence=["SE"],
        image_type=["ORIGINAL", "PRIMARY", "M", "NORM", "DIS2D"],
        echo_numbers=[1, 1, 1, 1, 2, 2, 2, 2],
    )
    header = read_series_header(directory)
    assert header.echo_numbers == (1, 2)
    assert classify_from_header(header) == ("anat", "T2w")


def test_the_enhanced_dialect_carries_its_sequence_name_under_a_different_tag(tmp_path):
    """XA30 renamed SequenceName to PulseSequenceName. No series carries both."""
    from duckbrain.core.dicom_header import read_series_header

    _write_classic(tmp_path / "Series_1_classic", 2, sequence_name="*tfl3d1_16ns")
    _write_enhanced(tmp_path / "Series_2_enhanced", 2, sequence_name="*tfl3d1_16ns")
    assert read_series_header(tmp_path / "Series_1_classic").sequence_name == "*tfl3d1_16ns"
    assert read_series_header(tmp_path / "Series_2_enhanced").sequence_name == "*tfl3d1_16ns"


def test_a_scout_is_recognised_from_its_sequence_name_when_the_name_says_nothing():
    """The localizer vocabulary only knows 'scout'/'localizer'/'aa_scout'.

    A site that calls its localizer anything else classified 'unknown' and the
    user got a warning about a series duckbrain should have known to drop.
    """
    header = classic(
        mr_acquisition_type="3D",
        is_epi=False,
        image_type=("ORIGINAL", "PRIMARY", "M", "ND", "NORM"),
        sequence_name="*fl3d1_ns",
        volumes=128,
    )
    assert classify_from_header(header) == ("scout", "")


def test_a_scout_reformat_is_derived_before_the_sequence_tier_sees_it():
    """The ordering guard, and the reason the fl3d1 rule is usable at all.

    Half of that family in the corpus is the scout's own MPR reformats, which
    carry the same sequence name. They are claimed by is_derived one tier
    earlier — if the tier ran first they would classify 'scout' and the
    distinction between a localizer and its reformats would be lost.
    """
    header = classic(
        mr_acquisition_type="3D",
        is_epi=False,
        image_type=("DERIVED", "PRIMARY", "MPR", "ND"),
        sequence_name="*fl3d1_ns",
    )
    assert classify_from_header(header) == ("derived", "")


def test_a_3d_space_is_a_t2w_from_its_sequence_name():
    """WMS/WMS179 Series_21 't2_space_sag_p2_iso', verbatim.

    Undefaced, so it is ORIGINAL\\PRIMARY and the 3D DERIVED\\SECONDARY rule
    never reaches it; enhanced, so the sequence name arrives as
    PulseSequenceName with no ScanningSequence beside it. The tier is the only
    header evidence that names this one.
    """
    header = enhanced(
        mr_acquisition_type="3D",
        is_epi=False,
        image_type=("ORIGINAL", "PRIMARY", "M", "NONE"),
        sequence_name="*spcR_282ns",
        volumes=176,
    )
    assert classify_from_header(header) == ("anat", "T2w")


@pytest.mark.parametrize("sequence_name", ["*spcir_282ns", "*fl3d1_16ns", "wibble2d1_9", ""])
def test_an_unrecognised_sequence_name_falls_through_to_the_name_pass(sequence_name):
    """Narrow keying is the contract: 'spcir' is SPACE-FLAIR, not a T2w, and a
    bare 'fl3d1' is a VIBE anatomical rather than a scout."""
    header = classic(
        mr_acquisition_type="3D",
        is_epi=False,
        image_type=("ORIGINAL", "PRIMARY", "M", "NORM"),
        sequence_name=sequence_name,
    )
    assert classify_from_header(header) == ("", "")


def test_the_sequence_tier_does_not_claim_an_undetermined_reference():
    """The other ordering guard, against anyone later adding epfid2d1 to the table.

    A 2D gradient-echo EPI whose volume count could not be settled returns early
    on purpose, so Siemens' own _SBRef suffix decides it in the name pass.
    """
    header = classic(single_volume=None, sequence_name="epfid2d1_116")
    assert classify_from_header(header) == ("", "")


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


# --- volume count vs file count --------------------------------------------
# `len(files) == 1` is a volume test only for a mosaic or an enhanced series.
# Every EPI series in the LCNI repository is mosaic (936x936 tiles of 104x104),
# which is why the file count held there — and why the gap was invisible.


def test_a_non_mosaic_reference_is_not_mistaken_for_a_bold_run(tmp_path):
    """One volume, one file per slice — the case the file count gets wrong.

    A site with mosaic disabled, or a GE/Philips classic export, writes 60 files
    for a single-volume reference. Counting files calls that a 60-volume BOLD.
    """
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_8_task_SBRef"
    _write_classic(
        directory,
        60,
        image_type=["ORIGINAL", "PRIMARY", "M", "ND"],  # no MOSAIC
        positions=[float(i) for i in range(60)],  # each slice visited once
    )
    header = read_series_header(directory)
    assert header.volumes == 60
    assert header.single_volume is True
    assert classify_from_header(header) == ("sbref", "")


def test_a_non_mosaic_time_series_is_a_bold_run(tmp_path):
    """Revisited slice positions mean more than one volume."""
    from duckbrain.core.dicom_header import read_series_header

    directory = tmp_path / "Series_9_task"
    _write_classic(
        directory,
        60,
        image_type=["ORIGINAL", "PRIMARY", "M", "ND"],
        positions=[float(i) for i in range(10)],  # 10 slices x 6 volumes
    )
    header = read_series_header(directory)
    assert header.single_volume is False
    assert classify_from_header(header) == ("func", "bold")


def test_a_mosaic_series_does_not_pay_for_the_position_scan(tmp_path):
    """One mosaic file is one whole volume, so the file count is exact."""
    from duckbrain.core.dicom_header import read_series_header

    _write_classic(tmp_path / "Series_9_food", 250)  # MOSAIC by default
    header = read_series_header(tmp_path / "Series_9_food")
    assert header.single_volume is False
    _write_classic(tmp_path / "Series_8_food_SBRef", 1)
    assert read_series_header(tmp_path / "Series_8_food_SBRef").single_volume is True


def test_an_undetermined_volume_count_defers_to_the_name(tmp_path):
    """Claiming 'bold' on an unknown count would convert a reference as a run."""
    from duckbrain.core.dicom_header import read_series_header
    from duckbrain.core.dicom_inspect import classify_series

    directory = tmp_path / "Series_8_task_SBRef"
    _write_classic(directory, 20, image_type=["ORIGINAL", "PRIMARY", "M", "ND"])
    header = read_series_header(directory)
    assert header.single_volume is None, "no ImagePositionPatient to settle it"
    assert classify_from_header(header) == ("", "")

    series = [
        SeriesInfo(
            series_number=8,
            description="task_SBRef",
            path=directory,
            file_count=20,
            header=header,
        )
    ]
    classify_series(series)
    assert series[0].classification == "sbref"
    assert series[0].classified_by == "name"


def test_acquisition_time_is_read_for_fieldmap_binding(tmp_path):
    from duckbrain.core.dicom_header import read_series_header

    _write_classic(tmp_path / "Series_7_fieldmap1", 4, acquisition_time="141550.020000")
    header = read_series_header(tmp_path / "Series_7_fieldmap1")
    assert header.series_time == pytest.approx(14 * 3600 + 15 * 60 + 50.02)
