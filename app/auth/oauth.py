from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App

from app.core.config import get_settings
from app.db.models.enums import AuthProvider

oauth = OAuth()

_settings = get_settings()

if _settings.GOOGLE_CLIENT_ID and _settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name=AuthProvider.GOOGLE.value,
        client_id=_settings.GOOGLE_CLIENT_ID,
        client_secret=_settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def get_oauth_client(provider: AuthProvider) -> StarletteOAuth2App | None:
    return oauth.create_client(provider.value)
