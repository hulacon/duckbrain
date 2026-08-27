#!/usr/bin/env bash
# Create or update duckbrain's conda environment on Talapas.
#
# Why this is a script rather than a line in a README: on this cluster a plain
# `conda env create -f environment.yml` silently resolves against FSL's
# channel (fslinstaller writes ~/.condarc with `channels: #!final`, and
# `conda env create` has no channel flags). See the header of environment.yml.
# The recipe is braintwill's, taken working rather than re-derived:
# /projects/hulacon/shared/mmmdata/code/braintwill/docs/talapas-conda.md.
#
#   ./scripts/setup_env.sh                 # create/update at the shared prefix
#   ./scripts/setup_env.sh --personal      # ~/.conda/envs/duckbrain instead
#   ./scripts/setup_env.sh --prefix PATH   # somewhere else entirely
#   ./scripts/setup_env.sh --dry-run       # solve only, install nothing
#
# Read-only network + a solve; safe on a login node, takes a few minutes.
#
# The default prefix is shared: one build under /projects/<pirg>/shared/envs
# serves the whole PIRG instead of each user growing a private copy under
# ~/.conda (invisible to everyone else — /home dirs here are drwx------ — and
# ~1.2 G each). The PIRG is read off this checkout's own physical path, so a
# clone under /projects/osl/... defaults to /projects/osl/shared/envs/duckbrain
# — this used to hardcode hulacon's prefix, which made the README's "shared by
# default" promise a permission error for every other PIRG. A clone outside
# /projects has no PIRG to share with: pass --personal or --prefix there.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Physical path, not the invoked one: a clone reached through a $HOME symlink
# still belongs to the PIRG whose filesystem holds it.
case "$(cd "$REPO" && pwd -P)" in
  /projects/*|/gpfs/projects/*)
    pirg="$(cd "$REPO" && pwd -P)"
    pirg="${pirg#/gpfs}"; pirg="${pirg#/projects/}"; pirg="${pirg%%/*}"
    SHARED_PREFIX="/projects/${pirg}/shared/envs/duckbrain"
    ;;
  *)
    SHARED_PREFIX=""
    ;;
esac
PREFIX="$SHARED_PREFIX"
CONDA_MODULE=miniconda3/20260319
DRY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --personal) PREFIX="$HOME/.conda/envs/duckbrain"; shift ;;
    --prefix)   PREFIX="${2:?--prefix needs a path}"; shift 2 ;;
    --dry-run)  DRY="--dry-run"; shift ;;
    -h|--help)  sed -n '2,25p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$PREFIX" ]]; then
  echo "error: this clone is outside /projects, so there is no PIRG to share an env with." >&2
  echo "       Pass --personal, or --prefix /projects/<your-pirg>/shared/envs/duckbrain." >&2
  exit 2
fi

# Refuse an unwritable prefix now, not after the multi-minute solve — conda's
# own permission error arrives at install time with the work already done.
# (--dry-run is exempt: solving against a prefix you can only read is legal.)
if [[ -z "$DRY" ]]; then
  probe="$PREFIX"
  while [[ ! -d "$probe" ]]; do probe="$(dirname "$probe")"; done
  if [[ ! -w "$probe" ]]; then
    echo "error: $PREFIX is not writable by you (nearest existing dir: $probe)." >&2
    echo "       Use --personal, or --prefix somewhere your account can write." >&2
    exit 2
  fi
fi

# 1. conda itself. A bare `conda` on $PATH here is FSL's (6.0.7.9, conda
#    23.11), not a module's, so load the module explicitly. NB: `module` is a
#    shell function that edits this shell's PATH — piping its output runs it
#    in a subshell and silently discards the load.
source /etc/profile.d/z00_lmod.sh 2>/dev/null || source /etc/profile.d/modules.sh 2>/dev/null || true
module load "$CONDA_MODULE" 2>/dev/null || {
  echo "error: could not 'module load $CONDA_MODULE'." >&2
  echo "       'module avail miniconda3' lists what is installed." >&2
  exit 1
}

# 2. Channels — the whole reason the script exists. Three things do NOT beat
#    the FSL condarc, all checked on-cluster 2026-08-04: pointing $CONDARC at
#    a clean file (it is *added* to the search path, not substituted), setting
#    CONDA_CHANNELS (#!final outranks it), and `conda env create` (no channel
#    flags at all). What works is `--override-channels -c conda-forge` on a
#    plain `conda create`/`conda install`, so this script reads the package
#    list out of environment.yml and passes it to those.
export CONDARC="$REPO/conda/condarc"          # for channel_priority, not channels
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$HOME/.conda/pkgs}"

# ~/.local/lib/pythonX.Y/site-packages sits AHEAD of any non-venv env's own
# site-packages — the same mechanism that put a beta tester's host NumPy
# inside every container (memory/container-host-python-leak), and it bit this
# script's first build live: the env solved streamlit 1.61.1 / nibabel 5.4.2
# and imported 1.56.0 / 5.3.3 out of this account's stale `pip install
# --user` leftovers. A venv is immune (venvs disable user site); a conda env
# is not. Exported here for every python this script runs; the activate.d
# hook below covers `conda activate` users; the launch scripts export it
# themselves.
export PYTHONNOUSERSITE=1

# environment.yml stays the single source of the conda package list. Parsed
# with sed rather than a YAML library on purpose: after `module load
# miniconda3` the python3 on $PATH is the module's, which has no pyyaml, and
# bootstrapping a parser to read the file that describes the environment is a
# circular mess. Range-limited to the dependencies block: `channels:` uses the
# same indent, and without the range `conda-forge` would silently be parsed as
# a package to install.
mapfile -t DEPS < <(
  sed -n '/^dependencies:/,$p' "$REPO/environment.yml" \
    | grep -E '^  - ' \
    | sed -e 's/#.*//' -e 's/^  - //' -e 's/[[:space:]]*$//' \
    | grep -v '^$' | grep -v '^pip:$'
)

[[ ${#DEPS[@]} -gt 0 ]] || { echo "error: no dependencies parsed" >&2; exit 1; }

# The pip half is NOT parsed from environment.yml: it is exactly one entry,
# `-e .[dev]`, and pyproject.toml owns everything it resolves. Assert the file
# still says what this script does, so the two cannot drift silently.
if ! grep -qE '^\s+- -e \.\[dev\]$' "$REPO/environment.yml"; then
  echo "error: environment.yml's pip section is not the expected '-e .[dev]'." >&2
  echo "       This script hardcodes that step; update both together." >&2
  exit 1
fi

echo "prefix  : $PREFIX"
echo "packages: ${#DEPS[@]} from environment.yml, then pip -e '$REPO[dev]'"
echo "channels: conda-forge only (enforced with --override-channels)"
echo

parent="$(dirname "$PREFIX")"
if [[ ! -d "$parent" ]]; then
  mkdir -p "$parent"
  # Group-writable + setgid so the PIRG can read and extend it, matching the
  # convention on /projects/hulacon/shared itself.
  [[ "$PREFIX" == "$SHARED_PREFIX" ]] && chmod 2775 "$parent" || true
fi

if [[ -d "$PREFIX" && -n "$(ls -A "$PREFIX" 2>/dev/null)" ]]; then
  echo "==> environment exists; installing/updating into it"
  echo "    NOTE: an incremental solve can land on different versions than a"
  echo "    fresh create (observed 2026-08-04 on braintwill: nilearn moved"
  echo "    backwards while scikit-learn moved forwards). The lockfile written"
  echo "    below would then describe this env rather than what a new user"
  echo "    gets. Before committing a lockfile, delete the prefix and rebuild."
  ACTION=(conda install --prefix "$PREFIX")
else
  echo "==> creating"
  ACTION=(conda create --prefix "$PREFIX")
fi

"${ACTION[@]}" --override-channels -c conda-forge --yes $DRY "${DEPS[@]}"

if [[ -n "$DRY" ]]; then
  echo; echo "dry run — nothing installed, no lockfile written."
  echo "pip step would run: pip install -e '$REPO[dev]'"
  exit 0
fi

# 3. duckbrain itself plus the dev extra, editable, from THIS checkout. No
#    --no-deps: pip must be free to fetch pytest/pytest-cov and the pinned
#    ruff/mypy from PyPI at pyproject.toml's bounds. The runtime floors are
#    all satisfied by the conda builds above, so pip leaves those alone — and
#    the check below proves it did rather than assuming.
echo
echo "==> pip install -e '$REPO[dev]'"
conda run --prefix "$PREFIX" python -m pip install --quiet -e "$REPO[dev]"

# 4. Verify rather than assume — three checks, each failing the script.
#
#    (a) Channel purity: nothing resolved from FSL's channel or defaults.
#    The whole channel argument above is only as good as this check.
echo
echo "==> verifying channel purity"
strays="$(conda list --prefix "$PREFIX" --show-channel-urls 2>/dev/null \
          | grep -vE '^#' | awk 'NF{print $NF}' \
          | grep -viE 'conda-forge|^pypi$' || true)"
if [[ -n "$strays" ]]; then
  echo "FAIL: packages resolved from a channel other than conda-forge:" >&2
  echo "$strays" | sort | uniq -c >&2
  echo "Do not use this environment; fix the channel handling first." >&2
  exit 1
fi
echo "ok — conda-forge (+ pypi for the dev extra) only"

#    (b) No runtime package shadowed by a pip wheel. `pypi` is a legitimate
#    channel for the dev tools; for the runtime set it means step 3 resolved
#    something conda should own — the classic way a conda+pip env goes wrong.
echo "==> verifying no runtime package came from pip"
shadowed="$(conda list --prefix "$PREFIX" --show-channel-urls 2>/dev/null \
            | awk '$NF=="pypi"{print $1}' \
            | grep -iE '^(streamlit|jinja2|pandas|nibabel|plotly|pydicom|tomli-w|numpy)$' || true)"
if [[ -n "$shadowed" ]]; then
  echo "FAIL: runtime packages installed by pip instead of conda:" >&2
  echo "$shadowed" >&2
  echo "The conda build no longer satisfies pyproject.toml's floor for" >&2
  echo "these; raise the conda side deliberately rather than shipping a" >&2
  echo "mixed env." >&2
  exit 1
fi
echo "ok — runtime set is conda-managed"

# 5. Snapshot exact builds. environment.yml states *intent* and is
#    deliberately unpinned; this states what one clean solve actually
#    resolved, so a build months later is reproducible rather than merely
#    similar.
LOCK="$REPO/conda/lock-linux-64.txt"
echo
echo "==> writing $LOCK"
{
  echo "# Exact builds resolved by scripts/setup_env.sh. Regenerate by re-running it"
  echo "# against a DELETED prefix (an incremental solve is not a fresh one)."
  echo "# Recreate with:"
  echo "#   conda create --prefix <path> --file conda/lock-linux-64.txt"
  echo "#   <prefix>/bin/python -m pip install -e '<checkout>[dev]'"
  echo "# Intent lives in environment.yml; this file records one solve."
  echo "#"
  echo "# NOT A COMPLETE LOCK ON ITS OWN: 'conda list --explicit' omits"
  echo "# pip-installed packages; the dev extra's pins live in pyproject.toml."
  conda list --prefix "$PREFIX" --explicit
} > "$LOCK"
echo "    $(grep -c '^https' "$LOCK") conda packages pinned"

# Make `conda activate <prefix>` itself set PYTHONNOUSERSITE=1, so the
# documented activate-and-run-pytest path is protected too, not just this
# script and the launchers.
mkdir -p "$PREFIX/etc/conda/activate.d" "$PREFIX/etc/conda/deactivate.d"
cat > "$PREFIX/etc/conda/activate.d/duckbrain-no-user-site.sh" <<'HOOK'
# ~/.local site-packages shadow a conda env's own (a venv is immune, this env
# is not). Written by scripts/setup_env.sh; see the comment there.
export _DUCKBRAIN_SAVED_PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-}"
export PYTHONNOUSERSITE=1
HOOK
cat > "$PREFIX/etc/conda/deactivate.d/duckbrain-no-user-site.sh" <<'HOOK'
if [ -n "${_DUCKBRAIN_SAVED_PYTHONNOUSERSITE:-}" ]; then
  export PYTHONNOUSERSITE="$_DUCKBRAIN_SAVED_PYTHONNOUSERSITE"
else
  unset PYTHONNOUSERSITE
fi
unset _DUCKBRAIN_SAVED_PYTHONNOUSERSITE
HOOK

#    (c) Import everything, from the env, and say what resolved. A resolved
#    dependency is not a verified one: conda-forge has name collisions that
#    solve cleanly (braintwill's `himalaya` installed one binary and no Python
#    package behind a green solve and a green channel check). Only the import
#    settles it. Each module must also resolve from INSIDE the prefix — the
#    first run of this check printed plausible versions that were actually
#    ~/.local's, and a check that reports without failing gets read once and
#    trusted forever.
#    The env's python is invoked directly, not via `conda run`: conda run
#    does not forward stdin, so a heredoc script under it runs EMPTY and
#    exits 0 — a vacuous pass, observed on this script's second run.
echo
"$PREFIX/bin/python" - "$PREFIX" <<'PYCHECK'
import sys
prefix = sys.argv[1]
assert sys.executable.startswith(prefix), sys.executable
import duckbrain
import streamlit, jinja2, pandas, nibabel, plotly, pydicom, tomli_w
print('python      ', sys.version.split()[0])
bad = []
for m in (streamlit, jinja2, pandas, nibabel, plotly, pydicom, tomli_w, duckbrain):
    where = getattr(m, '__file__', '') or ''
    print(f'{m.__name__:<12}', getattr(m, '__version__', 'unknown'))
    # duckbrain is editable-installed from the checkout, so it is exempt.
    if m.__name__ != 'duckbrain' and not where.startswith(prefix):
        bad.append(f'{m.__name__} imported from {where}')
if bad:
    print('\nFAIL: modules resolved from outside the environment:', file=sys.stderr)
    print('\n'.join(bad), file=sys.stderr)
    sys.exit(1)
from duckbrain.config import load_config  # exercise an entry point, not just the import
print()
print('smoke: imports resolve from the prefix; duckbrain.config.load_config resolves')
PYCHECK
echo
echo "==> dev tools"
conda run --prefix "$PREFIX" ruff --version
conda run --prefix "$PREFIX" mypy --version
conda run --prefix "$PREFIX" python -m pytest --version

# 6. Record the prefix in the checkout so scripts/launch.sh and the OnDemand
#    app find this env without a hardcoded path (the file is gitignored; each
#    checkout records the env built for it).
echo "$PREFIX" > "$REPO/.conda-prefix"
echo
echo "recorded $PREFIX in $REPO/.conda-prefix"

cat <<EOF

Activate with:
  module load $CONDA_MODULE
  conda activate $PREFIX

scripts/launch.sh and the OnDemand app now pick this env up automatically
(via .conda-prefix). A .venv, if present, is only used when no conda env is
recorded.
EOF
