"""训练子系统 Schema。"""
from pydantic import BaseModel, Field


class SandboxCommandIn(BaseModel):
    command: str = Field(min_length=1, max_length=500)
