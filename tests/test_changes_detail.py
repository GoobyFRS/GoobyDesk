import os
import tempfile
import unittest

from app import app
from storage.changes_store import ChangesStore


class ChangeDetailRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.temp_file.write("[]")
        self.temp_file.close()

        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["LOADED_CONFIG"] = {"core": {"changes_file": self.temp_file.name}}

        self.change_number = "CHG-2025-0001"
        store = ChangesStore(self.temp_file.name)
        store.append(
            {
                "change_number": self.change_number,
                "change_short_description": "Patch firewall rules",
                "change_description": "Allow new VPN access.",
                "implement_plan": "Apply config and verify connectivity.",
                "test_accept_plan": "Smoke test after deployment.",
                "rollback_plan": "Revert previous firewall rules.",
                "planned_start_timestamp": "2025-01-15 09:00:00",
                "planned_end_timestamp": "2025-01-15 10:00:00",
                "requestor_id": "Alice Tech",
                "change_status": "pending",
                "change_risk": "medium",
                "change_created_timestamp": "2025-01-15 08:00:00",
                "change_updated_timestamp": "2025-01-15 08:00:00",
            }
        )

        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_change_detail_route_renders_record(self):
        with self.client.session_transaction() as session:
            session["technician"] = "alice"
            session["roles"] = ["itsm_technician"]

        response = self.client.get(f"/changes/{self.change_number}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Change Record", response.data)
        self.assertIn(self.change_number.encode(), response.data)
        self.assertIn(b"Patch firewall rules", response.data)


if __name__ == "__main__":
    unittest.main()
