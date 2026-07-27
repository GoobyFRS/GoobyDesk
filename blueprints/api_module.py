#!/usr/bin/env python3
import json
import logging
import hashlib
import uuid
import os

from datetime import datetime
from flask import Blueprint, request, jsonify

import local_handlers.local_webhook_handler as local_webhook_handler
from flask import current_app
from storage.ticket_store import TicketStore

api_module_bp = Blueprint('api_module', __name__, url_prefix='/api')

def _opaque_id(value: str, prefix: str = "id") -> str:
    """Return a short opaque id for a value (redacts raw data in logs)."""
    if not value:
        return f"{prefix}_unknown"
    salt = os.getenv("LOG_SALT", "")
    short_hash = hashlib.sha256((str(value) + salt).encode()).hexdigest()[:8]
    return f"{prefix}_{short_hash}"

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

# Status Endpoint at /api/status
@api_module_bp.route("/status", methods=["GET"])
def api_status():
    """Return a simple API status payload."""
    return jsonify({
        "is_GoobyDesk": True,
        "installed": True,
        "edition": "community",
        "license_key": None
    }), 200

@api_module_bp.route("/tailscale", methods=["POST"])
def tailscale_webhook():
    """Ingest Tailscale webhook and create a support ticket."""
    try:
        payload = request.json
        if not payload:
            logging.warning("API INGEST - Tailscale webhook sent an empty payload.")
            return jsonify({"error": "Empty payload"}), 400

        # Avoid logging raw webhook payloads; keep full body only in ticket message.
        formatted_ts_webhook_body = json.dumps(payload, indent=4)

        requestor_name = "Tailscale"
        cfg = _get_config()
        requestor_email = cfg.get("email", {}).get("tailscale_notify_email")
        ticket_subject = "Tailscale Notification"
        ticket_message = formatted_ts_webhook_body
        ticket_impact = "Medium"
        ticket_urgency = "Medium"
        request_type = "Change"
        ticket_store = _get_ticket_store()
        ticket_number = ticket_store.next_ticket_number()

        new_ticket = {
            "ticket_number": ticket_number,
            "requestor_name": requestor_name,
            "requestor_email": requestor_email,
            "ticket_subject": ticket_subject,
            "ticket_message": ticket_message,
            "request_type": request_type,
            "ticket_impact": ticket_impact,
            "ticket_urgency": ticket_urgency,
            "ticket_status": "Open",
            "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket_notes": []
        }

        ticket_store.append(new_ticket)
        logging.info(f"Tailscale Notification — {ticket_number} created successfully.")

        try:
            local_webhook_handler.notify_ticket_event(
                ticket_number=ticket_number,
                ticket_status="Open",
                ticket_subject=ticket_subject
                )
            logging.info("API INGEST - Ticket %s created and notifications sent.", ticket_number)
        except Exception as exc:
            logging.error("API INGEST - Failed to send ticket status notifications for %s", ticket_number)
            logging.debug("API INGEST - Notification error details for %s: %s", ticket_number, str(exc))

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as exc:
        cid = uuid.uuid4().hex[:8]
        logging.critical("API INGEST - Tailscale webhook error; correlation_id=%s", cid)
        logging.debug("API INGEST - Tailscale webhook exception %s: %s", cid, str(exc))
        return jsonify({"error": "Internal server error"}), 500

@api_module_bp.route("/uptime-kuma", methods=["POST"])
def uptime_kuma_webhook():
    """Ingest Uptime Kuma webhooks and create tickets for DOWN/PENDING."""
    try:
        if not request.is_json:
            logging.warning("API INGEST -Uptime-Kuma webhook sent invalid content type.")
            return jsonify({"error": "Invalid content type"}), 400
        payload = request.json
        logging.info("API INGEST - Uptime Kuma webhook received; source=%s", _opaque_id(payload.get("monitor", {}).get("name")))

        heartbeat = payload.get("heartbeat", {})
        monitor = payload.get("monitor", {})

        status = heartbeat.get("status")
        monitor_name = monitor.get("name", "Unknown Monitor")
        monitor_url = monitor.get("url", "Unknown URL")
        message = heartbeat.get("msg", payload.get("msg", "No message"))

        status_text = {
            0: "DOWN",
            1: "UP",
            2: "PENDING",
            3: "MAINTENANCE"
        }.get(status, "UNKNOWN")

        if status not in [0, 2]:
            logging.info("API INGEST - Skipping ticket creation for monitor=%s (status=%s)", _opaque_id(monitor_name, "monitor"), status_text)
            return jsonify({"status": "ignored", "reason": f"status {status_text} not tracked"}), 200

        if status == 0:
            ticket_subject = f"Uptime Kuma Alert - {monitor_name} is DOWN"
            ticket_impact = "High"
            ticket_urgency = "High"
            request_type = "Incident"
        elif status == 2:
            ticket_subject = f"Uptime Kuma Alert - {monitor_name} is PENDING"
            ticket_impact = "Medium"
            ticket_urgency = "Medium"
            request_type = "Incident"

        # Keep full payload in ticket body only; do not log it directly.
        ticket_message = json.dumps(payload, indent=4)
        ticket_store = _get_ticket_store()
        ticket_number = ticket_store.next_ticket_number()

        new_ticket = {
            "ticket_number": ticket_number,
            "requestor_name": "Uptime Kuma",
            "requestor_email": "noreply@uptimekuma.example.org",
            "ticket_subject": ticket_subject,
            "ticket_message": ticket_message,
            "request_type": request_type,
            "ticket_impact": ticket_impact,
            "ticket_urgency": ticket_urgency,
            "ticket_status": "Open",
            "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket_notes": []
        }

        ticket_store.append(new_ticket)

        logging.info("API INGEST - Uptime-Kuma Notification %s created (status=%s)", ticket_number, status_text)

        try:
            local_webhook_handler.notify_ticket_event(
                ticket_number=ticket_number,
                ticket_status="Open",
                ticket_subject=ticket_subject
            )
            logging.info("API INGEST - Ticket %s status notifications sent.", ticket_number)
        except Exception as exc:
            logging.error("API INGEST - Failed to send ticket status notifications for %s", ticket_number)
            logging.debug("API INGEST - Notification error details for %s: %s", ticket_number, str(exc))

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as exc:
        cid = uuid.uuid4().hex[:8]
        logging.critical("API INGEST - Uptime Kuma webhook error; correlation_id=%s", cid)
        logging.debug("API INGEST - Uptime Kuma exception %s: %s", cid, str(exc))
        return jsonify({"error": "Internal server error"}), 500
"""
@api_module_bp.route("/goobyddns", methods=["POST"])
def goobyddns_webhook():

new_ticket = {
            "ticket_number": ticket_number,
            "requestor_name": "GoobyDDNS",
            "requestor_email": "noreply@goobyddns.example.org",
            "ticket_subject": ticket_subject,
            "ticket_message": ticket_message,
            "request_type": request_type,
            "ticket_impact": Low,
            "ticket_urgency": Low,
            "ticket_status": "Open",
            "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket_notes": []
        }
"""
@api_module_bp.route("/librenms", methods=["POST"])
def librenms_webhook():
    """Ingest LibreNMS alert-transport webhooks and open a ticket.
    Expects LibreNMS's default JSON alert transport payload. Only
    newly-triggered alerts (state == 1) create a ticket; recoveries
    and acknowledgements are logged and ignored.
    Returns:
        JSON confirmation with the created ticket number on success,
        an "ignored" status for untracked states, or 400/500 on failure.
    """
    try:
        if not request.is_json:
            logging.warning("API INGEST - LibreNMS webhook sent invalid content type.")
            return jsonify({"error": "Invalid content type"}), 400

        payload = request.json
        if not payload:
            logging.warning("API INGEST - LibreNMS webhook sent an empty payload.")
            return jsonify({"error": "Empty payload"}), 400

        logging.info("API INGEST - LibreNMS webhook received; source=%s", _opaque_id(payload.get("hostname")))

        state = payload.get("state")
        hostname = payload.get("hostname", "Unknown Host")
        title = payload.get("title", "LibreNMS Alert")
        severity = str(payload.get("severity", "")).lower()

        if state != 1:
            logging.info("API INGEST - Skipping ticket creation for host=%s (state=%s)", _opaque_id(hostname, "host"), state)
            return jsonify({"status": "ignored", "reason": f"state {state} not tracked"}), 200

        ticket_impact, ticket_urgency = "Medium", "Medium"
        if severity == "critical": 
            ticket_impact, ticket_urgency = "High", "High"
        ticket_subject = f"LibreNMS Alert - {hostname}: {title}"
        # Keep full payload in ticket body only; do not log it directly.
        ticket_message = json.dumps(payload, indent=4)
        ticket_store = _get_ticket_store()
        ticket_number = ticket_store.next_ticket_number()

        new_ticket = {
            "ticket_number": ticket_number,
            "requestor_name": "LibreNMS",
            "requestor_email": _get_config().get("email", {}).get("librenms_notify_email"),
            "ticket_subject": ticket_subject,
            "ticket_message": ticket_message,
            "request_type": "Incident",
            "ticket_impact": ticket_impact,
            "ticket_urgency": ticket_urgency,
            "ticket_status": "Open",
            "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket_notes": []
        }

        ticket_store.append(new_ticket)

        logging.info("API INGEST - LibreNMS Notification %s created (severity=%s)", ticket_number, severity or 'unknown')

        try:
            local_webhook_handler.notify_ticket_event(
                ticket_number=ticket_number,
                ticket_status="Open",
                ticket_subject=ticket_subject
            )
            logging.info("API INGEST - Ticket %s status notifications sent.", ticket_number)
        except Exception as exc:
            logging.error("API INGEST - Failed to send ticket status notifications for %s", ticket_number)
            logging.debug("API INGEST - Notification error details for %s: %s", ticket_number, str(exc))

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as exc:
        cid = uuid.uuid4().hex[:8]
        logging.critical("API INGEST - LibreNMS webhook error; correlation_id=%s", cid)
        logging.debug("API INGEST - LibreNMS exception %s: %s", cid, str(exc))
        return jsonify({"error": "Internal server error"}), 500