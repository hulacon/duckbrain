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
    classification: str = ""  # anat, func, fmap, sbref, physio, scout, derived, dwi, unknown
    # Header evidence, when the DICOMs were readable. ``None`` means classify
    # from the name alone — which is all duckbrain ever did, and is still the
    # fallback for a site whose export the reader can't parse.
    header: object | None = None
    # BIDS suffix the header pinned (``T1w``, ``epi``, ``phasediff``, …), or ""
    # when only the datatype is known.
    suffix_hint: str = ""
    # Where ``classification`` came from: "header" or "name". Carried so the
    # Conversion page can show the user which series were guessed from a string.
    classified_by: str = ""


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


# Every vocabulary token below is anchored to a token start with this guard.
# Without it the anat tokens match mid-word and silently steal functional runs:
# 'BART1_mb3_g2_2mm_te27' contains 'T1_' and 'SST2_...'/'React2_...' contain
# 'T2_', so three real tasks in the LCNI repository classified as anatomicals —
# and because anat descriptions collide on one filename, they overwrote each
# other. `_` is deliberately a separator here and NOT part of the guard, which
# is also why plain \b is wrong: \w includes '_', so r"\bscout\b" never matches
# 'aa_scout'. Pinned by tests/test_series_classification.py.
_TOKEN_START = r"(?<![A-Za-z0-9])"

# Siemens scanner localizers, whose console names run the words together
# ('AAHScout') or separate them ('AAhead_scout', 'AAHead_Scout', 'aa_scout'),
# plus the _MPR_cor/sag/tra reformats derived from them.
_AASCOUT = r"aa[_-]?(?:head|h)?[_-]?scout"

# Classification patterns, tried in order (first match wins). Definitive
# suffixes (_SBRef, _PhysioLog) come first so a functional run's single-band
# reference or physio log isn't swallowed by a broader token. Bare
# 'scout'/'localizer' still match only as whole words, so a *functional*
# localizer task like 'localizer_prf_run1' is NOT mistaken for the scanner
# localizer — it falls through and is recovered as func by SBRef pairing (see
# _recover_func_from_sbref).
_CLASSIFICATION_PATTERNS = [
    ("sbref", re.compile(r"_SBRef$", re.IGNORECASE)),
    ("physio", re.compile(r"(PhysioLog|physio)", re.IGNORECASE)),
    # Scanner-derived series that are never source data: the inline evaluation
    # maps, the motion-corrected copy, the Phoenix report, and the vNav
    # navigator *setter* (which carries 'mprage' in its name and so was
    # converted as a second, colliding T1w).
    (
        "derived",
        re.compile(
            _TOKEN_START + r"(?:PhoenixZIPReport|MoCo(?:Series)?|"
            r"t[-_]?Maps?|EvaSeries|setter)",
            re.IGNORECASE,
        ),
    ),
    # 'distortion_ap'/'distortion_pa' and 'fieldmap_2mm' are LCNI's own fieldmap
    # names and matched none of these, so they classified unknown and were
    # dropped with a generic warning. Recognising them does not by itself make
    # them convertible — the GRE flavour still isn't expressible — but a
    # fieldmap duckbrain names and refuses is worth far more to the user than a
    # fieldmap it never saw. plan_warnings says which is which.
    (
        "fmap",
        re.compile(
            r"(se_epi|SpinEchoFieldMap|SEfieldmap|distortion|topup|pepolar"
            r"|gre_field|field_?map|b0_?map)",
            re.IGNORECASE,
        ),
    ),
    (
        "dwi",
        re.compile(
            _TOKEN_START + r"(?:dwi|dti|diffusion|diff)(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    ("scout", re.compile(_TOKEN_START + _AASCOUT + r"|\bscout\b|\blocalizer\b", re.IGNORECASE)),
    (
        "anat",
        re.compile(
            _TOKEN_START + r"(?:T1w|T1[_-]|MPRAGE|T2w|T2[_-]|SPC|FLAIR)",
            re.IGNORECASE,
        ),
    ),
    ("func", re.compile(r"(bold|task-|cmrr_mbep2d)", re.IGNORECASE)),
]


def list_series(dicom_session_dir: str | Path, read_headers: bool = True) -> list[SeriesInfo]:
    """Enumerate all Series_NN_description/ dirs in a DICOM session.

    Parameters
    ----------
    dicom_session_dir : path
        Path to a single session's DICOM directory.
    read_headers : bool
        Read a few DICOM headers per series so classification can use what the
        scanner recorded rather than what the operator typed. Costs up to three
        ``dcmread(stop_before_pixels=True)`` per series. Set False only where
        the names are known to be authoritative and the I/O matters.

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
        if read_headers:
            from .dicom_header import read_series_header

            info.header = read_series_header(entry)
        series.append(info)

    return sorted(series, key=lambda s: s.series_number)


_SBREF_SUFFIX = re.compile(r"_SBRef$", re.IGNORECASE)


def classify_series(series_list: list[SeriesInfo]) -> list[SeriesInfo]:
    """Classify each series as anat/func/fmap/sbref/physio/scout/derived/dwi/unknown.

    The DICOM header decides where it can. What the scanner recorded is a fact;
    the series description is the console operator's free text, and across the
    LCNI repository it is frequently silent about datatype — `food`, `Whack`,
    `Resting1`, `WMS_R1` and `EPI196` are all ordinary BOLD runs. See
    :mod:`duckbrain.core.dicom_header` for the evidence and the ordered rules.

    Where the header is absent (no readable DICOM, or ``read_headers=False``) or
    not decisive, the name heuristics run exactly as before, so a session that
    never reaches a DICOM still classifies as well as it used to. A second pass
    then treats the single-band reference as authoritative: a matching
    ``<name>_SBRef`` sibling means ``<name>`` is a functional run, so it is
    promoted to ``func`` even if the name pass guessed ``scout`` or ``anat``.
    This rescues functional *localizer* tasks (e.g. MMM's ``localizer_prf_run1``,
    which the description pass would otherwise treat as a scanner localizer) and
    runs with study-specific names (e.g. DIVATTEN's ``div_perFace_perTone_r1``).

    Modifies series in-place and returns the list.
    """
    from .dicom_header import classify_from_header

    for s in series_list:
        classification, suffix = ("", "")
        if s.header is not None:
            classification, suffix = classify_from_header(s.header)
        if classification:
            s.classification = classification
            s.suffix_hint = suffix
            s.classified_by = "header"
        else:
            s.classification = _classify_one(s.description)
            s.suffix_hint = ""
            s.classified_by = "name"
    _recover_func_from_sbref(series_list)
    _demote_nd_duplicates(series_list)
    return series_list


# Siemens writes a second, distortion-uncorrected copy of a series with 'ND' (No
# Distortion correction) added to the name. Converting both puts two images on
# one BIDS filename.
_ND_TOKEN = re.compile(r"(?<![A-Za-z0-9])ND(?=[_-]|$)")


def _demote_nd_duplicates(series_list: list[SeriesInfo]) -> None:
    """Drop an '_ND_' copy only when its corrected twin is also present.

    Conditional on purpose. Dropping every ND series unconditionally would throw
    away the only anatomical at a site that acquires ND alone — a silent
    degradation, which this project treats as worse than a failure. So the ND
    copy is dropped only when removing the token yields a sibling that is
    actually in the session; otherwise it converts normally.
    """
    by_name = {s.description.lower(): s for s in series_list}
    for s in series_list:
        if not _ND_TOKEN.search(s.description):
            continue
        twin = re.sub(r"[_-]?(?<![A-Za-z0-9])ND(?=[_-]|$)", "", s.description, count=1)
        if twin.lower() != s.description.lower() and twin.lower() in by_name:
            s.classification = "derived"


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
        # Only a name-derived guess is overridden. The SBRef signal exists to
        # rescue a series whose *name* said nothing useful; it cannot outrank
        # what the scanner recorded about the acquisition itself.
        if s.classified_by == "header":
            continue
        if s.classification in _SBREF_PROMOTABLE and s.description.lower() in sbref_bases:
            s.classification = "func"
            s.suffix_hint = "bold"


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


def _detect_gre_fieldmaps(
    fmap_series: list[SeriesInfo],
) -> tuple[dict, list[str], set[int]]:
    """Pair the magnitude and phase halves of a gradient-echo fieldmap.

    A Siemens ``gre_field_mapping`` arrives as **two consecutive series** with
    the same description: the first holds both echoes of the magnitude (which
    dcm2niix splits into ``magnitude1``/``magnitude2``), the second the phase
    difference. Across the LCNI repository the phase series is at
    ``SeriesNumber + 1`` in 32 of 32 cases.

    Which half is which comes from the header (``'P'`` in ImageType marks phase),
    never from the name — both halves carry the *same* description, so there is
    nothing in the name to tell them apart. A session whose DICOMs weren't read
    therefore yields no GRE groups rather than a guess.

    Returns ``(groups, warnings, claimed_series_numbers)``.
    """
    magnitudes = [s for s in fmap_series if s.suffix_hint == "magnitude"]
    phases = [s for s in fmap_series if s.suffix_hint == "phasediff"]
    if not magnitudes and not phases:
        return {}, [], set()

    groups: dict[str, dict[str, int]] = {}
    warnings: list[str] = []
    claimed: set[int] = set()
    used_phase: set[int] = set()

    for magnitude in sorted(magnitudes, key=lambda s: s.series_number):
        partner = next(
            (
                p
                for p in sorted(phases, key=lambda s: s.series_number)
                if p.series_number not in used_phase
                and p.series_number > magnitude.series_number
                and p.description.lower() == magnitude.description.lower()
            ),
            None,
        )
        if partner is None:
            warnings.append(
                f"Series_{magnitude.series_number}_{magnitude.description} looks like "
                "the magnitude half of a gradient-echo fieldmap but no phase series "
                "follows it; it will not be converted."
            )
            continue
        name = _sanitize_task_label(_extract_fmap_group(magnitude.description.lower()) or "gre")
        key = name
        suffix = 2
        while key in groups:
            key = f"{name}-{suffix}"
            suffix += 1
        groups[key] = {"magnitude": magnitude.series_number, "phasediff": partner.series_number}
        used_phase.add(partner.series_number)
        claimed |= {magnitude.series_number, partner.series_number}

    for phase in phases:
        if phase.series_number not in used_phase:
            warnings.append(
                f"Series_{phase.series_number}_{phase.description} is a phase image "
                "with no matching magnitude series; it will not be converted."
            )

    return groups, warnings, claimed


def is_complete_group(members: dict) -> bool:
    """True when a fieldmap group has everything it needs to estimate a field.

    Both flavours live in one ``groups`` namespace so that binding, naming and
    collision checks don't have to know which is which — only this predicate does.
    """
    return ("ap" in members and "pa" in members) or (
        "magnitude" in members and "phasediff" in members
    )


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

    # The gradient-echo flavour is a different shape and is separated out first:
    # it has no phase-encoding direction to read, and its two halves are two
    # *series*, not two images. Everything below this is pepolar.
    gre_groups, gre_warnings, gre_claimed = _detect_gre_fieldmaps(fmap_series)
    fmap_series = [s for s in fmap_series if s.series_number not in gre_claimed]

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
        # The token match is deliberate: a plain ``"_ap" in desc`` test read
        # 'se_epi_pa_apex' as AP, because '_ap' occurs inside '_apex' and the AP
        # branch is tested first. Prefer the *last* direction token, so a name
        # that leads with the direction and repeats it at the end
        # ('AP_fieldmap_se_epi_2mm_ap') still resolves, and a group label that
        # merely contains the letters does not.
        direction = None
        if reproin.get("dir"):
            direction = reproin["dir"].lower()
        else:
            hits = _DIRECTION_TOKEN.findall(desc_lower)
            if hits and len({h for h in hits}) == 1:
                direction = hits[-1]
            elif hits:
                warnings.append(
                    f"Ambiguous phase-encoding direction "
                    f"({'/'.join(sorted(set(hits)))}) in "
                    f"Series_{s.series_number}_{s.description}"
                )

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

    # The two flavours share one namespace so that binding, entity naming and
    # the collision checks work on both without knowing which is which.
    for gname, members in gre_groups.items():
        key = gname
        suffix = 2
        while key in groups:
            key = f"{gname}-{suffix}"
            suffix += 1
        groups[key] = members
    warnings.extend(gre_warnings)

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


# A phase-encoding direction standing as its own token, so 'apex'/'paradigm'
# don't read as directions.
_DIRECTION_TOKEN = re.compile(r"(?<![a-z0-9])(ap|pa)(?![a-z0-9])", re.IGNORECASE)


def _is_fieldmap(description: str) -> bool:
    """Check if a description looks like a fieldmap."""
    desc = description.lower()
    if desc.endswith("_sbref"):
        return False
    if reproin_entities(description).get("seqtype") == "fmap":
        return True
    return bool(re.search(r"se_epi|spinecho.*field|sefieldmap|distortion|topup|pepolar", desc))


def _extract_fmap_group(desc_lower: str) -> str:
    """Extract a group name from fieldmap description.

    E.g., 'se_epi_ap_encoding' → 'encoding'
          'se_epi_pa_retrieval' → 'retrieval'
          'se_epi_ap' → '' (unnamed group)

    The direction token is removed only where it stands as its own token. The
    unanchored ``re.sub(r"_?(ap|pa)", ...)`` this replaces stripped *every*
    occurrence of those two letters anywhere in the string, so
    'AP_fieldmap_se_epi_2mm_ap' grouped as 'AP_fieldm_se_epi_2mm' and
    'se_epi_ap_capture' grouped as 'cture' — two names for what is one pair.
    """
    # Direction token only where it is a whole token (start, end, or _-delimited)
    cleaned = re.sub(r"(?<![a-z0-9])(?:ap|pa)(?![a-z0-9])", "", desc_lower)
    # Remove common prefixes
    cleaned = re.sub(r"^[_-]*(se_epi|spinecho|sefieldmap)[_-]?", "", cleaned)
    cleaned = re.sub(r"[_-]{2,}", "_", cleaned)
    cleaned = cleaned.strip("_- ")
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

# Acquisition parameters that sites append to the console protocol name —
# 'GNG1_mb3_g2_2mm_te27' is task GNG, not a task called 'Gng1Mb3G22mmTe27'.
# Stripped only as whole trailing tokens, so a parameter-looking fragment in the
# middle of a study's own name survives.
_ACQ_PARAM_TOKEN = re.compile(
    r"(?:(?:mb|sms|g|p|te|tr|ti|fa|acc)\d+(?:\.\d+)?|"
    r"[\d.]+mm|[\d.]+iso|iso|\d+ch|grappa)$",
    re.IGNORECASE,
)


def _strip_acq_params(label: str) -> str:
    """Drop a trailing run of acquisition-parameter tokens from a description."""
    parts = re.split(r"([_-])", label)
    tokens = parts[::2]
    while len(tokens) > 1 and _ACQ_PARAM_TOKEN.fullmatch(tokens[-1]):
        tokens.pop()
    seps = parts[1::2][: max(len(tokens) - 1, 0)]
    out = tokens[0]
    for sep, tok in zip(seps, tokens[1:]):
        out += sep + tok
    return out


# A task label ending in a bare index, e.g. 'MAB3' -> ('MAB', 3), 'route6' ->
# ('route', 6). Only meaningful when a sibling shares the stem; see
# dcm2bids_config.build_task_run_mapping.
_TRAILING_INDEX = re.compile(r"^(?P<stem>.*?[A-Za-z])[_-]?(?P<index>\d{1,3})$")


def split_trailing_index(label: str) -> tuple[str, int | None]:
    """Split a bare trailing index off a task label: 'MAB3' → ('MAB', 3).

    Returns ``(label, None)`` when there is no trailing index. The caller must
    decide whether the index is a *run* — on its own a trailing number is just
    as likely to be a matrix size or an echo time ('EPI196'), which is why this
    only reports the split and never applies it.
    """
    m = _TRAILING_INDEX.match(label)
    if not m:
        return label, None
    return m.group("stem").rstrip("_-"), int(m.group("index"))


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
        task_raw = _strip_acq_params(task_raw)

    return _sanitize_task_label(task_raw), run


def extract_task_label(description: str, template: str | re.Pattern | None = None) -> str:
    """Extract just the BIDS task label from a series description.

    Thin wrapper over :func:`parse_task_run`; kept for callers that only need
    the task. E.g. 'cmrr_mbep2d_bold_task-encoding_run-1' → 'encoding',
    'div_retScene_perTone_r1' → 'divRetScenePerTone'.
    """
    return parse_task_run(description, template)[0]
