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

# Activate venv if it exists
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
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
echo "============================================"

streamlit run "$PROJECT_DIR/src/duckbrain/gui/app.py" \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
