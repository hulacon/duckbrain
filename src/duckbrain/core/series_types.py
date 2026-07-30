"""Declared series types — the tier above the header and the name.

:func:`~duckbrain.core.dicom_inspect.classify_series` reads a series' datatype
off the DICOM header where the header states it and off the series description
where it doesn't. Both are inferences, and the second one is a guess about a
console operator's free text: ``food``, ``Whack`` and ``WMS_R1`` are all ordinary
BOLD runs. When duckbrain reads one wrong it reads it wrong for *every subject in
the study*, because the protocol repeats — so the correction belongs in the
project config beside ``[task_mapping]`` and ``[fmap_mapping]``, not in one
session's table. This module is that section's vocabulary and its reader/writer.

**A declaration carries a BIDS suffix, not just a datatype**, and that is the
whole reason this is a module rather than one unlocked column. ``func`` and
``sbref`` determine their output outright (``bold`` / ``sbref``). ``anat`` does
not: :func:`~duckbrain.core.dcm2bids_config._anat_description` picks the suffix
out of the *name* vocabulary (``t1``/``t2``/``mprage``/``flair``) and returns
``None`` when nothing fires, dropping the series. So declaring ``food_r1`` to be
an anatomical, without saying which one, would write no file and say nothing —
the failure the control exists to prevent, reintroduced by the control. An anat
declaration therefore names its suffix and the emitter takes it verbatim.

**Two datatypes are deliberately not declarable**, because a label alone cannot
make either of them emit — offering them would be the silently-degrading option
``CLAUDE.md`` forbids:

``fmap``
    :func:`~duckbrain.core.dcm2bids_config._fmap_description` only writes for a
    series :func:`~duckbrain.core.dicom_inspect.detect_fieldmaps` has already
    paired, and pairing reads the phase-encoding direction out of the
    description. A series whose name carries no direction gets no pair and so no
    file however it is labelled; the fix for a missed fieldmap is a detection
    rule, not a declaration.
``dwi``
    duckbrain has no diffusion emission path at all (``TODO.md`` ``#19.1``).

The non-emitting classifications (``scout``, ``physio``, ``derived``,
``unknown``) are not declarable either, and that is a separate point: they are
about *not* converting, and not converting already has its own control — the
``convert`` checkbox on the Conversion page. A datatype is a claim about what a
series is; a skip is a decision about what to do with it. Collapsing them would
make relabelling the only way to drop a series.
"""

from __future__ import annotations

from dataclasses import dataclass

# BIDS anat suffixes duckbrain can write. Ordered, because this tuple is also the
# order the Conversion page's dropdown offers them in; the lookup below is
# derived from it so the two can never list different suffixes.
BIDS_ANAT_SUFFIX_NAMES = (
    "T1w",
    "T2w",
    "T1map",
    "T2map",
    "T2star",
    "FLAIR",
    "PDw",
    "PDT2",
    "UNIT1",
    "angio",
)

BIDS_ANAT_SUFFIXES = {s.lower(): s for s in BIDS_ANAT_SUFFIX_NAMES}

# Datatypes whose output suffix is fixed, so a declaration needs no second half.
FIXED_SUFFIXES = {"func": "bold", "sbref": "sbref"}

SEPARATOR = "/"

# Every value a declaration may take, in the order the dropdown offers them.
DECLARABLE_TYPES = tuple(f"anat{SEPARATOR}{s}" for s in BIDS_ANAT_SUFFIX_NAMES) + tuple(
    FIXED_SUFFIXES
)


@dataclass(frozen=True)
class TypeRule:
    """A project-wide datatype declaration keyed on SeriesDescription.

    ``description`` is matched case-insensitively (whitespace-stripped), the same
    key :class:`~duckbrain.core.dcm2bids_config.TaskRule` uses and for the same
    reason: series numbers are per-session, so a series-keyed rule could not
    generalize across subjects, while a protocol's descriptions repeat.

    ``suffix`` is the BIDS suffix the emitter must use — always populated, since
    :func:`parse_type_token` fills in the fixed one for ``func`` and ``sbref``.
    """

    description: str
    datatype: str
    suffix: str

    @property
    def token(self) -> str:
        """The declaration as the config and the GUI spell it (``anat/T1w``)."""
        return format_type_token(self.datatype, self.suffix)


def parse_type_token(token: str) -> tuple[str, str]:
    """Split a declaration (``anat/T1w``, ``func``) into ``(datatype, suffix)``.

    Raises ``ValueError`` for anything outside :data:`DECLARABLE_TYPES`. Refusing
    rather than falling back is the point of the whole module: a declaration that
    quietly reverted to the guess it was written to correct would leave the user
    looking at a table that says the correction took.
    """
    raw = str(token).strip()
    datatype, _, suffix = raw.partition(SEPARATOR)
    datatype = datatype.strip().lower()
    suffix = suffix.strip()

    if datatype in FIXED_SUFFIXES:
        fixed = FIXED_SUFFIXES[datatype]
        if suffix and suffix.lower() != fixed:
            raise ValueError(
                f"{raw!r} is not a series type duckbrain can declare: a "
                f"{datatype!r} series is always written as {fixed!r}."
            )
        return datatype, fixed

    if datatype == "anat":
        canonical = BIDS_ANAT_SUFFIXES.get(suffix.lower())
        if canonical:
            return "anat", canonical

    raise ValueError(
        f"{raw!r} is not a series type duckbrain can declare. Use one of: "
        f"{', '.join(DECLARABLE_TYPES)}."
    )


def format_type_token(datatype: str, suffix: str = "") -> str:
    """Spell a classification (+ suffix) the way a declaration spells it.

    Used for the *seed* value of the Conversion page's Type column as well as for
    declarations, so it has to render what duckbrain inferred too — including the
    classifications that are never declarable. A datatype whose suffix is fixed,
    unknown or irrelevant renders bare, so ``scout`` stays ``scout`` and a
    functional run stays ``func`` rather than becoming ``func/bold``.
    """
    datatype = (datatype or "").strip()
    suffix = (suffix or "").strip()
    if datatype == "anat" and suffix:
        canonical = BIDS_ANAT_SUFFIXES.get(suffix.lower())
        if canonical:
            return f"anat{SEPARATOR}{canonical}"
    return datatype


def token_datatype(token: str) -> str:
    """The datatype half of a Type cell, whether or not it carries a suffix.

    Deliberately tolerant, unlike :func:`parse_type_token`: every read of the
    Conversion page's Type column goes through this, and most of those cells hold
    an *inferred* classification (``scout``, ``fmap``, ``unknown``) that is not a
    legal declaration and must still answer "is this row a func row?".
    """
    return str(token or "").partition(SEPARATOR)[0].strip().lower()


def type_rule_lookup(rules: list[TypeRule] | None) -> dict[str, TypeRule]:
    """Index rules by normalized (stripped, lowercased) description; last wins."""
    return {r.description.strip().lower(): r for r in rules} if rules else {}


def type_rules_from_config(config: dict) -> list[TypeRule]:
    """Read declarations from a merged config's ``[series_types]``.

    **Raises on an unrecognised type**, where
    :func:`~duckbrain.core.dcm2bids_config.task_rules_from_config` and its
    neighbours skip a malformed row. The asymmetry is the same one
    :func:`~duckbrain.core.dicom_inspect.nd_policy_from_config` makes: a skipped
    task rule falls back to a heuristic duckbrain then *states* in the table, so
    the user can see what happened, whereas a skipped declaration falls back to
    the very misclassification it was written to correct — and the series either
    converts under the wrong datatype or silently doesn't convert at all. A row
    with no description is dropped, because there is nothing for it to name.
    """
    section = config.get("series_types") or {}
    out: list[TypeRule] = []
    for row in section.get("rule") or []:
        desc = str(row.get("description", "")).strip()
        token = str(row.get("type", "")).strip()
        if not desc:
            continue
        try:
            datatype, suffix = parse_type_token(token)
        except ValueError as exc:
            raise ValueError(f"[series_types] rule for {desc!r}: {exc}") from exc
        out.append(TypeRule(desc, datatype, suffix))
    return out


def type_rules_to_config_section(rules: list[TypeRule]) -> dict:
    """Serialize declarations into a TOML-friendly ``[series_types]`` section."""
    return {"rule": [{"description": r.description, "type": r.token} for r in rules]}
