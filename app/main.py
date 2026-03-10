from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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


@app.middleware('http')
async def log_requests(request: Request, call_next):
    logger.info('request.start', path=request.url.path, method=request.method)
    response = await call_next(request)
    logger.info('request.end', path=request.url.path, status_code=response.status_code)
    return response


@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})
