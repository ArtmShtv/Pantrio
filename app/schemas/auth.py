import re
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

_USERNAME_RE = re.compile(r"[a-z0-9_.-]+")


def _check_username_chars(v: str) -> str:
    if not _USERNAME_RE.fullmatch(v):
        raise ValueError("may contain only letters a-z, digits, '_', '.' and '-'")
    return v

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=50,
    ),
    AfterValidator(_check_username_chars),
]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreateSchema(BaseModel):
    email: EmailStr
    username: Username
    password: Password

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "artem@example.com",
                    "username": "artem",
                    "password": "s3cret-pass"
                }
            ]
        }
    )


class UserReadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str


class UserLoginSchema(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
