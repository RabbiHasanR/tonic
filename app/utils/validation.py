import re

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_valid_email(value: str) -> bool:
    if not value or len(value) > 254:
        return False
    return _EMAIL_RE.match(value) is not None
