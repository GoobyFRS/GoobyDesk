#!/usr/bin/env python3
[__all__] = ["load_tickets","save_tickets","load_employees","save_employees"]

import local_config_loader
import json
import logging

core_yaml_config = local_config_loader.load_core_config()
TICKETS_FILE = core_yaml_config["tickets_file"]
EMPLOYEE_FILE = core_yaml_config["employee_file"]
LOG_FILE = core_yaml_config["logging"]["file"]
LOG_LEVEL = core_yaml_config["logging"]["level"]

logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        logging.critical("Ticket Database file could not be located.")
        exit(106)
        return [] # represents an empty list.
    
# Writes to the ticket file database. Eventually needs file locking for Linux.
def save_tickets(tickets):
    with open(TICKETS_FILE, "w") as tkt_file_write_op:
        json.dump(tickets, tkt_file_write_op, indent=4)
        logging.debug("The ticket database file was modified.")

# Read/Loads the employee file into memory.
def load_employees():
    try:
        with open(EMPLOYEE_FILE, "r") as tech_file_read_op:
            return json.load(tech_file_read_op)
    except FileNotFoundError:
        logging.debug("Employee Database file could not be located.")
        exit(107)
        return {} # represents an empty dictionary
    
# Helper script for secure password hasing auto-migration.
def save_employees(employees):
    with open(EMPLOYEE_FILE, "w") as emp_file_write_op:
        json.dump(employees, emp_file_write_op, indent=4)
    logging.debug("The employee database file was modified.")