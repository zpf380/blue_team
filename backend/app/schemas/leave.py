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


class LeaveOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    user_id: int
    user_name: Optional[str] = None
    department_name: Optional[str] = None
    leave_type: str
    start_at: dt.datetime
    end_at: dt.datetime
    reason: Optional[str] = None
    status: str
    approver_id: Optional[int] = None
    approver_name: Optional[str] = None
    reviewed_note: Optional[str] = None
    reviewed_at: Optional[dt.datetime] = None
    completed_at: Optional[dt.datetime] = None
    created_at: dt.datetime
