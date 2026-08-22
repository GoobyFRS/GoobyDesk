#!/usr/bin/env python3
"""Ticket storage wrapper.
This module provides a thin domain-specific API on top of JsonStore
for operations on ticket records. It normalizes ticket records to a
predictable shape and exposes convenience methods used by the
application (load/save/append/update/delete and ticket numbering).

Why: keep business logic (numbering, normalization) out of callers
and centralize JSON persistence concerns in one place.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from local_handlers.local_config_loader import load_core_config
from storage.json_store import JsonStore
from storage.validator import is_list

class TicketStore:
    def __init__(self, file_path: str) -> None:
        # JsonStore provides atomic-write, locking, and validation.
        # We ask for a list-backed store and a simple validator to
        # ensure top-level payloads are lists of tickets.
        self.store = JsonStore(file_path=file_path, default_factory=list, validator=is_list)

    @classmethod
    def from_config(cls) -> "TicketStore":
        config = load_core_config()
        return cls(config["core"]["tickets_file"])

    def load_all(self) -> list[dict[str, Any]]:
        # Read and normalize every ticket for downstream consumers.
        tickets = self.store.read(default=[])
        if not isinstance(tickets, list):
            return []
        return [self._normalize_ticket(ticket) for ticket in tickets]

    def save_all(self, tickets: list[dict[str, Any]]) -> None:
        # Normalize then overwrite the backing file atomically.
        normalized = [self._normalize_ticket(ticket) for ticket in tickets]
        self.store.write(normalized)

    def append(self, ticket: dict[str, Any]) -> None:
        # Append a single ticket to the list-backed store.
        self.store.append(self._normalize_ticket(ticket))

    def update(
        self,
        predicate: callable,
        updater: callable,
    ) -> bool:
        """Update first matching ticket using predicate and updater.

        Updater receives a shallow-copied record and should return the
        modified record (or None to leave unchanged). Returns True when
        a record was changed.
        """
        # Wrap the provided updater to ensure normalization before persisting.
        def _updater(record: dict[str, Any]):
            copy = dict(record)
            replacement = updater(copy)
            if replacement is None:
                return record
            return self._normalize_ticket(replacement)

        _, changed = self.store.update(predicate, _updater)
        return changed

    def delete(self, predicate: callable) -> int:
        """Delete tickets matching predicate. Returns number removed."""
        _, removed = self.store.delete(predicate)
        return removed

    def update_by_number(self, ticket_number: str, updater: callable) -> bool:
        """Convenience: update ticket by `ticket_number`. Returns True if changed."""
        return self.update(lambda r: r.get("ticket_number") == ticket_number, updater)

    def next_ticket_number(self, year: int | None = None) -> str:
        # Simple sequential numbering based on count of existing tickets.
        # Deterministic and easy to reason about; fine for small, single-writer apps.
        current_year = year or datetime.now().year
        ticket_count = len(self.load_all()) + 1
        return f"TKT-{current_year}-{ticket_count:04d}"

    def next_change_number(self, year: int | None = None) -> str:
        current_year = year or datetime.now().year
        ticket_count = len(self.load_all()) + 1
        return f"CHG-{current_year}-{ticket_count:04d}"

    @staticmethod
    def _normalize_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
        ticket.setdefault("ticket_notes", [])
        ticket.setdefault("ticket_worknotes", list(ticket.get("ticket_notes", [])))
        ticket.setdefault("ticket_resolution_notes", [])
        ticket.setdefault("ticket_queue", "support")
        ticket.setdefault("assigned_to", None)
        ticket.setdefault("ticket_acknowledged_timestamp", None)
        return ticket
