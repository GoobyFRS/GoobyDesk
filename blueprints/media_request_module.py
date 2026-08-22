#!/usr/bin/env python3
"""Media request form that submits a standard ITSM ticket."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import Blueprint, current_app, render_template, request

from local_handlers.ticket_builder import build_ticket_record
from storage.ticket_store import TicketStore

ALLOWED_MEDIA_TYPES = {"TV Show", "Movie", "Other"}
NAME_RE = re.compile(r"^[A-Za-z0-9 .,'’-]{2,64}$")
IMDB_HOSTS = {"imdb.com", "www.imdb.com", "m.imdb.com"}

media_request_module_bp = Blueprint('media_request_module', __name__, url_prefix='/media-request')


def _turnstile_keys() -> tuple[str | None, str | None]:
    """Read Turnstile keys lazily so `.env` (loaded after blueprint import) is respected."""
    return os.getenv("CF_TURNSTILE_SITE_KEY"), os.getenv("CF_TURNSTILE_SECRET_KEY")


def _verify_turnstile() -> tuple[bool, str]:
    """Validate the Cloudflare Turnstile token when CAPTCHA is enabled.
    Returns:
        tuple[bool, str]: Success flag and an error message when verification fails.
    """
    site_key, secret_key = _turnstile_keys()
    if not (site_key and secret_key):
        return True, ""

    turnstile_token = request.form.get("cf-turnstile-response")
    if not turnstile_token:
        logging.warning("Missing Turnstile token in media request submission")
        return False, "CAPTCHA verification failed. Please try again."

    url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    data = {
        "secret": secret_key,
        "response": turnstile_token,
        "remoteip": request.remote_addr,
    }
    try:
        resp = requests.post(url, data=data, timeout=5)
        result = resp.json()
    except Exception as exception:
        logging.error("Turnstile verification error while contacting provider")
        logging.debug("Turnstile verification exception: %s", str(exception))
        return False, "Error verifying CAPTCHA. Please try again later."

    if not result.get("success"):
        logging.warning("Turnstile verification failed for media request: %s", result)
        return False, "CAPTCHA verification failed. Please try again."

    return True, ""

def _sanitize_text(
    value: str, *, max_length: int,
    allow_newlines: bool = False,
) -> str:
    """Normalize user-entered text and enforce bounded length."""
    if value is None:
        return ""

    sanitized = str(value).strip()
    sanitized = sanitized.replace("\x00", "")
    sanitized = re.sub(r"[\u0000-\u001F\u007F]", "", sanitized)

    if not allow_newlines:
        sanitized = " ".join(sanitized.split())
    else:
        sanitized = "\n".join(line.strip() for line in sanitized.splitlines())
        sanitized = sanitized.strip()

    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip()

    return sanitized

def _normalize_media_type(value: str) -> str:
    """Return a safe media type or the default option."""
    candidate = _sanitize_text(value, max_length=32)
    if candidate in ALLOWED_MEDIA_TYPES:
        return candidate
    return "TV Show"

def _normalize_imdb_link(value: str) -> str:
    """Return a safe IMDb URL when provided, else an empty string."""
    candidate = _sanitize_text(value, max_length=255)
    if not candidate:
        return ""

    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return ""
    if host not in IMDB_HOSTS:
        return ""
    return candidate

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
    requestor_name = _sanitize_text(
        request.form.get("requestor_name", ""),
        max_length=64,
    )
    media_type = _normalize_media_type(request.form.get("media_type", "TV Show"))
    imdb_link = _normalize_imdb_link(request.form.get("imdb_link", ""))
    description = _sanitize_text(
        request.form.get("ticket_body", ""),
        max_length=2000,
        allow_newlines=True,)

    site_key, secret_key = _turnstile_keys()
    context = {
        "requestor_name": requestor_name,
        "media_type": media_type,
        "imdb_link": imdb_link,
        "description": description,
        "media_options": ["TV Show", "Movie", "Audio", "Other"],
        "error_message": "",
        "success_message": "",
        "ticket_number": "",
        "sitekey": site_key if (site_key and secret_key) else None,
    }

    if request.method == "POST":
        turnstile_ok, turnstile_error = _verify_turnstile()
        if not turnstile_ok:
            context["error_message"] = turnstile_error
            return render_template("public/media_request.html", **context)

        if not requestor_name or not description:
            context["error_message"] = (
                "Please complete your name and request details."
            )
            return render_template("public/media_request.html", **context)

        if not NAME_RE.match(requestor_name):
            context["error_message"] = (
                "Please enter a valid name using letters, numbers, spaces, "
                "and common punctuation only."
            )
            return render_template("public/media_request.html", **context)

        if len(description) < 4:
            context["error_message"] = (
                "Please provide a longer description for your request."
            )
            return render_template("public/media_request.html", **context)

        if request.form.get("imdb_link") and not imdb_link:
            context["error_message"] = (
                "Please provide a valid IMDb URL beginning with http:// or "
                "https:// and ending on imdb.com."
            )
            return render_template("public/media_request.html", **context)

        ticket_number = _get_ticket_store().next_ticket_number(
            datetime.now().year,
        )
        ticket_body = description
        if imdb_link:
            ticket_body = f"{ticket_body}\n\nIMDB Link: {imdb_link}"

        ticket = build_ticket_record(
            {
                "requestor_name": requestor_name,
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
        logging.info("Media request ticket %s created (type=%s).", ticket_number, media_type)
        context["success_message"] = (
            f"Your media request has been logged as ticket {ticket_number}."
        )
        context["ticket_number"] = ticket_number
        return render_template("public/media_request.html", **context)

    return render_template("public/media_request.html", **context)
