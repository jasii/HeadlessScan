#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

BACKEND_PORT=8000
FRONTEND_PORT=5173

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
die()     { echo -e "${RED}[error]${RESET} $*" >&2; exit 1; }

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PIDS=()
cleanup() {
    echo ""
    info "Shutting down…"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null || true
    done
    success "All services stopped."
}
trap cleanup EXIT INT TERM

# ── Check tools ───────────────────────────────────────────────────────────────
command -v python3 &>/dev/null || die "python3 not found."
command -v node    &>/dev/null || die "node not found."
command -v npm     &>/dev/null || die "npm not found."

# ── Backend: virtualenv + dependencies ───────────────────────────────────────
VENV="$BACKEND_DIR/.venv"
if [[ ! -d "$VENV" ]]; then
    info "Creating Python virtual environment…"
    python3 -m venv "$VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

info "Installing / checking Python dependencies…"
pip install -q -r "$BACKEND_DIR/requirements.txt"
success "Python dependencies ready."

# ── Frontend: npm install ─────────────────────────────────────────────────────
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    info "Installing Node dependencies (this may take a moment)…"
    npm --prefix "$FRONTEND_DIR" install --silent
    success "Node dependencies installed."
else
    success "Node dependencies already installed."
fi

# ── Create batches directory if missing ───────────────────────────────────────
mkdir -p "$SCRIPT_DIR/batches"

# ── Start backend ─────────────────────────────────────────────────────────────
info "Starting FastAPI backend on http://localhost:${BACKEND_PORT} …"
cd "$BACKEND_DIR"
uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")
cd "$SCRIPT_DIR"

# Give the backend a moment to bind
sleep 1
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    die "Backend failed to start."
fi
success "Backend running (PID $BACKEND_PID)."

# ── Start frontend ────────────────────────────────────────────────────────────
info "Starting Vite dev server on http://localhost:${FRONTEND_PORT} …"
npm --prefix "$FRONTEND_DIR" run dev -- --port "$FRONTEND_PORT" &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

sleep 1
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    die "Frontend failed to start."
fi
success "Frontend running (PID $FRONTEND_PID)."

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}HeadlessScan is running${RESET}"
echo -e "  Frontend : ${CYAN}http://localhost:${FRONTEND_PORT}${RESET}"
echo -e "  API docs : ${CYAN}http://localhost:${BACKEND_PORT}/docs${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  Press ${BOLD}Ctrl+C${RESET} to stop all services."
echo ""

# ── Wait for either process to exit ──────────────────────────────────────────
wait -n "${PIDS[@]}" 2>/dev/null || true
