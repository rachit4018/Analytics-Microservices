from fastapi import FastAPI
from src.core.logging import setup_logging
from src.middleware.tracing import TracingMiddleware
from src.middleware.error_handler import CatchAllMiddleware
from src.middleware.metrics import MetricsMiddleware, metrics_endpoint
from contextlib import asynccontextmanager
from src.models.session import engine
from src.api.health import router as health_router
from src.api.events import router as event_router
from src.middleware.error_handler import register_error_handlers
from src.api.anomalies import router as anomalies_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Analytics Microservice",
    lifespan=lifespan,
)

setup_logging(level="INFO")

app.add_middleware(MetricsMiddleware)
app.add_middleware(CatchAllMiddleware)
app.add_middleware(TracingMiddleware)

register_error_handlers(app)

app.add_route("/metrics", lambda request: metrics_endpoint(), methods=["GET"])

app.include_router(health_router)
app.include_router(event_router)
app.include_router(anomalies_router)
