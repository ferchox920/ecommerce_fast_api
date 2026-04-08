# Relevamiento de avance del ecommerce

Fecha de relevamiento: 2026-04-07

## Estado general

El proyecto ya se encuentra en una etapa funcional intermedia/avanzada como backend de ecommerce. No es un esqueleto inicial: tiene modelos, routers, servicios, migraciones y una suite de pruebas amplia. El alcance actual cubre catalogo, inventario, carrito, ordenes, pagos, abastecimiento, promociones, fidelizacion, notificaciones, preguntas sobre productos, analiticas y reportes.

La base del producto esta operativa a nivel backend. El principal gap actual ya no esta en la consistencia funcional del core sino en la actualizacion de documentacion general y en la limpieza tecnica de archivos auxiliares.

## Evidencia relevada

- Estructura modular en `app/api`, `app/services`, `app/models`, `app/schemas`, `app/tasks` y `migrations/versions`.
- Rutas montadas en `app/main.py` para auth, users, catalogo, cart, orders, payments, purchases, promotions, loyalty, engagement, exposure, notifications, analytics, reports y wishes.
- Migraciones especificas para catalogo, inventario, carrito, ordenes, pagos, preguntas/notificaciones, wish module, rate-view system y hardening de pagos.
- Suite automatizada ejecutada con `.\.venv\Scripts\python.exe -m pytest -q`.

Resultado actual de pruebas:

- 70 tests aprobados.
- 0 tests fallidos.

## Alcance implementado

### 1. Catalogo y administracion de productos

Estado: implementado y probado.

Incluye:

- CRUD de productos.
- Variantes por producto.
- Imagenes por producto y seleccion de imagen principal.
- Marcas y categorias.
- Filtros publicos por busqueda, categoria, marca y rango de precio.
- Evaluacion de calidad de producto.

Evidencia:

- Routers: `products.py`, `brands.py`, `categories.py`, `variants.py`.
- Tests: `test_products.py`, `test_products_list.py`, `test_brands.py`, `test_categories.py`, `test_variants.py`, `test_images.py`, `test_quality.py`.

### 2. Inventario y reposicion

Estado: implementado y probado.

Incluye:

- Movimientos de stock: `receive`, `reserve`, `release`, `sale`, `adjust`.
- Consulta de historial de movimientos.
- Alertas de reposicion.
- Sugerencias de reabastecimiento.
- Integracion con ordenes de compra para recepcion de mercaderia.

Evidencia:

- Servicios de inventario y endpoints bajo productos y compras.
- Tests: `test_inventory.py`, `test_inventory_service.py`, `test_replenishment.py`.

### 3. Carrito

Estado: implementado y probado.

Incluye:

- Carrito para usuario autenticado.
- Carrito anonimo con `guest_token`.
- Alta, modificacion y baja de items.
- Conversion de carrito a orden.

Evidencia:

- Router `cart.py`.
- Test `test_cart.py`.
- Flujo validado tambien desde `test_orders.py` con `POST /orders/from-cart`.

### 4. Ordenes

Estado: implementado y probado.

Incluye:

- Creacion de orden manual.
- Creacion de orden desde carrito.
- Alta de lineas sobre una orden.
- Pago logico de la orden.
- Cancelacion.
- Fulfillment con shipment.
- Listado y consulta de ordenes.
- Reserva y liberacion de stock segun estado de la orden.
- Notificaciones asociadas al ciclo de vida de la orden.

Observacion importante:

- El codigo actual impide que un usuario admin cree ordenes de cliente o pagos de cliente.
- La suite ya refleja esa regla usando usuario cliente para checkout y admin solo para operaciones administrativas u operativas.

Evidencia:

- Router `orders.py`.
- Servicio `order_service.py`.
- Tests: `test_orders.py`.

### 5. Pagos

Estado: implementado y endurecido.

Incluye:

- Creacion de preferencia de pago para Mercado Pago.
- Soporte de idempotencia en creacion de preferencia.
- Persistencia de `Payment`.
- Webhook de Mercado Pago.
- Validacion de firma del webhook.
- Dedupe de webhook para evitar reprocesamiento.
- Actualizacion del estado de pago y propagacion al estado de la orden.
- Refund administrativo sobre pagos aprobados.
- Refund parcial por monto.
- Reintegro de stock y actualizacion de orden/pago en refund total.
- Auditoria de pagos con refunds persistidos y eventos webhook asociados.

Limitaciones actuales:

- La integracion sigue enfocada en Checkout Pro / preferencia y webhook.
- No se observa soporte de captura parcial.
- Sigue sin existir conciliacion contable avanzada contra liquidaciones del proveedor.

Evidencia:

- Router `payments.py`.
- Servicio `payment_service.py`.
- Adaptador `payment_providers/mercado_pago.py`.
- Migracion `b7c3d9e4f1a2_payment_hardening.py`.
- Migracion `c4d5e6f7a8b9_payment_refund_audit.py`.
- Tests: `test_payments.py`.

### 6. Compras y abastecimiento

Estado: implementado y probado.

Incluye:

- Alta y listado de proveedores.
- Ordenes de compra.
- Agregado de lineas.
- Cambio de estado: `place`, `receive`, `cancel`.
- Generacion de OC desde sugerencias de reposicion.

Evidencia:

- Router `purchases.py`.
- Tests: `test_purchases.py`, `test_replenishment.py`.

### 7. Promociones

Estado: implementado a nivel backend.

Incluye:

- CRUD administrativo.
- Activacion y desactivacion.
- Consulta publica de promociones activas.
- Evaluacion de elegibilidad.

Evidencia:

- Routers `admin_promotions.py` y `promotions.py`.
- Modelos y servicios especificos de promociones.
- Integracion con exposure y pricing/promocion en distintos servicios.

### 8. Fidelizacion

Estado: implementado a nivel backend.

Incluye:

- Perfil de loyalty.
- Ajustes administrativos.
- Redencion de puntos.
- Consulta de niveles.

Evidencia:

- Router `loyalty.py`.
- Modelos `loyalty.py`.
- Servicio `loyalty_service.py`.

### 9. Engagement, scoring y exposure

Estado: implementado con observabilidad basica.

Incluye:

- Ingesta de eventos.
- Consulta por producto y por cliente.
- Ranking de productos.
- Exposure mix con cache y persistencia de slots.
- Reglas de popularidad, stock, cold boost y caps por categoria.
- Metricas basicas de exposure para requests, latencia, cache hit/miss e items servidos.

Observaciones:

- Sigue abierto el bloque de experimentacion A/B y observabilidad mas fina.

Evidencia:

- Routers `engagement.py`, `exposure.py`, `scoring.py`.
- Servicios `engagement_service.py`, `exposure_service.py`, `scoring_service.py`.
- Test `test_rate_view.py`.

### 10. Notificaciones y preguntas de producto

Estado: implementado y probado.

Incluye:

- Bandeja de notificaciones.
- Marcado de lectura.
- WebSocket autenticado para notificaciones.
- Preguntas sobre productos.
- Respuesta administrativa.
- Moderacion de visibilidad y bloqueo.

Evidencia:

- Routers `notifications.py`, `product_questions.py`, `admin_product_questions.py`.
- WebSocket `api/ws/notifications.py`.
- Tests: `test_notifications.py`, `test_product_questions.py`, `test_questions_notifications.py`.

### 11. Reportes y analiticas

Estado: implementado.

Incluye:

- Overview y dashboard administrativo.
- Reportes de ventas.
- Valor de inventario.
- Analisis de costos de compra.
- Rotacion de inventario.
- Soporte para ejecucion directa o via Celery.

Evidencia:

- Routers `analytics.py` y `reports.py`.
- Servicios `analytics_service.py` y `report_service.py`.
- Tests: `test_reports.py`.

### 12. Seguridad, auth y permisos

Estado: implementado y probado.

Incluye:

- Login y tokens.
- Scopes por dominio.
- Middlewares de observabilidad, payload limit y headers de seguridad.
- Validaciones de permisos en endpoints sensibles.

Evidencia:

- Tests: `test_auth.py`, `test_security_roles.py`, `test_security_granular.py`.

## Observaciones principales

### 1. Regla de negocio de checkout cerrada

El backend bloquea el checkout hecho por admins:

- `orders.py` rechaza creacion de orden por admin.
- `payments.py` rechaza creacion de pago por admin.

Conclusion:

- La regla de negocio queda confirmada: el admin no compra.
- La suite ya mantiene esa restriccion usando usuario cliente para checkout/pagos y admin solo para tareas operativas o administrativas.

### 2. Documentacion funcional alineada

El `README.md` ya fue actualizado para reflejar el estado real del backend, incluyendo pagos endurecidos, auditoria, exposure operativo y endpoints vigentes.

### 3. Integraciones externas en consolidacion

Las integraciones con terceros existen y ya muestran una primera capa de endurecimiento:

- Mercado Pago con webhook firmado, dedupe, idempotencia, refund parcial y auditoria.
- Cloudinary.
- Email delivery.
- Redis opcional para cache.
- Celery para tareas/reportes.

Esto no invalida el proyecto, pero indica que parte del alcance esta listo para evolucionar a entorno productivo, no necesariamente endurecido para produccion completa.

### 4. Arbol tecnico limpio

Los archivos `.bak` detectados en `app/services` y `app/tasks` ya fueron removidos para limpiar el arbol del proyecto.

## Evaluacion del estado del ecommerce

Clasificacion propuesta del backend:

- Backend ecommerce funcional.
- Cobertura amplia de modulos core.
- Nivel de madurez: alto para entorno de desarrollo e integracion.
- Nivel de madurez productiva: medio, por consolidar integraciones externas, conciliacion operativa y observabilidad avanzada.

## Siguientes pasos sugeridos

1. Consolidar un documento de alcance funcional versionado por modulo y estado.
2. Evaluar conciliacion operativa avanzada para pagos.
3. Profundizar observabilidad y A/B en exposure.
