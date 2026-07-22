#!/usr/bin/env python3
import io
import csv
import json
import logging

from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from local_handlers.local_config_loader import load_core_config
import local_handlers.crm_helpers as crm_helpers
import local_handlers.validation_helpers as validation_helpers

core_yaml_config = load_core_config()
CUSTOMERS_FILE = core_yaml_config["core"]["customers_file"]
SERVICE_APPID_FILE = core_yaml_config["core"]["serviceid_appid_file"]

crm_module_bp = Blueprint('crm_module', __name__, url_prefix='/crm')

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

def load_customers_file():
    try:
        with open(CUSTOMERS_FILE, "r") as customer_file:
            return json.load(customer_file)
    except FileNotFoundError:
        logging.critical("Customer JSON Database file could not be located.")
        exit(1)
        return [] # represents an empty list.

def save_customers_file(customers):
    """Write the given customers back to the customer JSON database.
    Args:
        customers (list[dict]): The full set of customer records to persist.
    """
    with open(CUSTOMERS_FILE, "w") as customer_file_write_op:
        json.dump(customers, customer_file_write_op, indent=4)
    logging.debug("The Customer JSON Database file was modified.")

# Dashboard Route
@crm_module_bp.route("/", methods=["GET"])
@technician_required
def crm_dashboard():
    # Render the CRM dashboard with a list of customers
    try:
        with open(CUSTOMERS_FILE, "r") as customers_file:
            customers = json.load(customers_file)
    except FileNotFoundError:
        logging.critical("Customer JSON Database file could not be located.")
        exit(1)
        return []  # represents an empty list.
    total_customers = len(customers)
    active_customers_list = [customer for customer in customers if customer.get("status") == "active"]
    vip_customers = sum(1 for customer in customers if customer.get("vip") is True)
    total_lifetime_value = sum(customer.get("lifetime_value", 0) for customer in customers)
    crm_base_stats = {
        "total_customers": total_customers,
        "active_customers": len(active_customers_list),
        "vip_customers": vip_customers,
        "total_lifetime_value": total_lifetime_value
    }
    #return render_template("under_construction.html")
    return render_template("crm/crm_dashboard.html", customers=active_customers_list, loggedInTech=session["technician"], stats=crm_base_stats)

# Create New Customer Route
@crm_module_bp.route("/submit-new", methods=["GET", "POST"])
@technician_required
def new_customer():
    if request.method == "GET":
        return render_template("crm/submit_new.html")

    first_name = validation_helpers.clean_str(request.form.get("first_name"))
    last_name = validation_helpers.clean_str(request.form.get("last_name"))
    email = validation_helpers.clean_str(request.form.get("email"))

    missing_fields = validation_helpers.require_fields(
        {"first_name": first_name, "last_name": last_name, "email": email},
        ["first_name", "last_name", "email"],
    )
    if missing_fields:
        return render_template(
            "crm/submit_new.html",
            error="First Name, Last Name, and Email are required."
        ), 400

    if not validation_helpers.is_valid_email(email):
        return render_template(
            "crm/submit_new.html",
            error="Please provide a valid email address."
        ), 400

    customers = load_customers_file()
    submission_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_customer_record = crm_helpers.build_customer_record(
        form=request.form,
        customers=customers,
        technician=session["technician"],
        submission_timestamp=submission_timestamp,
    )

    customers.append(new_customer_record)
    save_customers_file(customers)
    logging.info(f"CRM MODULE - Customer {new_customer_record['customer_id']} created by {session['technician']}.")

    return redirect(url_for("crm_module.customer_profile", uuid=new_customer_record["uuid"]))

# View Customer Details Route
@crm_module_bp.route("/profile/<uuid>", methods=["GET"])
@technician_required
def customer_profile(uuid):
    customers = load_customers_file()
    customer = next((c for c in customers if c["uuid"] == uuid), None)
    if not customer:
        return render_template("errors/404.html"), 404
    return render_template("crm/profile.html", customer=customer, loggedInTech=session["technician"])

"""
# Edit Customer Details Route
@crm_module_bp.route("/profile/<uuid>/edit", methods=["POST"])
@technician_required
"""
# Export Customer Data Route