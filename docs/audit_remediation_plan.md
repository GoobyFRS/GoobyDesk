# Audit Remediation Plan

This document describes the plan to address three audit findings:

1. Centralize logging configuration.
2. Extract large helper logic out of blueprints (starting with the CRM record builder).
3. Harden input validation with small, reusable helpers.

The intent is that this plan can be implemented incrementally by a human or a
smaller model, one section at a time, without needing to re-derive the design.

---

## 1. Centralize Logging

### Problem

`app.py` and every blueprint (`api_module.py`, `changes_module.py`,
`crm_module.py`, `hr_module.py`, `itsm_module.py`, `reports_module.py`) and
`local_handlers/local_email_handler.py` each independently:

- Load `core_yaml_config` and re-read `LOG_LEVEL` / `LOG_FILE`.
- Call `logging.basicConfig(filename=LOG_FILE, level=..., format=...)`.

Since `logging.basicConfig()` only has an effect the *first* time it's called
per process, whichever module is imported first silently wins, and every
other call is a dead no-op. This is fragile (import order dependent),
duplicated across 7 files, and confusing to maintain.

### Plan

1. **Single source of truth in `app.py`.**
   - Keep reading `LOG_LEVEL` / `LOG_FILE` from `core_yaml_config["logging"]`
     in `app.py` as is done today (lines ~40-41).
   - Configure logging in `app.py` **before** any blueprint modules are
     imported, using `logging.basicConfig(...)` exactly once (already present
     around line 101 — just needs to move above the blueprint imports at the
     top of the file, or the blueprint imports need to move below it).

2. **Remove `logging.basicConfig(...)` calls from every blueprint and from
   `local_handlers/local_email_handler.py`.**
   - Delete the `logging.basicConfig(...)` blocks in:
     - `blueprints/api_module.py`
     - `blueprints/changes_module.py`
     - `blueprints/crm_module.py`
     - `blueprints/hr_module.py`
     - `blueprints/itsm_module.py`
     - `blueprints/reports_module.py`
     - `local_handlers/local_email_handler.py`
   - Also remove the now-unused `LOG_LEVEL` / `LOG_FILE` module-level
     variables in those files if nothing else in the file uses them.
   - Keep `import logging` and existing `logging.info/debug/warning/error(...)`
     calls unchanged — they will use the root logger configured by `app.py`.

3. **Do not re-load `core_yaml_config` just for logging in blueprints.**
   - If a blueprint only used `core_yaml_config` to get `LOG_LEVEL`/`LOG_FILE`,
     the `load_core_config()` call and `core_yaml_config` variable can be
     removed entirely, provided no other config values are needed in that
     file. Check each blueprint individually — some (e.g. `api_module.py`)
     also read other keys like `TAILSCALE_NOTIFY_EMAIL` and must keep the
     `load_core_config()` call for those.

4. **Verify ordering.** Because Flask blueprint modules run their
   module-level code (including any logging setup) at import time, and
   `app.py` currently imports blueprints near the top of the file before the
   `logging.basicConfig()` call, the import statements for the blueprints
   must be moved below the `logging.basicConfig()` call (or the config/
   logging setup moved above the imports). Confirm this doesn't break
   circular imports (`api_module.py` imports from `app` lazily inside a
   function already, so this is safe).

5. **Sanity check after the change:**
   - Start the app and trigger one log line from each affected blueprint
     (e.g. hit a CRM, ITSM, HR, Changes, Reports, and API route) and confirm
     entries appear in the configured `LOG_FILE` with the configured format
     and level.
   - Confirm no blueprint still references a `LOG_LEVEL`/`LOG_FILE` variable
     that was deleted.

### Files touched

- `app.py`
- `blueprints/api_module.py`
- `blueprints/changes_module.py`
- `blueprints/crm_module.py`
- `blueprints/hr_module.py`
- `blueprints/itsm_module.py`
- `blueprints/reports_module.py`
- `local_handlers/local_email_handler.py`

---

## 2. Extract Large Helpers (CRM Record Builder First)

### Problem

`blueprints/crm_module.py`'s `new_customer()` view function (route handler)
mixes HTTP concerns (form parsing, redirects, template rendering) with a large
inline dictionary literal (~40 fields) that builds the new customer record.
This makes the view function long, hard to unit test, and hard to reuse (e.g.
from a future API endpoint or import script) without duplicating the same
dictionary shape.

### Plan

1. **Create `local_handlers/crm_helpers.py`.**
   - This follows the existing convention of `local_handlers/` holding
     reusable, non-Flask-route logic (`local_authentication_handler.py`,
     `local_config_loader.py`, `local_email_handler.py`,
     `local_webhook_handler.py`).

2. **Move record-building logic into a pure function**, e.g.:
   - `build_customer_record(form, customers, technician, timestamp)` (exact
     signature/name can be adjusted, but it should:)
     - Accept the raw `request.form` (or a plain `dict`) plus whatever
       context it needs (`customers` list for ID generation, current
       technician for the note author, and a timestamp) as parameters —
       it must **not** reach into `flask.request` or `flask.session`
       directly, so it stays framework-agnostic and unit-testable.
     - Return the fully-built customer record `dict`, including the optional
       initial note.
     - Contain no side effects (no file I/O, no `logging` calls, no
       `save_customers_file`) — those stay in the blueprint.
   - Also consider moving `generate_customer_id(customers)` into the same
     helper module, since it's tightly coupled to record construction and is
     already a small, pure function.

3. **Update `blueprints/crm_module.py`:**
   - Import the new helper module: `import local_handlers.crm_helpers as crm_helpers`.
   - Replace the inline dict construction in `new_customer()` with a call to
     `crm_helpers.build_customer_record(...)`.
   - Keep the input presence-check (first name / last name / email required),
     `load_customers_file()`, `save_customers_file()`, the `logging.info(...)`
     call, and the `redirect(...)` in the blueprint — those are route-level
     orchestration, not record-building.

4. **Do not change the record schema.** This is a refactor, not a behavior
   change — the resulting `dict` shape, field names, and defaults must be
   identical to what's produced today, so existing stored customer JSON stays
   compatible.

5. **Optional follow-up (not required for this pass, but note for later):**
   scan other blueprints (`itsm_module.py`, `hr_module.py`, `changes_module.py`)
   for similarly large inline record/dict builders that could benefit from the
   same treatment once this pattern is proven out with CRM.

### Files touched

- `local_handlers/crm_helpers.py` (new)
- `blueprints/crm_module.py`

---

## 3. Harden Input Validation

### Problem

Input validation is inconsistent and duplicated across blueprints:

- `crm_module.py` manually strips and checks `first_name`, `last_name`,
  `email` for truthiness only (no email format check, no length limits).
- `itsm_module.py` checks `if not new_tkt_note` with no strip/trim.
- `api_module.py` checks `if not request.is_json` / `if not payload` but does
  no per-field validation.
- No shared helper exists for common checks (required field, email format,
  string length bounds, safe enum/choice values).

This means it's easy to add a new form field or endpoint and forget a
necessary check, and any fix to validation logic (e.g. tightening the email
regex) has to be repeated in multiple places.

### Plan

1. **Create small, focused validation helpers** in a new module, e.g.
   `local_handlers/validation_helpers.py` (or, if preferred, add them to the
   existing `local_handlers/goobydesk_standard_library.py` if that module is
   already the project's catch-all for shared utility functions — check its
   current contents before deciding, to avoid creating two competing "shared
   utils" modules).

2. **Helpers to implement (keep each one small and single-purpose):**
   - `require_fields(data: dict, fields: list[str]) -> list[str]` — returns
     the list of missing/blank field names (after `.strip()` for strings),
     so callers can build their own error message.
   - `is_valid_email(value: str) -> bool` — a conservative regex or
     `email.utils`-based check for a well-formed email address. Keep it
     simple; this is presence/format validation, not deliverability
     verification.
   - `clean_str(value: str | None, max_length: int | None = None) -> str` —
     strips whitespace, coerces `None` to `""`, and optionally truncates or
     rejects values over `max_length` (decide: truncate vs. reject — reject
     is safer and should be preferred, raising or returning `None`/error).
   - `is_within_length(value: str, min_length: int = 0, max_length: int = 255) -> bool`
     — bounds check to prevent unbounded input being written to the JSON
     "database" files.
   - Each helper must have a docstring (Google style, per project
     convention), type hints, and no side effects (pure functions only —
     no `flask.request`/`flask.session` access, no logging, no file I/O).

3. **Apply the helpers across blueprints**, replacing ad hoc checks:
   - `crm_module.py` `new_customer()`: use `require_fields(...)` for
     first/last name and email, and `is_valid_email(...)` for the email
     format check that's currently missing entirely.
   - `itsm_module.py`: wherever `new_tkt_note` (and similar single-field
     checks) are validated, use `clean_str(...)` + a presence check via
     `require_fields(...)`.
   - `api_module.py`: for JSON payload fields, use `require_fields(...)`
     against the parsed payload dict in addition to the existing
     `is_json`/`payload` truthiness checks.
   - `hr_module.py` / `changes_module.py`: audit their form-handling routes
     for the same ad hoc `.strip()` / `if not x` pattern and replace with the
     shared helpers where a matching route exists.

4. **Keep error handling behavior unchanged.** The goal is to centralize
   *how* validation is performed, not to change what is considered valid or
   how errors are surfaced to the user (same HTTP status codes, same
   templates/flash messages, same JSON error shapes for the API blueprint).

5. **Add lightweight tests if/where a test suite already exists.** If there
   is no existing test infrastructure in the repo, this can be deferred, but
   note it as a gap — pure functions with no Flask dependencies are cheap to
   unit test and would be a good first addition to a test suite.

### Files touched

- `local_handlers/validation_helpers.py` (new, or merged into
  `goobydesk_standard_library.py` — decide after inspecting that file)
- `blueprints/crm_module.py`
- `blueprints/itsm_module.py`
- `blueprints/api_module.py`
- `blueprints/hr_module.py` (if applicable)
- `blueprints/changes_module.py` (if applicable)

---

## Suggested Implementation Order

1. Logging centralization first — it's the lowest-risk, most mechanical
   change and immediately removes duplicated dead config calls.
2. CRM record builder extraction second — isolated to one blueprint, easy to
   verify against the existing record shape.
3. Validation helpers last — touches the most files, so doing it after the
   above two keeps the diff focused and lets each blueprint be updated one at
   a time with its own quick manual test (submit each affected form/endpoint
   before and after, confirm identical accepted/rejected behavior for
   existing valid and invalid inputs).

## Acceptance Criteria

- Only one `logging.basicConfig(...)` call remains in the entire codebase
  (in `app.py`), and it still uses `core_yaml_config["logging"]["level"]`
  and `["file"]`.
- `local_handlers/crm_helpers.py` exists, exports a pure customer-record
  builder function, and `crm_module.py`'s `new_customer()` uses it instead
  of an inline dict literal, with no change to the resulting record schema.
- A shared validation helper module exists and is imported by at least
  `crm_module.py`; other blueprints are updated where a natural fit exists.
- No existing route's accepted/rejected input behavior changes as an
  observable side effect of this refactor.
