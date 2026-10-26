"""Collects every route module into one router, so main.py includes just this one."""

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router)
# api_router.include_router(auth.router)   # next: /auth/register, /auth/login, /auth/refresh
