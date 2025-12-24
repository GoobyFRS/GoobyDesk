#!/bin/bash

# GoobyDesk Basic Version Upgrade Script
# This script safely upgrades GoobyDesk to the latest version

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
APP_DIR="/var/www/GoobyDesk/GoobyDesk"
SERVICE_NAME="goobydesk"
LOG_FILE="/var/log/goobydesk.log"

# Helper functions
print_header() {
    echo -e "\n${BLUE}${BOLD}========================================${NC}"
    echo -e "${BLUE}${BOLD}$1${NC}"
    echo -e "${BLUE}${BOLD}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# Check if running as root
check_root() {
    if [ "$EUID" -eq 0 ]; then
        print_error "Please do not run this script as root. Use a regular user with sudo privileges."
        exit 1
    fi
}

# Check if directory exists
check_directory() {
    print_header "Checking Installation"
    
    if [ ! -d "$APP_DIR" ]; then
        print_error "GoobyDesk directory not found at $APP_DIR"
        print_info "Please run the setup script first"
        exit 1
    fi
    
    if [ ! -d "$APP_DIR/venv" ]; then
        print_error "Virtual environment not found at $APP_DIR/venv"
        print_info "Please run the setup script first"
        exit 1
    fi
    
    print_success "Installation found"
}

# Stop the service
stop_service() {
    print_header "Stopping Service"
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_info "Stopping $SERVICE_NAME service..."
        sudo systemctl stop "$SERVICE_NAME.service"
        
        # Wait a moment for service to fully stop
        sleep 2
        
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            print_error "Failed to stop service"
            exit 1
        else
            print_success "Service stopped"
        fi
    else
        print_warning "Service is not running"
    fi
}

# Pull latest changes
update_code() {
    print_header "Updating Code"
    
    cd "$APP_DIR"
    
    print_info "Fetching latest changes from origin/main..."
    
    # Check if there are uncommitted changes
    if ! git diff-index --quiet HEAD --; then
        print_warning "Uncommitted changes detected"
        read -p "Stash changes and continue? (Y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            git stash
            print_info "Changes stashed"
        else
            print_error "Cannot proceed with uncommitted changes"
            exit 1
        fi
    fi
    
    # Pull latest changes
    if sudo git pull origin main; then
        print_success "Code updated successfully"
    else
        print_error "Failed to pull latest changes"
        exit 1
    fi
}

# Update dependencies
update_dependencies() {
    print_header "Updating Dependencies"
    
    cd "$APP_DIR"
    
    print_info "Activating virtual environment..."
    source venv/bin/activate
    
    print_info "Upgrading pip..."
    pip install --upgrade pip --quiet
    
    print_info "Installing/updating requirements..."
    if pip install -r requirements.txt; then
        print_success "Dependencies updated"
    else
        print_error "Failed to install dependencies"
        deactivate
        exit 1
    fi
    
    deactivate
    print_info "Virtual environment deactivated"
}

# Start the service
start_service() {
    print_header "Starting Service"
    
    print_info "Starting $SERVICE_NAME service..."
    sudo systemctl start "$SERVICE_NAME.service"
    
    # Wait a moment for service to start
    sleep 3
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Service started successfully"
    else
        print_error "Service failed to start"
        print_warning "Check the status output below for details"
    fi
}

# Show service status
show_status() {
    print_header "Service Status"
    
    sudo systemctl status "$SERVICE_NAME.service" --no-pager || true
    echo
}

# Show recent logs
show_logs() {
    print_header "Recent Application Logs"
    
    if [ -f "$LOG_FILE" ]; then
        tail -n 25 "$LOG_FILE"
    else
        print_warning "Log file not found at $LOG_FILE"
    fi
    
    echo
}

# Show completion message
show_completion() {
    print_header "Upgrade Complete!"
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}${BOLD}✓ GoobyDesk has been successfully upgraded and is running${NC}\n"
    else
        echo -e "${RED}${BOLD}✗ Upgrade completed but service is not running${NC}"
        echo -e "${YELLOW}Please check the logs and status above for errors${NC}\n"
    fi
    
    echo "Useful commands:"
    echo "  • Check service status:    sudo systemctl status $SERVICE_NAME"
    echo "  • View live logs:          sudo journalctl -u $SERVICE_NAME -f"
    echo "  • View application logs:   tail -f $LOG_FILE"
    echo "  • Restart service:         sudo systemctl restart $SERVICE_NAME"
    echo
}

# Backup configuration (optional but recommended)
backup_config() {
    print_header "Backup Check"
    
    read -p "Create backup of configuration files? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        local backup_dir="$APP_DIR/backups"
        local timestamp=$(date +%Y%m%d_%H%M%S)
        
        mkdir -p "$backup_dir"
        
        local files=(".env" "employee.json" "tickets.json" "core_configuration.yml")
        
        for file in "${files[@]}"; do
            if [ -f "$APP_DIR/$file" ]; then
                cp "$APP_DIR/$file" "$backup_dir/${file}.${timestamp}"
                print_info "Backed up $file"
            fi
        done
        
        print_success "Configuration backed up to $backup_dir"
    else
        print_warning "Skipping backup"
    fi
}

# Main execution
main() {
    echo -e "${BOLD}${CYAN}"
    echo "╔════════════════════════════════════════╗"
    echo "║   GoobyDesk Version Upgrade Script    ║"
    echo "╚════════════════════════════════════════╝"
    echo -e "${NC}"
    
    check_root
    check_directory
    backup_config
    stop_service
    update_code
    update_dependencies
    start_service
    show_status
    show_logs
    show_completion
}

# Trap errors and ensure service is started
cleanup() {
    if [ $? -ne 0 ]; then
        print_error "An error occurred during upgrade"
        print_info "Attempting to start service..."
        sudo systemctl start "$SERVICE_NAME.service" 2>/dev/null || true
    fi
}

trap cleanup EXIT

# Run main function
main "$@"