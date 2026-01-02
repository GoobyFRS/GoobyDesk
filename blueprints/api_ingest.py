from flask import Blueprint, request, jsonify
import json, logging
from datetime import datetime
import local_webhook_handler
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
api_ingest_bp = Blueprint('api_ingest', __name__, url_prefix='/api')

# Importing from APP to avoid circular imports. There might be a better way for this.
def get_tickets_functions():
    from app import load_tickets, save_tickets, generate_ticket_number
    return load_tickets, save_tickets, generate_ticket_number

# Status Endpoint at /api/status
@api_ingest_bp.route("/status", methods=["GET"])
def api_status():
    return jsonify({
        "installed": true,
        "edition": "COMMUNITY",
        "license_key": none
    }), 200

@api_ingest_bp.route("/tailscale", methods=["POST"])
def tailscale_webhook():
    load_tickets, save_tickets, generate_ticket_number = get_tickets_functions()
    TAILSCALE_NOTIFY_EMAIL = api_ingest_bp.config.get('TAILSCALE_NOTIFY_EMAIL', 'noreply@tailscale.example.org')
    
    try:
        payload = request.json

        if not payload:
            logging.warning("WARNING: Tailscale webhook sent an empty payload.")
            return jsonify({"error": "Empty payload"}), 400

        formatted_ts_webhook_body = json.dumps(payload, indent=4)

        requestor_name = "Tailscale"
        requestor_email = TAILSCALE_NOTIFY_EMAIL
        ticket_subject = "Tailscale Notification"
        ticket_message = formatted_ts_webhook_body
        ticket_impact = "Medium"
        ticket_urgency = "Medium"
        request_type = "Change"
        ticket_number = generate_ticket_number()

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

        tickets = load_tickets()
        tickets.append(new_ticket)
        save_tickets(tickets)
        logging.info(f"Tailscale Notification — {ticket_number} created successfully.")

        try:
            local_webhook_handler.notify_ticket_event(
                ticket_number=ticket_number,
                ticket_status="Open",
                ticket_subject=ticket_subject
            )
            logging.info(f"Ticket {ticket_number} status notifications sent successfully.")
        except Exception as e:
            logging.error(f"Failed to send ticket status update notifications for {ticket_number}: {str(e)}")

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as e:
        logging.critical(f"Tailscale webhook error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@api_ingest_bp.route("/uptime-kuma", methods=["POST"])
def uptime_kuma_webhook():
    load_tickets, save_tickets, generate_ticket_number = get_tickets_functions()
    
    try:
        if not request.is_json:
            logging.warning("Uptime-Kuma webhook sent invalid content type.")
            return jsonify({"error": "Invalid content type"}), 400
        payload = request.json
        logging.info(f"Uptime Kuma payload received: {payload}")

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
            logging.info(f"Skipping ticket creation for {monitor_name} (status={status_text}).")
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

        ticket_message = json.dumps(payload, indent=4)
        ticket_number = generate_ticket_number()

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

        tickets = load_tickets()
        tickets.append(new_ticket)
        save_tickets(tickets)

        logging.info(f"Uptime-Kuma Notification — {ticket_number} created successfully (Status: {status_text}).")

        try:
            local_webhook_handler.notify_ticket_event(
                ticket_number=ticket_number,
                ticket_status="Open",
                ticket_subject=ticket_subject
            )
            logging.info(f"Ticket {ticket_number} status update notifications sent successfully.")
        except Exception as e:
            logging.error(f"Failed to send ticket status update notifications for {ticket_number}: {str(e)}")

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as e:
        logging.critical(f"Uptime Kuma webhook error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
    