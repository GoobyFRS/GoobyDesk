#!/usr/bin/env python3
import io
import csv
import logging
import hashlib
import os
from datetime import datetime

from flask import Blueprint, Response, redirect, render_template, request, session, url_for, current_app
from local_handlers.utils import resolve_preferred_name
from local_handlers.auth_decorators import role_required, ROLE_ITSM_TECH
from storage.changes_store import ChangesStore

# Blueprint
changes_module_bp = Blueprint("changes_module", __name__, url_prefix="/changes")

def _get_config():
    """Return loaded app config or fallback loader."""
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        from local_handlers.local_config_loader import load_core_config
        cfg = load_core_config()
    return cfg

def _get_changes_store():
    """Return a ChangesStore instance from loaded config."""
    cfg = _get_config()
    return ChangesStore(cfg["core"]["changes_file"])

def load_changes():
    """Return change records sorted by newest first."""
    store = _get_changes_store()
    return sorted(store.load_all(), key=_change_sort_key, reverse=True)

def _change_sort_key(change: dict) -> datetime:
    timestamp = change.get("change_created_timestamp")
    if isinstance(timestamp, str):
        try:
            return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.min
    return datetime.min

def _pseudonymize_actor(name: str) -> str:
    if not name:
        return "actor_unknown"
    salt = os.getenv("LOG_SALT", "")
    short_hash = hashlib.sha256((str(name) + salt).encode()).hexdigest()[:8]
    return f"actor_{short_hash}"

def _parse_datetime_local(value: str) -> str | None:
    """Parse ISO-like local datetime strings to normalized format or None."""
    value = (value or "").strip()
    if not value:
        return None

    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

def _clean_optional_timestamp(form_data, field_name: str) -> str:
    """Normalize an optional timestamp field from form data."""
    raw_value = form_data.get(field_name, "").strip()
    parsed_value = _parse_datetime_local(raw_value)
    return parsed_value or raw_value

def _build_change_record(form_data) -> dict:
    """Build a normalized change record from submitted form data."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    requestor = resolve_preferred_name(session.get("technician"))

    # Use store to generate a sequential change number
    store = _get_changes_store()
    change_number = store.next_change_number()

    record = {
        "change_number": change_number,
        "change_short_description": form_data.get("change_short_description", "").strip(),
        "change_description": form_data.get("change_description", "").strip(),
        "implement_plan": form_data.get("implement_plan", "").strip(),
        "test_accept_plan": form_data.get("test_accept_plan", "").strip(),
        "rollback_plan": form_data.get("rollback_plan", "").strip(),
        "planned_start_timestamp": _clean_optional_timestamp(form_data, "planned_start_timestamp"),
        "planned_end_timestamp": _clean_optional_timestamp(form_data, "planned_end_timestamp"),
        "requestor_id": requestor,
        "requestor_uuid": None,
        "implementor_id": None,
        "implementor_uuid": None,
        "impacted_service_id": None,
        "impacted_service_uuid": None,
        "change_created_timestamp": now,
        "change_updated_timestamp": now,
        "change_status": "pending",
        "change_risk": form_data.get("change_risk", "Medium").strip().capitalize(),
    }

    return record

# Dashboard Route
@changes_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def changes_home():
    """Render the change dashboard."""
    changes = load_changes()
    return render_template("changes/changes_dashboard.html", changes=changes, loggedInTech=resolve_preferred_name(session.get("technician")))

# Submit New Change Route
@changes_module_bp.route("/submit-new", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def submit_new() -> str:
    """Create a new change request."""
    if request.method == "GET":
        return render_template("changes/submit_new.html", loggedInTech=resolve_preferred_name(session.get("technician")))

    required_fields = {
        "change_short_description": "Short description is required.",
        "implement_plan": "Implement plan is required.",
        "test_accept_plan": "Test plan is required.",
        "rollback_plan": "Rollback plan is required.",
        "planned_start_timestamp": "Planned start date/time is required.",
        "planned_end_timestamp": "Planned end date/time is required.",
    }

    errors = []
    for field_name, message in required_fields.items():
        if not request.form.get(field_name, "").strip():
            errors.append(message)

    start_value = request.form.get("planned_start_timestamp", "").strip()
    end_value = request.form.get("planned_end_timestamp", "").strip()
    start_timestamp = _parse_datetime_local(start_value)
    end_timestamp = _parse_datetime_local(end_value)
    if start_value and not start_timestamp:
        errors.append("Planned start date/time must be valid.")
    if end_value and not end_timestamp:
        errors.append("Planned end date/time must be valid.")
    if start_timestamp and end_timestamp and end_timestamp <= start_timestamp:
        errors.append("Planned end date/time must be after the start date/time.")

    if errors:
        return render_template(
            "changes/submit_new.html",error=" ".join(errors),
            loggedInTech=resolve_preferred_name(session.get("technician")),
            form_values=request.form,
        ), 400

    new_change = _build_change_record(request.form)
    store = _get_changes_store()
    store.append(new_change)
    actor = _pseudonymize_actor(resolve_preferred_name(session.get("technician")))
    logging.info(
        "CHANGES MODULE - Created change %s actor=%s",
        new_change["change_number"],
        actor,
    )
    return redirect(url_for("changes_module.changes_home"))

# Export open change tickets as CSV.
@changes_module_bp.route("/export/csv", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def export_changes_csv():
    """Export change records as CSV."""
    open_changes = load_changes()

    output = io.StringIO()
    writer = csv.writer(output)

    # CSV Header
    writer.writerow([
        "Change Number",
        "Short Description",
        "Status",
        "Requestor",
        "Created",
        "Start",
        "End",
    ])

    for change in open_changes:
        writer.writerow([
            change.get("change_number"),
            change.get("change_short_description"),
            change.get("change_status"),
            change.get("requestor_id"),
            change.get("change_created_timestamp"),
            change.get("planned_start_timestamp"),
            change.get("planned_end_timestamp"),
        ])

    output.seek(0)

    logging.info(
        "CHANGES MODULE - Exported %s change tickets to CSV",
        len(open_changes),
    )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=open_changes.csv"
        },
    )
