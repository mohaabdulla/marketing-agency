"""Motion footage for storyboard scenes: licensed stock video search (Pexels, Pixabay) and previews."""
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from video import stock
from video.projects import Strict
from video.routes.common import guard

router = APIRouter()
_SEARCHES = threading.BoundedSemaphore(2)


@router.get('/stock/status')
def stock_status():
    """Which stock libraries are configured on this computer, their licence terms, and why GIFs are not used."""
    return stock.status()


class StockSearchRequest(Strict):
    query: str = Field(min_length=1, max_length=100)
    orientation: Literal['landscape', 'portrait', 'square'] = 'landscape'
    min_seconds: float = Field(0, ge=0, le=60)
    provider: Literal['pexels', 'pixabay'] | None = None


@router.post('/stock/search')
def stock_search(body: StockSearchRequest):
    """Clips long enough for a scene, in its orientation. Only the search words are sent to the library."""
    if not _SEARCHES.acquire(blocking=False):
        raise HTTPException(429, 'Another stock search is running; try again in a moment')
    try:
        return dict(results=guard(stock.search, body.query, body.orientation, body.min_seconds, body.provider),
                    credit_note='Credit the creator and the library; the client kit lists every clip used.')
    finally:
        _SEARCHES.release()


@router.get('/stock/{provider}/{item_id}/preview')
def stock_preview(provider: str, item_id: str):
    return FileResponse(guard(stock.preview_path, provider, item_id), media_type='image/jpeg')
