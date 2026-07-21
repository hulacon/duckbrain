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
for, or one it cannot run. That holds when a session collected *no* fieldmaps at
all, which is the case a "were any detected" guard would quietly skip.

The reserved group ``"none"`` binds a task to no fieldmap, so a run that
shouldn't be distortion-corrected — or a session whose fieldmaps weren't
collected — is stated rather than inferred from an absence. Sessions with no
fieldmaps and no binding are unaffected: no ``B0FieldIdentifier`` is written, no
``fmap`` descriptions are emitted, and fMRIPrep simply runs without SDC.
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


# The group value that opts a task out of distortion correction. It has to be a
# real word rather than the empty string: "" is already a *legitimate* group key
# (the session with one unnamed pair), so it can't double as "no fieldmap".
_NO_FMAP = "none"


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

    The reserved value ``"none"`` means *this task gets no distortion
    correction* — no ``B0FieldIdentifier`` is written, which is the right answer
    for a run whose fieldmaps weren't collected or shouldn't be applied. It is
    the one group value that is always satisfiable, so it is also how a project
    keeps a binding honest for sessions that legitimately lack fieldmaps rather
    than deleting the rule.

    ``run`` narrows the binding to a single run of that task. ``None`` — the
    default, and what every rule written before this existed means — binds *every*
    run, so existing ``[fmap_mapping]`` sections keep loading and keep meaning
    what they meant. A rule naming a run wins over one that doesn't: specific
    beats general, the same precedence explicit-beats-inferred already has.

    Run-level bindings exist for the case a task-level one cannot express at all:
    a fieldmap re-shot *within* a single task, where the runs before and after it
    want different pairs. Rare, but the task-keyed form has no way to say it.

    The rule is keyed on task+run rather than on series number deliberately.
    Series numbers are per-session, so a series-keyed rule could not generalize
    across subjects, and ``[fmap_mapping]`` is a project-level statement like
    ``[task_mapping]`` beside it.
    """

    task: str
    group: str
    run: int | None = None


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
        # A missing or unparseable run means "every run of this task" — which is
        # what every rule written before run-level bindings existed meant, so an
        # older [fmap_mapping] keeps working untouched.
        raw_run = row.get("run")
        try:
            run = int(raw_run) if raw_run not in (None, "") else None
        except (TypeError, ValueError):
            run = None
        out.append(FmapRule(task, group, run))
    return out


def collapse_fmap_rules(rules: list[FmapRule]) -> list[FmapRule]:
    """Reduce per-run bindings to task-wide ones wherever every run agrees.

    The Conversion page produces one binding per *run*, because that is the grain
    its table edits at. Writing those straight into ``[fmap_mapping]`` would spell
    out a rule per run for every study — including the overwhelming majority whose
    runs all use the same pair — and a project file nobody can read is one nobody
    will correct. So a task whose runs agree collapses to the single task-wide
    rule it always was, and only a task that genuinely differs run to run keeps
    per-run rows.

    Order is preserved by first appearance of the task, and a run of ``None`` on
    input is treated as already task-wide.
    """
    by_task: dict[str, list[FmapRule]] = {}
    for r in rules:
        by_task.setdefault(sanitize_task_label(r.task), []).append(r)

    out: list[FmapRule] = []
    for task, group_rules in by_task.items():
        groups = {r.group for r in group_rules}
        if len(groups) == 1:
            out.append(FmapRule(task, group_rules[0].group))
        else:
            out.extend(FmapRule(task, r.group, r.run) for r in group_rules)
    return out


def fmap_rules_to_config_section(rules: list[FmapRule]) -> dict:
    """Serialize fieldmap bindings into a TOML-friendly ``[fmap_mapping]`` section.

    ``run`` is written only when the rule names one, so a project that binds
    per-task keeps the same two-key rows it has always had.
    """
    return {
        "rule": [
            {"task": r.task, "group": r.group}
            if r.run is None
            else {"task": r.task, "group": r.group, "run": r.run}
            for r in rules
        ]
    }


def _fmap_rule_lookup(
    rules: list[FmapRule] | None,
) -> dict[tuple[str, int | None], str]:
    """Index fieldmap bindings by ``(sanitized lowercased task, run)``; last wins.

    Sanitizing the rule's task mirrors what :func:`generate_config` does to the
    mapping's task before it reaches assignment, so the two always meet in the
    same namespace. A rule with no ``run`` is stored under ``None``, which
    :func:`_lookup_fmap_rule` treats as the fallback for every run of the task.
    """
    if not rules:
        return {}
    return {
        (sanitize_task_label(r.task).lower(), r.run): r.group
        for r in rules
        if r.task
    }


def _lookup_fmap_rule(
    rules: dict[tuple[str, int | None], str] | None,
    task: str,
    run: int | None,
) -> str | None:
    """Find the binding for one run: the run-specific rule, else the task-wide one.

    Specific beats general. Without this precedence a study could not say "this
    task uses pair 1, except run 3" — it would have to enumerate every run.
    """
    if not rules:
        return None
    key = task.lower()
    if run is not None and (key, run) in rules:
        return rules[(key, run)]
    return rules.get((key, None))


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

    # Track which fieldmap group each (task, run) is bound to
    fmap_group_assignments: dict[tuple[str, int | None], str] = {}
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

        # Assign B0FieldIdentifier. Called unconditionally rather than behind a
        # "were any fieldmaps detected" guard: with none detected it returns None
        # and nothing is written (unchanged), but a project binding that names a
        # group still gets to fail instead of being skipped along with everything
        # else. That guard is what let an unhonorable rule pass silently.
        fmap_group = _assign_fmap_group(
            task, run, fieldmaps, fmap_group_assignments, fmap_rule_lookup
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
) -> dict[tuple[str, int | None], str]:
    """Report ``(task, run) -> fieldmap group`` exactly as :func:`generate_config` binds it.

    Keyed on the pair rather than the task because a binding is per-run: two runs
    of one task can legitimately point at different pairs (a fieldmap re-shot
    mid-task), and a task-keyed report could not show that.

    The binding is otherwise only visible as ``B0FieldIdentifier`` strings buried
    in the generated JSON, which is a poor way to check that a rule did what was
    intended. Runs the same bold-only, sanitized-label loop against the same
    assignment function, so it cannot drift from what is actually written — and
    it raises on an unsatisfiable rule for the same reason.

    A task bound to ``"none"`` is reported as such rather than omitted: opting a
    run out of distortion correction is a decision worth seeing in the table, not
    an absence. Tasks with no binding and no fieldmaps to assign are absent.
    """
    assignments: dict[tuple[str, int | None], str] = {}
    lookup = _fmap_rule_lookup(fmap_rules)
    for entry in mapping:
        if entry.role != "bold":
            continue
        _assign_fmap_group(
            sanitize_task_label(entry.task), entry.run, fieldmaps, assignments, lookup
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
    run: int | None,
    fieldmaps: FieldmapDetection,
    assignments: dict[tuple[str, int | None], str],
    rules: dict[tuple[str, int | None], str] | None = None,
) -> str | None:
    """Assign a fieldmap group to one run of a task.

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
    cache_key = (task, run)
    if cache_key in assignments:
        group = assignments[cache_key]
        return None if group == _NO_FMAP else group

    complete = [g for g, dirs in fieldmaps.groups.items() if "ap" in dirs and "pa" in dirs]

    # An explicit binding wins outright, and is matched exactly rather than by
    # prefix — the heuristic below infers, a rule states. This is checked *before
    # the no-groups early return* on purpose: a session that collected no
    # fieldmaps at all must still fail a binding it cannot honor, exactly as a
    # session that collected the wrong ones does. Skipping it there was a silent
    # degradation — the project said which pair to use and got none, quietly.
    wanted = _lookup_fmap_rule(rules, task, run)
    if wanted is not None:
        # ``none`` opts a task out of distortion correction entirely. A real
        # group could in principle be keyed "none" (from a series named
        # ``se_epi_ap_none``); if one is, the actual data wins over the sentinel.
        if wanted.lower() == _NO_FMAP and _NO_FMAP not in fieldmaps.groups:
            assignments[cache_key] = _NO_FMAP
            return None
        if wanted not in complete:
            # Not the bare word "none" — that is the opt-out sentinel, and
            # "Groups detected here: none" would read as naming it.
            known = ", ".join(sorted(fieldmaps.groups)) or "(no fieldmaps in this session)"
            reason = (
                f"holds only one phase-encoding direction "
                f"({', '.join(sorted(fieldmaps.groups[wanted])).upper()})"
                if wanted in fieldmaps.groups
                else "does not exist in this session"
            )
            subject = f"task '{task}' run {run}" if run is not None else f"task '{task}'"
            raise ValueError(
                f"[fmap_mapping] binds {subject} to fieldmap group "
                f"'{wanted}', but that group {reason}. Groups detected here: "
                f"{known}. Fix the rule in the project config, set the group to "
                f"'{_NO_FMAP}' if this task shouldn't be distortion-corrected, or "
                f"drop the rule to fall back to automatic assignment."
            )
        assignments[cache_key] = wanted
        return wanted

    groups = complete or list(fieldmaps.groups.keys())
    if not groups:
        return None

    # Try matching by name. A group reacquired within one session is keyed
    # "<name>-2", "<name>-3", … so match on the base name; the first pair wins,
    # which is the documented no-temporal-proximity limitation (TODO #5) and the
    # case an explicit rule above exists to settle.
    for g in groups:
        base = re.sub(r"-\d+$", "", g)
        if base and task.lower().startswith(base.lower()):
            assignments[cache_key] = g
            return g

    # Default to first group
    assignments[cache_key] = groups[0]
    return groups[0]


def config_to_json(config: dict, indent: int = 2) -> str:
    """Serialize dcm2bids config dict to formatted JSON string."""
    import json

    return json.dumps(config, indent=indent)
