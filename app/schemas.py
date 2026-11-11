from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import StaffRole, ThreatEnum


class CityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=25, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=25)


class CityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=25)


class CityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    threat: ThreatEnum
    monitoring_enabled: bool


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fcm_token: str = Field(min_length=1, max_length=4096)
    city: str = Field(default="dnipro", min_length=1, max_length=25, pattern=r"^[a-z][a-z0-9_-]*$")


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    city_id: int
    is_active: bool
    created_at: datetime


class ClassificationHistoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city_id: int = Field(gt=0)
    source_chat_id: int
    source_message_id: int = Field(gt=0)
    telegram_message: str = Field(min_length=1)
    first_answer: str
    final_answer: str
    threat: ThreatEnum | None
    occurred_at: datetime


class ClassificationHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    city_id: int
    source_chat_id: int
    source_message_id: int
    telegram_message: str
    first_answer: str
    final_answer: str
    threat: ThreatEnum | None
    occurred_at: datetime
    created_at: datetime


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    password: str = Field(min_length=12, max_length=128)
    role: StaffRole = StaffRole.ADMIN


class StaffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: StaffRole
    is_active: bool


class StaffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    role: StaffRole
    is_active: bool
    created_at: datetime
