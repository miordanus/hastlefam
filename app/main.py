import base64
import hmac
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from app.api.routers.health import router as health_router
from app.api.routers.tasks import router as tasks_router
from app.api.routers.finance import router as finance_router
from app.api.routers.reviews import router as reviews_router
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

templates = Jinja2Templates(directory=str(Path(__file__).parent / 'dashboard' / 'templates'))

_UNPROTECTED = {"/health", "/"}


@app.middleware('http')
async def auth_and_log(request: Request, call_next):
    logger.info('request.start', path=request.url.path, method=request.method)

    password = settings.dashboard_password
    if password and request.url.path not in _UNPROTECTED:
        auth = request.headers.get("Authorization", "")
        authorized = False
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                _, provided = decoded.split(":", 1)
                authorized = hmac.compare_digest(provided, password)
            except Exception:
                pass
        if not authorized:
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="hastlefam"'},
            )

    response = await call_next(request)
    logger.info('request.end', path=request.url.path, status_code=response.status_code)
    return response


@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})
