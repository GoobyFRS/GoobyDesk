# GoobyDesk

The Ultimate Simple, Lightweight, Databaseless Service Desk for Home Labbers, Families, and One Man MSPs.

**Current Version:**  v0.7.1

**Revision Date:** 2025.12.X

[GoobyDesk Repo Wiki](https://github.com/GoobyFRS/GoobyDesk/wiki) & [Production Deployment Guide](https://github.com/GoobyFRS/GoobyDesk/wiki/Production-Deployment-Guide).

## What is GoobyDesk

GoobyDesk is a Python3, Flask-based web application. Leverages Cloudflare Turnstile for Anti-Spam/Brute force protection. It has support for multiple technicians. It can send and receive email replies as well as send notifications to Slack and Discord! Accepts incoming webhooks from Tailscale and Uptime-Kuma!

Mobile-friendly landing page with lightweight ticket submission.

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

Simple YAML configuration!

New Ticket Created confirmation emails are based on a clean HTML5 Jinja template that can be easily customized. User email replies are appended to the ticket notes.

Technician Dashboard where logged in users can view Open Tickets and manage them. Closed Tickets are hidden from the Dashboard by default.

## Goals and Roadmap to Production v1.0

- Rework Webhook system
- Accept NewRelic webhooks for ticket creation. 
- Report Viewer with SLA tables.
- Secure Technician passwords with hashing.
- Rate Limit without CloudFlare.
- High Quality User Input Sanitation.
