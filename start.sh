#!/usr/bin/env bash
# start.sh — Launch Streamlit + ngrok tunnel in one command.
#
# Usage:    ./start.sh
# Stop:     Ctrl+C  (kills both Streamlit and ngrok cleanly)
#
# Config (via .env):
#   NGROK_DOMAIN    — ngrok static domain  (default: shale-unfailing-backyard.ngrok-free.dev)
#   STREAMLIT_PORT  — local port to bind   (default: 8501)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env ────────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

PORT="${STREAMLIT_PORT:-8501}"
NGROK_DOMAIN="${NGROK_DOMAIN:-shale-unfailing-backyard.ngrok-free.dev}"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Pre-flight checks ────────────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/data/storage_state.json" ]]; then
    echo ""
    echo "  ERROR: data/storage_state.json is missing — Scaler session not captured."
    echo ""
    echo "  Run:  python3 capture_login.py"
    echo "  Then: ./start.sh"
    echo ""
    exit 1
fi

# ── Activate venv if present and not already active ──────────────────────────
if [[ -f "$SCRIPT_DIR/.venv/bin/activate" && -z "${VIRTUAL_ENV:-}" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# ── Sync dependencies (fast no-op when already up to date) ──────────────────
if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
    PIP_CMD=""
    if command -v pip &>/dev/null; then PIP_CMD="pip"
    elif command -v pip3 &>/dev/null; then PIP_CMD="pip3"
    fi
    if [[ -n "$PIP_CMD" ]]; then
        echo "Syncing dependencies..."
        $PIP_CMD install -r "$SCRIPT_DIR/requirements.txt" -q --disable-pip-version-check
    fi
fi

# ── Resolve Streamlit launcher ───────────────────────────────────────────────
# 1. prefer the `streamlit` binary on PATH (covers venv and pipx installs)
# 2. fall back to `python3 -m streamlit` (user-site / system install)
STREAMLIT_CMD=""
if command -v streamlit &>/dev/null; then
    STREAMLIT_CMD="streamlit"
elif python3 -c "import streamlit" &>/dev/null 2>&1; then
    STREAMLIT_CMD="python3 -m streamlit"
else
    echo ""
    echo "  ERROR: Streamlit is not installed or not importable."
    echo "  Fix:   pip3 install -r requirements.txt"
    echo ""
    exit 1
fi

if ! command -v ngrok &>/dev/null; then
    echo ""
    echo "  ERROR: 'ngrok' not found in PATH."
    echo "  Install:  brew install ngrok/ngrok/ngrok"
    echo ""
    exit 1
fi

# ── Kill any stale Streamlit / ngrok from a previous run ─────────────────────
echo "Clearing any stale processes..."
# Kill whatever process owns port $PORT (old Streamlit / any prior process)
lsof -ti :"$PORT" | xargs kill -TERM 2>/dev/null || true
# Kill ALL ngrok processes by name — domain may not appear in the command line
# (e.g. set via ngrok.yml or a different flag), so pattern matching is unreliable
killall -TERM ngrok 2>/dev/null || true
# Wait for sockets to release AND for ngrok cloud to deregister the endpoint
# (ERR_NGROK_334 occurs even when the local process is dead but cloud hasn't
# released the tunnel yet; 5 s is enough in practice)
sleep 5

# ── PID tracking (used by cleanup trap) ─────────────────────────────────────
STREAMLIT_PID=""
NGROK_PID=""

cleanup() {
    echo ""
    echo "Stopping NV Contest Agent..."
    [[ -n "$STREAMLIT_PID" ]] && kill "$STREAMLIT_PID" 2>/dev/null || true
    [[ -n "$NGROK_PID"     ]] && kill "$NGROK_PID"     2>/dev/null || true
    wait "$STREAMLIT_PID" "$NGROK_PID" 2>/dev/null || true
    rm -f "$SCRIPT_DIR/data/run.lock"   # clear stale lock if killed mid-run
    echo "Stopped."
}
trap cleanup EXIT INT TERM

# ── Start Streamlit ──────────────────────────────────────────────────────────
echo "Starting Streamlit on port $PORT  (launcher: $STREAMLIT_CMD)..."
$STREAMLIT_CMD run streamlit_app.py \
    --server.port "$PORT" \
    --server.headless true \
    --server.runOnSave false \
    > >(tee -a "$LOG_DIR/streamlit.log") 2>&1 &
STREAMLIT_PID=$!

# Wait for Streamlit health endpoint (up to 30 s)
echo -n "  Waiting"
READY=0
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$PORT/_stcore/health" > /dev/null 2>&1; then
        READY=1; break
    fi
    echo -n "."; sleep 1
done
echo ""
if [[ $READY -eq 0 ]]; then
    echo "  ERROR: Streamlit did not start within 30 s."
    echo "  Check: $LOG_DIR/streamlit.log"
    exit 1
fi
echo "  Streamlit ready."

# ── Start ngrok ──────────────────────────────────────────────────────────────
echo "Starting ngrok tunnel → https://$NGROK_DOMAIN/ ..."
ngrok http \
    --url="$NGROK_DOMAIN" \
    --log=stdout \
    "$PORT" \
    > >(tee -a "$LOG_DIR/ngrok.log") 2>&1 &
NGROK_PID=$!
sleep 2   # brief pause for tunnel handshake

# ── Ready banner ─────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════"
echo "  NV Contest Agent is live"
echo ""
echo "  PUBLIC  →  https://$NGROK_DOMAIN/"
echo "  LOCAL   →  http://localhost:$PORT"
echo ""
echo "  Logs:   logs/streamlit.log"
echo "          logs/ngrok.log"
echo ""
echo "  Stop:   Ctrl+C"
echo "══════════════════════════════════════════════════════"
echo ""

wait "$STREAMLIT_PID"
