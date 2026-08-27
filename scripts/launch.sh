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

echo "============================================"
echo "  duckbrain — Neuroimaging Toolbox"
echo "============================================"
echo "  Node:    $(hostname)"
echo "  Port:    $PORT"
echo "  Config:  $DUCKBRAIN_CONFIG_DIR"
echo "  Project: ${DUCKBRAIN_PROJECT_DIR:-(choose in Project Setup)}"
echo ""
echo "  Access via SSH tunnel:"
echo "    ssh -L ${PORT}:$(hostname):${PORT} $(whoami)@talapas-login.uoregon.edu"
echo "  Then open: http://localhost:${PORT}"
echo ""
echo "  (From an OnDemand Desktop running on this node, skip the tunnel:"
echo "   open http://localhost:${PORT} in the desktop's own browser.)"
echo "============================================"

streamlit run "$PROJECT_DIR/src/duckbrain/gui/app.py" \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
