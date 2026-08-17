"""Does a planned filename match the BIDS schema? Asked before a job is submitted.

The dataset validator (``core/validation.py``) answers this *after* a conversion
has run, on real files; this module answers it at plan time, on paths that do
not exist yet, so a hand-edited ``custom_entities`` or a suffix outside the
specification is refused before it costs a SLURM job. The design record is
``docs/conversion-legibility.md`` phase 10.

The schema is not restated here. ``bidsschematools`` is the BIDS steering
group's own machine-readable schema, and :func:`regexify_all` compiles it into
one regex per specification entry — entity order, entity values, datatype
directories and suffixes included. Matching a path against those is the same
judgment the schema-based validator would make of the file once written, which
is what keeps this check from being a second, drifting statement of what BIDS
is. The compiled set is cached per process: loading the schema costs ~0.1 s,
matching is microseconds.

What this cannot judge: whether ``task-divPerFace`` *means* anything. Schema
conformance is syntax; the study-specific inference from series names is the
rest of the Conversion page's job.
"""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _compiled() -> tuple[list[re.Pattern[str]], str]:
    """Every schema path regex, compiled once, plus the BIDS version they state.

    The import happens here rather than at module top so importing this module
    stays free; ``bidsschematools.schema`` is imported explicitly because the
    package lazy-loads submodules and ``rules.regexify_all`` reaches for
    ``bst.schema`` without triggering that load — without the explicit import
    the call raises ``AttributeError`` on a fresh interpreter.
    """
    import bidsschematools.schema  # noqa: F401  (lazy-submodule load, see docstring)
    from bidsschematools.rules import regexify_all

    all_regex, schema = regexify_all()
    return [re.compile(r["regex"]) for r in all_regex], str(schema.bids_version)


def bids_version() -> str:
    """The BIDS specification version the installed schema encodes (``"1.10.1"``)."""
    return _compiled()[1]


def conforms(path: str) -> bool:
    """Whether ``path`` matches any filename pattern in the BIDS schema.

    ``path`` is relative to the BIDS root (``sub-001/ses-01/anat/…``), which is
    exactly what :class:`~duckbrain.core.conversion_plan.PlannedFile` carries.
    The directory components are part of the match — the schema's regexes pin a
    file to its datatype directory, so ``anat/…_bold.nii.gz`` is refused just
    like a malformed entity is.
    """
    patterns, _ = _compiled()
    return any(p.fullmatch(path) for p in patterns)
