# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from app.schemas.user import UserRead

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = Field(default="bearer")
    expires_in: int
    user: UserRead


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenRefresh(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer")
    expires_in: int


class VerifyEmailRequest(BaseModel):
    email: EmailStr  # Más estricto que str para validación automática


class OAuthUpsertRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=100)
    sub: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    picture: HttpUrl | None = None
    email_verified: bool | None = None


class OAuthTokenExchangeRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=100)
    id_token: str = Field(..., min_length=32)


class OAuthProviderConfig(BaseModel):
    provider: str
    client_id: str


class OAuthFrontendConfigResponse(BaseModel):
    providers: list[OAuthProviderConfig]
