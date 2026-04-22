"""DICOM series inspection — enumerate, classify, and detect fieldmaps."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SeriesInfo:
    """Metadata for one DICOM series directory."""

    series_number: int
    description: str
    path: Path
    file_count: int = 0
    classification: str = ""  # anat, func, fmap, sbref, physio, scout, unknown


@dataclass
class FieldmapDetection:
    """Result of fieldmap detection."""

    strategy: str  # "series_description", "series_number", "none"
    groups: dict = field(default_factory=dict)  # group_name → {"ap": num, "pa": num}
    warnings: list[str] = field(default_factory=list)


# Classification patterns
_CLASSIFICATION_PATTERNS = [
    ("scout", re.compile(r"(AAhead_scout|localizer|scout)", re.IGNORECASE)),
    ("physio", re.compile(r"(PhysioLog|physio)", re.IGNORECASE)),
    ("sbref", re.compile(r"_SBRef$", re.IGNORECASE)),
    ("fmap", re.compile(r"(se_epi|SpinEchoFieldMap|SEfieldmap)", re.IGNORECASE)),
    ("anat", re.compile(r"(T1w|T1_|MPRAGE|T2w|T2_|SPC|FLAIR)", re.IGNORECASE)),
    ("func", re.compile(r"(bold|task-|cmrr_mbep2d)", re.IGNORECASE)),
]


def list_series(dicom_session_dir: str | Path) -> list[SeriesInfo]:
    """Enumerate all Series_NN_description/ dirs in a DICOM session.

    Parameters
    ----------
    dicom_session_dir : path
        Path to a single session's DICOM directory.

    Returns
    -------
    list[SeriesInfo]
        Sorted by series number.
    """
    dicom_session_dir = Path(dicom_session_dir)
    series = []

    for entry in sorted(dicom_session_dir.iterdir()):
        if not entry.is_dir():
            continue

        match = re.match(r"^Series_(\d+)_(.*)$", entry.name)
        if not match:
            continue

        series_num = int(match.group(1))
        description = match.group(2)

        # Count DICOM files
        file_count = sum(1 for f in entry.iterdir() if f.is_file())

        info = SeriesInfo(
            series_number=series_num,
            description=description,
            path=entry,
            file_count=file_count,
        )
        series.append(info)

    return sorted(series, key=lambda s: s.series_number)


def classify_series(series_list: list[SeriesInfo]) -> list[SeriesInfo]:
    """Classify each series as anat/func/fmap/sbref/physio/scout/unknown.

    Modifies series in-place and returns the list.
    """
    for s in series_list:
        s.classification = _classify_one(s.description)
    return series_list


def _classify_one(description: str) -> str:
    """Classify a single series description."""
    for label, pattern in _CLASSIFICATION_PATTERNS:
        if pattern.search(description):
            return label
    return "unknown"


def detect_fieldmaps(series_list: list[SeriesInfo]) -> FieldmapDetection:
    """Find SE-EPI AP/PA fieldmap pairs.

    Looks for pairs of series with complementary phase encoding directions
    indicated by '_AP' / '_PA' suffixes or 'se_epi_ap' / 'se_epi_pa' patterns.

    Parameters
    ----------
    series_list : list[SeriesInfo]
        All series in a session.

    Returns
    -------
    FieldmapDetection
        Detected fieldmap strategy, groups, and any warnings.
    """
    fmap_series = [
        s for s in series_list if s.classification == "fmap" or _is_fieldmap(s.description)
    ]

    if not fmap_series:
        return FieldmapDetection(strategy="none")

    # Try description-based grouping (e.g., se_epi_ap_encoding, se_epi_pa_encoding)
    groups: dict[str, dict[str, int]] = {}
    warnings: list[str] = []
    strategy = "series_number"

    for s in fmap_series:
        desc_lower = s.description.lower()

        # Extract direction (AP/PA)
        direction = None
        if "_ap" in desc_lower or "accel_ap" in desc_lower:
            direction = "ap"
        elif "_pa" in desc_lower or "accel_pa" in desc_lower:
            direction = "pa"

        if direction is None:
            warnings.append(f"Cannot determine direction for Series_{s.series_number}_{s.description}")
            continue

        # Extract group name from description suffix
        group_name = _extract_fmap_group(desc_lower)
        if group_name:
            strategy = "series_description"

        if group_name not in groups:
            groups[group_name] = {}
        if direction in groups[group_name]:
            warnings.append(
                f"Duplicate {direction.upper()} in group '{group_name}': "
                f"Series {groups[group_name][direction]} and {s.series_number}"
            )
        groups[group_name][direction] = s.series_number

    # Validate groups have both AP and PA
    for gname, dirs in groups.items():
        if "ap" not in dirs:
            warnings.append(f"Group '{gname}' missing AP fieldmap")
        if "pa" not in dirs:
            warnings.append(f"Group '{gname}' missing PA fieldmap")

    if not groups:
        return FieldmapDetection(strategy="none", warnings=warnings)

    return FieldmapDetection(strategy=strategy, groups=groups, warnings=warnings)


def _is_fieldmap(description: str) -> bool:
    """Check if a description looks like a fieldmap."""
    desc = description.lower()
    return bool(
        re.search(r"se_epi|spinecho.*field|sefieldmap", desc)
        and not desc.endswith("_sbref")
    )


def _extract_fmap_group(desc_lower: str) -> str:
    """Extract a group name from fieldmap description.

    E.g., 'se_epi_ap_encoding' → 'encoding'
          'se_epi_pa_retrieval' → 'retrieval'
          'se_epi_ap' → '' (unnamed group)
    """
    # Remove direction suffix first
    cleaned = re.sub(r"_?(ap|pa)", "", desc_lower)
    # Remove common prefixes
    cleaned = re.sub(r"^(se_epi|spinecho|sefieldmap)_?", "", cleaned)
    cleaned = cleaned.strip("_ ")
    return cleaned


def get_bold_series(series_list: list[SeriesInfo], min_volumes: int = 20) -> list[SeriesInfo]:
    """Filter to just BOLD functional series, excluding low-volume (likely aborted) runs.

    Parameters
    ----------
    series_list : list[SeriesInfo]
        Classified series.
    min_volumes : int
        Minimum number of files to consider a series complete.

    Returns
    -------
    list[SeriesInfo]
        BOLD series with sufficient volumes.
    """
    return [
        s
        for s in series_list
        if s.classification == "func"
        and s.file_count >= min_volumes
        and not s.description.lower().endswith("_sbref")
    ]


def extract_task_label(description: str) -> str:
    """Extract a BIDS-compatible task label from a series description.

    E.g., 'cmrr_mbep2d_bold_task-encoding_run-1' → 'encoding'
          'task_rest_bold' → 'rest'
          'bold_encoding' → 'encoding'
    """
    # Look for explicit task-<label> pattern
    match = re.search(r"task[_-](\w+)", description, re.IGNORECASE)
    if match:
        label = match.group(1)
        # Strip trailing _run-N, _bold, etc.
        label = re.sub(r"_(run|bold|sbref).*", "", label, flags=re.IGNORECASE)
        return label.lower()

    # Remove common prefixes/suffixes and use what's left
    cleaned = description.lower()
    for pattern in [
        r"cmrr_mbep2d_bold_?",
        r"_bold$",
        r"_run[_-]?\d+",
        r"_sbref$",
    ]:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = cleaned.strip("_")

    return cleaned if cleaned else "unknown"
