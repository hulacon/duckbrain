"""Orchestrate dcm2bids runs via Singularity."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from pathlib import Path
from typing import TYPE_CHECKING

from .containers import isolation_flags

if TYPE_CHECKING:
    from ..config import Config


def build_dcm2bids_command(
    subject: str,
    session: str,
    dicom_dir: str | Path,
    bids_dir: str | Path,
    config_json: str | Path,
    container_path: str | Path,
    force: bool = False,
) -> list[str]:
    """Construct a Singularity exec command for dcm2bids.

    Parameters
    ----------
    subject : str
        Subject label (without "sub-" prefix).
    session : str
        Session label (without "ses-" prefix).
    dicom_dir : path
        Path to DICOM directory for this session.
    bids_dir : path
        Output BIDS directory root.
    config_json : path
        Path to dcm2bids config JSON file.
    container_path : path
        Path to dcm2bids Singularity image.
    force : bool
        Force overwrite of existing output.

    Returns
    -------
    list[str]
        Command arguments for subprocess.
    """
    # Resolve the DICOM dir so the Singularity bind source is the REAL directory.
    # Sourcedata uses symlink ingestion (sub-XX/dicom -> LCNI export). Binding the
    # symlink location works on Talapas (Singularity follows it), but binding the
    # resolved target is explicit and portable across Singularity/Apptainer configs
    # that restrict or don't follow symlinked bind sources.
    dicom_dir = Path(dicom_dir).resolve()
    bids_dir = Path(bids_dir)
    config_json = Path(config_json)
    container_path = Path(container_path)

    cmd = [
        "singularity",
        "run",
        *isolation_flags(),
        "-B",
        f"{dicom_dir}:{dicom_dir}:ro",
        "-B",
        f"{bids_dir}:{bids_dir}",
        "-B",
        f"{config_json.parent}:{config_json.parent}:ro",
        str(container_path),
        "-d",
        str(dicom_dir),
        "-p",
        subject,
    ]

    # Omit -s for single-session studies (no ses- entity)
    if session:
        cmd += ["-s", session]

    cmd += [
        "-c",
        str(config_json),
        "-o",
        str(bids_dir),
    ]

    if force:
        # BOTH flags, because they clobber different things and only the second
        # one is what "force" means to a user. --force_dcm2bids overwrites the
        # *temporary* dcm2niix output under tmp_dcm2bids/; --clobber overwrites
        # the BIDS output. dcm2bids skips any destination file that already
        # exists unless --clobber is given (dcm2bids_gen.py logs "already exists
        # / Use --clobber option to overwrite" and moves on).
        #
        # With only the first, a reconversion re-ran dcm2niix, wrote nothing, and
        # exited 0 — so a fix to the generated config could never reach a subject
        # that had been converted once. Found when the B0 identifier fix wouldn't
        # take on divatten_beta.
        cmd += ["--force_dcm2bids", "--clobber"]

    # Deliberately no validation here, and no --bids_validate. This is a direct
    # call / dry-run helper with no production caller; every real conversion goes
    # through the sbatch template, which runs bids-validator itself (see
    # core/validation.py). A fourth construction of that command is exactly what
    # the argv-agreement test exists to prevent.
    return cmd


def run_dcm2bids(
    subject: str,
    session: str,
    dicom_dir: str | Path,
    bids_dir: str | Path,
    config_json: str | Path,
    container_path: str | Path,
    force: bool = False,
    dry_run: bool = False,
) -> subprocess.CompletedProcess | list[str]:
    """Run dcm2bids conversion.

    Parameters
    ----------
    dry_run : bool
        If True, return the command instead of executing.

    Returns
    -------
    CompletedProcess or list[str]
        Execution result or command (if dry_run).
    """
    cmd = build_dcm2bids_command(
        subject, session, dicom_dir, bids_dir, config_json, container_path, force
    )

    if dry_run:
        return cmd

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result


def save_dcm2bids_config(config_dict: dict, output_path: str | Path) -> Path:
    """Write a dcm2bids config dict to a JSON file.

    Parameters
    ----------
    config_dict : dict
        The dcm2bids config (from dcm2bids_config.generate_config).
    output_path : path
        Where to write the JSON.

    Returns
    -------
    Path
        The written file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(config_dict, f, indent=2)
    return output_path


def resolve_dicom_dir(sourcedata_dir: str | Path, subject: str, session: str) -> Path:
    """Path to a session's ingested DICOM dir, following the ingest symlink."""
    from .ingestion import sub_ses_relpath

    dicom_dir = Path(sourcedata_dir) / sub_ses_relpath(subject, session) / "dicom"
    return dicom_dir.resolve() if dicom_dir.is_symlink() else dicom_dir


def session_bids_exists(bids_dir: str | Path, subject: str, session: str) -> bool:
    """Whether a session already has BIDS output (any NIfTI under its sub[/ses] dir).

    Presence-based, not completion-based: a partial/failed conversion also counts
    as "exists". Callers that want to redo it should pass force to dcm2bids.
    """
    from .ingestion import sub_ses_relpath

    sub_dir = Path(bids_dir) / sub_ses_relpath(subject, session)
    return sub_dir.is_dir() and any(sub_dir.rglob("*.nii.gz"))


def generate_session_config(
    dicom_dir: str | Path,
    subject: str,
    session: str,
    template: str | None = None,
    rules: list | None = None,
    fmap_rules: list | None = None,
    series_list: list | None = None,
    nd_duplicates: str = "corrected",
    skip: Collection[int] | None = None,
    type_rules: list | None = None,
    container: str | Path | None = None,
) -> dict:
    """Inspect a session's DICOMs and build a default dcm2bids config.

    The non-interactive equivalent of the Conversion page's inspect → classify →
    fieldmap → task/run mapping → generate_config pipeline, using the auto-derived
    task/run mapping (no manual edits). Used for bulk conversion.

    ``rules`` is an optional list of project-wide :class:`TaskRule`s; when given,
    they override the naming heuristic for the series they name, so a bulk convert
    inherits the study's once-defined task/run mapping. ``fmap_rules`` does the
    same for :class:`FmapRule` fieldmap bindings — without it a bulk convert would
    quietly fall back to automatic fieldmap assignment while the GUI path honored
    the project's bindings, which is exactly the kind of divergence the mapping
    exists to close.

    ``series_list`` lets a caller that has *already* inspected the session hand
    the result in rather than paying for a second walk of the DICOM tree. It is
    classified in place, exactly as a freshly-listed one would be.

    ``nd_duplicates`` is the project's choice of reconstruction where Siemens
    saved a series twice; it must reach here for the same reason ``fmap_rules``
    does — a bulk convert that fell back to the default while the GUI honoured
    the project's setting would ship a different image than the one reviewed.

    ``type_rules`` are the project's ``[series_types]`` declarations, and they
    reach here for the same reason ``rules`` and ``nd_duplicates`` do: a bulk
    convert that fell back to the header/name classification while the GUI
    honoured the study's declaration would write a *different datatype* than the
    one reviewed, or write nothing at all for a series the declaration rescued.

    ``skip`` is a set of series numbers to leave unconverted. It is per-session
    by nature — series numbers do not generalize across sessions, which is the
    same reason :class:`~duckbrain.core.dcm2bids_config.TaskRule` is keyed on
    description — so nothing here reads it from the project config. The GUI's
    saved ``dcm2bids_config.json`` is how a reviewed skip reaches a later
    convert: ``pipeline._build_converted`` reuses that file rather than calling
    this, and a skipped series is simply absent from it.

    ``container`` is the dcm2bids image to probe with dcm2niix, and it is also
    the switch: ``None`` means don't probe, so a caller with no config never pays
    for a subprocess it didn't ask for. It reaches here for the same reason
    ``rules``, ``fmap_rules``, ``nd_duplicates`` and ``type_rules`` do — a bulk
    convert that checked less than the reviewed path would submit exactly what
    the GUI refuses, which is the divergence that already shipped once with
    collisions. The preference is ``probe_runtime``'s: the pinned image, else a
    host ``dcm2niix``.

    A probe that *cannot* run warns and converts anyway. Refusing would be wrong
    here specifically because submission and conversion happen on different
    machines: the login node or OOD app that runs this may have no container
    runtime while the compute node that runs dcm2bids does, so a refusal would
    block a study that converts perfectly well. Nothing on this path claims the
    check ran — the claim lives in the Conversion page's panel, which says so
    itself — so this is not the silently-degrading class ``CLAUDE.md`` forbids.

    Raises ``ValueError`` if two series would be written to the same BIDS file.
    The interactive page renders that as an error and lets a human resolve it,
    but nothing rendered warnings on this path, so a bulk or cockpit convert
    submitted the job and dcm2bids kept whichever series it wrote last — a
    silent partial conversion, which is the failure mode this project treats as
    worse than a refusal.
    """
    import warnings

    from .conversion_plan import plan_conversion, plan_warnings
    from .dcm2bids_config import build_task_run_mapping, generate_config
    from .dcm2niix_probe import by_series_number, probe_runtime, probe_session
    from .dicom_inspect import classify_series, detect_fieldmaps, list_series

    if series_list is None:
        series_list = list_series(dicom_dir)
    if not series_list:
        raise ValueError(f"No series directories found in {dicom_dir}")
    classify_series(series_list, nd_duplicates=nd_duplicates, type_rules=type_rules)
    fieldmaps = detect_fieldmaps(series_list)
    mapping = build_task_run_mapping(series_list, template=template or None, rules=rules)
    config = generate_config(
        series_list,
        fieldmaps,
        subject=subject,
        session=session,
        mapping=mapping,
        fmap_rules=fmap_rules,
        skip=skip,
    )

    probes: dict = {}
    if container:
        runtime = probe_runtime(container)
        if runtime.available:
            # 10 s, not the module's 120: this runs inline in a bulk loop over
            # every unconverted session, and a cold probe is 0.7 s — anything
            # slower is already pathological and should not stall the batch.
            dirs = [s.path for s in series_list if s.path]
            probes = by_series_number(probe_session(dirs, runtime.container, timeout_s=10))
        else:
            warnings.warn(
                f"Phase-encoding checks skipped for sub-{subject}"
                + (f"/ses-{session}" if session else "")
                + f": {runtime.reason}",
                stacklevel=2,
            )

    plan = plan_conversion(config, series_list, subject=subject, session=session)
    blocking = [w for w in plan_warnings(plan, fieldmaps, probes=probes) if w.severity == "error"]
    if blocking:
        raise ValueError(
            f"Cannot convert sub-{subject}"
            + (f"/ses-{session}" if session else "")
            + ": "
            + " ".join(w.message for w in blocking)
        )
    return config


@dataclass
class ConfigDrift:
    """How a saved dcm2bids config differs from one generated for it now.

    A saved ``dcm2bids_config.json`` is the source of truth for a session:
    ``pipeline._build_converted`` reuses it and only generates when it is absent.
    That is right when the file records a human review — and wrong in a way
    nothing announced when the *generator* has since changed, because then the
    saved plan silently overrides the new code. That is not hypothetical: the B0
    identifier fix could not reach any already-reviewed session, since the stale
    plan kept re-supplying the identifier the fix existed to correct.

    Reporting the difference rather than resolving it is deliberate. A drift can
    equally mean "you edited this on purpose" or "duckbrain changed underneath
    you", and nothing on disk distinguishes them — the file records no
    provenance. Regenerating would silently discard a real review; ignoring it
    silently discards a real fix. Only the operator knows which, so both plans
    are described and the choice is theirs.
    """

    added: list[str] = dataclasses_field(default_factory=list)
    removed: list[str] = dataclasses_field(default_factory=list)
    changed: dict[str, list[str]] = dataclasses_field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def describe(self, limit: int | None = None) -> list[str]:
        """One human-readable line per difference.

        A single changed field can touch every functional run in a session — the
        B0 identifier drift on divatten_beta is 28 descriptions — so *limit*
        caps the list. The cap states itself in a final line rather than
        trailing off, because a list that silently stops reads as a complete one.
        """
        lines = []
        for desc_id in self.removed:
            lines.append(f"`{desc_id}` — in the saved config, no longer generated")
        for desc_id in self.added:
            lines.append(f"`{desc_id}` — newly generated, absent from the saved config")
        for desc_id, fields in self.changed.items():
            lines.append(f"`{desc_id}` — differs at {', '.join(f'`{f}`' for f in fields)}")
        if limit is not None and len(lines) > limit:
            hidden = len(lines) - limit
            lines = lines[:limit] + [
                f"…and {hidden} more description(s) with the same kind of change"
            ]
        return lines


def _flatten(desc: dict) -> dict[str, object]:
    """One level of nesting flattened to ``section.key``, so a diff can name the
    field that moved rather than dumping two dicts at the reader."""
    out: dict[str, object] = {}
    for key, value in desc.items():
        if isinstance(value, dict):
            for sub, inner in value.items():
                out[f"{key}.{sub}"] = inner
        else:
            out[key] = value
    return out


def compare_dcm2bids_configs(saved: dict, fresh: dict) -> ConfigDrift:
    """Differences between a saved dcm2bids config and a freshly generated one.

    Descriptions are matched on ``id``, which is what dcm2bids itself uses to
    identify them and what stays stable when only a sidecar value changes.
    """
    saved_by_id = {str(d.get("id", "")): d for d in saved.get("descriptions", [])}
    fresh_by_id = {str(d.get("id", "")): d for d in fresh.get("descriptions", [])}

    drift = ConfigDrift(
        removed=[i for i in saved_by_id if i not in fresh_by_id],
        added=[i for i in fresh_by_id if i not in saved_by_id],
    )
    for desc_id in saved_by_id:
        if desc_id not in fresh_by_id:
            continue
        old, new = _flatten(saved_by_id[desc_id]), _flatten(fresh_by_id[desc_id])
        fields = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        if fields:
            drift.changed[desc_id] = fields
    return drift


def get_container_path(config: Config) -> Path:
    """Get the path to the dcm2bids Singularity image from config."""
    containers_dir = Path(config["paths"]["containers_dir"])
    version = config["containers"]["dcm2bids_version"]
    # Try common naming patterns
    for pattern in [
        f"dcm2bids-{version}.sif",
        f"dcm2bids-{version}.simg",
        f"dcm2bids_{version}.sif",
        "dcm2bids.sif",
        "dcm2bids.simg",
    ]:
        path = containers_dir / pattern
        if path.exists():
            return path
    # Return the default pattern even if it doesn't exist yet
    return containers_dir / f"dcm2bids-{version}.sif"
