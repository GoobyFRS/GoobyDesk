# Webhook Documentation

GoobyDesk supports both **outbound** webhook notifications (sending ticket events to chat platforms) and **inbound** webhook ingestion (creating tickets automatically from third-party monitoring tools).

## Outbound Notifications

Outbound notifications fire whenever a ticket is created or its status changes (see `local_handlers/local_webhook_handler.py`). Each configured, enabled platform receives a short embed/attachment containing the ticket number, subject, and status.

### Discord

- Config keys: `discord.enabled`, `discord.webhook_url` in `configuration.yml`
- Sends an embed titled `New Ticket: <number> - Subject: <subject>` for new tickets, or `Ticket: <number> updated — Status: <status>` for updates
- Blue accent color for new tickets, yellow for status updates

### Slack

- Config keys: `slack.enabled`, `slack.webhook_url` in `configuration.yml`
- Sends an attachment using the same title format and color scheme as Discord

### Microsoft Teams

- Config keys: `teams365.enabled`, `teams365.webhook_url` in `configuration.yml`
- Support is present in `template_configuration.yml` but the sender is currently disabled/commented out in code; not yet functional

### Behavior Notes

- Notifications are best-effort: failures are logged and do not block ticket creation/updates
- Each platform is checked independently via `enabled` flags; disabled platforms are skipped
- Requests use a 5 second timeout and are sent as a simple `POST` with a JSON payload

## Inbound Webhook Ingestion

Inbound endpoints live under the `/api` blueprint (`blueprints/api_module.py`) and automatically create tickets from external systems. All endpoints expect a JSON body and are unauthenticated, so restrict access at the network/reverse-proxy layer.

### `POST /api/tailscale`

- Creates a `Change` request ticket from any Tailscale webhook payload
- Requestor is set to `Tailscale`; notification email comes from `email.tailscale_notify_email`
- Impact/Urgency default to `Medium`

### `POST /api/uptime-kuma`

- Creates an `Incident` ticket for Uptime-Kuma heartbeat events
- Only `DOWN` (status `0`) and `PENDING` (status `2`) heartbeats create tickets; `UP` and `MAINTENANCE` are ignored
- `DOWN` events are `High` impact/urgency; `PENDING` events are `Medium` impact/urgency
- Requestor is set to `Uptime Kuma`

### `POST /api/librenms`

- Creates an `Incident` ticket from LibreNMS's default alert-transport payload
- Only newly-triggered alerts (`state == 1`) create a ticket; recoveries/acknowledgements are ignored
- `critical` severity maps to `High` impact/urgency, otherwise `Medium`
- Requestor is set to `LibreNMS`; notification email comes from `email.librenms_notify_email`

### `GET /api/status`

- Simple health/identification endpoint
- Returns `{"is_GoobyDesk": true, "installed": true, "edition": "community", "license_key": null}`

### Common Behavior for Inbound Endpoints

- Successful ingestion returns `{"status": "success", "ticket": "<ticket_number>"}`
- Untracked states/statuses return `{"status": "ignored", "reason": "..."}` with HTTP 200
- Malformed/empty payloads return HTTP 400
- Unexpected errors are logged with a correlation ID and return HTTP 500 without leaking internal details
- Raw payloads are never logged directly; only opaque hashed identifiers appear in logs
- Every successfully created ticket triggers the outbound notification flow described above
