from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.core.logging import setup_logging
from src.middleware.tracing import TracingMiddleware
from src.middleware.error_handler import CatchAllMiddleware
from src.middleware.metrics import MetricsMiddleware, metrics_endpoint

from src.middleware.error_handler import register_error_handlers
app = FastAPI(title ="Analytics Microservices")
setup_logging(level="INFO")


# Added first = innermost. Added last = outermost.
# Execution order for a request:
#   Tracing -> CatchAll -> Metrics -> route handler
app.add_middleware(MetricsMiddleware)     # innermost
app.add_middleware(CatchAllMiddleware)    # middle
app.add_middleware(TracingMiddleware)     # outermost

register_error_handlers(app)

app.add_route("/metrics", lambda request: metrics_endpoint(), methods=["GET"])


@app.get("/health")
async def health():
    return {"status": "ok"}