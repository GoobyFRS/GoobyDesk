#!/usr/bin/env python3
from flask import Flask, Response, render_template, request, redirect, url_for, session, jsonify, flash
import json, threading, time, logging, requests, os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from functools import wraps

import local_handlers.local_config_loader as local_config_loader

BUILDID=str("0.9.9-RC1")

"""
Rest in Peace Alex, July 2nd 2005 - December 14th 2024
Rest in Peace Dave, August 16th 1967 - December 19th 2025
"""
# Secrets loaded from .env file.
load_dotenv(dotenv_path=".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App Password from Gmail or relevant email provider.
CF_TURNSTILE_SITE_KEY = os.getenv("CF_TURNSTILE_SITE_KEY") # REQUIRED for CAPTCHA functionality.
CF_TURNSTILE_SECRET_KEY = os.getenv("CF_TURNSTILE_SECRET_KEY") # REQUIRED for CAPTCHA functionality.

# Configuration non-secret data loaded from YAML.
core_yaml_config = local_config_loader.load_core_config()
TICKETS_FILE = core_yaml_config["core"]["tickets_file"]
EMPLOYEE_FILE = core_yaml_config["core"]["employee_auth_file"]
CHANGES_FILE = core_yaml_config["core"]["changes_file"]
CUSTOMERS_FILE = core_yaml_config["core"]["customers_file"]
HR_FILE = core_yaml_config["core"]["hr_file"]
SERVICE_APPID_FILE = core_yaml_config["core"]["serviceid_appid_file"]
LOG_LEVEL = core_yaml_config["logging"]["level"]
LOG_FILE = core_yaml_config["logging"]["file"]
EMAIL_ENABLED = core_yaml_config["email"]["enabled"]
EMAIL_ACCOUNT = core_yaml_config["email"]["account"]
IMAP_SERVER = core_yaml_config["email"]["imap_server"]
SMTP_SERVER = core_yaml_config["email"]["smtp_server"]
SMTP_PORT = core_yaml_config["email"]["smtp_port"]
TAILSCALE_NOTIFY_EMAIL = core_yaml_config["email"]["tailscale_notify_email"]

# Centralized logging configuration. This must be configured before any
# blueprint or local_handlers module is imported, since those modules log
# at import time and logging.basicConfig() only has an effect on its first
# call per process.
logging.basicConfig(filename=LOG_FILE, level=getattr(logging, LOG_LEVEL.upper(), logging.INFO), format="%(asctime)s - %(levelname)s - %(message)s")
""" Above is the default logging configuration.
Debug - Detailed information
Info - Successes
Warning - Unexpected events
Error - Function failures
Critical - Serious application failures
"""

import local_handlers.local_authentication_handler as local_authentication_handler
import local_handlers.local_email_handler as local_email_handler
import local_handlers.local_webhook_handler as local_webhook_handler

from blueprints.api_module import api_module_bp
from blueprints.reports_module import reports_module_bp
from blueprints.changes_module import changes_module_bp
from blueprints.itsm_module import itsm_module_bp
from blueprints.hr_module import hr_module_bp
from blueprints.crm_module import crm_module_bp

# Flask App core setup and configuration.
app = Flask(__name__)
app.secret_key = os.getenv("FLASKAPP_SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=12)

app.config.update(
    SESSION_COOKIE_NAME="goobydesk_session_cookie",
    SESSION_COOKIE_HTTPONLY=True, # XSS Cookie Theft Prevention
    SESSION_COOKIE_SECURE=not app.debug, 
    SESSION_COOKIE_SAMESITE="Lax", # Strict, Lax, None
    SESSION_REFRESH_EACH_REQUEST=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,)

#api_module_bp.config = {'TAILSCALE_NOTIFY_EMAIL': TAILSCALE_NOTIFY_EMAIL}
app.register_blueprint(itsm_module_bp)
app.register_blueprint(api_module_bp)
app.register_blueprint(reports_module_bp)
app.register_blueprint(changes_module_bp)
app.register_blueprint(hr_module_bp)
app.register_blueprint(crm_module_bp)

# Security Headers for all responses.
@app.after_request
def set_security_headers(response):
    # Prevent clickjacking attacks
    response.headers['X-Frame-Options'] = 'DENY'
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Enable browser XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Control referrer information
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Content Security Policy - start restrictive and adjust as needed
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.bunny.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https://fonts.bunny.net; "
        "connect-src 'self'; "
        "frame-src https://challenges.cloudflare.com; "
        "frame-ancestors 'none'"
    )
    # HTTP Strict Transport Security (forces HTTPS) set to 1 Day.
    if not app.debug:
        response.headers['Strict-Transport-Security'] = ('max-age=86400; includeSubDomains; preload')
    
    # Permissions Policy (formerly Feature-Policy)
    response.headers['Permissions-Policy'] = ('geolocation=(), microphone=(), camera=()')
    
    return response

# INITIAL ERROR CODES
if not CF_TURNSTILE_SITE_KEY or not CF_TURNSTILE_SECRET_KEY:
    logging.critical("CF_TURNSTILE_SITE_KEY and CF_TURNSTILE_SECRET_KEY must be configured in the .env file. It is required for CAPTCHA functionality.")
    exit(1) 

#email_thread_enabler_check = os.getenv("EMAIL_ENABLED")
#if email_thread_enabler_check is None:
#    logging.info("EMAIL_ENABLED is not defined. Defaulting to False.")
#    EMAIL_ENABLED = False
#else:
#    EMAIL_ENABLED = email_thread_enabler_check.lower() == "true"
#    logging.info(f"EMAIL_ENABLED is set to {EMAIL_ENABLED}.")

# Read/Loads the ticket file into memory. This is the original load_tickets function that works on Windows and Unix.
def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        logging.critical("Ticket JSON Database file could not be located.")
        exit(1)

# Writes to the ticket file database. Eventually needs file locking for Linux.
def save_tickets(tickets):
    with open(TICKETS_FILE, "w") as tkt_file_write_op:
        json.dump(tickets, tkt_file_write_op, indent=4)
        logging.debug("The Ticket JSON Database file was modified.")

# Read/Loads the employee file into memory.
def load_employees():
    try:
        with open(EMPLOYEE_FILE, "r") as tech_file_read_op:
            return json.load(tech_file_read_op)
    except FileNotFoundError:
        logging.debug("Employee JSON Database file could not be located.")
        exit(1)
        return {} # represents an empty dictionary
    
# Helper script for secure password hasing auto-migration.
def save_employees(employees):
    with open(EMPLOYEE_FILE, "w") as emp_file_write_op:
        json.dump(employees, emp_file_write_op, indent=4)
    logging.debug("The Employee JSON Database file was modified.")

# Generate a new ticket number.
def generate_ticket_number():
    tickets = load_tickets() # Read/Load the tickets-db into memory.
    current_year = datetime.now().year  # Get the current year dynamically
    ticket_count = str(len(tickets) + 1).zfill(4)  # Zero-padded ticket count
    return f"TKT-{current_year}-{ticket_count}"  # Format: TKT-YYYY-XXXX

def generate_change_request_number():
    tickets = load_tickets() # Read/Load the tickets-db into memory.
    current_year = datetime.now().year  # Get the current year dynamically
    ticket_count = str(len(tickets) + 1).zfill(4)  # Zero-padded ticket count
    return f"CHG-{current_year}-{ticket_count}"  # Format: CHG-YYYY-XXXX

# Background email inbox monitoring process.
def background_email_monitor():
    while True:
        local_email_handler.fetch_email_replies()
        time.sleep(600)  # Wait for emails every 10 minutes.
#threading.Thread(target=background_email_monitor, daemon=True).start()

if EMAIL_ENABLED is True:
    logging.info("Starting background email monitoring thread...")
    threading.Thread(target=background_email_monitor, daemon=True).start()
else:
    logging.info("EMAIL_ENABLED is set to false. Skipping...")

# Decorator to force authentication checking. Easy to append to routes.
"""
def technician_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Session-based auth check
        if not session.get("technician"):
            # Unauthorized access attempt
            return render_template("errors/403.html"), 403
        # Authorized technician → proceed to the route
        return func(*args, **kwargs)
    return wrapper
    """

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
            ticket_number = generate_ticket_number()
            
            new_ticket = {
                "ticket_number": ticket_number,
                "requestor_name": request.form["requestor_name"],
                "requestor_email": request.form["requestor_email"],
                "ticket_subject": request.form["ticket_subject"],
                "ticket_message": request.form["ticket_message"],
                "request_type": request.form["request_type"],
                "ticket_impact": request.form["ticket_impact"],
                "ticket_urgency": request.form["ticket_urgency"],
                "ticket_status": "Open",
                "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticket_notes": []
            }

            tickets = load_tickets()
            tickets.append(new_ticket)
            save_tickets(tickets)
            logging.info(f"{ticket_number} has been created.")

            # Send confirmation email to the requestor
            if EMAIL_ENABLED:
                try:
                    email_body = render_template("new-ticket-email.html", ticket=new_ticket)
                    local_email_handler.send_email(
                        new_ticket["requestor_email"],
                        f"{ticket_number} - {new_ticket['ticket_subject']}",
                        email_body,
                        html=True
                    )
                    logging.info(f"Confirmation email for {ticket_number} sent successfully.")
                except Exception as e:
                    logging.error(f"Failed to send email for {ticket_number}: {str(e)}")
            else:
                logging.debug(f"EMAIL_ENABLED is false. Skipping email for {ticket_number}.")

            # Send webhook notifications
            try:
                local_webhook_handler.notify_ticket_event(
                    ticket_number,
                    new_ticket["ticket_subject"],
                    "Open"
                )
                logging.info(f"Webhook notifications for {ticket_number} sent successfully.")
            except Exception as e:
                logging.error(f"Failed to send webhook notifications for {ticket_number}: {str(e)}")

            # Prompt the user's web interface of a successful ticket submission
            flash(f"Ticket {ticket_number} has been submitted successfully!", "success")
            return redirect(url_for("home"))

        except KeyError as e:
            logging.error(f"Missing required form field: {str(e)}")
            flash("Please fill out all required fields.", "danger")
            return redirect(url_for("home"))
        except Exception as e:
            logging.critical(f"Failed to process ticket submission: {str(e)}")
            flash("An error occurred while submitting your ticket. Please try again later.", "danger")
            return redirect(url_for("home"))

    # Refresh and reload the Home/Index
    return render_template("public/index.html", sitekey=CF_TURNSTILE_SITE_KEY)

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
                    return redirect(url_for("itsm.dashboard"))
                # Username matched, legacy password wrong -> stop checking
                break
            # MODERN HASHED PASSWORD CHECK
            stored_hash = employee.get("password_hash")
            if stored_hash and local_authentication_handler.verify_password(password, stored_hash):
                session["technician"] = username
                logging.info(f"{username} logged in successfully.")
                return redirect(url_for("itsm.dashboard"))
            # Username matched but password incorrect
            break

        # If we reach here -> authentication failed
        logging.warning(f"Failed login attempt for username: {username}")
        return render_template("public/login.html", error="Invalid credentials.")

    return render_template("public/login.html", sitekey=CF_TURNSTILE_SITE_KEY)

@app.route("/debug/routes")
def debug_routes():
    routes = sorted(
        f"{rule.endpoint:35} {rule.rule}"
        for rule in app.url_map.iter_rules()
    )
    return "<pre>" + "\n".join(routes) + "</pre>"

# ABOVE THIS LINE SHOULD ONLY BE TECHNICIAN/TICKETING PAGES ONLY!

# BELOW THIS LINE IS RESERVED FOR LOGOUT AND API INGEST ROUTES ONLY!
# Removes the session cookie from the user browser, sending the Technician/user back to the login page.

@app.route("/logout")
def logout():
    session.clear()
    response = redirect(url_for("login"))
    response.delete_cookie("goobydesk_session_cookie")
    return response

# BELOW THIS LINE IS RESERVED FOR FLASK ERROR ROUTES. PUT ALL CORE APP FUNCTIONS ABOVE THIS LINE!
# Handle 400 errors.
@app.errorhandler(400)
def bad_request(e):
    return render_template("errors/400.html"), 400

# Handle 403 errors.
@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403

# Handle 404 errors.
@app.errorhandler(404)
def page_not_found(e):
    return render_template("errors/404.html"), 404

# Handles 500 errors.
@app.errorhandler(500)
def internal_server_error(e):
    logging.critical(f"Internal Server Error: {str(e)}")
    return render_template("errors/500.html"), 500

if __name__ == "__main__":
    app.run() #debug=True
