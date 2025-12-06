#!/usr/bin/env python3
# Local module for sending Discord and Slack webhook notifications.
__all__ = ["send_discord_new_ticket","send_discord_update","send_slack_new_ticket","send_slack_update"]
import os
import json
import logging
import requests
from local_config_loader import load_core_config

def get_webhook_urls():
    config = load_core_config()
    return (
        config.get("discord", {}).get("webhook_url"),
        config.get("slack", {}).get("webhook_url"),
    )


def send_webhook(url, payload, service_name):
    """Generalized webhook sender for Discord & Slack."""
    if not url:
        logging.warning(
            f"WEBHOOK HANDLER - {service_name} webhook URL missing. Check .env configuration."
        )
        return False

    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()

        logging.info(
            f"WEBHOOK HANDLER - Successfully sent notification to {service_name}. Status: {response.status_code}"
        )
        return True

    except requests.exceptions.Timeout:
        logging.error(f"WEBHOOK HANDLER - {service_name} request timed out.")
    except requests.exceptions.ConnectionError:
        logging.error(
            f"WEBHOOK HANDLER - Failed to connect to {service_name}. Check internet and webhook URL."
        )
    except requests.exceptions.RequestException as e:
        logging.error(f"WEBHOOK HANDLER - {service_name} unexpected error: {e}")

    return False

# DISCORD NOTIFICATIONS

def send_discord_new_ticket(ticket_number, subject, message):
    DISCORD_URL, _ = get_webhook_urls()

    payload = {
        "username": "GoobyDesk",
        "embeds": [
            {
                "title": f"New Ticket Created: {ticket_number} - {subject}",
                "description": f"**Details:** {message}",
                "color": 0x58B9FF,  # Light blue
            }
        ],
    }

    return send_webhook(DISCORD_URL, payload, "Discord")

def send_discord_update(ticket_number, status):
    DISCORD_URL, _ = get_webhook_urls()

    payload = {
        "username": "GoobyDesk",
        "embeds": [
            {
                "title": f"Ticket {ticket_number} updated to {status}",
                "color": 0xFFFF00,  # Yellow
            }
        ],
    }

    return send_webhook(DISCORD_URL, payload, "Discord")

# SLACK NOTIFICATIONS

def send_slack_new_ticket(ticket_number, subject, message):
    _, SLACK_URL = get_webhook_urls()

    payload = {
        "username": "GoobyDesk",
        "attachments": [
            {
                "title": f"New Ticket Created: {ticket_number} - {subject}",
                "text": f"*Details:* {message}",
                "color": "#58B9FF",
            }
        ],
    }

    return send_webhook(SLACK_URL, payload, "Slack")

def send_slack_update(ticket_number, status):
    _, SLACK_URL = get_webhook_urls()

    payload = {
        "username": "GoobyDesk",
        "attachments": [
            {
                "title": f"Ticket {ticket_number} updated to {status}",
                "color": "#FFFF00",
            }
        ],
    }

    return send_webhook(SLACK_URL, payload, "Slack")