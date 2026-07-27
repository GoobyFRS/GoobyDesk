#!/usr/bin/env python3
"""HR module blueprint for GoobyDesk.
Provides the HR dashboard and its supporting employee-data helpers.
"""
import logging
import secrets
import re
import uuid
import hashlib
import os
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from local_handlers.auth_decorators import ROLE_ADMIN, ROLE_HR_TECH, role_required
from local_handlers.local_config_loader import load_core_config
from local_handlers.utils import hash_password, resolve_preferred_name
from local_handlers.validation import is_valid_email, require_fields
from storage.employee_store import EmployeeStore
from storage.hr_store import HrStore

AUTH_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
HR_ROLE_MAP = {
    "itsm_technician": {"roles": ["itsm_technician"], "role": "itsm_technician"},
    "hr_technician": {"roles": ["hr_technician"], "role": "hr_technician"},
    "manager": {"roles": ["manager"], "role": "manager"},
    "admin": {"roles": ["admin"], "role": "admin"},
}

def _get_config():
    """Return loaded app config or fallback loader."""
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        cfg = load_core_config()
    return cfg

def _get_hr_store():
    """Return an HrStore instance from loaded config."""
    cfg = _get_config()
    return HrStore(cfg["core"]["hr_file"])

def _get_employee_store():
    """Return an EmployeeStore instance from loaded config."""
    cfg = _get_config()
    return EmployeeStore(cfg["core"]["employee_auth_file"])

def _build_timestamp() -> str:
    """Return current UTC timestamp in ISO-like format."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

def _next_employee_sequence(employees: list[dict], year: int) -> int:
    """Compute next employee sequence number for given year."""
    existing_ids = [
        employee.get("employee_id", "")
        for employee in employees
        if isinstance(employee.get("employee_id", ""), str)
        and employee.get("employee_id", "").startswith(f"EMP-{year}-")
    ]
    sequence_numbers = []
    for employee_id in existing_ids:
        suffix = employee_id.rsplit("-", maxsplit=1)[-1]
        if suffix.isdigit():
            sequence_numbers.append(int(suffix))

    if not sequence_numbers:
        return 1
    return max(sequence_numbers) + 1

def _build_employment_details(form: dict, created_date: str) -> dict:
    """Construct the employment details sub-dictionary for an employee."""
    status = form.get("status") or "active"
    return {
        "hire_date": created_date,
        "termination_date": None,
        "status": status,
        "rehire_eligible": True,
        "title": form.get("title") or "",
        "business_unit": form.get("business_unit") or "",
        "department": form.get("department") or "",
        "reports_to": None,
        "employment_type": form.get("employment_type") or "full_time",
        "compensation_type": form.get("compensation_type") or "salary",
        "salary": form.get("salary") or None,
        "hourly_rate": form.get("hourly_rate") or None,
        "pay_frequency": form.get("pay_frequency") or None,
        "direct_deposit_info": form.get("direct_deposit_info") or None,
        "equity": {"notes": form.get("equity")} if form.get("equity") else {},
        "bonus_history": [],
        "raise_history": [],
        "salary_exempt": True,
        "bonus_eligible": False,
        "bonus_rate": 0.0,
        "pto_available_hours": 0,
        "pto_used_hours": 0,
    }

def _normalize_username(username: str) -> str:
    """Trim a login username before validation."""
    return username.strip()

def _validate_auth_username(username: str) -> None:
    """Reject login usernames that do not match the allowed format."""
    if not AUTH_USERNAME_RE.fullmatch(username):
        raise ValueError("Login username must be 3-32 characters using letters, digits, '_' or '-'.")

def _map_hr_role_to_auth_payload(role: str) -> tuple[list[str], str]:
    """Map one HR role to auth-store roles and role."""
    normalized_role = (role or "").strip().lower()
    mapped = HR_ROLE_MAP.get(normalized_role)
    if mapped is None:
        raise ValueError("Invalid access role selected.")
    return mapped["roles"], mapped["role"]

def _find_auth_employee_by_uuid(employees: list[dict], employee_uuid: str) -> dict | None:
    """Return the auth record that already points at this employee UUID."""
    for employee in employees:
        if employee.get("uuid") == employee_uuid:
            return employee
    return None

def _find_auth_employee_by_username(employees: list[dict], username: str) -> dict | None:
    """Return the auth record that already uses this username."""
    lowered_username = username.lower()
    for employee in employees:
        if str(employee.get("tech_username", "")).lower() == lowered_username:
            return employee
    return None

def _derive_auth_username(employee_id: str, override_username: str | None, auth_employees: list[dict]) -> str:
    """Pick a unique login username for a new employee."""
    candidate_username = _normalize_username(override_username or employee_id)
    _validate_auth_username(candidate_username)
    if _find_auth_employee_by_username(auth_employees, candidate_username) is not None:
        raise ValueError("Login username already exists.")
    return candidate_username

def _build_employee_auth_record(employee_record: dict, auth_username: str, temporary_password: str) -> dict:
    """Build the auth-store record for a newly created employee."""
    auth_roles, auth_role = _map_hr_role_to_auth_payload(employee_record.get("access", {}).get("role", ""))
    now = _build_timestamp()
    return {
        "uuid": employee_record["uuid"],
        "tech_username": auth_username,
        "password_hash": hash_password(temporary_password),
        "roles": auth_roles,
        "role": auth_role,
        "account_locked": False,
        "must_change_password": False,
        "created": now,
        "updated": now,
    }

def _build_employee_access(form: dict, auth_username: str | None, create_login_access: bool) -> dict:
    """Build the access block stored in the HR record."""
    return {
        "role": form.get("role") or "itsm_technician",
        "assignment_queue": form.get("assignment_queue") or "support",
        "account_locked": False,
        "mfa_enabled": False,
        "last_login": None,
        "password_last_changed": None,
        "failed_login_attempts": 0,
        "login_enabled": create_login_access,
        "auth_username": auth_username,
        "provisioning_status": "pending" if create_login_access else "disabled",
    }

def _build_employee_record(form: dict, employees: list[dict]) -> tuple[dict, str]:
    now = _build_timestamp()
    current_year = datetime.now().year
    employee_sequence = _next_employee_sequence(employees, current_year)
    employee_id = f"EMP-{current_year}-{employee_sequence:04d}"

    new_record = {
        "uuid": str(uuid.uuid4()),
        "employee_id": employee_id,
        "first_name": form.get("first_name"),
        "last_name": form.get("last_name"),
        "preferred_name": form.get("preferred_name") or form.get("first_name"),
        "email": form.get("email"),
        "date_of_birth": form.get("date_of_birth"),
        "work_authorization": form.get("work_authorization"),
        "address": {
            "street": form.get("street") or None,
            "city": form.get("city") or None,
            "state": form.get("state") or None,
            "postal_code": form.get("postal_code") or None,
            "country": form.get("country") or None,
        },
        "phone": form.get("phone"),
        "timezone": form.get("timezone") or "UTC",
        "employment": _build_employment_details(form, now.split("T")[0]),
        "hr_worknotes": [],
        "access": _build_employee_access(form, None, False),
        "applications": {},
        "contact_preferences": {
            "preferred_contact": "email",
            "maintenance_notifications": True,
        },
        "emergency_contact": {"name": None, "relationship": None, "phone": None},
        "certifications": [],
        "skills": [],
        "created": now,
        "created_by": resolve_preferred_name(session.get("technician")),
        "audit": {
            "creation_source": "auth_web",
            "last_modified": now,
            "last_modified_by": resolve_preferred_name(session.get("technician")),
        },
        "updated": now,
    }
    return new_record, employee_id

def _append_initial_compensation_history(employee_record: dict, form: dict, created_at: str) -> None:
    """Append initial compensation notes (bonus/raise) to employee record."""
    created_date = created_at.split("T")[0]
    initial_bonus = form.get("initial_bonus")
    if initial_bonus:
        employee_record["employment"]["bonus_history"].append(
            {"date": created_date, "note": initial_bonus}
        )

    initial_raise = form.get("initial_raise")
    if initial_raise:
        employee_record["employment"]["raise_history"].append(
            {"date": created_date, "note": initial_raise})

def _find_employee_by_uuid(employees: list[dict], employee_uuid: str) -> dict | None:
    """Find and return an employee record by its UUID, or None."""
    for employee in employees:
        if employee.get("uuid") == employee_uuid:
            return employee
    return None

def _clean_form_value(form: dict, field_name: str) -> str | None:
    """Trim a string form value and return None if empty/missing."""
    value = form.get(field_name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None

def _update_employee_record(employee: dict, form: dict) -> None:
    """Apply cleaned form values to an employee record in-place."""
    now = _build_timestamp()
    address = employee.setdefault("address", {})
    employment = employee.setdefault("employment", {})

    first_name = _clean_form_value(form, "first_name")
    last_name = _clean_form_value(form, "last_name")
    preferred_name = _clean_form_value(form, "preferred_name")
    email = _clean_form_value(form, "email")

    employee["first_name"] = first_name
    employee["last_name"] = last_name
    employee["preferred_name"] = preferred_name or first_name
    employee["email"] = email
    employee["date_of_birth"] = _clean_form_value(form, "date_of_birth")
    employee["work_authorization"] = _clean_form_value(form, "work_authorization")
    employee["phone"] = _clean_form_value(form, "phone")
    employee["timezone"] = _clean_form_value(form, "timezone") or "UTC"

    address["street"] = _clean_form_value(form, "street")
    address["city"] = _clean_form_value(form, "city")
    address["state"] = _clean_form_value(form, "state")
    address["postal_code"] = _clean_form_value(form, "postal_code")
    address["country"] = _clean_form_value(form, "country")

    employment["title"] = _clean_form_value(form, "title") or ""
    employment["business_unit"] = _clean_form_value(form, "business_unit") or ""
    employment["department"] = _clean_form_value(form, "department") or ""
    employment["status"] = _clean_form_value(form, "status") or "active"
    employment["employment_type"] = _clean_form_value(form, "employment_type") or "full_time"
    employment["compensation_type"] = _clean_form_value(form, "compensation_type") or "salary"
    employment["salary"] = _clean_form_value(form, "salary")
    employment["hourly_rate"] = _clean_form_value(form, "hourly_rate")
    employment["pay_frequency"] = _clean_form_value(form, "pay_frequency")
    employment["direct_deposit_info"] = _clean_form_value(form, "direct_deposit_info")

    equity_notes = _clean_form_value(form, "equity")
    employment["equity"] = {"notes": equity_notes} if equity_notes else {}
    employee["updated"] = now
    audit = employee.setdefault("audit", {})
    audit["last_modified"] = now
    audit["last_modified_by"] = resolve_preferred_name(session.get("technician"))

def _provision_employee_login_access(
    employee_record: dict,
    auth_employees: list[dict],
    override_username: str | None,
) -> tuple[dict, str]:
    """Create the auth-store record and one-time password for an employee."""
    if _find_auth_employee_by_uuid(auth_employees, employee_record["uuid"]) is not None:
        raise ValueError("Auth record already exists for this employee.")
    auth_username = _derive_auth_username(employee_record["employee_id"], override_username, auth_employees)
    temporary_password = secrets.token_urlsafe(9)
    auth_record = _build_employee_auth_record(employee_record, auth_username, temporary_password)

    access_block = employee_record.setdefault("access", {})
    access_block["auth_username"] = auth_username
    access_block["login_enabled"] = True
    access_block["provisioning_status"] = "pending"
    access_block["account_locked"] = False

    return auth_record, temporary_password

hr_module_bp = Blueprint("hr_module", __name__, url_prefix="/hr")

CERT_EXPIRY_WARNING_DAYS = 90  # Certifications expiring within this window are flagged.

# NOTE: HR routes should require HR technician role; use `@role_required(ROLE_HR_TECH)`

def load_hr_employees() -> list[dict]:
    """Load the employee roster from the HR JSON database.
    Returns:
        A list of employee records.
    Raises:
        SystemExit: If the HR database file cannot be found. This
            mirrors the fail-fast behavior used for other core data
            files (e.g. ``load_tickets`` in app.py).
    """
    store = _get_hr_store()
    return store.load_all()

def _is_cert_expiring(expires: str | None, within_days: int) -> bool:
    """Check whether a certification expiry date falls within a window.
    Args:
        expires: An ISO ``YYYY-MM-DD`` date string, or None.
        within_days: How many days out from today counts as "soon".
    Returns:
        True if the certification expires between now and the given
        number of days from now. Malformed or missing dates are
        treated as not expiring, with a warning logged for the former.
    """
    if not expires:
        return False
    try:
        expiry_date = datetime.strptime(expires, "%Y-%m-%d")
    except ValueError:
        logging.warning("Unparseable certification expiry date provided; parsing failed.")
        return False
    return datetime.now() <= expiry_date <= datetime.now() + timedelta(days=within_days)

def build_hr_stats(employees: list[dict]) -> dict:
    """Compute summary statistics for the HR dashboard.
    Args:
        employees: The full employee roster.
    Returns:
        A dictionary of aggregate counts consumed by the dashboard
        template's stat cards.
    """
    active_employees = sum( 1 for emp in employees if emp.get("employment", {}).get("status") == "active" )
    locked_accounts = sum( 1 for emp in employees if emp.get("access", {}).get("account_locked"))
    expiring_certs = sum( 1 for emp in employees
        for cert in emp.get("certifications", [])
        if _is_cert_expiring(cert.get("expires"), CERT_EXPIRY_WARNING_DAYS))
    return {
        "total_employees": len(employees),
        "active_employees": active_employees,
        "locked_accounts": locked_accounts,
        "expiring_certs": expiring_certs,
    }

def _pseudonymize_actor(name: str) -> str:
    """Create a short, stable actor id for logs instead of raw usernames."""
    if not name:
        return "actor_unknown"
    salt = os.getenv("LOG_SALT", "")
    short_hash = hashlib.sha256((str(name) + salt).encode()).hexdigest()[:8]
    return f"actor_{short_hash}"
# Dashboard Route
@hr_module_bp.route("/", methods=["GET"])
@role_required(ROLE_HR_TECH)
def hr_dashboard():
    """Render the HR dashboard listing all employees and summary stats.
    Returns:
        The rendered HR dashboard template.
    """
    employees = load_hr_employees()
    stats = build_hr_stats(employees)
    return render_template("hr/hr_dashboard.html", employees=employees, stats=stats, loggedInTech=resolve_preferred_name(session.get("technician")))

# View Employee Details Route
@hr_module_bp.route("/employee/<uuid>", methods=["GET"])
@role_required(ROLE_HR_TECH)
def employee_profile(uuid: str):
    """Render a single employee's profile page.
    Args:
        uuid: The employee's unique identifier.
    Returns:
        The rendered employee profile page, or a 404 error page if no
        employee matches the given uuid.
    Note:
        The profile template itself hasn't been built yet, so this
        currently falls back to under_construction.html once the
        employee is found. Swap in "hr/employee_profile.html" when
        that template exists.
    """
    employees = load_hr_employees()
    employee = _find_employee_by_uuid(employees, uuid)
    if employee is None:
        return render_template("errors/404.html"), 404
    return render_template("hr/profile.html", employee=employee, loggedInTech=resolve_preferred_name(session.get("technician")))

@hr_module_bp.route("/employee/<uuid>/edit", methods=["GET", "POST"])
@role_required(ROLE_HR_TECH)
def edit_employee(uuid: str):
    """Render and process edits for an existing employee record."""
    store = _get_hr_store()
    employees = store.load_all()
    employee = _find_employee_by_uuid(employees, uuid)
    if employee is None:
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        return render_template("hr/submit_new.html", employee=employee, loggedInTech=resolve_preferred_name(session.get("technician")))

    form = {key: value for key, value in request.form.items()}
    ok, _missing = require_fields(form, ["first_name", "last_name", "email"])
    if not ok or not is_valid_email(form.get("email")):
            return render_template("hr/submit_new.html",employee=employee, error="First Name, Last Name, and a valid Email are required.",
            loggedInTech=resolve_preferred_name(session.get("technician")),), 400

    _update_employee_record(employee, form)
    store.save_all(employees)
    flash(f"Employee {employee.get('employee_id', uuid)} updated.", "success")
    return redirect(url_for("hr_module.employee_profile", uuid=employee["uuid"]))

@hr_module_bp.route("/employee/<uuid>/reset-password", methods=["POST"])
@role_required(ROLE_ADMIN)
def reset_employee_password(uuid: str):
    """Admin action: reset an employee's password and return the new password once."""
    store = _get_employee_store()
    employees = store.load_all()
    employee = next((emp for emp in employees if emp.get("uuid") == uuid), None)
    if employee is None:
        return render_template("errors/404.html"), 404

    # Generate a short-lived one-time password to show to the admin
    new_password = secrets.token_urlsafe(9)  # ~12 chars, URL-safe
    # Hash the password for storage
    hashed = hash_password(new_password)

    # Update the employee record
    employee["password_hash"] = hashed
    if "tech_authcode" in employee:
        del employee["tech_authcode"]
    employee["password_reset_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    store.save_all(employees)
    actor = _pseudonymize_actor(resolve_preferred_name(session.get("technician")))
    logging.warning(
        "HR MODULE - Password reset performed; actor=%s target_employee_id=%s",
        actor, employee.get("employee_id"))

    # Show password once to admin via template variable and flash
    flash("Password reset successful - show it once below.", "success")
    return render_template("hr/profile.html", employee=employee, reset_password=new_password, loggedInTech=resolve_preferred_name(session.get("technician")))

@hr_module_bp.route("/employee/<uuid>/append_note", methods=["POST"])
@role_required(ROLE_HR_TECH)
def add_employee_note(uuid: str):
    # Restrict: only HR technicians or Administrators may add HR notes.
    roles = session.get("roles", [])
    if not (ROLE_HR_TECH in roles or ROLE_ADMIN in roles):
        return ("", 403)

    note_content = (request.form.get("note_content") or "").strip()
    if not note_content:
        return ("", 400)

    store = _get_hr_store()
    employees = store.load_all()
    found = False
    note_record = {
        "created_by": resolve_preferred_name(session.get("technician")) or "unknown",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": note_content,
    }

    for emp in employees:
        if emp.get("uuid") == uuid:
            emp.setdefault("hr_worknotes", [])
            emp["hr_worknotes"].append(note_record)
            found = True
            break

    if not found:
        return ("Employee not found.", 404)

    store.save_all(employees)
    return ({"message": "Note added successfully.", "note": note_record}, 200)

# Create New Employee Route
@hr_module_bp.route("/employee/submit-new", methods=["GET", "POST"])
@role_required(ROLE_HR_TECH)
def new_employee():
    """Render form to create a new employee and handle submissions.
    GET: render the `hr/submit_new.html` form.
    POST: validate input, append record to HR store, redirect to profile.
    """
    if request.method == "GET":
        return render_template("hr/submit_new.html")

    form = {key: value for key, value in request.form.items()}
    ok, _missing = require_fields(form, ["first_name", "last_name", "email"])
    if not ok or not is_valid_email(form.get("email")):
        return render_template("hr/submit_new.html",
            error="First Name, Last Name, and a valid Email are required.",), 400

    create_login_access = request.form.get("create_login_access") == "on"
    auth_username_override = _clean_form_value(form, "auth_username")

    hr_store = _get_hr_store()
    auth_store = _get_employee_store()

    employees = hr_store.load_all()
    auth_employees = auth_store.load_all()
    new_record, employee_id = _build_employee_record(form, employees)
    temporary_password = None
    auth_record = None

    if create_login_access:
        try:
            auth_record, temporary_password = _provision_employee_login_access(
                new_record,
                auth_employees,
                auth_username_override,
            )
        except ValueError as exc:
            return render_template("hr/submit_new.html", error=str(exc), loggedInTech=resolve_preferred_name(session.get("technician"))), 400
    else:
        new_record["access"]["login_enabled"] = False
        new_record["access"]["provisioning_status"] = "disabled"

    # Persist
    employees.append(new_record)
    _append_initial_compensation_history(new_record, form, new_record["created"])
    hr_store.save_all(employees)

    if auth_record is not None:
        try:
            auth_employees.append(auth_record)
            auth_store.save_all(auth_employees)
            new_record["access"]["provisioning_status"] = "complete"
            hr_store.save_all(employees)
        except Exception:
            logging.exception("HR MODULE - Login provisioning failed; rolling back HR record.")
            employees = [employee for employee in employees if employee.get("uuid") != new_record["uuid"]]
            hr_store.save_all(employees)
            return render_template("hr/submit_new.html", error="Employee created, but login provisioning failed.", loggedInTech=resolve_preferred_name(session.get("technician"))), 500

    if temporary_password is not None:
        flash(f"Temporary password: {temporary_password}", "success")
    else:
        flash(f"Employee {employee_id} created.", "success")

    return render_template(
        "hr/profile.html",
        employee=new_record,
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )

# Export Employee Data Route
# TODO: implement export_employees() (CSV/JSON), technician_required.
# Export Employee Data Route
