# Production Deployment Guide

## First Time Deploy Script (Automated)

```shell
cd /var/www/
git clone https://github.com/GoobyFRS/GoobyDesk.git
cd GoobyDesk/helper_scripts/
sudo chmod +x ./first_time_setup.sh
sudo ./first_time_setup.sh
```

## Debian 13 Setup Process (Manual)

This document will guide you through the process of deploying GoobyDesk for production use on a VPS. This has been tested on Linode and Oracle OCI.

```shell
cd /var/www/
git clone https://github.com/GoobyFRS/GoobyDesk.git
sudo chown caddy /var/www/GoobyDesk
sudo mkdir /var/www/GoobyDesk/prod_data
cp example_dotenv .env
cp seed_employee.json prod_data/employee.json
cp example_tickets.json prod_data/tickets.json
cp example_customer.json prod_data/customers.json
cp example_hr_file.json prod_data/hr_file.json
cp example_changes.json prod_data/changes.json
cp template_configuration.yml prod_data/configuration.yml
sudo touch /var/log/goobydesk.log
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

### GUNICORN Setup

Create a systemd service for Gunicorn. By default Gunicorn will use port 8000.

```sudo touch /etc/systemd/system/goobydesk.service```

Add the following content.

```shell
[Unit]
Description=Gunicorn Instance serving GoobyDesk
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=/var/www/GoobyDesk
Environment="PATH=/var/www/GoobyDesk/venv/bin"
ExecStart=/var/www/GoobyDesk/venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app

[Install]
WantedBy=multi-user.target
```

### Caddy Setup

Append the following to your Caddyfile.

```shell
subdomain.example.org {
        reverse_proxy 127.0.0.1:8000
        
        # Security headers
        header {
                # Remove server identification
                -Server
                
                # HSTS - Force HTTPS (Caddy handles this well at the edge)
                Strict-Transport-Security "max-age=86400; includeSubDomains; preload"
                
                # Prevent clickjacking
                X-Frame-Options "DENY"
                
                # Prevent MIME type sniffing
                X-Content-Type-Options "nosniff"
                
                # Enable browser XSS protection
                X-XSS-Protection "1; mode=block"
                
                # Control referrer information
                Referrer-Policy "strict-origin-when-cross-origin"
        }
        
        log {
                output file /var/log/caddy/access.log
                format json
        }
}
```

After creating the Caddyfile with logging, setup a log rotation config for the Caddy logs....

```shell
sudo nano /etc/logrotate.d/caddy
```

Append the following data to the Caddy log rotation config...

```txt
/var/log/caddy/access.log {
    size 10M
    rotate 12
    compress
    missingok
    notifempty
    copytruncate
}
```

### Troubleshooting

- ```sudo systemctl status goobydesk.service```
- ```sudo systemctl stop goobydesk.service```
- ```sudo systemctl start goobydesk.service```
- ```sudo systemctl restart goobydesk.service```
- ```tail -n 25 /var/log/goobydesk.log```

### How To Update Production to latest version

```shell
/your/desired/path/GoobyDesk
sudo systemctl stop goobydesk.service
git pull origin main
sudo systemctl start goobydesk.service
sudo systemctl status goobydesk.service
```

#### Uninstall GoobyDesk

- Stop Service.
- Remove applicable Caddyfile content.
- Delete goobydesk.service daemon.
- Delete GoobyDesk logs.
- Delete Caddy logs.
