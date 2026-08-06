"""Read the few DICOM header fields that actually determine a series' datatype.

Classification used to run entirely on the string after ``Series_NN_`` in a
directory name. That is the console operator's free text, and across the LCNI
repository (`/projects/lcni/dcm/repository`, 15 studies) it carries no reliable
signal at all: `food`, `Whack`, `Resting1`, `WMS_R1`, `Animal`, `StartFMRI` and
`EPI196` are all ordinary BOLD runs, and nothing in those names says so. Sites
are under no obligation to name a sequence after what it is.

The header does say. Measured over the corpus, ``ImageType`` alone separates the
converted classes with 1.90 bits of information gain (86% purity), and
``ImageType`` + ``MRAcquisitionType`` + is-EPI + is-spin-echo + volume count is a
100%-pure joint key over all 359 series the LCNI curator converted.

**Two dialects, and this is the part that bites.** 36% of the corpus is
enhanced-MR (Siemens ``syngo MR XA30``), where ``ScanningSequence``,
``SequenceName``, ``EchoNumbers``, ``EchoTime``, ``RepetitionTime`` and
``FlipAngle`` are *absent at the top level* — they live inside
``SharedFunctionalGroupsSequence``, and the EPI flag moves to
``EchoPlanarPulseSequence``. A rule keyed on ``ScanningSequence`` doesn't
misfire on those series, it silently sees nothing. Everything here normalises
across both, and :attr:`SeriesHeader.dialect` records which one was read.

Only ``ImageType``, ``Modality``, ``MRAcquisitionType`` and the file count are
strong in both dialects; the rest is reconstructed per-dialect below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pydicom is imported inside the functions that parse (see _read_one)
    from pydicom import Dataset

# ImageType tokens that mark a series as never-source-data. 'MPR' is the scout
# reformat (390 series in the corpus), 'CSA REPORT' the Phoenix report, and the
# TTEST/DESIGN/GLM/MEAN family the scanner's inline evaluation.
_DERIVED_TOKENS = frozenset(
    {
        "MPR",
        "CSA REPORT",
        "PHYSIO",
        "RAWDATA",
        "DUMMY IMAGE",
        "TTEST",
        "DESIGN",
        "GLM",
        "MEAN",
        "MOCO",
        "ADC",
        "TRACEW",
        "FA",
        "PROJECTION IMAGE",
    }
)

_DIFFUSION_TOKENS = frozenset({"DIFFUSION"})


@dataclass(frozen=True)
class SeriesHeader:
    """The header evidence a classifier needs, normalised across MR dialects."""

    modality: str = ""
    image_type: tuple[str, ...] = ()
    mr_acquisition_type: str = ""  # "2D", "3D", or "" when absent
    is_epi: bool | None = None
    is_spin_echo: bool | None = None
    echo_numbers: tuple[int, ...] = ()
    protocol_name: str = ""
    series_description: str = ""
    # PulseSequenceName (enhanced) else SequenceName (classic) — the two are
    # strictly complementary across the corpus, so one merged read covers both
    # dialects. This is the console's name for the pulse sequence, not the
    # operator's name for the series, so it says what was *run*.
    sequence_name: str = ""
    dialect: str = ""  # "classic" | "enhanced"
    volumes: int = 0  # best-effort volume count; see single_volume for the exact test
    # Whether this series is a single volume. ``None`` when it could not be
    # determined, which callers must not read as "no". Kept separate from
    # ``volumes`` because the file count is only a volume count under conditions
    # that have to be checked — see _single_volume.
    single_volume: bool | None = None
    # Seconds since midnight, from AcquisitionTime (else SeriesTime). Standard in
    # both dialects and every vendor, which is why fieldmap binding uses it.
    series_time: float | None = None
    unreadable: bool = False

    @property
    def is_derived(self) -> bool:
        """A scanner-produced reformat, report or statistic — never source data."""
        if self.modality and self.modality != "MR":
            return True
        if _DERIVED_TOKENS & set(self.image_type):
            return True
        # DERIVED\PRIMARY is the scanner's own reconstruction of another series.
        # DERIVED\SECONDARY is *not* the same thing and must not be caught here:
        # defacing rewrites a perfectly good T1w as secondary capture, and every
        # one of the 112 anatomicals in the corpus is DERIVED\SECONDARY.
        return tuple(self.image_type[:2]) == ("DERIVED", "PRIMARY")

    @property
    def is_diffusion(self) -> bool:
        return bool(_DIFFUSION_TOKENS & set(self.image_type))

    @property
    def is_phase(self) -> bool:
        """Phase image — the 'P' of a gradient-echo fieldmap's magnitude/phase pair."""
        return "P" in self.image_type


# `Any`, not `object`, for the raw tag values below: each of these three
# helpers exists to absorb whatever pydicom put in the element — a str, a
# MultiValue, an int, or nothing — and each guards with its own
# try/except. Typing them `object` would make the guard itself unwritable.
def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return (str(value),)


def _first(sequence: Any, attr: str) -> Any:
    """Dig one level into a DICOM sequence, tolerating absence at every step."""
    if not sequence:
        return None
    try:
        return getattr(sequence[0], attr, None)
    except (IndexError, TypeError):
        return None


def _shared_group(dataset: Dataset, sequence_name: str, attr: str) -> Any:
    """Read ``SharedFunctionalGroupsSequence[0].<sequence_name>[0].<attr>``."""
    shared = getattr(dataset, "SharedFunctionalGroupsSequence", None)
    if not shared:
        return None
    try:
        inner = getattr(shared[0], sequence_name, None)
    except (IndexError, TypeError):
        return None
    return _first(inner, attr)


def _read_one(path: Path) -> Dataset | None:
    """Parse one file, or return None if it isn't a DICOM we can use.

    ``force=True`` is needed because some exports omit the 128-byte preamble,
    but it also means pydicom will happily parse a text file into an *empty*
    Dataset rather than raising. An empty parse is indistinguishable from a
    DICOM with no useful tags, so require a minimum of identifying content —
    otherwise a stray README in a series directory reads as a valid header that
    says nothing, and silently outvotes the name heuristics.
    """
    import pydicom

    try:
        dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception:  # an unreadable file is a finding, not a crash
        return None
    if not any(hasattr(dataset, tag) for tag in ("SOPClassUID", "Modality", "ImageType")):
        return None
    return dataset


def _dicom_time(dataset: Dataset) -> float | None:
    """DICOM ``HHMMSS.FFFFFF`` as seconds since midnight."""
    for attr in ("AcquisitionTime", "SeriesTime"):
        raw = str(getattr(dataset, attr, "") or "").strip()
        if len(raw) < 6:
            continue
        try:
            return int(raw[0:2]) * 3600 + int(raw[2:4]) * 60 + float(raw[4:])
        except ValueError:
            continue
    return None


# How many files to inspect when counting distinct slice positions. A repeated
# position appears within one slice-group of the start under either DICOM
# ordering (slice-major repeats immediately, time-major after n_slices), so this
# only has to exceed a plausible slice count — not the series length.
_POSITION_SCAN_LIMIT = 192


def _single_volume(files: list[Path], image_type: tuple[str, ...], enhanced: bool) -> bool | None:
    """Is this series one volume? The question that separates an SBRef from a BOLD.

    ``len(files) == 1`` is *not* the general answer, and treating it as one is a
    real trap. It holds for a Siemens mosaic (the whole volume is tiled into one
    image) and for the enhanced-MR series in the LCNI repository (one file per
    volume) — but a site with mosaic disabled, or a GE/Philips classic export,
    writes one file *per slice*. A single-volume reference then arrives as 60
    files and reads as a BOLD run, silently.

    So: trust the file count only where it is a volume count, and otherwise
    settle it by looking at the slice positions. A single volume visits each
    position once; a time series revisits them. Returns ``None`` when neither
    test applies, which the caller must not read as "no".
    """
    if not files:
        return None
    if "MOSAIC" in image_type or enhanced:
        return len(files) == 1
    if len(files) == 1:
        return True

    import pydicom

    seen: set[tuple] = set()
    for path in files[:_POSITION_SCAN_LIMIT]:
        try:
            ds = pydicom.dcmread(
                str(path),
                stop_before_pixels=True,
                force=True,
                specific_tags=["ImagePositionPatient"],
            )
        except Exception:
            return None
        position = getattr(ds, "ImagePositionPatient", None)
        if position is None:
            return None
        key = tuple(round(float(v), 3) for v in position)
        if key in seen:
            return False  # a revisited slice position means more than one volume
        seen.add(key)
    # Every position distinct across everything we looked at. Only conclusive if
    # that was the whole series; otherwise we genuinely do not know.
    return True if len(files) <= _POSITION_SCAN_LIMIT else None


def _dicom_files(series_dir: Path) -> list[Path]:
    try:
        entries = sorted(p for p in series_dir.iterdir() if p.is_file())
    except OSError:
        return []
    return entries


def read_series_header(series_dir: str | Path) -> SeriesHeader | None:
    """Read normalised header evidence for one ``Series_NN_<desc>/`` directory.

    Returns ``None`` when the directory holds no readable DICOM, which callers
    must treat as "fall back to the name" rather than "nothing here". An
    *empty* series directory is a real occurrence — 6 of the corpus's 1384
    (0.43%) are empty, and a name-only converter reports having found the T1w
    and then produces no file.
    """
    series_dir = Path(series_dir)
    files = _dicom_files(series_dir)
    if not files:
        return None

    # First, middle and last: enough to see a second echo without reading a
    # 900-file BOLD run.
    probe_indices = {0, len(files) // 2, len(files) - 1}
    datasets = [ds for ds in (_read_one(files[i]) for i in sorted(probe_indices)) if ds is not None]
    if not datasets:
        return SeriesHeader(volumes=len(files), unreadable=True)

    head = datasets[0]
    sop = str(getattr(head, "SOPClassUID", "") or "")
    enhanced = sop.endswith(".1.1.4.1") or hasattr(head, "SharedFunctionalGroupsSequence")

    echo_numbers = set()
    for ds in datasets:
        value = getattr(ds, "EchoNumbers", None)
        for item in _as_tuple(value):
            try:
                echo_numbers.add(int(item))
            except (TypeError, ValueError):
                continue

    # XA30 renamed the tag rather than moving it into a functional group, and no
    # series carries both, so one merged read serves both dialects.
    sequence_name = str(
        getattr(head, "PulseSequenceName", "") or getattr(head, "SequenceName", "") or ""
    )

    if enhanced:
        epi_flag = getattr(head, "EchoPlanarPulseSequence", None)
        is_epi = None if epi_flag is None else str(epi_flag).upper() == "YES"
        # A spin-echo readout drives a refocusing train; a gradient-echo one does
        # not. EchoPulseSequenceType is NOT usable here — XA reports 'GRADIENT'
        # for the spin-echo pepolar fieldmaps (16/16 in the corpus).
        train = _shared_group(head, "MRTimingAndRelatedParametersSequence", "RFEchoTrainLength")
        is_spin_echo = None if train is None else int(train) >= 1
        dialect = "enhanced"
    else:
        scanning = {s.upper() for s in _as_tuple(getattr(head, "ScanningSequence", None))}
        is_epi = ("EP" in scanning) if scanning else None
        # Two witnesses, and neither subsumes the other — measured on the corpus:
        # the pepolar spin-echo EPI ('epse2d1_104') reports ScanningSequence
        # ('EP',) with no 'SE' in it, so only the name sees it; the turbo spin
        # echo ('*tse2d1_18') reports ('SE',) and its name doesn't start 'epse',
        # so only ScanningSequence sees it. Every gradient-echo family is false
        # under both: epfid2d1 ('EP',), fl3d1 ('GR',), tfl3d1 ('GR','IR'),
        # fm2d2r ('GR',), ep_b0 ('EP',).
        if sequence_name or scanning:
            is_spin_echo = sequence_name.lower().startswith("epse") or "SE" in scanning
        else:
            is_spin_echo = None
        dialect = "classic"

    image_type = tuple(t.upper() for t in _as_tuple(getattr(head, "ImageType", None)))
    mr_acquisition_type = str(getattr(head, "MRAcquisitionType", "") or "")

    # The volume count separates a single-band reference from its BOLD, which is
    # the *only* thing it decides — and settling it can cost a per-slice position
    # scan (see _single_volume). So compute it only where it could matter: a 2D
    # gradient-echo EPI. An anat or a fieldmap is never an SBRef, and running the
    # scan over its 176 files would be pure waste.
    could_be_reference = (
        mr_acquisition_type.upper() == "2D" and is_epi is True and is_spin_echo is False
    )
    single_volume = _single_volume(files, image_type, enhanced) if could_be_reference else None

    return SeriesHeader(
        modality=str(getattr(head, "Modality", "") or ""),
        image_type=image_type,
        mr_acquisition_type=mr_acquisition_type,
        is_epi=is_epi,
        is_spin_echo=is_spin_echo,
        echo_numbers=tuple(sorted(echo_numbers)),
        protocol_name=str(getattr(head, "ProtocolName", "") or ""),
        series_description=str(getattr(head, "SeriesDescription", "") or ""),
        sequence_name=sequence_name,
        dialect=dialect,
        volumes=len(files),
        single_volume=single_volume,
        series_time=_dicom_time(head),
    )


# --- classification from header evidence ------------------------------------
#
# Ordered, first match wins. Measured against the LCNI curator's own choices:
# 359/359 converted series get the right datatype, with no cross-class
# confusion. Returns ``("", "")`` when the header is not decisive, which hands
# the series back to the name heuristics rather than guessing.


def classify_from_header(header: SeriesHeader) -> tuple[str, str]:
    """Return ``(classification, suffix_hint)`` implied by the header.

    ``suffix_hint`` is the BIDS suffix when the header pins it (``T1w``,
    ``phasediff``, …) and ``""`` when it only pins the datatype.
    """
    if header is None or header.unreadable:
        return "", ""
    if header.modality and header.modality != "MR":
        return "derived", ""
    if header.is_derived:
        return "derived", ""
    if header.is_diffusion:
        return "dwi", ""

    acquisition = header.mr_acquisition_type.upper()

    if acquisition == "2D" and header.is_epi:
        if header.is_spin_echo:
            # A spin-echo EPI acquired as a handful of volumes is the pepolar
            # fieldmap; the BOLD runs beside it are gradient-echo.
            return "fmap", "epi"
        # Nothing in the header distinguishes a single-band reference from its
        # parent BOLD — same ImageType, TR, flip angle and sequence. Being one
        # volume is the only separator, and it is exact: 34/34 sbref are one
        # volume, 130/130 bold are more. Note this asks single_volume rather
        # than `volumes == 1`: the file count is a volume count only for a
        # mosaic or an enhanced series, and a non-mosaic reference arrives as
        # one file per slice.
        if header.single_volume:
            return "sbref", ""
        if header.single_volume is None:
            # Undetermined. Claiming "bold" here would silently convert a
            # reference as a run, so leave it to the name pass, where Siemens'
            # own _SBRef suffix settles it.
            return "", ""
        return "func", "bold"

    if acquisition == "2D" and header.is_epi is False and header.is_spin_echo is False:
        # Gradient echo, not EPI: the classic Siemens gre_field_mapping, which
        # arrives as two consecutive series — magnitude (two echoes) then phase.
        if header.is_phase:
            return "fmap", "phasediff"
        if len(header.echo_numbers) > 1:
            return "fmap", "magnitude"

    if acquisition == "3D":
        # The vNav navigator setter and the scout are both 3D and ORIGINAL; a
        # real anatomical in this corpus is DERIVED\SECONDARY because defacing
        # rewrote it. That is an artefact of *this* archive, so it can promote a
        # series to anat but never demote one — an undefaced T1w is ORIGINAL and
        # must still reach the name heuristics rather than be dropped here.
        if tuple(header.image_type[:2]) == ("DERIVED", "SECONDARY"):
            return "anat", ""
        # Falls through to the sequence-name tier rather than returning here: an
        # undefaced 3D series is where the scout and the SPACE both live, and the
        # tier is the only evidence that separates them.

    if acquisition == "2D" and header.is_spin_echo and not header.is_epi:
        # Turbo/fast spin echo — the T2w in this corpus (TR 11–15 s, FA 150°).
        # Reached in both dialects: enhanced via RFEchoTrainLength, classic via
        # ScanningSequence 'SE'. The classic half was unreachable until the
        # is_spin_echo union above, because a '*tse2d1_18' name doesn't start
        # 'epse' — those series only classified because their *name* said 't2'.
        return "anat", "T2w"

    return _classify_from_sequence_name(header)


# What the console called the pulse sequence, for the two classes nothing else
# reaches. Deliberately small: every other family LCNI documents is already
# decided above, and a second path could only disagree with a validated one.
_SEQUENCE_CLASSES = {
    # 3D FLASH non-selective — the AAHScout. Keyed on the full 'fl3d1_ns' token
    # and not the bare 'fl3d1' family, because plain 3D FLASH (a VIBE) is a real
    # anatomical elsewhere and must keep falling through.
    "fl3d1_ns": ("scout", ""),
    # SPACE. Matched exactly, not as a 'spc' prefix: 'spcir' is SPACE-FLAIR and
    # would be mislabelled T2w, and there is no local data to validate a FLAIR
    # rule against.
    "spcr": ("anat", "T2w"),
}


def _classify_from_sequence_name(header: SeriesHeader) -> tuple[str, str]:
    """Last tier — corroborates where nothing else decided, never overrules.

    Three properties keep this safe, and they are properties of *where* it is
    called rather than of the table:

    * It runs after ``is_derived``, so a scout's MPR reformat is already
      ``derived`` and never reaches the scout rule. That is what makes the
      ``fl3d1`` family usable at all — half of it is those reformats.
    * It cannot reach the deliberate ``("", "")`` returned for an SBRef whose
      volume count is undetermined, which is an explicit early return. That
      deferral exists so Siemens' own ``_SBRef`` suffix settles it in the name
      pass.
    * An unrecognised sequence name returns ``("", "")`` and the series lands in
      the name heuristics exactly as before.

    Siemens prefixes the non-EPI families with ``*`` (``*fl3d1_ns``,
    ``*tfl3d1_16ns``, ``*fm2d2r``, ``*tse2d1_18``) and the EPI ones with nothing
    (``epfid2d1_104``, ``epse2d1_104``, ``ep_b0``), so the asterisk carries no
    signal here and is stripped before matching.
    """
    raw = header.sequence_name.lstrip("*").lower()
    for token, verdict in _SEQUENCE_CLASSES.items():
        if raw == token or raw.startswith(f"{token}_"):
            return verdict
    return "", ""
