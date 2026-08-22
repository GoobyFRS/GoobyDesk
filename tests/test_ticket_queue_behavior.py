import json
import os
import tempfile
import unittest

from app import app
from local_handlers.ticket_builder import build_ticket_record
from storage.ticket_store import TicketStore


class TicketQueueBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.temp_file.write("[]")
        self.temp_file.close()

        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["LOADED_CONFIG"] = {"core": {"tickets_file": self.temp_file.name}}
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def _write_tickets(self, tickets):
        with open(self.temp_file.name, "w", encoding="utf-8") as handle:
            json.dump(tickets, handle)

    def test_new_ticket_defaults_queue_and_assignment(self):
        ticket = build_ticket_record(
            {
                "requestor_name": "Matt",
                "requestor_email": "matt@example.org",
                "ticket_subject": "Printer Issue",
                "ticket_body": "The printer is offline.",
            },
            "TKT-2026-0001",
            source="web",
        )

        self.assertEqual(ticket["ticket_queue"], "support")
        self.assertIsNone(ticket["assigned_to"])
        self.assertIsNone(ticket["ticket_acknowledged_timestamp"])

    def test_ticket_store_normalizes_legacy_tickets(self):
        legacy_ticket = {"ticket_number": "TKT-2025-0002", "ticket_subject": "Legacy ticket"}
        self._write_tickets([legacy_ticket])

        ticket = TicketStore(self.temp_file.name).load_all()[0]
        self.assertEqual(ticket["ticket_queue"], "support")
        self.assertIsNone(ticket["assigned_to"])
        self.assertEqual(ticket["ticket_worknotes"], [])

    def test_dashboard_and_queue_routes_filter_by_signature_and_assignment(self):
        self._write_tickets(
            [
                {
                    "ticket_number": "TKT-2025-0001",
                    "ticket_subject": "Support ticket",
                    "ticket_status": "open",
                    "ticket_queue": "support",
                    "assigned_to": "alice",
                },
                {
                    "ticket_number": "TKT-2025-0002",
                    "ticket_subject": "Support but not mine",
                    "ticket_status": "open",
                    "ticket_queue": "support",
                    "assigned_to": "bob",
                },
                {
                    "ticket_number": "TKT-2025-0003",
                    "ticket_subject": "Escalation for me",
                    "ticket_status": "open",
                    "ticket_queue": "escalation",
                    "assigned_to": "alice",
                },
                {
                    "ticket_number": "TKT-2025-0004",
                    "ticket_subject": "Billing for me",
                    "ticket_status": "open",
                    "ticket_queue": "billing",
                    "assigned_to": "alice",
                },
                {
                    "ticket_number": "TKT-2025-0005",
                    "ticket_subject": "Closed ticket",
                    "ticket_status": "closed",
                    "ticket_queue": "support",
                    "assigned_to": "alice",
                },
            ]
        )

        with self.client.session_transaction() as session:
            session["technician"] = "alice"
            session["roles"] = ["itsm_technician"]

        dashboard_response = self.client.get("/itsm/")
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertIn("TKT-2025-0001", dashboard_html)
        self.assertIn("TKT-2025-0003", dashboard_html)
        self.assertIn("TKT-2025-0004", dashboard_html)
        self.assertNotIn("TKT-2025-0002", dashboard_html)
        self.assertNotIn("TKT-2025-0005", dashboard_html)

        support_response = self.client.get("/itsm/queue/support")
        self.assertEqual(support_response.status_code, 200)
        self.assertIn("TKT-2025-0001", support_response.get_data(as_text=True))
        self.assertNotIn("TKT-2025-0003", support_response.get_data(as_text=True))

        escalation_response = self.client.get("/itsm/queue/escalation")
        self.assertEqual(escalation_response.status_code, 200)
        self.assertIn("TKT-2025-0003", escalation_response.get_data(as_text=True))

        billing_response = self.client.get("/itsm/queue/billing")
        self.assertEqual(billing_response.status_code, 200)
        self.assertIn("TKT-2025-0004", billing_response.get_data(as_text=True))

    def test_assign_to_me_updates_assignment_and_requires_auth(self):
        self._write_tickets(
            [
                {
                    "ticket_number": "TKT-2025-0001",
                    "ticket_subject": "Unassigned ticket",
                    "ticket_status": "open",
                    "ticket_queue": "support",
                    "assigned_to": None,
                    "ticket_acknowledged_timestamp": None,
                },
                {
                    "ticket_number": "TKT-2025-0002",
                    "ticket_subject": "Already assigned ticket",
                    "ticket_status": "open",
                    "ticket_queue": "escalation",
                    "assigned_to": "bob",
                    "ticket_acknowledged_timestamp": "2025-01-01 12:00:00",
                },
            ]
        )

        with self.client.session_transaction() as session:
            session["technician"] = "alice"
            session["roles"] = ["itsm_technician"]

        assign_response = self.client.post("/itsm/ticket/TKT-2025-0001/assign_to_me")
        self.assertEqual(assign_response.status_code, 200)
        ticket = TicketStore(self.temp_file.name).load_all()[0]
        self.assertEqual(ticket["assigned_to"], "alice")
        self.assertIsNotNone(ticket["ticket_acknowledged_timestamp"])

        second_assign = self.client.post("/itsm/ticket/TKT-2025-0002/assign_to_me")
        self.assertEqual(second_assign.status_code, 200)
        reassigned = TicketStore(self.temp_file.name).load_all()[1]
        self.assertEqual(reassigned["assigned_to"], "alice")
        self.assertEqual(reassigned["ticket_acknowledged_timestamp"], "2025-01-01 12:00:00")

        missing_response = self.client.post("/itsm/ticket/TKT-2025-9999/assign_to_me")
        self.assertEqual(missing_response.status_code, 404)

        with self.client.session_transaction() as session:
            session.clear()

        no_auth_response = self.client.post("/itsm/ticket/TKT-2025-0001/assign_to_me")
        self.assertEqual(no_auth_response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
