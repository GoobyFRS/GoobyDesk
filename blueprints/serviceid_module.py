#!/usr/bin/env python3
import logging
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for
from local_handlers.utils import resolve_preferred_name
from local_handlers.auth_decorators import role_required, ROLE_ITSM_TECH

from flask import current_app
from local_handlers.local_config_loader import load_core_config
from storage.service_appid_store import ServiceAppIdStore

def _pseudonymize_actor(name: str | None) -> str:
    """Return a stable opaque actor id for logging."""
    if not name:
        return "actor_unknown"
    safe_name = str(name).strip()
    if not safe_name:
        return "actor_unknown"
    return f"actor_{abs(hash(safe_name)) % 1000000:06d}"

def _get_config():
    """Return loaded app config or fallback loader."""
    cfg = current_app.config.get("LOADED_CONFIG")
    if cfg is None:
        cfg = load_core_config()
    return cfg

def _get_service_appid_store():
    """Return a ServiceAppIdStore instance from loaded config."""
    cfg = _get_config()
    return ServiceAppIdStore(cfg["core"]["serviceid_appid_file"])

def _resolve_customer_uuid_from_id(customer_id: str | None, customers: list | None = None) -> str:
    """Resolve a customer UUID from its customer ID."""
    normalized_customer_id = (customer_id or "").strip()
    if not normalized_customer_id:
        return ""

    if customers is None:
        from blueprints.crm_module import load_customers_file
        customers = load_customers_file()

    for customer in customers:
        if str(customer.get("customer_id") or "") == normalized_customer_id:
            return str(customer.get("uuid") or "")
    return ""

def _sync_customer_service_links(service_record: dict, previous_customer_uuid: str | None = None) -> None:
    """Keep the linked customer record aligned with the APPID list."""
    from blueprints.crm_module import load_customers_file, save_customers_file

    service_id = str(service_record.get("service_id") or "").strip()
    if not service_id:
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


serviceid_module_bp = Blueprint("serviceid_module", __name__, url_prefix="/serviceid")

# use @role_required(ROLE_ITSM_TECH)
def load_service_appids():
    """Load and return configured service APPIDs."""
    store = _get_service_appid_store()
    return store.load_all()

def generate_service_id(services):
    """Return the next service identifier in the APP-YYYY-#### format."""
    current_year = datetime.now().strftime("%Y")
    highest_number = 0

    for service in services:
        service_id = str(service.get("service_id") or "")
        if not service_id.startswith("APP-"):
            continue

        parts = service_id.split("-")
        if len(parts) != 3:
            continue

        try:
            candidate = int(parts[2])
        except ValueError:
            continue

        highest_number = max(highest_number, candidate)

    return f"APP-{current_year}-{highest_number + 1:04d}"

def _is_terminated_service(service: dict) -> bool:
    """Return True when a service record should be hidden by default."""
    service_status = str(service.get("service_status") or service.get("status") or "").strip().lower()
    if service_status == "terminated":
        return True

    terminated_timestamp = service.get("service_terminated_timestamp") or service.get("terminated")
    if terminated_timestamp in (None, "", "null", "None"):
        return False
    return True

@serviceid_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def serviceid_dashboard():
    """Render service APPID dashboard view."""
    actor = resolve_preferred_name(session.get("technician"))
    show_all = request.args.get("show_all") == "1"
    services = load_service_appids()
    displayed_services = services if show_all else [
        service for service in services if not _is_terminated_service(service)
    ]
    logging.info(
        "SERVICEID MODULE - Dashboard loaded actor=%s total_services=%s visible_services=%s show_all=%s",
        _pseudonymize_actor(actor),
        len(services),
        len(displayed_services),
        show_all,
    )
    return render_template(
        "services-appid/dashboard.html",
        services=displayed_services,
        loggedInTech=actor,
        show_all=show_all,
    )

@serviceid_module_bp.route("/profile/<uuid>", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def service_profile(uuid):
    """Render the profile for a single service record."""
    actor = resolve_preferred_name(session.get("technician"))
    services = load_service_appids()
    service = next((record for record in services if record.get("uuid") == uuid), None)
    if service is None:
        logging.warning("SERVICEID MODULE - Profile lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404
    logging.info("SERVICEID MODULE - Service profile viewed actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
    return render_template(
        "services-appid/profile.html",
        service=service,
        loggedInTech=actor,
    )

@serviceid_module_bp.route("/edit/<uuid>", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def edit_service(uuid):
    """Render and process the service edit form for a given record."""
    actor = resolve_preferred_name(session.get("technician"))
    services = load_service_appids()
    service = next((record for record in services if record.get("uuid") == uuid), None)
    if service is None:
        logging.warning("SERVICEID MODULE - Edit lookup failed actor=%s uuid=%s", _pseudonymize_actor(actor), uuid)
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        logging.info("SERVICEID MODULE - Edit form opened actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
        from blueprints.crm_module import load_customers_file
        return render_template(
            "services-appid/submit_new.html",
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

    service_rcon_port = form.get("service_rcon_port")
    if service_rcon_port in ("", "null", "None"):
        service_rcon_port = None
    else:
        service_rcon_port = int(service_rcon_port)

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
        "minecraft_version": (form.get("minecraft_version") or "").strip(),
        "modpack_name": (form.get("modpack_name") or "").strip(),
        "node_id": (form.get("node_id") or "").strip(),
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
    })

    store = _get_service_appid_store()
    try:
        store.save_all(services)
    except Exception:
        logging.exception("SERVICEID MODULE - Service update failed actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
        raise

    _sync_customer_service_links(service, previous_customer_uuid=previous_customer_uuid or None)

    logging.info("SERVICEID MODULE - Service updated actor=%s service_id=%s uuid=%s", _pseudonymize_actor(actor), service.get("service_id"), uuid)
    return redirect(url_for("serviceid_module.service_profile", uuid=uuid))

@serviceid_module_bp.route("/submit-new", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def new_service():
    """Render and process the service creation form."""
    actor = resolve_preferred_name(session.get("technician"))
    if request.method == "GET":
        logging.info("SERVICEID MODULE - New service form opened actor=%s", _pseudonymize_actor(actor))
        from blueprints.crm_module import load_customers_file
        return render_template(
            "services-appid/submit_new.html",
            loggedInTech=actor,
            customers=load_customers_file(),
        )

    form = request.form.to_dict()
    services = load_service_appids()
    service_name = (form.get("service_name") or "").strip()
    if not service_name:
        logging.warning("SERVICEID MODULE - Service creation rejected actor=%s reason=missing_service_name", _pseudonymize_actor(actor))
        from blueprints.crm_module import load_customers_file
        return render_template(
            "services-appid/submit_new.html",
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
    if service_rcon_port in ("", "null", "None"):
        service_rcon_port = None
    else:
        service_rcon_port = int(service_rcon_port)

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
        "minecraft_version": (form.get("minecraft_version") or "").strip(),
        "modpack_name": (form.get("modpack_name") or "").strip(),
        "node_id": (form.get("node_id") or "").strip(),
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
    }

    services.append(new_record)
    store = _get_service_appid_store()
    try:
        store.save_all(services)
    except Exception:
        logging.exception("SERVICEID MODULE - Service creation failed actor=%s service_id=%s service_name=%s", _pseudonymize_actor(actor), service_id, service_name)
        raise

    _sync_customer_service_links(new_record)

    logging.info("SERVICEID MODULE - Service created actor=%s service_id=%s service_name=%s", _pseudonymize_actor(actor), service_id, service_name)
    return redirect(url_for("serviceid_module.serviceid_dashboard"))
