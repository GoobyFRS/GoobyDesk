#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import logging
import os
import uuid

from datetime import datetime
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, session, Response, current_app, flash
from markupsafe import escape
from local_handlers.utils import resolve_preferred_name
from local_handlers.auth_decorators import role_required, ROLE_ITSM_TECH
from storage.crm_store import CrmStore
from local_handlers.crm_helpers import build_customer_record
from local_handlers.validation import require_fields, is_valid_email

logger = logging.getLogger(__name__)
crm_module_bp = Blueprint('crm_module', __name__, url_prefix='/crm')

# NOTE: use @role_required(ROLE_ITSM_TECH) on routes requiring ITSM technicians

def _get_crm_store():
    """Return a CrmStore instance using loaded config or legacy loader."""
    core_cfg = current_app.config.get("LOADED_CONFIG")
    if core_cfg is None:
        logger.debug("CRM MODULE - No config loaded; falling back to legacy loader")
        from local_handlers.local_config_loader import load_core_config
        core_cfg = load_core_config()
    customers_file = core_cfg["core"]["customers_file"]
    logger.debug("CRM MODULE - Opening CRM store for file=%s", customers_file)
    return CrmStore(customers_file)

def load_customers_file():
    """Load and return all customer records from the CRM store."""
    store = _get_crm_store()
    customers = store.load_all()
    logger.debug("CRM MODULE - Loaded %s customer records", len(customers))
    return customers

def save_customers_file(customers):
    """Persist the full customers list to the CRM store."""
    store = _get_crm_store()
    store.save_all(customers)
    logger.debug("CRM MODULE - Persisted %s customer records", len(customers))

def _pseudonymize_actor(name: str) -> str:
    """Return a stable pseudonym for a username for logging."""
    if not name:
        return "actor_unknown"
    normalized_name = str(name).strip()
    if not normalized_name:
        return "actor_unknown"
    salt = os.getenv("LOG_SALT", "")
    short_hash = hashlib.sha256((normalized_name + salt).encode("utf-8")).hexdigest()[:8]
    return f"actor_{short_hash}"

def generate_customer_id(customers):
    """Return next customer identifier (CID) for this year."""
    store = _get_crm_store()
    customer_id = store.next_customer_id(customers)
    logger.debug("CRM MODULE - Generated next customer ID=%s", customer_id)
    return customer_id

def _find_customer_by_uuid(customers: list, customer_uuid: str):
    """Find a customer by `uuid` in the provided list, or None."""
    for cust in customers:
        if cust.get("uuid") == customer_uuid:
            return cust
    logger.debug("CRM MODULE - Customer lookup miss for uuid=%s", customer_uuid)
    return None

def _clean_form_value(form: dict, field_name: str):
    """Trim and return a form value, or None if empty/missing."""
    raw_value = form.get(field_name)
    if raw_value is None:
        return None
    cleaned = raw_value.strip()
    return cleaned or None

def _update_customer_record(customer: dict, form: dict) -> None:
    """Apply cleaned form values onto an existing customer record in-place."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.debug("CRM MODULE - Updating customer record uuid=%s", customer.get("uuid"))

    customer["first_name"] = _clean_form_value(form, "first_name") or customer.get("first_name")
    customer["last_name"] = _clean_form_value(form, "last_name") or customer.get("last_name")
    customer["preferred_name"] = _clean_form_value(form, "preferred_name") or customer.get("first_name")
    email = _clean_form_value(form, "email")
    customer["email"] = email.lower() if email else customer.get("email")

    customer["phone"] = _clean_form_value(form, "phone") or customer.get("phone")
    customer["country"] = _clean_form_value(form, "country") or customer.get("country")
    customer["timezone"] = _clean_form_value(form, "timezone") or customer.get("timezone") or "UTC"
    customer["status"] = _clean_form_value(form, "status") or customer.get("status")
    customer["preferred_contact"] = _clean_form_value(form, "preferred_contact") or customer.get("preferred_contact")

    # Flags
    customer["vip"] = True if "vip" in form else False
    customer["content_creator"] = True if "content_creator" in form else False
    customer["marketing_opt_in"] = True if "marketing_opt_in" in form else False
    customer["maintenance_notifications"] = True if "maintenance_notifications" in form else False

    # Discord / Minecraft
    discord = customer.setdefault("discord", {})
    discord["username"] = _clean_form_value(form, "discord_username") or discord.get("username")
    minecraft = customer.setdefault("minecraft", {})
    minecraft["username"] = _clean_form_value(form, "minecraft_username") or minecraft.get("username")

    # Audit
    audit = customer.setdefault("audit", {})
    audit["last_modified"] = now
    audit["last_modified_by"] = resolve_preferred_name(session.get("technician"))
    customer["updated"] = now

    # Optional advanced fields
    # Company / Job title
    customer["company"] = _clean_form_value(form, "company") or customer.get("company")
    customer["job_title"] = _clean_form_value(form, "job_title") or customer.get("job_title")

    # Address fields
    address = customer.setdefault("address", {})
    address["street"] = _clean_form_value(form, "street") or address.get("street")
    address["city"] = _clean_form_value(form, "city") or address.get("city")
    address["state"] = _clean_form_value(form, "state") or address.get("state")
    address["postal_code"] = _clean_form_value(form, "postal_code") or address.get("postal_code")

    # Account flags
    customer["email_verified"] = True if form.get("email_verified") else False
    customer["account_locked"] = True if form.get("account_locked") else False
    customer["mfa_enabled"] = True if form.get("mfa_enabled") else False

    # Financial / billing
    lv = _clean_form_value(form, "lifetime_value")
    try:
        customer["lifetime_value"] = float(lv) if lv is not None else customer.get("lifetime_value", 0.0)
    except ValueError:
        # keep existing on parse error
        pass
    customer["billing_currency"] = _clean_form_value(form, "billing_currency") or customer.get("billing_currency")

    # Assigned manager
    customer["assigned_account_manager"] = _clean_form_value(form, "assigned_account_manager") or customer.get("assigned_account_manager")

    # Lists: services and account tags (comma-separated input)
    services_val = _clean_form_value(form, "services")
    if services_val is not None:
        customer["services"] = [
            service_name.strip() for service_name in services_val.split(",") if service_name.strip()
        ]

    tags_val = _clean_form_value(form, "account_tags")
    if tags_val is not None:
        customer["account_tags"] = [
            tag_name.strip() for tag_name in tags_val.split(",") if tag_name.strip()
        ]

    # Support contract
    support_enabled = True if form.get("support_enabled") else False
    support_sla = _clean_form_value(form, "support_sla")
    support_expires = _clean_form_value(form, "support_expires")
    customer["support_contract"] = {
        "enabled": support_enabled,
        "sla": support_sla or customer.get("support_contract", {}).get("sla"),
        "expires": support_expires or customer.get("support_contract", {}).get("expires"),
    }

# Dashboard Route
@crm_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def crm_dashboard():
    """Render CRM dashboard showing active customers and stats."""
    actor = resolve_preferred_name(session.get("technician"))
    show_all = request.args.get("show_all") == "1"
    customers = load_customers_file()
    total_customers = len(customers)
    active_customers_list = [customer for customer in customers if customer.get("status") == "active"]
    displayed_customers = customers if show_all else active_customers_list
    vip_customers = sum(1 for customer in customers if customer.get("vip") is True)
    total_lifetime_value = sum(customer.get("lifetime_value", 0) for customer in customers)
    crm_base_stats = {
        "total_customers": total_customers,
        "active_customers": len(active_customers_list),
        "vip_customers": vip_customers,
        "total_lifetime_value": total_lifetime_value,
    }
    logger.info(
        "CRM MODULE - Dashboard loaded actor=%s total_customers=%s active_customers=%s show_all=%s",
        _pseudonymize_actor(actor),
        total_customers,
        len(active_customers_list),
        show_all,
    )
    return render_template(
        "crm/crm_dashboard.html",
        customers=displayed_customers,
        loggedInTech=actor,
        stats=crm_base_stats,
        show_all=show_all,
    )

# Create New Customer Route
@crm_module_bp.route("/submit-new", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def new_customer():
    """Render creation form (GET) and create a new customer (POST)."""
    actor = resolve_preferred_name(session.get("technician"))
    if request.method == "GET":
        logger.info("CRM MODULE - Customer create form opened actor=%s", _pseudonymize_actor(actor))
        return render_template("crm/submit_new.html")

    form = {key: value for key, value in request.form.items()}

    ok, missing = require_fields(form, ["first_name", "last_name", "email"])
    if not ok or not is_valid_email(form.get("email")):
        logger.warning(
            "CRM MODULE - Customer creation rejected actor=%s reason=invalid_fields missing=%s",
            _pseudonymize_actor(actor),
            missing,
        )
        return render_template(
            "crm/submit_new.html",
            error="First Name, Last Name, and a valid Email are required."
        ), 400

    customers = load_customers_file()
    submission_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build base record from the form
    base = build_customer_record(form)
    # Enrich with persistence/audit fields
    new_customer_record = {
        "uuid": str(uuid.uuid4()),
        "customer_id": generate_customer_id(customers),
        **base,
        "created": submission_timestamp,
        "created_by": resolve_preferred_name(session.get("technician")),
        "audit": {
            "creation_source": "auth_web",
            "last_modified": submission_timestamp,
            "last_modified_by": resolve_preferred_name(session.get("technician")),
        },
    }

    # Apply any additional fields present on the creation form
    _update_customer_record(new_customer_record, form)

    initial_note = form.get("crm_worknotes", "").strip()
    if initial_note:
        new_customer_record["crm_worknotes"].append({
            "date": submission_timestamp,
            "created_by": resolve_preferred_name(session.get("technician")),
            "note": initial_note,
        })

    customers.append(new_customer_record)
    save_customers_file(customers)
    actor = _pseudonymize_actor(session.get('technician'))
    logger.info("CRM MODULE - Customer %s created actor=%s", new_customer_record['customer_id'], actor)

    return redirect(url_for("crm_module.customer_profile", uuid=new_customer_record["uuid"]))

# View Customer Details Route
@crm_module_bp.route("/profile/<uuid>", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def customer_profile(uuid):
    """Show a single customer's profile by `uuid`."""
    actor = resolve_preferred_name(session.get("technician"))
    customers = load_customers_file()
    customer = next((cust for cust in customers if cust["uuid"] == uuid), None)
    if not customer:
        logger.warning("CRM MODULE - Customer profile lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404

    linked_services = []
    try:
        from blueprints.serviceid_module import _get_service_appid_store
        linked_services = [
            service for service in _get_service_appid_store().load_all()
            if str(service.get("customer_uuid") or "") == str(uuid)
        ]
    except Exception:
        logger.exception("CRM MODULE - Failed to load linked services for customer_uuid=%s", uuid)

    logger.info(
        "CRM MODULE - Customer profile viewed actor=%s customer_id=%s uuid=%s linked_services=%s",
        _pseudonymize_actor(actor),
        customer.get("customer_id"),
        uuid,
        len(linked_services),
    )
    return render_template(
        "crm/profile.html",
        customer=customer,
        linked_services=linked_services,
        loggedInTech=actor,
    )

@crm_module_bp.route("/customer/<uuid>/append_note", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def add_customer_note(uuid):
    """Append a single worknote to a customer record."""
    actor = resolve_preferred_name(session.get("technician"))
    note_content = (request.form.get("note_content") or "").strip()
    if not note_content:
        logger.warning("CRM MODULE - Empty customer note rejected actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return ("", 400)

    customers = load_customers_file()
    found = False
    note_record = {
        "created_by": actor or "unknown",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": note_content,
    }

    for cust in customers:
        if cust.get("uuid") == uuid:
            cust.setdefault("crm_worknotes", [])
            cust["crm_worknotes"].append(note_record)
            found = True
            break

    if not found:
        logger.warning("CRM MODULE - Customer note append failed actor=%s uuid=%s reason=customer_not_found", _pseudonymize_actor(actor), uuid)
        return ("Customer not found.", 404)

    save_customers_file(customers)
    logger.info("CRM MODULE - Customer note added actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
    response_note = dict(note_record)
    response_note["note"] = escape(response_note.get("note", ""))
    return ({"message": "Note added successfully.", "note": response_note}, 200)

@crm_module_bp.route("/customer/<uuid>/edit", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def edit_customer(uuid):
    """Render edit form (GET) and apply updates to an existing customer (POST)."""
    actor = resolve_preferred_name(session.get("technician"))
    customers = load_customers_file()
    customer = _find_customer_by_uuid(customers, uuid)
    if customer is None:
        logger.warning("CRM MODULE - Customer edit lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        logger.info("CRM MODULE - Customer edit form opened actor=%s customer_id=%s uuid=%s", _pseudonymize_actor(actor), customer.get("customer_id"), uuid)
        return render_template("crm/submit_new.html", customer=customer, loggedInTech=actor)

    form = {key: value for key, value in request.form.items()}
    ok, _missing = require_fields(form, ["first_name", "last_name", "email"])
    if not ok or not is_valid_email(form.get("email")):
        logger.warning(
            "CRM MODULE - Customer update rejected actor=%s customer_id=%s reason=invalid_fields",
            _pseudonymize_actor(actor),
            customer.get("customer_id"),
        )
        return render_template("crm/submit_new.html",customer=customer,
            error="First Name, Last Name, and a valid Email are required.",
            loggedInTech=actor,), 400

    _update_customer_record(customer, form)

    note_text = (form.get("crm_worknotes") or "").strip()
    if note_text:
        note = {"date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "created_by": actor, "note": note_text}
        customer.setdefault("crm_worknotes", []).append(note)

    save_customers_file(customers)
    flash(f"Customer {customer.get('customer_id', uuid)} updated.", "success")
    actor_label = _pseudonymize_actor(actor)
    logger.info("CRM MODULE - Customer %s edited actor=%s", customer.get('customer_id'), actor_label)
    return redirect(url_for("crm_module.customer_profile", uuid=customer["uuid"]))


def _serialize_customer_value(value):
    """Convert nested customer data to CSV-safe values."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


@crm_module_bp.route("/export/csv", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def export_customers_csv():
    """Export all customer records to a timestamped CSV file."""
    customers = load_customers_file()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"customers_{timestamp}.csv"

    fieldnames = [
        "customer_id",
        "uuid",
        "first_name",
        "last_name",
        "preferred_name",
        "company",
        "job_title",
        "email",
        "phone",
        "status",
        "country",
        "timezone",
        "created",
        "updated",
    ]

    for customer in customers:
        for key, value in customer.items():
            if isinstance(value, dict):
                for nested_key in value.keys():
                    nested_name = f"{key}.{nested_key}"
                    if nested_name not in fieldnames:
                        fieldnames.append(nested_name)
            elif key not in fieldnames:
                fieldnames.append(key)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for customer in customers:
        row = {}
        for key, value in customer.items():
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    row[f"{key}.{nested_key}"] = _serialize_customer_value(nested_value)
            else:
                row[key] = _serialize_customer_value(value)
        writer.writerow({field: row.get(field, "") for field in fieldnames})

    output.seek(0)
    logger.info("CRM MODULE - Exported %s customer records to CSV actor=%s", len(customers), _pseudonymize_actor(resolve_preferred_name(session.get("technician"))))
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
