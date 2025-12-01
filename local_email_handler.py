#!/usr/bin/env python3
# Local module for send_email, extact_email_body and fetch_email_replies functions.
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

# Load environment variables
load_dotenv(".env")

EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "False").lower() == "true"
IMAP_SERVER = os.getenv("IMAP_SERVER")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")
TICKETS_FILE = os.getenv("TICKETS_FILE") # Required for email ticket handling.

# Helper Functions for ticket handling. Not using a locking mechanism for simplicity. Maybe in the future.

def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        return [] # represents an empty list.
    
def save_tickets(tickets): # Required for email ticket handling.
    with open(TICKETS_FILE, "w") as tkt_file_write_op:
        json.dump(tickets, tkt_file_write_op, indent=4)
        logging.debug("The ticket database file was modified.")

# Core Email Handling Functions.

def send_email(requestor_email, ticket_subject, ticket_message, html=True):
    if not EMAIL_ENABLED:
        logging.info("EMAIL HANDLER - Email skipped as EMAIL_ENABLED is set to False.")
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
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition"))

            if "attachment" in cdisp:
                continue

            try:
                if ctype == "text/plain":
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
                    return body
                elif ctype == "text/html" and not body:
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
            except Exception as e:
                logging.warning(f"EMAIL HANDLER - Error decoding email part: {e}")
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore").strip()
        except Exception as e:
            logging.error(f"EMAIL HANDLER - Error decoding single email: {e}")

    return body

def fetch_email_replies():
    if not EMAIL_ENABLED:
        logging.debug("EMAIL HANDLER - IMAP fetch skipped as EMAIL_ENABLED is set to False.")
        return

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            logging.error("EMAIL HANDLER - Failed to search inbox.")
            return

        email_ids = messages[0].split()
        tickets = load_tickets()

        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                continue

            for part in msg_data:
                if isinstance(part, tuple):
                    msg = email.message_from_bytes(part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]

                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    match_ticket = re.search(r"TKT-\d{4}-\d+", subject)
                    if not match_ticket:
                        continue

                    ticket_id = match_ticket.group(0)
                    body = extract_email_body(msg)

                    for t in tickets:
                        if t["ticket_number"] == ticket_id:
                            t["ticket_notes"].append({"ticket_message": body})
                            save_tickets(tickets)
                            logging.info(f"EMAIL HANDLER - Updated {ticket_id} with email reply.")
                            break

        mail.logout()

    except Exception as e:
        logging.error(f"EMAIL HANDLER - Error fetching email replies: {e}")
