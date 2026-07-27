#!/usr/bin/env python3
"""Shared utility helpers for local handlers.
Provides small, pure helpers for authentication and email parsing so
duplicate implementations can be removed from individual modules.
"""
from __future__ import annotations
import logging
import bcrypt
from email import message_from_bytes

__all__ = ["hash_password", "verify_password", "extract_email_body", "resolve_preferred_name"]


def resolve_preferred_name(technician_username: str) -> str:
    """Resolve a login username to the HR preferred name when possible.

    Falls back to the original username if no HR mapping exists or on error.
    """
    if not technician_username:
        return technician_username or ""
    try:
        # Local import to avoid startup cycles
        from local_handlers.local_config_loader import load_core_config
        from storage.employee_store import EmployeeStore
        from storage.hr_store import HrStore

        cfg = load_core_config()
        emp_store = EmployeeStore(cfg["core"]["employee_auth_file"])
        auth_employees = emp_store.load_all()
        lowered = technician_username.lower()
        auth = next(
            (
                auth_employee
                for auth_employee in auth_employees
                if str(auth_employee.get("tech_username", "")).lower() == lowered
            ),
            None,
        )
        if not auth:
            return technician_username
        user_uuid = auth.get("uuid")
        if not user_uuid:
            return technician_username
        hr_store = HrStore(cfg["core"]["hr_file"])
        hr_employees = hr_store.load_all()
        hr_employee = next(
            (
                hr_record
                for hr_record in hr_employees
                if hr_record.get("uuid") == user_uuid
            ),
            None,
        )
        if not hr_employee:
            return technician_username
        return hr_employee.get("preferred_name") or hr_employee.get("first_name") or technician_username
    except Exception:
        return technician_username

def hash_password(plain_password: str) -> str:
    """Hash a password using bcrypt and return the UTF-8 decoded hash.
    Args:
        plain_password: The plain text password to hash.
    Returns:
        The bcrypt hash as a string.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Verify a plain password against a stored bcrypt hash.
    Args:
        plain_password: The plain text password to verify.
        stored_hash: The stored bcrypt hash.
    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        logging.exception("Password verification failed due to exception")
        return False

def extract_email_body(msg) -> str:
    """Extract a best-effort email body (prefer plain text, fallback to html).
    Args:
        msg: An email.message.Message instance (or bytes that will be parsed by callers).
    Returns:
        A string with the extracted body (may be empty on failure).
    """
    body = ""
    try:
        # If callers pass raw bytes, convert to Message
        if isinstance(msg, (bytes, bytearray)):
            msg = message_from_bytes(msg)

        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdisp = str(part.get("Content-Disposition"))
                if "attachment" in cdisp:
                    continue
                try:
                    if ctype == "text/plain":
                        return part.get_payload(decode=True).decode(errors="ignore").strip()
                    elif ctype == "text/html" and not body:
                        body = part.get_payload(decode=True).decode(errors="ignore").strip()
                except Exception:
                    logging.warning("Failed decoding email part")
        else:
            try:
                body = msg.get_payload(decode=True).decode(errors="ignore").strip()
            except Exception:
                logging.error("Failed decoding email payload")
    except Exception:
        logging.exception("extract_email_body failed")

    return body
