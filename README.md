## FastAPI E-Commerce Platform

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-orange)
![Alembic](https://img.shields.io/badge/Migrations-Alembic-lightgrey)
![Pytest](https://img.shields.io/badge/Tests-70%20passed-brightgreen)

Backend modular para un ecommerce construido con **FastAPI**, **SQLAlchemy 2.x** y **Alembic**. El proyecto cubre catalogo, inventario, carrito, ordenes, pagos, abastecimiento, promociones, fidelizacion, notificaciones, preguntas sobre productos, analiticas y reportes.

## Estado actual

- Suite actual: `70` tests aprobados.
- Catalogo, inventario, carrito, ordenes y compras: implementados y probados.
- Pagos con Mercado Pago: preferencia, webhook firmado, idempotencia, dedupe, refund total/parcial y auditoria.
- Exposure engine: operativo, con cache y metricas basicas de observabilidad.

## Caracteristicas principales

### Catalogo e inventario

- CRUD de productos, variantes, imagenes, marcas y categorias.
- Movimientos de stock: `receive`, `reserve`, `release`, `sale`, `adjust`.
- Alertas de reposicion y sugerencias de reabastecimiento.
- Evaluacion de calidad de producto.

### Carrito y ordenes

- Carrito para usuario autenticado y anonimo con `guest_token`.
- Conversion de carrito a orden.
- Ordenes con lineas, pagos, shipment y estados operativos.
- Regla de negocio aplicada: el admin no realiza checkout de cliente.

### Pagos

- Integracion con Mercado Pago para crear preferencias de checkout.
- Idempotencia por `Idempotency-Key` en creacion de pagos.
- Webhook con validacion de firma y deduplicacion de eventos.
- Refund administrativo total o parcial.
- Auditoria de pagos con eventos webhook y refunds persistidos.

### Promociones, loyalty y engagement

- CRUD administrativo de promociones y elegibilidad publica.
- Loyalty con perfiles, niveles, ajustes y redencion.
- Ingesta de eventos `view`, `click`, `add_to_cart`, `purchase`.
- Scoring y exposure mix con reglas de popularidad, stock y cold boost.

### Notificaciones y preguntas

- Bandeja de notificaciones.
- WebSocket autenticado.
- Preguntas sobre productos con respuesta y moderacion administrativa.

### Reportes y analiticas

- Overview administrativo.
- Dashboard operativo.
- Reportes de ventas, valor de inventario, costos de compra y rotacion.
- Ejecucion directa o via Celery.

## Arquitectura

- **FastAPI** para la capa HTTP.
- **Pydantic v2** para validacion y serializacion.
- **SQLAlchemy 2.x** con sesiones async.
- **Alembic** para migraciones.
- **PostgreSQL** como base principal.
- **SQLite** para tests locales.
- **Redis** opcional para cache del exposure engine.
- **Celery** para tareas y reportes.

Estructura principal:

- `app/api`: routers HTTP y WebSocket.
- `app/models`: modelos ORM.
- `app/schemas`: contratos de entrada/salida.
- `app/services`: logica de negocio.
- `app/tasks`: tareas Celery.
- `migrations/versions`: historial de migraciones.
- `tests`: cobertura automatizada.

## Endpoints destacados

| Dominio | Ruta / Metodo | Descripcion |
|---|---|---|
| Auth | `POST /api/v1/auth/login` | Login con JWT. |
| Productos | `GET /api/v1/products` | Listado publico con filtros. |
| Carrito | `POST /api/v1/cart/items` | Agrega item al carrito. |
| Ordenes | `POST /api/v1/orders` | Crea orden para usuario cliente. |
| Ordenes | `POST /api/v1/orders/from-cart` | Convierte carrito a orden. |
| Pagos | `POST /api/v1/payments/orders/{order_id}` | Crea preferencia de pago. |
| Pagos | `POST /api/v1/payments/mercado-pago/webhook` | Webhook del proveedor. |
| Pagos | `POST /api/v1/payments/{payment_id}/refund` | Refund administrativo total o parcial. |
| Pagos | `GET /api/v1/payments/{payment_id}/audit` | Auditoria del pago. |
| Promociones | `GET /api/v1/promotions/active` | Lista promociones activas. |
| Loyalty | `GET /api/v1/loyalty/profile` | Perfil de fidelizacion. |
| Exposure | `GET /api/v1/exposure` | Mix de productos balanceado. |
| Analytics | `GET /api/v1/admin/analytics/overview` | KPIs generales. |
| Reportes | `GET /api/v1/reports/sales` | Reporte de ventas. |

## Configuracion

Archivo base:

- `.env`
- `.env.example`

Variables relevantes:

- `DATABASE_URL`
- `ASYNC_DATABASE_URL`
- `SECRET_KEY`
- `REFRESH_SECRET_KEY`
- `MERCADO_PAGO_ACCESS_TOKEN`
- `MERCADO_PAGO_WEBHOOK_SECRET`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

## Migraciones

Ejecutar:

```bash
alembic upgrade head
```

Migraciones relevantes del dominio:

- `e1a2b3c4d5f6_orders_module`
- `f1234567890ab_cart_module`
- `0a1b2c3d4e5f_orders_payments_shipments`
- `2f6e7a8b9cde_rate_view_system`
- `b7c3d9e4f1a2_payment_hardening`
- `c4d5e6f7a8b9_payment_refund_audit`

## Pruebas

Ejecutar:

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

Estado actual:

- `70 passed`

Cobertura funcional principal:

- auth y permisos,
- productos, categorias, marcas, variantes e imagenes,
- inventario y replenishment,
- carrito,
- ordenes,
- pagos,
- preguntas y notificaciones,
- reportes,
- rate-view.

## Observabilidad

Actualmente el backend expone:

- metricas HTTP generales,
- metricas de login,
- metricas de exposure para requests, latencia, cache hit/miss e items servidos,
- endpoint `/metrics` protegido por admin.

## Limitaciones conocidas

- La integracion de pagos sigue enfocada en Mercado Pago Checkout Pro.
- No hay conciliacion contable avanzada ni captura parcial.
- Exposure ya tiene metricas basicas, pero la parte de A/B y observabilidad mas fina sigue abierta.
- El documento de avance en `docs/ecommerce_avance.md` es la referencia mas precisa del estado actual.

## Referencias internas

- Estado funcional actualizado: `docs/ecommerce_avance.md`
- Notas de OAuth frontend: `docs/oauth_google_frontend.md`
- Flujo de alta de producto: `docs/product_creation.md`
