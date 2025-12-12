#!/usr/bin/env python3
# Local module for Chat Platform webhook notifications.
import logging
import requests
import local_config_loader

__all__ = ["notify_ticket_event", "send_webhook"]

# CONFIG HELPERS
def load_webhook_config():
    return local_config_loader.load_core_config() or {}

def is_enabled(service_name: str) -> bool:
    enabled_service_status = load_webhook_config()
    service_cfg = enabled_service_status.get(service_name.lower(), {})
    return bool(service_cfg.get("enabled", False))

def get_webhook_urls():
    webhook_url_check = load_webhook_config()
    discord_url = webhook_url_check.get("discord", {}).get("webhook_url")
    slack_url = webhook_url_check.get("slack", {}).get("webhook_url")

    return discord_url, slack_url

# -----------------------------------------------------
# MAIN ENTRY POINT: SEND TICKET EVENTS
def notify_ticket_event(ticket_number: str, ticket_subject: str, ticket_status: str):

    results = {}

    if is_enabled("discord"):
        results["discord"] = send_discord_notification(ticket_number, ticket_subject, ticket_status)
    else:
        logging.debug("WEBHOOK HANDLER - Discord disabled; skipping.")

    if is_enabled("slack"):
        results["slack"] = send_slack_notification(ticket_number, ticket_subject, ticket_status)
    else:
        logging.debug("WEBHOOK HANDLER - Slack disabled; skipping.")

    return results

# -----------------------------------------------------
# GENERIC WEBHOOK SENDER
def send_webhook(url, payload, service_name):
    service_key = service_name.lower()

    if not is_enabled(service_key):
        logging.info(f"WEBHOOK HANDLER - {service_name} disabled. Skipping.")
        return False

    if not url:
        logging.warning(f"WEBHOOK HANDLER - {service_name} webhook URL missing in core_configuration.yml")
        return False

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        logging.info(f"WEBHOOK HANDLER - Successfully sent notification to {service_name}.")
        return True

    except requests.exceptions.Timeout:
        logging.error(f"WEBHOOK HANDLER - {service_name} request timed out.")
    except requests.exceptions.ConnectionError:
        logging.error(f"WEBHOOK HANDLER - Failed to connect to {service_name}.")
    except requests.exceptions.RequestException as e:
        logging.error(f"WEBHOOK HANDLER - {service_name} unexpected error: {e}")

    return False

# -----------------------------------------------------
# DISCORD PAYLOAD
def send_discord_notification(ticket_number, ticket_subject, ticket_status):
    DISCORD_URL = get_webhook_urls()
    new_ticket_status = ticket_status.lower() == "open"
    title = (
        f"New Ticket {ticket_number} — {ticket_subject}"
        if new_ticket_status
        else f"Ticket {ticket_number} updated — Status: {ticket_status}"
    )
    payload = {
        "username": "GoobyDesk",
        "embeds": [
            {
                "title": title,
                "color": 0x58B9FF if new_ticket_status else 0xFFFF00,
            }
        ],
    }

    return send_webhook(DISCORD_URL, payload, "Discord")

# -----------------------------------------------------
# SLACK PAYLOAD
# -----------------------------------------------------
def send_slack_notification(ticket_number, ticket_subject, ticket_status):
    SLACK_URL = get_webhook_urls()

    new_ticket_status = ticket_status.lower() == "open"
    title = (
        f"New Ticket {ticket_number}: {ticket_subject}"
        if new_ticket_status
        else f"Ticket {ticket_number} updated — Status: {ticket_status}"
    )
    payload = {
        "username": "GoobyDesk",
        "attachments": [
            {
                "title": title,
                "color": "#58B9FF" if new_ticket_status else "#FFFF00",
            }
        ],
    }

    return send_webhook(SLACK_URL, payload, "Slack")
