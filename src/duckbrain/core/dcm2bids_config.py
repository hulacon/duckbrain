"""Auto-generate dcm2bids JSON config from DICOM inspection results."""

from __future__ import annotations

from .dicom_inspect import (
    FieldmapDetection,
    SeriesInfo,
    extract_task_label,
)


def generate_config(
    series_list: list[SeriesInfo],
    fieldmaps: FieldmapDetection,
    subject: str = "",
    session: str = "",
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

    Returns
    -------
    dict
        dcm2bids config with {"descriptions": [...]}.
    """
    descriptions = []
    sub_ses = f"sub{subject}ses{session}" if subject and session else ""

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
    run_counters: dict[str, int] = {}
    for s in func_series:
        task = extract_task_label(s.description)
        run_counters[task] = run_counters.get(task, 0) + 1

        desc = {
            "id": f"func-bold-{task}",
            "datatype": "func",
            "suffix": "bold",
            "criteria": {
                "SeriesDescription": f"*{s.description}*",
            },
            "custom_entities": f"task-{task}",
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
        task = extract_task_label(s.description)
        desc = {
            "id": f"func-sbref-{task}",
            "datatype": "func",
            "suffix": "sbref",
            "criteria": {
                "SeriesDescription": f"*{s.description}*",
            },
            "custom_entities": f"task-{task}",
        }
        descriptions.append(desc)

    # --- Fieldmaps ---
    for group_name, group_dirs in fieldmaps.groups.items():
        group_id = f"B0map_{group_name}_{sub_ses}" if sub_ses else f"B0map_{group_name}"

        if "ap" in group_dirs:
            descriptions.append(
                _fmap_description(group_dirs["ap"], "AP", group_id, series_list)
            )
        if "pa" in group_dirs:
            descriptions.append(
                _fmap_description(group_dirs["pa"], "PA", group_id, series_list)
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
            "SeriesDescription": f"*{series.description}*",
        },
    }


def _fmap_description(
    series_number: int,
    direction: str,
    b0_field_id: str,
    series_list: list[SeriesInfo],
) -> dict:
    """Build a fieldmap description entry."""
    # Find the series to get its description for matching
    series_desc = ""
    for s in series_list:
        if s.series_number == series_number:
            series_desc = s.description
            break

    return {
        "id": f"fmap-epi-{direction.lower()}",
        "datatype": "fmap",
        "suffix": "epi",
        "criteria": {
            "SeriesNumber": series_number,
        },
        "sidecar_changes": {
            "B0FieldSource": b0_field_id,
            "PhaseEncodingDirection": "j-" if direction == "AP" else "j",
        },
        "custom_entities": f"dir-{direction}",
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
