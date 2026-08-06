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

**Fieldmap binding.** BIDS expresses fieldmap intent with two keys pointing in
opposite directions, and getting them the wrong way round fails *silently*: the
fieldmap is estimated from every scan sharing a ``B0FieldIdentifier`` and applied
to every scan sharing a ``B0FieldSource``. So a **fieldmap** carries
``B0FieldIdentifier`` (it is an input to the estimation) and a **bold or sbref**
carries ``B0FieldSource`` (it consumes the estimate). Inverting them produces a
valid-looking dataset that no tool complains about and on which fMRIPrep quietly
reports "Susceptibility distortion correction: None" — which duckbrain shipped
and real runs confirmed. Never swap these.

Which fieldmap pair a bold's ``B0FieldSource`` points
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
fieldmaps and no binding are unaffected: no ``B0FieldSource`` is written, no
``fmap`` descriptions are emitted, and fMRIPrep simply runs without SDC.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, TypedDict

from .dicom_inspect import (
    _SBREF_SUFFIX,
    FieldmapDetection,
    SeriesInfo,
    extract_task_label,
    is_complete_group,
    parse_task_run,
    phase_encoding_direction_token,
    reproin_entities,
    sanitize_task_label,
    split_trailing_index,
)

# One vocabulary, two consumers: the emitter below picks from it and the
# Conversion page's Type dropdown offers it. Kept in series_types because that
# module is what makes a declaration legal, so a suffix duckbrain can write and a
# suffix a user may declare cannot drift apart.
from .series_types import BIDS_ANAT_SUFFIXES as _BIDS_ANAT_SUFFIXES

if TYPE_CHECKING:
    from ..config import Config


class _DescriptionKeys(TypedDict):
    """The four keys every description duckbrain emits carries."""

    id: str
    datatype: str
    suffix: str
    criteria: dict[str, Any]


class Description(_DescriptionKeys, total=False):
    """One entry of a dcm2bids config's ``descriptions`` list.

    Split across two classes because ``custom_entities`` and ``sidecar_changes``
    are genuinely optional — an anat with no ``acq-`` label carries neither, and
    both are added conditionally after the literal is built. ``NotRequired``
    would say the same thing in one class, but it is 3.11 and the floor is 3.10;
    a required base plus a ``total=False`` subclass is the older spelling of
    exactly that, with no new dependency (TODO #33.2 verified the semantics
    under ``--strict`` on the 3.10 venv before this was written).

    ``criteria`` and ``sidecar_changes`` stay ``dict[str, Any]`` on purpose.
    duckbrain only ever writes ``SeriesNumber``/``EchoNumber`` into the first
    and three known keys into the second, but the same shape is read back out of
    a **hand-edited** config by :mod:`~duckbrain.core.conversion_plan`, where
    anything dcm2bids accepts may appear — a ``SeriesDescription`` glob most
    obviously. Narrowing them here would make the import path lie.

    This is not the same list as ``conversion_plan._KNOWN_DESC_KEYS``, which
    holds the keys the *conversion table* can render. They agree today. They are
    kept separate because a seventh key emitted here should make that check
    report loss, which is exactly what deriving one from the other would hide.
    """

    custom_entities: str
    sidecar_changes: dict[str, Any]


#: A whole dcm2bids config — the JSON file duckbrain writes and dcm2bids reads.
#:
#: **Not** :data:`duckbrain.config.Config`, which is duckbrain's own layered TOML.
#: Both are ``dict[str, Any]``, both are called ``config``, and three functions
#: had already collected the wrong one of the two in a reader's head — which is
#: the whole reason either is named.
#:
#: Deliberately not a ``TypedDict``, though :func:`generate_config`'s return is
#: precise enough to be one. Every function annotated with this reads a config
#: back **off disk**, where a user may have hand-edited in any key dcm2bids
#: accepts (``dcm2niixOptions``, ``search_method``, ``post_op``); the import path
#: exists to *report* those as unrepresentable, and a closed TypedDict would make
#: reading them an error rather than the finding they are.
Dcm2BidsConfig = dict[str, Any]


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
    correction* — no ``B0FieldSource`` is written, which is the right answer
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


def _shared_task_stems(
    parsed: dict[int, tuple[str, int | None]],
) -> dict[int, tuple[str, int]]:
    """Find task labels that are really one task plus a bare run index.

    LCNI protocols overwhelmingly name repeats by suffixing the console name
    ('MAB1', 'MAB2', 'MAB3'; 'route1'…'route6'). Read one at a time those are
    three unrelated tasks, and duckbrain emitted ``task-MAB1_run-1``,
    ``task-MAB2_run-1``, … — the run entity meaningless and the task label
    different for every repeat of the same paradigm.

    The evidence that a trailing number is a run index is that *another series in
    the same session shares the stem and carries a different index*. That is a
    fact about the session, not a guess about vocabulary, so a lone 'EPI196'
    (matrix size, no sibling) is left alone. Requiring distinct indices also
    keeps a genuinely repeated acquisition of one name from being collapsed.

    Returns ``{series_number: (stem, run_index)}`` for the series it claims.
    """
    groups: dict[str, list[tuple[int, int]]] = {}
    for series_number, (task, run_token) in parsed.items():
        if run_token is not None:
            continue
        stem, index = split_trailing_index(task)
        if index is None or not stem:
            continue
        groups.setdefault(stem.lower(), []).append((series_number, index))

    claimed: dict[int, tuple[str, int]] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        if len({index for _, index in members}) != len(members):
            continue
        for series_number, index in members:
            stem, _ = split_trailing_index(parsed[series_number][0])
            claimed[series_number] = (sanitize_task_label(stem), index)
    return claimed


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
    parsed = {}
    for s in func:
        parsed[s.series_number] = parse_task_run(s.description, template)
    shared = _shared_task_stems(parsed)

    for s in func:
        # A rule overrides only the task; the run still comes from the name token
        # (else acquisition-order counting), so repeats never collide.
        parsed_task, run_token = parsed[s.series_number]
        rule = lookup.get(s.description.strip().lower())
        if rule is not None:
            task = rule.task
        elif run_token is None and s.series_number in shared:
            # 'MAB1'/'MAB2'/'MAB3' is one task acquired three times, not three
            # tasks. Only trusted because siblings in this session share the
            # stem — see _shared_task_stems.
            task, run_token = shared[s.series_number]
        else:
            task = parsed_task
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
        # Its own name, not the BOLD loop's `run`: a BOLD always ends up with a
        # run index (counted if the name carries no token), whereas an SBRef with
        # no paired BOLD and no token keeps `None` and emits no `run-` entity.
        if pair is not None:
            task, sbref_run = pair
        else:
            parsed_task, sbref_run = parse_task_run(base, template)
            rule = lookup.get(base.strip().lower())
            task = rule.task if rule is not None else parsed_task
        entries.append(TaskRunEntry(s.series_number, s.description, "sbref", task, sbref_run))

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


def task_rules_from_config(config: Config) -> list[TaskRule]:
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


def task_rules_to_config_section(rules: list[TaskRule]) -> dict[str, Any]:
    """Serialize rules into a TOML-friendly ``[task_mapping]`` section."""
    return {"rule": [{"description": r.description, "task": r.task} for r in rules]}


def fmap_rules_from_config(config: Config) -> list[FmapRule]:
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


def fmap_rules_to_config_section(rules: list[FmapRule]) -> dict[str, Any]:
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
    return {(sanitize_task_label(r.task).lower(), r.run): r.group for r in rules if r.task}


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


def _without_skipped_groups(
    fieldmaps: FieldmapDetection, skip: Collection[int]
) -> FieldmapDetection:
    """Drop every fieldmap group that lost a member to ``skip``.

    A pair estimates the field from both of its halves, so omitting one does not
    leave a usable fieldmap behind — it leaves nothing. Emitting the surviving
    half anyway would write a ``fmap/`` file that no scan can be corrected from
    and that fMRIPrep will pick up and fail on, which is the silently-degrading
    shape ``CLAUDE.md`` forbids. Dropping the whole group instead means the bolds
    bound to it fall through to no ``B0FieldSource``, and the plan says so.

    Returns a copy; the caller's detection is left intact, because the GUI still
    renders the full set of detected pairs beside the table.
    """
    skip = set(skip)
    if not skip:
        return fieldmaps
    doomed = {g for g, dirs in fieldmaps.groups.items() if skip & set(dirs.values())}
    if not doomed:
        return fieldmaps
    return replace(
        fieldmaps,
        groups={g: d for g, d in fieldmaps.groups.items() if g not in doomed},
        group_entities={g: e for g, e in fieldmaps.group_entities.items() if g not in doomed},
        group_times={g: t for g, t in fieldmaps.group_times.items() if g not in doomed},
        deprioritized={g for g in fieldmaps.deprioritized if g not in doomed},
    )


def generate_config(
    series_list: list[SeriesInfo],
    fieldmaps: FieldmapDetection,
    subject: str = "",
    session: str = "",
    mapping: list[TaskRunEntry] | None = None,
    template: str | None = None,
    fmap_rules: list[FmapRule] | None = None,
    skip: Collection[int] | None = None,
) -> dict[str, list[Description]]:
    """Build a dcm2bids-compatible config dict from classified DICOM series.

    Parameters
    ----------
    series_list : list[SeriesInfo]
        Classified series from dicom_inspect.classify_series().
    fieldmaps : FieldmapDetection
        Fieldmap detection results.
    subject : str
        Subject label (for B0 field identifier naming).
    session : str
        Session label (for B0 field identifier naming).
    mapping : list[TaskRunEntry], optional
        The task/run mapping to use as the source of truth for func/sbref
        naming. If omitted, one is seeded with :func:`build_task_run_mapping`
        (using ``template``). Pass an edited mapping to honor user corrections.
    template : str, optional
        Glob-like naming template used only when ``mapping`` is not supplied.
    fmap_rules : list[FmapRule], optional
        Project-wide ``task -> fieldmap group`` bindings; each wins over the
        name-matching heuristic for the task it names.
    skip : collection of int, optional
        Series numbers to leave unconverted. A skipped series gets no
        description, which is exactly how the config format already expresses
        "not converted" — so the omission survives a save/reload round trip with
        no extra state, and :func:`~duckbrain.core.conversion_plan.plan_conversion`
        reports it as dropped without being told about the skip separately.

        Skipping one half of a fieldmap pair drops the whole group; see
        :func:`_without_skipped_groups`.

    Returns
    -------
    dict
        dcm2bids config with {"descriptions": [...]}.

    Raises
    ------
    ValueError
        If an ``fmap_rules`` entry names a group this session doesn't have, or
        one that holds only a single phase-encoding direction. A group skipped
        out of existence raises through the same path, which is the intended
        reading: the project asked for a binding the session can no longer honor.
    """
    descriptions: list[Description] = []
    sub_ses = f"sub{subject}ses{session}" if subject and session else ""
    skipped = set(skip or ())
    fieldmaps = _without_skipped_groups(fieldmaps, skipped)

    if mapping is None:
        mapping = build_task_run_mapping(series_list, template)
    entry_by_series = {e.series_number: e for e in mapping}

    # Track which fieldmap group each (task, run) is bound to
    fmap_group_assignments: dict[tuple[str, int | None], str] = {}
    fmap_rule_lookup = _fmap_rule_lookup(fmap_rules)

    # --- Anatomicals ---
    for s in series_list:
        if s.classification != "anat" or s.series_number in skipped:
            continue
        anat_desc = _anat_description(s)
        if anat_desc:
            descriptions.append(anat_desc)

    # --- Functionals (BOLD) ---
    func_series = [
        s for s in series_list if s.classification == "func" and s.series_number not in skipped
    ]
    for s in func_series:
        entry = entry_by_series.get(s.series_number)
        # Sanitize regardless of source: the heuristic already yields a valid
        # label, but a user-entered mapping edit or project rule (entry.task) can
        # carry an underscore/space/hyphen that would break the BIDS entity.
        task = sanitize_task_label(entry.task if entry else extract_task_label(s.description))
        run = entry.run if entry else None
        run_suffix = f"-run{run}" if run is not None else ""
        acq_suffix = f"-{s.acq_label}" if s.acq_label else ""
        custom_entities = _func_entities(task, s.acq_label, run)

        bold_desc: Description = {
            "id": f"func-bold-{task}{acq_suffix}{run_suffix}",
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

        # Assign the B0FieldSource. Called unconditionally rather than behind a
        # "were any fieldmaps detected" guard: with none detected it returns None
        # and nothing is written (unchanged), but a project binding that names a
        # group still gets to fail instead of being skipped along with everything
        # else. That guard is what let an unhonorable rule pass silently.
        fmap_group = _assign_fmap_group(
            task,
            run,
            fieldmaps,
            fmap_group_assignments,
            fmap_rule_lookup,
            series_time=s.header.series_time if s.header is not None else None,
        )
        if fmap_group is not None:
            bold_desc["sidecar_changes"]["B0FieldSource"] = _b0_identifier(fmap_group, sub_ses)

        descriptions.append(bold_desc)

    # --- SBRef ---
    for s in series_list:
        if s.classification != "sbref" or s.series_number in skipped:
            continue
        entry = entry_by_series.get(s.series_number)
        # Sanitize regardless of source: the heuristic already yields a valid
        # label, but a user-entered mapping edit or project rule (entry.task) can
        # carry an underscore/space/hyphen that would break the BIDS entity.
        task = sanitize_task_label(entry.task if entry else extract_task_label(s.description))
        run = entry.run if entry else None
        run_suffix = f"-run{run}" if run is not None else ""
        acq_suffix = f"-{s.acq_label}" if s.acq_label else ""
        custom_entities = _func_entities(task, s.acq_label, run)
        sbref_desc: Description = {
            "id": f"func-sbref-{task}{acq_suffix}{run_suffix}",
            "datatype": "func",
            "suffix": "sbref",
            "criteria": {
                "SeriesNumber": s.series_number,
            },
            "custom_entities": custom_entities,
        }

        # An SBRef is acquired with the same readout as its BOLD, so it carries
        # the same distortions and needs the same correction. It also matters
        # more than it looks: fMRIPrep uses an SBRef, when present, to build the
        # BOLD reference that coregistration and SDC operate on — so leaving it
        # unassociated makes the reference the one image in the chain nothing
        # corrects. This runs after the BOLD loop, so the (task, run) assignment
        # is already cached and the pair is guaranteed to match the BOLD's.
        fmap_group = _assign_fmap_group(
            task,
            run,
            fieldmaps,
            fmap_group_assignments,
            fmap_rule_lookup,
            series_time=s.header.series_time if s.header is not None else None,
        )
        if fmap_group is not None:
            sbref_desc["sidecar_changes"] = {"B0FieldSource": _b0_identifier(fmap_group, sub_ses)}

        descriptions.append(sbref_desc)

    # --- Diffusion ---
    # After the SBRef pass so the two diffusion suffixes are adjacent in the
    # output, and before fieldmaps because nothing here reads a fieldmap group:
    # see _dwi_description for why a diffusion series gets no B0FieldSource.
    for s in series_list:
        if s.classification != "dwi" or s.series_number in skipped:
            continue
        descriptions.append(_dwi_description(s))

    # --- Fieldmaps ---
    # Stripping illegal characters can map two group names onto one identifier
    # ("2.5mm" and "25mm"), which would hand fMRIPrep two pairs as a single
    # estimator and correct every bold from the wrong images — processed-looking
    # output, silently deformed. Fail instead; the group names come from series
    # descriptions, so the fix is to rename a sequence on the console.
    by_identifier: dict[str, str] = {}
    for group_name in fieldmaps.groups:
        gid = _b0_identifier(group_name, sub_ses)
        if gid in by_identifier:
            raise ValueError(
                f"Fieldmap groups '{by_identifier[gid]}' and '{group_name}' both "
                f"reduce to the B0 identifier '{gid}' once characters illegal in "
                f"a nipype node name are removed. fMRIPrep would treat the two "
                f"pairs as one fieldmap. Rename one of the source series so the "
                f"groups differ by more than punctuation."
            )
        by_identifier[gid] = group_name

    for group_name, group_dirs in fieldmaps.groups.items():
        group_id = _b0_identifier(group_name, sub_ses)
        # Extra entity (acq-/run-) that keeps multiple pairs from colliding on the
        # same dir-<X> filename; empty for the lone-pair case.
        extra_entity = fieldmaps.group_entities.get(group_name, "")

        if "ap" in group_dirs:
            descriptions.append(
                _fmap_description(group_dirs["ap"], "AP", group_id, group_name, extra_entity)
            )
        if "pa" in group_dirs:
            descriptions.append(
                _fmap_description(group_dirs["pa"], "PA", group_id, group_name, extra_entity)
            )
        if "magnitude" in group_dirs and "phasediff" in group_dirs:
            descriptions.extend(
                _gre_fmap_descriptions(
                    group_dirs["magnitude"],
                    group_dirs["phasediff"],
                    group_id,
                    group_name,
                    extra_entity,
                )
            )

    _disambiguate(descriptions, "anat")
    _disambiguate_dwi(descriptions, series_list)

    return {"descriptions": descriptions}


def resolve_fmap_assignments(
    mapping: list[TaskRunEntry],
    fieldmaps: FieldmapDetection,
    fmap_rules: list[FmapRule] | None = None,
    series_times: dict[int, float] | None = None,
) -> dict[tuple[str, int | None], str]:
    """Report ``(task, run) -> fieldmap group`` exactly as :func:`generate_config` binds it.

    Keyed on the pair rather than the task because a binding is per-run: two runs
    of one task can legitimately point at different pairs (a fieldmap re-shot
    mid-task), and a task-keyed report could not show that.

    The binding is otherwise only visible as ``B0FieldSource`` strings buried
    in the generated JSON, which is a poor way to check that a rule did what was
    intended. Runs the same bold-only, sanitized-label loop against the same
    assignment function, so it cannot drift from what is actually written — and
    it raises on an unsatisfiable rule for the same reason.

    A task bound to ``"none"`` is reported as such rather than omitted: opting a
    run out of distortion correction is a decision worth seeing in the table, not
    an absence. Tasks with no binding and no fieldmaps to assign are absent.

    ``series_times`` (``{series_number: acquisition seconds}``) must be supplied
    for the report to match a nearest-in-time binding — without it the timing
    tier can't fire here and the preview would show the old first-group choice
    while generate_config wrote the time-matched one. generate_config reads the
    time straight off each series' header; this path only has the mapping, so
    the caller passes the lookup.
    """
    assignments: dict[tuple[str, int | None], str] = {}
    lookup = _fmap_rule_lookup(fmap_rules)
    times = series_times or {}
    for entry in mapping:
        if entry.role != "bold":
            continue
        _assign_fmap_group(
            sanitize_task_label(entry.task),
            entry.run,
            fieldmaps,
            assignments,
            lookup,
            series_time=times.get(entry.series_number),
        )
    return assignments


# BIDS anatomical suffixes a ReproIn ``anat-<label>`` may name. Spelled out
# rather than passed through, so a console typo becomes an unconverted series the
# user can see rather than an invalid BIDS suffix written into the dataset.
def _anat_description(series: SeriesInfo) -> Description | None:
    """Build an anat description entry.

    A project ``[series_types]`` declaration outranks everything here, ReproIn
    included: it is the study stating the suffix, where all three paths below
    infer one. That is also what makes an editable Type honest — declaring an
    anatomical without saying *which* would fall through to the name vocabulary,
    which for a study-specific name fires nothing and returns ``None``, dropping
    the series without a word. See :mod:`duckbrain.core.series_types`.

    A ReproIn ``anat-<label>`` names its BIDS suffix outright, so it is trusted
    ahead of the vocabulary matching below. Without this, an anat whose label
    isn't in that vocabulary (``anat-PDw``, ``anat-UNIT1``) returned None and the
    series was dropped from the conversion silently.

    The header's ``suffix_hint`` is the *last* resort, after the name vocabulary
    rather than before it, so a hint can only rescue a series the name would have
    dropped — never relabel one the name already named. A ``mprage``-named series
    stays ``T1w`` whatever the header hints.
    """
    # Used verbatim, with no membership check: parse_type_token is the only thing
    # that sets this field and it canonicalizes against the same vocabulary, so a
    # `.get()` here would be a fallback for a state that cannot arise — and a
    # fallback is precisely what a declaration must not have.
    if series.declared_suffix:
        return _anat_entry(series, series.declared_suffix)

    reproin = reproin_entities(series.description)
    if reproin.get("seqtype") == "anat":
        suffix = _BIDS_ANAT_SUFFIXES.get(reproin.get("suffix", "").lower())
        if suffix:
            return _anat_entry(series, suffix)

    desc_lower = series.description.lower()

    # Token-anchored for the same reason as the classifier's vocabulary: a bare
    # ``"t1_" in desc`` also fires on 'BART1_…' and 'SST2_…'. The two must agree,
    # or a series routes here as anat and then picks the wrong suffix.
    if _ANAT_T1.search(desc_lower) or "mprage" in desc_lower:
        suffix = "T1w"
    elif _ANAT_T2.search(desc_lower):
        suffix = "T2w"
    elif "flair" in desc_lower:
        suffix = "FLAIR"
    else:
        suffix = _BIDS_ANAT_SUFFIXES.get((series.suffix_hint or "").lower())
        if not suffix:
            return None

    return _anat_entry(series, suffix)


def anat_suffix_for(series: SeriesInfo) -> str:
    """The BIDS suffix this anatomical will actually be written under, or ``""``.

    Answered by *calling the emitter* rather than by re-running its vocabulary,
    which is the same anti-drift stance :func:`resolve_fmap_assignments` takes
    and the reason the Conversion page's Type column can show ``anat/T1w``
    without inventing a second suffix derivation. ``""`` is the honest answer for
    an anat nothing pins a suffix on — that series converts to nothing, and the
    bare ``anat`` the page then shows is exactly the case the Type control exists
    to let a user fix.
    """
    if series.classification != "anat":
        return ""
    entry = _anat_description(series)
    return entry["suffix"] if entry else ""


def _func_entities(task: str, acq_label: str, run: int | None) -> str:
    """Compose a func/sbref ``custom_entities`` string in BIDS entity order.

    ``acq-`` sits between ``task-`` and ``run-``; BIDS fixes that order, and
    dcm2bids writes ``custom_entities`` through verbatim.
    """
    parts = [f"task-{task}"]
    if acq_label:
        parts.append(f"acq-{acq_label}")
    if run is not None:
        parts.append(f"run-{run}")
    return "_".join(parts)


def _anat_entry(series: SeriesInfo, suffix: str) -> Description:
    """One anat description, carrying an ``acq-`` entity when it needs one.

    ``acq_label`` is set only where two reconstructions of the same acquisition
    both convert, which is the one case where an anat would otherwise write two
    images to a single filename. A lone survivor keeps the plain name — same
    stance as a single fieldmap pair keeping the bare ``dir-<X>_epi``.
    """
    entry: Description = {
        "id": f"anat-{suffix}",
        "datatype": "anat",
        "suffix": suffix,
        "criteria": {"SeriesNumber": series.series_number},
    }
    if series.acq_label:
        entry["custom_entities"] = f"acq-{series.acq_label}"
        entry["id"] = f"anat-{suffix}-{series.acq_label}"
    return entry


def _dwi_description(series: SeriesInfo) -> Description:
    """One diffusion description — the volume series, or its reference.

    **Returns a description unconditionally**, where :func:`_anat_description`
    returns ``dict | None``. That is not an oversight to tidy up later: an anat's
    suffix comes from a name vocabulary that can fail to fire, so there is a real
    "nothing to write" case. Diffusion has no such ladder — the suffix is ``dwi``
    or ``sbref`` and both are always known — and ``dir-`` is *decoration*, not a
    precondition. A diffusion series whose name carries no direction token still
    writes ``sub-X_dwi.nii.gz``; adding a ``return None`` for that case would drop
    the commonest single-direction acquisition there is.

    ``.bval``/``.bvec`` need no handling here. dcm2bids moves every companion
    dcm2niix produced — its ``Dcm2BidsGen.move`` globs ``<srcRoot>.*`` and
    whitelists ``.nii``/``.gz``/``.json``/``.bval``/``.bvec`` — so claiming the
    series is the whole of what duckbrain has to do. Verified end to end on
    `mmmsourcedata` and on the LCNI `Round_Robin` sessions.

    **No ``B0FieldSource``**, deliberately. duckbrain runs no diffusion
    preprocessing, so nothing would consume it; :func:`_assign_fmap_group` is
    keyed on ``(task, run)`` and diffusion has no task; and the nearest-in-time
    binding it implements is validated for BOLD only. The decisive reason is
    reviewability, though: :func:`resolve_fmap_assignments` filters
    ``role != "bold"``, and that is what the Conversion page's `fieldmap` column
    renders from — so a binding chosen here would be applied silently and could
    not be overridden, which is the shape ``CLAUDE.md`` forbids. Revisit when
    there is a diffusion stage to consume it, not before.
    """
    suffix = "sbref" if series.suffix_hint == "sbref" else "dwi"
    return _dwi_entry(series, suffix, phase_encoding_direction_token(series.description))


def _dwi_entry(series: SeriesInfo, suffix: str, direction: str) -> Description:
    """One dwi description, with its entities in BIDS order.

    ``acq-`` before ``dir-``, matching :func:`_fmap_description`; ``run-`` is
    appended afterwards by :func:`_disambiguate` when a direction repeats. The
    ``acq-`` label comes from the ND policy exactly as an anat's does — the twin
    machinery is classification-agnostic, so a diffusion series reconstructed
    twice really does arrive here with one.
    """
    parts = []
    if series.acq_label:
        parts.append(f"acq-{series.acq_label}")
    if direction:
        parts.append(f"dir-{direction.upper()}")
    custom_entities = "_".join(parts)

    entry: Description = {
        "id": "-".join(p for p in ("dwi", suffix, series.acq_label, direction.lower()) if p),
        "datatype": "dwi",
        "suffix": suffix,
        "criteria": {"SeriesNumber": series.series_number},
    }
    if custom_entities:
        entry["custom_entities"] = custom_entities
    return entry


_ANAT_T1 = re.compile(r"(?<![a-z0-9])t1(?:w|[_-])")
_ANAT_T2 = re.compile(r"(?<![a-z0-9])t2(?:w|[_-])")


def _disambiguate(
    descriptions: list[Description], datatype: str, suffix: str = ""
) -> dict[int, int]:
    """Give repeated series of one datatype a ``run-`` entity so they stop colliding.

    An anat description carried no entities at all, so every T1w in a session
    resolved to the same ``id`` *and* the same output filename. A protocol that
    reshoots a moved MPRAGE, or acquires a fast localiser-quality T1 alongside
    the full one, therefore wrote two or three images to one path and kept
    whichever dcm2bids happened to write last — with the plan's collision check
    the only signal, and only on the interactive page. Diffusion repeats the same
    way when a session shoots one direction twice.

    ``run-`` is added only when a suffix actually repeats, so the common
    single-anatomical session keeps its plain ``sub-X_T1w`` name. Numbering is by
    acquisition order, which is what the ``SeriesNumber`` criteria already sort by.

    Grouped by ``(suffix, custom_entities)`` and not by suffix alone, so two
    reconstructions of one acquisition — ``acq-nd`` and ``acq-dis`` — are not
    treated as repeats. They are already distinct filenames, and ``run-`` would
    be a false claim about them: it means the scan was *acquired* more than once.
    Two genuine repeats within one ``acq-`` still number normally.

    ``suffix`` narrows the pass to one suffix within the datatype; diffusion uses
    it to number the volume series alone and then hand those numbers to the
    references, rather than numbering each suffix independently. Returns
    ``{series_number: run}`` so the caller can do that.
    """
    by_suffix: dict[tuple[str, str], list[Description]] = {}
    for d in descriptions:
        if d.get("datatype") != datatype:
            continue
        if suffix and d.get("suffix") != suffix:
            continue
        key = (d["suffix"], d.get("custom_entities", ""))
        by_suffix.setdefault(key, []).append(d)

    runs: dict[int, int] = {}
    for group in by_suffix.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda d: d["criteria"]["SeriesNumber"])
        for index, d in enumerate(group, start=1):
            _add_run_entity(d, index)
            runs[d["criteria"]["SeriesNumber"]] = index
    return runs


def _add_run_entity(description: Description, run: int) -> None:
    """Append ``run-N`` to a description's entities and id, in BIDS order."""
    existing = description.get("custom_entities", "")
    description["custom_entities"] = f"{existing}_run-{run}" if existing else f"run-{run}"
    description["id"] = f"{description['id']}-run{run}"


def _disambiguate_dwi(descriptions: list[Description], series_list: list[SeriesInfo]) -> None:
    """Number repeated diffusion runs, and give each reference its sibling's number.

    **The two suffixes must not be numbered independently.** Doing so is correct
    only when the repeats are balanced, and a session where one volume series was
    aborted is exactly when they are not: with references 1/2/3 and volumes 1/3
    surviving, independent numbering makes ``dir-AP_run-2_sbref`` claim to be the
    reference for ``dir-AP_run-2_dwi``, which is the *third* acquisition. Wrong
    pairing, no warning. The functional path never has this problem because a
    BOLD and its SBRef read one shared ``(task, run)`` mapping keyed on series
    number; this is the diffusion equivalent of that mapping.

    So: number the volume series, then hand each reference the run of the volume
    it belongs to — matched on the ``_SBRef``-stripped description, which is the
    same relation :func:`~duckbrain.core.dicom_inspect._recover_dwi_sbref_from_sibling`
    used to call it diffusion in the first place, and nearest-in-series-number
    one-to-one where a description repeats. A reference left over keeps its
    unnumbered entities, so it matches no volume and the plan's ``orphan-sbref``
    check names it — which is the honest outcome for a reference whose volume
    series is not being written.
    """
    runs = _disambiguate(descriptions, "dwi", suffix="dwi")
    if not runs:
        return

    desc_by_series = {s.series_number: s.description for s in series_list}
    refs = [d for d in descriptions if d.get("datatype") == "dwi" and d.get("suffix") == "sbref"]
    unclaimed = {
        d["criteria"]["SeriesNumber"]: d
        for d in refs
        if d["criteria"]["SeriesNumber"] in desc_by_series
    }

    for volume_series in sorted(runs):
        base = desc_by_series.get(volume_series, "").strip().lower()
        candidates = [
            n
            for n, d in unclaimed.items()
            if _SBREF_SUFFIX.sub("", desc_by_series[n]).strip().lower() == base
        ]
        if not candidates:
            continue
        nearest = min(candidates, key=lambda n: (abs(n - volume_series), n))
        _add_run_entity(unclaimed.pop(nearest), runs[volume_series])


_B0_ILLEGAL = re.compile(r"[^A-Za-z0-9_-]+")


def _b0_identifier(group_name: str, sub_ses: str) -> str:
    """Compose the ``B0map_…`` string binding a fieldmap to the scans it corrects.

    The group name arrives straight off the scanner's series description
    (``se_epi_2.5mm_ap`` yields the group ``2.5mm``), and sdcflows names a nipype
    node after whatever it reads from ``B0FieldIdentifier``. nipype accepts only
    ``[\\w-]`` in a node name, so a period aborts fMRIPrep at workflow-build time
    with ``Node name "out_B0map_2.5mm" is not valid`` — before a single volume is
    processed. Dropping the illegal characters is the whole fix.

    Hyphens and underscores are legal and are deliberately **kept**: the
    repeat-pair suffix (``encoding-2``) and ``sub_ses`` both need them to stay
    distinguishable, which is why this is narrower than
    :func:`~duckbrain.core.dicom_inspect.sanitize_task_label` — that one targets
    BIDS entity values, which must be strictly alphanumeric, and would collapse
    ``encoding-2`` into ``encoding2``.

    An empty group name stays empty (``B0map_``). The lone unnamed pair is the
    common case and was always valid.
    """
    composed = f"B0map_{group_name}_{sub_ses}" if sub_ses else f"B0map_{group_name}"
    return _B0_ILLEGAL.sub("", composed)


def _gre_fmap_descriptions(
    magnitude_series: int,
    phase_series: int,
    b0_field_id: str,
    group_name: str = "",
    extra_entity: str = "",
) -> list[Description]:
    """Build the three descriptions a gradient-echo fieldmap produces.

    One magnitude *series* holds two echoes, and dcm2niix splits it into
    ``magnitude1`` and ``magnitude2``; the phase series becomes ``phasediff``.
    So ``SeriesNumber`` alone — the only criteria key duckbrain otherwise uses —
    cannot separate the two magnitudes, and ``EchoNumber`` has to join it. That
    key is present in every sidecar dcm2niix writes for a multi-echo series.

    ``EchoTime1``/``EchoTime2`` are deliberately not written: BIDS requires them
    on a phasediff, and dcm2niix already computes both from the two echoes and
    puts them in the sidecar. Injecting a second copy from a header duckbrain
    read separately could only disagree with the data — the same trap as
    forcing PhaseEncodingDirection, described in _fmap_description below.

    All three carry ``B0FieldIdentifier``: sdcflows treats the files sharing one
    identifier as the inputs to a single field estimator, and a phasediff
    estimator needs its magnitude to mask with.
    """
    parts = [p for p in extra_entity.split("_") if p]
    acq = next((p for p in parts if p.startswith("acq-")), "")
    run = next((p for p in parts if p.startswith("run-")), "")
    custom_entities = "_".join(p for p in (acq, run) if p)

    id_suffix = f"-{group_name}" if group_name else ""

    def entry(suffix: str, criteria: dict[str, Any]) -> Description:
        description: Description = {
            "id": f"fmap-{suffix.lower()}{id_suffix}",
            "datatype": "fmap",
            "suffix": suffix,
            "criteria": criteria,
            "sidecar_changes": {"B0FieldIdentifier": b0_field_id},
        }
        if custom_entities:
            description["custom_entities"] = custom_entities
        return description

    return [
        entry("magnitude1", {"SeriesNumber": magnitude_series, "EchoNumber": 1}),
        entry("magnitude2", {"SeriesNumber": magnitude_series, "EchoNumber": 2}),
        entry("phasediff", {"SeriesNumber": phase_series}),
    ]


def _fmap_description(
    series_number: int,
    direction: str,
    b0_field_id: str,
    group_name: str = "",
    extra_entity: str = "",
) -> Description:
    """Build a fieldmap description entry.

    ``extra_entity`` (an ``acq-<label>`` or ``run-<n>`` token) distinguishes
    multiple fieldmap pairs in one session; it is placed in BIDS entity order
    (``acq`` before ``dir``, ``run`` after) and folded into the description id so
    ids stay unique across pairs.
    """
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
        # NOTE: PhaseEncodingDirection is deliberately NOT written here.
        #
        # It used to be forced to "j-"/"j" from the ``_ap``/``_pa`` token in the
        # series name. But dcm2niix already derives the real value from the DICOM
        # header (it is present in every sidecar it writes), so overwriting it
        # with a name-derived guess could only ever lose information: a no-op when
        # they agree, and wrong when they don't. And it is wrong in the worst
        # possible way — a mis-signed phase-encoding direction doesn't skip
        # distortion correction, it applies it backwards, deforming the data while
        # looking processed.
        #
        # Trusting a filename over the data is the same species of error as the
        # inverted B0 fields (see this module's header). The header wins; a
        # disagreement between it and the name is *reported* instead, by
        # ``consistency._check_pe_direction`` — a name/header mismatch is a
        # real signal about the acquisition, worth surfacing rather than silently
        # overwriting.
        "sidecar_changes": {
            "B0FieldIdentifier": b0_field_id,
        },
        "custom_entities": custom_entities,
    }


def _assign_fmap_group(
    task: str,
    run: int | None,
    fieldmaps: FieldmapDetection,
    assignments: dict[tuple[str, int | None], str],
    rules: dict[tuple[str, int | None], str] | None = None,
    series_time: float | None = None,
) -> str | None:
    """Assign a fieldmap group to one run of a task.

    Four sources, each overriding the one after it:

      1. an explicit project-wide :class:`FmapRule` binding (``rules``),
      2. a name match — the task label prefixed by the group's base name,
      3. the complete group acquired nearest this run in time,
      4. the first complete group.

    Only groups holding *both* directions are candidates. An aborted fieldmap
    leaves a lone AP that pairs with nothing, and it sorts first — real sessions
    do this (MMM_003_sess18 opens with two APs before the PA). Pointing a bold's
    ``B0FieldSource`` at a half-group would give fMRIPrep a distortion
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

    complete = [g for g, dirs in fieldmaps.groups.items() if is_complete_group(dirs)]

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

    # Complete pairs ONLY. This used to read `complete or list(groups)`, which
    # made every incomplete group a candidate whenever a session had no complete
    # one — so an aborted lone AP got bound after all (TODO #17.3), contradicting
    # both the Fieldmap Detection panel ("isn't offered below") and #4's closing
    # note. A half pair cannot estimate a field, so binding to it buys nothing and
    # costs a job: the per-session page hard-errored on a binding it had made
    # itself, and the bulk path submitted it. No complete pair means no binding,
    # which is an honest "no SDC" that plan_warnings already reports. An explicit
    # [fmap_mapping] rule naming a half group still raises above, unchanged.
    # Two reconstructions of one fieldmap are both complete and both bindable,
    # and they were acquired at the same instant — so the timing below cannot
    # separate them and would fall through to insertion order, which puts the
    # uncorrected copy first. Prefer the corrected one for *automatic* binding
    # while leaving `complete` intact, so an explicit rule naming the ND group
    # still validates and still wins.
    groups = [g for g in complete if g not in fieldmaps.deprioritized] or complete
    if not groups:
        return None

    # Try matching by name. A group reacquired within one session is keyed
    # "<name>-2", "<name>-3", … so match on the base name. A name match is the
    # console operator saying outright which pair goes with which task, so it
    # still outranks the timing below, which only infers it.
    for g in groups:
        base = re.sub(r"-\d+$", "", g)
        if base and task.lower().startswith(base.lower()):
            assignments[cache_key] = g
            return g

    # Nearest in acquisition time. A fieldmap is re-shot when the prescription
    # or the shim changes, so the pair a run belongs to is the one it was
    # acquired next to — before or after, whichever is closer. This replaces
    # "whichever pair sorts first", which was arbitrary and, on a session with
    # two pairs, wrong for every run after the second one: REV055 shoots
    # fieldmap1, then BART and SST, then fieldmap2, then React, and bound all
    # five runs to fieldmap1. Standard DICOM timing, so it works on both MR
    # dialects and every vendor — unlike the shim settings that are the actual
    # physical cause, which live in a Siemens private blob and aren't readable
    # before dcm2niix runs. TODO #5's standing note about no temporal proximity.
    nearest = _nearest_group_in_time(groups, fieldmaps.group_times, series_time)
    if nearest is not None:
        assignments[cache_key] = nearest
        return nearest

    # Default to first group
    assignments[cache_key] = groups[0]
    return groups[0]


def _nearest_group_in_time(
    groups: list[str], group_times: dict[str, float], series_time: float | None
) -> str | None:
    """The complete group acquired closest to ``series_time``.

    ``None`` when the timing can't decide — no time on this run, none on the
    groups, or a tie. A tie is deliberately not broken here: falling through to
    the caller's stable first-group choice is better than picking arbitrarily
    while looking principled.
    """
    if series_time is None or not group_times:
        return None
    timed = [(abs(group_times[g] - series_time), g) for g in groups if g in group_times]
    if not timed:
        return None
    timed.sort()
    if len(timed) > 1 and timed[0][0] == timed[1][0]:
        return None
    return timed[0][1]


def config_to_json(config: Dcm2BidsConfig, indent: int = 2) -> str:
    """Serialize dcm2bids config dict to formatted JSON string."""
    import json

    return json.dumps(config, indent=indent)
