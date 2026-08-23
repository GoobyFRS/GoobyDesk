# Implement 3 Queues Plan

Goal: introduce **Support**, **Escalation**, and **Billing** ticket queues, an
**Assign to Me** button, and a per-technician "My Tickets" dashboard.

This plan is written for a smaller model to execute step by step. Follow the
steps in order. Each step lists the exact file(s) to change and what to
change. Do not skip normalization/migration steps or existing tickets will be
missing fields.

## 0. Current State (read this first)

- `storage/ticket_store.py` (`TicketStore`) normalizes every ticket on
  read/write via `_normalize_ticket`. This is the correct place to backfill
  new fields for old tickets.
- `local_handlers/ticket_builder.py` (`build_ticket_record`) builds new
  tickets for the web form, API, and media requests. This is the correct
  place to set defaults for brand-new tickets.
- `blueprints/itsm_module.py` has the dashboard, ticket console, status
  update, and note routes. It currently has no queue routes and no assign
  routes.
- `templates/itsm/dashboard.html` lists all open tickets (no queue
  filtering, no "assigned to me" filtering).
- `templates/itsm/queue.html` exists but has **no body content** (head only).
  It is not wired to any route yet.
- `blueprints/reports_module.py` already has a `VALID_TICKET_QUEUES = {
  "support", "escalation", "billing"}` set and `_summarize_queue_counts`,
  but it incorrectly reads `ticket.get("request_type")` for the queue name.
  `request_type` is the ticket **type** (Incident/Request/Change/etc.), not
  the queue. This must be fixed to read the new `ticket_queue` field
  instead (see Step 5).

## 1. New Ticket Fields

Add two new fields to every ticket:

- `ticket_queue`: one of `"support"`, `"escalation"`, `"billing"`. Defaults
  to `"support"` for all newly created tickets.
- `assigned_to`: technician username string, or `None` when unassigned.

The existing `ticket_acknowledged_timestamp` field (already present, always
`None` today) will be used as the assignment acknowledgement timestamp — it
gets set the first time a ticket is assigned.

### 1a. `local_handlers/ticket_builder.py`

In `build_ticket_record`, add the two new fields to the returned dict
(near `"ticket_status": "open"`):

```python
"ticket_queue": "support",
"assigned_to": None,
```

Leave `"ticket_acknowledged_timestamp": None` as-is — it will be set later
by the assign route.

### 1b. `storage/ticket_store.py`

In `TicketStore._normalize_ticket`, backfill the new fields for tickets that
predate this change, so old JSON data does not crash the templates:

```python
@staticmethod
def _normalize_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    ticket.setdefault("ticket_notes", [])
    ticket.setdefault("ticket_worknotes", list(ticket.get("ticket_notes", [])))
    ticket.setdefault("ticket_resolution_notes", [])
    ticket.setdefault("ticket_queue", "support")
    ticket.setdefault("assigned_to", None)
    ticket.setdefault("ticket_acknowledged_timestamp", None)
    return ticket
```

## 2. Backend Routes — `blueprints/itsm_module.py`

### 2a. Add a queue filter helper

Add a module-level constant and helper near the top (after
`_pseudonymize_actor`):

```python
VALID_QUEUES = ("support", "escalation", "billing")

def _filter_by_queue(tickets: list[dict], queue_name: str) -> list[dict]:
    """Return open tickets belonging to the given queue."""
    return [
        t for t in tickets
        if (t.get("ticket_queue", "support") or "support").lower() == queue_name
        and (t.get("ticket_status", "") or "").lower() != "closed"
    ]
```

### 2b. Rewrite the dashboard route to show "my tickets"

Replace the existing `dashboard()` view so it shows tickets assigned to the
logged-in technician by default, and pass queue links to the template:

```python
@itsm_module_bp.route("/", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def dashboard():
    """Render ITSM dashboard with tickets assigned to the current technician."""
    logged_in_tech = resolve_preferred_name(session.get("technician"))
    tickets = load_tickets()
    my_tickets = [
        t for t in tickets
        if (t.get("ticket_status", "") or "").lower() != "closed"
        and t.get("assigned_to") == session.get("technician")
    ]
    return render_template(
        "itsm/dashboard.html",
        tickets=my_tickets,
        loggedInTech=logged_in_tech,
    )
```

Note: `assigned_to` is compared against `session.get("technician")` (the raw
username used elsewhere for role checks), not the display name, to stay
consistent with how `role_required`/`get_current_user` identify users.

### 2c. Add queue routes

Add three routes. `/queue` and `/queue/support` render the same view:

```python
@itsm_module_bp.route("/queue", methods=["GET"])
@itsm_module_bp.route("/queue/support", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def queue_support():
    """Render the Support queue."""
    tickets = load_tickets()
    return render_template(
        "itsm/queue.html",
        tickets=_filter_by_queue(tickets, "support"),
        queue_name="Support",
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )

@itsm_module_bp.route("/queue/escalation", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def queue_escalation():
    """Render the Escalation queue."""
    tickets = load_tickets()
    return render_template(
        "itsm/queue.html",
        tickets=_filter_by_queue(tickets, "escalation"),
        queue_name="Escalation",
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )

@itsm_module_bp.route("/queue/billing", methods=["GET"])
@role_required(ROLE_ITSM_TECH)
def queue_billing():
    """Render the Billing queue."""
    tickets = load_tickets()
    return render_template(
        "itsm/queue.html",
        tickets=_filter_by_queue(tickets, "billing"),
        queue_name="Billing",
        loggedInTech=resolve_preferred_name(session.get("technician")),
    )
```

Remove the dead commented-out `"""..."""` block near the bottom of the file
that references `/queue/support`, `/queue/escalation`, `/queue/billing` as a
triple-quoted no-op — it is replaced by the routes above.

### 2d. Add the "Assign to Me" route

Add this route after `add_ticket_note`:

```python
@itsm_module_bp.route("/ticket/<ticket_number>/assign_to_me", methods=["POST"])
@role_required(ROLE_ITSM_TECH)
def assign_ticket_to_me(ticket_number):
    """Assign a ticket to the logged-in technician and timestamp acknowledgement.
    Args:
        ticket_number (str): The ticket number to assign.
    Returns:
        JSON confirmation on success, or 404 if the ticket does not exist.
    """
    technician_username = session.get("technician")
    logged_in_tech = resolve_preferred_name(technician_username)
    store = _get_ticket_store()

    def _updater(record: dict):
        record["assigned_to"] = technician_username
        if not record.get("ticket_acknowledged_timestamp"):
            record["ticket_acknowledged_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return record

    changed = store.update(lambda record: record.get("ticket_number") == ticket_number, _updater)
    if not changed:
        return jsonify({"message": "Ticket not found."}), 404

    logging.info("Ticket %s assigned to %s.", ticket_number, _pseudonymize_actor(logged_in_tech))
    return jsonify({"message": f"Ticket {ticket_number} assigned to {logged_in_tech}."})
```

Only the acknowledgement timestamp is set on **first** assignment
(re-assigning a ticket to someone else later does not reset it) — this
matches "assigning a ticket should timestamp the acknowledgement" as a
first-touch SLA marker.

## 3. Templates

### 3a. `templates/itsm/dashboard.html`

- Change heading from "Technician Dashboard" to "My Tickets".
- Add a queue navigation block above the ticket list linking to the three
  queues:

```html
<nav class="queue-links">
    <a href="{{ url_for('itsm.queue_support') }}">Support Queue</a> |
    <a href="{{ url_for('itsm.queue_escalation') }}">Escalation Queue</a> |
    <a href="{{ url_for('itsm.queue_billing') }}">Billing Queue</a>
</nav>
```

Keep the rest of the template (close-ticket box, logout, footer) unchanged.

### 3b. `templates/itsm/queue.html`

This template currently has no `<body>`. Add one, modeled on
`dashboard.html`, that:

- Displays `queue_name` in the heading (e.g. "Support Queue").
- Lists `tickets` with subject/status like the dashboard.
- Shows `assigned_to` (or "Unassigned") per ticket.
- Adds an **Assign to Me** button per ticket that is unassigned or assigned
  to someone else, calling a new JS function `assignTicketToMe(ticketNumber)`.

Example body:

```html
<body>
    <main class="container">
        <div class="logo">
            <img src="{{ url_for('static', filename='/img/logo_white.webp') }}" alt="GoobyDesk Logo">
        </div>
        <h2>{{ queue_name }} Queue</h2>
        <nav class="queue-links">
            <a href="{{ url_for('itsm.dashboard') }}">My Tickets</a> |
            <a href="{{ url_for('itsm.queue_support') }}">Support</a> |
            <a href="{{ url_for('itsm.queue_escalation') }}">Escalation</a> |
            <a href="{{ url_for('itsm.queue_billing') }}">Billing</a>
        </nav>
        <ul class="ticket-list">
            {% for ticket in tickets %}
                <li>
                    <a href="{{ url_for('itsm.ticket_detail', ticket_number=ticket.ticket_number) }}">
                        {{ ticket.ticket_number }} - {{ ticket.ticket_subject }} ({{ ticket.ticket_status }})
                    </a>
                    &mdash; Assigned to: {{ ticket.assigned_to or "Unassigned" }}
                    <button class="assign-btn inline-btn" onclick="assignTicketToMe('{{ ticket.ticket_number }}')">Assign to Me</button>
                </li>
            {% else %}
                <li class="text-muted">No tickets in this queue.</li>
            {% endfor %}
        </ul>
        <form action="{{ url_for('logout') }}" method="GET">
        <button type="submit" class="submit-btn">Logout</button>
        </form>
        <p class="footer-text">©2025 GoobyDesk, FOSS created by GoobyFRS | Logged In as: {{ loggedInTech }} |
            <br>
            <a href="{{ url_for('itsm.dashboard') }}">Queues</a> | <a href="{{ url_for('changes_module.changes_home') }}">Changes</a> | <a href="{{ url_for('crm_module.crm_dashboard') }}">CRM</a> | <a href="{{ url_for('hr_module.hr_dashboard') }}">HR</a> | <a href="{{ url_for('serviceid_module.serviceid_dashboard') }}">ServiceID</a> | <a href="{{ url_for('reports_module.reports_home') }}">Reports</a>
        </p>
    </main>
</body>
</html>
```

### 3c. `templates/itsm/console.html`

Add an assignment line and button in the `.ticket-details` block and
button row:

```html
<p><strong>Assigned To:</strong> {{ ticket.assigned_to or "Unassigned" }}</p>
```

```html
<button class="assign-btn" onclick="assignTicketToMe('{{ ticket.ticket_number }}')">Assign to Me</button>
```

## 4. `static/main.js`

Add a new function following the existing style of `updateTicketStatus`:

```javascript
/**
 * Assigns a ticket to the currently logged-in technician
 * @param {string} ticketNumber - The ticket number to assign
 * @returns {Promise<void>}
 */
async function assignTicketToMe(ticketNumber) {
    try {
        let response = await fetch(`/itsm/ticket/${ticketNumber}/assign_to_me`, {
            method: "POST",
            headers: { "Accept": "application/json" }
        });

        let data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || "Unknown error");
        }

        alert(data.message);
        location.reload();
    } catch (error) {
        console.error("Error:", error);
        alert("An error occurred while assigning the ticket. Please try again.");
    }
}
```

## 5. Fix `blueprints/reports_module.py` queue counting

`_summarize_queue_counts` currently reads `ticket.get("request_type")` to
determine the queue, which is wrong — `request_type` is the ticket type
(Incident/Request/Change), not the queue. Change it to read the new
`ticket_queue` field:

```python
def _summarize_queue_counts(tickets: list[dict]) -> dict[str, int]:
    """Summarize active (non-closed) ticket counts grouped by queue (Support/Escalation/Billing only)."""
    queue_counts: dict[str, int] = {}
    for ticket in tickets:
        if (ticket.get("ticket_status", "") or "").lower() == "closed":
            continue
        queue = str(ticket.get("ticket_queue", "") or "").strip()
        if queue.lower() not in VALID_TICKET_QUEUES:
            continue
        queue_counts[queue] = queue_counts.get(queue, 0) + 1
    return queue_counts
```

## 6. Migration of existing production data

`prod_data/tickets.json` and `example_data/seed_tickets.json` predate this
change and have no `ticket_queue`/`assigned_to` fields. Step 1b's
`_normalize_ticket` backfill handles this automatically on next read/write
— no manual migration script is required. Do not hand-edit the JSON files.

## 7. Testing Checklist

Add/extend tests under `tests/` (see existing `tests/test_changes_detail.py`
for the project's test style/fixtures) to cover:

- New tickets default to `ticket_queue == "support"` and `assigned_to is None`.
- `/itsm/queue`, `/itsm/queue/support`, `/itsm/queue/escalation`,
  `/itsm/queue/billing` each return 200 and only show tickets from the
  correct queue.
- `/itsm/` (dashboard) only shows tickets where `assigned_to` matches the
  logged-in technician.
- `POST /itsm/ticket/<ticket_number>/assign_to_me`:
  - sets `assigned_to` to the logged-in technician,
  - sets `ticket_acknowledged_timestamp` on first assignment,
  - does **not** overwrite `ticket_acknowledged_timestamp` if already set
    when re-assigned,
  - returns 404 for an unknown ticket number,
  - is rejected for unauthenticated requests (via `role_required`).
- Old-format ticket records (missing `ticket_queue`/`assigned_to`) load
  without error and are normalized to `"support"` / `None`.

## Summary of Files Touched

- `local_handlers/ticket_builder.py` — default new fields.
- `storage/ticket_store.py` — normalize/backfill new fields.
- `blueprints/itsm_module.py` — dashboard filter, 3 queue routes, assign route.
- `templates/itsm/dashboard.html` — "My Tickets" heading + queue links.
- `templates/itsm/queue.html` — new body: queue list + Assign to Me button.
- `templates/itsm/console.html` — show assignment + Assign to Me button.
- `static/main.js` — `assignTicketToMe()` function.
- `blueprints/reports_module.py` — fix queue counting to use `ticket_queue`.
- `tests/` — new/extended coverage per Section 7.
