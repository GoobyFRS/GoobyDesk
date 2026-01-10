#!/usr/bin/env python3
from flask import Blueprint, render_template, session, Response
import io, csv, json, logging
from functools import wraps
from local_config_loader import load_core_config


# CONFIG & LOGGING
core_yaml_config = load_core_config()
LOG_LEVEL = core_yaml_config["logging"]["level"]
LOG_FILE = core_yaml_config["logging"]["file"]
TICKETS_FILE = core_yaml_config["tickets_file"]

logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",)

# BLUEPRINT
changes_module_bp = Blueprint("changes", __name__, url_prefix="/changes")

# Helpers
def technician_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Session-based auth check
        if not session.get("technician"):
            # Unauthorized access attempt
            return render_template("403.html"), 403
        # Authorized technician → proceed to the route
        return func(*args, **kwargs)
    return wrapper

def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        logging.critical("Ticket JSON Database file could not be located.")
        exit(1)
        return [] # represents an empty list.

# ROUTES
@changes_module_bp.route("/", methods=["GET"])
@technician_required
def changes_home():
    tickets = load_tickets()
    # Filtering out tickets with the Closed Status on the main Dashboard.
    open_changes = [ticket for ticket in tickets if ticket["ticket_type"] == "Change" and ticket["ticket_status"].lower() != "closed"]
    return render_template("under_construction.html")

# Export open change tickets as CSV.
@changes_module_bp.route("/export/csv", methods=["GET"])
@technician_required
def export_changes_csv():
    tickets = load_tickets()

    open_changes = [
        t for t in tickets
        if t.get("ticket_type") == "Change"
        and t.get("ticket_status", "").lower() != "closed"
    ]

    output = io.StringIO()
    writer = csv.writer(output)

    # CSV Header
    writer.writerow([
        "Ticket Number",
        "Subject",
        "Status",
        "Submitted By",
        "Submission Date",
        "Assigned To",
    ])

    for t in open_changes:
        writer.writerow([
            t.get("ticket_number"),
            t.get("ticket_subject"),
            t.get("ticket_status"),
            t.get("submitted_by"),
            t.get("submission_date"),
            t.get("assigned_technician"),
        ])

    output.seek(0)

    logging.info(
        f"CHANGES MODULE - Exported {len(open_changes)} change tickets to CSV"
    )

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=open_changes.csv"
        },
    )
