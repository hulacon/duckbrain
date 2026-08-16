"""The project-level series skip — ``[series_skip]``, keyed on description.

A study that acquires a series and never uses it says so *once*, here, instead
of unticking ``convert`` on the Conversion page for every session. The section
is a list of SeriesDescriptions; every series matching one converts to nothing,
in the GUI, in bulk convert and in the cockpit alike. The case that motivates it
is curation scope, not junk: five of the LCNI repository's fifteen studies keep
canonical trees containing *nothing but* ``anat/T1w`` (on WMS that is 6
descriptions across 56 sessions, ~336 unticks), and REV's curator kept
``fieldmap2`` and dropped ``fieldmap1`` in 6 of 6 sessions — recurring,
description-keyed decisions no per-session checkbox should be re-stating.
Measured 2026-07-30; the full survey is the ``#13.1`` ledger row in ``TODO.md``.

**A skip is its own section, not a ``[series_types]`` value.** A datatype is a
claim about what a series *is*; a skip is a decision about what to do with it —
collapsing them would make relabelling a series the only way to drop it. The
mechanical half of that argument is the stronger one: an ``ignore``
*classification* would not reliably drop anything, because what implements a
skip is :func:`~duckbrain.core.dcm2bids_config.generate_config`'s ``skip`` set
plus ``_without_skipped_groups`` (both keyed on series numbers), and
``generate_config`` emits fieldmaps by walking ``fieldmaps.groups`` without
consulting ``classification`` at all. Leaving the classification intact is also
what keeps the preflight honest — that a dropped series was a *functional run*
rather than a scout, that an SBRef was stranded, that unticking one fieldmap
half took the whole pair, are all read off ``classification`` beside the skip.

**Nor does it fold into ``[expected]``** (decided 2026-08-11, owed by
``#16.1``): a count over BIDS entities cannot say *which* series to drop —
"keep ``fieldmap2``, drop ``fieldmap1``" is description-specific — and the
expectations layer's contract is reports-never-repairs, so routing conversion
behavior through it would make deleting ``[expected]`` silently change what
gets converted. The two stay complementary: an anat-only study *should also*
declare an anat-only ``[expected.session]``, and then the plan, the tree and
the checks all agree — but they are two declarations with two jobs.

**The per-session ``convert`` checkbox stays, and outranks this for the session
in front of you.** A description key is exactly what a per-session fact cannot
use: ``fmap_eyeball``'s ``sub-01`` holds ``cued_recall_encoding_run2`` twice —
aborted at 14 volumes and complete at 210, identical descriptions — and a
description-keyed rule would drop both. So the page seeds a skipped series
unticked and lets a re-tick win for that session (the saved
``dcm2bids_config.json`` is the record, as for every per-session decision), and
the save button only promotes a description whose *every* row is unticked.

**Resolution happens per session, inside**
:func:`~duckbrain.core.conversion.generate_session_config`, beside where
``type_rules`` is applied — a description resolves to series numbers only once
the session is listed, which is also why the resolved set rides the existing
``skip`` mechanism rather than a parallel one: the whole-pair rule and the
save/reload round trip come for free. Only series whose classification is in
:data:`~duckbrain.core.dicom_inspect.EMITTED_CLASSIFICATIONS` resolve, so a
scout matching a skipped description does not earn a "deliberate drop" note for
a conversion that was never going to happen.

**A malformed section raises rather than converting anyway.** The fallback for
an unreadable skip is converting the very series the study excluded — a control
silently not doing what it says, which this project treats as worse than a
refusal. Same asymmetry ``type_rules_from_config`` makes, for the same reason.

**A coarser include-by-datatype control ("anat only") was considered for the
anat-only case and declined** (2026-08-16). It would express five studies'
intent in one line, but its failure mode is inverted: a study that adds a
sequence would lose it *silently*, whereas under a skip the new series converts
and shows up in the plan and the tree — visible, and one line to exclude if
unwanted. Naming six descriptions is the price of that visibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .dicom_inspect import EMITTED_CLASSIFICATIONS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..config import Config
    from .dicom_inspect import SeriesInfo

SECTION = "series_skip"

# The reason plan_warnings states for a project-skipped series, rendered into
# "Series N `desc` will not be converted: <reason>." — distinguishable from the
# page's own "you unticked `convert`" so a note about a study-wide decision
# doesn't read as something this session's reviewer did.
SKIP_REASON = "the project config's `[series_skip]` section leaves it out of every session"


def _normalize(description: str) -> str:
    return description.strip().lower()


def skip_lookup(descriptions: Iterable[str]) -> set[str]:
    """Index a skip list by normalized (stripped, lowercased) description.

    The same matching :class:`~duckbrain.core.series_types.TypeRule` and
    :class:`~duckbrain.core.dcm2bids_config.TaskRule` use, for the same reason:
    the key is a console operator's free text.
    """
    return {_normalize(d) for d in descriptions if d.strip()}


def skip_descriptions_from_config(config: Config) -> list[str]:
    """Read the skip list from a merged config's ``[series_skip]``.

    Order-preserving and deduped case-insensitively (first spelling wins), so
    the list round-trips through the GUI without reshuffling. **Raises on a
    malformed section** — a skipped skip converts the series the study
    excluded, which is the silently-degrading shape ``CLAUDE.md`` forbids.
    Blank entries are dropped: there is nothing for them to name.
    """
    section = config.get(SECTION) or {}
    raw = section.get("descriptions")
    if raw is None:
        return []
    if isinstance(raw, str) or not isinstance(raw, list):
        raise ValueError(
            f"[{SECTION}] descriptions must be an array of series descriptions, "
            f'got {raw!r}. Example: descriptions = ["fieldmap1_AP", "fieldmap1_PA"].'
        )
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"[{SECTION}] descriptions must all be strings, got {item!r}.")
        desc = item.strip()
        if not desc:
            continue
        key = _normalize(desc)
        if key in seen:
            continue
        seen.add(key)
        out.append(desc)
    return out


def skip_to_config_section(descriptions: Iterable[str]) -> dict[str, Any]:
    """Serialize a skip list into a TOML-friendly ``[series_skip]`` section."""
    out: list[str] = []
    seen: set[str] = set()
    for d in descriptions:
        desc = d.strip()
        if not desc or _normalize(desc) in seen:
            continue
        seen.add(_normalize(desc))
        out.append(desc)
    return {"descriptions": out}


def apply_project_skip(series_list: list[SeriesInfo], descriptions: Iterable[str]) -> set[int]:
    """Resolve the skip list against one session and return the series numbers.

    Stamps ``drop_reason`` on each matched series, which is what carries the
    "why" into :func:`~duckbrain.core.conversion_plan.plan_warnings` — without
    it a project-skipped run would be reported as a series nothing claimed,
    indistinguishable from the anat-suffix bug that warning exists to catch.

    Must run *after* ``classify_series``: only series duckbrain would otherwise
    emit resolve (see the module docstring), and classification is what says so.
    """
    keys = skip_lookup(descriptions)
    if not keys:
        return set()
    matched: set[int] = set()
    for s in series_list:
        if s.classification in EMITTED_CLASSIFICATIONS and _normalize(s.description) in keys:
            s.drop_reason = SKIP_REASON
            matched.add(s.series_number)
    return matched
