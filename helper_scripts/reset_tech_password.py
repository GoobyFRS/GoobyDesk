#!/usr/bin/env python3
# Reset a technicians password using the legacy authentication method.
import json
import sys
import getpass
import local_config_loader

def load_employees():
    core_yaml_config = local_config_loader.load_core_config()
    EMPLOYEE_FILE = core_yaml_config["employee_file"]
    try:
        with open(EMPLOYEE_FILE, "r") as f:
            return json.load(f), EMPLOYEE_FILE
    except FileNotFoundError:
        print(f"ERROR: Employee JSON Database not found: {EMPLOYEE_FILE}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"ERROR: Employee JSON Database is not valid JSON")
        sys.exit(1)

def save_employees(employees, employee_file):
    with open(employee_file, "w") as f:
        json.dump(employees, f, indent=4)

def reset_password(username, new_password):
    employees, employee_file = load_employees()
    
    user_found = False
    for employee in employees:
        if employee.get("tech_username") == username:
            user_found = True
            
            # Remove password_hash if it exists
            if "password_hash" in employee:
                del employee["password_hash"]
            
            # Set legacy tech_authcode
            employee["tech_authcode"] = new_password
            
            print(f"✓ Password reset for user: {username}")
            print(f"  - Removed password_hash")
            print(f"  - Set tech_authcode (will auto-migrate on next login)")
            break
    
    if not user_found:
        print(f"ERROR: User '{username}' not found in employee database")
        sys.exit(1)
    
    save_employees(employees, employee_file)
    print(f"✓ Changes saved to {employee_file}")
    print("\nThe user can now log in with the new password, and it will")
    print("automatically be migrated to a secure password_hash.")

def main():
    print("=" * 60)
    print("GoobyDesk Technician Password Reset Tool")
    print("=" * 60)
    print()
    
    # Get username
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter technician username: ").strip()
    
    if not username:
        print("ERROR: Username cannot be empty")
        sys.exit(1)
    
    # Get new password
    print()
    new_password = getpass.getpass("Enter new password: ")
    confirm_password = getpass.getpass("Confirm new password: ")
    
    if new_password != confirm_password:
        print("ERROR: Passwords do not match")
        sys.exit(1)
    
    if len(new_password) < 8:
        print("WARNING: Password is less than 8 characters")
        confirm = input("Continue anyway? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Password reset cancelled")
            sys.exit(0)
    
    print()
    print(f"Resetting password for: {username}")
    confirm = input("Are you sure? (yes/no): ").strip().lower()
    
    if confirm != "yes":
        print("Password reset cancelled")
        sys.exit(0)
    
    print()
    reset_password(username, new_password)

if __name__ == "__main__":
    main()