#!/usr/bin/env python3
"""Build ticket record helper."""
from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any

def build_ticket_record(form_or_payload: Any, ticket_number: str, source: str = "web", technician: str | None = None) -> dict[str, Any]:
    """Construct a normalized ticket dict from a request form or JSON payload.
    Args:
        form_or_payload: Mapping-like object with ticket fields (supports `.get`).
        ticket_number: Pre-generated ticket number string.
        source: Source string (e.g. "web" or "api").
        technician: Optional technician username creating the ticket.
    Returns:
        dict: Ticket ready to persist (not persisted by this function).
    """
    if hasattr(form_or_payload, "get"):
        get = form_or_payload.get
    else:
        def get(key, default=None):
            return getattr(form_or_payload, key, default)

    requestor_name = get("requestor_name", "") or ""
    requestor_email = get("requestor_email", "") or ""
    ticket_subject = get("ticket_subject", "") or "(No Subject)"
    ticket_body = get("ticket_body", "") or ""
    request_type = get("request_type", "") or ""
    ticket_impact = get("ticket_impact", "") or ""
    ticket_urgency = get("ticket_urgency", "") or ""

    ticket = {
        "uuid": str(uuid.uuid4()),
        "ticket_number": ticket_number,
        "requestor_name": requestor_name,
        "requestor_email": requestor_email,
        "ticket_subject": ticket_subject,
        "ticket_body": ticket_body,
        "request_type": request_type,
        "ticket_impact": ticket_impact,
        "ticket_urgency": ticket_urgency,
        "ticket_status": "open",
        "ticket_queue": "support",
        "assigned_to": None,
        "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ticket_acknowledged_timestamp": None,
        "ticket_escalation_timestamp": None,
        "ticket_resolved_timestamp": None,
        "escalation_level": 0,
        "ticket_overdue": False,
        "ticket_source": source,
        "ticket_notes": [],
        "ticket_worknotes": [],
        "ticket_resolution_notes": [],
    }

    # Optionally record who created the ticket
    if technician:
        ticket["created_by"] = technician

    return ticket
