"""Typed request and response models for authentication endpoints."""
import re
from pydantic import BaseModel, EmailStr, Field, field_validator

PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not PASSWORD_PATTERN.match(value):
            raise ValueError("Password must be at least 8 characters and include uppercase, lowercase, and a number.")
        return value


class Signup(Credentials):
    name: str = Field(min_length=1, max_length=120)


class Login(Credentials):
    remember: bool = False


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not PASSWORD_PATTERN.match(value):
            raise ValueError("Password must be at least 8 characters and include uppercase, lowercase, and a number.")
        return value


class VerifyToken(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class UserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    email_verified: bool
    role: str
