import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

_USERNAME_RE = re.compile(r"[a-z0-9_.-]+")


def _check_username_chars(v: str) -> str:
    if not _USERNAME_RE.fullmatch(v):
        raise ValueError("may contain only letters a-z, digits, '_', '.' and '-'")
    return v


# Lowercased so "Artem" and "artem" can't both be registered; the charset
# limit keeps out spaces and look-alike Unicode characters in public handles.
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=50,
    ),
    # Runs after strip/lowercase. A `pattern=` above would be checked against
    # the raw input, so "Artem" would be rejected instead of normalized.
    AfterValidator(_check_username_chars),
]

# max_length caps the work Argon2 does per request (an anti-DoS limit).
Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    email: EmailStr
    username: Username
    password: Password

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"email": "artem@example.com", "username": "artem", "password": "s3cret-pass"}
            ]
        }
    )


class UserRead(BaseModel):
    # from_attributes lets FastAPI build this from the SQLAlchemy User object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
