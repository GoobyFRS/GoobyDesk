#!/usr/bin/env python3
# Local module for Chat Platform webhook notifications.
import logging
import requests
import local_config_loader

__all__ = ["notify_ticket_event","send_webhook",]

# Helper functions.
def load_webhook_config():
    return local_config_loader.load_core_config()

def is_enabled(service_name: str) -> bool:
    return load_webhook_config.get(service_name, {}).get("enabled", False)

def get_webhook_urls():
    get_webhook_config = local_config_loader.load_core_config()
    return (
        get_webhook_config.get("discord", {}).get("webhook_url"),
        get_webhook_config.get("slack", {}).get("webhook_url"),
    )

# ---------------------------------------
# MAIN NOTIFICATION ENTRY POINT
# ---------------------------------------
# TICKET NUMBER, SUBJECT, STATUS!
def notify_ticket_event(ticket_number: str, ticket_subject: str, ticket_status: str):
    results = {}

    if is_enabled("discord"):
        results["discord"] = send_discord_notification(
            ticket_number, ticket_subject, ticket_status
        )

    if is_enabled("slack"):
        results["slack"] = send_slack_notification(
            ticket_number, ticket_subject, ticket_status
        )

    return results

# ---------------------------------------
# GENERIC WEBHOOK FUNCTION
# ---------------------------------------
def send_webhook(url, payload, service_name):
    if not is_enabled(service_name.lower()):
        logging.info(f"WEBHOOK HANDLER - {service_name} disabled. Skipping.")
        return False

    if not url:
        logging.warning(f"WEBHOOK HANDLER - {service_name} webhook URL missing in core_configuration.yml")
        return False

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        logging.info(f"WEBHOOK HANDLER - Successfully sent notification to {service_name}. ")
        return True

    except requests.exceptions.Timeout:
        logging.error(f"WEBHOOK HANDLER - {service_name} request timed out.")
    except requests.exceptions.ConnectionError:
        logging.error(
            f"WEBHOOK HANDLER - Failed to connect to {service_name}.")
    except requests.exceptions.RequestException as e:
        logging.error(f"WEBHOOK HANDLER - {service_name} unexpected error: {e}")

    return False
# ---------------------------------------
# Discord
def send_discord_notification(ticket_number, ticket_subject, ticket_status):
    DISCORD_URL, _ = get_webhook_urls()

    # Better titles depending on whether it's new or updated
    title = (
        f"New Ticket {ticket_number}: {ticket_subject}"
        if ticket_status.lower() == "open"
        else f"Ticket {ticket_number} updated — Status: {ticket_status}"
    )

    payload = {
        "username": "GoobyDesk",
        "embeds": [
            {
                "title": title,
                "color": 0x58B9FF if ticket_status.lower() == "open" else 0xFFFF00,
            }
        ],
    }

    return send_webhook(DISCORD_URL, payload, "Discord")

# ---------------------------------------
# Slack
def send_slack_notification(ticket_number, ticket_subject, ticket_status):
    _, SLACK_URL = get_webhook_urls()

    title = (
        f"New Ticket {ticket_number}: {ticket_subject}"
        if ticket_status.lower() == "open"
        else f"Ticket {ticket_number} updated — Status: {ticket_status}"
    )

    payload = {
        "username": "GoobyDesk",
        "attachments": [
            {
                "title": title,
                "color": "#58B9FF" if ticket_status.lower() == "open" else "#FFFF00",
            }
        ],
    }

    return send_webhook(SLACK_URL, payload, "Slack")
