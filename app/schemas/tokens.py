from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPairSchema(Token):
    refresh_token: str


class RefreshTokenSchema(BaseModel):
    refresh_token: str