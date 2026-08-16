#!/bin/bash

# GoobyDesk Production Uninstaller
# Removes the application, systemd service, and log artifacts created by the
# installation guide while keeping the operation safe and reviewable.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TARGET_DIR=${TARGET_DIR:-/var/www/GoobyDesk}
SERVICE_NAME=${SERVICE_NAME:-goobydesk.service}
LOGFILE=${LOGFILE:-/var/log/goobydesk.log}
DRY_RUN=${DRY_RUN:-0}
FORCE=${FORCE:-0}

usage() {
    cat <<EOF
Usage: sudo ./uninstaller.sh [--force] [--dry-run]

Options:
  --force     Skip the confirmation prompt.
  --dry-run   Show actions without deleting files.
  -h, --help  Show this help message.
EOF
}

log() {
    printf '%s\n' "$1"
}

warn() {
    printf '%b%s%b\n' "$YELLOW" "$1" "$NC"
}

error() {
    printf '%b%s%b\n' "$RED" "$1" "$NC" >&2
}

confirm() {
    if [[ "$FORCE" == "1" ]]; then
        return 0
    fi

    cat <<EOF
This will permanently remove:
  - Systemd service: $SERVICE_NAME
  - Application directory: $TARGET_DIR
  - Logs: $LOGFILE
  - Caddy access and error logs if present

It will NOT automatically remove your Caddy reverse proxy block.
Review /etc/caddy/Caddyfile before continuing.

Type 'yes' to continue: 
EOF

    read -r response
    if [[ "$response" != "yes" ]]; then
        log "Uninstall cancelled."
        exit 1
    fi
}

run_cmd() {
    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY RUN: $*"
        return 0
    fi

    "$@"
}

main() {
    if [[ ${EUID} -ne 0 ]]; then
        error "This script must be run as root (use sudo)."
        exit 1
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force)
                FORCE=1
                ;;
            --dry-run)
                DRY_RUN=1
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
        shift
    done

    confirm

    log "Stopping GoobyDesk service..."
    if systemctl list-unit-files --type=service 2>/dev/null | awk '{print $1}' | grep -Fxq "$SERVICE_NAME"; then
        run_cmd systemctl stop "$SERVICE_NAME" || true
        run_cmd systemctl disable "$SERVICE_NAME" || true
        run_cmd rm -f "/etc/systemd/system/$SERVICE_NAME"
        run_cmd systemctl daemon-reload
        run_cmd systemctl reset-failed "$SERVICE_NAME" || true
        log "Service removed."
    else
        warn "Service '$SERVICE_NAME' is not installed; skipping service removal."
    fi

    log "Removing application files..."
    if [[ -d "$TARGET_DIR" ]]; then
        run_cmd rm -rf "$TARGET_DIR"
        log "Removed $TARGET_DIR"
    else
        warn "Directory '$TARGET_DIR' does not exist; skipping removal."
    fi

    log "Removing log files..."
    for log_path in "$LOGFILE" "/var/log/caddy/access.log" "/var/log/caddy/error.log"; do
        if [[ -e "$log_path" ]]; then
            run_cmd rm -f "$log_path"
            log "Removed $log_path"
        fi
    done

    if [[ -f /etc/caddy/Caddyfile ]]; then
        warn "Caddyfile was not changed automatically."
        warn "Review /etc/caddy/Caddyfile and remove the GoobyDesk site block containing 'reverse_proxy 127.0.0.1:8000'."
    fi

    printf '\n%bUninstall complete.%b\n' "$GREEN" "$NC"
    log "If this machine still runs other services, check the Caddyfile and systemd unit list before reusing the host."
}

main "$@"
