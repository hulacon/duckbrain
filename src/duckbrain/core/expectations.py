"""Declared study expectations — what a session is *supposed* to contain.

Everything else in duckbrain derives its expectations from the data it is
judging. ``surveyor.discover_units`` builds the subject roster from the union of
what exists in sourcedata and BIDS; ``surveyor._expected_bold_keys`` gets the
expected BOLD list from the converted tree; ``_expected_conversion_counts`` gets
expected NIfTI counts from the dcm2bids config duckbrain itself emitted;
``consistency.py`` compares provenance sources against *each other*. Every one of
those is a comparison of the data with itself.

That circularity is a bug class, not a nitpick. A subject scanned but never
ingested, a run the scanner aborted, a series the heuristics mis-mapped and
dropped — in each case the expected set shrinks to match what happened and the
board reads COMPLETE. TODO #14 was the same shape one level down: every artifact
agreed with every other artifact and all of them were wrong together.

This module holds the one thing that cannot be re-derived: a **declaration**,
stored in the project config, of what a session should contain.

**Absent means off.** A project with no ``[expected]`` section gets no
expectation checks at all, silently — the same stance ``consistency.py`` takes
toward absent provenance. Declaring expectations is opt-in, because a study that
has not declared them is not thereby wrong.

**Elicit, then freeze.** Nobody hand-writes a declaration, which is how these
formats die. :func:`elicit` reads one session the user has *confirmed good* and
proposes it as the rule (the same bootstrap BIDScoin's study bidsmap uses). What
makes it worth anything is the freezing: from then on every other session is
judged against that session, not against itself.

**Exceptions are load-bearing, not polish.** A subject who genuinely got 3 of 4
runs must be markable as expected-and-accepted, or the board fills with permanent
noise and people stop reading it — which costs more than the check ever paid for.
``[expected.exceptions]`` is that escape hatch, and it carries a ``reason`` so the
deviation stays legible a year later.

The config shape::

    [expected]
    participants = 37                 # or ["001", "002", ...]

    [expected.session]
    fmap_pairs = 1

    [expected.session.anat]
    T1w = 1

    [expected.session.task]
    div = 4

    [expected.exceptions."013"]
    reason = "scanner aborted the last run"
    [expected.exceptions."013".task]
    div = 3

Reports, never repairs — the standing rule. Nothing here writes to a dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .ingestion import sub_ses_relpath

#: Config section this module owns, end to end.
SECTION = "expected"


def unit_key(subject: str, session: str) -> str:
    """The name an ``[expected.exceptions]`` entry uses for one unit.

    ``"013"`` for a sessionless subject, ``"013/02"`` with a session. Labels are
    bare — no ``sub-``/``ses-`` prefix — matching how they are carried everywhere
    else in the core (``discover_units``, ``advance_one``, the submission log).
    """
    return f"{subject}/{session}" if session else subject


def bids_entities(name: str) -> dict[str, str]:
    """The ``key-value`` entities in a BIDS filename, as a dict.

    Local rather than shared: ``qc._parse_bids_filename`` does the same job for
    MRIQC's flat IQM filenames, and merging the two would couple this module to
    the QC page's needs for six lines of savings.
    """
    entities: dict[str, str] = {}
    for token in name.split(".")[0].split("_"):
        key, sep, value = token.partition("-")
        if sep and value:
            entities[key] = value
    return entities


def bids_suffix(name: str) -> str:
    """The suffix of a BIDS filename — the last ``_``-separated token, no entity."""
    stem = name.split(".")[0]
    last = stem.rsplit("_", 1)[-1]
    return "" if "-" in last else last


@dataclass(frozen=True)
class SessionExpectation:
    """What one session should contain: anat images, fieldmap pairs, task runs.

    Deliberately coarse — **counts and presence, never acquisition parameters**.
    TR, voxel size and flip angle are protocol-compliance questions and belong to
    mrQA, which does them properly against a real scanner protocol export. The
    line duckbrain holds is *did we get the things we said we would*, and growing
    a parameter comparison here is the road to a worse mrQA.

    Zero is a **declaration, not an absence**, throughout. "This subject has no
    resting run" is the commonest real deviation there is, so ``{"resting": 0}``
    in an exception has to mean *expect none* and silence the check — if zero were
    read as "unstated" it would fall through to the study default and the
    exception could never turn anything off. Hence ``fmap_pairs`` is ``None`` when
    undeclared rather than ``0``, and the count parsers keep zeros while still
    dropping junk.
    """

    #: BIDS anat suffix → count, e.g. ``{"T1w": 1}``.
    anat: dict[str, int] = field(default_factory=dict)
    #: Complete fieldmap pairs (two opposed-PE scans). ``None`` = not declared.
    fmap_pairs: int | None = None
    #: BIDS task label → number of BOLD runs, e.g. ``{"div": 4}``.
    task: dict[str, int] = field(default_factory=dict)
    #: Free text from an ``[expected.exceptions]`` entry; ``""`` for the default.
    reason: str = ""

    def is_empty(self) -> bool:
        """True when nothing is declared — treat as "no expectation stated"."""
        return not self.anat and not self.task and self.fmap_pairs is None

    def to_config_section(self) -> dict:
        """The TOML-ready mapping, omitting anything not declared."""
        out: dict = {}
        if self.fmap_pairs is not None:
            out["fmap_pairs"] = self.fmap_pairs
        if self.anat:
            out["anat"] = dict(sorted(self.anat.items()))
        if self.task:
            out["task"] = dict(sorted(self.task.items()))
        if self.reason:
            out["reason"] = self.reason
        return out

    @classmethod
    def from_config_section(cls, data: object) -> SessionExpectation:
        """Parse one ``[expected.session]``-shaped table, ignoring junk.

        Tolerant by design: a hand-edited config with a stray key or a string
        where a count belongs yields a *narrower* expectation, never an
        exception. A declaration that fails to load must not take the cockpit
        down with it.
        """
        if not isinstance(data, dict):
            return cls()
        return cls(
            anat=_count_map(data.get("anat")),
            fmap_pairs=_as_count(data.get("fmap_pairs")),
            task=_count_map(data.get("task")),
            reason=data.get("reason") if isinstance(data.get("reason"), str) else "",
        )

    def merged_with(self, override: SessionExpectation) -> SessionExpectation:
        """This expectation with *override*'s declared fields replacing ours.

        Key-by-key, not wholesale: an exception saying "this subject has 3 runs of
        `div`" must not silently drop the T1w and fieldmap expectations it did not
        mention. Same deep-merge stance the config layers themselves take.
        """
        return SessionExpectation(
            anat={**self.anat, **override.anat},
            fmap_pairs=(
                override.fmap_pairs if override.fmap_pairs is not None else self.fmap_pairs
            ),
            task={**self.task, **override.task},
            reason=override.reason or self.reason,
        )


def _as_count(value: object) -> int | None:
    """A non-negative int, or ``None`` for anything that isn't one.

    ``None`` rather than ``0`` for the reject case, so a declared zero survives
    parsing — see the class docstring on why zero has to be sayable.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _count_map(value: object) -> dict[str, int]:
    """A ``label -> count`` mapping, dropping entries that aren't (but keeping 0)."""
    if not isinstance(value, dict):
        return {}
    parsed = ((k, _as_count(v)) for k, v in value.items() if isinstance(k, str))
    return {k: n for k, n in parsed if n is not None}


# ---- reading the declaration ------------------------------------------------


def declared(config: dict) -> dict | None:
    """The raw ``[expected]`` section, or ``None`` when the project declares none.

    ``None`` and ``{}`` both mean "off". Callers should test this first and do
    nothing — that is the opt-out.
    """
    section = config.get(SECTION)
    if not isinstance(section, dict) or not section:
        return None
    return section


def expected_participants(config: dict) -> tuple[list[str], int]:
    """The declared roster as ``(labels, count)``.

    A study may state either a list of subject labels or just how many it plans
    to scan; both are useful and they check different things. ``([], 0)`` means
    no roster was declared.
    """
    section = declared(config) or {}
    raw = section.get("participants")
    if isinstance(raw, bool):
        return [], 0
    if isinstance(raw, int):
        return [], max(raw, 0)
    if isinstance(raw, list):
        labels = sorted({str(p).replace("sub-", "").strip() for p in raw if str(p).strip()})
        return labels, len(labels)
    return [], 0


def expected_for(config: dict, subject: str, session: str = "") -> SessionExpectation | None:
    """What *this* unit should contain, exceptions applied.

    ``None`` when the project declares no session expectation at all. An
    exception may be keyed on the exact unit (``"013/02"``) or on the subject
    (``"013"``, covering every session); the more specific one wins, and both
    merge over the default rather than replacing it.
    """
    section = declared(config)
    if section is None:
        return None
    base = SessionExpectation.from_config_section(section.get("session"))
    if base.is_empty():
        return None

    exceptions = section.get("exceptions")
    if isinstance(exceptions, dict):
        for key in (subject, unit_key(subject, session)):
            if key in exceptions:
                base = base.merged_with(SessionExpectation.from_config_section(exceptions[key]))
    return base


# ---- observing what is actually there ---------------------------------------


def _read_json(path: Path) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _fmap_pair_count(fmap_dir: Path) -> int:
    """Complete fieldmap pairs in *fmap_dir* — groups holding two opposed PE dirs.

    Grouped by ``B0FieldIdentifier`` where the sidecars carry one, because that
    is the field BIDS actually estimates from and it survives any naming scheme.
    Where they don't, fall back to the filename with its ``dir-`` token removed,
    which is what a pair looks like before intent is written.

    A group needs **two distinct ``dir-`` values** to count. One direction is not
    half a pair, it is an unusable field — the lone-AP case ``_assign_fmap_group``
    already refuses to bind a BOLD to.
    """
    if not fmap_dir.is_dir():
        return 0
    groups: dict[str, set[str]] = {}
    for nii in sorted(fmap_dir.glob("*_epi.nii.gz")):
        entities = bids_entities(nii.name)
        direction = entities.get("dir", "")
        sidecar = nii.with_name(nii.name.replace(".nii.gz", ".json"))
        identifiers = _read_json(sidecar).get("B0FieldIdentifier")
        if isinstance(identifiers, str) and identifiers:
            key = identifiers
        elif isinstance(identifiers, list) and identifiers:
            key = str(identifiers[0])
        else:
            key = "_".join(f"{k}-{v}" for k, v in entities.items() if k != "dir")
        groups.setdefault(key, set()).add(direction)
    return sum(1 for dirs in groups.values() if len(dirs - {""}) >= 2)


def observe(bids_dir: str | Path, subject: str, session: str = "") -> SessionExpectation:
    """Count what one session in *bids_dir* actually holds.

    The mirror image of a declaration, in the same shape, so the two compare
    directly. Used both to *check* a session and — via :func:`elicit` — to
    propose the declaration in the first place.
    """
    unit = Path(bids_dir) / sub_ses_relpath(subject, session)

    anat: dict[str, int] = {}
    anat_dir = unit / "anat"
    if anat_dir.is_dir():
        for nii in anat_dir.glob("*.nii.gz"):
            suffix = bids_suffix(nii.name)
            if suffix:
                anat[suffix] = anat.get(suffix, 0) + 1

    task: dict[str, int] = {}
    func_dir = unit / "func"
    if func_dir.is_dir():
        for nii in func_dir.glob("*_bold.nii.gz"):
            label = bids_entities(nii.name).get("task")
            if label:
                task[label] = task.get(label, 0) + 1

    return SessionExpectation(
        anat=anat,
        fmap_pairs=_fmap_pair_count(unit / "fmap"),
        task=task,
    )


def has_bids_unit(bids_dir: str | Path, subject: str, session: str = "") -> bool:
    """Whether this unit has been converted at all.

    Checks gate on this: a subject that has been ingested but not yet converted
    is *pending*, not deficient, and reporting every un-run session as a shortfall
    would make the panel worthless on day one of a study.
    """
    return (Path(bids_dir) / sub_ses_relpath(subject, session)).is_dir()


# ---- eliciting a draft ------------------------------------------------------


def elicit(config: dict, subject: str, session: str = "") -> dict:
    """Propose an ``[expected.session]`` table from one confirmed-good session.

    Returns the config-ready mapping; the caller shows it and the user accepts
    it. Deliberately **does not** propose ``participants``: the roster is the one
    thing the filesystem genuinely cannot know — reading it back off disk would
    reproduce exactly the circularity this module exists to break — so it stays a
    number the experimenter states.
    """
    bids_dir = (config.get("paths") or {}).get("bids_dir") or ""
    return observe(bids_dir, subject, session).to_config_section()
