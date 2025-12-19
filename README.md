# GoobyDesk

The Ultimate Simple, Lightweight, Databaseless Service Desk for Home Labbers, Families, and One Man MSPs.

**Current Version:**  v0.7.5

**Revision Date:** 2025.12.19

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

- Accept NewRelic webhooks for ticket creation. 
- Reporting Module with SLA tables.
- Rate Limit without CloudFlare.
- High Quality User Input Sanitation.

### Mobile Landing Page

![Mobile_Landing_Page](https://github.com/user-attachments/assets/f83a13c1-e180-40e7-b911-67c866099bce)

### Login Page

![LoginPage](https://github.com/user-attachments/assets/9f31bdca-6711-49c4-90a3-829544b02194)

### Ticket Commander View

![Ticket_Commander_View](https://github.com/user-attachments/assets/bd0a8798-7cff-455b-8563-1dd0b77a9e2b)

### Email Template

![Email_Template](https://github.com/user-attachments/assets/70f4e4fa-dd39-45e5-bb15-7e71a298e773)

### Slack Alert

Image coming soon.

### Discord Alert

![Discord_Alert](https://github.com/user-attachments/assets/05010365-00fe-4ad6-a3eb-807909708f04)
