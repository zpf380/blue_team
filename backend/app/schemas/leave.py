"""考勤子系统 Schema：休假/外勤申请。"""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class LeaveCreate(BaseModel):
    leave_type: str = Field(pattern="^(on_leave|business_trip)$")
    start_at: dt.datetime
    end_at: dt.datetime
    reason: Optional[str] = Field(default=None, max_length=500)


class LeaveReviewIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=255)
