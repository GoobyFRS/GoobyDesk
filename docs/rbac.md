# Role-Based Access Control (RBAC)

GoobyDesk uses a lightweight, session-based RBAC model. Roles are assigned to an employee's auth record and are copied into the Flask session at login. Access decisions are enforced per-route via the `@role_required(...)` decorator (`local_handlers/auth_decorators.py`).

## Roles

| Role Constant | Value | Typical Purpose |
| --- | --- | --- |
| `ROLE_ITSM_TECH` | `itsm_technician` | Works tickets, changes, CRM, and service IDs |
| `ROLE_HR_TECH` | `hr_technician` | Manages employee/HR records |
| `ROLE_MANAGER` | `manager` | Elevated, cross-module access |
| `ROLE_ADMIN` | `admin` | Full access, including sensitive HR actions |

A single employee may hold multiple roles; roles are stored as a list on the employee's auth record and are set during HR account provisioning (`blueprints/hr_module.py`, `HR_ROLE_MAP`).

## How Access Is Checked

1. On login (`app.py`, `login()`), `_assign_roles_to_session()` populates `session["roles"]` from the authenticated employee record.
2. Protected routes are wrapped with `@role_required(*required_roles, require_all=False, redirect_to_login=True)`.
3. `role_required` enforces, in order:
   - **Unauthenticated** users are redirected to `/login` (or given a 403 if `redirect_to_login=False`).
   - **Admin or Manager bypass** — if the session has `admin` or `manager`, the request is always allowed, regardless of the route's declared roles.
   - **Wildcard role** — a route declared with `@role_required("*")` allows any authenticated user.
   - **Explicit role match** — otherwise, the user must have at least one of the declared roles (or all of them, if `require_all=True`).
4. Unauthorized authenticated users receive a rendered `errors/403.html` page.

## Role Requirements by Module

| Module | Routes | Required Role(s) |
| --- | --- | --- |
| ITSM (`itsm_module.py`) | Dashboard, ticket detail, status update, add note | `itsm_technician` |
| Changes (`changes_module.py`) | Dashboard, submit new, CSV export | `itsm_technician` |
| CRM (`crm_module.py`) | Dashboard, new/edit customer, worknotes | `itsm_technician` |
| Service IDs (`serviceid_module.py`) | Dashboard, submit new | `itsm_technician` |
| HR (`hr_module.py`) | Dashboard, new/edit employee | `hr_technician` |
| HR (`hr_module.py`) | Reset employee password | `admin` |
| Reports (`reports_module.py`) | Dashboard, CSV export | `*` (any authenticated user) |

Because Admins and Managers bypass explicit role checks, they can access every module above regardless of the table.

## Session Fields

- `session["technician"]` — logged-in username
- `session["roles"]` — list of role strings for the current session

## Notes for Contributors

- Always use the `ROLE_*` constants from `local_handlers/auth_decorators.py` rather than hardcoded role strings, so role names stay consistent.
- Use `require_all=True` only when a route genuinely needs every listed role; the default is "any of".
- New sensitive actions (e.g., password resets, account unlocks) should default to `ROLE_ADMIN` rather than a broader role.
