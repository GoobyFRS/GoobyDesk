# Audit Results

**Planned Actions**
- **Scan**: Inspect each blueprint for the 9 standard routes.
- **Map**: Record which routes exist and their endpoints.
- **Recommend**: List missing routes and consistency suggestions.

**Summary**
- **Required routes**: Dashboard, Submit New, View, Edit, Delete, Export, Import, Search, Bulk Update.
- I scanned the blueprint modules in [blueprints](blueprints) and mapped each against the required set.

**Per-Blueprint Findings**

- **changes_module**: [blueprints/changes_module.py](blueprints/changes_module.py#L1-L200)
	- **Dashboard**: Present (`/`)
	- **Submit New**: Present (`/submit-new`)
	- **View**: Present (`/<change_number>`)
	- **Edit**: Missing
	- **Delete**: Missing
	- **Export**: Present (`/export/csv`)
	- **Import**: Missing
	- **Search**: Missing
	- **Bulk Update**: Missing

- **crm_module**: [blueprints/crm_module.py](blueprints/crm_module.py#L1-L200)
	- **Dashboard**: Present (`/`)
	- **Submit New**: Present (`/submit-new`)
	- **View**: Present (`/profile/<uuid>`)
	- **Edit**: Present (`/customer/<uuid>/edit`)
	- **Delete**: Present (`/customer/<uuid>/delete`)
	- **Export**: Present (`/export/csv`)
	- **Import**: Missing
	- **Search**: Missing (no dedicated `/search` route)
	- **Bulk Update**: Missing

- **hr_module**: [blueprints/hr_module.py](blueprints/hr_module.py#L1-L200)
	- **Dashboard**: Present (`/`)
	- **Submit New**: Present (`/employee/submit-new`)
	- **View**: Present (`/employee/<uuid>`)
	- **Edit**: Present (`/employee/<uuid>/edit`)
	- **Delete**: Present (`/employee/<uuid>/delete`)
	- **Export**: Present (`/export/csv`)
	- **Import**: Missing
	- **Search**: Missing
	- **Bulk Update**: Missing

- **appid_module**: [blueprints/appid_module.py](blueprints/appid_module.py#L1-L200)
	- **Dashboard**: Present (`/`)
	- **Submit New**: Present (`/submit-new`) (placeholder)
	- **View**: Present (`/<appid_uuid>`) (placeholder)
	- **Edit**: Present (`/<appid_uuid>/edit`) (placeholder)
	- **Delete**: Present (`/<appid_uuid>/delete`) (placeholder)
	- **Export**: Present (`/export`) (placeholder)
	- **Import**: Present (`/import`) (placeholder)
	- **Search**: Present (`/search`) (placeholder)
	- **Bulk Update**: Present (`/bulk-update`) (placeholder)

- **itsm_module**: [blueprints/itsm_module.py](blueprints/itsm_module.py#L1-L200)
	- **Dashboard**: Present (`/`)
	- **Submit New**: Missing (ticket creation handled elsewhere / public forms)
	- **View**: Present (`/ticket/<ticket_number>`)
	- **Edit**: Partial (status update endpoints: `/ticket/<n>/update_status/<status>` and actions like assign/append_note)
	- **Delete**: Missing
	- **Export**: Missing
	- **Import**: Missing
	- **Search**: Missing
	- **Bulk Update**: Missing

- **serviceid_module**: [blueprints/serviceid_module.py](blueprints/serviceid_module.py#L1-L200)
	- **Dashboard**: Present (`/`)
	- **Submit New**: Present (`/submit-new`)
	- **View**: Present (`/profile/<uuid>`)
	- **Edit**: Present (`/edit/<uuid>`)
	- **Delete**: Present (`/delete/<uuid>`)
	- **Export**: Missing
	- **Import**: Present (`/import/csv`)
	- **Search**: Missing
	- **Bulk Update**: Missing

- **reports_module**: [blueprints/reports_module.py](blueprints/reports_module.py#L1-L200)
	- **Dashboard**: Present (`/dashboard`)
	- **Export**: Present (`/export/csv`)
	- Other standard CRUD routes: Not applicable / Missing

- **media_request_module**: [blueprints/media_request_module.py](blueprints/media_request_module.py#L1-L200)
	- **Submit New**: Present (`/`) public media request form
	- Other standard routes: Missing (module focuses on a single public form)

- **api_module**: [blueprints/api_module.py](blueprints/api_module.py#L1-L200)
	- **API/webhook endpoints**: Present (status, webhooks). Not a CRUD blueprint; standard UI routes not applicable.

**Findings & Recommendations**
- **Inconsistent coverage**: Some modules (crm, hr, serviceid, changes) implement most UI CRUD patterns; others (itsm, reports, media_request, api) are specialized.
- **Canonical route names**: Standardize on these endpoints where applicable: `/` (dashboard), `/submit-new`, `/<id>` (view), `/<id>/edit`, `/<id>/delete`, `/export` (or `/export/csv`), `/import` (or `/import/csv`), `/search`, `/bulk-update`.
- **Shared helpers**: Create small helpers in `local_handlers/` for common tasks: CSV export, import parsing, id normalization, permission checks, render helpers. This avoids duplicated code.
- **Placeholders**: Where modules currently have placeholder handlers (e.g., `appid_module`), implement real flows or keep a consistent `_render_not_implemented()` response across modules.
- **itsm ticket creation**: Decide whether ticket submit should live in `itsm_module` or remain in public modules (`media_request_module`) and document the chosen pattern.
- **Search & Bulk Update**: Add `/search` (GET) and `/bulk-update` (POST) to modules that manage lists (crm, serviceid, hr, changes) to enable consistent admin workflows.

**Next Steps (I can do)**
- Add a short `local_handlers/blueprint_helpers.py` with CSV export/import helpers and a `standard_routes.py` mixin to apply consistent endpoints.
- Open PR implementing missing placeholder routes as HTML stubs and wiring to helpers for one module (suggest starting with `changes_module`).
- Or, implement a checklist patch that adds route stubs for the missing endpoints across all blueprints.

Tell me which next step you want: add helpers, stub routes, or implement one module fully.

