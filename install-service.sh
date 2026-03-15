#!/usr/bin/env bash
# install-service.sh
# Installs HeadlessScan as a systemd service on Debian/Ubuntu.
# Must be run as root (or with sudo).
# Does NOT start the service automatically — run: sudo systemctl start headlessscan

set -e

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
die()     { echo -e "${RED}[error]${RESET} $*" >&2; exit 1; }

# ── Must run as root ──────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || die "Please run as root: sudo ./install-service.sh"

# ── Resolve project directory (absolute path of this script's folder) ─────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV="$BACKEND_DIR/.venv"
SERVICE_NAME="headlessscan"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Determine the unprivileged user to run the service as ─────────────────────
# Use SUDO_USER if available (the user who called sudo), otherwise prompt.
if [[ -n "$SUDO_USER" && "$SUDO_USER" != "root" ]]; then
    RUN_AS="$SUDO_USER"
else
    read -rp "Enter the username the service should run as: " RUN_AS
fi

id "$RUN_AS" &>/dev/null || die "User '$RUN_AS' does not exist."
info "Service will run as user: $RUN_AS"

# ── Check required tools ──────────────────────────────────────────────────────
for cmd in python3 node npm; do
    command -v "$cmd" &>/dev/null || die "'$cmd' is not installed. Install it first."
done

# ── Build frontend (produces frontend/dist/ served by FastAPI) ────────────────
info "Installing Node dependencies…"
sudo -u "$RUN_AS" npm --prefix "$FRONTEND_DIR" install --silent

info "Building frontend…"
sudo -u "$RUN_AS" npm --prefix "$FRONTEND_DIR" run build
success "Frontend built → frontend/dist/"

# ── Python virtual environment + dependencies ─────────────────────────────────
if [[ ! -d "$VENV" ]]; then
    info "Creating Python virtual environment…"
    sudo -u "$RUN_AS" python3 -m venv "$VENV"
fi

info "Installing Python dependencies…"
sudo -u "$RUN_AS" "$VENV/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
success "Python dependencies installed."

# ── Create batches directory with correct ownership ───────────────────────────
BATCHES_DIR="$SCRIPT_DIR/batches"
mkdir -p "$BATCHES_DIR"
chown "$RUN_AS":"$RUN_AS" "$BATCHES_DIR"
success "Batches directory ready: $BATCHES_DIR"

# ── Write systemd unit file ───────────────────────────────────────────────────
info "Writing systemd unit: $SERVICE_FILE"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=HeadlessScan – Epson ADF scanner service for paperless-ng
After=network.target
Wants=network.target

[Service]
Type=simple
User=${RUN_AS}
WorkingDirectory=${BACKEND_DIR}
ExecStart=${VENV}/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

# Harden the service
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${SCRIPT_DIR}/batches

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$SERVICE_FILE"
success "Service file written."

# ── Reload systemd and enable the service ────────────────────────────────────
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
success "Service enabled (will start on next boot)."

# ── Final instructions ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}Installation complete!${RESET}"
echo -e ""
echo -e "  Start now  : ${CYAN}sudo systemctl start ${SERVICE_NAME}${RESET}"
echo -e "  Stop       : ${CYAN}sudo systemctl stop ${SERVICE_NAME}${RESET}"
echo -e "  Status     : ${CYAN}sudo systemctl status ${SERVICE_NAME}${RESET}"
echo -e "  Logs       : ${CYAN}sudo journalctl -u ${SERVICE_NAME} -f${RESET}"
echo -e ""
echo -e "  Once started, open: ${CYAN}http://localhost:8000${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
