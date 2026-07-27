#!/usr/bin/env python3
"""One-time helper: migrate change-like tickets from tickets.json to changes.json."""
from __future__ import annotations

import argparse
from datetime import datetime

from local_handlers.local_config_loader import load_core_config
from storage.ticket_store import TicketStore
from storage.changes_store import ChangesStore


def is_change_like(ticket: dict) -> bool:
    keys = (
        "change_short_description",
        "implement_plan",
        "rollback_plan",
        "test_accept_plan",
        "change_number",
    )
    for key in keys:
        value = ticket.get(key)
        if value:
            return True

    subj = ticket.get("ticket_subject") or ticket.get("subject") or ""
    return isinstance(subj, str) and "change" in subj.lower()


def migrate(dry_run: bool = True) -> int:
    cfg = load_core_config()
    tstore = TicketStore(cfg["core"]["tickets_file"])
    cstore = ChangesStore(cfg["core"]["changes_file"])

    tickets = tstore.load_all()
    migrated = []

    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue
        if not is_change_like(ticket):
            continue

        new_change = {
            "change_number": cstore.next_change_number(),
            "change_short_description": (
                ticket.get("change_short_description")
                or ticket.get("ticket_subject")
                or ticket.get("subject")
                or ""
            ),
            "change_description": (
                ticket.get("change_description")
                or ticket.get("ticket_description")
                or ticket.get("ticket_body")
                or ""
            ),
            "implement_plan": ticket.get("implement_plan") or "",
            "test_accept_plan": ticket.get("test_accept_plan") or "",
            "rollback_plan": ticket.get("rollback_plan") or "",
            "planned_start_timestamp": ticket.get("planned_start_timestamp") or ticket.get("planned_start") or None,
            "planned_end_timestamp": ticket.get("planned_end_timestamp") or ticket.get("planned_end") or None,
            "requestor_id": (
                ticket.get("requestor_id")
                or ticket.get("owner")
                or ticket.get("created_by")
                or ticket.get("requestor")
                or ""
            ),
            "requestor_uuid": ticket.get("requestor_uuid") or None,
            "change_created_timestamp": (
                ticket.get("change_created_timestamp")
                or ticket.get("ticket_created_timestamp")
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
            "change_updated_timestamp": (
                ticket.get("change_updated_timestamp")
                or ticket.get("ticket_updated_timestamp")
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
            "change_status": ticket.get("change_status") or "pending",
            "change_risk": ticket.get("change_risk") or None,
        }

        migrated.append(new_change)

    if dry_run:
        print(f"Found {len(migrated)} change-like tickets to migrate (dry-run).")
        return len(migrated)

    for ch in migrated:
        cstore.append(ch)

    print(f"Migrated {len(migrated)} change records to {cfg['core']['changes_file']}")
    return len(migrated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate change-like tickets from tickets.json to changes.json"
    )
    parser.add_argument("--apply", action="store_true", help="Apply migration (default: dry-run)")
    args = parser.parse_args()

    migrated_count = migrate(dry_run=not args.apply)
    if not args.apply:
        print("Re-run with --apply to perform migration.")
