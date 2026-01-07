#!/usr/bin/env python3
from flask import Blueprint, render_template, session, Response
import io
import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from local_config_loader import load_core_config
from decorators import technician_required   # your @technician_required decorator

# --------------------------------------------------
# CONFIG & LOGGING
# --------------------------------------------------
core_yaml_config = load_core_config()

LOG_LEVEL = core_yaml_config["logging"]["level"]
LOG_FILE = core_yaml_config["logging"]["file"]

TICKETS_FILE = core_yaml_config["paths"]["tickets_file"]  # recommended

logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# --------------------------------------------------
# BLUEPRINT
# --------------------------------------------------
changes_module_bp = Blueprint(
    "changes",
    __name__,
    url_prefix="/changes"
)

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def load_tickets():
    """Safely load tickets from disk."""
    try:
        with open(TICKETS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"CHANGES MODULE - Failed to load tickets: {e}")
        return []

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@changes_module_bp.route("/", methods=["GET"])
@technician_required
def changes_home():
    """
    List all OPEN change tickets.
    """
    tickets = load_tickets()

    open_changes = [
        t for t in tickets
        if t.get("ticket_type") == "Change"
        and t.get("ticket_status", "").lower() != "closed"
    ]

    logging.info(
        f"CHANGES MODULE - Loaded {len(open_changes)} open change tickets"
    )

    return render_template(
        "changes_home.html",
        changes=open_changes,
        loggedInTech=session.get("technician"),
    )


@changes_module_bp.route("/export/csv", methods=["GET"])
@technician_required
def export_changes_csv():
    """
    Export open change tickets as CSV.
    """
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