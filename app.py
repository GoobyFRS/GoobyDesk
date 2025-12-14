#!/usr/bin/env python3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import json, threading, time, logging, requests, os
import local_config_loader
import local_email_handler
import local_webhook_handler
from dotenv import load_dotenv
from datetime import datetime
#from local_config_loader import load_core_config
#import fcntl # Unix file locking support. Not currently being used.

BUILDID=str("0.7.4-beta-a")

load_dotenv(dotenv_path=".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App Password from Gmail or relevant email provider.
CF_TURNSTILE_SITE_KEY = os.getenv("CF_TURNSTILE_SITE_KEY") # REQUIRED for CAPTCHA functionality.
CF_TURNSTILE_SECRET_KEY = os.getenv("CF_TURNSTILE_SECRET_KEY") # REQUIRED for CAPTCHA functionality.
TAILSCALE_NOTIFY_EMAIL = os.getenv("TAILSCALE_NOTIFY_EMAIL")

core_yaml_config = local_config_loader.load_core_config()
TICKETS_FILE = core_yaml_config["tickets_file"]
EMPLOYEE_FILE = core_yaml_config["employee_file"]
LOG_LEVEL = core_yaml_config["logging"]["level"]
LOG_FILE = core_yaml_config["logging"]["file"]
EMAIL_ENABLED = core_yaml_config["email"]["enabled"]
EMAIL_ACCOUNT = core_yaml_config["email"]["account"]
IMAP_SERVER = core_yaml_config["email"]["imap_server"]
SMTP_SERVER = core_yaml_config["email"]["smtp_server"]
SMTP_PORT = core_yaml_config["email"]["smtp_port"]
#DISCORD_ENABLED = core_yaml_config["discord"]["enabled"]
#SLACK_ENABLED = core_yaml_config["slack"]["enabled"]

app = Flask(__name__)
app.secret_key = os.getenv("FLASKAPP_SECRET_KEY")

logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
"""
Debug - Detailed information
Info - Successes
Warning - Unexpected events
Error - Function failures
Critical - Serious application failures
"""
# INITIAL ERROR CODES - ENV FILE RELATED

if not CF_TURNSTILE_SITE_KEY:
    logging.critical("CF_TURNSTILE_SITE_KEY must be configured in .env file. Its required for CAPTCHA functionality.")
    print("CRITICAL: CF_TURNSTILE_SITE_KEY must be configured in .env file. Its required for CAPTCHA functionality.")
    exit(108) 

if not CF_TURNSTILE_SECRET_KEY:
    logging.critical("CF_TURNSTILE_SITE_KEY must be configured in .env file. Its required for CAPTCHA functionality.")
    print("CRITICAL: CF_TURNSTILE_SITE_KEY must be configured in .env file. Its required for CAPTCHA functionality.")
    exit(109)

email_thread_enabler_check = os.getenv("EMAIL_ENABLED")
if email_thread_enabler_check is None:
    logging.critical("EMAIL_ENABLED is not defined. Defaulting to False.")
    EMAIL_ENABLED = False
else:
    EMAIL_ENABLED = email_thread_enabler_check.lower() == "true"
    logging.info(f"EMAIL_ENABLED is set to {EMAIL_ENABLED}.")

# Read/Loads the ticket file into memory. This is the original load_tickets function that works on Windows and Unix.
def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        logging.critical("Ticket Database file could not be located.")
        exit(106)
        return [] # represents an empty list.

# This load_tickets function contains the file locking mechanism for Linux. Not currently being tested or developed.
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

# Writes to the ticket file database. Eventually needs file locking for Linux.
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
        logging.debug("Employee Database file could not be located.")
        exit(107)
        return {} # represents an empty dictionary.

# Generate a new ticket number.
def generate_ticket_number():
    tickets = load_tickets() # Read/Load the tickets-db into memory.
    current_year = datetime.now().year  # Get the current year dynamically
    ticket_count = str(len(tickets) + 1).zfill(4)  # Zero-padded ticket count
    return f"TKT-{current_year}-{ticket_count}"  # Format: TKT-YYYY-XXXX

# Background email inbox monitoring process.
def background_email_monitor():
    while True:
        local_email_handler.fetch_email_replies()
        time.sleep(600)  # Wait for emails every 10 minutes.

if EMAIL_ENABLED:
    logging.info("Starting background email monitoring thread...")
    threading.Thread(target=background_email_monitor, daemon=True).start()
else:
    logging.info("EMAIL_ENABLED is set to false. Skipping...")

#threading.Thread(target=background_email_monitor, daemon=True).start()

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

            # Sends confirmation email to the requestor using the local_email_handler module.
            if EMAIL_ENABLED:
                try:
                    logging.debug(f"EMAIL HANDLER - EMAIL_ENABLED is set to true. Attempting to send email for {ticket_number}.")
                    email_body = render_template("new-ticket-email.html", ticket=new_ticket)
                    local_email_handler.send_email(requestor_email, f"{ticket_number} - {ticket_subject}", email_body, html=True)
                    logging.info(f"Confirmation Email for {ticket_number} sent successfully.")
                except Exception as e:
                    logging.error(f"Failed to send email for {ticket_number}: {str(e)}")
                else:
                    logging.info(f"EMAIL_ENABLED is set to false. Skipping email sending for {ticket_number}.")
                    
            # Sends webhook notifications using the local_webhook_handler module.    
            try:
                local_webhook_handler.notify_ticket_event(ticket_number, ticket_subject, "Open")
                logging.info(f"Webhook notifications for {ticket_number} sent successfully.")
            except Exception as e:
                logging.error(f"Failed to send webhook notifications for {ticket_number}: {str(e)}")

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
        employees = load_employees() # Loading the employee database into memory.

        # Iterate through the list of employees to check for a match.
        # After adding this feature/function the simplified ability to only have one defined technician is broke. This should be resolved before production release.
        for defined_technician in employees:
            if username == defined_technician["tech_username"] and password == defined_technician["tech_authcode"]:
                session["technician"] = username
                logging.info(f"{username} has logged in.") # Store the technician's username in the session cookie.
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
    return render_template("dashboard.html", tickets=open_tickets, loggedInTech=session["technician"], BUILDID=BUILDID)

# Route for viewing a ticket in the Ticket Commander view.
@app.route("/ticket/<ticket_number>")
def ticket_detail(ticket_number):
    if "technician" not in session:  # Validate the logged-in user cookie...
        return render_template("403.html"), 403  # Return our custom HTTP 403 page.

    tickets = load_tickets()
    ticket = next((t for t in tickets if t["ticket_number"] == ticket_number), None)
    
    if ticket:
        return render_template("ticket-commander.html", ticket=ticket, loggedInTech=session["technician"])

    return render_template("404.html"), 404

# Route for updating a ticket. Called from Dashboard and Ticket Commander.
@app.route("/ticket/<ticket_number>/update_status/<ticket_status>", methods=["POST"])
def update_ticket_status(ticket_number, ticket_status):
    logging.info(f"{ticket_number} status has been changed to {ticket_status}.")
    
    if not session.get("technician"):
        return render_template("403.html"), 403
    
    valid_statuses = ["Open", "In-Progress", "Closed"]
    if ticket_status not in valid_statuses:
        return render_template("400.html"), 400

    loggedInTech = session["technician"]
    tickets = load_tickets()

    for ticket in tickets:
        if ticket["ticket_number"] == ticket_number:
            # Extract subject for webhook notifications
            ticket_subject = ticket.get("ticket_subject", "No Subject Provided")
            # Update ticket in memory
            ticket["ticket_status"] = ticket_status
            
            if ticket_status == "Closed":
                ticket["closed_by"] = loggedInTech
                ticket["closure_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            save_tickets(tickets)
            logging.info(f"Ticket {ticket_number} status updated to {ticket_status} by {loggedInTech}.")
            # Send webhook notifications for status update.
            try:
                local_webhook_handler.notify_ticket_event(ticket_number=ticket_number,ticket_status=ticket_status,ticket_subject=ticket_subject) # Consider a refactor later.
                logging.info(f"Ticket {ticket_number} status update notifications sent successfully.")
            except Exception as e:
                logging.error(f"Failed to send ticket status update notifications for {ticket_number}: {str(e)}")

            return jsonify({"message": f"Ticket {ticket_number} updated to {ticket_status}."})

    return render_template("404.html"), 404

# Route for appending a new note to a ticket.
@app.route("/ticket/<ticket_number>/append_note", methods=["POST"])
def add_ticket_note(ticket_number):
    new_tkt_note = request.form.get("note_content")  # Ensure the key matches the JS request

    if not new_tkt_note:
        return jsonify({"message": "Note Contents cannot be empty!"}), 400

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

@app.route("/api/uptime-kuma", methods=["POST"])
def uptime_kuma_webhook():
    try:
        if not request.is_json:
            logging.warning("Uptime-Kuma webhook sent invalid content type.")
            return jsonify({"error": "Invalid content type"}), 400

        payload = request.json
        logging.info(f"Uptime Kuma payload received: {payload}")

        # Uptime Kuma Heartbeat Structure
        heartbeat = payload.get("heartbeat", {})
        monitor = payload.get("monitor", {})

        # Extract fields
        status = heartbeat.get("status")
        monitor_name = monitor.get("name", "Unknown Monitor")
        monitor_url = monitor.get("url", "Unknown URL") # Not currently used.
        message = heartbeat.get("msg", payload.get("msg", "No message")) # Not currently used.
        timestamp = heartbeat.get("time", int(time.time())) # Not currently used.

        # Status mapping for readability
        status_text = {
            0: "DOWN",
            1: "UP",
            2: "PENDING"
        }.get(status, "UNKNOWN")

        # Only trigger for DOWN events
        if status != 0:
            logging.info(f"Skipping ticket creation for {monitor_name} (status={status_text}).")
            return jsonify({"status": "ignored", "reason": "not down"}), 200

        # Build ticket content
        ticket_subject = f"Uptime Kuma Alert - {monitor_name} is DOWN"
        ticket_message = json.dumps(payload, indent=4)

        ticket_number = generate_ticket_number()
        new_ticket = {
            "ticket_number": ticket_number,
            "requestor_name": "Uptime Kuma",
            "requestor_email": "noreply@uptimekuma.local",
            "ticket_subject": ticket_subject,
            "ticket_message": ticket_message,
            "request_type": "Incident",
            "ticket_impact": "High",
            "ticket_urgency": "High",
            "ticket_status": "Open",
            "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket_notes": []
        }

        tickets = load_tickets()
        tickets.append(new_ticket)
        save_tickets(tickets)
        logging.info(f"Uptime-Kuma Notification — {ticket_number} created successfully.")

        try:
            local_webhook_handler.notify_ticket_event(ticket_number=ticket_number,ticket_status="Open",ticket_subject=ticket_subject) # Considering a refactor later.
            logging.info(f"Ticket {ticket_number} status update notifications sent successfully.")
        except Exception as e:
            logging.error(f"Failed to send ticket status update notifications for {ticket_number}: {str(e)}")

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as e:
        logging.critical(f"Uptime Kuma webhook error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

"""
@app.route("/api/newrelic", methods=["POST"])

"""

@app.route("/api/tailscale", methods=["POST"])
def tailscale_webhook():
    try:
        payload = request.json

        if not payload:
            logging.warning("WARNING: Tailscale webhook sent an empty payload.")
            return jsonify({"error": "Empty payload"}), 400

        # Pretty-print JSON for ticket body
        formatted_ts_webhook_body = json.dumps(payload, indent=4)

        # Build ticket content
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
            local_webhook_handler.notify_ticket_event(ticket_number=ticket_number,ticket_status="Open",ticket_subject=ticket_subject) # Considering a refactor later.
            logging.info(f"Ticket {ticket_number} status notifications sent successfully.")
        except Exception as e:
            logging.error(f"Failed to send ticket status update notifications for {ticket_number}: {str(e)}")

        return jsonify({"status": "success", "ticket": ticket_number}), 200

    except Exception as e:
        logging.critical(f"Tailscale webhook error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

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
    logging.info("GoobyDesk Flask application is starting up.")
    app.run() #debug=True
