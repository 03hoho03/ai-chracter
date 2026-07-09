import uuid

from pydantic import EmailStr

from api.core.schema import CamelModel


class AdminLoginRequest(CamelModel):
    email: EmailStr
    password: str


class AdminMeResponse(CamelModel):
    id: uuid.UUID
    email: str
