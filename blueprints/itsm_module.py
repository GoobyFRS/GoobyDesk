#!/usr/bin/env python3
import logging
import hashlib
import os

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session
from local_handlers.utils import resolve_preferred_name
from local_handlers.auth_decorators import role_required, ROLE_ITSM_TECH

import local_handlers.local_webhook_handler as local_webhook_handler
from flask import current_app
from storage.ticket_store import TicketStore

def _get_config():
    """Return loaded app config or fallback loader."""
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        from local_handlers.local_config_loader import load_core_config
        cfg = load_core_config()
    return cfg

def _get_ticket_store():
    """Return a TicketStore instance from loaded config."""
    cfg = _get_config()
    return TicketStore(cfg["core"]["tickets_file"])

itsm_module_bp = Blueprint('itsm', __name__, url_prefix='/itsm')
logger = logging.getLogger(__name__)

def _apply_ticket_status_update(record: dict, canonical_status: str, logged_in_tech: str) -> dict:
    """Apply a normalized status update and keep close timestamps consistent."""
    record.setdefault("ticket_subject", "No Subject Provided")
    record["ticket_status"] = canonical_status

    if canonical_status == "Closed":
        resolved_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record["closed_by"] = logged_in_tech
        record["closure_date"] = resolved_timestamp
        record["ticket_resolved_timestamp"] = resolved_timestamp
        return record

    record.pop("closed_by", None)
    record["closure_date"] = None
    record["ticket_resolved_timestamp"] = None
    return record

def _pseudonymize_actor(name: str) -> str:
    if not name:
        return "actor_unknown"
    salt = os.getenv("LOG_SALT", "")
    short_hash = hashlib.sha256((str(name) + salt).encode()).hexdigest()[:8]
    return f"actor_{short_hash}"

VALID_QUEUES = ("support", "escalation", "billing")

def _filter_by_queue(tickets: list[dict], queue_name: str) -> list[dict]:
    """Return open tickets belonging to the given queue."""
    return [
        ticket_record
        for ticket_record in tickets
        if (ticket_record.get("ticket_queue", "support") or "support").lower() == queue_name
        and (ticket_record.get("ticket_status", "") or "").lower() != "closed"
    ]

def load_tickets():
    """Read/load the ticket JSON database into memory."""
    store = _get_ticket_store()
    return store.load_all()

def save_tickets(tickets):
    """Write the given tickets back to the ticket JSON database."""
    store = _get_ticket_store()
    store.save_all(tickets)
    logger.debug("ITSM MODULE - The Ticket JSON Database file was modified.")

@itsm_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def dashboard():
    """Render ITSM dashboard with tickets assigned to the current technician."""
    logged_in_tech = resolve_preferred_name(session.get("technician"))
    tickets = load_tickets()
    my_tickets = [
        ticket_record
        for ticket_record in tickets
        if (ticket_record.get("ticket_status", "") or "").lower() != "closed"
        and ticket_record.get("assigned_to") == session.get("technician")
    ]
    return render_template(
        "itsm/dashboard.html",
        tickets=my_tickets,
        loggedInTech=logged_in_tech,
    )

@itsm_module_bp.route("/queue", methods=["GET"])
@itsm_module_bp.route("/queue/support", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def queue_support():
    """Render the Support queue."""
    tickets = load_tickets()
    return render_template(
        "itsm/queue.html",
        tickets=_filter_by_queue(tickets, "support"),
        queue_name="Support",
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )

@itsm_module_bp.route("/queue/escalation", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def queue_escalation():
    """Render the Escalation queue."""
    tickets = load_tickets()
    return render_template(
        "itsm/queue.html",
        tickets=_filter_by_queue(tickets, "escalation"),
        queue_name="Escalation",
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )

@itsm_module_bp.route("/queue/billing", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def queue_billing():
    """Render the Billing queue."""
    tickets = load_tickets()
    return render_template(
        "itsm/queue.html",
        tickets=_filter_by_queue(tickets, "billing"),
        queue_name="Billing",
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )

@itsm_module_bp.route("/ticket/<ticket_number>")
@role_required(ROLE_ITSM_TECH)
def ticket_detail(ticket_number):
    """Show ticket console for a given ticket number."""
    tickets = load_tickets()
    ticket = next(
        (ticket_record for ticket_record in tickets if ticket_record["ticket_number"] == ticket_number),
        None,
    )
    if ticket:
        return render_template("itsm/console.html", ticket=ticket, loggedInTech=resolve_preferred_name(session.get("technician")))
    return render_template("errors/404.html"), 404

@itsm_module_bp.route("/ticket/<ticket_number>/update_status/<ticket_status>", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def update_ticket_status(ticket_number, ticket_status):
    """Update a ticket's status. Called from the Dashboard and Ticket Commander.
    Args:
        ticket_number (str): The ticket number to update.
        ticket_status (str): The new status. Must be one of "Open",
            "In-Progress", or "Closed".
    Returns:
        JSON confirmation on success, or 400/404 on invalid input.
    """
    logger.info("ITSM MODULE - Ticket %s status change requested: %s", ticket_number, ticket_status)

    valid_statuses = ["Open", "In-Progress", "Closed"]
    # Normalize incoming status to a canonical value (case-insensitive match).
    canonical_status = None
    for candidate in valid_statuses:
        if ticket_status.lower() == candidate.lower():
            canonical_status = candidate
            break
    if not canonical_status:
        return render_template("errors/400.html"), 400

    logged_in_tech = resolve_preferred_name(session.get("technician"))
    store = _get_ticket_store()

    def _updater(record: dict):
        return _apply_ticket_status_update(record, canonical_status, logged_in_tech)

    changed = store.update(lambda record: record.get("ticket_number") == ticket_number, _updater)
    if not changed:
        return render_template("errors/404.html"), 404

    # Load updated ticket to get subject for notifications
    tickets = load_tickets()
    ticket = next(
        (ticket_record for ticket_record in tickets if ticket_record.get("ticket_number") == ticket_number),
        None,
    )
    ticket_subject = ticket.get("ticket_subject", "No Subject Provided") if ticket else "No Subject Provided"

    logger.info("ITSM MODULE - Ticket %s status updated to %s by %s", ticket_number, ticket_status, _pseudonymize_actor(logged_in_tech))

    try:
        local_webhook_handler.notify_ticket_event(
            ticket_number=ticket_number,
            ticket_status=canonical_status,
            ticket_subject=ticket_subject,
        )
        logger.info("ITSM MODULE - Ticket %s status update notifications sent successfully.", ticket_number)
    except Exception:
        logger.exception("ITSM MODULE - Failed to send ticket status notifications for %s", ticket_number)

    return jsonify({"message": f"Ticket {ticket_number} updated to {canonical_status}."})

@itsm_module_bp.route("/ticket/<ticket_number>/append_note", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def add_ticket_note(ticket_number):
    """Append a technician note to a ticket.
    Args:
        ticket_number (str): The ticket number to annotate.
    Returns:
        JSON confirmation on success, or an error message on failure.
    """
    note_content = (request.form.get("note_content") or "").strip()
    if not note_content:
        return jsonify({"message": "Note contents cannot be empty."}), 400
    if len(note_content) > 8000:
        return jsonify({"message": "Note too long (max 8000 chars)."}), 400

    store = _get_ticket_store()

    note_record = {
        "author": resolve_preferred_name(session.get("technician")) or "unknown",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": note_content,}

    def _updater(record: dict):
        record.setdefault("ticket_worknotes", [])
        record["ticket_worknotes"].append(note_record)
        return record

    changed = store.update(lambda record: record.get("ticket_number") == ticket_number, _updater)
    if not changed:
        return jsonify({"message": "Ticket not found."}), 404

    logger.info("ITSM MODULE - Note appended to %s by %s.", ticket_number, _pseudonymize_actor(note_record["author"]))
    return jsonify({"message": "Note added successfully.", "note": note_record}), 200


@itsm_module_bp.route("/ticket/<ticket_number>/assign_to_me", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def assign_ticket_to_me(ticket_number):
    """Assign a ticket to the logged-in technician and timestamp acknowledgement.
    Args:
        ticket_number (str): The ticket number to assign.
    Returns:
        JSON confirmation on success, or 404 if the ticket does not exist.
    """
    technician_username = session.get("technician")
    logged_in_tech = resolve_preferred_name(technician_username)
    store = _get_ticket_store()

    def _updater(record: dict):
        record["assigned_to"] = technician_username
        if not record.get("ticket_acknowledged_timestamp"):
            record["ticket_acknowledged_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return record

    changed = store.update(lambda record: record.get("ticket_number") == ticket_number, _updater)
    if not changed:
        return jsonify({"message": "Ticket not found."}), 404

    logger.info("ITSM MODULE - Ticket %s assigned to %s.", ticket_number, _pseudonymize_actor(logged_in_tech))
    return jsonify({"message": f"Ticket {ticket_number} assigned to {logged_in_tech}."})
