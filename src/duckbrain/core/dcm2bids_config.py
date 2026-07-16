"""Auto-generate dcm2bids JSON config from DICOM inspection results.

The task/run assignment for functional runs flows through an explicit, editable
**mapping** (:class:`TaskRunEntry` / :func:`build_task_run_mapping`) rather than
being re-derived inline during config generation. The mapping is the source of
truth: extraction tools (the naming heuristic, or a study-specific glob-like
template) merely *seed* it, and a GUI can let the user correct any row before it
is consumed here. This keeps the automatic and manual paths from diverging.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dicom_inspect import (
    _SBREF_SUFFIX,
    FieldmapDetection,
    SeriesInfo,
    extract_task_label,
    parse_task_run,
)


@dataclass
class TaskRunEntry:
    """One row of the task/run mapping table (source of truth for func naming).

    ``series_number`` / ``description`` identify the DICOM series; ``role`` is
    ``"bold"`` or ``"sbref"``; ``task`` and ``run`` are the (editable) BIDS
    entities. ``run`` of ``None`` emits no ``run-`` entity.
    """

    series_number: int
    description: str
    role: str
    task: str
    run: int | None = None


def build_task_run_mapping(
    series_list: list[SeriesInfo], template: str | None = None
) -> list[TaskRunEntry]:
    """Seed the task/run mapping for all func/sbref series.

    Task labels come from :func:`parse_task_run` (optionally guided by a
    glob-like ``template`` such as ``"{task}_r{run}"``). Run indices come from an
    explicit run token in the name when present, otherwise from counting repeats
    of the same task in acquisition (series-number) order — so studies that don't
    encode a run in the description still get sequential ``run-`` entities. Each
    SBRef inherits the task/run of the BOLD run it references.

    The returned rows are meant to be reviewed/edited (e.g. in the GUI) and then
    passed to :func:`generate_config`.
    """
    entries: list[TaskRunEntry] = []
    by_base: dict[str, tuple[str, int | None]] = {}
    counters: dict[str, int] = {}

    func = sorted(
        (s for s in series_list if s.classification == "func"),
        key=lambda s: s.series_number,
    )
    for s in func:
        task, run_token = parse_task_run(s.description, template)
        if run_token is None:
            counters[task] = counters.get(task, 0) + 1
            run = counters[task]
        else:
            run = run_token
        by_base[s.description.lower()] = (task, run)
        entries.append(TaskRunEntry(s.series_number, s.description, "bold", task, run))

    sbref = sorted(
        (s for s in series_list if s.classification == "sbref"),
        key=lambda s: s.series_number,
    )
    for s in sbref:
        base = _SBREF_SUFFIX.sub("", s.description)
        pair = by_base.get(base.lower())
        if pair is not None:
            task, run = pair
        else:
            task, run = parse_task_run(base, template)
        entries.append(TaskRunEntry(s.series_number, s.description, "sbref", task, run))

    return entries


def generate_config(
    series_list: list[SeriesInfo],
    fieldmaps: FieldmapDetection,
    subject: str = "",
    session: str = "",
    mapping: list[TaskRunEntry] | None = None,
    template: str | None = None,
) -> dict:
    """Build a dcm2bids-compatible config dict from classified DICOM series.

    Parameters
    ----------
    series_list : list[SeriesInfo]
        Classified series from dicom_inspect.classify_series().
    fieldmaps : FieldmapDetection
        Fieldmap detection results.
    subject : str
        Subject label (for B0FieldIdentifier naming).
    session : str
        Session label (for B0FieldIdentifier naming).
    mapping : list[TaskRunEntry], optional
        The task/run mapping to use as the source of truth for func/sbref
        naming. If omitted, one is seeded with :func:`build_task_run_mapping`
        (using ``template``). Pass an edited mapping to honor user corrections.
    template : str, optional
        Glob-like naming template used only when ``mapping`` is not supplied.

    Returns
    -------
    dict
        dcm2bids config with {"descriptions": [...]}.
    """
    descriptions = []
    sub_ses = f"sub{subject}ses{session}" if subject and session else ""

    if mapping is None:
        mapping = build_task_run_mapping(series_list, template)
    entry_by_series = {e.series_number: e for e in mapping}

    # Track which fieldmap groups are used by which tasks
    fmap_group_assignments: dict[str, str] = {}

    # --- Anatomicals ---
    for s in series_list:
        if s.classification != "anat":
            continue
        desc = _anat_description(s)
        if desc:
            descriptions.append(desc)

    # --- Functionals (BOLD) ---
    func_series = [s for s in series_list if s.classification == "func"]
    for s in func_series:
        entry = entry_by_series.get(s.series_number)
        task = entry.task if entry else extract_task_label(s.description)
        run = entry.run if entry else None
        run_suffix = f"-run{run}" if run is not None else ""
        custom_entities = f"task-{task}" + (f"_run-{run}" if run is not None else "")

        desc = {
            "id": f"func-bold-{task}{run_suffix}",
            "datatype": "func",
            "suffix": "bold",
            # Match on SeriesNumber, not a SeriesDescription wildcard: a bold's
            # description is a prefix of its SBRef's (e.g. '..._r1' vs
            # '..._r1_SBRef'), so '*..._r1*' would also match the SBRef and
            # dcm2bids would skip both as an ambiguous "Several Pairing".
            "criteria": {
                "SeriesNumber": s.series_number,
            },
            "custom_entities": custom_entities,
            "sidecar_changes": {
                "TaskName": task,
            },
        }

        # Assign B0FieldIdentifier if fieldmaps detected
        if fieldmaps.strategy != "none" and fieldmaps.groups:
            fmap_group = _assign_fmap_group(task, fieldmaps, fmap_group_assignments)
            if fmap_group is not None:
                group_id = f"B0map_{fmap_group}_{sub_ses}" if sub_ses else f"B0map_{fmap_group}"
                desc["sidecar_changes"]["B0FieldIdentifier"] = group_id

        descriptions.append(desc)

    # --- SBRef ---
    for s in series_list:
        if s.classification != "sbref":
            continue
        entry = entry_by_series.get(s.series_number)
        task = entry.task if entry else extract_task_label(s.description)
        run = entry.run if entry else None
        run_suffix = f"-run{run}" if run is not None else ""
        custom_entities = f"task-{task}" + (f"_run-{run}" if run is not None else "")
        desc = {
            "id": f"func-sbref-{task}{run_suffix}",
            "datatype": "func",
            "suffix": "sbref",
            "criteria": {
                "SeriesNumber": s.series_number,
            },
            "custom_entities": custom_entities,
        }
        descriptions.append(desc)

    # --- Fieldmaps ---
    for group_name, group_dirs in fieldmaps.groups.items():
        group_id = f"B0map_{group_name}_{sub_ses}" if sub_ses else f"B0map_{group_name}"
        # Extra entity (acq-/run-) that keeps multiple pairs from colliding on the
        # same dir-<X> filename; empty for the lone-pair case.
        extra_entity = fieldmaps.group_entities.get(group_name, "")

        if "ap" in group_dirs:
            descriptions.append(
                _fmap_description(
                    group_dirs["ap"], "AP", group_id, series_list, group_name, extra_entity
                )
            )
        if "pa" in group_dirs:
            descriptions.append(
                _fmap_description(
                    group_dirs["pa"], "PA", group_id, series_list, group_name, extra_entity
                )
            )

    return {"descriptions": descriptions}


def _anat_description(series: SeriesInfo) -> dict | None:
    """Build an anat description entry."""
    desc_lower = series.description.lower()

    if "t1w" in desc_lower or "t1_" in desc_lower or "mprage" in desc_lower:
        suffix = "T1w"
    elif "t2w" in desc_lower or "t2_" in desc_lower:
        suffix = "T2w"
    elif "flair" in desc_lower:
        suffix = "FLAIR"
    else:
        return None

    return {
        "id": f"anat-{suffix}",
        "datatype": "anat",
        "suffix": suffix,
        "criteria": {
            "SeriesNumber": series.series_number,
        },
    }


def _fmap_description(
    series_number: int,
    direction: str,
    b0_field_id: str,
    series_list: list[SeriesInfo],
    group_name: str = "",
    extra_entity: str = "",
) -> dict:
    """Build a fieldmap description entry.

    ``extra_entity`` (an ``acq-<label>`` or ``run-<n>`` token) distinguishes
    multiple fieldmap pairs in one session; it is placed in BIDS entity order
    (``acq`` before ``dir``, ``run`` after) and folded into the description id so
    ids stay unique across pairs.
    """
    # Find the series to get its description for matching
    series_desc = ""
    for s in series_list:
        if s.series_number == series_number:
            series_desc = s.description
            break

    custom_entities = f"dir-{direction}"
    if extra_entity.startswith("acq-"):
        custom_entities = f"{extra_entity}_dir-{direction}"
    elif extra_entity:
        custom_entities = f"dir-{direction}_{extra_entity}"

    id_suffix = f"-{group_name}" if group_name else ""

    return {
        "id": f"fmap-epi-{direction.lower()}{id_suffix}",
        "datatype": "fmap",
        "suffix": "epi",
        "criteria": {
            "SeriesNumber": series_number,
        },
        "sidecar_changes": {
            "B0FieldSource": b0_field_id,
            "PhaseEncodingDirection": "j-" if direction == "AP" else "j",
        },
        "custom_entities": custom_entities,
    }


def _assign_fmap_group(
    task: str,
    fieldmaps: FieldmapDetection,
    assignments: dict[str, str],
) -> str | None:
    """Assign a fieldmap group to a task.

    If there are named groups, tries to match task → group name.
    Otherwise assigns the first (or only) group.
    """
    if task in assignments:
        return assignments[task]

    groups = list(fieldmaps.groups.keys())
    if not groups:
        return None

    # Try matching by name
    for g in groups:
        if g and task.lower().startswith(g.lower()):
            assignments[task] = g
            return g

    # Default to first group
    assignments[task] = groups[0]
    return groups[0]


def config_to_json(config: dict, indent: int = 2) -> str:
    """Serialize dcm2bids config dict to formatted JSON string."""
    import json

    return json.dumps(config, indent=indent)
