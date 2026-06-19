# Documento 04 — Diccionario de Datos
## PayNova S.A. — Catálogo Completo del Esquema de Datos

**Versión:** 1.0  
**Motor:** PostgreSQL 13+  
**Schemas:** `produccion`, `transacciones`  
**Referencias cruzadas:** `03_business_conceptual_model.md`, `06_metrics_catalog.md`, `10_agent_knowledge_base.md`

---

## SCHEMA: `produccion`

---

### Tabla: `produccion.usuarios`

**Propósito:** Tabla maestra de clientes registrados en la plataforma. Contiene el perfil, estado del ciclo de vida y scores analíticos de cada usuario.  
**Fuente de datos:** IBM Financial Transaction Dataset, columna `[User]`  
**Registros estimados:** ~2,000 usuarios únicos  
**Frecuencia de actualización:** Tiempo real (inserciones) + batch nocturno (scores)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `usuario_id` | UUID | NO | PK | Identificador interno único generado automáticamente |
| `customer_id_origen` | BIGINT | NO | UNIQUE | ID numérico original del dataset IBM. Mapea a `[User]` |
| `fecha_registro` | DATE | SÍ | — | Fecha de la primera transacción del usuario (MIN de `fecha_transaccion`) |
| `estado` | VARCHAR(20) | NO | — | Estado del ciclo de vida: `activo`, `inactivo`, `suspendido`, `bloqueado` |
| `tipo_usuario` | VARCHAR(30) | NO | — | Clasificación: `individual`, `empresarial`, `premium`, `basico` |
| `nivel_riesgo` | VARCHAR(20) | NO | — | Clasificación de riesgo: `bajo`, `medio`, `alto`, `critico` |
| `pais` | CHAR(3) | SÍ | — | País de operación. Valor: `USA` para el dataset IBM |
| `ciudad` | VARCHAR(100) | SÍ | — | Ciudad más frecuente de transacción del usuario |
| `score_actividad` | NUMERIC(5,2) | SÍ | — | Score 0–100. Fórmula: `LN(1 + count_tx) / max_log * 100`. Refleja frecuencia transaccional |
| `score_rentabilidad` | NUMERIC(5,2) | SÍ | — | Score 0–100. Fórmula: `SUM(monto) / MAX(SUM(monto)) * 100`. Refleja volumen monetario |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación del registro |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de última actualización (via trigger) |

**Índices:** `estado`, `nivel_riesgo`, `(score_actividad DESC, score_rentabilidad DESC)`, `(pais, ciudad)`

**Ejemplo de consulta:** Usuarios activos con alto nivel de riesgo
```sql
SELECT usuario_id, ciudad, score_actividad, score_rentabilidad
FROM produccion.usuarios
WHERE estado = 'activo' AND nivel_riesgo IN ('alto', 'critico')
ORDER BY score_rentabilidad DESC;
```

---

### Tabla: `produccion.dispositivos`

**Propósito:** Registro de dispositivos móviles y web asociados a cada usuario. Datos sintéticos (IBM no provee esta información).  
**Registros estimados:** ~3,000–4,000 (puede haber múltiples por usuario)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `dispositivo_id` | UUID | NO | PK | Identificador único del dispositivo |
| `usuario_id` | UUID | NO | FK → usuarios | Usuario propietario del dispositivo |
| `device_type` | VARCHAR(50) | SÍ | — | Tipo: `mobile` (65%), `tablet` (20%), `desktop` (15%) |
| `sistema_operativo` | VARCHAR(50) | SÍ | — | OS: `iOS`, `Android`, `Web` |
| `version_app` | VARCHAR(20) | SÍ | — | Versión de la aplicación instalada |
| `fecha_primer_uso` | DATE | SÍ | — | Primera vez que el dispositivo fue usado (MIN fecha_tx) |
| `fecha_ultimo_uso` | DATE | SÍ | — | Último uso registrado del dispositivo |
| `estado_dispositivo` | VARCHAR(20) | NO | — | `activo`, `inactivo`, `bloqueado`, `eliminado` |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |

---

### Tabla: `produccion.merchants`

**Propósito:** Tabla maestra de comercios afiliados. Contiene información de identificación, categorización MCC, estado operacional y datos geográficos.  
**Fuente de datos:** IBM Financial Transaction Dataset, columnas `[Merchant Name]`, `[Merchant City]`, `[Merchant State]`, `[MCC]`  
**Registros estimados:** ~3,000 comercios únicos

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `merchant_id` | UUID | NO | PK | Identificador interno único |
| `merchant_id_origen` | BIGINT | SÍ | UNIQUE | ID numérico del dataset IBM |
| `nombre_comercio` | VARCHAR(255) | SÍ | — | Nombre del comercio (texto del dataset IBM) |
| `categoria` | VARCHAR(100) | SÍ | — | Categoría humana derivada del MCC (ej: "Supermercados") |
| `mcc_code` | SMALLINT | SÍ | — | Merchant Category Code (ISO 18245). Ej: 5411 = Supermercados |
| `segmento` | VARCHAR(100) | SÍ | — | Segmento de industria derivado del rango MCC |
| `ciudad` | VARCHAR(100) | SÍ | — | Ciudad del comercio (IBM: `[Merchant City]`) |
| `estado_region` | VARCHAR(10) | SÍ | — | Estado/provincia del comercio (IBM: `[Merchant State]`) |
| `zip_code` | VARCHAR(10) | SÍ | — | Código postal (IBM: `[Zip]`) |
| `pais` | CHAR(3) | NO | — | País. Valor: `USA` |
| `fecha_afiliacion` | DATE | SÍ | — | Fecha de incorporación a la plataforma |
| `estado` | VARCHAR(20) | NO | — | Estado legal: `activo`, `inactivo`, `suspendido` |
| `cuenta_tipo` | VARCHAR(50) | SÍ | — | Tipo de cuenta comercial: `individual`, `pyme`, `empresa` |
| `status_operacional` | VARCHAR(20) | SÍ | — | Estado operativo: `activo`, `inactivo`, `suspendido` |
| `ultima_actividad` | DATE | SÍ | — | Fecha de la última transacción procesada |
| `coordinador_id` | UUID | SÍ | FK → account_managers | Account Manager asignado al comercio |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de última actualización |

**Índices:** `mcc_code`, `categoria`, `(ciudad, pais)`, `nombre_comercio` (GIN trigram para búsqueda de texto)

**MCC Codes principales modelados:**

| MCC | Categoría | Segmento |
|-----|-----------|---------|
| 5411 | Supermercados | Retail |
| 5812 | Restaurantes | Gastronomía |
| 5912 | Farmacias | Salud |
| 5541 | Gasolineras | Combustible |
| 5699 | Ropa y Accesorios | Retail |
| 5732 | Electrónica | Retail |
| 7011 | Hoteles | Servicios |
| 4511 | Aerolíneas | Servicios |
| 8220 | Educación | Servicios |

---

### Tabla: `produccion.segmentacion_merchants`

**Propósito:** Clasificación estratégica multidimensional de comercios. Se recalcula periódicamente por el proceso ETL de segmentación.  
**Registros:** ~3,000 (1 por comercio activo)  
**Frecuencia de actualización:** Mensual

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `segmentacion_id` | UUID | NO | PK | Identificador del registro |
| `merchant_id` | UUID | NO | FK → merchants | Comercio segmentado (relación 1:1) |
| `segmento_volumen` | VARCHAR(50) | NO | — | Por GMV mensual: `micro`, `pequeno`, `mediano`, `grande`, `mega` |
| `segmento_rentabilidad` | VARCHAR(50) | NO | — | Por MDR mensual: `bronze`, `silver`, `gold`, `platinum`, `diamond` |
| `segmento_riesgo` | VARCHAR(50) | SÍ | — | Por tasa de rechazo/fraude: `bajo`, `medio`, `alto`, `critico` |
| `mdr_promedio` | NUMERIC(6,4) | SÍ | — | MDR promedio histórico del comercio |
| `valor_promedio_tx` | NUMERIC(15,2) | SÍ | — | Ticket promedio histórico de transacciones |
| `volumen_anual_estimado` | NUMERIC(18,2) | SÍ | — | Proyección de GMV anual |
| `tasa_rechazo_promedio` | NUMERIC(5,2) | SÍ | — | % histórico de transacciones rechazadas |
| `estado_riesgo` | VARCHAR(20) | SÍ | — | `normal`, `monitoreado`, `alerta`, `suspendido` |
| `fecha_segmentacion` | DATE | NO | — | Fecha de la última segmentación |
| `proxima_revision` | DATE | SÍ | — | Fecha programada para recálculo |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de actualización |

---

### Tabla: `produccion.account_managers`

**Propósito:** Registro de los gestores comerciales (coordinadores) que acompañan el desarrollo de los comercios afiliados.  
**Registros:** 20 gestores activos

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `manager_id` | UUID | NO | PK | Identificador único del gestor |
| `nombre` | VARCHAR(255) | NO | — | Nombre completo del Account Manager |
| `email` | VARCHAR(255) | NO | UNIQUE | Email corporativo |
| `telefono` | VARCHAR(20) | SÍ | — | Teléfono de contacto |
| `estado` | VARCHAR(20) | NO | — | `activo`, `inactivo`, `suspendido` |
| `region` | VARCHAR(100) | SÍ | — | Región geográfica de responsabilidad |
| `fecha_contratacion` | DATE | SÍ | — | Fecha de ingreso a la empresa |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de actualización |

---

### Tabla: `produccion.integraciones_merchant`

**Propósito:** Estado detallado del proceso de onboarding e integración técnica de cada comercio. Es la fuente de verdad del funnel de comercios.  
**Registros:** ~3,000 (1:1 con merchants)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `integracion_id` | UUID | NO | PK | Identificador único |
| `merchant_id` | UUID | NO | FK → merchants (UNIQUE) | Comercio asociado |
| `estado_integracion` | VARCHAR(20) | NO | — | `no_iniciada`, `en_curso`, `activa`, `pausada`, `suspendida` |
| `email_integrado` | BOOLEAN | SÍ | — | Si el canal de email está activo para este comercio |
| `sms_integrado` | BOOLEAN | SÍ | — | Si el canal SMS está activo |
| `webhook_integrado` | BOOLEAN | SÍ | — | Si el webhook está configurado y activo |
| `api_key_validado` | BOOLEAN | SÍ | — | Si la API key fue validada exitosamente |
| `fecha_inicio` | DATE | NO | — | Fecha de inicio del proceso de onboarding |
| `fecha_completacion` | DATE | SÍ | — | Fecha en que la integración quedó completamente activa |
| `coordinador_id` | UUID | SÍ | FK → account_managers | Gestor que acompañó el onboarding |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de actualización |

**Campo derivado útil:** `TieneNotificacion = (email_integrado = TRUE OR sms_integrado = TRUE)`

---

### Tabla: `produccion.payouts`

**Propósito:** Registro histórico de todos los desembolsos realizados a comercios. Es la fuente de verdad de las liquidaciones.  
**Registros:** ~18,000 (~6 payouts promedio por comercio)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `payout_id` | UUID | NO | PK | Identificador único del desembolso |
| `merchant_id` | UUID | NO | FK → merchants | Comercio beneficiario |
| `monto` | NUMERIC(15,2) | NO | — | Monto bruto del desembolso (> 0) |
| `comision_payout` | NUMERIC(12,4) | NO | — | Comisión cobrada sobre el payout (varía por segmento) |
| `monto_neto` | NUMERIC(15,2) | GENERATED | — | `monto - comision_payout`. Calculado automáticamente |
| `estado` | VARCHAR(20) | NO | — | `pendiente`, `procesado`, `fallido`, `rechazado`, `revertido`, `pendiente_revision` |
| `razon_rechazo` | VARCHAR(255) | SÍ | — | Motivo si el estado es `rechazado` o `fallido` |
| `metodo_pago` | VARCHAR(50) | SÍ | — | `transferencia_bancaria`, `cheque`, `efectivo`, `otro` |
| `numero_referencia` | VARCHAR(100) | SÍ | — | Código de referencia bancaria |
| `fecha_solicitud` | TIMESTAMPTZ | NO | — | Cuando se generó el payout en el sistema |
| `fecha_payout` | TIMESTAMPTZ | SÍ | — | Cuando se ejecutó el desembolso |
| `fecha_confirmacion` | TIMESTAMPTZ | SÍ | — | Cuando se confirmó la recepción |
| `periodo_desde` | DATE | SÍ | — | Inicio del período de liquidación |
| `periodo_hasta` | DATE | SÍ | — | Fin del período de liquidación |
| `notas` | TEXT | SÍ | — | Notas operativas adicionales |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de actualización |

**Índices:** `merchant_id`, `estado`, `fecha_payout DESC`, `(merchant_id, fecha_payout DESC)`

---

### Tabla: `produccion.notificaciones`

**Propósito:** Registro de todas las comunicaciones enviadas a comercios a través de todos los canales. Permite análisis de costos y engagement.  
**Registros:** ~96,000 (~32 notificaciones promedio por comercio)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `notificacion_id` | UUID | NO | PK | Identificador único |
| `merchant_id` | UUID | NO | FK → merchants | Comercio destinatario |
| `tipo_canal` | VARCHAR(20) | NO | — | `email`, `sms`, `push`, `webhook`, `whatsapp` |
| `destinatario` | VARCHAR(255) | NO | — | Email, número de teléfono o endpoint |
| `asunto_titulo` | VARCHAR(255) | SÍ | — | Asunto del email o título de la notificación |
| `cantidad_enviada` | BIGINT | NO | — | Número de mensajes en el lote (> 0) |
| `costo_unitario` | NUMERIC(8,4) | NO | — | Costo por mensaje en USD |
| `costo_total` | NUMERIC(12,4) | GENERATED | — | `cantidad_enviada * costo_unitario`. Calculado automáticamente |
| `estado` | VARCHAR(20) | NO | — | `enviada`, `entregada`, `fallida`, `rebotada`, `spam`, `no_entregada` |
| `motivo_fallo` | VARCHAR(255) | SÍ | — | Razón si el estado es `fallida` |
| `tasa_apertura` | NUMERIC(5,2) | SÍ | — | % de apertura (aplica principalmente a email) |
| `tasa_click` | NUMERIC(5,2) | SÍ | — | % de click (aplica a email con links) |
| `fecha_envio` | TIMESTAMPTZ | NO | — | Timestamp del envío |
| `fecha_entrega` | TIMESTAMPTZ | SÍ | — | Timestamp de confirmación de entrega |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación del registro |

**Costos de referencia por canal:**

| Canal | Costo unitario estimado |
|-------|------------------------|
| `email` | $0.001 |
| `sms` | $0.050 |
| `push` | $0.0001 |
| `whatsapp` | $0.030 |
| `webhook` | $0.0005 |

---

### Tabla: `produccion.fraude`

**Propósito:** Registro de alertas de fraude generadas por el sistema de detección. Cada registro está vinculado a una transacción específica.  
**Fuente:** IBM `[Is Fraud?]` para carga inicial. Modelo ML propio para alertas en tiempo real.  
**Registros:** ~600,000 (aprox. 2.5% de transacciones)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `fraude_id` | UUID | NO | PK | Identificador único de la alerta |
| `transaccion_id` | UUID | NO | FK → transacciones | Transacción que originó la alerta |
| `fecha_transaccion` | TIMESTAMPTZ | NO | FK (compuesta) | Necesario por el particionamiento de la tabla de transacciones |
| `flag_fraude` | BOOLEAN | NO | — | `TRUE` = fraude confirmado (IBM: `Yes`), `FALSE` = legítima |
| `tipo_alerta` | VARCHAR(50) | SÍ | — | Categoría del patrón detectado |
| `score_fraude` | NUMERIC(6,4) | SÍ | — | Probabilidad de fraude 0–1 asignada por el modelo |
| `modelo_detector` | VARCHAR(100) | SÍ | — | Identificador del modelo que generó la alerta |
| `fecha_deteccion` | TIMESTAMPTZ | SÍ | — | Timestamp de la detección |
| `estado_revision` | VARCHAR(30) | NO | — | `pendiente`, `en_revision`, `confirmado`, `descartado`, `escalado` |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | NO | — | Timestamp de actualización |

**Tipos de alerta:**

| Tipo | Descripción |
|------|-------------|
| `monto_inusual` | Monto muy superior al ticket promedio histórico del usuario |
| `ubicacion_anomala` | Transacción en ubicación geográfica no habitual |
| `frecuencia_alta` | Múltiples transacciones en ventana corta de tiempo |
| `patron_sospechoso` | Secuencia de montos que sugiere prueba de tarjeta robada |
| `tarjeta_clonada` | Uso simultáneo de la misma tarjeta en ubicaciones distintas |
| `identidad_robada` | Cambio abrupto de patrón comportamental del usuario |

---

### Tabla: `produccion.segmentacion`

**Propósito:** Clasificación multidimensional de usuarios. Se actualiza periódicamente por modelos ML (K-Means) y reglas ETL.

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `segmentacion_id` | UUID | NO | PK | Identificador único |
| `usuario_id` | UUID | NO | FK → usuarios | Usuario segmentado |
| `segmento_transaccional` | VARCHAR(50) | SÍ | — | `alto_volumen`, `frecuente`, `esporadico`, `inactivo` |
| `segmento_rentabilidad` | VARCHAR(50) | SÍ | — | `platinum`, `gold`, `silver`, `bronze` |
| `segmento_riesgo` | VARCHAR(50) | SÍ | — | `critico`, `alto`, `medio`, `bajo` |
| `cluster_ml` | SMALLINT | SÍ | — | Número de cluster asignado por K-Means. NULL hasta ejecución |
| `fecha_segmentacion` | DATE | NO | — | Fecha del último cálculo de segmentación |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de creación |

---

## SCHEMA: `transacciones`

---

### Tabla: `transacciones.transacciones`

**Propósito:** Tabla central de hechos. Contiene cada transacción individual procesada por la plataforma. Es la tabla más grande y crítica del sistema.  
**Fuente:** IBM Financial Transaction Dataset (~24 millones de filas)  
**Arquitectura:** Tabla única (reemplaza el esquema particionado anual de `produccion`)

| Columna | Tipo | Nulo | PK/FK | Descripción |
|---------|------|------|-------|-------------|
| `transaccion_id` | UUID | NO | PK | Identificador único generado |
| `transaction_id_origen` | BIGINT | SÍ | — | Índice 0-based de la fila original en el CSV IBM |
| `year_month` | VARCHAR(7) | NO | — | Formato `YYYY-MM`. Generado en ETL desde `fecha_transaccion`. Permite agrupación eficiente |
| `usuario_origen_id` | UUID | NO | FK → usuarios | Usuario que realizó el pago |
| `usuario_destino_id` | UUID | SÍ | FK → usuarios | Solo para transferencias entre usuarios. NULL en compras |
| `merchant_id` | UUID | SÍ | FK → merchants | Comercio receptor del pago. NULL en retiros/transferencias |
| `tarjeta_id` | UUID | SÍ | FK → tarjetas | Tarjeta usada. NULL si es transferencia directa |
| `fecha_transaccion` | TIMESTAMPTZ | NO | — | Timestamp completo de la transacción (IBM: Year+Month+Day+Time) |
| `tipo_transaccion` | VARCHAR(50) | NO | — | `compra`, `retiro`, `transferencia`, `pago_servicio`, `recarga`, `devolucion`, `ajuste`, `otro` |
| `subtipo_transaccion` | VARCHAR(100) | SÍ | — | Subcategoría más detallada derivada del MCC |
| `monto` | NUMERIC(15,2) | NO | — | Monto de la transacción en USD. Diferente de cero. Negativo para devoluciones |
| `moneda` | CHAR(3) | NO | — | ISO 4217. Valor: `USD` |
| `canal` | VARCHAR(30) | SÍ | — | `chip`, `banda_magnetica`, `online`, `nfc`, `atm`, `transferencia`, `otro` |
| `estado` | VARCHAR(20) | NO | — | `completada`, `pendiente`, `rechazada`, `revertida`, `error` |
| `costo_operativo` | NUMERIC(12,4) | NO | — | **0.8% del monto**. Costo de procesamiento por transacción |
| `ingreso_comision` | NUMERIC(12,4) | NO | — | **1.8% del monto**. MDR cobrado al comercio |
| `margen` | NUMERIC(12,4) | GENERATED | — | `ingreso_comision - costo_operativo` = **1.0% del monto**. Columna calculada automáticamente |
| `riesgo_score` | NUMERIC(6,4) | SÍ | — | Probabilidad de fraude 0–1. IBM: 0.95 si `Is Fraud?=Yes`, 0.05 si No |
| `hora_transaccion` | SMALLINT | SÍ | — | Hora del día (0–23). `EXTRACT(HOUR FROM fecha_transaccion)` |
| `dia_semana` | SMALLINT | SÍ | — | Día de la semana (0=Domingo, 6=Sábado). `EXTRACT(DOW)` |
| `mes` | INT | SÍ | — | Mes del año (1–12). `EXTRACT(MONTH)` |
| `razon_rechazo` | VARCHAR(100) | SÍ | — | Motivo del rechazo si `estado = 'rechazada'` |
| `created_at` | TIMESTAMPTZ | NO | — | Timestamp de inserción en la BD |

**Índices:**
- `year_month` — agrupación mensual eficiente
- `fecha_transaccion DESC` — consultas recientes
- `usuario_origen_id` — historial por usuario
- `merchant_id` — historial por comercio
- `tarjeta_id` — historial por tarjeta
- `estado` — filtrado por estado
- `tipo_transaccion` — filtrado por tipo
- `monto` — filtros por rango monetario
- `riesgo_score DESC WHERE riesgo_score > 0.5` — alertas de riesgo
- `hora_transaccion` — heatmap por hora
- `dia_semana` — heatmap por día

**Reglas de negocio embebidas:**
- `monto <> 0`: No se permiten transacciones de monto cero
- `costo_operativo >= 0`: Siempre positivo
- `ingreso_comision >= 0`: Siempre positivo
- `riesgo_score BETWEEN 0 AND 1`: Score normalizado

---

## Vistas y Vistas Materializadas

### Vista: `produccion.vw_transacciones_completas`

**Propósito:** Vista enriquecida que hace JOIN de transacciones con todas las dimensiones relevantes. Útil para consultas ad-hoc sin necesidad de hacer JOINs manuales.

**Incluye columnas de:** `transacciones`, `usuarios`, `merchants`, `tarjetas`, `fraude`

```sql
-- Ejemplo de uso
SELECT nombre_comercio, merchant_categoria, SUM(monto) AS gmv
FROM produccion.vw_transacciones_completas
WHERE fecha_transaccion >= '2018-01-01'
  AND estado = 'completada'
GROUP BY nombre_comercio, merchant_categoria
ORDER BY gmv DESC;
```

---

### Vista: `produccion.vw_kpi_dashboard`

**Propósito:** KPIs principales del dashboard ejecutivo. Devuelve una sola fila con los valores agregados globales.

**Columnas:** `gmv_total`, `total_transacciones`, `total_payouts`, `mdr_total`, `ticket_promedio`, `tasa_exito_general`, `costo_notificaciones_total`, `usuarios_activos`, `merchants_activos`

---

### Vista: `produccion.vw_funnel_comercios`

**Propósito:** Conteo de comercios en cada etapa del funnel de onboarding y activación. Una fila por período analizado.

**Columnas:** `comercios_registrados`, `comercios_integrados`, `comercios_activos`, `comercios_con_notificaciones`, `comercios_con_transacciones`, `comercios_con_payouts`, `porcentaje_integracion`, `porcentaje_activos`

---

### Vista: `produccion.vw_matriz_comercios_estrategicos`

**Propósito:** Datos para el scatter/bubble chart de la matriz estratégica. Un registro por comercio con métricas de rentabilidad, volumen y costos.

**Columnas:** `merchant_id`, `nombre_comercio`, `categoria`, `gmv_total`, `total_transacciones`, `rentabilidad_promedio`, `costo_notificaciones_total`, `segmento_rentabilidad`, `segmento_volumen`

---

### Vista: `produccion.vw_waterfall_rentabilidad`

**Propósito:** Desglose diario de GMV, ingresos, costos y margen neto para el gráfico de cascada de rentabilidad.

**Columnas:** `fecha`, `gmv`, `mdr`, `costo_notificaciones`, `otros_costos`, `margen_neto`

---

### Vista Materializada: `produccion.mv_metricas_diarias`

**Propósito:** Pre-cálculo de KPIs por merchant y por día. Optimiza el rendimiento del dashboard evitando queries pesadas sobre la tabla de transacciones.  
**Frecuencia de refresh:** Nocturna (batch)  
**Registros:** ~90,000 filas

**Columnas:** `fecha`, `merchant_id`, `nombre_comercio`, `total_transacciones`, `transacciones_completadas`, `transacciones_rechazadas`, `gmv`, `mdr`, `costos_operativos`, `margen_neto`, `ticket_promedio`, `transacciones_fraude`, `tasa_exito`

**Ejemplo de consulta:**
```sql
-- Top 10 comercios por GMV en los últimos 30 días
SELECT merchant_id, nombre_comercio, SUM(gmv) AS gmv_30d
FROM produccion.mv_metricas_diarias
WHERE fecha >= CURRENT_DATE - 30
GROUP BY merchant_id, nombre_comercio
ORDER BY gmv_30d DESC
LIMIT 10;
```

---

## Resumen de Volúmenes

| Tabla / Vista | Registros estimados | Frecuencia de actualización |
|---------------|--------------------|-----------------------------|
| `transacciones.transacciones` | ~24,000,000 | Tiempo real |
| `produccion.usuarios` | ~2,000 | Tiempo real + batch |
| `produccion.merchants` | ~3,000 | Tiempo real |
| `produccion.fraude` | ~600,000 | Tiempo real |
| `produccion.payouts` | ~18,000 | Batch (diario/semanal) |
| `produccion.notificaciones` | ~96,000 | Batch |
| `produccion.integraciones_merchant` | ~3,000 | Tiempo real |
| `produccion.segmentacion_merchants` | ~3,000 | Mensual |
| `produccion.account_managers` | 20 | Manual |
| `mv_metricas_diarias` | ~90,000 | Nocturna |
