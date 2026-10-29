from pydantic import BaseModel


class Token(BaseModel):
    token_type: str = "bearer"
    access_token: str


class TokenPairSchema(Token):
    refresh_token: str


class RefreshTokenSchema(BaseModel):
    refresh_token: str