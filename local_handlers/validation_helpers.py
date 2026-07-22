#!/usr/bin/env python3
"""Small, reusable input validation helpers shared across blueprints.

These helpers are pure functions with no Flask, session, or file I/O
dependencies, so they can be unit tested in isolation and reused wherever
form or JSON input needs to be validated.
"""
import re

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_str(value: str | None, max_length: int | None = None) -> str:
    """Strip whitespace from a string value, coercing ``None`` to ``""``.

    Args:
        value: The raw value to clean. ``None`` is treated as an empty
            string.
        max_length: If provided, the cleaned string is truncated to this
            length.

    Returns:
        The stripped (and optionally truncated) string.
    """
    cleaned = (value or "").strip()
    if max_length is not None:
        cleaned = cleaned[:max_length]
    return cleaned


def is_within_length(value: str, min_length: int = 0, max_length: int = 255) -> bool:
    """Check whether a string's length falls within the given bounds.

    Args:
        value: The string to check.
        min_length: Minimum allowed length, inclusive.
        max_length: Maximum allowed length, inclusive.

    Returns:
        True if ``min_length <= len(value) <= max_length``.
    """
    return min_length <= len(value) <= max_length


def is_valid_email(value: str) -> bool:
    """Check whether a string looks like a well-formed email address.

    This is a conservative presence/format check only. It does not verify
    deliverability or perform DNS/MX lookups.

    Args:
        value: The email address to validate.

    Returns:
        True if the value matches a basic ``local@domain.tld`` shape.
    """
    return bool(value) and bool(_EMAIL_PATTERN.match(value))


def require_fields(data: dict, fields: list[str]) -> list[str]:
    """Determine which required fields are missing or blank in ``data``.

    Args:
        data: A mapping of field names to submitted values (e.g.
            ``request.form`` or a parsed JSON payload).
        fields: The list of field names that must be present with a
            non-blank value.

    Returns:
        The list of field names that are missing, ``None``, or blank after
        stripping whitespace (for string values). Empty if all fields are
        present.
    """
    missing = []
    for field in fields:
        value = data.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing
