#!/usr/bin/env python3
import logging
from flask import Blueprint, current_app, render_template, request, session
from local_handlers.auth_decorators import ROLE_ITSM_TECH, role_required
from local_handlers.utils import resolve_preferred_name
from storage.service_appid_store import ServiceAppIdStore

appid_module_bp = Blueprint('appid_module', __name__, url_prefix='/appid')

logger = logging.getLogger(__name__)


def _get_appid_store() -> ServiceAppIdStore:
	"""Return the configured shared ServiceID/AppID store."""
	config = current_app.config["LOADED_CONFIG"]
	core_config = config["core"]
	store_path = core_config.get("serviceid_appid_file") or core_config["serviceid_file"]
	return ServiceAppIdStore(store_path)


def _is_appid_record(record: dict) -> bool:
	"""Return whether a shared store record represents an application."""
	app_id = str(record.get("app_id") or record.get("application_id") or "")
	record_type = str(record.get("record_type") or record.get("type") or "").lower()
	return app_id.startswith("APP-") or record_type in {"appid", "application"}


def _is_retired_appid(record: dict) -> bool:
	"""Return whether an application record should be hidden by default."""
	status = str(record.get("app_status") or record.get("status") or "").lower()
	return status in {"retired", "terminated", "decommissioned"}


def _render_not_implemented():
	"""Render the placeholder until the AppID record workflows exist."""
	return render_template("under_construction.html")


@appid_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def appid_dashboard():
	"""Render the AppID dashboard."""
	show_all = request.args.get("show_all") == "1"
	appids = [
		record for record in _get_appid_store().load_all()
		if _is_appid_record(record)
	]
	displayed_appids = appids if show_all else [
		record for record in appids if not _is_retired_appid(record)
	]
	logger.info(
		"APPID MODULE - Dashboard loaded total_appids=%s visible_appids=%s show_all=%s",
		len(appids),
		len(displayed_appids),
		show_all,
	)
	return render_template(
		"appid/appid_dashboard.html",
		appids=displayed_appids,
		loggedInTech=resolve_preferred_name(session.get("technician")),
		show_all=show_all,
	)


@appid_module_bp.route("/submit-new", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def submit_new():
	"""Render the AppID submit-new placeholder."""
	# TODO: Implement AppID creation.
	return _render_not_implemented()


@appid_module_bp.route("/<appid_uuid>", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def view_appid(appid_uuid: str):
	"""Render the AppID record-view placeholder."""
	# TODO: Implement AppID record viewing.
	return _render_not_implemented()


@appid_module_bp.route("/<appid_uuid>/edit", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def edit_appid(appid_uuid: str):
	"""Render the AppID edit placeholder."""
	# TODO: Implement AppID record editing.
	return _render_not_implemented()


@appid_module_bp.route("/<appid_uuid>/delete", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def delete_appid(appid_uuid: str):
	"""Render the AppID delete placeholder."""
	# TODO: Implement AppID record deletion.
	return _render_not_implemented()


@appid_module_bp.route("/export", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def export_appids():
	"""Render the AppID export placeholder."""
	# TODO: Implement AppID record export.
	return _render_not_implemented()


@appid_module_bp.route("/import", methods=["GET", "POST"])
@role_required(ROLE_ITSM_TECH)
def import_appids():
	"""Render the AppID import placeholder."""
	# TODO: Implement AppID record import.
	return _render_not_implemented()


@appid_module_bp.route("/search", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def search_appids():
	"""Render the AppID search placeholder."""
	# TODO: Implement AppID record search.
	return _render_not_implemented()


@appid_module_bp.route("/bulk-update", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def bulk_update_appids():
	"""Render the AppID bulk-update placeholder."""
	# TODO: Implement AppID bulk updates.
	return _render_not_implemented()
