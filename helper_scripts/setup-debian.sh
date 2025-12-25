#!/bin/bash
# GoobyDesk Production Setup Script for Debian 12 / Ubuntu 24.04 LTS 
# This script automates the deployment process for VPS environments

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
APP_DIR="/var/www/GoobyDesk"
REPO_URL="https://github.com/GoobyFRS/GoobyDesk.git"
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

# Check system compatibility
check_system() {
    print_header "Checking System Compatibility"
    
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        print_info "Detected: $NAME $VERSION"
        
        if [[ "$ID" != "debian" && "$ID" != "ubuntu" ]]; then
            print_warning "This script is designed for Debian 12 or Ubuntu 24"
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_warning "Cannot detect OS version"
    fi
    
    print_success "System check complete"
}

# Check and install dependencies
check_dependencies() {
    print_header "Checking Dependencies"
    
    local deps=("git" "python3" "python3-pip" "python3-venv")
    local missing=()
    
    for dep in "${deps[@]}"; do
        if ! dpkg -l | grep -q "^ii  $dep "; then
            missing+=("$dep")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        print_warning "Missing packages: ${missing[*]}"
        read -p "Install missing packages? (Y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            print_info "Updating package list..."
            sudo apt update
            print_info "Installing packages: ${missing[*]}"
            sudo apt install -y "${missing[@]}"
            print_success "Dependencies installed"
        else
            print_error "Cannot proceed without required packages"
            exit 1
        fi
    else
        print_success "All dependencies satisfied"
    fi
}

# Setup directory structure and clone repository
setup_directories() {
    print_header "Setting Up Directory Structure"
    
    if [ -d "$APP_DIR" ] && [ "$(ls -A $APP_DIR)" ]; then
        print_warning "Directory $APP_DIR already exists and is not empty"
        read -p "Continue and potentially overwrite files? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        print_info "Creating directory: $APP_DIR"
        sudo mkdir -p "$APP_DIR"
    fi
    
    # Check if caddy user exists
    if id "caddy" &>/dev/null; then
        print_info "Setting ownership to caddy user"
        sudo chown -R caddy:caddy "$APP_DIR"
    else
        print_warning "Caddy user not found, using current user: $USER"
        sudo chown -R "$USER:$USER" "$APP_DIR"
    fi
    
    print_success "Directory structure ready"
}

# Clone repository directly into APP_DIR
clone_repository() {
    print_header "Cloning Repository"
    
    cd "$APP_DIR"
    
    # Check if this looks like a git repository already
    if [ -d ".git" ]; then
        print_warning "Git repository already exists in $APP_DIR"
        read -p "Pull latest changes? (Y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            git pull
            print_success "Repository updated"
        fi
    else
        print_info "Cloning from $REPO_URL directly into $APP_DIR"
        # Clone into a temp directory first, then move contents
        git clone "$REPO_URL" /tmp/goobydesk_temp
        # Move all files including hidden ones from temp to APP_DIR
        shopt -s dotglob
        sudo mv /tmp/goobydesk_temp/* "$APP_DIR/"
        sudo rmdir /tmp/goobydesk_temp
        
        # Fix ownership after moving files
        if id "caddy" &>/dev/null; then
            sudo chown -R caddy:caddy "$APP_DIR"
        else
            sudo chown -R "$USER:$USER" "$APP_DIR"
        fi
        
        print_success "Repository cloned"
    fi
}

# Setup configuration files
setup_config_files() {
    print_header "Setting Up Configuration Files"
    
    cd "$APP_DIR"
    
    local files=(
        "example_dotenv:.env"
        "example_employee.json:employee.json"
        "example_tickets.json:tickets.json"
        "template_configuration.yml:core_configuration.yml"
    )
    
    for file_pair in "${files[@]}"; do
        IFS=':' read -r source dest <<< "$file_pair"
        
        if [ -f "$dest" ]; then
            print_warning "$dest already exists, skipping..."
        elif [ -f "$source" ]; then
            cp "$source" "$dest"
            print_success "Created $dest"
        else
            print_error "Source file $source not found"
        fi
    done
    
    # Create log file
    if [ ! -f "$LOG_FILE" ]; then
        print_info "Creating log file: $LOG_FILE"
        sudo touch "$LOG_FILE"
        sudo chown "$USER:$USER" "$LOG_FILE"
        print_success "Log file created"
    else
        print_warning "Log file already exists"
    fi
}

# Setup Python virtual environment
setup_python_env() {
    print_header "Setting Up Python Environment"
    
    cd "$APP_DIR"
    
    if [ -d "venv" ]; then
        print_warning "Virtual environment already exists"
        read -p "Recreate virtual environment? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf venv
            python3 -m venv venv
            print_success "Virtual environment recreated"
        fi
    else
        print_info "Creating virtual environment"
        python3 -m venv venv
        print_success "Virtual environment created"
    fi
    
    if [ -f "requirements.txt" ]; then
        print_info "Installing Python dependencies (this may take a moment)..."
        source venv/bin/activate
        pip install --upgrade pip
        pip install -r requirements.txt
        deactivate
        print_success "Dependencies installed"
    else
        print_error "requirements.txt not found"
        exit 1
    fi
}

# Prompt for manual configuration
prompt_manual_config() {
    print_header "Manual Configuration Required"
    
    echo -e "${YELLOW}${BOLD}BEFORE CONTINUING, YOU MUST:${NC}\n"
    echo "1. Edit .env file with correct variables"
    echo "2. Update employee.json with desired login credentials"
    echo "3. Verify content of core_configuration.yml file"
    echo -e "\n${CYAN}Configuration files location: $APP_DIR${NC}\n"
    
    read -p "Press Enter when configuration is complete..."
    echo
}

# Test application
test_application() {
    print_header "Testing Application"
    
    cd "$APP_DIR"
    
    read -p "Run Flask application test? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        print_info "Starting Flask application..."
        print_warning "Check for errors, then press CTRL+C to continue"
        echo
        source venv/bin/activate
        python3 ./app.py || true
        deactivate
        echo
        print_success "Application test completed"
    fi
}

# Test Gunicorn
test_gunicorn() {
    print_header "Testing Gunicorn"
    
    cd "$APP_DIR"
    
    read -p "Run Gunicorn test? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        print_info "Starting Gunicorn on 127.0.0.1:8000..."
        print_warning "Press CTRL+C to continue when ready"
        echo
        source venv/bin/activate
        gunicorn --bind 127.0.0.1:8000 app:app || true
        deactivate
        echo
        print_success "Gunicorn test completed"
    fi
}

# Setup systemd service
setup_systemd_service() {
    print_header "Setting Up Systemd Service"
    
    local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
    
    print_info "Creating systemd service file"
    
    sudo tee "$service_file" > /dev/null << EOF
[Unit]
Description=Gunicorn Instance serving GoobyDesk
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app

[Install]
WantedBy=multi-user.target
EOF
    
    print_success "Service file created"
    
    print_info "Reloading systemd daemon"
    sudo systemctl daemon-reload
    
    print_info "Enabling ${SERVICE_NAME} service"
    sudo systemctl enable "${SERVICE_NAME}.service"
    
    print_success "Systemd service configured"
    
    echo
    read -p "Start the service now? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        sudo systemctl start "${SERVICE_NAME}.service"
        echo
        sudo systemctl status "${SERVICE_NAME}.service" --no-pager || true
        echo
        print_success "Service started"
    fi
}

# Display final instructions
show_completion() {
    print_header "Setup Complete!"
    
    echo -e "${GREEN}${BOLD}GoobyDesk has been successfully set up!${NC}\n"
    echo "Useful commands:"
    echo "  • Check service status:    sudo systemctl status $SERVICE_NAME"
    echo "  • Start service:           sudo systemctl start $SERVICE_NAME"
    echo "  • Stop service:            sudo systemctl stop $SERVICE_NAME"
    echo "  • Restart service:         sudo systemctl restart $SERVICE_NAME"
    echo "  • View logs:               sudo journalctl -u $SERVICE_NAME -f"
    echo "  • View application logs:   tail -f $LOG_FILE"
    echo
    echo "Next steps:"
    echo "  1. Configure your reverse proxy (Caddy/Nginx) to point to 127.0.0.1:8000"
    echo "  2. Set up SSL certificates for your domain"
    echo "  3. Configure firewall rules if needed"
    echo
    echo -e "${CYAN}Application location: $APP_DIR${NC}"
    echo
}

# Main execution
main() {
    echo -e "${BOLD}${CYAN}"
    echo "╔════════════════════════════════════════╗"
    echo "║   GoobyDesk Production Setup Script   ║"
    echo "║     Debian 12 / Ubuntu 24 LTS          ║"
    echo "╚════════════════════════════════════════╝"
    echo -e "${NC}"
    
    check_root
    check_system
    check_dependencies
    setup_directories
    clone_repository
    setup_config_files
    setup_python_env
    prompt_manual_config
    test_application
    test_gunicorn
    setup_systemd_service
    show_completion
}

# Run main function
main "$@"