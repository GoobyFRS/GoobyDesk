# AI Instructions

You are assisting with GoobyDesk. An open source, lightweight, databaseless, self-hosted ITSM Service Desk.

**Inspiration:**

**End Goal:** High quality self-hosted ITSM Service Desk for SMB Technology Departments, Managed IT Service Providers, and Home Labbers.

- Basic ITSM Ticketing
- Employee/User Management
- Basic ITSM Change Management
- Basic Customer Management
- Basic ITSM Application Management
- Push Notifications and Webhooks
- Reporting Module

**Entry Point:** `app.py`

**Setup:**

```shell
source venv/bin/activate
pip install -r requirements.txt
python3 flask run --debug
```

Always prefer:

- simplicity
- maintainability
- security
- readability
- never use single character variables


Never introduce unnecessary frameworks. Never add dependencies unless requested. When unsure, ask instead of inventing behavior.

Avoid global states.

Favor composition over inheritance.

Document public APIs.

Write production-quality code.

Use async only when it materially improves concurrency, responsiveness, or I/O scalability. Avoid unnecessary async complexity.

Comment out unused code. Do not delete it.

## Language Preference

- **Primary language**: Python 3
- **Secondary language**: vanilla HTML5/CSS3/JavaScript

### Naming Conventions

| Type | Convention | Example |
| --- | --- | --- |
| Variables | `snake_case` | `user_count`, `total_items` |
| Constants | `UPPERCASE` | `MAX_RETRIES`, `API_BASE_URL` |
| Functions | `snake_case` | `get_user_data()`, `calculate_total()` |
| Classes | `PascalCase` | `UsercodeManager`, `DataProcessor` |
| Private/Internal | `_leading_underscore` | `_internal_helper()`, `_cache` |
| Ignored variables | `_` prefix | `for _ in range(10)`, `x, _ = get_pair()` |
| Module constants | `SCREAMING_SNAKE_CASE` | `DEFAULT_TIMEOUT = 30` |

### Security Requirements

- Never hardcode secrets
- Use environment variables for configuration
- Validate all user input
- Escape or sanitize rendered content
- Prefer parameterized database queries
- Avoid shell=True in subprocess calls
- Use least-privilege principles
- Log security-relevant events

## Repository File Tree

```txt
├── AGENTS.md      # Code Quality Guidelines
├── app.py      # Primary Script
├── CHANGELOG      # unused
├── LICENSE
├── README.md      #
├── requirements.txt
├── .github/      #
│   └── copilot-instructions.md      # Repo specific guides
├── blueprints/      #
│   ├── __init__.py      #
│   ├── api_module.py      #
│   ├── changes_module.py      #
│   ├── crm_module.py      #
│   ├── hr_module.py      #
│   ├── itsm_module.py      #
│   ├── reports_module.py      #
│   └── serviceid_module.py      #
├── docs/      #
│   └── roadmap.md      #
├── example_data/      # EXAMPLE PRODUCTION DATA
├── helper_scripts/      #
│   ├── app_secret_maker.py      #
│   ├── basic_version_upgrade.sh      #
│   ├── first_time_setup.sh      # Debian Installer
│   └── migrate_changes.py      #
├── local_handlers/      #
│   ├── __init__.py      #
│   ├── auth_decorators.py      # RBAC Controls via Decorators.
│   ├── crm_helpers.py      #
│   ├── local_config_loader.py      #
│   ├── local_email_handler.py      #
│   ├── local_webhook_handler.py      #
│   ├── ticket_builder.py      #
│   ├── utils.py      # Password Hashing and Inbox Scraping
│   └── validation.py      #
├── prod_data/      # UNTRACKED PRODUCTION DATA
├── static/      #
│   ├── main.js      # JavaScript Operations and Public Alerts
│   ├── styles.css      # GitHub/W3 Inspired
│   └── img/      # Static Images
├── storage/      #
│   ├── __init__.py      #
│   ├── backup.py      #
│   ├── changes_store.py      #
│   ├── crm_store.py      # Customer Relations specific JSON operations.
│   ├── employee_store.py      #
│   ├── hr_store.py      # Employee Management specific JSON operations.
│   ├── json_store.py      # Basic JSON atomic storage controller.
│   ├── service_appid_store.py      # APPID specific JSON operations.
│   ├── ticket_store.py      # ITSM specific JSON operations.
│   └── validator.py      #
├── templates/      #
│   ├── new-ticket-email.html      #
│   ├── under_construction.html      #
│   ├── changes/      #
│   │   ├── changes_dashboard.html      #
│   │   └── submit_new.html      #
│   ├── crm/      # 
│   │   ├── crm_dashboard.html      #
│   │   ├── profile.html      #
│   │   └── submit_new.html      #
│   ├── errors/
│   │   ├── 400.html
│   │   ├── 403.html
│   │   ├── 404.html
│   │   └── 500.html
│   ├── hr/      #
│   │   ├── hr_dashboard.html      #
│   │   ├── profile.html      #
│   │   └── submit_new.html      #
│   ├── itsm/      #
│   │   ├── console.html      #
│   │   ├── dashboard.html      #
│   │   └── queue.html      #
│   ├── public/      #
│   │   ├── bouncer.html      #
│   │   ├── index.html      #
│   │   ├── login.html      #
│   │   └── signup.html      #
│   ├── reports/      #
│   │   └── reports_dashboard.html      #
│   └── services-appid/      #
│       ├── dashboard.html      #
│       ├── profile.html      #
│       └── submit_new.html      #
```
