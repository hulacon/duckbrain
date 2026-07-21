"""Auto-generate dcm2bids JSON config from DICOM inspection results.

The task/run assignment for functional runs flows through an explicit, editable
**mapping** (:class:`TaskRunEntry` / :func:`build_task_run_mapping`) rather than
being re-derived inline during config generation. The mapping is the source of
truth: extraction tools (the naming heuristic, or a study-specific glob-like
template) merely *seed* it, and a GUI can let the user correct any row before it
is consumed here. This keeps the automatic and manual paths from diverging.

**Project-wide mapping.** A study's scanner protocol is the same across subjects,
so the same SeriesDescriptions recur — which makes description the stable key a
mapping can be *defined once and inherited* across every subject. A
:class:`TaskRule` names ``description -> task`` at the project level (stored in the
project config's ``[task_mapping]`` section). Seeding then layers three sources,
each overriding the one before it:

  1. the per-session heuristic / template (:func:`parse_task_run`),
  2. **project-wide rules** — override the heuristic's *task* for series they name,
  3. per-session manual edits — the final override, for one-off exceptions.

Rules fix the task only; run numbers stay per-session (positional), so a subject
that repeats a task never collides on run-. :func:`task_rules_from_mapping`
collapses a reviewed session back into rules, so a user reviews one subject and
saves that as the project default for the rest.

**Fieldmap binding.** Which fieldmap pair a bold's ``B0FieldIdentifier`` points
at is decided by :func:`_assign_fmap_group`, whose heuristic (prefix-match the
task label against the group name, else take the first complete pair) cannot
express "this task used the *second* ``encoding`` pair". A :class:`FmapRule`
(project config's ``[fmap_mapping]``) binds ``task -> group`` outright and wins
over that heuristic — the same explicit-beats-inferred stance the ReproIn entity
handling takes. A rule naming a group this session lacks, or one missing a
direction, **raises**: a project-wide binding that silently fell back to a
different pair would hand fMRIPrep a distortion correction the user didn't ask
for, or one it cannot run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dicom_inspect import (
    _SBREF_SUFFIX,
    FieldmapDetection,
    SeriesInfo,
    extract_task_label,
    parse_task_run,
    reproin_entities,
    sanitize_task_label,
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


@dataclass
class TaskRule:
    """A project-wide task rule keyed on SeriesDescription.

    ``description`` is matched case-insensitively (whitespace-stripped) against a
    series' SeriesDescription; a match overrides the naming heuristic's *task*
    label with this rule's ``task``. Defined once per study and inherited by
    every subject.

    A rule deliberately fixes only the task, never the run. Run numbers are
    positional — they come from an explicit run token in the series name or, when
    absent, from acquisition-order counting *within each session*. Pinning a run
    project-wide would collide the moment a subject acquired that task more than
    once (every repeat would land on the same run-), so run derivation is left
    untouched and stays a per-session concern (and a per-session manual edit).
    """

    description: str
    task: str


@dataclass
class FmapRule:
    """A project-wide binding of a task label to a fieldmap group.

    ``task`` is matched against the *sanitized* BIDS task entity (the label that
    actually reaches the filename), case-insensitively and exactly — a rule is an
    explicit statement, so it does not prefix-match the way the fallback
    heuristic does. Both sides are sanitized before comparison, so a rule written
    as ``free_recall`` still binds the task that ships as ``freeRecall``.

    ``group`` is a key of :attr:`FieldmapDetection.groups` — ``"encoding"``,
    ``"encoding-2"``, or ``"1"``/``"2"`` for unnamed pairs (the names the
    Conversion page lists under Fieldmap Detection). Group keys are stable for a
    study for the same reason task rules are: the protocol, and therefore the
    SeriesDescriptions the keys derive from, repeat across subjects.
    """

    task: str
    group: str


def _rule_lookup(rules: list[TaskRule] | None) -> dict[str, TaskRule]:
    """Index rules by normalized (stripped, lowercased) description; last wins."""
    return {r.description.strip().lower(): r for r in rules} if rules else {}


def build_task_run_mapping(
    series_list: list[SeriesInfo],
    template: str | None = None,
    rules: list[TaskRule] | None = None,
) -> list[TaskRunEntry]:
    """Seed the task/run mapping for all func/sbref series.

    Task labels come from :func:`parse_task_run` (optionally guided by a
    glob-like ``template`` such as ``"{task}_r{run}"``). Run indices come from an
    explicit run token in the name when present, otherwise from counting repeats
    of the same task in acquisition (series-number) order — so studies that don't
    encode a run in the description still get sequential ``run-`` entities. Each
    SBRef inherits the task/run of the BOLD run it references.

    A project-wide ``rules`` list (description-keyed :class:`TaskRule`) takes
    precedence over the heuristic for any series it names — this is how a study
    defines task/run once and every subject inherits it. A series no rule names
    still falls back to the heuristic, and per-session manual edits remain the
    final override downstream of this.

    The returned rows are meant to be reviewed/edited (e.g. in the GUI) and then
    passed to :func:`generate_config`.
    """
    entries: list[TaskRunEntry] = []
    by_base: dict[str, tuple[str, int | None]] = {}
    counters: dict[str, int] = {}
    lookup = _rule_lookup(rules)

    func = sorted(
        (s for s in series_list if s.classification == "func"),
        key=lambda s: s.series_number,
    )
    for s in func:
        # A rule overrides only the task; the run still comes from the name token
        # (else acquisition-order counting), so repeats never collide.
        parsed_task, run_token = parse_task_run(s.description, template)
        rule = lookup.get(s.description.strip().lower())
        task = rule.task if rule is not None else parsed_task
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
            parsed_task, run = parse_task_run(base, template)
            rule = lookup.get(base.strip().lower())
            task = rule.task if rule is not None else parsed_task
        entries.append(TaskRunEntry(s.series_number, s.description, "sbref", task, run))

    return entries


def task_rules_from_mapping(entries: list[TaskRunEntry]) -> list[TaskRule]:
    """Collapse a reviewed session's BOLD rows into project-wide task rules.

    One rule per distinct BOLD SeriesDescription (SBRefs inherit their BOLD, so
    they are skipped); later duplicate descriptions win, matching the mapping's
    own last-write semantics. Only the task carries over — run numbers are
    positional and stay per-session. This is the "save this subject's mapping as
    the project default" direction.
    """
    by_desc: dict[str, TaskRule] = {}
    for e in entries:
        if e.role != "bold":
            continue
        desc = e.description.strip()
        if not desc:
            continue
        by_desc[desc.lower()] = TaskRule(desc, e.task)
    return list(by_desc.values())


def task_rules_from_config(config: dict) -> list[TaskRule]:
    """Read project-wide task rules from a merged config's ``[task_mapping]``.

    Tolerant of malformed rows (missing description/task are skipped) so a
    hand-edited section can never sink config loading. A legacy ``run`` key is
    ignored — rules fix the task only.
    """
    section = config.get("task_mapping") or {}
    out: list[TaskRule] = []
    for row in section.get("rule") or []:
        desc = str(row.get("description", "")).strip()
        task = str(row.get("task", "")).strip()
        if not desc or not task:
            continue
        out.append(TaskRule(desc, task))
    return out


def task_rules_to_config_section(rules: list[TaskRule]) -> dict:
    """Serialize rules into a TOML-friendly ``[task_mapping]`` section."""
    return {"rule": [{"description": r.description, "task": r.task} for r in rules]}


def fmap_rules_from_config(config: dict) -> list[FmapRule]:
    """Read project-wide fieldmap bindings from a merged config's ``[fmap_mapping]``.

    Tolerant of malformed rows (a missing task or group is skipped) so a
    hand-edited section can never sink config loading — same contract as
    :func:`task_rules_from_config`. A group that doesn't exist in a given session
    is *not* caught here: it is a per-session fact, so it surfaces at assignment
    time where the available groups are known.
    """
    section = config.get("fmap_mapping") or {}
    out: list[FmapRule] = []
    for row in section.get("rule") or []:
        task = str(row.get("task", "")).strip()
        group = str(row.get("group", "")).strip()
        if not task or not group:
            continue
        out.append(FmapRule(task, group))
    return out


def fmap_rules_to_config_section(rules: list[FmapRule]) -> dict:
    """Serialize fieldmap bindings into a TOML-friendly ``[fmap_mapping]`` section."""
    return {"rule": [{"task": r.task, "group": r.group} for r in rules]}


def _fmap_rule_lookup(rules: list[FmapRule] | None) -> dict[str, str]:
    """Index fieldmap bindings by sanitized, lowercased task label; last wins.

    Sanitizing the rule's task mirrors what :func:`generate_config` does to the
    mapping's task before it reaches assignment, so the two always meet in the
    same namespace.
    """
    if not rules:
        return {}
    return {sanitize_task_label(r.task).lower(): r.group for r in rules if r.task}


def generate_config(
    series_list: list[SeriesInfo],
    fieldmaps: FieldmapDetection,
    subject: str = "",
    session: str = "",
    mapping: list[TaskRunEntry] | None = None,
    template: str | None = None,
    fmap_rules: list[FmapRule] | None = None,
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
    fmap_rules : list[FmapRule], optional
        Project-wide ``task -> fieldmap group`` bindings; each wins over the
        name-matching heuristic for the task it names.

    Returns
    -------
    dict
        dcm2bids config with {"descriptions": [...]}.

    Raises
    ------
    ValueError
        If an ``fmap_rules`` entry names a group this session doesn't have, or
        one that holds only a single phase-encoding direction.
    """
    descriptions = []
    sub_ses = f"sub{subject}ses{session}" if subject and session else ""

    if mapping is None:
        mapping = build_task_run_mapping(series_list, template)
    entry_by_series = {e.series_number: e for e in mapping}

    # Track which fieldmap groups are used by which tasks
    fmap_group_assignments: dict[str, str] = {}
    fmap_rule_lookup = _fmap_rule_lookup(fmap_rules)

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
        # Sanitize regardless of source: the heuristic already yields a valid
        # label, but a user-entered mapping edit or project rule (entry.task) can
        # carry an underscore/space/hyphen that would break the BIDS entity.
        task = sanitize_task_label(entry.task if entry else extract_task_label(s.description))
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
            fmap_group = _assign_fmap_group(
                task, fieldmaps, fmap_group_assignments, fmap_rule_lookup
            )
            if fmap_group is not None:
                group_id = f"B0map_{fmap_group}_{sub_ses}" if sub_ses else f"B0map_{fmap_group}"
                desc["sidecar_changes"]["B0FieldIdentifier"] = group_id

        descriptions.append(desc)

    # --- SBRef ---
    for s in series_list:
        if s.classification != "sbref":
            continue
        entry = entry_by_series.get(s.series_number)
        # Sanitize regardless of source: the heuristic already yields a valid
        # label, but a user-entered mapping edit or project rule (entry.task) can
        # carry an underscore/space/hyphen that would break the BIDS entity.
        task = sanitize_task_label(entry.task if entry else extract_task_label(s.description))
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


def resolve_fmap_assignments(
    mapping: list[TaskRunEntry],
    fieldmaps: FieldmapDetection,
    fmap_rules: list[FmapRule] | None = None,
) -> dict[str, str]:
    """Report ``task -> fieldmap group`` exactly as :func:`generate_config` binds it.

    The binding is otherwise only visible as ``B0FieldIdentifier`` strings buried
    in the generated JSON, which is a poor way to check that a rule did what was
    intended. Runs the same bold-only, sanitized-label loop against the same
    assignment function, so it cannot drift from what is actually written — and
    it raises on an unsatisfiable rule for the same reason.
    """
    if fieldmaps.strategy == "none" or not fieldmaps.groups:
        return {}
    assignments: dict[str, str] = {}
    lookup = _fmap_rule_lookup(fmap_rules)
    for entry in mapping:
        if entry.role != "bold":
            continue
        _assign_fmap_group(
            sanitize_task_label(entry.task), fieldmaps, assignments, lookup
        )
    return assignments


# BIDS anatomical suffixes a ReproIn ``anat-<label>`` may name. Spelled out
# rather than passed through, so a console typo becomes an unconverted series the
# user can see rather than an invalid BIDS suffix written into the dataset.
_BIDS_ANAT_SUFFIXES = {
    s.lower(): s
    for s in ("T1w", "T2w", "T1map", "T2map", "T2star", "FLAIR", "PDw", "PDT2", "UNIT1", "angio")
}


def _anat_description(series: SeriesInfo) -> dict | None:
    """Build an anat description entry.

    A ReproIn ``anat-<label>`` names its BIDS suffix outright, so it is trusted
    ahead of the vocabulary matching below. Without this, an anat whose label
    isn't in that vocabulary (``anat-PDw``, ``anat-UNIT1``) returned None and the
    series was dropped from the conversion silently.
    """
    reproin = reproin_entities(series.description)
    if reproin.get("seqtype") == "anat":
        suffix = _BIDS_ANAT_SUFFIXES.get(reproin.get("suffix", "").lower())
        if suffix:
            return {
                "id": f"anat-{suffix}",
                "datatype": "anat",
                "suffix": suffix,
                "criteria": {"SeriesNumber": series.series_number},
            }

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

    # BIDS entity order is acq- before dir-, run- after; extra_entity may carry
    # either or both (a named group reacquired in one session gets both).
    parts = [p for p in extra_entity.split("_") if p]
    acq = next((p for p in parts if p.startswith("acq-")), "")
    run = next((p for p in parts if p.startswith("run-")), "")
    custom_entities = "_".join(p for p in (acq, f"dir-{direction}", run) if p)

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
    rules: dict[str, str] | None = None,
) -> str | None:
    """Assign a fieldmap group to a task.

    Three sources, each overriding the one after it:

      1. an explicit project-wide :class:`FmapRule` binding (``rules``),
      2. a name match — the task label prefixed by the group's base name,
      3. the first complete group.

    Only groups holding *both* directions are candidates. An aborted fieldmap
    leaves a lone AP that pairs with nothing, and it sorts first — real sessions
    do this (MMM_003_sess18 opens with two APs before the PA). Pointing a bold's
    ``B0FieldIdentifier`` at a half-group would give fMRIPrep a distortion
    correction it cannot run.

    Raises ``ValueError`` when a rule names a group this session lacks or one
    that is half a pair. Falling back would silently give the run a *different*
    fieldmap than the project asked for — the one outcome an explicit binding
    exists to prevent.
    """
    if task in assignments:
        return assignments[task]

    complete = [g for g, dirs in fieldmaps.groups.items() if "ap" in dirs and "pa" in dirs]
    groups = complete or list(fieldmaps.groups.keys())
    if not groups:
        return None

    # An explicit binding wins outright, and is matched exactly rather than by
    # prefix — the heuristic below infers, a rule states.
    wanted = (rules or {}).get(task.lower())
    if wanted is not None:
        if wanted not in complete:
            known = ", ".join(sorted(fieldmaps.groups)) or "none"
            reason = (
                f"holds only one phase-encoding direction "
                f"({', '.join(sorted(fieldmaps.groups[wanted])).upper()})"
                if wanted in fieldmaps.groups
                else "does not exist in this session"
            )
            raise ValueError(
                f"[fmap_mapping] binds task '{task}' to fieldmap group "
                f"'{wanted}', but that group {reason}. Groups detected here: "
                f"{known}. Fix the rule in the project config, or drop it to "
                f"fall back to automatic assignment."
            )
        assignments[task] = wanted
        return wanted

    # Try matching by name. A group reacquired within one session is keyed
    # "<name>-2", "<name>-3", … so match on the base name; the first pair wins,
    # which is the documented no-temporal-proximity limitation (TODO #5) and the
    # case an explicit rule above exists to settle.
    for g in groups:
        base = re.sub(r"-\d+$", "", g)
        if base and task.lower().startswith(base.lower()):
            assignments[task] = g
            return g

    # Default to first group
    assignments[task] = groups[0]
    return groups[0]


def config_to_json(config: dict, indent: int = 2) -> str:
    """Serialize dcm2bids config dict to formatted JSON string."""
    import json

    return json.dumps(config, indent=indent)
