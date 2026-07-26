"""API v1 aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import admin, crossings

api_router = APIRouter()
api_router.include_router(crossings.router)
api_router.include_router(admin.router)
