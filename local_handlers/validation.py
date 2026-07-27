import re
from typing import Dict, List, Tuple

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_fields(data: Dict[str, str], fields: List[str]) -> Tuple[bool, str]:
    """Ensure required fields are present and non-empty.

    Returns (True, "") on success or (False, "field_name") on missing field.
    """
    for field_name in fields:
        value = data.get(field_name)
        if value is None:
            return False, field_name
        if isinstance(value, str) and value.strip() == "":
            return False, field_name
    return True, ""


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    return bool(EMAIL_RE.match(email))
