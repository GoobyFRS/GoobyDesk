#!/usr/bin/env python3
"""Pure helper functions for building CRM customer records.

These helpers contain no Flask, session, or file I/O dependencies so they
can be unit tested in isolation and reused outside of the CRM blueprint.
"""
import uuid
from datetime import datetime, timezone


def generate_customer_id(customers: list[dict]) -> str:
    """Generate the next sequential CID for the current year.

    Args:
        customers: Existing customer records to scan.

    Returns:
        A new customer ID in the form CID-YYYY-NNNN.
    """
    current_year = datetime.now(timezone.utc).year
    year_prefix = f"CID-{current_year}-"
    existing_ids = [c.get("customer_id", "") for c in customers if c.get("customer_id", "").startswith(year_prefix)]
    next_sequence = len(existing_ids) + 1
    return f"{year_prefix}{next_sequence:04d}"


def build_customer_record(form: dict, customers: list[dict], technician: str, submission_timestamp: str) -> dict:
    """Build a new CRM customer record from submitted form data.

    Args:
        form: Raw form field values (e.g. ``request.form``). Only
            ``.get(key, default)`` access is used, so any mapping-like
            object works.
        customers: Existing customer records, used to generate the new
            customer ID.
        technician: Username of the technician creating the record, used
            as the author of the initial note (if provided).
        submission_timestamp: ISO-8601 UTC timestamp string to stamp on the
            record's ``created`` field and any initial note.

    Returns:
        The fully-built customer record, ready to be appended to the
        customers list and persisted.
    """
    first_name = form.get("first_name", "").strip()
    last_name = form.get("last_name", "").strip()
    email = form.get("email", "").strip()

    new_customer_record = {
        "uuid": str(uuid.uuid4()),
        "customer_id": generate_customer_id(customers),
        "first_name": first_name,
        "last_name": last_name,
        "preferred_name": form.get("preferred_name", "").strip() or first_name,

        "company": form.get("company", "").strip() or None,
        "email": email,
        "phone": form.get("phone", "").strip() or None,

        "discord_username": form.get("discord_username", "").strip() or None,
        "discord_user_id": None,
        "minecraft_username": form.get("minecraft_username", "").strip() or None,

        "country": form.get("country", "").strip() or None,
        "timezone": form.get("timezone", "").strip() or None,
        "created": submission_timestamp,
        "last_seen": None,
        "last_login": None,

        "status": form.get("status", "active"),
        "status_reason": None,
        "account_locked": False,
        "email_verified": False,
        "mfa_enabled": False,

        "vip": form.get("vip") == "on",
        "content_creator": form.get("content_creator") == "on",

        "risk_level": "low",
        "lifetime_value": 0.00,
        "billing_currency": "USD",
        "last_order": None,
        "last_payment": None,

        "preferred_contact": form.get("preferred_contact", "email"),
        "marketing_opt_in": form.get("marketing_opt_in") == "on",
        "maintenance_notifications": form.get("maintenance_notifications") == "on",
        "assigned_account_manager": None,
        "services": [],

        "account_tags": [],

        "notes": [],
    }

    initial_note = form.get("notes", "").strip()
    if initial_note:
        new_customer_record["notes"].append({
            "date": submission_timestamp,
            "author": technician,
            "note": initial_note,
        })

    return new_customer_record
