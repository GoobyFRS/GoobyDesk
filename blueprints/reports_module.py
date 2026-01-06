#!/usr/bin/env python3
from flask import Blueprint, render_template, session, Response
import io, csv, logging
from datetime import datetime, timedelta
from local_config_loader import load_core_config

core_yaml_config = load_core_config()
LOG_LEVEL = core_yaml_config["logging"]["level"]
LOG_FILE = core_yaml_config["logging"]["file"]

logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
""" Above is the default logging configuration.
Debug - Detailed information
Info - Successes
Warning - Unexpected events
Error - Function failures
Critical - Serious application failures
"""

reports_module_bp = Blueprint('reports', __name__, url_prefix='/reports')

# Importing from APP to avoid circular imports. There might be a better way for this.
def get_app_functions():
    from app import load_tickets, technician_required
    return load_tickets, technician_required

@reports_module_bp.route("/", endpoint='reports_home')
def reports_home():
    from app import load_tickets, BUILDID
    
    if not session.get("technician"):
        return render_template("403.html"), 403
    
    tickets = load_tickets()
    now = datetime.now()
    total_tickets = len(tickets)
    
    status_counts = {
        "Open": 0,
        "In-Progress": 0,
        "Closed": 0,
    }
    
    time_buckets = {
        "last_60_days": 0,
        "last_30_days": 0,
        "last_14_days": 0,
        "last_7_days": 0,
    }
    
    for ticket in tickets:
        status = ticket.get("ticket_status")
        if status in status_counts:
            status_counts[status] += 1
        
        try:
            submitted_at = datetime.strptime(
                ticket["submission_date"], "%Y-%m-%d %H:%M:%S"
            )
            age = now - submitted_at
            
            if age <= timedelta(days=60):
                time_buckets["last_60_days"] += 1
            if age <= timedelta(days=30):
                time_buckets["last_30_days"] += 1
            if age <= timedelta(days=14):
                time_buckets["last_14_days"] += 1
            if age <= timedelta(days=7):
                time_buckets["last_7_days"] += 1
        
        except (KeyError, ValueError):
            logging.warning("REPORTING - Invalid submission_date on ticket")
    
    return render_template("reports_home.html",
        total_tickets=total_tickets,
        open_tickets=status_counts["Open"],
        in_progress_tickets=status_counts["In-Progress"],
        closed_tickets=status_counts["Closed"],
        last_60_days=time_buckets["last_60_days"],
        last_30_days=time_buckets["last_30_days"],
        last_14_days=time_buckets["last_14_days"],
        last_7_days=time_buckets["last_7_days"],
        loggedInTech=session["technician"], 
        BUILDID=BUILDID)

@reports_module_bp.route("/export/csv", endpoint='export_tickets_csv')
def export_tickets_csv():
    from app import load_tickets
    
    if not session.get("technician"):
        return render_template("403.html"), 403
    
    tickets = load_tickets()
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        "Ticket Number",
        "Subject",
        "Status",
        "Submission Date",
        "Closed By",
        "Closure Date"
    ])
    
    for ticket in tickets:
        writer.writerow([
            ticket.get("ticket_number", ""),
            ticket.get("ticket_subject", ""),
            ticket.get("ticket_status", ""),
            ticket.get("submission_date", ""),
            ticket.get("closed_by", ""),
            ticket.get("closure_date", "")
        ])
    
    output.seek(0)
    return Response(
        output, 
        mimetype="text/csv", 
        headers={"Content-Disposition": "attachment; filename=goobydesk_tickets_report_basic.csv"}
    )