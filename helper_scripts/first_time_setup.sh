#!/bin/bash

# GoobyDesk First Time Setup Script
# This script automates the basic installation and configuration of GoobyDesk

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TARGET_DIR=${TARGET_DIR:-/var/www/GoobyDesk}
# Preferred runtime user: SUDO_USER when run via sudo, else default to 'caddy'
DEFAULT_RUNTIME_USER=caddy
RUNTIME_USER=${SUDO_USER:-${RUNTIME_USER:-$DEFAULT_RUNTIME_USER}}
LOGFILE=/var/log/goobydesk.log

echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}===== GoobyDesk First-Time Setup Script =====${NC}"
echo -e "${GREEN}=============================================${NC}"

echo "Timestamp: ${TIMESTAMP}"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Check for required commands
for cmd in git python3 pip systemctl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: Required command '$cmd' not found"
        exit 1
    fi
done

# Navigate to /var/www/
echo "Ensuring target parent directory exists: /var/www"
mkdir -p /var/www
cd /var/www/ || { echo "ERROR: Failed to navigate to /var/www/"; exit 1; }

# Clone repository
echo "Cloning GoobyDesk repository..."
if [ -d "$TARGET_DIR" ]; then
    echo "WARNING: $TARGET_DIR already exists. Skipping clone."
else
    git clone --depth 1 https://github.com/GoobyFRS/GoobyDesk.git "$TARGET_DIR" || { echo "ERROR: Failed to clone repository"; exit 1; }
fi

cd "$TARGET_DIR" || { echo "ERROR: Failed to navigate to $TARGET_DIR"; exit 1; }

# Set ownership
echo "Setting directory ownership to ${RUNTIME_USER} (if user exists)"
if id -u "$RUNTIME_USER" >/dev/null 2>&1; then
    chown -R "$RUNTIME_USER" "$TARGET_DIR" || { echo "ERROR: Failed to set ownership"; exit 1; }
else
    echo "WARNING: user '$RUNTIME_USER' not found; skipping chown"
fi

# Create data directory
echo "Creating prod_data directory..."
mkdir -p "$TARGET_DIR/prod_data" || { echo "ERROR: Failed to create prod_data directory"; exit 1; }

# Copy configuration files
echo "Copying configuration files from examples (no overwrite)..."
# Prefer files under example_data when present
if [ -d example_data ]; then
    cp -n example_data/example_dotenv .env || true
    cp -n example_data/seed_employee.json prod_data/employee_auth.json || true
    cp -n example_data/example_hr_file.json prod_data/hr_file.json || true
    cp -n example_data/example_tickets.json prod_data/tickets.json || true
    cp -n example_data/template_configuration.yml prod_data/configuration.yml || true
else
    # fallback to root examples (older layout)
    cp -n example_dotenv .env || true
    cp -n seed_employee.json prod_data/employee_auth.json || true
    cp -n example_hr_file.json prod_data/hr_file.json || true
    cp -n example_tickets.json prod_data/tickets.json || true
    cp -n template_configuration.yml prod_data/configuration.yml || true
fi

# Verify at least one config exists
if [ ! -f .env ]; then
    echo "WARNING: .env not created; please create $TARGET_DIR/.env from example_dotenv"
fi

# Create log file
echo "Creating log file..."
touch "$LOGFILE" || { echo "ERROR: Failed to create log file $LOGFILE"; exit 1; }
if id -u "$RUNTIME_USER" >/dev/null 2>&1; then
    chown "$RUNTIME_USER" "$LOGFILE" || { echo "ERROR: Failed to set log file ownership"; exit 1; }
fi

# Create Python virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv || { echo "ERROR: Failed to create virtual environment"; exit 1; }

echo "Installing Python dependencies into venv..."
"$TARGET_DIR/venv/bin/pip" install -r requirements.txt || { echo "ERROR: Failed to install requirements"; exit 1; }

# Create systemd service
[ -n "$TARGET_DIR" ] || { echo "ERROR: TARGET_DIR not set"; exit 1; }

echo "Creating systemd service..."
tee /etc/systemd/system/goobydesk.service > /dev/null <<EOF
[Unit]
Description=Gunicorn Instance serving GoobyDesk
After=network.target

[Service]
User=${RUNTIME_USER}
Group=www-data
WorkingDirectory=${TARGET_DIR}
Environment="PATH=${TARGET_DIR}/venv/bin"
ExecStart=${TARGET_DIR}/venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app

[Install]
WantedBy=multi-user.target
EOF

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create systemd service file"
    exit 1
fi

echo "Reloading systemd and enabling service..."
systemctl daemon-reload || { echo "ERROR: Failed to reload systemd daemon"; exit 1; }
systemctl enable goobydesk.service || { echo "ERROR: Failed to enable service"; exit 1; }

echo
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}=== GoobyDesk First-Time Install Complete ===${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo "GoobyDesk will be accessible on http://127.0.0.1:8000"
echo ""
echo "Next steps:"
echo "1. Review and edit configuration files in ${TARGET_DIR}/prod_data/"
echo "2. Edit .env file if needed. I like to use nano."
echo "3. Start the service: sudo systemctl start goobydesk.service"
echo "4. Check status: sudo systemctl status goobydesk.service"
echo "5. View logs: sudo journalctl -u goobydesk.service -f"
echo "7. Tail logfile: tail -n 25 ${LOGFILE}"
echo ""
echo -e "${GREEN}=============================================${NC}"