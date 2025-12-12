#!/usr/bin/env python3
# Local module for send_email, extract_email_body and fetch_email_replies functions.
__all__ = ["send_email", "extract_email_body", "fetch_email_replies"]
import os
import smtplib
import imaplib
import email
import re
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from dotenv import load_dotenv
import json
from datetime import datetime
from local_config_loader import load_core_config

load_dotenv(".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

core_yaml_config = load_core_config()
# Configuration variables from core_configuration.yml
EMAIL_ENABLED = core_yaml_config["email"]["enabled"]
EMAIL_ACCOUNT = core_yaml_config["email"]["account"]
IMAP_SERVER = core_yaml_config["email"]["imap_server"]
SMTP_SERVER = core_yaml_config["email"]["smtp_server"]
SMTP_PORT = core_yaml_config["email"]["smtp_port"]
TICKETS_FILE = core_yaml_config["tickets_file"]

"""
Logging expectations:
Debug - Detailed information for troubleshooting
Info - Successful operations
Warning - Unexpected but non-breaking events
Error - Failures of functions that the app can recover from
Critical - Serious application failures
"""
# Helper functions below for loading and saving tickets.
def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        return []

def save_tickets(tickets):
    with open(TICKETS_FILE, "w") as f:
        json.dump(tickets, f, indent=4)
    logging.debug("EMAIL HANDLER - Ticket database updated.")

# Helpers functions above only! Core functions below.
# Send an email if EMAIL_ENABLED is True.
def send_email(requestor_email, ticket_subject, ticket_message, html=True):
    if not EMAIL_ENABLED:
        logging.info("EMAIL HANDLER - Email skipped; EMAIL_ENABLED=False.")
        return False

    if not EMAIL_ACCOUNT or not EMAIL_PASSWORD or not SMTP_SERVER:
        logging.error("EMAIL HANDLER - Email configuration incomplete. Check core_configuration.yml and .env.")
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

        logging.info(f"EMAIL HANDLER - Email sent to {requestor_email}")
        return True

    except Exception as e:
        logging.error(f"EMAIL HANDLER - Email sending failed: {e}")
        return False

def extract_email_body(msg):
    logging.debug("EMAIL HANDLER - Extracting email body.")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition"))
            if "attachment" in cdisp:
                continue
            try:
                if ctype == "text/plain":
                    return part.get_payload(decode=True).decode(errors="ignore").strip()
                elif ctype == "text/html" and not body:
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
            except Exception as e:
                logging.warning(f"EMAIL HANDLER - Failed decoding email part: {e}")
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore").strip()
        except Exception as e:
            logging.error(f"EMAIL HANDLER - Failed decoding email: {e}")
    return body

def fetch_email_replies():
    """Fetch unread IMAP emails and append them as ticket notes."""
    if not EMAIL_ENABLED:
        logging.debug("EMAIL HANDLER - Skipping IMAP fetch; EMAIL_ENABLED=False.")
        return

    logging.debug("EMAIL HANDLER - Checking IMAP for new email replies.")

    try:
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
                for t in tickets:
                    if t["ticket_number"] == ticket_id:
                        t["ticket_notes"].append({"ticket_message": body})
                        save_tickets(tickets)
                        logging.info(f"EMAIL HANDLER - Email reply added to {ticket_id}.")
                        break
        mail.logout()

    except Exception as e:
        logging.error(f"EMAIL HANDLER - IMAP error: {e}")
