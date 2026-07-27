#!/usr/bin/env python3
"""Centralized role-based auth decorators and helpers.
Keep small, readable, and testable.
"""
from functools import wraps
import logging
from flask import session, redirect, url_for, render_template

# Role constants
ROLE_ITSM_TECH = "itsm_technician"
ROLE_HR_TECH = "hr_technician"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"

DEFAULT_ROLES = [ROLE_ITSM_TECH, ROLE_HR_TECH, ROLE_MANAGER, ROLE_ADMIN]

logger = logging.getLogger(__name__)

def get_current_user() -> str | None:
    """Return the currently authenticated username or None."""
    return session.get("technician") or session.get("user_id")

def get_current_roles() -> list[str]:
    """Return a list of roles for the current session (never None)."""
    roles = session.get("roles")
    if not isinstance(roles, list):
        return []
    return roles

def user_has_role(role: str) -> bool:
    """Check if current session has `role`."""
    return role in get_current_roles()

def role_required(*required_roles: str, require_all: bool = False, redirect_to_login: bool = True):
    """Decorator factory to require one or more roles.
    Examples:
        @role_required(ROLE_ITSM_TECH)
        @role_required(ROLE_MANAGER, ROLE_ADMIN)
    Args:
        required_roles: one or more role strings.
        require_all: when True, user must have all roles; otherwise any role suffices.
        redirect_to_login: if True unauthenticated users are redirected to `login`.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            username = get_current_user()
            if not username:
                logger.debug("Unauthenticated access attempt to %s", getattr(func, "__name__", "<view>"))
                if redirect_to_login:
                    return redirect(url_for("login"))
                return render_template("errors/403.html"), 403

            roles = get_current_roles()

            # Admins and Managers bypass explicit role checks (global access)
            if ROLE_ADMIN in roles or ROLE_MANAGER in roles:
                logger.debug("RBAC bypass: user %s has elevated roles=%s; allowing access to %s", username, roles, getattr(func, '__name__', '<view>'))
                allowed = True
            # Special-case: wildcard role '*' → allow any authenticated user
            elif required_roles == ("*",) or any(required_role == "*" for required_role in required_roles):
                allowed = True
            else:
                if require_all:
                    allowed = all(required_role in roles for required_role in required_roles)
                else:
                    allowed = any(required_role in roles for required_role in required_roles)

            if not allowed:
                logger.warning("User %s lacks required role(s) %s for %s", username, required_roles, func.__name__)
                return render_template("errors/403.html"), 403

            # authorized
            logger.debug("User %s authorized for %s with roles=%s", username, func.__name__, roles)
            return func(*args, **kwargs)

        return wrapper

    return decorator
