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


# --- ReproIn ---------------------------------------------------------------
# ReproIn (https://github.com/ReproNim/reproin) is a convention for naming
# sequences *at the scanner console* so the BIDS entities are carried explicitly
# rather than reconstructed downstream:
#
#     <seqtype[-label]>[_ses-<id>][_task-<id>][_acq-<label>][_run-<n>][_dir-<dir>][__<free text>]
#     e.g. func-bold_ses-pre_task-faces_acq-1mm_run-01_dir-AP
#
# duckbrain converts with dcm2bids, not heudiconv, so the ReproIn *heuristic* is
# not used — only the naming convention is recognized. Everywhere the two could
# disagree, the explicit entity wins over the inferring heuristic: that is the
# entire point of the convention, and the heuristics exist only to recover what a
# console operator didn't record (see TODO #5).
#
# The trailing ``__<free text>`` is console-only cruft by design and is dropped.
_REPROIN_SEQTYPES = {"anat": "anat", "func": "func", "fmap": "fmap", "dwi": "dwi"}
_REPROIN_SEQTYPE_RE = re.compile(r"^(anat|func|fmap|dwi)(?:-[A-Za-z0-9]+)?(?=_|$)", re.IGNORECASE)
# A BIDS key-value entity anywhere in the name, e.g. "_run-01", "_acq-1mm".
_REPROIN_ENTITY_RE = re.compile(r"[_-](ses|task|acq|run|dir)-([A-Za-z0-9.]+)", re.IGNORECASE)


def is_reproin_name(description: str) -> bool:
    """True when a series description follows the ReproIn console convention."""
    return _REPROIN_SEQTYPE_RE.match(_strip_reproin_custom(description)) is not None


def _strip_reproin_custom(description: str) -> str:
    """Drop ReproIn's ``__<free text>`` tail — console-only, never BIDS."""
    return description.split("__", 1)[0]


def reproin_entities(description: str) -> dict[str, str]:
    """Parse the BIDS entities a ReproIn sequence name carries.

    Returns ``{}`` for a name that isn't ReproIn-formed, so callers can use a
    truthy check to decide between the explicit and the inferred path.
    """
    core = _strip_reproin_custom(description)
    m = _REPROIN_SEQTYPE_RE.match(core)
    if m is None:
        return {}
    label = core[: m.end()].partition("-")[2]
    found = _REPROIN_ENTITY_RE.findall(core[m.end() :])
    # The seqtype alone is not enough to claim a name is ReproIn — a legacy
    # description can open with one of those words by coincidence
    # (``func_run1``, ``anat_scan``). Require the convention to show itself:
    # either a ``-<label>`` on the seqtype or at least one ``key-value`` entity.
    if not label and not found:
        return {}
    entities = {"seqtype": m.group(1).lower()}
    if label:
        entities["suffix"] = label
    for key, value in found:
        entities[key.lower()] = value
    return entities


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
    """Classify a single series description.

    A ReproIn seqtype is decisive and checked first — it *states* the datatype,
    where every pattern below only guesses one from vocabulary. The `_SBRef`
    suffix still wins over it, because Siemens appends that to the console
    protocol name, so a ReproIn bold and its reference share a seqtype.
    """
    if _CLASSIFICATION_PATTERNS[0][1].search(description):
        return "sbref"
    seqtype = reproin_entities(description).get("seqtype")
    if seqtype:
        return _REPROIN_SEQTYPES[seqtype]
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

    # Fieldmaps are bucketed by group name — the label a description carries
    # (``se_epi_ap_encoding`` → "encoding"), or "" for a plain
    # ``se_epi_ap``/``se_epi_pa`` — and then paired by *acquisition order* within
    # each bucket. Reacquisition is the norm in both buckets: a session may shoot
    # a topup pair before and after the functionals (unnamed), or reshoot
    # ``se_epi_ap_encoding`` between task blocks (named). Either way each
    # AP-then-PA sweep is its own pair, never a collapsed group that reads as a
    # spurious "Duplicate AP" while quietly discarding all but the last pair.
    # (That discard was real: MMM_005_sess19 in /projects/lcni/dcm/hulacon/mmmdata
    # has three ``encoding`` pairs and kept one.)
    by_name: dict[str, list[tuple[int, str]]] = {}
    # Explicit ``run-`` per fieldmap, when the console recorded one (ReproIn).
    explicit_runs: dict[str, dict[int, int]] = {}
    warnings: list[str] = []
    strategy = "series_number"

    for s in sorted(fmap_series, key=lambda s: s.series_number):
        desc_lower = s.description.lower()
        reproin = reproin_entities(s.description)

        # Extract direction (AP/PA). ReproIn states it as a ``dir-`` entity;
        # otherwise fall back to the bare suffix conventions.
        direction = None
        if reproin.get("dir"):
            direction = reproin["dir"].lower()
        elif "_ap" in desc_lower or "accel_ap" in desc_lower:
            direction = "ap"
        elif "_pa" in desc_lower or "accel_pa" in desc_lower:
            direction = "pa"

        if direction not in ("ap", "pa"):
            warnings.append(
                f"Cannot determine direction for Series_{s.series_number}_{s.description}"
            )
            continue

        if reproin:
            # ``acq-`` is the group; ``run-`` distinguishes repeats of it.
            strategy = "series_description"
            group_name = reproin.get("acq", "")
            if reproin.get("run"):
                explicit_runs.setdefault(group_name, {})[s.series_number] = int(reproin["run"])
        else:
            group_name = _extract_fmap_group(desc_lower)
            if group_name:
                strategy = "series_description"
        by_name.setdefault(group_name, []).append((s.series_number, direction))

    paired = {
        name: _pair_fieldmaps(items, explicit_runs.get(name, {})) for name, items in by_name.items()
    }
    total_pairs = sum(len(p) for p in paired.values())

    groups: dict[str, dict[str, int]] = {}
    group_entities: dict[str, str] = {}

    for name, pairs in paired.items():
        for position, (label, pair) in enumerate(pairs, start=1):
            # Keys stay unique across repeats of one name: "encoding",
            # "encoding-2", … The base name is what task→group matching reads
            # back (see _assign_fmap_group), so the suffix must be strippable.
            key = name if position == 1 else f"{name}-{label}"
            if not name:
                # Unnamed pairs are keyed by run label, except a sole pair,
                # which keeps the historical empty-name group.
                key = "" if total_pairs == 1 else str(label)
            groups[key] = pair
            if total_pairs == 1:
                # Sole pair keeps the historical bare ``dir-<X>_epi`` filename.
                continue
            # Two or more pairs would otherwise write the same ``dir-<X>_epi``
            # name, so each gets a distinguishing entity: ``acq-`` from the group
            # label, ``run-`` for the repeat index.
            entity = f"acq-{_sanitize_task_label(name)}" if name else ""
            if len(pairs) > 1 or not name:
                entity = f"{entity}_run-{label}" if entity else f"run-{label}"
            group_entities[key] = entity

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


def _pair_fieldmaps(
    directed: list[tuple[int, str]], explicit_runs: dict[int, int]
) -> list[tuple[int, dict[str, int]]]:
    """Group fieldmaps into AP/PA pairs, labelled by run.

    Returns ``[(run_label, {"ap": n, "pa": m}), …]``. When the console recorded a
    ``run-`` for *every* fieldmap in the group (ReproIn), that number is trusted
    and used as the label — it survives an acquisition order the inference can't
    read, such as all the APs shot before all the PAs. Otherwise the label is the
    positional index and pairing falls back to acquisition order.
    """
    if explicit_runs and all(n in explicit_runs for n, _ in directed):
        by_run: dict[int, dict[str, int]] = {}
        for series_number, direction in directed:
            by_run.setdefault(explicit_runs[series_number], {})[direction] = series_number
        return sorted(by_run.items())

    return [(i, pair) for i, pair in enumerate(_pair_by_acquisition(directed), start=1)]


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
    if desc.endswith("_sbref"):
        return False
    if reproin_entities(description).get("seqtype") == "fmap":
        return True
    return bool(re.search(r"se_epi|spinecho.*field|sefieldmap", desc))


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

    # A ReproIn name states both outright, and its run- is mid-string (entities
    # like dir- follow it), so the trailing-token heuristic below would miss it.
    reproin = reproin_entities(description)
    if reproin.get("task"):
        run_value = reproin.get("run")
        return (
            _sanitize_task_label(reproin["task"]),
            int(run_value) if run_value and run_value.isdigit() else None,
        )

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
