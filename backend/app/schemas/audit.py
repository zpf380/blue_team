"""审计中心 Schema：合规报告。"""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class ReportCreate(BaseModel):
    report_type: str = Field(default="on_demand", pattern="^(daily|weekly|monthly|on_demand)$")
    date_from: Optional[dt.date] = None
    date_to: Optional[dt.date] = None
