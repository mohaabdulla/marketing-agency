"""The /api/video router.

Each route group lives in video/routes/; this module mounts them under one prefix behind the
same-origin check. server.py includes `router` in the FastAPI app.
"""
from fastapi import APIRouter, Depends

from core.security_headers import trusted_origin
from video.routes import brand, editing, footage, media, projects, storyboard

router = APIRouter(prefix='/api/video', tags=['video'], dependencies=[Depends(trusted_origin)])
for group in (storyboard, footage, media, projects, editing, brand):
    router.include_router(group.router)
