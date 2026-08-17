"""训练中心：课程管理 Schema。"""
from typing import Any

from pydantic import BaseModel, Field


class CourseGenerateIn(BaseModel):
    topic: str = Field(min_length=2, max_length=100, description="课程主题")


class CourseIn(BaseModel):
    """手动新建草稿课程（AI 生成外的兜底）。"""
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    difficulty: int = Field(default=1, ge=1, le=5)
    prerequisites: list[str] | None = None
    order_index: int = Field(default=0)


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    prerequisites: list[str] | None = None
    order_index: int | None = None


class ScenarioIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    scenario_type: str | None = None
    content: dict[str, Any] | None = None
    points: int = Field(default=10, ge=0)
    penalty_points: int = Field(default=5, ge=0)
    time_limit: int | None = None
    order_index: int = Field(default=0)


class ScenarioUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    scenario_type: str | None = None
    content: dict[str, Any] | None = None
    points: int | None = Field(default=None, ge=0)
    penalty_points: int | None = Field(default=None, ge=0)
    time_limit: int | None = None
    order_index: int | None = None
