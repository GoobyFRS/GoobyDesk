#!/usr/bin/env python3
import json
import logging
from functools import wraps
from flask import Blueprint, render_template, session, Response
from local_handlers.local_config_loader import load_core_config

core_yaml_config = load_core_config()
HR_FILE = core_yaml_config["core"]["hr_file"]

hr_module_bp = Blueprint('hr_module', __name__, url_prefix='/hr')

# Helpers
def technician_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Session-based auth check
        if not session.get("technician"):
            # Unauthorized access attempt
            return render_template("errors/403.html"), 403
        # Authorized technician → proceed to the route
        return func(*args, **kwargs)
    return wrapper

def load_hr_file():
    try:
        with open(HR_FILE, "r") as hr_file:
            return json.load(hr_file)
    except FileNotFoundError:
        logging.critical("Ticket JSON Database file could not be located.")
        exit(1)
        return [] # represents an empty list

# Dashboard Route
@hr_module_bp.route("/", methods=["GET"])
@technician_required
def hr_dashboard():
    # Render the HR dashboard with a list of employees
    try:
        with open(HR_FILE, "r") as hr_file:
            employees = json.load(hr_file)
    except FileNotFoundError:
        logging.critical("Employee JSON Database file could not be located.")
        exit(1)
        return []  # represents an empty list
    return render_template("under_construction.html")
    #return render_template("hr/hr_dashboard.html", employees=employees, loggedInTech=session["technician"])

# Create New Employee Route

# View Employee Details Route

# Edit Employee Details Route

# Export Employee Data Route
