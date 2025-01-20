#!/usr/bin/env python3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json # My preffered method of "database" replacements.
import smtplib # Outgoing Email
import imaplib # Incoming Email
import email # Email
import threading # Monitor Email for Replies in the background
import time
import re # Regex Support for Email Replies
import os # Dotenv requirement.
import secrets # Securing Cookies/Session data on the client.
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.header import decode_header
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secretdemokey"

# Load environment variables from .env
load_dotenv(dotenv_path=".env")
TICKETS_FILE = os.getenv("TICKETS_FILE")
EMPLOYEE_FILE = os.getenv("EMPLOYEE_FILE")
IMAP_SERVER = os.getenv("IMAP_SERVER") # Provider IMAP Server Address
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT") # SEND FROM Email Address/Username
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App Password - No OAuth or OAuth2 support yet.
SMTP_SERVER = os.getenv("SMTP_SERVER") # Provider SMTP Server Address.
SMTP_PORT = os.getenv("SMTP_PORT") # Provider SMTP Server Port. Default is TCP/587.

# Read Tickets
def load_tickets():
    try:
        with open(TICKETS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_tickets(tickets):
    with open(TICKETS_FILE, "w") as f:
        json.dump(tickets, f, indent=4)

# Read the Employees Database
def load_employees():
    try:
        with open(EMPLOYEE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Generate new ticket number
def generate_ticket_number():
    tickets = load_tickets()
    current_year = datetime.now().year  # Get the current year dynamically
    ticket_count = str(len(tickets) + 1).zfill(4)  # Zero-padded ticket count
    return f"TKT-{current_year}-{ticket_count}"  # Format: TKT-YYYY-XXXX

# Send confirmation email
def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject # Subject provided by user input.
    msg["From"] = EMAIL_ACCOUNT # Email Account referenced at the top.
    msg["To"] = to_email # Email provided by user input.
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ACCOUNT, to_email, msg.as_string())
            #print("INFO - Confirmation email was successfully sent.")
    except Exception as e:
        print(f"ERROR - Email sending failed: {e}")

# extract_email_body is attempting to scrape the content of the "valid" TKT email replies. It skips attachments. I do not currently need this feature. 
def extract_email_body(msg):
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                continue  # Skip attachments

            if content_type == "text/plain":  # Prefer plaintext over HTML
                try:
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
                except Exception as e:
                    print(f"Error decoding email part: {e}")
                    continue
            elif content_type == "text/html" and not body:
                try:
                    body = part.get_payload(decode=True).decode(errors="ignore").strip()
                except Exception as e:
                    print(f"Error decoding HTML part: {e}")
                    continue
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore").strip()
        except Exception as e:
            print(f"Error decoding single-part email: {e}")

    return body

# fetch_email_replies logically occurs before extract_email_body which is above this comment in the code.
def fetch_email_replies():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD) # Graceful Email system login.
        mail.select("inbox") # Select the inbox for reading/monitoring.

        _status, messages = mail.search(None, "UNSEEN") # UNSEEN or ALL -- Only reading UNSEEN currently.
        email_ids = messages[0].split()

        tickets = load_tickets() # Read the tickets file into memory.
        
        for email_id in email_ids:
            _status, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")
                    
                    from_email = msg.get("From")
                    match_ticket_reply = re.search(r"(?i)\bTKT-\d{4}-\d+\b", subject)  # Match "TKT-YYYY-XXXX" with no case sensitivity and should accept RE: re: and whitespace.
                    ticket_id = match_ticket_reply.group(0) if match_ticket_reply else None # Cleans up the extracted ticket number so it doesn"t include "RE:".
                    #print(f"DEBUG - Extracted ticket ID: {ticket_id} from subject: {subject}")


                    if not ticket_id:
                        continue  # Skip if no valid ticket-id is found

                    body = extract_email_body(msg)

                    # Find the corresponding ticket
                    for ticket in tickets:
                        if ticket["ticket_number"] == ticket_id:
                            ticket["notes"].append({"message": body})
                            save_tickets(tickets)  # Save changes to the ticket-db
                            print(f"INFO - Updated ticket {ticket_id} with reply from {from_email}")
                            break
                        
        #save_tickets(tickets) # Commenting this out to prevent constant writing to the tickets.json file.
        mail.logout() # Graceful logout.
        #print("INFO - Email fetch job completed.")
    except Exception as e:
        print(f"Error fetching emails: {e}")

# Background email monitoring
def background_email_monitor():
    while True:
        fetch_email_replies()
        time.sleep(300)  # Wait for  emails every 5 minutes.

threading.Thread(target=background_email_monitor, daemon=True).start()

# BELOW THIS LINE IS RESERVED FOR FLASK APP ROUTES
# This is the "default" route for the home/index/landing page. This is where users submit a ticket.
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        subject = request.form["subject"]
        message = request.form["message"]
        request_type = request.form["type"]
        ticket_number = generate_ticket_number()
        
        new_ticket = {
            "ticket_number": ticket_number,
            "requestor_name": name,
            "requestor_email": email,
            "subject": subject,
            "message": message,
            "request_type": request_type,
            "status": "Open",
            "submission_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "notes": []
        }
        
        tickets = load_tickets() # Load the ticket-db into memory via a read operation.
        tickets.append(new_ticket)
        save_tickets(tickets) # Writes the new ticket into the tickets.json file.
        
        # Craft the initial email format. This will eventually be updated to support HTML email signatures.
        send_email(email, f"{ticket_number} - {subject}", f"Thank you for your request. Your new Ticket ID is {ticket_number}. You have provided the following details... {message}")
        
        return redirect(url_for("home"))
    
    return render_template("index.html")

# 
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        employees = load_employees()
        
        # If successful login, send to the dashboard.
        if username == employees.get("tech_username") and password == employees.get("tech_authcode"):
            session["technician"] = True
            return redirect(url_for("dashboard"))
        
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if not session.get("technician"): # If the local machine does not have a session token/cookie containing the 'technician' tag.
        # Placeholder line - I may add some sort of print statement for debug logging. Future standard logging should eventually be implemented.
        return redirect(url_for("login")) # Redirect them to the login page.
    
    tickets = load_tickets() # Load the ticket-db into memory via a read operation.
    # Filtering out tickets with the Closed Status.
    open_tickets = [ticket for ticket in tickets if ticket["status"].lower() != "closed"]
    return render_template("dashboard.html", tickets=open_tickets)

# Opens a ticket in raw json. This should be tweaked eventually.
@app.route("/ticket/<ticket_number>")
def ticket_detail(ticket_number):
    tickets = load_tickets() 
    ticket = next((t for t in tickets if t["ticket_number"] == ticket_number), None)
    if ticket:
        return jsonify(ticket)
    return "Ticket Number in the URL was not found", 404

# Removes the session cookie from the user browser, sending the Technician/user back to the login page.
@app.route("/logout")
def logout():
    session.pop("technician", None)
    return redirect(url_for("login")) # Send a logged out user back to the login page. This can be customized.

# Routine to close a ticket. This invloves a write operation to the tickets.json file.
@app.route("/close_ticket/<ticket_number>", methods=["POST"])
def close_ticket(ticket_number):
    if not session.get("technician"):  # Ensure only logged-in techs can close tickets.
        return jsonify({"message": "Unauthorized"}), 403
    tickets = load_tickets() # Loads tickets.json into memory.
    for ticket in tickets:
        if ticket["ticket_number"] == ticket_number: # Basic input validation.
            ticket["status"] = "Closed"
            save_tickets(tickets) # Writes to the tickets.json file.
            return jsonify({"message": f"Ticket {ticket_number} has been closed."}) # This appears to be a pop-up. I'm not sure I am happy with this.
        # If the ticket was not found....
    return jsonify({"message": "Ticket not found"}), 404

if __name__ == "__main__":
    app.run() #debug=True
