from fastapi import Request
from fastapi.responses import JSONResponse
from app.infrastructure.logging.logger import get_logger

logger = get_logger('errors')


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error('unhandled.exception', path=str(request.url.path), error=str(exc))
    return JSONResponse(status_code=500, content={'detail': 'Internal server error'})
