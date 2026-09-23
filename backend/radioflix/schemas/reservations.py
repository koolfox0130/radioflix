from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

JST = ZoneInfo("Asia/Tokyo")


class Broadcast(BaseModel):
    id: str
    station: str = Field(pattern=r"^[A-Z0-9_-]{1,24}$")
    region: str = Field(default="JP13", pattern=r"^JP(?:[1-9]|[1-3][0-9]|4[0-7])$")
    title: str = Field(min_length=1, max_length=300)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def valid_dates(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Timezone is required")
        self.starts_at = self.starts_at.astimezone(JST)
        self.ends_at = self.ends_at.astimezone(JST)
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(hours=24):
            raise ValueError("Invalid duration")
        return self


class ReservationRequest(BaseModel):
    program_id: str = Field(min_length=1, max_length=1000)
    broadcast_id: str = Field(min_length=1, max_length=100)
    mode: Literal["once", "weekly"]


class RecordingError(Exception):
    def __init__(self, code: str, message: str, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.uncertain = uncertain
