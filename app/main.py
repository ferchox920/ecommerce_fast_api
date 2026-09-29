import logging  # <-- Importar logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.error_handlers import register_exception_handlers
from app.api.deps import get_current_admin
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.metrics import export_metrics
from app.db.session_async import AsyncSessionLocal
from app.api.routers import (
    admin,
    admin_product_questions,
    admin_promotions,
    analytics,
    auth,
    brands,
    categories,
    cart,
    engagement,
    exposure,
    notifications,
    payments,
    promotions,
    product_questions,
    products,
    scoring,
    orders,
    loyalty,
    purchases,
    reports,
    users,
    variants,
    wishes,
)
from app.api.ws import notifications as ws_notifications
from app.middleware import ObservabilityMiddleware, PayloadLimitMiddleware, SecurityHeadersMiddleware
from app.initial_data import create_initial_admin_user  # <-- Importar

# --- Models registration (necesario para que Alembic los detecte) ---
# Es importante importar todos los modelos para que SQLAlchemy los conozca
import app.models.product        # noqa: F401
import app.models.inventory      # noqa: F401
import app.models.supplier     # noqa: F401
import app.models.purchase     # noqa: F401
import app.models.order          # noqa: F401
import app.models.cart           # noqa: F401
import app.models.product_question  # noqa: F401
import app.models.notification      # noqa: F401
import app.models.engagement        # noqa: F401
import app.models.promotion         # noqa: F401
import app.models.loyalty           # noqa: F401
import app.models.wish              # noqa: F401
import app.models.user              # noqa: F401


# --- Metadatos de la API para la documentacion ---
TAGS_METADATA = [
    {"name": "auth", "description": "Autenticacion, tokens y gestion de sesiones."},
    {"name": "users", "description": "Operaciones del perfil de usuario."},
    {"name": "admin", "description": "Operaciones de administracion de usuarios."},
    {"name": "admin-promotions", "description": "Gestion de promociones (administracion)."},
    {"name": "products", "description": "Gestion y consulta del catalogo de productos."},
    {"name": "categories", "description": "Gestion de categoriasias de productos."},
    {"name": "brands", "description": "Gestion de marcas."},
    {"name": "variants", "description": "Gestion de variantes de productos (SKU, stock, etc.)."},
    {"name": "purchases", "description": "Gestion de proveedores y ordenes de compra."},
    {"name": "orders", "description": "Ordenes de venta del cliente."},
    {"name": "payments", "description": "Pagos y preferencias de checkout."},
    {"name": "notifications", "description": "Centro de notificaciones en tiempo real."},
    {"name": "product-questions", "description": "Preguntas y respuestas sobre productos."},
    {"name": "engagement", "description": "Registro de eventos y metricas de interaccion."},
    {"name": "exposure", "description": "Motor de exposicion equilibrada de productos."},
    {"name": "promotions", "description": "Promociones dinamicas."},
    {"name": "loyalty", "description": "Sistema de fidelizacion."},
    {"name": "wishes", "description": "Lista de deseos y alertas de promociones."},
    {"name": "analytics", "description": "Paneles y metricas administrativas."},
    {"name": "cart", "description": "Carritos de compra para usuarios e invitados."},
    {"name": "reports", "description": "Metricas y reportes de negocio."},
]

setup_logging() # Configura el logging globalmente

# --- Gestor de Ciclo de Vida (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("app.lifespan")
    logger.info("Startup: preparando inicializacionesa")
    try:
        await create_initial_admin_user()
    except Exception as e:
        logger.exception("Error inicializando admin en startup: %s", e)
    finally:
        logger.info("Startup: finalizado.")
    yield
    logger.info("Shutdown: limpieza finalizada.")



# Crear la instancia de la aplicacion FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "API de E-Commerce modular y escalable.\n\n"
        "- **Auth**: Login, refresh tokens y verificacion de email.\n"
        "- **Users**: Gestion de perfiles de usuario.\n"
        "- **Products**: CatAlogo completo con variantes, imAgenes y filtros.\n"
        "- **Purchases**: Ciclo de abastecimiento con proveedores y Ordenes de compra.\n"
        "- **Reports**: Metricas de negocio basadas en el historial de ventas.\n\n"
        "Usa el boton **Authorize** para probar los endpoints protegidos."
    ),
    openapi_tags=TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "tryItOutEnabled": True,
    },
    lifespan=lifespan  # <-- Asignar el lifespan a la app
)

# Registrar manejadores de excepciones personalizados
register_exception_handlers(app)

# --- Middlewares ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ajustar en produccion para mayor seguridad
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PayloadLimitMiddleware) # Limita tamaAo del payload
app.add_middleware(ObservabilityMiddleware) # AAade metricas y tracing
app.add_middleware(SecurityHeadersMiddleware) # AAade cabeceras de seguridad

# --- Routers ---
# Incluir todos los routers de los diferentes modulos de la API
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(users.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)
app.include_router(admin_promotions.router, prefix=settings.API_V1_STR)
app.include_router(categories.router, prefix=settings.API_V1_STR)
app.include_router(categories.admin_router, prefix=settings.API_V1_STR)
app.include_router(brands.router, prefix=settings.API_V1_STR)
app.include_router(engagement.router, prefix=settings.API_V1_STR)
app.include_router(exposure.router, prefix=settings.API_V1_STR)
app.include_router(cart.router, prefix=settings.API_V1_STR)
app.include_router(products.router, prefix=settings.API_V1_STR)
app.include_router(variants.router, prefix=settings.API_V1_STR)
app.include_router(product_questions.router, prefix=settings.API_V1_STR)
app.include_router(admin_product_questions.router, prefix=settings.API_V1_STR)
app.include_router(promotions.router, prefix=settings.API_V1_STR)
app.include_router(payments.router, prefix=settings.API_V1_STR)
app.include_router(loyalty.router, prefix=settings.API_V1_STR)
app.include_router(purchases.router, prefix=settings.API_V1_STR)
app.include_router(orders.router, prefix=settings.API_V1_STR)
app.include_router(scoring.router, prefix=settings.API_V1_STR)
app.include_router(notifications.router, prefix=settings.API_V1_STR)
app.include_router(ws_notifications.router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix=settings.API_V1_STR)
app.include_router(reports.router, prefix=settings.API_V1_STR)
app.include_router(wishes.router, prefix=settings.API_V1_STR)


# --- Configuracion personalizada de OpenAPI ---
# (Se usa para anadir logo, configurar autenticacion Bearer por defecto, etc.)
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=TAGS_METADATA,
    )

    openapi_schema["info"]["x-logo"] = {
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
    }

    # Configuracion del esquema de seguridad Bearer JWT
    comps = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    comps["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Pega tu access token aquA. Formato: `Bearer <token>`",
    }
    
    # Define que los endpoints usarAn BearerAuth por defecto
    openapi_schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi  # Aplica la configuracion personalizada


# --- Endpoints raiz y de metricas ---
@app.get("/", include_in_schema=False)
def root():
    """Endpoint raiz para verificar el estado."""
    return {"status": "ok", "docs_url": "/docs", "redoc_url": "/redoc"}


@app.get("/health/live", tags=["health"])
async def liveness():
    """Report that the API process is running without probing dependencies."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
async def readiness():
    """Report readiness based on the required database dependency."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return Response(
            content='{"status":"not_ready","database":"unavailable"}',
            status_code=503,
            media_type="application/json",
        )
    return {"status": "ready", "database": "available"}

@app.websocket(f"{settings.API_V1_STR}/_ws_echo")
async def ws_echo(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"ok": True})
    await websocket.close(code=1000, reason="ok")


@app.get("/metrics", include_in_schema=False)
def metrics(_: None = Depends(get_current_admin)) -> Response:
    """Endpoint para exportar metricas de Prometheus (protegido por admin)."""
    payload, content_type = export_metrics()
    return Response(content=payload, media_type=content_type)



