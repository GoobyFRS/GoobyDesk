#!/usr/bin/env python3
from flask import Flask, Response, render_template, request, redirect, url_for, session, jsonify, flash
import json, threading, time, logging, requests, os, io, csv
import local_config_loader, local_email_handler, local_webhook_handler, local_authentication_handler
from dotenv import load_dotenv
from datetime import datetime, timedelta
from functools import wraps

BUILDID=str("0.7.7-beta-e")

load_dotenv(dotenv_path=".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App Password from Gmail or relevant email provider.
CF_TURNSTILE_SITE_KEY = os.getenv("CF_TURNSTILE_SITE_KEY") # REQUIRED for CAPTCHA functionality.
CF_TURNSTILE_SECRET_KEY = os.getenv("CF_TURNSTILE_SECRET_KEY") # REQUIRED for CAPTCHA functionality.
TAILSCALE_NOTIFY_EMAIL = os.getenv("TAILSCALE_NOTIFY_EMAIL")

"""
Rest in Peace Alex, July 2nd 2005 - December 14th 2024
Rest in Peace Dave, August 15th 1967 - December 19th 2025
"""

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

app = Flask(__name__)
app.secret_key = os.getenv("FLASKAPP_SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=4)

app.config.update(
    SESSION_COOKIE_NAME="goobies_cookie",
    SESSION_COOKIE_HTTPONLY=True, # XSS Cookie Theft Prevention
    SESSION_COOKIE_SECURE=not app.debug, 
    SESSION_COOKIE_SAMESITE="Lax", # Strict, Lax, None
    SESSION_REFRESH_EACH_REQUEST=True
)

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

""" This load_tickets function contains the file locking mechanism for Linux. Not currently being tested or developed.
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
        return {} # represents an empty dictionary
    
# Helper script for secure password hasing auto-migration.
def save_employees(employees):
    with open(EMPLOYEE_FILE, "w") as emp_file_write_op:
        json.dump(employees, emp_file_write_op, indent=4)
    logging.debug("The employee database file was modified.")

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
#threading.Thread(target=background_email_monitor, daemon=True).start()

if EMAIL_ENABLED:
    logging.info("Starting background email monitoring thread...")
    threading.Thread(target=background_email_monitor, daemon=True).start()
else:
    logging.info("EMAIL_ENABLED is set to false. Skipping...")

# Decorator to force authentication checking. Easy to append to routes.
def technician_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Session-based auth check
        if not session.get("technician"):
            # Unauthorized access attempt
            return render_template("403.html"), 403
        # Authorized technician → proceed to the route
        return func(*args, **kwargs)
    return wrapper

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

# The old route for the technician login page/process. This has been depricated as of v0.7.5. Consider removing this code.
"""@app.route("/login", methods=["GET", "POST"])
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
        
    return render_template("login.html", sitekey=CF_TURNSTILE_SITE_KEY)"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("tech_username_box", "").strip()
        password = request.form.get("tech_password_box", "")

        employees = load_employees()

        for employee in employees:
            if employee.get("tech_username") != username:
                session.permanent = True # Make session permanent for 'x' time defined above in app.config.
                session["technician"] = username # Define a session even if auth fails to prevent timing attacks.
                continue

            # LEGACY PASSWORD AUTO-MIGRATION
            if "tech_authcode" in employee:
                if password == employee["tech_authcode"]:
                    employee["password_hash"] = local_authentication_handler.hash_password(password)
                    del employee["tech_authcode"]

                    save_employees(employees)

                    session["technician"] = username
                    logging.info(f"{username} logged in using legacy password and was auto-migrated.")
                    return redirect(url_for("dashboard"))
                # Username matched, legacy password wrong -> stop checking
                break

            # MODERN HASHED PASSWORD CHECK
            stored_hash = employee.get("password_hash")
            if stored_hash and local_authentication_handler.verify_password(password, stored_hash):
                session["technician"] = username
                logging.info(f"{username} logged in successfully.")
                return redirect(url_for("dashboard"))

            # Username matched but password incorrect
            break

        # If we reach here -> authentication failed
        logging.warning(f"Failed login attempt for username: {username}")
        return render_template("login.html", error="Invalid credentials.")

    return render_template("login.html", sitekey=CF_TURNSTILE_SITE_KEY)

# Route/routine for rendering the core technician dashboard. Displays all Open and In-Progress tickets.
@app.route("/dashboard")
@technician_required
def dashboard():
    tickets = load_tickets()
    # Filtering out tickets with the Closed Status on the main Dashboard.
    open_tickets = [ticket for ticket in tickets if ticket["ticket_status"].lower() != "closed"]
    return render_template("dashboard.html", tickets=open_tickets, loggedInTech=session["technician"], BUILDID=BUILDID)

# Route for viewing a ticket in the Ticket Commander view.
@app.route("/ticket/<ticket_number>")
@technician_required
def ticket_detail(ticket_number):
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["ticket_number"] == ticket_number), None)
    
    if ticket:
        return render_template("ticket-commander.html", ticket=ticket, loggedInTech=session["technician"])

    return render_template("404.html"), 404

# Route for updating a ticket. Called from Dashboard and Ticket Commander.
@app.route("/ticket/<ticket_number>/update_status/<ticket_status>", methods=["POST"])
@technician_required
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
@technician_required
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

# ABOVE THIS LINE SHOULD ONLY BE TECHNICIAN/TICKETING PAGES ONLY!

@app.route("/reports_home")
@technician_required
def reports_home():

    tickets = load_tickets()
    now = datetime.now()

    # Ticket counters
    total_tickets = len(tickets)

    status_counts = {
        "Open": 0,
        "In-Progress": 0,
        "Closed": 0,
    }

    time_buckets = {
        "last_60_days": 0,
        "last_30_days": 0,
        "last_14_days": 0,
        "last_7_days": 0,
    }

    for ticket in tickets:
        # ---- Status counts ----
        status = ticket.get("ticket_status")
        if status in status_counts:
            status_counts[status] += 1

        # ---- Time-based counts ----
        try:
            submitted_at = datetime.strptime(
                ticket["submission_date"], "%Y-%m-%d %H:%M:%S"
            )
            age = now - submitted_at

            if age <= timedelta(days=60):
                time_buckets["last_60_days"] += 1
            if age <= timedelta(days=30):
                time_buckets["last_30_days"] += 1
            if age <= timedelta(days=14):
                time_buckets["last_14_days"] += 1
            if age <= timedelta(days=7):
                time_buckets["last_7_days"] += 1

        except (KeyError, ValueError):
            logging.warning("REPORTING - Invalid submission_date on ticket")

    return render_template("reports_home.html",
        total_tickets=total_tickets,
        open_tickets=status_counts["Open"],
        in_progress_tickets=status_counts["In-Progress"],
        closed_tickets=status_counts["Closed"],
        last_60_days=time_buckets["last_60_days"],
        last_30_days=time_buckets["last_30_days"],
        last_14_days=time_buckets["last_14_days"],
        last_7_days=time_buckets["last_7_days"],
        loggedInTech=session["technician"], 
        BUILDID=BUILDID
    )

@app.route("/reports/export/csv")
@technician_required
def export_tickets_csv():
    tickets = load_tickets()

    output = io.StringIO()
    writer = csv.writer(output)

    # CSV Header
    writer.writerow([
        "Ticket Number",
        "Subject",
        "Status",
        "Submission Date",
        "Closed By",
        "Closure Date"
    ])

    # Rows
    for ticket in tickets:
        writer.writerow([
            ticket.get("ticket_number", ""),
            ticket.get("ticket_subject", ""),
            ticket.get("ticket_status", ""),
            ticket.get("submission_date", ""),
            ticket.get("closed_by", ""),
            ticket.get("closure_date", "")
        ])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=goobydesk_tickets_report_basic.csv"})

# BELOW THIS LINE IS RESERVED FOR LOGOUT AND API INGEST ROUTES ONLY!
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

# Handles 500 errors.
@app.errorhandler(500)
def internal_server_error(e):
    return render_template("500.html"), 500

if __name__ == "__main__":
    app.run() #debug=True
