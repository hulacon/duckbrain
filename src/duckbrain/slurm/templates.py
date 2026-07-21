"""Jinja2 SBATCH template rendering."""

from __future__ import annotations

from pathlib import Path

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

    template_file = f"{step_name}.sbatch.j2"
    template = env.get_template(template_file)
    return template.render(**context)


def build_context(config: dict, step: str, **extra) -> dict:
    """Build a template context dict from config + extra variables.

    Merges the full config with per-step SLURM overrides and any
    additional keyword arguments (subject, session, etc.).
    """
    from ..config import get_slurm_resources

    slurm = get_slurm_resources(config, step)
    paths = config.get("paths", {})

    context = {
        "slurm": slurm,
        "paths": paths,
        "containers": config.get("containers", {}),
        "fmriprep": config.get("fmriprep", {}),
        "nordic": config.get("nordic", {}),
        # Default on: the validator is already inside the dcm2bids container, so
        # the only cost of leaving it off is not knowing.
        "bids_validate": (config.get("conversion") or {}).get("bids_validate", True),
    }
    context.update(extra)
    return context
