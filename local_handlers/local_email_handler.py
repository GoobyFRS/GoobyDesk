#!/usr/bin/env python3
# Local module for send_email, extract_email_body and fetch_email_replies functions.
__all__ = ["send_email", "extract_email_body", "fetch_email_replies"]
import os
import smtplib
import imaplib
import email
import re
import logging
import hashlib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from dotenv import load_dotenv
from datetime import datetime # Pending removal.

from local_handlers.utils import extract_email_body

from flask import current_app
from local_handlers.local_config_loader import load_core_config
from storage.ticket_store import TicketStore

load_dotenv(".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def _get_config():
    """Return loaded core configuration, falling back to disk when needed.
    Returns:
        dict: Core configuration mapping.
    """
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        cfg = load_core_config()
    return cfg

def _get_ticket_store():
    """Instantiate and return a TicketStore from current config.
    Returns:
        storage.ticket_store.TicketStore: Ticket store instance.
    """
    cfg = _get_config()
    return TicketStore(cfg["core"]["tickets_file"])

def _get_email_settings():
    """Return a normalized email settings dict from core config.
    Returns:
        dict: Keys: enabled, account, imap_server, smtp_server, smtp_port.
    """
    cfg = _get_config()
    email_cfg = cfg.get("email", {})
    return {
        "enabled": email_cfg.get("enabled", False),
        "account": email_cfg.get("account"),
        "imap_server": email_cfg.get("imap_server"),
        "smtp_server": email_cfg.get("smtp_server"),
        "smtp_port": email_cfg.get("smtp_port"),
    }

# Helper functions below for loading and saving tickets.
def load_tickets():
    """Load tickets using local ticket store helper.
    Returns:
        list[dict]: All ticket records.
    """
    store = _get_ticket_store()
    return store.load_all()

def _redact_email(addr: str) -> str:
    if not addr:
        return "email_unknown"
    salt = os.getenv("LOG_SALT", "")
    email_hash = hashlib.sha256((str(addr) + salt).encode()).hexdigest()[:8]
    return f"email_{email_hash}"

def save_tickets(tickets):
    """Persist tickets via ticket store helper.
    Args:
        tickets (list[dict]): Tickets to persist.
    """
    store = _get_ticket_store()
    store.save_all(tickets)
    logging.debug("EMAIL HANDLER - Ticket database was updated.")

# Helpers functions above only! Core functions below.
# Send an email if EMAIL_ENABLED is True.
def send_email(requestor_email, ticket_subject, ticket_message, html=True):
    """Send an email to requestor if email is enabled and configured.
    Args:
        requestor_email (str): Recipient email address.
        ticket_subject (str): Email subject.
        ticket_message (str): Email body.
        html (bool): Send as HTML when True.
    Returns:
        bool: True on successful send, False otherwise.
    """
    settings = _get_email_settings()
    if not settings.get("enabled"):
        logging.info("EMAIL HANDLER - Email skipped; EMAIL_ENABLED=False.")
        return False

    EMAIL_ACCOUNT = settings.get("account")
    SMTP_SERVER = settings.get("smtp_server")
    SMTP_PORT = settings.get("smtp_port")

    if not EMAIL_ACCOUNT or not EMAIL_PASSWORD or not SMTP_SERVER:
        logging.error("EMAIL HANDLER - Email configuration incomplete. Check configuration.yml and .env.")
        return False

    msg = MIMEMultipart()
    msg["Subject"] = ticket_subject
    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = requestor_email
    msg.attach(MIMEText(ticket_message, "html" if html else "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ACCOUNT, requestor_email, msg.as_string())

        logging.info("EMAIL HANDLER - Email sent to %s", _redact_email(requestor_email))
        return True

    except Exception as e:
        logging.error("EMAIL HANDLER - Email sending failed")
        logging.debug("EMAIL HANDLER - Email send exception for %s: %s", _redact_email(requestor_email), str(e))
        return False

def fetch_email_replies():
    """Fetch unread IMAP emails and append them as ticket notes.
    Connects to IMAP, finds UNSEEN messages, and appends replies
    matching ticket IDs into ticket notes.
    """
    settings = _get_email_settings()
    if not settings.get("enabled"):
        logging.debug("EMAIL HANDLER - Skipping IMAP fetch; EMAIL_ENABLED=False.")
        return
    logging.debug("EMAIL HANDLER - Checking IMAP for new email replies.")

    try:
        IMAP_SERVER = settings.get("imap_server")
        EMAIL_ACCOUNT = settings.get("account")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            logging.error("EMAIL HANDLER - IMAP search failed.")
            return
        email_ids = messages[0].split()
        tickets = load_tickets()
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                continue

            for part in msg_data:
                if not isinstance(part, tuple):
                    continue

                msg = email.message_from_bytes(part[1])
                subject_raw, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject_raw, bytes):
                    subject = subject_raw.decode(encoding or "utf-8")
                else:
                    subject = subject_raw
                ticket_match = re.search(r"TKT-\d{4}-\d+", subject)
                if not ticket_match:
                    continue

                ticket_id = ticket_match.group(0)
                body = extract_email_body(msg)
                for ticket_record in tickets:
                    if ticket_record["ticket_number"] == ticket_id:
                        ticket_record.setdefault("ticket_notes", [])
                        ticket_record["ticket_notes"].append({"ticket_message": body})
                        save_tickets(tickets)
                        logging.info("EMAIL HANDLER - Email reply added to %s", ticket_id)
                        break
        mail.logout()

    except Exception as e:
        logging.error("EMAIL HANDLER - IMAP error interacting with server")
        logging.debug("EMAIL HANDLER - IMAP exception: %s", str(e))
