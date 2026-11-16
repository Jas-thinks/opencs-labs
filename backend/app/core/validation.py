"""Reusable validation types.

Pydantic's ``EmailStr`` rejects reserved development domains such as
``.local``. OpenCS must accept the institution's real addresses and also the
documented demo accounts, so address syntax is validated here and delivery is
never attempted.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def validate_email(value: str) -> str:
    value = (value or "").strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValueError("value is not a valid email address")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or ".." in value:
        raise ValueError("value is not a valid email address")
    return value


EmailAddress = Annotated[str, AfterValidator(validate_email)]
