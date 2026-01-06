#!/bin/bash

# GoobyDesk First Time Setup Script
# This script automates the basic installation and configuration of GoobyDesk

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}===== GoobyDesk First-Time Setup Script =====${NC}"
echo -e "${GREEN}=============================================${NC}"

echo "Timestamp: ${TIMESTAMP}"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run with sudo${NC}"
    exit 1
fi

# Check for required commands
for cmd in git python3 pip sudo; do
    if ! command -v $cmd &> /dev/null; then
        echo "ERROR: Required command '$cmd' not found"
        exit 1
    fi
done

# Navigate to /var/www/
echo "Navigating to /var/www/..."
cd /var/www/ || { echo "ERROR: Failed to navigate to /var/www/"; exit 1; }

# Clone repository
echo "Cloning GoobyDesk repository..."
if [ -d "GoobyDesk" ]; then
    echo "WARNING: GoobyDesk directory already exists. Skipping clone."
else
    git clone https://github.com/GoobyFRS/GoobyDesk.git || { echo "ERROR: Failed to clone repository"; exit 1; }
fi

cd GoobyDesk || { echo "ERROR: Failed to navigate to GoobyDesk directory"; exit 1; }

# Set ownership
echo "Setting directory ownership to caddy..."
sudo chown -R caddy /var/www/GoobyDesk || { echo "ERROR: Failed to set ownership"; exit 1; }

# Create data directory
echo "Creating my_data directory..."
sudo mkdir -p /var/www/GoobyDesk/my_data || { echo "ERROR: Failed to create my_data directory"; exit 1; }

# Copy configuration files
echo "Copying configuration files..."
cp example_dotenv .env || { echo "ERROR: Failed to copy .env file"; exit 1; }
cp example_employee.json my_data/employee.json || { echo "ERROR: Failed to copy employee.json"; exit 1; }
cp example_tickets.json my_data/tickets.json || { echo "ERROR: Failed to copy tickets.json"; exit 1; }
cp template_configuration.yml my_data/core_configuration.yml || { echo "ERROR: Failed to copy core_configuration.yml"; exit 1; }

# Create log file
echo "Creating log file..."
sudo touch /var/log/goobydesk.log || { echo "ERROR: Failed to create log file"; exit 1; }
sudo chown caddy /var/log/goobydesk.log || { echo "ERROR: Failed to set log file ownership"; exit 1; }

# Create Python virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv || { echo "ERROR: Failed to create virtual environment"; exit 1; }

# Activate virtual environment and install dependencies
echo "Installing Python dependencies..."
source venv/bin/activate || { echo "ERROR: Failed to activate virtual environment"; exit 1; }
pip install -r requirements.txt || { echo "ERROR: Failed to install requirements"; deactivate; exit 1; }
deactivate

# Create systemd service
echo "Creating systemd service..."
sudo tee /etc/systemd/system/goobydesk.service > /dev/null <<EOF
[Unit]
Description=Gunicorn Instance serving GoobyDesk
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=/var/www/GoobyDesk
Environment="PATH=/var/www/GoobyDesk/venv/bin"
ExecStart=/var/www/GoobyDesk/venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app

[Install]
WantedBy=multi-user.target
EOF

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create systemd service file"
    exit 1
fi

# Reload systemd and enable service
echo "Enabling GoobyDesk service..."
sudo systemctl daemon-reload || { echo "ERROR: Failed to reload systemd daemon"; exit 1; }
sudo systemctl enable goobydesk.service || { echo "ERROR: Failed to enable service"; exit 1; }

echo
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}=== GoobyDesk First-Time Install Complete ===${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo "GoobyDesk will be accessible on http://127.0.0.1:8000"
echo ""
echo "Next steps:"
echo "1. Review and edit configuration files in /var/www/GoobyDesk/my_data/"
echo "2. Edit .env file if needed. I like to use nano."
echo "3. Start the service: sudo systemctl start goobydesk.service"
echo "4. Check status: sudo systemctl status goobydesk.service"
echo "5. View logs: sudo journalctl -u goobydesk.service -f"
echo "6. View logs: tail -n 25 /var/log/goobyDesk.log"
echo ""
echo -e "${GREEN}=============================================${NC}"