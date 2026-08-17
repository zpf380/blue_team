"""API v1 路由聚合。"""
from fastapi import APIRouter

from app.api.v1 import ai, audit, auth, channels, departments, files, leaves, monitor, roles, stats, training, training_manage, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(departments.router)
api_router.include_router(roles.router)
api_router.include_router(stats.router)
api_router.include_router(channels.router)
api_router.include_router(ai.router)
api_router.include_router(files.router)
api_router.include_router(audit.router)
api_router.include_router(training.router)
api_router.include_router(training_manage.router)
api_router.include_router(monitor.router)
api_router.include_router(leaves.router)
