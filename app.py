#!/usr/bin/env python3
"""GoobyDesk - A lightweight self-hosted ITSM platform for home users and small businesses."""
import json
import logging
import os
import threading
import time
from datetime import datetime
from datetime import timedelta
from functools import wraps
from typing import Any
from typing import Callable

import requests
from dotenv import load_dotenv
from flask import Flask
from flask import Response
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for

import local_handlers.local_authentication_handler as local_authentication_handler
import local_handlers.local_config_loader as local_config_loader
import local_handlers.local_email_handler as local_email_handler
import local_handlers.local_webhook_handler as local_webhook_handler
from blueprints.api_ingest import api_ingest_bp
from blueprints.changes_module import changes_module_bp
from blueprints.reports_module import reports_module_bp

# Type alias for ticket and employee dictionaries
# Using Any for values because ticket/employee fields have mixed types (str, list, etc.)
TicketDict = dict[str, Any]
EmployeeDict = dict[str, Any]

BUILD_ID = "0.9.4-beta"

# Rest in Peace Alex, July 2nd 2005 - December 14th 2024
# Rest in Peace Dave, August 16th 1967 - December 19th 2025

# Secrets loaded from .env file
load_dotenv(dotenv_path=".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
CF_TURNSTILE_SITE_KEY = os.getenv("CF_TURNSTILE_SITE_KEY")
CF_TURNSTILE_SECRET_KEY = os.getenv("CF_TURNSTILE_SECRET_KEY")
TAILSCALE_NOTIFY_EMAIL = os.getenv("TAILSCALE_NOTIFY_EMAIL")

# Configuration non-secret data loaded from YAML
core_yaml_config = local_config_loader.load_core_config()
TICKETS_FILE: str = core_yaml_config["tickets_file"]
EMPLOYEE_FILE: str = core_yaml_config["employee_file"]
LOG_LEVEL: str = core_yaml_config["logging"]["level"]
LOG_FILE: str = core_yaml_config["logging"]["file"]
EMAIL_ENABLED: bool = core_yaml_config["email"]["enabled"]
EMAIL_ACCOUNT: str = core_yaml_config["email"]["account"]
IMAP_SERVER: str = core_yaml_config["email"]["imap_server"]
SMTP_SERVER: str = core_yaml_config["email"]["smtp_server"]
SMTP_PORT: int = core_yaml_config["email"]["smtp_port"]

# Flask App core setup and configuration
app = Flask(__name__)
app.secret_key = os.getenv("FLASKAPP_SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=12)

app.config.update(
    SESSION_COOKIE_NAME="goobydesk_session_cookie",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=not app.debug,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_REFRESH_EACH_REQUEST=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)

api_ingest_bp.config = {"TAILSCALE_NOTIFY_EMAIL": TAILSCALE_NOTIFY_EMAIL}
app.register_blueprint(api_ingest_bp)
app.register_blueprint(reports_module_bp)
app.register_blueprint(changes_module_bp)


@app.after_request
def set_security_headers(response: Response) -> Response:
    """Add security headers to all HTTP responses.

    Args:
        response: The Flask response object.

    Returns:
        The response with security headers added.
    """
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.bunny.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https://fonts.bunny.net; "
        "connect-src 'self'; "
        "frame-src https://challenges.cloudflare.com; "
        "frame-ancestors 'none'"
    )
    if not app.debug:
        response.headers["Strict-Transport-Security"] = (
            "max-age=86400; includeSubDomains; preload"
        )
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    return response


logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(module)s/%(funcName)s - %(message)s"
)

# Validate required environment variables
if not CF_TURNSTILE_SITE_KEY or not CF_TURNSTILE_SECRET_KEY:
    logging.critical(
        "CF_TURNSTILE_SITE_KEY and CF_TURNSTILE_SECRET_KEY must be configured "
        "in the .env file. Required for CAPTCHA functionality."
    )
    exit(1)


def load_tickets() -> list[TicketDict]:
    """Load all tickets from the JSON database file.

    Returns:
        List of ticket dictionaries.

    Raises:
        SystemExit: If the ticket database file cannot be found.
    """
    try:
        with open(TICKETS_FILE, "r") as tkt_file:
            return json.load(tkt_file)
    except FileNotFoundError:
        logging.critical("Ticket JSON Database file could not be located.")
        exit(1)


def save_tickets(tickets: list[TicketDict]) -> None:
    """Save tickets to the JSON database file.

    Args:
        tickets: List of ticket dictionaries to persist.
    """
    with open(TICKETS_FILE, "w") as tkt_file_write_op:
        json.dump(tickets, tkt_file_write_op, indent=4)
        logging.debug("The Ticket JSON Database file was modified.")


def load_employees() -> list[EmployeeDict]:
    """Load all employees from the JSON database file.

    Returns:
        List of employee dictionaries.

    Raises:
        SystemExit: If the employee database file cannot be found.
    """
    try:
        with open(EMPLOYEE_FILE, "r") as tech_file_read_op:
            return json.load(tech_file_read_op)
    except FileNotFoundError:
        logging.debug("Employee JSON Database file could not be located.")
        exit(1)


def save_employees(employees: list[EmployeeDict]) -> None:
    """Save employees to the JSON database file.

    Args:
        employees: List of employee dictionaries to persist.
    """
    with open(EMPLOYEE_FILE, "w") as emp_file_write_op:
        json.dump(employees, emp_file_write_op, indent=4)
    logging.debug("The Employee JSON Database file was modified.")


def generate_ticket_number() -> str:
    """Generate a unique ticket number in the format TKT-YYYY-XXXX.

    Returns:
        A new ticket number string.
    """
    tickets = load_tickets()
    current_year = datetime.now().year
    ticket_count = str(len(tickets) + 1).zfill(4)
    return f"TKT-{current_year}-{ticket_count}"


def generate_change_request_number() -> str:
    """Generate a unique change request number in the format CHG-YYYY-XXXX.

    Returns:
        A new change request number string.
    """
    tickets = load_tickets()
    current_year = datetime.now().year
    ticket_count = str(len(tickets) + 1).zfill(4)
    return f"CHG-{current_year}-{ticket_count}"


# Background email inbox monitoring constants and function
EMAIL_MONITOR_MAX_ITERATIONS = 10_000_000
EMAIL_MONITOR_INTERVAL_SECONDS = 600


def background_email_monitor() -> None:
    """Monitor email inbox for ticket replies in a background thread.

    Runs in a loop, checking for new email replies every 10 minutes
    and appending them as notes to matching tickets.
    """
    for _ in range(EMAIL_MONITOR_MAX_ITERATIONS):
        local_email_handler.fetch_email_replies()
        time.sleep(EMAIL_MONITOR_INTERVAL_SECONDS)


if EMAIL_ENABLED is True:
    logging.info("Starting background email monitoring thread...")
    threading.Thread(target=background_email_monitor, daemon=True).start()
else:
    logging.info("EMAIL_ENABLED is set to false. Skipping...")


def technician_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to require technician authentication for a route.

    Args:
        func: The route function to wrap.

    Returns:
        Wrapped function that checks for technician session.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Response | tuple[str, int]:
        if not session.get("technician"):
            return render_template("403.html"), 403
        return func(*args, **kwargs)
    return wrapper


@app.route("/", methods=["GET", "POST"])
def home() -> Response | tuple[str, int]:
    """Handle the home page and ticket submission form.

    GET: Render the ticket submission form.
    POST: Process a new ticket submission with CAPTCHA validation.

    Returns:
        Rendered template or redirect response.
    """
    if request.method == "POST":
        return _process_ticket_submission()

    return render_template("index.html", sitekey=CF_TURNSTILE_SITE_KEY)


def _process_ticket_submission() -> Response | tuple[str, int]:
    """Process a new ticket submission from the home page form.

    Returns:
        Redirect to home page with flash message.
    """
    # Validate CAPTCHA
    turnstile_token = request.form.get("cf-turnstile-response")
    if not turnstile_token:
        flash("CAPTCHA verification failed. Please try again.", "danger")
        return redirect(url_for("home"))

    if not _verify_captcha(turnstile_token):
        flash("CAPTCHA verification failed. Please try again.", "danger")
        return redirect(url_for("home"))

    # Create and save ticket
    try:
        ticket_number = generate_ticket_number()
        new_ticket = _create_ticket_from_form(ticket_number)

        tickets = load_tickets()
        tickets.append(new_ticket)
        save_tickets(tickets)
        logging.info(f"{ticket_number} has been created.")

        _send_ticket_notifications(new_ticket, ticket_number)

        flash(f"Ticket {ticket_number} has been submitted successfully!", "success")
        return redirect(url_for("home"))

    except KeyError as e:
        logging.error(f"Missing required form field: {e}")
        flash("Please fill out all required fields.", "danger")
        return redirect(url_for("home"))


def _verify_captcha(turnstile_token: str) -> bool:
    """Verify a Cloudflare Turnstile CAPTCHA token.

    Args:
        turnstile_token: The CAPTCHA response token from the form.

    Returns:
        True if verification succeeded, False otherwise.
    """
    turnstile_url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    turnstile_data = {
        "secret": CF_TURNSTILE_SECRET_KEY,
        "response": turnstile_token,
        "remoteip": request.remote_addr
    }

    try:
        turnstile_response = requests.post(
            turnstile_url, data=turnstile_data, timeout=10
        )
        result = turnstile_response.json()
        if not result.get("success"):
            logging.warning(f"Turnstile verification failed: {result}")
            return False
        return True
    except requests.exceptions.Timeout:
        logging.error("Turnstile verification timed out")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Turnstile verification error: {e}")
        return False


def _create_ticket_from_form(ticket_number: str) -> TicketDict:
    """Create a ticket dictionary from form data.

    Args:
        ticket_number: The generated ticket number.

    Returns:
        A ticket dictionary ready for storage.

    Raises:
        KeyError: If a required form field is missing.
    """
    return {
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


def _send_ticket_notifications(ticket: TicketDict, ticket_number: str) -> None:
    """Send email and webhook notifications for a new ticket.

    Args:
        ticket: The ticket dictionary.
        ticket_number: The ticket identifier.
    """
    if EMAIL_ENABLED:
        try:
            email_body = render_template("new-ticket-email.html", ticket=ticket)
            local_email_handler.send_email(
                ticket["requestor_email"],
                f"{ticket_number} - {ticket['ticket_subject']}",
                email_body,
                html=True
            )
            logging.info(f"Confirmation email for {ticket_number} sent successfully.")
        except (OSError, ValueError) as e:
            logging.error(f"Failed to send email for {ticket_number}: {e}")
    else:
        logging.debug(f"EMAIL_ENABLED is false. Skipping email for {ticket_number}.")

    try:
        local_webhook_handler.notify_ticket_event(
            ticket_number,
            ticket["ticket_subject"],
            "Open"
        )
        logging.info(f"Webhook notifications for {ticket_number} sent successfully.")
    except (OSError, ValueError) as e:
        logging.error(f"Failed to send webhook notifications for {ticket_number}: {e}")


@app.route("/login", methods=["GET", "POST"])
def login() -> Response | tuple[str, int]:
    """Handle technician login page and authentication.

    GET: Render the login form.
    POST: Authenticate the technician and create a session.

    Returns:
        Rendered login template or redirect to dashboard on success.
    """
    if request.method == "POST":
        username = request.form.get("tech_username_box", "").strip()
        password = request.form.get("tech_password_box", "")
        employees = load_employees()

        for employee in employees:
            if employee.get("tech_username") != username:
                continue

            # Legacy password auto-migration
            if "tech_authcode" in employee:
                if password == employee["tech_authcode"]:
                    employee["password_hash"] = local_authentication_handler.hash_password(
                        password
                    )
                    del employee["tech_authcode"]
                    save_employees(employees)

                    session.permanent = True
                    session["technician"] = username
                    logging.info(
                        f"{username} logged in using legacy password and was auto-migrated."
                    )
                    return redirect(url_for("dashboard"))
                break

            # Modern hashed password check
            stored_hash = employee.get("password_hash")
            if stored_hash and local_authentication_handler.verify_password(
                password, stored_hash
            ):
                session.permanent = True
                session["technician"] = username
                logging.info(f"{username} logged in successfully.")
                return redirect(url_for("dashboard"))
            break

        logging.warning(f"Failed login attempt for username: {username}")
        return render_template("login.html", error="Invalid credentials.")

    return render_template("login.html", sitekey=CF_TURNSTILE_SITE_KEY)


@app.route("/dashboard")
@technician_required
def dashboard() -> Response | tuple[str, int]:
    """Render the technician dashboard showing open and in-progress tickets.

    Returns:
        Rendered dashboard template with filtered tickets.
    """
    tickets = load_tickets()
    open_tickets = [
        ticket for ticket in tickets
        if ticket["ticket_status"].lower() != "closed"
    ]
    return render_template(
        "dashboard.html",
        tickets=open_tickets,
        logged_in_tech=session["technician"],
        BUILDID=BUILD_ID
    )


@app.route("/ticket/<ticket_number>")
@technician_required
def ticket_detail(ticket_number: str) -> Response | tuple[str, int]:
    """Render the ticket commander view for a specific ticket.

    Args:
        ticket_number: The ticket identifier to display.

    Returns:
        Rendered ticket commander template or 404 if not found.
    """
    tickets = load_tickets()
    ticket = next((t for t in tickets if t["ticket_number"] == ticket_number), None)

    if ticket:
        return render_template(
            "ticket-commander.html",
            ticket=ticket,
            logged_in_tech=session["technician"]
        )

    return render_template("404.html"), 404


@app.route("/ticket/<ticket_number>/update_status/<ticket_status>", methods=["POST"])
@technician_required
def update_ticket_status(ticket_number: str, ticket_status: str) -> Response | tuple[str, int]:
    """Update the status of a ticket.

    Args:
        ticket_number: The ticket identifier to update.
        ticket_status: The new status value.

    Returns:
        JSON response with result message or error template.
    """
    logging.info(f"{ticket_number} status has been changed to {ticket_status}.")

    valid_statuses = ["Open", "In-Progress", "Closed"]
    if ticket_status not in valid_statuses:
        return render_template("400.html"), 400

    logged_in_tech = session["technician"]
    tickets = load_tickets()

    for ticket in tickets:
        if ticket["ticket_number"] == ticket_number:
            ticket_subject = ticket.get("ticket_subject", "No Subject Provided")
            ticket["ticket_status"] = ticket_status

            if ticket_status == "Closed":
                ticket["closed_by"] = logged_in_tech
                ticket["closure_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            save_tickets(tickets)
            logging.info(
                f"Ticket {ticket_number} status updated to {ticket_status} by {logged_in_tech}."
            )

            try:
                local_webhook_handler.notify_ticket_event(
                    ticket_number=ticket_number,
                    ticket_status=ticket_status,
                    ticket_subject=ticket_subject
                )
                logging.info(
                    f"Ticket {ticket_number} status update notifications sent successfully."
                )
            except (OSError, ValueError) as e:
                logging.error(
                    f"Failed to send ticket status update notifications for {ticket_number}: {e}"
                )

            return jsonify({"message": f"Ticket {ticket_number} updated to {ticket_status}."})

    return render_template("404.html"), 404


@app.route("/ticket/<ticket_number>/append_note", methods=["POST"])
@technician_required
def add_ticket_note(ticket_number: str) -> Response | tuple[dict[str, str], int]:
    """Append a note to a ticket.

    Args:
        ticket_number: The ticket identifier to add a note to.

    Returns:
        JSON response with success or error message.
    """
    new_tkt_note = request.form.get("note_content")

    if not new_tkt_note:
        return jsonify({"message": "Note Contents cannot be empty!"}), 400

    tickets = load_tickets()

    for ticket in tickets:
        if ticket["ticket_number"] == ticket_number:
            ticket["ticket_notes"].append(new_tkt_note)
            save_tickets(tickets)
            logging.info(f"Note successfully appended to {ticket_number}.")
            return jsonify({"message": "Note added successfully."}), 200

    return jsonify({"message": "Ticket not found."}), 404


@app.route("/logout")
def logout() -> Response:
    """Log out the current technician by clearing the session.

    Returns:
        Redirect to the login page.
    """
    session.pop("technician", None)
    return redirect(url_for("login"))


@app.errorhandler(400)
def bad_request(e: Exception) -> tuple[str, int]:
    """Handle 400 Bad Request errors.

    Args:
        e: The exception that triggered the error.

    Returns:
        Rendered 400 error template.
    """
    return render_template("400.html"), 400


@app.errorhandler(403)
def forbidden(e: Exception) -> tuple[str, int]:
    """Handle 403 Forbidden errors.

    Args:
        e: The exception that triggered the error.

    Returns:
        Rendered 403 error template.
    """
    return render_template("403.html"), 403


@app.errorhandler(404)
def page_not_found(e: Exception) -> tuple[str, int]:
    """Handle 404 Not Found errors.

    Args:
        e: The exception that triggered the error.

    Returns:
        Rendered 404 error template.
    """
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(e: Exception) -> tuple[str, int]:
    """Handle 500 Internal Server errors.

    Args:
        e: The exception that triggered the error.

    Returns:
        Rendered 500 error template.
    """
    logging.critical(f"Internal Server Error: {e}")
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run()
