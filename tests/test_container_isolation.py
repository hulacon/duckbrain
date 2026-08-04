"""Every container duckbrain runs must be isolated from the host's Python.

The bug this exists for, reported by a beta tester 2026-08-04 and reproduced on
Talapas the same day: MRIQC crashed while building its workflow because
``transforms3d`` called a function NumPy 2.0 removed. The image ships NumPy
1.26.4 and does not have that problem. What it was actually importing was the
*user's* NumPy, out of ``~/.local/lib/python3.11/site-packages``.

``--cleanenv``, which every invocation already passed, does not prevent that. It
clears environment variables; apptainer still binds ``$HOME`` by default, and
CPython still adds the user's site-packages to ``sys.path`` ahead of the image's
own. Measured inside the real image:

    container python: 3.11.8
    numpy version   : 1.26.4
    user site enabled: True
       LEAK: /home/bhutch/.local/lib/python3.11/site-packages

The MRIQC 24.0.2 and fMRIPrep 24.1.1 images are both Python 3.11, so one host
directory shadows both.

Two kinds of test here, and the sweeps are the durable half. A per-site
assertion cannot fail for the site nobody added yet, and there are nine of them —
five Python command builders and four lines across three sbatch templates. The
sweeps say the flags are spelled *once* and that every site uses that spelling.
"""

import ast
from pathlib import Path

import pytest

from duckbrain.core.containers import ISOLATION_FLAGS, isolation_flags, isolation_flags_sh
from duckbrain.slurm.templates import _get_templates_dir, build_context, render_sbatch

SRC = Path(__file__).resolve().parent.parent / "src" / "duckbrain"
# The one module allowed to spell the flags, because it is where they are defined.
_DEFINING_MODULE = SRC / "core" / "containers.py"
_RUNTIMES = {"singularity", "apptainer"}


def test_the_flags_disable_user_site_packages():
    """The whole point, stated once so the rest of the file can lean on it.

    ``--cleanenv`` is necessary and was never sufficient; ``PYTHONNOUSERSITE=1``
    is what actually stops the host's packages being imported.
    """
    assert "--cleanenv" in ISOLATION_FLAGS
    # Passed as `--env NAME=VALUE`, so the two have to be adjacent and in order.
    flags = list(ISOLATION_FLAGS)
    assert flags[flags.index("--env") + 1] == "PYTHONNOUSERSITE=1"
    assert isolation_flags() == flags
    assert isolation_flags() is not isolation_flags(), "must hand out a fresh list"
    assert isolation_flags_sh() == "--cleanenv --env PYTHONNOUSERSITE=1"


# ---- Sweeps: the flags are spelled once, and every site uses that spelling ----


def _python_sources():
    return sorted(p for p in SRC.rglob("*.py") if p != _DEFINING_MODULE)


def _container_argvs(tree):
    """Every list literal that looks like ``["singularity", ...]``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.List) or not node.elts:
            continue
        first = node.elts[0]
        if isinstance(first, ast.Constant) and first.value in _RUNTIMES:
            yield node


def test_every_container_command_in_src_splats_the_shared_flags():
    """A new command builder cannot quietly omit the isolation flags.

    Structural rather than textual: it asserts the argv is *built from* the
    shared constant, so a site that hand-rolls an equivalent string still fails.
    """
    checked = 0
    for path in _python_sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for argv in _container_argvs(tree):
            checked += 1
            starred = [
                e
                for e in argv.elts
                if isinstance(e, ast.Starred)
                and isinstance(e.value, ast.Call)
                and getattr(e.value.func, "id", getattr(e.value.func, "attr", None))
                == "isolation_flags"
            ]
            assert starred, (
                f"{path.relative_to(SRC)} builds a container argv without *isolation_flags()"
            )
    # If this drops to zero the sweep has stopped looking at anything — most
    # likely because the argv shape changed — and would pass vacuously forever.
    assert checked >= 5, f"expected at least 5 container argvs in src/, found {checked}"


def test_no_module_outside_containers_spells_the_flags_itself():
    """Spelled in one place. Nine sites is eight chances to drift."""
    for path in _python_sources():
        text = path.read_text()
        for flag in ("--cleanenv", "PYTHONNOUSERSITE"):
            assert flag not in text, (
                f"{path.relative_to(SRC)} spells {flag!r} itself — "
                "import isolation_flags from core.containers instead"
            )


def test_no_template_spells_the_flags_itself():
    """Same rule for the sbatch side, where `build_context` supplies them."""
    for path in sorted(_get_templates_dir().glob("*.sbatch.j2")):
        text = path.read_text()
        for flag in ("--cleanenv", "PYTHONNOUSERSITE"):
            assert flag not in text, f"{path.name} spells {flag!r} itself"


def test_every_template_container_line_carries_the_flags():
    """A template that runs a container and forgets the flags is the tenth site.

    Text sweep for the same reason the ``paths.work_dir`` sweep is one: the
    failure is a *new* template, which no per-template rendering test covers.
    """
    checked = 0
    for path in sorted(_get_templates_dir().glob("*.sbatch.j2")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if not any(stripped.startswith(f"{r} {v}") for r in _RUNTIMES for v in ("run", "exec")):
                continue
            checked += 1
            assert "{{ container_flags }}" in line, f"{path.name}:{n} runs a container unisolated"
    assert checked >= 4, f"expected at least 4 container lines in templates, found {checked}"


# ---- Behaviour: what actually reaches the shell ------------------------------
#
# Config and per-template arguments come from `test_sbatch_templates`, which
# already maintains one valid context per template. Sharing them means a template
# added there is checked here too, rather than here having its own list that
# quietly stops covering everything.
from test_sbatch_templates import _TEMPLATE_DEFAULTS, _cfg  # noqa: E402


def _container_lines(script):
    return [
        ln for ln in script.splitlines() if ln.strip().startswith(("singularity ", "apptainer "))
    ]


@pytest.mark.parametrize("step", sorted(_TEMPLATE_DEFAULTS))
def test_a_rendered_sbatch_disables_user_site_packages(step):
    """End to end: the flag is in the script SLURM will actually run.

    Over *every* template, not the container ones only — the NORDIC pair runs
    MATLAB and renders no container line today, and the point is that if one ever
    grows one it is covered without anybody remembering to add it here.
    """
    script = render_sbatch(step, build_context(_cfg(), step, **_TEMPLATE_DEFAULTS[step]))
    for line in _container_lines(script):
        assert "--cleanenv" in line, line
        assert "--env PYTHONNOUSERSITE=1" in line, line


def test_the_rendered_sbatches_do_run_containers():
    """Guards the test above against passing because it found nothing to check."""
    total = sum(
        len(_container_lines(render_sbatch(step, build_context(_cfg(), step, **extra))))
        for step, extra in _TEMPLATE_DEFAULTS.items()
    )
    assert total >= 4, f"expected at least 4 rendered container invocations, found {total}"


def test_the_flags_reach_the_script_unquoted():
    """They are several arguments; `| sh` would collapse them into one.

    The mistake is easy to make because every *path* in these templates does
    carry `| sh`, and it fails in the ugliest way — apptainer receiving one
    unknown flag whose name is the whole string.
    """
    script = render_sbatch("mriqc", build_context(_cfg(), "mriqc", **_TEMPLATE_DEFAULTS["mriqc"]))
    assert "'--cleanenv --env PYTHONNOUSERSITE=1'" not in script
    assert "singularity run --cleanenv --env PYTHONNOUSERSITE=1 \\" in script


def test_every_built_command_disables_user_site_packages():
    """The Python builders, which the GUI and the fsaverage preflight use."""
    from duckbrain.core.conversion import build_dcm2bids_command
    from duckbrain.core.fmriprep import build_fmriprep_command
    from duckbrain.core.mriqc import build_mriqc_command
    from duckbrain.core.validation import validator_command

    built = {
        "mriqc": build_mriqc_command("/b", "/o", "/w", "/c/m.simg", subject="04"),
        "fmriprep": build_fmriprep_command("/b", "/o", "/w", "04", "/c/f.simg", "/opt/lic.txt"),
        "dcm2bids": build_dcm2bids_command("04", "01", "/d", "/b", "/c/cfg.json", "/c/d.sif"),
        "validator": validator_command("/c/d.sif", "/b"),
    }
    for name, cmd in built.items():
        assert cmd[0] in _RUNTIMES, name
        assert "--cleanenv" in cmd, name
        assert cmd[cmd.index("--env") + 1] == "PYTHONNOUSERSITE=1", name
        # Before the image path, or apptainer reads it as an argument to the tool.
        assert cmd.index("--env") < next(
            i for i, a in enumerate(cmd) if a.endswith((".simg", ".sif"))
        ), name


def test_the_fsaverage_preflight_is_isolated_too(monkeypatch):
    """The one site that runs `python -c` in the image, so the most exposed.

    It executes rather than returning an argv, so the command is captured off
    ``subprocess.run``.
    """
    import subprocess

    from duckbrain.core import fsaverage

    seen = {}

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(fsaverage.subprocess, "run", _fake_run)
    fsaverage._run_in_container("/c/f.simg", "print(1)", [], [])

    cmd = seen["cmd"]
    assert cmd[0] in _RUNTIMES
    assert "--cleanenv" in cmd
    assert cmd[cmd.index("--env") + 1] == "PYTHONNOUSERSITE=1"
