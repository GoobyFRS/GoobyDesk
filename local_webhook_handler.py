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
    webhook_service_status = load_webhook_config()
    webhook_service_cfg = webhook_service_status.get(service_name.lower(), {})
    return bool(webhook_service_cfg.get("enabled", False))

def get_webhook_urls():
    # LOAD WEBHOOK URLS - Easy to add more services/platforms.
    webhook_url_check = load_webhook_config()
    discord_url = webhook_url_check.get("discord", {}).get("webhook_url")
    slack_url = webhook_url_check.get("slack", {}).get("webhook_url")
    teams_url   = webhook_url_check.get("teams365", {}).get("webhook_url")

    return discord_url, slack_url, teams_url

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

    if is_enabled("teams365"):
        results["teams365"] = send_teams365_notification(ticket_number, ticket_subject, ticket_status)
    else:
        logging.debug("WEBHOOK HANDLER - Teams365 disabled; skipping.")

    return results

# -----------------------------------------------------
# GENERIC WEBHOOK SENDER
def send_webhook(url, payload, service_name):
    enabled_service_key = service_name.lower() 

    if not is_enabled(enabled_service_key):
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
    discord_url, _ = get_webhook_urls()
    new_ticket_status = ticket_status.lower() == "open"
    title = (
        f"New Ticket: {ticket_number} - Subject: {ticket_subject}"
        if new_ticket_status
        else f"Ticket: {ticket_number} updated — Status: {ticket_status}"
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

    return send_webhook(discord_url, payload, "Discord")

# -----------------------------------------------------
# SLACK PAYLOAD
def send_slack_notification(ticket_number, ticket_subject, ticket_status):
    _, slack_url = get_webhook_urls()

    ticket_status_new = ticket_status.lower() == "open"
    title = (
        f"New Ticket: {ticket_number} - Subject: {ticket_subject}"
        if ticket_status_new
        else f"Ticket: {ticket_number} updated — Status: {ticket_status}"
    )
    payload = {
        "username": "GoobyDesk",
        "attachments": [
            {
                "title": title,
                "color": "#58B9FF" if ticket_status_new else "#FFFF00",
            }
        ],
    }

    return send_webhook(slack_url, payload, "Slack")

# -----------------------------------------------------
# Microsoft Office 365 Teams PAYLOAD
def send_teams365_notification(ticket_number, ticket_subject, ticket_status):
    _, _, teams_url = get_webhook_urls()

    is_new_ticket = ticket_status.lower() == "open"

    title = (
        f"New Ticket Created"
        if is_new_ticket
        else f"Ticket Updated"
    )

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"GoobyDesk Ticket {ticket_number}",
        "themeColor": "58B9FF" if is_new_ticket else "FFFF00",
        "title": title,
        "sections": [
            {
                "facts": [
                    {"name": "Ticket Number", "value": ticket_number},
                    {"name": "Subject", "value": ticket_subject},
                    {"name": "Status", "value": ticket_status},
                ],
                "markdown": True,
            }
        ],
    }

    return send_webhook(teams_url, payload, "Teams365")

