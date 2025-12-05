# GoobyDesk

Simple, Lightweight, Databaseless Service Desk for Home Labbers, Families, and One Man MSPs.

**Current Version:**  v0.6.1

**Revision Date:** 2025.12.4

[GoobyDesk Repo Wiki](https://github.com/GoobyFRS/GoobyDesk/wiki) & [Production Deployment Guide](https://github.com/GoobyFRS/GoobyDesk/wiki/Production-Deployment-Guide).

## What is GoobyDesk

GoobyDesk is a Python3, Flask-based web application. Leverages Cloudflare Turnstile for Anti-Spam/Brute force protection.

- By default, the Flask app will run at ```http://127.0.0.1:5000``` during local development.
- Production instances should be ran behind a Python3 WSGI server such as [Gunicorn](https://gunicorn.org/).
- Production Gunicorn instances should be ran behind a Reverse Proxy such as [Caddy](https://caddyserver.com/).

Mobile-friendly landing page with lightweight ticket submission.

- Requestor Name
- Requestor Contact Email
- Ticket Subject/Title
- Ticket Impact
  - Low
  - Medium
  - High
- Ticket Urgency
  - Planning
  - Low
  - Medium
  - High
- Ticket Message
- Ticket Category
  - Request
  - Incident
  - Maintenance
  - Change
  - Access

New Ticket Created confirmation emails are sent from an inbox defined in a DOTENV file.

New Ticket Created confirmation emails are based on a clean HTML5 Jinja template that can be easily customized.

User email replies are appended to the ticket notes.

Technician Dashboard where logged in users can view Open Tickets and manage them.

Support for multiple technicians.

Closed Tickets are hidden from the Dashboard by default.

## Goals and Roadmap to Production v1.0

- Accept Uptime-Kuma webhooks for ticket creation. 
- Accept NewRelic webhooks for ticket creation. 
- Report Viewer with SLA tables.
- Easy toggle for email platform use. 
- Secure Technician passwords with hashing.
- Rate Limit without CloudFlare.
- High Quality User Input Sanitation.

### Linux Project Setup

```shell
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 ./app.py
```

CTRL+C to break. ```deactivate``` to clean up.

### Windows Project Setup

1. Comment out ```import fcntl``` line 11.
2. Comment out ```load_tickets``` lines 44-60.
3. Uncomment top ```load_tickets```. lines 35 - 42.
4. Enable Debugging at EOF.

```shell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

CTRL+C to break. ```deactivate``` to clean up.
