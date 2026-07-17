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
    # group_name → extra BIDS entity that keeps multiple pairs from colliding on
    # the same ``dir-<X>`` filename, e.g. "run-1" (order) or "acq-encoding"
    # (named). Empty/absent means no extra entity (the single-pair case).
    group_entities: dict = field(default_factory=dict)


# Classification patterns, tried in order (first match wins). Definitive
# suffixes (_SBRef, _PhysioLog) come first so a functional run's single-band
# reference or physio log isn't swallowed by a broader token. 'scout'/'localizer'
# match only as whole words, so a *functional* localizer task like
# 'localizer_prf_run1' is NOT mistaken for the scanner localizer — it falls
# through and is recovered as func by SBRef pairing (see _recover_func_from_sbref).
_CLASSIFICATION_PATTERNS = [
    ("sbref", re.compile(r"_SBRef$", re.IGNORECASE)),
    ("physio", re.compile(r"(PhysioLog|physio)", re.IGNORECASE)),
    ("fmap", re.compile(r"(se_epi|SpinEchoFieldMap|SEfieldmap)", re.IGNORECASE)),
    ("anat", re.compile(r"(T1w|T1_|MPRAGE|T2w|T2_|SPC|FLAIR)", re.IGNORECASE)),
    ("scout", re.compile(r"(AAhead_scout|\bscout\b|\blocalizer\b)", re.IGNORECASE)),
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


_SBREF_SUFFIX = re.compile(r"_SBRef$", re.IGNORECASE)


def classify_series(series_list: list[SeriesInfo]) -> list[SeriesInfo]:
    """Classify each series as anat/func/fmap/sbref/physio/scout/unknown.

    A first pass classifies each series by its description alone. A second pass
    then treats the single-band reference as authoritative: a matching
    ``<name>_SBRef`` sibling means ``<name>`` is a functional run, so it is
    promoted to ``func`` even if the first pass guessed ``scout`` or ``anat``.
    This makes classification naming-agnostic and, in particular, rescues
    functional *localizer* tasks (e.g. MMM's ``localizer_prf_run1``, which the
    description pass would otherwise treat as a scanner localizer) and runs with
    study-specific names (e.g. DIVATTEN's ``div_perFace_perTone_r1``).

    Modifies series in-place and returns the list.
    """
    for s in series_list:
        s.classification = _classify_one(s.description)
    _recover_func_from_sbref(series_list)
    return series_list


# A matching SBRef sibling is definitive: whatever the description pass guessed,
# such a series is a functional run. Only these non-definitive guesses may be
# overridden — never sbref/physio/fmap, which the SBRef signal can't contradict.
_SBREF_PROMOTABLE = frozenset({"unknown", "scout", "anat"})


def _recover_func_from_sbref(series_list: list[SeriesInfo]) -> None:
    """Promote series with a matching SBRef sibling to 'func' (authoritative)."""
    sbref_bases = {
        _SBREF_SUFFIX.sub("", s.description).lower()
        for s in series_list
        if s.classification == "sbref"
    }
    if not sbref_bases:
        return
    for s in series_list:
        if s.classification in _SBREF_PROMOTABLE and s.description.lower() in sbref_bases:
            s.classification = "func"


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

    # Two grouping bases coexist. Fieldmaps whose description carries a group name
    # (``se_epi_ap_encoding`` → "encoding") are grouped by that name. Fieldmaps
    # with no name (plain ``se_epi_ap``/``se_epi_pa``) are grouped by *acquisition
    # order*: a session that reacquires a plain AP/PA pair (e.g. a topup pair
    # before and after the functionals) yields two distinct pairs, not one
    # collapsed group that spuriously reads as a "Duplicate AP".
    named_groups: dict[str, dict[str, int]] = {}
    unnamed: list[tuple[int, str]] = []  # (series_number, direction), acquisition order
    warnings: list[str] = []
    strategy = "series_number"

    for s in sorted(fmap_series, key=lambda s: s.series_number):
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

        group_name = _extract_fmap_group(desc_lower)
        if group_name:
            strategy = "series_description"
            slot = named_groups.setdefault(group_name, {})
            if direction in slot:
                # A named group naming the same direction twice is a genuine
                # config smell (unlike the unnamed reacquire case below).
                warnings.append(
                    f"Duplicate {direction.upper()} in group '{group_name}': "
                    f"Series {slot[direction]} and {s.series_number}"
                )
            slot[direction] = s.series_number
        else:
            unnamed.append((s.series_number, direction))

    groups: dict[str, dict[str, int]] = dict(named_groups)
    group_entities: dict[str, str] = {}

    unnamed_pairs = _pair_by_acquisition(unnamed)
    if len(unnamed_pairs) == 1 and not named_groups:
        # Sole unnamed pair keeps the historical empty-name group (no extra entity).
        groups[""] = unnamed_pairs[0]
    else:
        for i, pair in enumerate(unnamed_pairs, start=1):
            groups[str(i)] = pair
            group_entities[str(i)] = f"run-{i}"

    # When two or more pairs coexist they'd otherwise write the same
    # ``dir-<X>_epi`` filename; give each named pair an ``acq-`` label so the
    # converted fieldmaps stay distinct (unnamed pairs already carry ``run-``).
    if len(groups) >= 2:
        for name in groups:
            if name and name not in group_entities:
                group_entities[name] = f"acq-{_sanitize_task_label(name)}"

    # Validate groups have both AP and PA
    for gname, dirs in groups.items():
        if "ap" not in dirs:
            warnings.append(f"Group '{gname}' missing AP fieldmap")
        if "pa" not in dirs:
            warnings.append(f"Group '{gname}' missing PA fieldmap")

    if not groups:
        return FieldmapDetection(strategy="none", warnings=warnings)

    return FieldmapDetection(
        strategy=strategy, groups=groups, warnings=warnings, group_entities=group_entities
    )


def _pair_by_acquisition(directed: list[tuple[int, str]]) -> list[dict[str, int]]:
    """Pair a series of (series_number, direction) fieldmaps by acquisition order.

    Walks in order, filling one ``{"ap": n, "pa": m}`` pair at a time; seeing a
    direction the current pair already holds starts a new pair. So an interleaved
    ``AP, PA, AP, PA`` acquisition becomes two complete pairs.
    """
    pairs: list[dict[str, int]] = []
    current: dict[str, int] = {}
    for series_number, direction in directed:
        if direction in current:
            pairs.append(current)
            current = {}
        current[direction] = series_number
    if current:
        pairs.append(current)
    return pairs


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


# Trailing run token, e.g. "_r1", "_run-2", "_run03"
_RUN_SUFFIX = re.compile(r"[_-](?:run|r)[-_]?(\d+)$", re.IGNORECASE)
# Scan-type noise stripped from a description when there is no explicit task-<x>
_TASK_NOISE = [
    re.compile(r"cmrr_mbep2d_bold", re.IGNORECASE),
    re.compile(r"mbep2d", re.IGNORECASE),
    re.compile(r"^bold[_-]?", re.IGNORECASE),
    re.compile(r"[_-]?bold$", re.IGNORECASE),
    re.compile(r"[_-]?sbref$", re.IGNORECASE),
]


def _sanitize_task_label(raw: str) -> str:
    """Reduce an arbitrary string to a BIDS-valid task label (alphanumeric).

    Splits on non-alphanumeric separators and camelCases the pieces, preserving
    interior capitalization: 'div_retScene_perTone' → 'divRetScenePerTone',
    'encoding' → 'encoding'.
    """
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", raw) if p]
    if not parts:
        return "unknown"
    label = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    label = re.sub(r"[^A-Za-z0-9]", "", label)
    return label or "unknown"


def sanitize_task_label(raw: str) -> str:
    """Public wrapper for :func:`_sanitize_task_label`.

    A BIDS entity value must be alphanumeric — an underscore, space, or hyphen in
    a task label would break the filename (``task-resting_test`` parses as
    ``task-resting`` plus an orphan ``test`` token). The naming heuristic already
    routes its output through this, but a *user-entered* task label (a mapping
    table edit or a hand-written project rule) does not — so consumers that build
    BIDS entities from any task label (heuristic or human) must sanitize here.
    """
    return _sanitize_task_label(raw)


def compile_naming_template(template: str) -> re.Pattern:
    """Compile a glob-like naming template into a regex with named groups.

    The template uses ``{task}`` and ``{run}`` placeholders; everything else is
    matched literally. E.g. ``"{task}_r{run}"`` or ``"{task}_run-{run}"``.
    """
    parts = re.split(r"\{(task|run)\}", template)
    pattern = ""
    for i, part in enumerate(parts):
        if i % 2 == 0:
            pattern += re.escape(part)
        elif part == "task":
            pattern += r"(?P<task>.+?)"
        else:
            pattern += r"(?P<run>\d+)"
    return re.compile(pattern)


def parse_task_run(
    description: str, template: str | re.Pattern | None = None
) -> tuple[str, int | None]:
    """Parse a series description into (task_label, run_index).

    A study-specific ``template`` (glob-like ``{task}``/``{run}``, or a compiled
    pattern) is tried first; if it doesn't match, a naming-agnostic heuristic
    runs: strip a trailing run token, prefer an explicit ``task-<label>``, else
    treat the remaining description (minus scan-type noise) as the task. The run
    index is ``None`` when the name carries no run token — callers derive it by
    counting repeats (see :func:`duckbrain.core.dcm2bids_config.build_task_run_mapping`).
    """
    if template is not None:
        pat = template if isinstance(template, re.Pattern) else compile_naming_template(template)
        m = pat.fullmatch(description)
        if m:
            gd = m.groupdict()
            task = _sanitize_task_label(gd.get("task", "") or "")
            run = int(gd["run"]) if gd.get("run") else None
            return task, run

    core = description
    run: int | None = None
    m = _RUN_SUFFIX.search(core)
    if m:
        run = int(m.group(1))
        core = core[: m.start()]

    task_match = re.search(r"task[_-]([A-Za-z0-9]+)", core, re.IGNORECASE)
    if task_match:
        task_raw = task_match.group(1)
    else:
        task_raw = core
        for noise in _TASK_NOISE:
            task_raw = noise.sub("", task_raw)

    return _sanitize_task_label(task_raw), run


def extract_task_label(description: str, template: str | re.Pattern | None = None) -> str:
    """Extract just the BIDS task label from a series description.

    Thin wrapper over :func:`parse_task_run`; kept for callers that only need
    the task. E.g. 'cmrr_mbep2d_bold_task-encoding_run-1' → 'encoding',
    'div_retScene_perTone_r1' → 'divRetScenePerTone'.
    """
    return parse_task_run(description, template)[0]
