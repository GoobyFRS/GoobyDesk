#!/usr/bin/env python3
from flask import Flask, Response, render_template, request, redirect, url_for, session, jsonify, flash
import threading, time, logging, logging.config, requests, os, uuid, hashlib
from dotenv import load_dotenv
from datetime import datetime, timedelta

from local_handlers.utils import hash_password, verify_password, resolve_preferred_name
import local_handlers.local_config_loader as local_config_loader
import local_handlers.local_email_handler as local_email_handler
import local_handlers.local_webhook_handler as local_webhook_handler
import local_handlers.ticket_builder as ticket_builder

from blueprints.api_module import api_module_bp
from blueprints.reports_module import reports_module_bp
from blueprints.changes_module import changes_module_bp
from blueprints.itsm_module import itsm_module_bp
from blueprints.hr_module import hr_module_bp
from blueprints.crm_module import crm_module_bp
from blueprints.serviceid_module import serviceid_module_bp
from storage.employee_store import EmployeeStore
from storage.changes_store import ChangesStore
from storage.ticket_store import TicketStore

BUILDID=str("1.0.0")

def _pseudonymize_actor(name: str) -> str:
    """Return a stable, opaque actor id for logging (no raw usernames).
    Uses optional LOG_SALT env var to make hashes non-identical across deployments.
    """
    if not name:
        return "actor_unknown"
    salt = os.getenv("LOG_SALT", "")
    hash_digest = hashlib.sha256((str(name) + salt).encode()).hexdigest()[:8]
    return f"actor_{hash_digest}"

"""
Rest in Peace Alex, July 2nd 2005 - December 14th 2024
Rest in Peace Dave, August 16th 1967 - December 19th 2025
"""
# Secrets loaded from .env file.
load_dotenv(dotenv_path=".env")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App Password from Gmail or relevant email provider.
# Cloudflare Turnstile keys (optional). If missing, CAPTCHA is disabled.
CF_TURNSTILE_SITE_KEY = os.getenv("CF_TURNSTILE_SITE_KEY")
CF_TURNSTILE_SECRET_KEY = os.getenv("CF_TURNSTILE_SECRET_KEY")
CAPTCHA_ENABLED = bool(CF_TURNSTILE_SITE_KEY and CF_TURNSTILE_SECRET_KEY)

# Configuration non-secret data loaded from YAML.
core_yaml_config = local_config_loader.load_core_config()
TICKETS_FILE = core_yaml_config["core"]["tickets_file"]
EMPLOYEE_FILE = core_yaml_config["core"]["employee_auth_file"]
LOG_LEVEL = core_yaml_config.get("logging", {}).get("level", "INFO")
LOG_FILE = core_yaml_config.get("logging", {}).get("file")
EMAIL_ENABLED = core_yaml_config["email"]["enabled"]
EMAIL_ACCOUNT = core_yaml_config["email"]["account"]
IMAP_SERVER = core_yaml_config["email"]["imap_server"]
SMTP_SERVER = core_yaml_config["email"]["smtp_server"]
SMTP_PORT = core_yaml_config["email"]["smtp_port"]
TAILSCALE_NOTIFY_EMAIL = core_yaml_config["email"]["tailscale_notify_email"]

# Centralized logging configuration
LOG_CFG = core_yaml_config.get("logging_config")
if not LOG_CFG:
    # No YAML logging config found — construct a minimal `dictConfig` dict
    # that provides reasonable defaults for formatting and handlers.
    # `version` is required by logging.config.dictConfig.
    # The `default` formatter includes timestamp, level, logger name, and message.
    LOG_CFG = {
        "version": 1,
        "formatters": {
            "default": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"}
        },
        # Console handler writes to stdout/stderr using the default formatter.
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "default"}
        },
        # Root logger uses configured `LOG_LEVEL` and the console handler by default.
        "root": {"level": LOG_LEVEL.upper(), "handlers": ["console"]},
    }
    # If a log file path is configured, add a FileHandler and attach it to root.
    if LOG_FILE:
        LOG_CFG["handlers"]["file"] = {
            "class": "logging.FileHandler",
            "filename": LOG_FILE,
            "formatter": "default",
        }
        LOG_CFG["root"]["handlers"].append("file")

try:
    logging.config.dictConfig(LOG_CFG)
except Exception:
    # If dictConfig fails, fall back to a reasonable basicConfig so app still logs.
    logging.exception("Failed to apply logging dictConfig; falling back to basicConfig.")
    logging.basicConfig(level=LOG_LEVEL.upper())

""" Above is the default logging configuration.
Debug - Detailed information
Info - Successes
Warning - Unexpected events
Error - Function failures
Critical - Serious application failures
"""

ticket_store = TicketStore(TICKETS_FILE)
change_store = ChangesStore(core_yaml_config["core"]["changes_file"])
employee_store = EmployeeStore(EMPLOYEE_FILE)

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

# Expose loaded core configuration for blueprints and handlers that use it at runtime
app.config["LOADED_CONFIG"] = core_yaml_config

#api_module_bp.config = {'TAILSCALE_NOTIFY_EMAIL': TAILSCALE_NOTIFY_EMAIL}
app.register_blueprint(itsm_module_bp)
app.register_blueprint(api_module_bp)
app.register_blueprint(reports_module_bp)
app.register_blueprint(changes_module_bp)
app.register_blueprint(hr_module_bp)
app.register_blueprint(crm_module_bp)
app.register_blueprint(serviceid_module_bp)

# Security Headers for all responses.
@app.after_request
def set_security_headers(response):
    """Attach common security headers to every response.
    Args:
        response (flask.Response): Response object to modify.
    Returns:
        flask.Response: Modified response with security headers.
    """
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
        "frame-ancestors 'none'")
    # HTTP Strict Transport Security (forces HTTPS) set to 1 Day.
    if not app.debug:
        response.headers['Strict-Transport-Security'] = ('max-age=86400; includeSubDomains; preload')
    
    # Permissions Policy (formerly Feature-Policy)
    response.headers['Permissions-Policy'] = ('geolocation=(), microphone=(), camera=()')
    
    return response

# INITIAL ERROR CODES
if not CAPTCHA_ENABLED:
    logging.critical("CF_TURNSTILE_SITE_KEY and/or CF_TURNSTILE_SECRET_KEY not set; CAPTCHA disabled.")

# Read/Loads the ticket file into memory. This is the original load_tickets function that works on Windows and Unix.
def load_tickets():
    """Load tickets from storage.
    Returns:
        list[dict]: All ticket records.
    """
    return ticket_store.load_all()

# Writes to the ticket file database. Eventually needs file locking for Linux.
def save_tickets(tickets):
    """Persist tickets to storage.
    Args: tickets (list[dict]): Tickets to save.
    """
    ticket_store.save_all(tickets)
    logging.debug("The Ticket JSON Database file was modified.")

# Read/Loads the employee file into memory.
def load_employees():
    """Load employee records from storage.
    Returns: list[dict]: Employee records.
    """
    return employee_store.load_all()
    
# Helper script for secure password hasing auto-migration.
def save_employees(employees):
    """Persist employee records to storage.
    Args: employees (list[dict]): Employee records to save.
    """
    employee_store.save_all(employees)
    logging.debug("The Employee JSON Database file was modified.")

def _assign_roles_to_session(employee: dict) -> None:
    """Populate `session['roles']` from an employee record.
    Prefers explicit `roles`; falls back to `user_role` or `role`.
    Args: employee (dict): Employee record.
    """
    roles = employee.get("roles")
    if isinstance(roles, list):
        session["roles"] = roles
        return

    role = (employee.get("user_role") or employee.get("role") or "").strip().lower()
    if role:
        session["roles"] = [role]
        return

    session["roles"] = []

# Generate a new ticket number.
def generate_ticket_number():
    """Generate next ticket number for current year.
    Returns: str: New ticket identifier.
    """
    return ticket_store.next_ticket_number(datetime.now().year)

# Generate a new change request number.
def generate_change_request_number():
    """Generate next change request number for current year.
    Returns: str: New change request identifier.
    """
    return change_store.next_change_number(datetime.now().year)


def _verify_turnstile():
    """Validate Cloudflare Turnstile token when enabled.
    Returns: bool: True when CAPTCHA is disabled or verification succeeds.
    """
    if not CAPTCHA_ENABLED:
        return True

    turnstile_token = request.form.get("cf-turnstile-response")
    if not turnstile_token:
        logging.warning("Missing Turnstile token in form")
        flash("CAPTCHA verification failed. Please try again.", "danger")
        return False

    url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    data = {
        "secret": CF_TURNSTILE_SECRET_KEY,
        "response": turnstile_token,
        "remoteip": request.remote_addr,
    }
    try:
        resp = requests.post(url, data=data, timeout=5)
        result = resp.json()
    except Exception as e:
        logging.error("Turnstile verification error while contacting provider")
        logging.debug("Turnstile verification exception: %s", str(e))
        flash("Error verifying CAPTCHA. Please try again later.", "danger")
        return False

    if not result.get("success"):
        logging.warning("Turnstile verification failed: %s", result)
        flash("CAPTCHA verification failed. Please try again.", "danger")
        return False

    return True

# Background email inbox monitoring process.
def background_email_monitor():
    """Background loop: poll mailbox for replies every 10 minutes.
    Runs indefinitely; intended for a daemon thread.
    """
    while True:
        local_email_handler.fetch_email_replies()
        time.sleep(600)  # Wait for emails every 10 minutes.
#threading.Thread(target=background_email_monitor, daemon=True).start()

if EMAIL_ENABLED is True:
    logging.info("Starting background email monitoring thread...")
    threading.Thread(target=background_email_monitor, daemon=True).start()
else:
    logging.info("EMAIL_ENABLED is set to false. Skipping...")

@app.route("/", methods=["GET", "POST"])
def home():
    """Serve home page and handle ticket submissions.
    POST: validate CAPTCHA, create ticket, trigger side-effects, redirect.
    GET: render index template.
    """
    if request.method == "POST":
        # Verify CAPTCHA early and return on failure
        if not _verify_turnstile():
            return redirect(url_for("home"))

        # Build and persist ticket; handle form problems separately from side-effects
        try:
            ticket_number = generate_ticket_number()
            new_ticket = ticket_builder.build_ticket_record(
                request.form,
                ticket_number,
                source="web", technician=resolve_preferred_name(session.get("technician")))
            ticket_store.append(new_ticket)
            logging.info("Ticket %s created.", ticket_number)
        except KeyError as e:
            logging.error("Missing required form field in ticket submission")
            logging.debug("Ticket submission missing field: %s", str(e))
            flash("Please fill out all required fields.", "danger")
            return redirect(url_for("home"))
        except Exception as e:
            cid = uuid.uuid4().hex[:8]
            logging.critical("Failed to process ticket submission; correlation_id=%s", cid)
            logging.debug("Ticket submission exception %s: %s", cid, str(e))
            flash("An error occurred while submitting your ticket. Please try again later.", "danger")
            return redirect(url_for("home"))

        # Side-effects: email and webhooks — failures should not block user flow
        if EMAIL_ENABLED:
            try:
                email_body = render_template("new-ticket-email.html", ticket=new_ticket)
                local_email_handler.send_email(
                    new_ticket.get("requestor_email"),
                    f"{ticket_number} - {new_ticket.get('ticket_subject')}",
                    email_body,
                    html=True,
                )
                logging.info("Confirmation email for %s sent.", ticket_number)
            except Exception as e:
                logging.error("Failed to send confirmation email for %s", ticket_number)
                logging.debug("Email send exception for %s: %s", ticket_number, str(e))
        else:
            logging.debug("EMAIL_ENABLED is false. Skipping email for %s.", ticket_number)

        try:
            local_webhook_handler.notify_ticket_event(ticket_number, new_ticket.get("ticket_subject"), "Open")
            logging.info("Webhook notifications for %s sent successfully.", ticket_number)
        except Exception as e:
            logging.error("Failed to send webhook notifications for %s", ticket_number)
            logging.debug("Webhook notification exception for %s: %s", ticket_number, str(e))

        flash(f"Ticket {ticket_number} has been submitted successfully!", "success")
        return redirect(url_for("home"))

    # Refresh and reload the Home/Index
    return render_template("public/index.html", sitekey=(CF_TURNSTILE_SITE_KEY if CAPTCHA_ENABLED else None))

@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle technician login (legacy and hashed passwords supported).
    POST: authenticate and set session.
    GET: render login page.
    """
    if request.method == "POST":
        # Verify CAPTCHA early and block login attempts when it fails
        if not _verify_turnstile():
            return render_template("public/login.html", sitekey=CF_TURNSTILE_SITE_KEY)
        username = request.form.get("tech_username_box", "").strip()
        password = request.form.get("tech_password_box", "")
        employees = load_employees()
        # Find user record first
        user = next((employee for employee in employees if str(employee.get("tech_username", "")).lower() == username.lower()), None)
        if user is None:
            logging.warning("Failed login attempt (user not found) actor=%s", _pseudonymize_actor(username))
            return render_template("public/login.html", error="Invalid credentials.")

        if user.get("account_locked") or user.get("login_enabled") is False:
            logging.warning("Failed login attempt (account disabled) actor=%s", _pseudonymize_actor(username))
            return render_template("public/login.html", error="Invalid credentials.")

        # LEGACY PASSWORD AUTO-MIGRATION
        if "tech_authcode" in user:
            if password == user["tech_authcode"]:
                user["password_hash"] = hash_password(password)
                del user["tech_authcode"]
                save_employees(employees)
                session.permanent = True
                session["technician"] = username
                _assign_roles_to_session(user)
                logging.info("Login via legacy password auto-migrated actor=%s", _pseudonymize_actor(username))
                return redirect(url_for("itsm.dashboard"))
            logging.warning("Failed legacy login attempt actor=%s (password mismatch)", _pseudonymize_actor(username))
            return render_template("public/login.html", error="Invalid credentials.")

        # MODERN HASHED PASSWORD CHECK
        stored_hash = user.get("password_hash")
        if stored_hash and verify_password(password, stored_hash):
            session.permanent = True
            session["technician"] = username
            _assign_roles_to_session(user)
            logging.info("Login success actor=%s", _pseudonymize_actor(username))
            return redirect(url_for("itsm.dashboard"))

        logging.warning("Failed login attempt (bad password) actor=%s", _pseudonymize_actor(username))
        return render_template("public/login.html", error="Invalid credentials.")

    return render_template("public/login.html", sitekey=CF_TURNSTILE_SITE_KEY)

@app.route("/debug/routes")
def debug_routes():
    """Return a plain-text list of registered Flask routes for debugging.
    Returns:
        str: Preformatted routes list.
    """
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
    """Clear session and remove session cookie, redirect to login.
    Returns:
        Response: Redirect to login page.
    """
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
    correlation = uuid.uuid4().hex[:8]
    logging.critical("Internal Server Error: correlation_id=%s", correlation)
    logging.debug("Internal Server Error details for %s: %s", correlation, str(e))
    return render_template("errors/500.html"), 500

if __name__ == "__main__":
    app.run() #debug=True
