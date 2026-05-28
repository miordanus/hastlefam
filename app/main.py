from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.api.routers.health import router as health_router
from app.api.routers.tasks import router as tasks_router
from app.api.routers.finance import router as finance_router
from app.api.routers.reviews import router as reviews_router
from app.api.routers.auth import router as auth_router, verify_session, SESSION_COOKIE, login_page
from app.infrastructure.config.settings import get_settings
from app.infrastructure.logging.logger import configure_logging, get_logger
from app.observability.error_handler import unhandled_exception_handler

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger('api')

app = FastAPI(title=settings.app_name)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(finance_router)
app.include_router(reviews_router)
app.include_router(auth_router)

templates = Jinja2Templates(directory=str(Path(__file__).parent / 'dashboard' / 'templates'))

_UNPROTECTED_PREFIXES = ('/health', '/login', '/auth/')


@app.middleware('http')
async def auth_and_log(request: Request, call_next):
    logger.info('request.start', path=request.url.path, method=request.method)

    path = request.url.path
    needs_auth = path != '/' and not any(path.startswith(p) for p in _UNPROTECTED_PREFIXES)

    if needs_auth:
        token = request.cookies.get(SESSION_COOKIE, '')
        payload = verify_session(token) if token else None
        if payload is None:
            accept = request.headers.get('accept', '')
            if 'application/json' in accept:
                return JSONResponse({'detail': 'unauthorized'}, status_code=401)
            return RedirectResponse(url='/login', status_code=302)
        request.state.user_id = payload.get('uid')
        request.state.household_id = payload.get('hid')

    response = await call_next(request)
    logger.info('request.end', path=request.url.path, status_code=response.status_code)
    return response


@app.get('/')
def root(request: Request):
    token = request.cookies.get(SESSION_COOKIE, '')
    payload = verify_session(token) if token else None
    if payload and payload.get('hid'):
        return RedirectResponse(url=f"/finance/health?household_id={payload['hid']}", status_code=302)
    return login_page(request)
