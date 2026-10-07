#!/bin/bash
# launch.sh — Start duckbrain Streamlit GUI on a Talapas compute node.
#
# Usage:
#   bash scripts/launch.sh              # Start on login node (for quick testing)
#   srun --pty bash scripts/launch.sh   # Start on a compute node (recommended)
#
# For a dedicated interactive session:
#   srun --partition=interactive --time=04:00:00 --mem=4G --cpus-per-task=2 --pty bash scripts/launch.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Environment, in precedence order:
#   1. the conda env scripts/setup_env.sh recorded in .conda-prefix
#      ($DUCKBRAIN_CONDA_PREFIX overrides the file);
#   2. the legacy .venv, if present.
# The conda branch prepends bin/ rather than `conda activate`: activation
# needs conda's shell hook, which this non-login shell may not have, and
# nothing in this env's activate scripts is load-bearing for Streamlit.
# PYTHONPATH then makes THIS checkout the code that serves, even if the
# (possibly shared) env has a different checkout editable-installed —
# otherwise a user launching their own clone would silently run someone
# else's code, and provenance (git describe of the imported package's repo)
# would follow it.
if [ -z "${DUCKBRAIN_CONDA_PREFIX:-}" ] && [ -f "$PROJECT_DIR/.conda-prefix" ]; then
    DUCKBRAIN_CONDA_PREFIX="$(cat "$PROJECT_DIR/.conda-prefix")"
fi
if [ -n "${DUCKBRAIN_CONDA_PREFIX:-}" ] && [ -x "$DUCKBRAIN_CONDA_PREFIX/bin/streamlit" ]; then
    export PATH="$DUCKBRAIN_CONDA_PREFIX/bin:$PATH"
    export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    # ~/.local site-packages shadow a conda env's own (a venv is immune; a
    # conda env is not) — the host-side twin of the container leak. Without
    # this, a stale `pip install --user` streamlit silently serves instead of
    # the env's.
    export PYTHONNOUSERSITE=1
elif [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# Locate the shipped base.toml (defaults). Project-specific settings live inside
# the chosen project dir; shared resources live in ~/.config/duckbrain/.
export DUCKBRAIN_CONFIG_DIR="$PROJECT_DIR/config"

# Optionally pre-select a project directory. If unset, choose one in Project Setup.
if [ -n "${DUCKBRAIN_PROJECT_DIR:-}" ]; then
    export DUCKBRAIN_PROJECT_DIR
fi

# Find an available port
PORT=${DUCKBRAIN_PORT:-8501}

# The GUI acts as whoever started it, so it answers only a browser holding
# this session's token (src/duckbrain/gui/access.py). Localhost keeps other
# hosts out; the token keeps out other users on this one, since compute nodes
# are shared between jobs and a login node is shared by everyone. The link
# below carries it, so nobody types it.
DUCKBRAIN_ACCESS_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export DUCKBRAIN_ACCESS_TOKEN
LINK="http://localhost:${PORT}/?token=${DUCKBRAIN_ACCESS_TOKEN}"

echo "============================================"
echo "  duckbrain — Neuroimaging Toolbox"
echo "============================================"
echo "  Node:    $(hostname)"
echo "  Port:    $PORT"
echo "  Config:  $DUCKBRAIN_CONFIG_DIR"
echo "  Project: ${DUCKBRAIN_PROJECT_DIR:-(choose in Project Setup)}"
echo ""
echo "  From your own computer, open an SSH tunnel:"
echo "    ssh -L ${PORT}:localhost:${PORT} -J $(whoami)@talapas-login.uoregon.edu $(whoami)@$(hostname)"
echo "  Then open this link (it is your key to this session; don't share it):"
echo "    ${LINK}"
echo ""
echo "  (From an OnDemand Desktop running on this node, skip the tunnel and"
echo "   open the same link in the desktop's own browser.)"
echo "============================================"

# Localhost only: the -J tunnel above ends on this node (Slurm lets you ssh to
# a node where you hold a job), so nothing is lost. The OnDemand app has to
# listen on the network for its proxy, and relies on the same token.
streamlit run "$PROJECT_DIR/src/duckbrain/gui/serve.py" \
    --server.port "$PORT" \
    --server.address 127.0.0.1 \
    --server.headless true \
    --browser.gatherUsageStats false
