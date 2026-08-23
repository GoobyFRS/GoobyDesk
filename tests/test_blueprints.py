import json
import io
import os
import tempfile
import unittest

import blueprints.api_module as api_module
import blueprints.appid_module as appid_module
import blueprints.changes_module as changes_module
import blueprints.crm_module as crm_module
import blueprints.hr_module as hr_module
import blueprints.itsm_module as itsm_module
import blueprints.media_request_module as media_request_module
import blueprints.reports_module as reports_module
import blueprints.serviceid_module as serviceid_module

from app import app

class BlueprintRouteTests(unittest.TestCase):
    """Base test case for blueprint route coverage using temp JSON stores."""

    def setUp(self):
        """Prepare a test app instance and temporary backing files."""
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SERVER_NAME"] = "localhost.test"
        self.app.secret_key = "test-secret"

        self.original_turnstile_site_key = os.environ.get("CF_TURNSTILE_SITE_KEY")
        self.original_turnstile_secret_key = os.environ.get("CF_TURNSTILE_SECRET_KEY")
        os.environ["CF_TURNSTILE_SITE_KEY"] = ""
        os.environ["CF_TURNSTILE_SECRET_KEY"] = ""

        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = self.app.test_client()

    def tearDown(self):
        """Restore env variables and clean temporary files."""
        self.temp_dir.cleanup()

        if self.original_turnstile_site_key is None:
            os.environ.pop("CF_TURNSTILE_SITE_KEY", None)
        else:
            os.environ["CF_TURNSTILE_SITE_KEY"] = self.original_turnstile_site_key

        if self.original_turnstile_secret_key is None:
            os.environ.pop("CF_TURNSTILE_SECRET_KEY", None)
        else:
            os.environ["CF_TURNSTILE_SECRET_KEY"] = self.original_turnstile_secret_key

    def _write_json(self, path, payload):
        """Persist a JSON payload to a temporary file."""
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def _set_auth_session(self, username="alice", roles=None):
        """Seed a valid technician session for route auth checks."""
        with self.client.session_transaction() as session:
            session["technician"] = username
            session["roles"] = roles or ["itsm_technician"]

    def test_blueprint_loggers_are_module_scoped(self):
        """Every blueprint should declare a module logger for production-safe output."""
        modules = [
            api_module,
            appid_module,
            changes_module,
            crm_module,
            hr_module,
            itsm_module,
            media_request_module,
            reports_module,
            serviceid_module,
        ]

        for module in modules:
            self.assertTrue(hasattr(module, "logger"))
            self.assertEqual(module.logger.name, module.__name__)

    def test_appid_blueprint_has_standard_route_schema(self):
        """The AppID blueprint should expose the same CRUD-style route layout used across modules."""
        self.assertTrue(hasattr(appid_module, "appid_dashboard"))
        self.assertTrue(hasattr(appid_module, "submit_new"))
        self.assertTrue(hasattr(appid_module, "view_appid"))
        self.assertTrue(hasattr(appid_module, "edit_appid"))
        self.assertTrue(hasattr(appid_module, "delete_appid"))
        self.assertTrue(hasattr(appid_module, "export_appids"))
        self.assertTrue(hasattr(appid_module, "import_appids"))
        self.assertTrue(hasattr(appid_module, "search_appids"))
        self.assertTrue(hasattr(appid_module, "bulk_update_appids"))
        self.assertIn("/appid/", str(self.app.url_map))

class ApiBlueprintTests(BlueprintRouteTests):
    """Validate the public API ingress endpoints."""

    def test_status_route(self):
        """The status endpoint should report the app as active."""
        ticket_file = os.path.join(self.temp_dir.name, "tickets.json")
        self._write_json(ticket_file, [])
        self.app.config["LOADED_CONFIG"] = {"core": {"tickets_file": ticket_file}}

        response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["is_GoobyDesk"])

    def test_uptime_kuma_webhook_creates_ticket(self):
        """A tracked Uptime Kuma alert should create an incident ticket."""
        ticket_file = os.path.join(self.temp_dir.name, "tickets.json")
        self._write_json(ticket_file, [])
        self.app.config["LOADED_CONFIG"] = {"core": {"tickets_file": ticket_file}}

        response = self.client.post(
            "/api/uptime-kuma",
            json={
                "monitor": {"name": "Primary Web", "url": "https://example.com"},
                "heartbeat": {"status": 0, "msg": "Service is down"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        with open(ticket_file, "r", encoding="utf-8") as handle:
            tickets = json.load(handle)
        self.assertEqual(len(tickets), 1)
        self.assertIn("Uptime Kuma Alert - Primary Web", tickets[0]["ticket_subject"])


class ChangesBlueprintTests(BlueprintRouteTests):
    """Validate the change-management blueprint and request flow."""

    def test_dashboard_and_submit_new_change(self):
        """The dashboard renders and a valid change submission persists."""
        change_file = os.path.join(self.temp_dir.name, "changes.json")
        self._write_json(change_file, [])
        self.app.config["LOADED_CONFIG"] = {"core": {"changes_file": change_file}}
        self._set_auth_session()

        dashboard_response = self.client.get("/changes/")
        self.assertEqual(dashboard_response.status_code, 200)

        create_response = self.client.post(
            "/changes/submit-new",
            data={
                "change_short_description": "Patch firewall rules",
                "change_description": "Allow new VPN access.",
                "implement_plan": "Apply config and verify connectivity.",
                "test_accept_plan": "Ping the VPN gateway.",
                "rollback_plan": "Revert the firewall baseline.",
                "planned_start_timestamp": "2025-01-15T09:00",
                "planned_end_timestamp": "2025-01-15T10:00",
                "change_risk": "medium",
            },
        )

        self.assertEqual(create_response.status_code, 302)
        with open(change_file, "r", encoding="utf-8") as handle:
            change_records = json.load(handle)
        self.assertEqual(len(change_records), 1)
        self.assertEqual(change_records[0]["change_short_description"], "Patch firewall rules")

class CrmBlueprintTests(BlueprintRouteTests):
    """Validate the CRM customer dashboard and creation workflow."""

    def test_crm_dashboard_and_customer_creation(self):
        """The CRM dashboard loads and valid customer creation persists."""
        customer_file = os.path.join(self.temp_dir.name, "customers.json")
        self._write_json(customer_file, [])
        self.app.config["LOADED_CONFIG"] = {"core": {"customers_file": customer_file}}
        self._set_auth_session()

        dashboard_response = self.client.get("/crm/")
        self.assertEqual(dashboard_response.status_code, 200)

        create_response = self.client.post(
            "/crm/submit-new",
            data={
                "first_name": "Steve",
                "last_name": "Customer",
                "email": "steve@example.com",
                "status": "active",
                "country": "United States",
                "timezone": "UTC",
            },
        )

        self.assertEqual(create_response.status_code, 302)
        with open(customer_file, "r", encoding="utf-8") as handle:
            customers = json.load(handle)
        self.assertEqual(len(customers), 1)
        self.assertEqual(customers[0]["first_name"], "Steve")
        self.assertEqual(customers[0]["last_name"], "Customer")

    def test_crm_export_csv(self):
        """The CRM export endpoint should return a CSV download for all customers."""
        customer_file = os.path.join(self.temp_dir.name, "customers.json")
        self._write_json(
            customer_file,
            [
                {
                    "customer_id": "CID-2026-0001",
                    "first_name": "Steve",
                    "last_name": "Customer",
                    "email": "steve@example.com",
                    "status": "active",
                    "country": "United States",
                    "timezone": "UTC",
                }
            ],
        )
        self.app.config["LOADED_CONFIG"] = {"core": {"customers_file": customer_file}}
        self._set_auth_session()

        response = self.client.get("/crm/export/csv")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers.get("Content-Type", ""))
        self.assertIn("attachment; filename=customers_", response.headers.get("Content-Disposition", ""))
        self.assertIn("Steve", response.get_data(as_text=True))


class HrBlueprintTests(BlueprintRouteTests):
    """Validate HR employee dashboard and new-employee provisioning."""

    def test_hr_dashboard_and_employee_creation(self):
        """The HR dashboard renders and a valid employee record is saved."""
        hr_file = os.path.join(self.temp_dir.name, "hr.json")
        auth_file = os.path.join(self.temp_dir.name, "employees.json")
        self._write_json(hr_file, [])
        self._write_json(auth_file, [])
        self.app.config["LOADED_CONFIG"] = {
            "core": {
                "hr_file": hr_file,
                "employee_auth_file": auth_file,
            }
        }
        self._set_auth_session(username="hradmin", roles=["hr_technician"])

        dashboard_response = self.client.get("/hr/")
        self.assertEqual(dashboard_response.status_code, 200)

        create_response = self.client.post(
            "/hr/employee/submit-new",
            data={
                "first_name": "Bob",
                "last_name": "Employee",
                "email": "bob@example.org",
                "title": "Systems Engineer",
                "department": "IT",
                "role": "itsm_technician",
                "assignment_queue": "support",
            },
        )

        self.assertEqual(create_response.status_code, 200)
        with open(hr_file, "r", encoding="utf-8") as handle:
            employees = json.load(handle)
        self.assertEqual(len(employees), 1)
        self.assertEqual(employees[0]["first_name"], "Bob")

    def test_hr_export_csv(self):
        """The HR export endpoint should return a CSV download for all employees."""
        hr_file = os.path.join(self.temp_dir.name, "hr.json")
        auth_file = os.path.join(self.temp_dir.name, "employees.json")
        self._write_json(
            hr_file,
            [
                {
                    "employee_id": "EMP-2026-1234",
                    "uuid": "employee-123",
                    "first_name": "Bob",
                    "last_name": "Employee",
                    "email": "bob@example.org",
                    "employment": {"status": "active"},
                }
            ],
        )
        self._write_json(auth_file, [])
        self.app.config["LOADED_CONFIG"] = {
            "core": {
                "hr_file": hr_file,
                "employee_auth_file": auth_file,
            }
        }
        self._set_auth_session(username="hradmin", roles=["hr_technician"])

        response = self.client.get("/hr/export/csv")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers.get("Content-Type", ""))
        self.assertIn("attachment; filename=employees_", response.headers.get("Content-Disposition", ""))
        self.assertIn("Bob", response.get_data(as_text=True))

class ItsmBlueprintTests(BlueprintRouteTests):
    """Validate the ITSM ticket queues and assignment workflows."""

    def test_ticket_queue_routes_and_assign_to_me(self):
        """Queue views and assignment updates should reflect the active technician."""
        ticket_file = os.path.join(self.temp_dir.name, "tickets.json")
        self._write_json(
            ticket_file,
            [
                {
                    "ticket_number": "TKT-2025-0001",
                    "ticket_subject": "Printer offline",
                    "ticket_status": "open",
                    "ticket_queue": "support",
                    "assigned_to": "bob",
                }
            ],
        )
        self.app.config["LOADED_CONFIG"] = {"core": {"tickets_file": ticket_file}}
        self._set_auth_session()

        support_response = self.client.get("/itsm/queue/support")
        self.assertEqual(support_response.status_code, 200)

        assign_response = self.client.post("/itsm/ticket/TKT-2025-0001/assign_to_me")
        self.assertEqual(assign_response.status_code, 200)
        with open(ticket_file, "r", encoding="utf-8") as handle:
            tickets = json.load(handle)
        self.assertEqual(tickets[0]["assigned_to"], "alice")

class MediaRequestBlueprintTests(BlueprintRouteTests):
    """Validate public media request ticket creation."""

    def test_media_request_form_and_submission(self):
        """A valid media request form should persist a ticket and render success."""
        ticket_file = os.path.join(self.temp_dir.name, "tickets.json")
        self._write_json(ticket_file, [])
        self.app.config["LOADED_CONFIG"] = {"core": {"tickets_file": ticket_file}}

        get_response = self.client.get("/media-request/")
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(
            "/media-request/",
            data={
                "requestor_name": "Alice Example",
                "media_type": "Movie",
                "ticket_body": "Please add this movie to the catalog.",
                "imdb_link": "https://www.imdb.com/title/tt0111161/",
            },
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertIn(b"Your media request has been logged", post_response.data)
        with open(ticket_file, "r", encoding="utf-8") as handle:
            tickets = json.load(handle)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["requestor_name"], "Alice Example")

class ReportsBlueprintTests(BlueprintRouteTests):
    """Validate the reporting dashboard and CSV export actions."""

    def test_reports_dashboard_and_csv_export(self):
        """The reports page and export endpoint should load successfully."""
        ticket_file = os.path.join(self.temp_dir.name, "tickets.json")
        change_file = os.path.join(self.temp_dir.name, "changes.json")
        self._write_json(
            ticket_file,
            [
                {
                    "ticket_number": "TKT-2025-0001",
                    "ticket_subject": "Printer offline",
                    "ticket_status": "Open",
                    "submission_date": "2025-01-01 00:00:00",
                    "ticket_source": "web",
                    "ticket_queue": "support",
                    "closure_date": None,
                }
            ],
        )
        self._write_json(change_file, [])
        self.app.config["LOADED_CONFIG"] = {"core": {"tickets_file": ticket_file, "changes_file": change_file}}
        self._set_auth_session()

        dashboard_response = self.client.get("/reports/dashboard")
        self.assertEqual(dashboard_response.status_code, 200)

        export_response = self.client.get("/reports/export/csv")
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("text/csv", export_response.headers.get("Content-Type", ""))


class ServiceIdBlueprintTests(BlueprintRouteTests):
    """Validate the service dashboard and creation flow."""

    def test_service_dashboard_and_creation(self):
        """The service dashboard loads and a valid service record is saved."""
        customer_file = os.path.join(self.temp_dir.name, "customers.json")
        service_file = os.path.join(self.temp_dir.name, "serviceid.json")
        self._write_json(
            customer_file,
            [{
                "uuid": "customer-123",
                "customer_id": "CID-2026-0001",
                "first_name": "Alice",
                "last_name": "Customer",
                "services": [],
            }],
        )
        self._write_json(service_file, [])
        self.app.config["LOADED_CONFIG"] = {
            "core": {
                "customers_file": customer_file,
                "serviceid_appid_file": service_file,
            }
        }
        self._set_auth_session()

        dashboard_response = self.client.get("/serviceid/")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertNotIn("APPID", dashboard_response.get_data(as_text=True).upper())

        create_response = self.client.post(
            "/serviceid/submit-new",
            data={
                "service_name": "Test Service",
                "customer_id": "CID-2026-0001",
                "customer_uuid": "customer-123",
                "allocated_cpu_cores": "2",
                "allocated_disk_gb": "20",
                "allocated_ram_mb": "4096",
                "player_limit": "10",
                "service_status": "provisioning",
                "provisioning_status": "pending",
            },
        )

        self.assertEqual(create_response.status_code, 302)
        with open(service_file, "r", encoding="utf-8") as handle:
            services = json.load(handle)
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["service_name"], "Test Service")

    def test_service_csv_import(self):
        """The CSV import endpoint should create service records from uploaded rows."""
        customer_file = os.path.join(self.temp_dir.name, "customers.json")
        service_file = os.path.join(self.temp_dir.name, "serviceid.json")
        self._write_json(
            customer_file,
            [{
                "uuid": "customer-123",
                "customer_id": "CID-2026-0001",
                "first_name": "Alice",
                "last_name": "Customer",
                "services": [],
            }],
        )
        self._write_json(service_file, [])
        self.app.config["LOADED_CONFIG"] = {
            "core": {
                "customers_file": customer_file,
                "serviceid_appid_file": service_file,
            }
        }
        self._set_auth_session()

        csv_payload = io.BytesIO(
            (
                "service_name,customer_id,service_type,service_status,provisioning_status,allocated_cpu_cores,allocated_ram_mb,allocated_disk_gb,allocated_ports\n"
                "Imported Service,CID-2026-0001,web_server,active,provisioned,4,8192,120,\"25565,25575\"\n"
            ).encode("utf-8")
        )

        response = self.client.post(
            "/serviceid/import/csv",
            data={"csv_file": (csv_payload, "service_import.csv")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        with open(service_file, "r", encoding="utf-8") as handle:
            services = json.load(handle)
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["service_name"], "Imported Service")
        self.assertEqual(services[0]["customer_uuid"], "customer-123")
        self.assertEqual(services[0]["allocated_ports"], [25565, 25575])

if __name__ == "__main__":
    unittest.main()
