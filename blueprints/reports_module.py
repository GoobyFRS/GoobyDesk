#!/usr/bin/env python3
from flask import Blueprint, render_template, session, Response
from local_handlers.utils import resolve_preferred_name
from local_handlers.auth_decorators import role_required
import io, csv, logging
from datetime import datetime, timedelta
from local_handlers.local_config_loader import load_core_config
from flask import current_app
from storage.changes_store import ChangesStore
from storage.ticket_store import TicketStore

def _get_config():
    """Return loaded app config or fallback loader."""
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        from local_handlers.local_config_loader import load_core_config
        cfg = load_core_config()
    return cfg

def _get_reports_store():
    """Return a TicketStore for reports using loaded config."""
    cfg = _get_config()
    return TicketStore(cfg["core"]["tickets_file"])


def _get_changes_store():
    """Return a ChangesStore for reports using loaded config."""
    cfg = _get_config()
    return ChangesStore(cfg["core"]["changes_file"])


def _load_changes():
    """Load change records for reports."""
    store = _get_changes_store()
    return [record for record in store.load_all() if isinstance(record, dict)]


def _summarize_changes(changes: list[dict]) -> tuple[int, int, dict[str,int], dict[str,int]]:
    """Summarize change counts by status and risk."""
    total_changes = len(changes)
    active_changes = 0
    status_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}

    for record in changes:
        status = str(record.get("change_status", "Unknown") or "Unknown").strip()
        risk = str(record.get("change_risk", "None") or "None").strip().capitalize()

        status_counts[status] = status_counts.get(status, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

        if status not in {"Completed", "Cancelled", "completed", "cancelled"}:
            active_changes += 1

    for default_status in ["Planned", "Scheduled", "InProgress", "Completed", "Cancelled"]:
        status_counts.setdefault(default_status, 0)

    for default_risk in ["High", "Medium", "Low", "None"]:
        risk_counts.setdefault(default_risk, 0)

    return total_changes, active_changes, status_counts, risk_counts


def _summarize_resolution_times(tickets: list[dict]) -> dict[str, float]:
    """Compute average/min/max resolution hours for closed tickets."""
    resolution_hours = []
    for ticket in tickets:
        if (ticket.get("ticket_status", "") or "").lower() != "closed":
            continue
        try:
            submitted_at = datetime.strptime(ticket["submission_date"], "%Y-%m-%d %H:%M:%S")
            closed_at = datetime.strptime(ticket["closure_date"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            logging.warning("REPORTING - Missing or invalid submission/closure date on ticket")
            continue
        resolution_hours.append((closed_at - submitted_at).total_seconds() / 3600)

    if not resolution_hours:
        return {"total_resolved": 0, "avg_resolution_hours": 0, "min_resolution_hours": 0, "max_resolution_hours": 0}

    return {
        "total_resolved": len(resolution_hours),
        "avg_resolution_hours": sum(resolution_hours) / len(resolution_hours),
        "min_resolution_hours": min(resolution_hours),
        "max_resolution_hours": max(resolution_hours),
    }


def _summarize_source_counts(tickets: list[dict]) -> dict[str, int]:
    """Summarize ticket counts grouped by ticket source channel."""
    source_counts: dict[str, int] = {}
    for ticket in tickets:
        source = str(ticket.get("ticket_source", "") or "unknown").strip() or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
    return source_counts


def _summarize_queue_counts(tickets: list[dict]) -> dict[str, int]:
    """Summarize active (non-closed) ticket counts grouped by request type/queue."""
    queue_counts: dict[str, int] = {}
    for ticket in tickets:
        if (ticket.get("ticket_status", "") or "").lower() == "closed":
            continue
        queue = str(ticket.get("request_type", "") or "unknown").strip() or "unknown"
        queue_counts[queue] = queue_counts.get(queue, 0) + 1
    return queue_counts

reports_module_bp = Blueprint('reports_module', __name__, url_prefix='/reports')

@reports_module_bp.route("/dashboard", methods=["GET"])
@role_required("*")
def reports_home():
    """Render reports dashboard with ticket aggregates."""
    from app import load_tickets
    
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
            submitted_at = datetime.strptime(ticket["submission_date"], "%Y-%m-%d %H:%M:%S")
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

    changes = _load_changes()
    total_changes, active_changes, change_status_counts, change_risk_counts = _summarize_changes(changes)
    resolution_stats = _summarize_resolution_times(tickets)
    source_counts = _summarize_source_counts(tickets)
    queue_counts = _summarize_queue_counts(tickets)

    return render_template("reports/reports_dashboard.html",
        total_tickets=total_tickets,
        open_tickets=status_counts["Open"],
        in_progress_tickets=status_counts["In-Progress"],
        closed_tickets=status_counts["Closed"],
        last_60_days=time_buckets["last_60_days"],
        last_30_days=time_buckets["last_30_days"],
        last_14_days=time_buckets["last_14_days"],
        last_7_days=time_buckets["last_7_days"],
        total_changes=total_changes,
        active_changes=active_changes,
        change_status_counts=change_status_counts,
        change_risk_counts=change_risk_counts,
        resolution_stats=resolution_stats,
        source_counts=source_counts,
        queue_counts=queue_counts,
        loggedInTech=resolve_preferred_name(session.get("technician")))

@reports_module_bp.route("/export/csv", endpoint='export_tickets_csv')
@role_required("*")
def export_tickets_csv():
    """Export basic ticket list as CSV for download."""
    from app import load_tickets
    
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
