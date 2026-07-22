"""Predict what a dcm2bids config will actually produce, for review before it runs.

The Conversion page asks a user to approve a *transformation* — these DICOM
series become those BIDS files — but the outputs only ever existed as
``custom_entities`` fragments inside the generated JSON. Reviewing a mapping
therefore meant simulating :func:`~duckbrain.core.dcm2bids_config.generate_config`
by hand. This module renders the other half so it can be shown next to the input.

**The plan is derived from the generated config, never re-derived from the series
list.** That is the whole design constraint, and it is the same stance
:func:`~duckbrain.core.dcm2bids_config.resolve_fmap_assignments` takes for the
fieldmap binding: a second, independent derivation of BIDS filenames would agree
with dcm2bids right up until one of them changed, and a preview that is subtly
wrong is worse than no preview — the user would have approved it. Everything here
reads the config dict that dcm2bids itself will consume, so the two cannot drift.

The one thing the config does not state outright is which *group* a
``B0FieldIdentifier`` refers to, since it carries the composed
``B0map_<group>_sub<X>ses<Y>`` string. That is recovered exactly rather than
guessed: the ``fmap`` descriptions pair each identifier with the description
``id`` it was built from (``fmap-epi-ap-<group>``), so the mapping is read back
out of the same artifact instead of being parsed out of the string — group names
can legitimately contain underscores (``se_epi_ap_foo_bar``), which would make
splitting the composed identifier ambiguous.

See ``docs/conversion-legibility.md`` (TODO ``#13``) for the design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dicom_inspect import FieldmapDetection, SeriesInfo

# Classifications dcm2bids is *supposed* to leave behind. Everything else that
# goes unclaimed is worth surfacing: an anat whose suffix vocabulary didn't match
# used to vanish silently, which is exactly the failure this list must not hide.
_EXPECTED_DROPS = frozenset({"scout", "physio"})

# dcm2bids writes a sidecar beside each of these; the image is the representative.
_IMAGE_EXT = ".nii.gz"


@dataclass
class PlannedFile:
    """One BIDS file the config will produce.

    ``entities`` is the ``custom_entities`` string as written (already in BIDS
    entity order); ``path`` is relative to the BIDS root. ``fmap_group`` is the
    fieldmap group this file binds to — the pair that corrects it for a bold, or
    the pair it belongs to for a fieldmap — and is ``None`` when there is none.
    """

    series_number: int
    description: str
    datatype: str
    suffix: str
    entities: str
    filename: str
    path: str
    description_id: str
    fmap_group: str | None = None

    @property
    def is_bold(self) -> bool:
        return self.datatype == "func" and self.suffix == "bold"


@dataclass
class DroppedSeries:
    """A series no description claims — dcm2bids will not convert it.

    ``expected`` marks the classifications that are *meant* to be left behind
    (scout, physio), so the unexpected ones can be reported louder without
    burying them in the routine noise.
    """

    series_number: int
    description: str
    classification: str
    expected: bool


@dataclass
class ConversionPlan:
    """Everything a config will and won't produce, for one session."""

    files: list[PlannedFile] = field(default_factory=list)
    dropped: list[DroppedSeries] = field(default_factory=list)

    @property
    def by_series(self) -> dict[int, list[PlannedFile]]:
        """Planned files indexed by source series number.

        A list per series rather than a single file: nothing in the config
        format stops two descriptions matching one ``SeriesNumber``, and a
        preview that silently showed only the last one would hide precisely the
        duplicate the collision check exists to catch.
        """
        out: dict[int, list[PlannedFile]] = {}
        for f in self.files:
            out.setdefault(f.series_number, []).append(f)
        return out

    def bolds_for_group(self, group: str | None) -> list[PlannedFile]:
        """Bold runs bound to ``group`` — the task↔fieldmap relation, one way round."""
        return [f for f in self.files if f.is_bold and f.fmap_group == group]

    def corrected_by(self, group: str | None) -> list[PlannedFile]:
        """Every scan ``group`` corrects — bolds *and* their SBRefs.

        Distinct from :meth:`bolds_for_group`, which answers the narrower
        "which runs". An SBRef is bound by :func:`~duckbrain.core.dcm2bids_config.
        generate_config` exactly as its BOLD is, and it is not a detail: fMRIPrep
        builds the BOLD reference from the SBRef when one exists, so an SBRef
        missing from this view reads as unbound when it is not.
        """
        return [
            f
            for f in self.files
            if f.datatype == "func" and f.suffix in ("bold", "sbref") and f.fmap_group == group
        ]


def _bids_filename(subject: str, session: str, entities: str, suffix: str) -> str:
    """Compose ``sub-X[_ses-Y][_<entities>]_<suffix>.nii.gz``."""
    parts = [f"sub-{subject}"] if subject else []
    if session:
        parts.append(f"ses-{session}")
    parts.extend(p for p in entities.split("_") if p)
    parts.append(suffix)
    return "_".join(parts) + _IMAGE_EXT


def _group_by_identifier(descriptions: list[dict]) -> dict[str, str]:
    """Map each composed ``B0map_…`` identifier back to its group name.

    Read off the ``fmap`` descriptions, which hold both halves: the ``id`` was
    built as ``fmap-epi-<dir>[-<group>]`` and ``B0FieldSource`` is the composed
    identifier. Exact by construction — no string splitting, so a group name
    containing an underscore stays unambiguous.
    """
    out: dict[str, str] = {}
    for d in descriptions:
        if d.get("datatype") != "fmap":
            continue
        identifier = (d.get("sidecar_changes") or {}).get("B0FieldIdentifier")
        if not identifier:
            continue
        desc_id = str(d.get("id", ""))
        group = ""
        for direction in ("ap", "pa"):
            prefix = f"fmap-epi-{direction}"
            if desc_id.startswith(prefix):
                group = desc_id[len(prefix) :].lstrip("-")
                break
        out[identifier] = group
    return out


def plan_conversion(
    config: dict,
    series_list: list[SeriesInfo],
    subject: str = "",
    session: str = "",
) -> ConversionPlan:
    """Render a generated dcm2bids config into the files it will produce.

    Parameters
    ----------
    config : dict
        The config dict from
        :func:`~duckbrain.core.dcm2bids_config.generate_config` — the same object
        that gets written to ``dcm2bids_config.json`` and consumed by the tool.
    series_list : list[SeriesInfo]
        Classified series for this session, used to name the source of each
        planned file and to find the ones nothing claims.
    subject, session : str
        Bare labels (``"001"``, ``"02"``), matching
        :func:`~duckbrain.core.ingestion.sub_ses_relpath`.

    Returns
    -------
    ConversionPlan
        Planned files plus the series left unconverted.
    """
    descriptions = config.get("descriptions") or []
    group_by_id = _group_by_identifier(descriptions)
    desc_by_series = {s.series_number: s.description for s in series_list}

    ses_dir = f"ses-{session}/" if session else ""
    sub_dir = f"sub-{subject}/" if subject else ""

    files: list[PlannedFile] = []
    claimed: set[int] = set()

    for d in descriptions:
        criteria = d.get("criteria") or {}
        series_number = criteria.get("SeriesNumber")
        if series_number is None:
            # Every description generate_config emits matches on SeriesNumber.
            # A hand-edited config need not, and there is nothing to preview for
            # it — skip rather than invent a filename.
            continue
        series_number = int(series_number)
        claimed.add(series_number)

        datatype = str(d.get("datatype", ""))
        suffix = str(d.get("suffix", ""))
        entities = str(d.get("custom_entities", ""))
        sidecar = d.get("sidecar_changes") or {}

        identifier = sidecar.get("B0FieldIdentifier") or sidecar.get("B0FieldSource")
        fmap_group = group_by_id.get(identifier) if identifier else None

        filename = _bids_filename(subject, session, entities, suffix)
        files.append(
            PlannedFile(
                series_number=series_number,
                description=desc_by_series.get(series_number, ""),
                datatype=datatype,
                suffix=suffix,
                entities=entities,
                filename=filename,
                path=f"{sub_dir}{ses_dir}{datatype}/{filename}",
                description_id=str(d.get("id", "")),
                fmap_group=fmap_group,
            )
        )

    dropped = [
        DroppedSeries(
            series_number=s.series_number,
            description=s.description,
            classification=s.classification,
            expected=s.classification in _EXPECTED_DROPS,
        )
        for s in series_list
        if s.series_number not in claimed
    ]

    return ConversionPlan(files=files, dropped=dropped)


@dataclass
class PlanWarning:
    """One preflight finding about a plan.

    ``severity`` is ``"error"`` (the conversion will lose data), ``"warning"``
    (probably wrong, worth a look) or ``"info"`` (a legitimate choice worth
    seeing stated). ``series`` lists the DICOM series numbers involved so a GUI
    can point at the rows.
    """

    kind: str
    severity: str
    message: str
    series: list[int] = field(default_factory=list)


def plan_warnings(
    plan: ConversionPlan, fieldmaps: FieldmapDetection | None = None
) -> list[PlanWarning]:
    """Preflight a plan: what will go wrong, or is worth confirming, before submitting.

    Reports; never repairs. That is `TODO` ``#5``'s standing rule — a bad guess
    made *visible* is the job, and quietly rewriting a mapping here would be the
    silently-degrading behavior ``CLAUDE.md`` forbids.

    Ordered most severe first, so a caller can render them as-is.
    """
    out: list[PlanWarning] = []

    # --- Collisions: two descriptions writing the same file. dcm2bids writes one
    # and the other is simply lost, which is invisible in a table of inputs.
    by_path: dict[str, list[PlannedFile]] = {}
    for f in plan.files:
        by_path.setdefault(f.path, []).append(f)
    for path, hits in sorted(by_path.items()):
        if len(hits) > 1:
            nums = sorted(h.series_number for h in hits)
            out.append(
                PlanWarning(
                    kind="collision",
                    severity="error",
                    message=(
                        f"{len(hits)} series map to the same file `{path}` "
                        f"(series {', '.join(str(n) for n in nums)}). Only one "
                        "will be written — give them distinct task or run values."
                    ),
                    series=nums,
                )
            )

    # --- Half pairs: a group with one phase-encoding direction cannot be used
    # for distortion correction. detect_fieldmaps already warns; repeated here so
    # everything blocking a good conversion is in one panel.
    if fieldmaps is not None:
        for group, dirs in sorted(fieldmaps.groups.items()):
            missing = [d for d in ("ap", "pa") if d not in dirs]
            if not missing:
                continue
            label = group or "(unnamed)"
            out.append(
                PlanWarning(
                    kind="half-pair",
                    severity="warning",
                    message=(
                        f"Fieldmap group **{label}** has only "
                        f"{', '.join(sorted(dirs)).upper()} — a pair needs both AP "
                        "and PA, so this group can't correct anything and isn't "
                        "offered for binding."
                    ),
                    series=sorted(dirs.values()),
                )
            )

    # --- Series nothing claims. Unexpected ones first: an anat whose suffix
    # vocabulary didn't match is a real bug and looks exactly like a scout here.
    unexpected = [d for d in plan.dropped if not d.expected]
    for d in unexpected:
        out.append(
            PlanWarning(
                kind="dropped",
                severity="warning",
                message=(
                    f"Series {d.series_number} `{d.description}` "
                    f"(classified *{d.classification or 'unknown'}*) matches no "
                    "description and will not be converted."
                ),
                series=[d.series_number],
            )
        )

    # --- Bolds with no distortion correction, when a usable pair exists. A
    # deliberate 'none' looks identical, so this states the outcome rather than
    # calling it wrong.
    complete = (
        [g for g, dirs in fieldmaps.groups.items() if "ap" in dirs and "pa" in dirs]
        if fieldmaps is not None
        else []
    )
    if complete:
        uncorrected = [f for f in plan.files if f.is_bold and f.fmap_group is None]
        if uncorrected:
            nums = sorted(f.series_number for f in uncorrected)
            out.append(
                PlanWarning(
                    kind="uncorrected",
                    severity="info",
                    message=(
                        f"{len(uncorrected)} bold run(s) will be written with no "
                        "`B0FieldIdentifier`, so fMRIPrep will preprocess them "
                        "without distortion correction, even though this session "
                        "has a usable fieldmap pair. Intentional if you set the "
                        "binding to `none`."
                    ),
                    series=nums,
                )
            )

    expected = [d for d in plan.dropped if d.expected]
    if expected:
        out.append(
            PlanWarning(
                kind="dropped",
                severity="info",
                message=(
                    f"{len(expected)} series left unconverted as expected "
                    f"({', '.join(sorted({d.classification for d in expected}))})."
                ),
                series=sorted(d.series_number for d in expected),
            )
        )

    return out


# --- Reading a hand-edited config back into the table -----------------------
# The table is *lossy* relative to the config: criteria beyond SeriesNumber,
# arbitrary sidecar_changes, custom description ids and dcm2bids' own options
# have no column. That is exactly why this is an explicit, one-shot import rather
# than continuous two-way sync — a round trip that ran on every keystroke would
# drop those silently, which is the failure mode this codebase keeps refusing.
# Here the loss is *reported*, and the user decides.

_ENTITY_RE = re.compile(r"(?:^|_)(task|run)-([A-Za-z0-9]+)")

# Everything the table can express. Anything else in a description is loss.
_KNOWN_DESC_KEYS = frozenset(
    {"id", "datatype", "suffix", "criteria", "custom_entities", "sidecar_changes"}
)
_KNOWN_SIDECAR_KEYS = frozenset(
    {"TaskName", "B0FieldIdentifier", "B0FieldSource", "PhaseEncodingDirection"}
)


@dataclass
class ConfigImport:
    """A hand-edited config expressed in the conversion table's terms.

    ``unrepresentable`` lists, in plain sentences, everything the table has no
    column for. It is the point of the whole exercise: an import that quietly
    discarded a custom ``criteria`` would be worse than refusing to import.
    """

    task_by_series: dict[int, str] = field(default_factory=dict)
    run_by_series: dict[int, int | None] = field(default_factory=dict)
    group_by_series: dict[int, str | None] = field(default_factory=dict)
    unrepresentable: list[str] = field(default_factory=list)


def read_config_into_table(config: dict, series_list: list[SeriesInfo]) -> ConfigImport:
    """Parse a dcm2bids config back into per-series task / run / fieldmap values.

    The inverse of what the Conversion Plan table generates, as far as the table
    can go. Entities are read from ``custom_entities`` (the same string
    :func:`plan_conversion` renders into a filename) and the fieldmap group from
    the composed ``B0map_…`` identifier, so both stay consistent with the plan.
    """
    out = ConfigImport()
    descriptions = config.get("descriptions") or []
    group_by_id = _group_by_identifier(descriptions)

    for key in sorted(set(config) - {"descriptions"}):
        out.unrepresentable.append(
            f"top-level `{key}` is kept in the JSON but has no column in the table"
        )

    for d in descriptions:
        criteria = d.get("criteria") or {}
        series_number = criteria.get("SeriesNumber")
        label = d.get("id") or "(unnamed description)"
        if series_number is None:
            out.unrepresentable.append(
                f"`{label}` does not match on SeriesNumber, so it has no table row"
            )
            continue
        series_number = int(series_number)

        extra_criteria = sorted(set(criteria) - {"SeriesNumber"})
        if extra_criteria:
            out.unrepresentable.append(f"`{label}` also matches on {', '.join(extra_criteria)}")
        extra_keys = sorted(set(d) - _KNOWN_DESC_KEYS)
        if extra_keys:
            out.unrepresentable.append(f"`{label}` sets {', '.join(extra_keys)}")

        sidecar = d.get("sidecar_changes") or {}
        extra_sidecar = sorted(set(sidecar) - _KNOWN_SIDECAR_KEYS)
        if extra_sidecar:
            out.unrepresentable.append(f"`{label}` sets sidecar_changes {', '.join(extra_sidecar)}")

        entities = dict(_ENTITY_RE.findall(str(d.get("custom_entities", ""))))
        if "task" in entities:
            out.task_by_series[series_number] = entities["task"]
        run = entities.get("run")
        out.run_by_series[series_number] = int(run) if run is not None and run.isdigit() else None

        identifier = sidecar.get("B0FieldIdentifier") or sidecar.get("B0FieldSource")
        out.group_by_series[series_number] = group_by_id.get(identifier) if identifier else None

    known = {s.series_number for s in series_list}
    for series_number in sorted(set(out.task_by_series) - known):
        out.unrepresentable.append(
            f"series {series_number} is named in the config but not in this session"
        )

    return out
