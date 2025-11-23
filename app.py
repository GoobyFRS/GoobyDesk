#!/usr/bin/env python3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import json # My preffered method of "database" replacements.
import smtplib # Required protocol for sending emails by code.
import imaplib # Required protocol for receiving/logging into email provider.
import re # Regex support for reading emails and subject lines.
import email # Required to read the content of the emails.
import threading # Background process.
import time # Used for script sleeping.
import logging
import requests # CF Turnstiles.
import os # Required to load DOTENV files.
import fcntl # Unix file locking support.
from dotenv import load_dotenv # Dependant on OS module.
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart # Required for new-ticket-email.html
from email.header import decode_header
from datetime import datetime # Timestamps.
from local_webhook_handler import send_discord_notification, send_TktUpdate_discord_notification # I need to find a better way to handle this import but I learned this new thing!
from local_email_handler import send_email, fetch_email_replies

# Load environment variables from .env in the local folder.
load_dotenv(dotenv_path=".env")
TICKETS_FILE = os.getenv("TICKETS_FILE")
EMPLOYEE_FILE = os.getenv("EMPLOYEE_FILE")
IMAP_SERVER = os.getenv("IMAP_SERVER") # Provider IMAP Server Address
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT") # SEND FROM Email Address/Username
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App Password
SMTP_SERVER = os.getenv("SMTP_SERVER") # Provider SMTP Server Address.
SMTP_PORT = os.getenv("SMTP_PORT") # Provider SMTP Server Port. Default is TCP/587.
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
LOG_FILE = os.getenv("LOG_FILE")
CF_TURNSTILE_SITE_KEY = os.getenv("CF_TURNSTILE_SITE_KEY")
CF_TURNSTILE_SECRET_KEY = os.getenv("CF_TURNSTILE_SECRET_KEY")
UPTIME_KUMA_WEBHOOK_SECRET = os.getenv("UPTIME_KUMA_WEBHOOK_SECRET")

app = Flask(__name__)
app.secret_key = os.getenv("FLASKAPP_SECRET_KEY")

# Standard Logging. basicConfig makes it reusable in other local py modules.
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# INITIAL ERROR CODES - ENV FILE RELATED

if not CF_TURNSTILE_SITE_KEY:
    logging.critical("CF_TURNSTILE_SITE_KEY is not set in .env file!")
    print("CRITICAL: CF_TURNSTILE_SITE_KEY must be configured in .env file. Its required for CAPTCHA functionality.")
    exit(10) 

if not CF_TURNSTILE_SECRET_KEY:
    logging.critical("CF_TURNSTILE_SITE_KEY is not set in .env file!")
    print("CRITICAL: CF_TURNSTILE_SITE_KEY must be configured in .env file. Its required for CAPTCHA functionality.")
    exit(11) 

if not UPTIME_KUMA_WEBHOOK_SECRET:
    logging.critical("UPTIME_KUMA_WEBHOOK_SECRET is not set in .env file!")
    print("CRITICAL: UPTIME_KUMA_WEBHOOK_SECRET must be configured in .env file")
    exit(12)

# Read/Loads the ticket file into memory. This is the original load_tickets function that works on Windows and Unix.
def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        return [] # represents an empty list.

# This load_tickets function contains the file locking mechanism for Linux.

"""
def load_tickets(retries=5, delay=0.2):
   # Load tickets from JSON file with file locking and retry logic.
   for attempt in range(retries):
       try:
           with open(TICKETS_FILE, "r") as file:
               fcntl.flock(file, fcntl.LOCK_SH)  # Shared lock for reading
               tickets = json.load(file)
               fcntl.flock(file, fcntl.LOCK_UN)  # Unlock the file.
               return tickets
       except (json.JSONDecodeError, FileNotFoundError) as e:
           logging.critical(f"Error loading tickets: {e}")
           print(f"ERROR - Error loading tickets: {e}")
           return []
       except BlockingIOError:
           logging.critical(f"File is locked, retrying... ({attempt+1}/{retries})")
           time.sleep(delay)  # Wait before retrying
   raise Exception("ERROR - Failed to load tickets after multiple attempts.")
"""

# Writes to the ticket file database.
def save_tickets(tickets):
    with open(TICKETS_FILE, "w") as tkt_file_write_op:
        json.dump(tickets, tkt_file_write_op, indent=4)
        logging.debug("The ticket database file was modified.")

# Read/Loads the employee file into memory.
def load_employees():
    try:
        with open(EMPLOYEE_FILE, "r") as tech_file_read_op:
            return json.load(tech_file_read_op)
    except FileNotFoundError:
        logging.debug("Employee Database file could not be located. Check your .env config file.")
        return {} # represents an empty dictionary.

# Generate a new ticket number.
def generate_ticket_number():
    tickets = load_tickets() # Read/Load the tickets-db into memory.
    current_year = datetime.now().year  # Get the current year dynamically
    ticket_count = str(len(tickets) + 1).zfill(4)  # Zero-padded ticket count
    return f"TKT-{current_year}-{ticket_count}"  # Format: TKT-YYYY-XXXX

# Send a confirmation email.
"""
def send_email(requestor_email, ticket_subject, ticket_message, html=True):
    msg = MIMEMultipart()
    msg["Subject"] = ticket_subject
    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = requestor_email
    
    # Attach body as plain text and/or HTML
    if html:
        msg.attach(MIMEText(ticket_message, "html"))
    else:
        msg.attach(MIMEText(ticket_message, "plain"))
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ACCOUNT, requestor_email, msg.as_string())
    except Exception as e:
        logging.error(f"Email sending failed: {e}")
    logging.info(f"Confirmation Email sent to {requestor_email}")
"""

# extract_email_body is attempting to scrape the content of the "valid" TKT email replies. It skips attachments. I do not currently need this feature. 
"""
def extract_email_body(msg): 
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                continue  # Skip attachments

            if content_type == "text/plain":  # Prefer plaintext over HTML
                try:
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
                except Exception as e:
                    logging.warning(f"Error decoding email part: {e}")
                    continue
            elif content_type == "text/html" and not body:
                try:
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
                except Exception as e:
                    logging.warning(f"Error decoding HTML part: {e}")
                    continue
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore").strip()
        except Exception as e:
            logging.error(f"Error decoding single-part email: {e}")

    return body
"""

# fetch_email_replies logically occurs before extract_email_body which is above this comment in the code.
"""
def fetch_email_replies():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)  
        mail.select("inbox")  

        mail_server_response_status, messages = mail.search(None, "UNSEEN")  
        if mail_server_response_status != "OK":
            logging.error("Reading Inbox via IMAP failed for an unknown reason.")
            return

        email_ids = messages[0].split()
        tickets = load_tickets()  

        for email_id in email_ids:
            email_id = email_id.decode()  # Ensure it's a string
            mail_server_response_status, msg_data = mail.fetch(email_id, "(RFC822)")
            if mail_server_response_status != "OK" or not msg_data:
                logging.warning(f"Unable to fetch email {email_id}")
                continue  

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    from_email = msg.get("From")
                    match_ticket_reply = re.search(r"(?i)\bTKT-\d{4}-\d+\b", subject)
                    ticket_id = match_ticket_reply.group(0) if match_ticket_reply else None
                    logging.debug(f"Extracted ticket ID: {ticket_id} from subject: {subject}")  

                    if not ticket_id:
                        continue  

                    body = extract_email_body(msg)

                    for ticket in tickets:
                        if ticket["ticket_number"] == ticket_id:
                            ticket["ticket_notes"].append({"ticket_message": body})
                            save_tickets(tickets) 
                            logging.debug(f"Updated ticket {ticket_id} with reply from {from_email}") 
                            break
                        
        mail.logout()
        logging.debug("Email fetch job completed successfully.")
    except Exception as e:
        logging.error(f"Error fetching emails: {e}")
"""

# Background email monitoring. This is a running process using modules above.
def background_email_monitor():
    while True:
        fetch_email_replies()
        time.sleep(600)  # Wait for emails every 10 minutes.

threading.Thread(target=background_email_monitor, daemon=True).start()

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        try:
            # Cloudflare Turnstile CAPTCHA validation
            turnstile_token = request.form.get("cf-turnstile-response")
            if not turnstile_token:
                flash("CAPTCHA verification failed. Please try again.", "danger")
                return redirect(url_for("home"))

            turnstile_url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
            turnstile_data = {
                "secret": CF_TURNSTILE_SECRET_KEY,
                "response": turnstile_token,
                "remoteip": request.remote_addr
            }

            try:
                turnstile_response = requests.post(turnstile_url, data=turnstile_data)
                result = turnstile_response.json()
                if not result.get("success"):
                    logging.warning(f"Turnstile verification failed: {result}")
                    flash("CAPTCHA verification failed. Please try again.", "danger")
                    return redirect(url_for("home"))
            except Exception as e:
                logging.error(f"Turnstile verification error: {str(e)}")
                flash("Error verifying CAPTCHA. Please try again later.", "danger")
                return redirect(url_for("home"))

            # Process ticket submission
            requestor_name = request.form["requestor_name"]
            requestor_email = request.form["requestor_email"]
            ticket_subject = request.form["ticket_subject"]
            ticket_message = request.form["ticket_message"]
            ticket_impact = request.form["ticket_impact"]
            ticket_urgency = request.form["ticket_urgency"]
            request_type = request.form["request_type"]
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
            logging.info(f"{ticket_number} has been created.")

            # Attempt to send a Confirmation Email via SMTP with logging and graceful error handling.
            try:
                email_body = render_template("/new-ticket-email.html", ticket=new_ticket)
                send_email(requestor_email, f"{ticket_number} - {ticket_subject}", email_body, html=True)
                logging.info(f"Confirmation Email for {ticket_number} sent successfully.")
            except Exception as e:
                logging.error(f"Failed to send email for {ticket_number}: {str(e)}")

            # Attempt to send a Discord webhook notification with logging and graceful error handling.
            try:
                send_discord_notification(ticket_number, ticket_subject, ticket_message)
            except Exception as e:
                logging.error(f"Failed to send Discord notification for {ticket_number}: {str(e)}")
            # Prompt the users web interface of a successful ticket submission.
            flash(f"Ticket {ticket_number} has been submitted successfully!", "success")
            return redirect(url_for("home"))

        except Exception as e:
            logging.critical(f"Failed to process ticket submission: {str(e)}")
            return "An error occurred while submitting your ticket. Please try again later.", 500
    # Refresh and Reload the Home/Index
    return render_template("index.html", sitekey=CF_TURNSTILE_SITE_KEY)

# Route/routine for the technician login page/process.
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["tech_username_box"] # query from HTML form name.
        password = request.form["tech_password_box"]
        employees = load_employees() # Loads the employee data into memory.

        # Iterate through the list of employees to check for a match.
        # After adding this feature/function the simplified ability to only have one defined technician is broke. This should be resolved before production release.
        for defined_technician in employees:
            if username == defined_technician["tech_username"] and password == defined_technician["tech_authcode"]:
                session["technician"] = username  # Store the technician's username in the session cookie.
                return redirect(url_for("dashboard")) # On successful login, send to Dashboard.
            else:
                return render_template("404.html"), 404 # Send our custom 404 page.
        
    return render_template("login.html", sitekey=CF_TURNSTILE_SITE_KEY)

# Route/routine for rendering the core technician dashboard. Displays all Open and In-Progress tickets.
@app.route("/dashboard")
def dashboard():
    if not session.get("technician"): # Check for technician login cookie.
        return redirect(url_for("login")) #else redirect them to the login page.
    
    tickets = load_tickets()
    # Filtering out tickets with the Closed Status on the main Dashboard.
    open_tickets = [ticket for ticket in tickets if ticket["ticket_status"].lower() != "closed"]
    return render_template("dashboard.html", tickets=open_tickets, loggedInTech=session["technician"])

# Route/routine for viewing a ticket in the Ticket Commander view.
@app.route("/ticket/<ticket_number>")
def ticket_detail(ticket_number):
    if "technician" not in session:  # Validate the logged-in user cookie...
        return render_template("403.html"), 403  # Return our custom HTTP 403 page.

    tickets = load_tickets()
    ticket = next((t for t in tickets if t["ticket_number"] == ticket_number), None)
    
    if ticket:
        return render_template("ticket-commander.html", ticket=ticket, loggedInTech=session["technician"])

    return render_template("404.html"), 404

# Route/routine for updating a ticket. Called from Dashboard and Ticket Commander.
@app.route("/ticket/<ticket_number>/update_status/<ticket_status>", methods=["POST"])
def update_ticket_status(ticket_number, ticket_status): 
    if not session.get("technician"):  # Ensure only authenticated techs can update tickets.
        return render_template("403.html"), 403
    
    valid_statuses = ["Open", "In-Progress", "Closed"]
    if ticket_status not in valid_statuses:
        return render_template("400.html"), 400

    loggedInTech = session["technician"]  # Capture the logged-in technician.
    tickets = load_tickets()  # Load tickets into memory.

    for ticket in tickets:
        if ticket["ticket_number"] == ticket_number: 
            ticket["ticket_status"] = ticket_status  

            if ticket_status == "Closed":
                ticket["closed_by"] = loggedInTech  # Append the Closed_By_Tech to support ticket audits.
                ticket["closure_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Append the ticket closure date.

            save_tickets(tickets)  # Save the updated tickets.
            send_TktUpdate_discord_notification(ticket_number, ticket_status)  # Updated notification.
            logging.debug(f"Ticket {ticket_number} updated to {ticket_status}.")
            return jsonify({"message": f"Ticket {ticket_number} updated to {ticket_status}."})  # Success popup.

    return render_template("404.html"), 404  # If ticket not found.

# Route for appending a new note to a ticket.
@app.route("/ticket/<ticket_number>/append_note", methods=["POST"])
def add_ticket_note(ticket_number):
    new_tkt_note = request.form.get("note_content")  # Ensure the key matches the JS request

    if not new_tkt_note:
        return jsonify({"message": "Note content cannot be empty."}), 400

    tickets = load_tickets()  # Load tickets into memory.

    for ticket in tickets:
        if ticket["ticket_number"] == ticket_number:
            ticket["ticket_notes"].append(new_tkt_note)  # Append note
            save_tickets(tickets)  # Save updates
            logging.info(f"Note successfully appended to {ticket_number}.")
            return jsonify({"message": "Note added successfully."}), 200  # Return JSON response

    return jsonify({"message": "Ticket not found."}), 404

# Removes the session cookie from the user browser, sending the Technician/user back to the login page.
@app.route("/logout")
def logout():
    session.pop("technician", None)
    return redirect(url_for("login"))

# Route/routine for Webhook endpoint for Uptime-Kuma monitoring alerts. Automatically creates tickets when monitors go down or recover. Secured with secret token validation.
"""
@app.route("/api/uptime-kuma", methods=["POST"])
def uptime_kuma_webhook():0

    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            logging.warning("Webhook rejected: Missing Authorization header.")
            return jsonify({"status": "error", "message": "Missing Authorization header"}), 401

        if not auth_header.startswith("Bearer "):
            logging.warning("Webhook rejected: Authorization header not using Bearer token.")
            return jsonify({"status": "error", "message": "Invalid Authorization format"}), 401

        provided_token = auth_header.replace("Bearer ", "").strip()
        if provided_token != UPTIME_KUMA_WEBHOOK_SECRET:
            logging.warning(f"Webhook rejected: Invalid token from {request.remote_addr}")
            return jsonify({"status": "error", "message": "Invalid token"}), 403

        webhook_data = request.get_json(silent=True)

        if webhook_data is None:
            logging.warning("Webhook received invalid or empty JSON payload.")
            return jsonify({"status": "error", "message": "Invalid JSON payload"}), 400

        logging.debug(f"Webhook payload received: {webhook_data}")

        # ------------------------------
        # 3. Extract Monitor Information (supports BOTH formats)
        # ------------------------------

        # FORMAT A (complex):
        # {
        #   "monitor": { "name": "", "url": "", "type": "" },
        #   "heartbeat": { "msg": "", "status": 0 }
        # }

        # FORMAT B (simple):
        # {
        #   "name": "",
        #   "url": "",
        #   "msg": "",
        #   "status": "DOWN"
        # }

        monitor_obj = webhook_data.get("monitor", {}) or {}

        monitor_name = monitor_obj.get("name") or webhook_data.get("name", "Unknown Monitor")
        monitor_url = monitor_obj.get("url") or webhook_data.get("url", "N/A")
        monitor_type = monitor_obj.get("type") or "Unknown"

        heartbeat_obj = webhook_data.get("heartbeat", {}) or {}

        heartbeat_msg = heartbeat_obj.get("msg") or webhook_data.get("msg", "")

        # Status handling — can be number OR string
        heartbeat_status = heartbeat_obj.get("status")

        if heartbeat_status is None:  
            status_str = str(webhook_data.get("status", "")).lower()
            heartbeat_status = 0 if status_str == "down" else 1

        if heartbeat_status == 0:
            alert_type = "DOWN"
            ticket_impact = "High"
            ticket_urgency = "High"
            request_type = "Incident"
        else:
            alert_type = "RECOVERED"
            ticket_impact = "Low"
            ticket_urgency = "Low"
            request_type = "Incident"

        ticket_subject = f"[Uptime-Kuma] {monitor_name} - {alert_type}"

        ticket_message = f"""

Monitor Alert from Uptime-Kuma:

Monitor Name: {monitor_name}
Monitor Type: {monitor_type}
Monitor URL: {monitor_url}

Status: {alert_type}
Message: {heartbeat_msg}

This ticket was automatically generated by the Uptime-Kuma monitoring system.
        """.strip()

        if heartbeat_status == 0:
            ticket_number = generate_ticket_number()

            new_ticket = {
                "ticket_number": ticket_number,
                "requestor_name": "Uptime-Kuma Monitor",
                "requestor_email": EMAIL_ACCOUNT,   # System email
                "ticket_subject": ticket_subject,
                "ticket_message": ticket_message,
                "request_type": request_type,
                "ticket_impact": ticket_impact,
                "ticket_urgency": ticket_urgency,
                "ticket_status": "Open",
                "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticket_notes": [],
                "source": "uptime-kuma-webhook"
            }

            tickets = load_tickets()
            tickets.append(new_ticket)
            save_tickets(tickets)

            logging.info(
                f"{ticket_number} created from Uptime-Kuma webhook "
                f"for monitor '{monitor_name}' ({monitor_url})"
            )

            # Discord Notification
            try:
                send_discord_notification(ticket_number, ticket_subject, ticket_message)
            except Exception as e:
                logging.error(f"Failed sending Discord notification for {ticket_number}: {e}")

            return jsonify({
                "status": "success",
                "ticket_number": ticket_number,
                "message": f"Ticket created for monitor '{monitor_name}'"
            }), 201
        else:
            logging.info(f"Uptime-Kuma recovery received for monitor '{monitor_name}'")
            return jsonify({
                "status": "success",
                "message": f"Recovery acknowledged for {monitor_name}"
            }), 200

    except Exception as e:
        logging.error(f"ERROR: processing Uptime-Kuma webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
"""

# BELOW THIS LINE IS RESERVED FOR FLASK ERROR ROUTES. PUT ALL CORE APP FUNCTIONS ABOVE THIS LINE!
# Handle 400 errors.
@app.errorhandler(400)
def bad_request(e):
    return render_template("400.html"), 400

# Handle 403 errors.
@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403

# Handle 404 errors.
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

if __name__ == "__main__":
    app.run() #debug=True
