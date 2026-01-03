#!/bin/bash

# GoobyDesk Upgrade Script
# This script performs a backup and upgrade of the GoobyDesk application

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="/var/www/GoobyDesk"
SERVICE_NAME="goobydesk.service"
DATA_DIR="${APP_DIR}/my_data"
LOG_FILE="/var/log/goobydesk.log"
BACKUP_DIR="/var/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="my_data_backup_${TIMESTAMP}.tgz"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}========= GoobyDesk Upgrade Script ==========${NC}"
echo -e "${GREEN}=============================================${NC}"
echo "Timestamp: ${TIMESTAMP}"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run with sudo${NC}"
    exit 1
fi

# Check if app directory exists
if [ ! -d "$APP_DIR" ]; then
    echo -e "${RED}Error: Application directory ${APP_DIR} does not exist${NC}"
    exit 1
fi

# Step 1: Stop service
echo -e "${YELLOW}Step 1/6: Stopping service...${NC}"
systemctl stop "$SERVICE_NAME"
echo -e "${GREEN}  ✓ Service stopped${NC}"
echo ""

# Step 2: Create backup
echo -e "${YELLOW}Step 2/6: Creating backup...${NC}"
BACKUP_TEMP_DIR=$(mktemp -d)
mkdir -p "${BACKUP_TEMP_DIR}/my_data"

if [ -d "$DATA_DIR" ]; then
    cp -r "$DATA_DIR"/* "${BACKUP_TEMP_DIR}/my_data/" 2>/dev/null || true
    echo "  - my_data folder backed up"
else
    echo -e "${YELLOW}  - Warning: my_data directory not found${NC}"
fi

if [ -f "$LOG_FILE" ]; then
    cp "$LOG_FILE" "${BACKUP_TEMP_DIR}/"
    echo "  - goobydesk.log backed up"
else
    echo -e "${YELLOW}  - Warning: log file not found${NC}"
fi

tar -czf "$BACKUP_PATH" -C "$BACKUP_TEMP_DIR" .
rm -rf "$BACKUP_TEMP_DIR"
echo -e "${GREEN}  ✓ Backup created: ${BACKUP_PATH}${NC}"
echo ""

# Step 3: Pull latest code
echo -e "${YELLOW}Step 3/6: Pulling latest code from git...${NC}"
cd "$APP_DIR"
sudo git pull origin main
echo -e "${GREEN}  ✓ Code updated${NC}"
echo ""

# Step 4: Update dependencies
echo -e "${YELLOW}Step 4/6: Updating dependencies...${NC}"
source venv/bin/activate
pip install -r requirements.txt
deactivate
echo -e "${GREEN}  ✓ Dependencies updated${NC}"
echo ""

# Step 5: Start service
echo -e "${YELLOW}Step 5/6: Starting service...${NC}"
systemctl start "$SERVICE_NAME"
echo -e "${GREEN}  ✓ Service started${NC}"
echo ""

# Step 6: Wait and check status
echo -e "${YELLOW}Step 6: Waiting 10 seconds for service to fully initialize...${NC}"
sleep 10
echo ""

echo -e "${YELLOW}Service Status:${NC}"
systemctl status "$SERVICE_NAME" --no-pager || true
echo ""

echo -e "${YELLOW}Recent Log Entries (last 25 lines):${NC}"
tail -n 25 "$LOG_FILE"
echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}============== Upgrade Complete =============${NC}"
echo -e "Backup location: ${GREEN}${BACKUP_PATH}${NC}"
echo -e "${GREEN}=============================================${NC}"
