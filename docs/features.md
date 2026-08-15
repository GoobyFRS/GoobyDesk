# GoobyDesk Features

## Ticket Submission and Management

- Requestor Name
- Requestor Contact Email
- Ticket Subject/Title
- Ticket Impact
  - Low, Medium, High
- Ticket Urgency
  - Planning, Low, Medium, High
- Ticket Message
- Ticket Category
  - Request, Incident, Maintenance, Change, Access
- Technician Dashboard listing all open tickets
- Ticket Console for viewing and working an individual ticket
- Status updates (Open, In-Progress, Closed), with closure actor and timestamp recorded automatically
- Technician work notes appended to a ticket's history
- Automatic ticket creation from inbound webhooks (see Integrations)

## Change Management

- Change request submission with:
  - Short and full description
  - Implementation plan
  - Test/acceptance plan
  - Rollback plan
  - Planned start and end date/time
  - Risk level (Low, Medium, High)
- Sequential change numbering (`CHG-YYYY-####`)
- Change dashboard listing all requests and their status
- CSV export of change requests

## Customer Management

- Customer records with contact info, address, company, and job title
- Sequential customer IDs (`CID-YYYY-####`)
- VIP, content creator, and marketing opt-in flags
- Discord and Minecraft username linking
- Support contract tracking (enabled, SLA, expiration)
- Lifetime value and billing currency tracking
- Assigned account manager and account tags/services lists
- Account security flags (email verified, account locked, MFA enabled)
- CRM dashboard with active customer and VIP stats

## Employee Management

- Employee records with contact info, address, and timezone
- Sequential employee IDs (`EMP-YYYY-####`)
- Employment details: title, department, business unit, employment type, compensation
- Bonus and raise history tracking
- Role-based access provisioning (ITSM Technician, HR Technician, Manager, Admin) with login credential creation
- HR work notes and dashboard

## Service Management

- Service/Application ID (APPID) registry for tracking service accounts and integrations
- Dashboard listing all registered service APPIDs

## Reporting

- Ticket volume dashboard with counts by status (Open, In-Progress, Closed)
- Ticket aging breakdown (last 7/14/30/60 days)
- Change request summary by status and risk level
- CSV export of ticket data

## Access Control

- Role-based access control (RBAC) with four roles: ITSM Technician, HR Technician, Manager, Admin
- Managers and Admins have elevated access across all modules
- Session-based authentication with password hashing

## Anti-Spam / Brute-Force Protection

Anti-Spam/Brute-Force implementation requires a CloudFlare Turnstiles Site Key and Secret Key.

## Integrations

End Users can get an email copy of their submitted Ticket IF you have email functionality setup and enabled.

New Tickets, and Ticket Status Updates can be sent to Discord and Slack channels.

GoobyDesk supports automatic ticket creation from webhooks, including:

- Tailscale
- Self-hosted Uptime-Kuma instances
- LibreNMS alert transport

A public API status endpoint (`/api/status`) is available for basic health checks.

## Notifications

### Email

### Slack

### Discord
