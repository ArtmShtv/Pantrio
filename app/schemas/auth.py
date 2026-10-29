import re
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
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


class UserUpdateSchema(BaseModel):
    # Unknown fields (email, password, is_active, ...) -> 422 instead of being
    # silently ignored, so the client learns they can't be changed here.
    model_config = ConfigDict(extra="forbid")

    username: Username | None = None

    @field_validator("username")
    @classmethod
    def username_not_null(cls, v: str | None) -> str:
        # Runs only when the field is sent; an explicit null is rejected.
        if v is None:
            raise ValueError("username cannot be null")
        return v