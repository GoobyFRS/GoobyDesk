#!/usr/bin/env python3
"""Media request form that submits a standard ITSM ticket."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, render_template, request

from local_handlers.ticket_builder import build_ticket_record
from storage.ticket_store import TicketStore

media_request_module_bp = Blueprint('media_request_module', __name__, url_prefix='/requst-media')

def _get_ticket_store() -> TicketStore:
    """Return a configured ticket store for the current app context."""
    config = current_app.config.get("LOADED_CONFIG")
    if config is None:
        from local_handlers.local_config_loader import load_core_config

        config = load_core_config()
    return TicketStore(config["core"]["tickets_file"])

@media_request_module_bp.route("/", methods=["GET", "POST"])
def submit_media_request():
    """Render a media request form and create a normal ticket on submit."""
    requestor_name = (request.form.get("requestor_name") or "").strip()
    requestor_email = (request.form.get("requestor_email") or "").strip()
    media_type = (request.form.get("media_type") or "TV Show").strip() or "TV Show"
    imdb_link = (request.form.get("imdb_link") or "").strip()
    description = (request.form.get("ticket_body") or "").strip()

    context = {
        "requestor_name": requestor_name,
        "requestor_email": requestor_email,
        "media_type": media_type,
        "imdb_link": imdb_link,
        "description": description,
        "media_options": ["TV Show", "Movie", "Other"],
        "error_message": "",
        "success_message": "",
        "ticket_number": "",
    }

    if request.method == "POST":
        if not requestor_name or not requestor_email or not description:
            context["error_message"] = "Please complete your name, email, and request details."
            return render_template("public/request_media.html", **context)

        ticket_number = _get_ticket_store().next_ticket_number(datetime.now().year)
        ticket_body = description
        if imdb_link:
            ticket_body = f"{ticket_body}\n\nIMDB Link: {imdb_link}"

        ticket = build_ticket_record(
            {
                "requestor_name": requestor_name,
                "requestor_email": requestor_email,
                "ticket_subject": f"Media Request - {media_type}",
                "ticket_body": ticket_body,
                "request_type": media_type,
                "ticket_impact": "Low",
                "ticket_urgency": "Normal",
            },
            ticket_number,
            source="web",
        )

        _get_ticket_store().append(ticket)
        context["success_message"] = f"Your media request has been logged as ticket {ticket_number}."
        context["ticket_number"] = ticket_number
        return render_template("public/request_media.html", **context)

    return render_template("public/request_media.html", **context)
