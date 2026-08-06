"""Jinja2 SBATCH template rendering."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import jinja2


def _get_templates_dir() -> Path:
    """Locate the templates/sbatch/ directory."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "templates" / "sbatch"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise FileNotFoundError("Cannot find templates/sbatch/ directory")


def render_sbatch(step_name: str, context: dict, templates_dir: str | Path | None = None) -> str:
    """Render an sbatch template for the given pipeline step.

    Parameters
    ----------
    step_name : str
        Pipeline step name (e.g., "dcm2bids", "fmriprep", "nordic_denoise").
        Corresponds to templates/sbatch/<step_name>.sbatch.j2.
    context : dict
        Template variables. Typically includes:
        - slurm: SLURM resource settings
        - paths: project paths
        - subject, session: identifiers
        - Step-specific variables
    templates_dir : path, optional
        Override templates directory.

    Returns
    -------
    str
        Rendered sbatch script content.
    """
    if templates_dir is None:
        templates_dir = _get_templates_dir()
    else:
        templates_dir = Path(templates_dir)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    # `| sh` marks a value as exactly ONE shell argument. Every path in a
    # template is one, and Setup accepts whatever server path the user picks —
    # this is not hypothetical, /projects/lcni/dcm/hulacon/Hutchinson/New Program
    # is a real DICOM export with a space in it, one form away from a rendered
    # sbatch. Unquoted it becomes two arguments and the job fails obscurely.
    #
    # Two things it must NOT be applied to. `#SBATCH` directive lines are parsed
    # by Slurm, not bash, and quoting would put literal quotes in the value. And
    # `extra_flags` is deliberately a shell fragment the operator supplies —
    # quoting would collapse `--use-syn-sdc --fd-spike-threshold 0.5` into a
    # single argument. See the note on it in fmriprep.sbatch.j2.
    env.filters["sh"] = shlex.quote

    template_file = f"{step_name}.sbatch.j2"
    template = env.get_template(template_file)
    return template.render(**context)


def build_context(config: dict, step: str, **extra: Any) -> dict:
    """Build a template context dict from config + extra variables.

    Merges the full config with per-step SLURM overrides and any
    additional keyword arguments (subject, session, etc.).
    """
    from ..config import get_slurm_resources, unit_work_dir
    from ..core.containers import isolation_flags_sh

    slurm = get_slurm_resources(config, step)
    paths = config.get("paths", {})

    context = {
        "slurm": slurm,
        "paths": paths,
        # The flags every `singularity` line must carry, rendered once here so no
        # template spells them itself — the same rule `work_dir` below follows,
        # and for the same reason: a flag that has to be on all four lines is one
        # that will be missing from the fifth. Interpolate it WITHOUT `| sh`;
        # it is several arguments and quoting collapses it into one.
        # `core.containers.ISOLATION_FLAGS` says what they are and why.
        "container_flags": isolation_flags_sh(),
        "containers": config.get("containers", {}),
        "fmriprep": config.get("fmriprep", {}),
        "nordic": config.get("nordic", {}),
        # Default on: the validator is already inside the dcm2bids container, so
        # the only cost of leaving it off is not knowing.
        "bids_validate": (config.get("conversion") or {}).get("bids_validate", True),
    }
    context.update(extra)
    # Derived here rather than by each caller, so no template ever has to build a
    # scratch path out of `paths.work_dir` itself — that is how the bare
    # `/tmp/sub-<label>` two studies could share got written twice. Set after the
    # update so `extra` cannot quietly supply a different one; the tests in
    # test_sbatch_templates.py assert no template reads `paths.work_dir`.
    context["work_dir"] = unit_work_dir(
        config, step, str(context.get("subject") or ""), str(context.get("session") or "")
    )
    return context
