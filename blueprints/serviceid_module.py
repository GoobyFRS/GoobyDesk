#!/usr/bin/env python3
import csv
import hashlib
import io
import logging
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for
from local_handlers.utils import resolve_preferred_name
from local_handlers.auth_decorators import role_required, ROLE_ITSM_TECH

from flask import current_app
from local_handlers.local_config_loader import load_core_config
from storage.service_appid_store import ServiceAppIdStore

logger = logging.getLogger(__name__)

def _pseudonymize_actor(name: str | None) -> str:
    """Return a stable opaque actor id for logging."""
    if not name:
        return "actor_unknown"
    safe_name = str(name).strip()
    if not safe_name:
        return "actor_unknown"
    salt = os.getenv("LOG_SALT", "")
    short_hash = hashlib.sha256((safe_name + salt).encode("utf-8")).hexdigest()[:8]
    return f"actor_{short_hash}"

def _get_config():
    """Return loaded app config or fallback loader."""
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        logger.debug("SERVICEID MODULE - Falling back to legacy core config loader")
        cfg = load_core_config()
    return cfg

def _get_service_appid_store():
    """Return the configured service store instance with legacy compatibility."""
    cfg = _get_config()
    core_cfg = cfg.get("core", {})
    service_file = core_cfg.get("serviceid_file") or core_cfg.get("serviceid_appid_file")
    logger.debug("SERVICEID MODULE - Opening service store file=%s", service_file)
    return ServiceAppIdStore(service_file)

def _resolve_customer_uuid_from_id(normalized_customer_id: str) -> str:
    """Return the matching customer UUID for a customer_id when one exists."""
    if not normalized_customer_id:
        logger.debug("SERVICEID MODULE - Customer ID resolution skipped; empty input")
        return ""

    from blueprints.crm_module import load_customers_file

    customers = load_customers_file()
    for customer in customers:
        if str(customer.get("customer_id") or "") == normalized_customer_id:
            resolved_uuid = str(customer.get("uuid") or "")
            logger.debug("SERVICEID MODULE - Resolved customer_id=%s to uuid=%s", normalized_customer_id, resolved_uuid)
            return resolved_uuid

    logger.warning("SERVICEID MODULE - Unable to resolve customer_id=%s to customer_uuid", normalized_customer_id)
    return ""

def _sync_customer_service_links(service_record: dict, previous_customer_uuid: str | None = None) -> None:
    """Keep the linked customer record aligned with the service list."""
    from blueprints.crm_module import load_customers_file, save_customers_file

    service_id = str(service_record.get("service_id") or "").strip()
    if not service_id:
        logger.warning("SERVICEID MODULE - Service link sync skipped; missing service_id")
        return

    customers = load_customers_file()
    customer_uuid = str(service_record.get("customer_uuid") or "").strip()
    for customer in customers:
        customer_uuid_value = str(customer.get("uuid") or "")
        services = customer.get("services")
        if not isinstance(services, list):
            customer["services"] = []
            services = customer["services"]

        if previous_customer_uuid and customer_uuid_value == previous_customer_uuid and service_id in services:
            services.remove(service_id)

        if customer_uuid and customer_uuid_value == customer_uuid and service_id not in services:
            services.append(service_id)

    save_customers_file(customers)
    logger.debug("SERVICEID MODULE - Synced linked services for service_id=%s customer_uuid=%s", service_id, customer_uuid)


serviceid_module_bp = Blueprint("serviceid_module", __name__, url_prefix="/serviceid")

# use @role_required(ROLE_ITSM_TECH)
def load_service_appids():
    """Load and return configured service records."""
    store = _get_service_appid_store()
    services = store.load_all()
    logger.debug("SERVICEID MODULE - Loaded %s service records", len(services))
    return services

def generate_service_id(services):
    """Return the next service identifier in the SRV-YYYY-#### format."""
    current_year = datetime.now().strftime("%Y")
    highest_number = 0

    for service in services:
        service_id = str(service.get("service_id") or "")
        if not service_id:
            continue

        prefix = "SRV-" if service_id.startswith("SRV-") else "APP-" if service_id.startswith("APP-") else ""
        if not prefix:
            continue

        parts = service_id.split("-")
        if len(parts) != 3:
            continue

        try:
            candidate = int(parts[2])
        except ValueError:
            continue

        highest_number = max(highest_number, candidate)

    next_service_id = f"SRV-{current_year}-{highest_number + 1:04d}"
    logger.debug("SERVICEID MODULE - Generated service identifier=%s", next_service_id)
    return next_service_id

def _is_terminated_service(service: dict) -> bool:
    """Return True when a service record should be hidden by default."""
    service_status = str(service.get("service_status") or service.get("status") or "").strip().lower()
    if service_status == "terminated":
        return True

    terminated_timestamp = service.get("service_terminated_timestamp") or service.get("terminated")
    if terminated_timestamp in (None, "", "null", "None"):
        return False
    return True


def _first_csv_value(row: dict, *field_names: str) -> str:
    """Return the first non-empty value from a CSV row."""
    for field_name in field_names:
        raw_value = row.get(field_name)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return ""


def _parse_csv_ports(raw_value: str) -> list[int]:
    """Parse a comma-separated port list from CSV."""
    if not raw_value:
        return []

    ports = []
    for port_value in raw_value.replace(";", ",").split(","):
        cleaned_port = port_value.strip()
        if not cleaned_port:
            continue
        ports.append(int(cleaned_port))
    return ports


def _build_service_from_csv_row(service: dict, row: dict, now_timestamp: str) -> dict:
    """Return a service record updated from CSV values."""
    updated_service = dict(service)
    text_fields = {
        "cluster_id": ("cluster_id",),
        "homepage_url": ("homepage_url",),
        "management_url": ("management_url",),
        "minecraft_version": ("minecraft_version",),
        "modpack_name": ("modpack_name",),
        "node_id": ("node_id",),
        "platform": ("platform",),
        "region": ("region",),
        "server_type": ("server_type",),
        "service_ip": ("service_ip", "ip_address"),
        "service_name": ("service_name", "name"),
        "service_provision_source": ("service_provision_source",),
        "service_rcon_pwd": ("service_rcon_pwd",),
        "service_sku": ("service_sku", "sku"),
        "service_status": ("service_status", "status"),
        "service_subdomain": ("service_subdomain", "hostname"),
        "service_type": ("service_type", "type"),
        "web_server_engine": ("web_server_engine",),
        "customer_id": ("customer_id",),
        "customer_uuid": ("customer_uuid",),
    }
    int_fields = {
        "allocated_disk_gb": ("allocated_disk_gb",),
        "allocated_ram_mb": ("allocated_ram_mb",),
        "player_limit": ("player_limit",),
        "service_rcon_port": ("service_rcon_port",),
    }
    float_fields = {
        "allocated_cpu_cores": ("allocated_cpu_cores",),
    }
    timestamp_fields = {
        "service_created_timestamp": ("service_created_timestamp", "created"),
        "service_updated_timestamp": ("service_updated_timestamp", "updated"),
        "service_terminated_timestamp": ("service_terminated_timestamp", "terminated"),
    }

    for field_name, aliases in text_fields.items():
        value = _first_csv_value(row, *aliases)
        if value:
            updated_service[field_name] = value

    for field_name, aliases in int_fields.items():
        value = _first_csv_value(row, *aliases)
        if value:
            updated_service[field_name] = int(value)

    for field_name, aliases in float_fields.items():
        value = _first_csv_value(row, *aliases)
        if value:
            updated_service[field_name] = float(value)

    allocated_ports = _first_csv_value(row, "allocated_ports")
    if allocated_ports:
        updated_service["allocated_ports"] = _parse_csv_ports(allocated_ports)

    for field_name, aliases in timestamp_fields.items():
        value = _first_csv_value(row, *aliases)
        if value:
            updated_service[field_name] = value

    updated_service.setdefault("service_created_timestamp", now_timestamp)
    updated_service["service_updated_timestamp"] = _first_csv_value(row, "service_updated_timestamp", "updated") or now_timestamp

    if not _first_csv_value(row, "service_id", "app_id", "id") and not updated_service.get("service_id"):
        updated_service["service_id"] = ""

    return updated_service


@serviceid_module_bp.route("/import/csv", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def import_services_csv():
    """Import service records from a CSV upload."""
    actor = resolve_preferred_name(str(session.get("technician") or ""))
    if request.method == "GET":
        logger.info("SERVICEID MODULE - CSV import form opened actor=%s", _pseudonymize_actor(actor))
        return render_template(
            "serviceid/import_csv.html",
            loggedInTech=actor,
        )

    uploaded_file = request.files.get("csv_file")
    if uploaded_file is None or not uploaded_file.filename:
        logger.warning("SERVICEID MODULE - CSV import rejected actor=%s reason=missing_file", _pseudonymize_actor(actor))
        return render_template(
            "serviceid/import_csv.html",
            loggedInTech=actor,
            error="Choose a CSV file to import.",
        ), 400

    raw_csv = uploaded_file.stream.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw_csv))
    if not reader.fieldnames:
        logger.warning("SERVICEID MODULE - CSV import rejected actor=%s reason=missing_headers", _pseudonymize_actor(actor))
        return render_template(
            "serviceid/import_csv.html",
            loggedInTech=actor,
            error="The CSV file must include a header row.",
        ), 400

    services = load_service_appids()
    imported_count = 0
    updated_count = 0
    row_errors = []
    pending_syncs = []
    now_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for row_number, row in enumerate(reader, start=2):
        if not any(str(value).strip() for value in row.values() if value is not None):
            continue

        service_uuid = _first_csv_value(row, "uuid")
        service_id = _first_csv_value(row, "service_id", "app_id", "id")
        service = None
        previous_customer_uuid = None

        if service_uuid:
            service = next((record for record in services if str(record.get("uuid") or "") == service_uuid), None)
        if service is None and service_id:
            service = next((record for record in services if str(record.get("service_id") or record.get("app_id") or record.get("id") or "") == service_id), None)

        is_new_record = service is None
        if service is None:
            if not _first_csv_value(row, "service_name", "name"):
                row_errors.append(f"Row {row_number}: service_name is required.")
                continue

            service = {"uuid": service_uuid or str(uuid.uuid4())}
            if not service_id:
                service_id = generate_service_id(services)
            service["service_id"] = service_id
            imported_count += 1
            services.append(service)
        else:
            previous_customer_uuid = str(service.get("customer_uuid") or "").strip() or None

        try:
            updated_service = _build_service_from_csv_row(service, row, now_timestamp)
        except ValueError as exc:
            row_errors.append(f"Row {row_number}: {exc}")
            if is_new_record and service in services:
                services.remove(service)
                imported_count = max(imported_count - 1, 0)
            continue

        if not is_new_record:
            updated_count += 1

        if not updated_service.get("service_id"):
            updated_service["service_id"] = generate_service_id(services)

        if not updated_service.get("customer_uuid") and updated_service.get("customer_id"):
            updated_service["customer_uuid"] = _resolve_customer_uuid_from_id(str(updated_service.get("customer_id") or ""))

        if is_new_record:
            service.clear()
            service.update(updated_service)
        else:
            service.clear()
            service.update(updated_service)

        pending_syncs.append((service, previous_customer_uuid))

    if imported_count or updated_count:
        store = _get_service_appid_store()
        try:
            store.save_all(services)
        except Exception:
            logger.exception("SERVICEID MODULE - CSV import failed actor=%s", _pseudonymize_actor(actor))
            raise

        for service, previous_customer_uuid in pending_syncs:
            _sync_customer_service_links(service, previous_customer_uuid=previous_customer_uuid)

    logger.info(
        "SERVICEID MODULE - CSV import processed actor=%s imported=%s updated=%s errors=%s",
        _pseudonymize_actor(actor),
        imported_count,
        updated_count,
        len(row_errors),
    )
    return render_template(
        "serviceid/import_csv.html",
        loggedInTech=actor,
        imported_count=imported_count,
        updated_count=updated_count,
        row_errors=row_errors,
    )

@serviceid_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def serviceid_dashboard():
    """Render the service dashboard view."""
    actor = resolve_preferred_name(str(session.get("technician") or ""))
    show_all = request.args.get("show_all") == "1"
    services = load_service_appids()
    displayed_services = services if show_all else [
        service for service in services if not _is_terminated_service(service)
    ]
    logger.info(
        "SERVICEID MODULE - Dashboard loaded actor=%s total_services=%s visible_services=%s show_all=%s",
        _pseudonymize_actor(actor),
        len(services),
        len(displayed_services),
        show_all,)
    return render_template(
        "serviceid/dashboard.html",
        services=displayed_services,
        loggedInTech=actor,
        show_all=show_all,)

@serviceid_module_bp.route("/profile/<uuid>", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def service_profile(uuid):
    """Render the profile for a single service record."""
    actor = resolve_preferred_name(str(session.get("technician") or ""))
    services = load_service_appids()
    service = next((record for record in services if record.get("uuid") == uuid), None)
    if service is None:
        logger.warning("SERVICEID MODULE - Profile lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404
    logger.info("SERVICEID MODULE - Service profile viewed actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
    return render_template(
        "serviceid/profile.html",
        service=service,
        loggedInTech=actor,)

@serviceid_module_bp.route("/edit/<uuid>", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def edit_service(uuid):
    """Render and process the service edit form for a given record."""
    actor = resolve_preferred_name(str(session.get("technician") or ""))
    services = load_service_appids()
    service = next((record for record in services if record.get("uuid") == uuid), None)
    if service is None:
        logger.warning("SERVICEID MODULE - Edit lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        logger.info("SERVICEID MODULE - Edit form opened actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
        from blueprints.crm_module import load_customers_file
        return render_template(
            "serviceid/submit_new.html",
            service=service,
            loggedInTech=actor,
            customers=load_customers_file(),
            selected_customer_id=service.get("customer_id"),
            selected_customer_uuid=service.get("customer_uuid"),
        )

    form = request.form.to_dict()
    selected_customer_id = (form.get("customer_id") or "").strip()
    selected_customer_uuid = (form.get("customer_uuid") or "").strip()
    previous_customer_uuid = str(service.get("customer_uuid") or "").strip()
    if not selected_customer_uuid and selected_customer_id:
        selected_customer_uuid = _resolve_customer_uuid_from_id(selected_customer_id)

    raw_ports = (form.get("allocated_ports") or "").strip()
    allocated_ports = [int(port.strip()) for port in raw_ports.split(",") if port.strip()] if raw_ports else []
    if raw_ports and not allocated_ports:
        logger.warning("SERVICEID MODULE - Service update for uuid=%s contained no valid allocated_ports", uuid)

    service_rcon_port = form.get("service_rcon_port")
    if service_rcon_port in (None, "", "null", "None"):
        service_rcon_port = None
    else:
        try:
            service_rcon_port = int(service_rcon_port)
        except (TypeError, ValueError):
            service_rcon_port = None

    service_terminated_timestamp = form.get("service_terminated_timestamp")
    if service_terminated_timestamp in ("", "null", "None"):
        service_terminated_timestamp = None

    service.update({
        "allocated_cpu_cores": float(form.get("allocated_cpu_cores") or 0.0),
        "allocated_disk_gb": int(form.get("allocated_disk_gb") or 0),
        "allocated_ports": allocated_ports,
        "allocated_ram_mb": int(form.get("allocated_ram_mb") or 0),
        "cluster_id": (form.get("cluster_id") or "").strip(),
        "customer_id": selected_customer_id or service.get("customer_id"),
        "customer_uuid": selected_customer_uuid or service.get("customer_uuid"),
        "homepage_url": (form.get("homepage_url") or "").strip(),
        "management_url": (form.get("management_url") or "").strip(),
        "minecraft_version": (form.get("minecraft_version") or "").strip(),
        "modpack_name": (form.get("modpack_name") or "").strip(),
        "node_id": (form.get("node_id") or "").strip(),
        "platform": (form.get("platform") or "").strip(),
        "player_limit": int(form.get("player_limit") or 0),
        "provisioning_status": (form.get("provisioning_status") or "pending").strip(),
        "region": (form.get("region") or "").strip(),
        "server_type": (form.get("server_type") or "").strip(),
        "service_ip": (form.get("service_ip") or "").strip(),
        "service_name": (form.get("service_name") or "").strip() or service.get("service_name"),
        "service_provision_source": (form.get("service_provision_source") or "").strip(),
        "service_rcon_port": service_rcon_port,
        "service_rcon_pwd": (form.get("service_rcon_pwd") or "").strip(),
        "service_sku": (form.get("service_sku") or "").strip(),
        "service_status": (form.get("service_status") or "provisioning").strip(),
        "service_subdomain": (form.get("service_subdomain") or "").strip(),
        "service_terminated_timestamp": service_terminated_timestamp,
        "service_type": (form.get("service_type") or "").strip(),
        "service_updated_timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "web_server_engine": (form.get("web_server_engine") or "").strip(),
    })

    store = _get_service_appid_store()
    try:
        store.save_all(services)
    except Exception:
        logger.exception("SERVICEID MODULE - Service update failed actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
        raise

    _sync_customer_service_links(service, previous_customer_uuid=previous_customer_uuid or None)

    logger.info("SERVICEID MODULE - Service updated actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
    return redirect(url_for("serviceid_module.service_profile", uuid=uuid))


@serviceid_module_bp.route("/delete/<uuid>", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def delete_service(uuid):
    """Delete a service record and unlink it from the owning customer."""
    actor = resolve_preferred_name(str(session.get("technician") or ""))
    services = load_service_appids()
    service = next((record for record in services if record.get("uuid") == uuid), None)
    if service is None:
        logger.warning("SERVICEID MODULE - Delete lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404

    previous_customer_uuid = str(service.get("customer_uuid") or "").strip() or None
    services = [record for record in services if record.get("uuid") != uuid]

    store = _get_service_appid_store()
    try:
        store.save_all(services)
    except Exception:
        logger.exception("SERVICEID MODULE - Service delete failed actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
        raise

    if previous_customer_uuid:
        _sync_customer_service_links({"service_id": service.get("service_id"), "customer_uuid": ""}, previous_customer_uuid=previous_customer_uuid)

    logger.info("SERVICEID MODULE - Service deleted actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
    return redirect(url_for("serviceid_module.serviceid_dashboard"))

@serviceid_module_bp.route("/submit-new", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def new_service():
    """Render and process the service creation form."""
    actor = resolve_preferred_name(str(session.get("technician") or ""))
    if request.method == "GET":
        logger.info("SERVICEID MODULE - New service form opened actor=%s", _pseudonymize_actor(actor))
        from blueprints.crm_module import load_customers_file
        return render_template(
            "serviceid/submit_new.html",
            loggedInTech=actor,
            customers=load_customers_file(),)

    form = request.form.to_dict()
    services = load_service_appids()
    service_name = (form.get("service_name") or "").strip()
    if not service_name:
        logger.warning("SERVICEID MODULE - Service creation rejected actor=%s reason=missing_service_name", _pseudonymize_actor(actor))
        from blueprints.crm_module import load_customers_file
        return render_template(
            "serviceid/submit_new.html",
            error="Service name is required.",
            loggedInTech=actor,
            customers=load_customers_file(),
            selected_customer_id=(form.get("customer_id") or "").strip(),
            selected_customer_uuid=(form.get("customer_uuid") or "").strip(),
        ), 400

    raw_ports = (form.get("allocated_ports") or "").strip()
    if raw_ports:
        allocated_ports = [int(port.strip()) for port in raw_ports.split(",") if port.strip()]
    else:
        allocated_ports = []

    service_id = generate_service_id(services)
    customer_id = (form.get("customer_id") or "").strip()
    customer_uuid = (form.get("customer_uuid") or "").strip()
    if not customer_uuid and customer_id:
        customer_uuid = _resolve_customer_uuid_from_id(customer_id)

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    service_rcon_port = form.get("service_rcon_port")
    if service_rcon_port in (None, "", "null", "None"):
        service_rcon_port = None
    else:
        try:
            service_rcon_port = int(service_rcon_port)
        except (TypeError, ValueError):
            service_rcon_port = None

    service_terminated_timestamp = form.get("service_terminated_timestamp")
    if service_terminated_timestamp in ("", "null", "None"):
        service_terminated_timestamp = None

    new_record = {
        "uuid": str(uuid.uuid4()),
        "allocated_cpu_cores": float(form.get("allocated_cpu_cores") or 0.0),
        "allocated_disk_gb": int(form.get("allocated_disk_gb") or 0),
        "allocated_ports": allocated_ports,
        "allocated_ram_mb": int(form.get("allocated_ram_mb") or 0),
        "cluster_id": (form.get("cluster_id") or "").strip(),
        "customer_id": customer_id,
        "customer_uuid": customer_uuid,
        "homepage_url": (form.get("homepage_url") or "").strip(),
        "management_url": (form.get("management_url") or "").strip(),
        "minecraft_version": (form.get("minecraft_version") or "").strip(),
        "modpack_name": (form.get("modpack_name") or "").strip(),
        "node_id": (form.get("node_id") or "").strip(),
        "platform": (form.get("platform") or "").strip(),
        "player_limit": int(form.get("player_limit") or 0),
        "provisioning_status": (form.get("provisioning_status") or "pending").strip(),
        "region": (form.get("region") or "").strip(),
        "server_type": (form.get("server_type") or "").strip(),
        "service_created_timestamp": form.get("service_created_timestamp") or now,
        "service_id": service_id,
        "service_ip": (form.get("service_ip") or "").strip(),
        "service_name": service_name,
        "service_provision_source": (form.get("service_provision_source") or "").strip(),
        "service_rcon_port": service_rcon_port,
        "service_rcon_pwd": (form.get("service_rcon_pwd") or "").strip(),
        "service_sku": (form.get("service_sku") or "").strip(),
        "service_status": (form.get("service_status") or "provisioning").strip(),
        "service_subdomain": (form.get("service_subdomain") or "").strip(),
        "service_terminated_timestamp": service_terminated_timestamp,
        "service_type": (form.get("service_type") or "").strip(),
        "service_updated_timestamp": form.get("service_updated_timestamp") or now,
        "web_server_engine": (form.get("web_server_engine") or "").strip(),
    }

    services.append(new_record)
    store = _get_service_appid_store()
    try:
        store.save_all(services)
    except Exception:
        logger.exception("SERVICEID MODULE - Service creation failed actor=%s service_id=%s service_name=%s", _pseudonymize_actor(actor), service_id, service_name)
        raise

    _sync_customer_service_links(new_record)

    logger.info("SERVICEID MODULE - Service created actor=%s service_id=%s service_name=%s", _pseudonymize_actor(actor), service_id, service_name)
    return redirect(url_for("serviceid_module.serviceid_dashboard"))
